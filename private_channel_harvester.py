import pyrogram_patch
"""
Telegram 私密/受限频道采集与无痕洗白转存引擎 (Private & Restricted Channel Harvester)
====================================================================================
支持：
1. 私密频道帖子链接 (https://t.me/c/<raw_id>/<msg_id>) 及连号区间 (100-150) 解析；
2. 公开频道帖子链接 (https://t.me/<username>/<msg_id>)、网页预览链接 (/s/)、?single 参数及连号区间解析；
3. 私密入群邀请码 (https://t.me/+<hash> / joinchat/<hash>) 自动加群；
4. 复制发布链接深度解析 (Deep Post Link Resolution)：
   - 原生基于 Telethon (MTProto Layer 227) 协议号引擎，彻底解决旧版协议 Layer 151 下
     现代媒体 (Spoiler/Blockquote/新型视频属性) 被识别为 MessageMediaUnsupported 的问题；
   - 相册/媒体组 (grouped_id) 自动关联展开：复制单条帖子链接即可自动探测并拉取同相册内的
     全部预览图与正片大视频，自动继承相册主标题配文并聚合为网盘相册文件夹；
   - 导航/跳转帖深度追踪：若目标消息为纯文本引导帖，自动提取正文、超链接实体 (TextUrl)
     及内联按钮 (InlineKeyboard) 中的嵌套帖子链接并深入采集；
5. 智能双模转存管线：
   - 模式一 (fast_copy)：未开启内容保护时，优先通过 copy_message 零流量秒传并清洗配文；
   - 模式二 (restricted_relay)：开启禁止转发 (noforwards / has_protected_content) 时，通过协议号
     底层流式下载、执行文件名去广告与配文洗白后，由频道写入客户端重新上传至 BIN_CHANNEL 并自动清理临时文件。
"""

import os
import re
import time
import math
import shutil
import asyncio
import logging
import secrets
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any, Callable, Union, Set
from urllib.parse import quote_plus

try:
    from pyrogram.file_id import FileId
except ImportError:
    FileId = None

try:
    from pyrogram.types import (
        InputMediaPhoto,
        InputMediaVideo,
        InputMediaAudio,
        InputMediaDocument,
    )
except ImportError:
    class InputMediaPhoto:
        def __init__(self, media=None, **kwargs):
            self.media = media
            for k, v in kwargs.items():
                setattr(self, k, v)
    class InputMediaVideo:
        def __init__(self, media=None, **kwargs):
            self.media = media
            for k, v in kwargs.items():
                setattr(self, k, v)
    class InputMediaAudio:
        def __init__(self, media=None, **kwargs):
            self.media = media
            for k, v in kwargs.items():
                setattr(self, k, v)
    class InputMediaDocument:
        def __init__(self, media=None, **kwargs):
            self.media = media
            for k, v in kwargs.items():
                setattr(self, k, v)

try:
    from WebStreamer.utils.custom_dl import ByteStreamer, get_available_bot_indices
except ImportError:
    ByteStreamer = None
    get_available_bot_indices = None

MULTIBOT_DOWNLOAD_THRESHOLD_BYTES = 8 * 1024 * 1024  # 8MB 阈值，大文件启用多 Bot 并发分片下载

import db
from configer import get_config_value
from session_adapter import (
    parse_session_to_pyrogram_string,
    parse_session_to_telethon_string,
)
from WebStreamer.vars import Var
from WebStreamer.utils import get_hash, get_name
from WebStreamer.utils.rebrand_cleaner import (
    clean_and_rebrand_caption,
    clean_drive_filename,
)

logger = logging.getLogger("private_harvester")

# 正则表达式定义（支持 /s/ 预览路径及 ?single / ?comment 等查询参数）
INVITE_LINK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
RAW_INVITE_HASH_RE = re.compile(r"^\+([A-Za-z0-9_-]{8,64})$")

PRIVATE_POST_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?c/(\d+)/(\d+)(?:\s*-\s*(\d+))?(?:[?#][^\s]*)?",
    re.IGNORECASE,
)

PUBLIC_POST_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?(?!c/|\+|joinchat/)([A-Za-z0-9_]{4,32})/(\d+)(?:\s*-\s*(\d+))?(?:[?#][^\s]*)?",
    re.IGNORECASE,
)

MAX_RANGE_SPAN = 200


@dataclass
class HarvestTarget:
    """单个频道的待采集目标描述"""
    chat_id: Union[int, str]
    raw_chat_id: str
    is_private: bool
    msg_ids: List[int] = field(default_factory=list)


def parse_telegram_post_links(
    text: str,
    default_invite: Optional[str] = None,
    max_range_span: int = MAX_RANGE_SPAN,
) -> Tuple[List[HarvestTarget], List[str]]:
    """
    解析输入文本中的私密/公开频道帖子链接（支持连号区间、?single 等参数）及私密频道邀请链接。

    Returns:
        (targets, invite_links)
    """
    if not text and not default_invite:
        return [], []

    invite_links: List[str] = []

    def _add_invite(inv_url: str):
        if inv_url and inv_url not in invite_links:
            invite_links.append(inv_url)

    # 1. 处理显式传入的 default_invite
    if default_invite and default_invite.strip():
        raw_inv = default_invite.strip()
        m_inv = INVITE_LINK_RE.search(raw_inv)
        if m_inv:
            _add_invite(f"https://t.me/+{m_inv.group(1)}")
        else:
            m_raw = RAW_INVITE_HASH_RE.match(raw_inv)
            if m_raw:
                _add_invite(f"https://t.me/+{m_raw.group(1)}")
            elif "t.me/" in raw_inv or "telegram.me/" in raw_inv:
                _add_invite(raw_inv)

    content = text or ""

    # 2. 提取正文中内嵌的邀请链接
    for m_inv in INVITE_LINK_RE.finditer(content):
        _add_invite(f"https://t.me/+{m_inv.group(1)}")

    targets_map: Dict[Union[int, str], HarvestTarget] = {}

    def _append_msg_ids(
        chat_key: Union[int, str],
        raw_id_str: str,
        is_priv: bool,
        start_str: str,
        end_str: Optional[str],
    ):
        start_id = int(start_str)
        end_id = int(end_str) if end_str else start_id
        if start_id <= 0 or end_id <= 0:
            return
        if start_id > end_id:
            start_id, end_id = end_id, start_id
        span = min(end_id - start_id + 1, max_range_span)
        ids = list(range(start_id, start_id + span))

        if chat_key not in targets_map:
            targets_map[chat_key] = HarvestTarget(
                chat_id=chat_key,
                raw_chat_id=raw_id_str,
                is_private=is_priv,
                msg_ids=[],
            )
        existing = set(targets_map[chat_key].msg_ids)
        for mid in ids:
            if mid not in existing:
                targets_map[chat_key].msg_ids.append(mid)
                existing.add(mid)

    # 3. 提取私密频道帖子链接 (https://t.me/c/<raw_id>/<msg_id>[-<end_id>])
    for m_priv in PRIVATE_POST_RE.finditer(content):
        raw_id = m_priv.group(1)
        start_s = m_priv.group(2)
        end_s = m_priv.group(3)
        full_chat_id = int(f"-100{raw_id}")
        _append_msg_ids(full_chat_id, raw_id, True, start_s, end_s)

    # 4. 提取公开频道帖子链接 (https://t.me/<username>/<msg_id>[-<end_id>])
    for m_pub in PUBLIC_POST_RE.finditer(content):
        username = m_pub.group(1)
        start_s = m_pub.group(2)
        end_s = m_pub.group(3)
        _append_msg_ids(username, username, False, start_s, end_s)

    return list(targets_map.values()), invite_links


def get_harvester_temp_dir() -> str:
    """获取采集器受限媒体中转临时目录"""
    save_path = get_config_value("SAVE_PATH", "/data/downloads")
    if not save_path or not os.path.exists(save_path):
        local_dl = os.path.abspath("./downloads")
        save_path = local_dl if os.path.exists(local_dl) else tempfile.gettempdir()
    tmp_dir = os.path.join(save_path, ".harvester_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    return tmp_dir


def get_media_type_and_obj(msg: Any) -> Tuple[Optional[str], Optional[Any]]:
    """
    从消息对象中提取媒体类型与媒体对象，兼容 Pyrogram Message 与 Telethon Message。
    """
    if not msg or getattr(msg, "empty", False):
        return None, None

    # 1. Pyrogram 风格 (带有 msg.media.value 枚举)
    media_enum = getattr(msg, "media", None)
    if media_enum is not None and hasattr(media_enum, "value"):
        m_val = media_enum.value
        m_obj = getattr(msg, m_val, None)
        if m_obj is not None and not isinstance(m_obj, bool):
            return m_val, m_obj

    # 2. Telethon 风格 (带有 msg.file 封装属性)
    file_wrapper = getattr(msg, "file", None)
    if file_wrapper is not None:
        if getattr(msg, "video", None) is not None:
            return "video", getattr(msg, "video")
        if getattr(msg, "photo", None) is not None:
            return "photo", getattr(msg, "photo")
        if getattr(msg, "audio", None) is not None:
            return "audio", getattr(msg, "audio")
        if getattr(msg, "voice", None) is not None:
            return "voice", getattr(msg, "voice")
        if getattr(msg, "gif", None) is not None:
            return "animation", getattr(msg, "gif")
        if getattr(msg, "video_note", None) is not None:
            return "video_note", getattr(msg, "video_note")
        if getattr(msg, "document", None) is not None:
            return "document", getattr(msg, "document")

    # 3. 通用属性遍历兜底 (兼容 Pyrogram 及单元测试 Mock)
    media_attrs = (
        "video",
        "document",
        "photo",
        "audio",
        "animation",
        "voice",
        "video_note",
    )
    for attr in media_attrs:
        obj = getattr(msg, attr, None)
        if obj is not None and not isinstance(obj, bool):
            return attr, obj
    return None, None


def is_message_protected(msg: Any) -> bool:
    """判断消息或所属频道是否开启了禁止转发/复制保护 (noforwards / has_protected_content)"""
    if not msg:
        return False
    chat_obj = getattr(msg, "chat", None)
    return bool(
        getattr(msg, "has_protected_content", False)
        or getattr(msg, "noforwards", False)
        or getattr(chat_obj, "has_protected_content", False)
        or getattr(chat_obj, "noforwards", False)
    )


def extract_media_dimensions(msg: Any, media_obj: Any) -> Tuple[int, int, int, int]:
    """
    提取媒体时长、宽、高、文件大小 (兼容 Pyrogram 与 Telethon)。
    Returns: (duration, width, height, file_size)
    """
    file_wrapper = getattr(msg, "file", None)
    duration = int(
        getattr(media_obj, "duration", 0)
        or getattr(file_wrapper, "duration", 0)
        or 0
    )
    width = int(
        getattr(media_obj, "width", 0)
        or getattr(file_wrapper, "width", 0)
        or 0
    )
    height = int(
        getattr(media_obj, "height", 0)
        or getattr(file_wrapper, "height", 0)
        or 0
    )
    file_size = int(
        getattr(media_obj, "file_size", 0)
        or getattr(media_obj, "size", 0)
        or getattr(file_wrapper, "size", 0)
        or 0
    )
    return duration, width, height, file_size


def _build_title_prefix_from_caption(caption: Optional[str], max_chars: int = 36) -> str:
    """从相册或帖子配文首行提取干净的标题前缀，用于为无文件名的图片/视频赋予可读名称"""
    if not caption or not caption.strip():
        return ""
    first_line = ""
    for line in caption.splitlines():
        stripped = line.strip()
        if stripped:
            first_line = stripped
            break
    if not first_line:
        return ""
    # 去除首尾括号与特殊符号
    cleaned = re.sub(r"^[【\[（(《「『]+|[】\]）)》」』]+$", "", first_line).strip()
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", cleaned)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._- ")
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip("._- ")
    return cleaned


def extract_raw_filename(
    msg: Any,
    media_type: Optional[str],
    media_obj: Any,
    effective_caption: Optional[str] = None,
) -> str:
    """
    提取消息的原始文件名（兼容 Pyrogram、Telethon 与单元测试 Mock）。
    对于无原生文件名的照片或流视频，自动结合帖子标题与消息 ID 生成可读文件名。
    """
    msg_id = getattr(msg, "id", None) or int(time.time())

    # 1. 尝试调用 get_name (支持 Pyrogram Message 及单元测试 @patch("private_channel_harvester.get_name"))
    try:
        name_from_util = get_name(msg)
        if name_from_util and not re.match(r"^(?:photo|video|audio|voice|file)-\d{4}-\d{2}-\d{2}", name_from_util):
            return name_from_util
    except Exception:
        name_from_util = None

    # 2. 检查 media_obj.file_name 或 Telethon msg.file.name
    file_wrapper = getattr(msg, "file", None)
    explicit_name = (
        getattr(media_obj, "file_name", None)
        or getattr(file_wrapper, "name", None)
    )
    if explicit_name and str(explicit_name).strip():
        return str(explicit_name).strip()

    # 3. 若刚才 get_name 返回了默认带时间戳的名称且无显式文件名，则在无标题时可作兜底
    ext_map = {
        "photo": ".jpg",
        "video": ".mp4",
        "animation": ".mp4",
        "video_note": ".mp4",
        "audio": ".mp3",
        "voice": ".ogg",
    }
    ext = getattr(file_wrapper, "ext", None) or ext_map.get(media_type or "", ".bin")
    if not ext.startswith("."):
        ext = f".{ext}"

    title_prefix = _build_title_prefix_from_caption(effective_caption)
    if title_prefix:
        return f"{title_prefix}_{msg_id}{ext}"

    if name_from_util:
        return name_from_util

    return f"{media_type or 'media'}_{msg_id}{ext}"


def extract_nested_post_links(msg: Any) -> Tuple[List[HarvestTarget], List[str]]:
    """
    当目标消息本身不含媒体文件时（如导航帖、目录帖），深度提取其正文、
    超链接实体 (MessageEntityTextUrl) 与内联按钮 (InlineKeyboard) 中嵌套的 Telegram 帖子链接。
    """
    if not msg:
        return [], []

    parts: List[str] = []
    for attr in ("caption", "text", "message"):
        val = getattr(msg, attr, None)
        if isinstance(val, str) and val.strip():
            parts.append(val)

    for ent_attr in ("entities", "caption_entities"):
        ents = getattr(msg, ent_attr, None) or []
        for ent in ents:
            url = getattr(ent, "url", None)
            if isinstance(url, str) and url.strip():
                parts.append(url)

    reply_markup = getattr(msg, "reply_markup", None)
    if reply_markup:
        rows = (
            getattr(reply_markup, "inline_keyboard", None)
            or getattr(reply_markup, "rows", None)
            or []
        )
        for row in rows:
            buttons = (
                getattr(row, "buttons", None)
                if hasattr(row, "buttons")
                else (row if isinstance(row, (list, tuple)) else [])
            )
            for btn in buttons:
                url = getattr(btn, "url", None)
                if isinstance(url, str) and url.strip():
                    parts.append(url)

    combined = "\n".join(parts)
    if not combined.strip():
        return [], []
    return parse_telegram_post_links(combined)


async def _fetch_single_msg(reader_client: Any, chat_target: Any, msg_id: int) -> Any:
    """兼容 Telethon 与 Pyrogram 的单条消息拉取"""
    # Telethon 客户端特征：拥有 iter_messages 且 get_messages 支持 ids= 关键字参数
    if hasattr(reader_client, "iter_messages") and not hasattr(reader_client, "copy_message"):
        res = await reader_client.get_messages(chat_target, ids=msg_id)
    else:
        res = await reader_client.get_messages(chat_target, msg_id)
    if isinstance(res, list):
        return res[0] if res else None
    return res


async def _fetch_batch_msgs(reader_client: Any, chat_target: Any, msg_ids: List[int]) -> List[Any]:
    """兼容 Telethon 与 Pyrogram 的批量消息拉取"""
    if not msg_ids:
        return []
    if hasattr(reader_client, "iter_messages") and not hasattr(reader_client, "copy_message"):
        res = await reader_client.get_messages(chat_target, ids=msg_ids)
    else:
        res = await reader_client.get_messages(chat_target, msg_ids)
    if not isinstance(res, (list, tuple)):
        return [res] if res is not None else []
    return [m for m in res if m is not None]


async def fetch_and_expand_post(
    reader_client: Any,
    chat_target: Any,
    msg_id: int,
    album_scan_before: int = 35,
    album_scan_after: int = 45,
) -> Tuple[List[Any], Optional[str], str]:
    """
    拉取单条帖子消息，并深度探测其是否属于相册/媒体组 (grouped_id / media_group_id)。
    若属于相册媒体组，自动扫描前后窗口提取该相册内的全部媒体消息（如多张预览图 + 正片大视频），
    同时提取整个相册的主配文供组内无配文的视频/图片继承使用。

    Returns:
        (messages_list, group_id_str, primary_caption)
    """
    msg = await _fetch_single_msg(reader_client, chat_target, msg_id)
    if not msg or getattr(msg, "empty", False):
        return [], None, ""

    raw_group_id = getattr(msg, "grouped_id", None) or getattr(msg, "media_group_id", None)
    if not raw_group_id:
        single_cap = getattr(msg, "caption", None) or getattr(msg, "message", None) or ""
        return [msg], None, single_cap

    group_id_str = str(raw_group_id)
    start_id = max(1, int(msg_id) - album_scan_before)
    end_id = int(msg_id) + album_scan_after
    scan_ids = list(range(start_id, end_id + 1))

    try:
        nearby_msgs = await _fetch_batch_msgs(reader_client, chat_target, scan_ids)
    except Exception as scan_err:
        logger.debug(f"相册窗口扫描回退单条模式 (msg_id={msg_id}): {scan_err}")
        nearby_msgs = [msg]

    album_msgs: List[Any] = []
    seen_ids: Set[int] = set()
    for m in nearby_msgs:
        if not m or getattr(m, "empty", False):
            continue
        m_gid = getattr(m, "grouped_id", None) or getattr(m, "media_group_id", None)
        mid = getattr(m, "id", None)
        if m_gid is not None and str(m_gid) == group_id_str and mid is not None and mid not in seen_ids:
            album_msgs.append(m)
            seen_ids.add(mid)

    cur_mid = getattr(msg, "id", None)
    if cur_mid is not None and cur_mid not in seen_ids:
        album_msgs.append(msg)

    album_msgs.sort(key=lambda x: getattr(x, "id", 0))

    primary_caption = ""
    for m in album_msgs:
        cap = getattr(m, "caption", None) or getattr(m, "message", None) or ""
        if isinstance(cap, str) and cap.strip():
            primary_caption = cap
            break

    return album_msgs, group_id_str, primary_caption


async def ensure_peer_cached(client: Any, chat_id: Any):
    """确保 Pyrogram 客户端已解析目标频道的 access_hash。若未解析，尝试根据用户名预热。"""
    if client is None or not chat_id:
        return
    try:
        if hasattr(client, "resolve_peer"):
            await client.resolve_peer(chat_id)
            return
    except Exception:
        pass

    try:
        import db
        uname = db.get_channel_username_by_chat_id(chat_id)
        if uname and hasattr(client, "get_chat"):
            clean_uname = uname.lstrip("@")
            if not clean_uname.startswith("channel_"):
                await client.get_chat(f"@{clean_uname}")
                logger.info(f"成功通过 @{clean_uname} 预热 Pyrogram Peer 缓存: {chat_id}")
    except Exception as e:
        logger.debug(f"预热 Pyrogram Peer 缓存失败 ({chat_id}): {e}")


def get_write_bot_client(preferred_bot: Any = None, target_bin: Any = None) -> Any:
    """获取具备写入权限的 Bot 客户端。若目标为租户专属频道，优先调度已提权的主控 StreamBot。"""
    if preferred_bot is not None:
        return preferred_bot
    try:
        import WebStreamer.bot as bot_mod
        from WebStreamer.vars import Var

        default_bin = getattr(Var, "BIN_CHANNEL", None)
        if target_bin and default_bin and str(target_bin) != str(default_bin):
            stream_bot = getattr(bot_mod, "StreamBot", None)
            if stream_bot and is_client_ready(stream_bot):
                return stream_bot

        write_indices = getattr(bot_mod, "channel_write_clients", set())
        multi_clients = getattr(bot_mod, "multi_clients", {})
        work_loads = getattr(bot_mod, "work_loads", {})
        bot_runtime = getattr(bot_mod, "bot_runtime", {})
        if write_indices and multi_clients:
            valid = [
                i for i in write_indices
                if i in multi_clients and is_client_ready(multi_clients[i])
            ]
            if valid:
                def _calc_score(idx: int) -> float:
                    st = bot_runtime.get(idx, {}) if isinstance(bot_runtime, dict) else {}
                    hdc = st.get("home_dc")
                    if hdc == 1:
                        dc_weight = 0.0
                    elif hdc == 3:
                        dc_weight = 0.2
                    elif hdc in (2, 4):
                        dc_weight = 1.0
                    elif hdc == 5:
                        dc_weight = 2.5
                    else:
                        dc_weight = 1.5
                    load = work_loads.get(idx, 0)
                    return dc_weight + load * 1.5

                best_idx = min(valid, key=_calc_score)
                return multi_clients[best_idx]
        return getattr(bot_mod, "StreamBot", None)
    except Exception:
        return None


def is_client_ready(client: Any) -> bool:
    """检查 Telegram 客户端是否已连接并处于可调用状态"""
    if client is None:
        return False
    if hasattr(client, "_mock_return_value") or type(client).__name__ in ("MagicMock", "AsyncMock", "Mock"):
        return True
    if hasattr(client, "is_connected"):
        attr = getattr(client, "is_connected")
        return attr() if callable(attr) else bool(attr)
    if hasattr(client, "me") and getattr(client, "me", None) is not None:
        return True
    return True


def get_worker_bot_client(preferred_bot: Any = None) -> Tuple[Optional[int], Any]:
    """
    从 multi_clients 中挑选当前负载最低且已就绪的 Worker Bot 客户端（优先挑选从机 Worker 节点 >= 1）。
    返回 (bot_index, bot_client)。
    """
    if preferred_bot is not None and is_client_ready(preferred_bot):
        return None, preferred_bot
    try:
        import WebStreamer.bot as bot_mod
        multi_clients = getattr(bot_mod, "multi_clients", {})
        work_loads = getattr(bot_mod, "work_loads", {})
        if multi_clients:
            worker_indices = [
                i for i in multi_clients.keys()
                if i >= 1 and multi_clients.get(i) is not None and is_client_ready(multi_clients.get(i))
            ]
            if worker_indices:
                best_idx = min(worker_indices, key=lambda idx: work_loads.get(idx, 0))
                return best_idx, multi_clients[best_idx]
            ready_indices = [
                i for i in multi_clients.keys()
                if multi_clients.get(i) is not None and is_client_ready(multi_clients.get(i))
            ]
            if ready_indices:
                best_idx = min(ready_indices, key=lambda idx: work_loads.get(idx, 0))
                return best_idx, multi_clients[best_idx]
        stream_bot = getattr(bot_mod, "StreamBot", None)
        if is_client_ready(stream_bot):
            return 0, stream_bot
    except Exception:
        pass
    return None, None


async def _resolve_least_loaded_bot_for_msg(
    current_bot_idx: Optional[int],
    current_bot: Any,
    chat_target: Any,
    msg: Any,
    file_size: int,
) -> Tuple[Optional[int], Any, Any]:
    """
    当文件体积较大（>50MB）且由 Bot 下载时，动态检查是否有负载更低的空闲 Worker Bot，
    若有则由该空闲 Bot 重新拉取单条消息上下文（刷新专属 file_reference）并承接下载任务。
    """
    if file_size < 50 * 1024 * 1024 or current_bot is None:
        return current_bot_idx, current_bot, msg
    try:
        import WebStreamer.bot as bot_mod
        work_loads = getattr(bot_mod, "work_loads", {})
        best_idx, best_bot = get_worker_bot_client()
        if (
            best_bot is not None
            and best_bot is not current_bot
            and current_bot_idx is not None
            and best_idx is not None
            and work_loads.get(best_idx, 0) < work_loads.get(current_bot_idx, 0)
        ):
            refreshed_msg = await _fetch_single_msg(best_bot, chat_target, getattr(msg, "id", 0))
            if refreshed_msg:
                return best_idx, best_bot, refreshed_msg
    except Exception as e:
        logger.debug(f"动态切换空闲 Worker Bot 跳过: {e}")
    return current_bot_idx, current_bot, msg


def split_media_group_batches(items: List[Any], max_size: int = 10) -> List[List[Any]]:
    """
    遵循 Telegram 官方限制 (单个 media_group 必须包含 2~10 个媒体项)，
    将媒体列表安全切分为批次。若只有 1 项则返回包含 1 项的单批次供单发兜底。
    """
    if len(items) <= 1:
        return [items] if items else []
    if len(items) <= max_size:
        return [items]

    batches: List[List[Any]] = []
    rem = list(items)
    while len(rem) > max_size:
        # 避免切出最后一批仅有 1 个成员导致 MULTI_MEDIA_TOO_SMALL 报错
        if len(rem) - max_size == 1:
            take = max_size - 1
        else:
            take = max_size
        batches.append(rem[:take])
        rem = rem[take:]
    if rem:
        batches.append(rem)
    return batches


async def optimize_video_for_streaming(
    video_path: str,
    log_fn: Optional[Callable[[str], None]] = None,
) -> str:
    """
    使用 ffmpeg -c copy -movflags +faststart 优化 MP4/MOV 视频容器封装：
    1. 将 moov 索引头置于文件最前端，实现浏览器与播放器秒开起播；
    2. 将音视频数据包紧密交错（Interleaving），消除 HTML5 / Chrome 播放器解复用时的跨段 Range 震荡；
    3. 纯字节流拷贝（0 重编码、0 画质损耗，耗时通常 < 1 秒）；
    4. 若文件过小（< 4KB，如单元测试 Mock）、格式不支持或 ffmpeg 异常，安全保持原文件不变。
    """
    if not video_path or not os.path.exists(video_path):
        return video_path
    try:
        fsize = os.path.getsize(video_path)
        if fsize < 4096:
            return video_path

        _, ext = os.path.splitext(video_path)
        ext_lower = ext.lower()
        if ext_lower not in {".mp4", ".m4v", ".mov", ".mkv"}:
            return video_path

        faststart_tmp = f"{video_path}.faststart.mp4"
        cmd = [
            "ffmpeg",
            "-y",
            "-v", "error",
            "-i", video_path,
            "-c", "copy",
            "-movflags", "+faststart",
            faststart_tmp,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=45.0)

        if proc.returncode == 0 and os.path.exists(faststart_tmp) and os.path.getsize(faststart_tmp) > 0:
            os.replace(faststart_tmp, video_path)
            if log_fn:
                log_fn(f"🎬 视频流封装优化完成 (+faststart & 音视频平滑交错): {os.path.basename(video_path)}")
        else:
            if os.path.exists(faststart_tmp):
                try:
                    os.unlink(faststart_tmp)
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"视频流优化跳过或未命中: {e}")

    return video_path


def normalize_bot_chat_target(chat_target: Any, msg: Any = None) -> Any:
    """标准化供 Pyrogram Worker Bot 调用的频道/聊天目标标识"""
    if isinstance(chat_target, str) and chat_target:
        return chat_target
    if hasattr(chat_target, "username") and getattr(chat_target, "username", None):
        return getattr(chat_target, "username")
    if hasattr(chat_target, "id") and getattr(chat_target, "id", None) is not None:
        cid = getattr(chat_target, "id")
        if isinstance(cid, int) and cid > 0 and not str(cid).startswith("-100"):
            return int(f"-100{cid}")
        return cid
    if isinstance(chat_target, int):
        if chat_target > 0 and not str(chat_target).startswith("-100"):
            return int(f"-100{chat_target}")
        return chat_target
    if msg is not None:
        c_obj = getattr(msg, "chat", None)
        if c_obj:
            if getattr(c_obj, "username", None):
                return getattr(c_obj, "username")
            cid = getattr(c_obj, "id", None)
            if cid is not None:
                if isinstance(cid, int) and cid > 0 and not str(cid).startswith("-100"):
                    return int(f"-100{cid}")
                return cid
    return chat_target


async def download_media_concurrent_multibot(
    msg: Any,
    chat_target: Any,
    temp_file_path: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    speed_reporter: Optional[Callable[[str], None]] = None,
    log_fn: Optional[Callable[[str], None]] = None,
    chunk_size: int = 1024 * 1024,
    max_bots: Optional[int] = None,
) -> Optional[str]:
    """
    多 Bot 1-to-N 并发切片流式下载器：
    利用集群内多个就绪 Worker Bot 并发获取目标消息上下文与专属合法 file_reference，
    以 1MB 随机写入窗口从目标 Telegram 数据中心并发下载大文件至本地磁盘，跑满 30~40+ MB/s。
    """
    if ByteStreamer is None or FileId is None:
        return None

    media_type, media_obj = get_media_type_and_obj(msg)
    if not media_obj:
        return None

    _, _, _, file_size = extract_media_dimensions(msg, media_obj)
    if file_size < MULTIBOT_DOWNLOAD_THRESHOLD_BYTES:
        return None

    msg_id = getattr(msg, "id", None)
    target_chat_norm = normalize_bot_chat_target(chat_target, msg)
    if not msg_id or not target_chat_norm:
        return None

    try:
        import WebStreamer.bot as bot_mod
        multi_clients = getattr(bot_mod, "multi_clients", {})
        work_loads = getattr(bot_mod, "work_loads", {})
    except Exception:
        return None

    if not multi_clients or len(multi_clients) < 2:
        return None

    target_dc = None
    raw_fid = getattr(media_obj, "file_id", None)
    if raw_fid:
        try:
            target_dc = getattr(FileId.decode(raw_fid), "dc_id", None)
        except Exception:
            target_dc = None

    if callable(get_available_bot_indices):
        candidate_indices = get_available_bot_indices(0, set(), target_dc=target_dc)
    else:
        candidate_indices = []
    for idx in sorted(multi_clients.keys()):
        if idx not in candidate_indices:
            candidate_indices.append(idx)

    candidate_indices = [
        idx for idx in candidate_indices
        if idx in multi_clients and is_client_ready(multi_clients[idx])
    ]
    if max_bots is not None and max_bots > 0:
        candidate_indices = candidate_indices[:max_bots]

    if len(candidate_indices) < 2:
        return None

    # 并发预热各个 Worker Bot 对该频道消息的会话与专属 file_reference
    if log_fn:
        log_fn(
            f"🔄 正在并发预热 {len(candidate_indices)} 个 Worker Bot 的 Telegram 访问凭证与专属媒体会话..."
        )
    init_sem = asyncio.Semaphore(min(40, max(8, len(candidate_indices))))

    async def _init_bot(idx: int):
        c = multi_clients.get(idx)
        if not c:
            return None
        async with init_sem:
            try:
                if getattr(msg, "_client", None) is c:
                    b_msg = msg
                else:
                    b_msg = await asyncio.wait_for(
                        _fetch_single_msg(c, target_chat_norm, msg_id),
                        timeout=6.0,
                    )
                if not b_msg or getattr(b_msg, "empty", False):
                    return None
                _, b_mo = get_media_type_and_obj(b_msg)
                if not b_mo or not getattr(b_mo, "file_id", None):
                    return None
                try:
                    b_fid = FileId.decode(b_mo.file_id)
                except Exception:
                    b_fid = b_mo.file_id
                streamer = ByteStreamer.for_client(c)
                loc = await ByteStreamer.get_location(b_fid)
                return (idx, c, streamer, b_fid, loc)
            except Exception as e:
                logger.debug(f"Bot #{idx} 初始化分片下载上下文跳过: {e}")
                return None

    bot_contexts = await asyncio.gather(*[_init_bot(i) for i in candidate_indices])
    active_bots = [b for b in bot_contexts if b is not None]
    if len(active_bots) < 2:
        return None

    part_count = math.ceil(file_size / chunk_size)
    part_queue: asyncio.Queue = asyncio.Queue()
    for p in range(part_count):
        part_queue.put_nowait(p)

    os.makedirs(os.path.dirname(os.path.abspath(temp_file_path)), exist_ok=True)
    f = open(temp_file_path, "wb")
    f.truncate(file_size)

    completed_parts = 0
    completed_bytes = 0
    completed_parts_set: set = set()
    in_flight_since: Dict[int, float] = {}
    write_lock = asyncio.Lock()
    part_retries: Dict[int, int] = {}
    abort_event = asyncio.Event()
    done_event = asyncio.Event()
    start_ts = time.time()
    last_speed_ts = start_ts
    last_speed_bytes = 0

    if log_fn:
        log_fn(
            f"⚡ 启动多 Bot 集群并发分片下载: 已调动 {len(active_bots)} 个 Worker Bot 并发拉取 #{msg_id} ({_format_size(file_size)}, 共 {part_count} 分片)..."
        )

    async def _worker(bot_tuple):
        nonlocal completed_parts, completed_bytes, last_speed_ts, last_speed_bytes
        idx, client, streamer, fid, loc = bot_tuple
        work_loads[idx] = work_loads.get(idx, 0) + 1
        consecutive_err = 0
        try:
            while not abort_event.is_set() and not done_event.is_set():
                part_idx = None
                try:
                    part_idx = part_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

                if part_idx is not None:
                    if part_idx in completed_parts_set:
                        continue
                    in_flight_since[part_idx] = time.time()
                else:
                    # 队列为空时：检查是否全部完成；若未完成，检查是否有耗时超过 2.5s 的滞后尾块，由当前空闲 Worker 快速对冲拉取
                    if len(completed_parts_set) >= part_count:
                        done_event.set()
                        break
                    now_ts = time.time()
                    straggler = None
                    for p in range(part_count):
                        if p not in completed_parts_set and (now_ts - in_flight_since.get(p, 0)) >= 2.5:
                            straggler = p
                            break
                    if straggler is not None:
                        part_idx = straggler
                        in_flight_since[part_idx] = now_ts
                    else:
                        await asyncio.sleep(0.1)
                        continue

                part_offset = part_idx * chunk_size
                expected_len = min(chunk_size, file_size - part_offset)
                chunk_ok = False

                try:
                    ok, r, _, _ = await streamer._try_get_file_chunk(
                        client,
                        idx,
                        fid,
                        loc,
                        part_offset,
                        chunk_size,
                        max_retries=1,
                        timeout=5.0,
                    )
                    raw_bytes = getattr(r, "bytes", None) if (ok and r is not None) else None
                    if raw_bytes:
                        chunk_data = raw_bytes[:expected_len]
                        if len(chunk_data) == expected_len:
                            async with write_lock:
                                if part_idx not in completed_parts_set:
                                    f.seek(part_offset)
                                    f.write(chunk_data)
                                    completed_parts_set.add(part_idx)
                                    completed_bytes += len(chunk_data)
                                    completed_parts = len(completed_parts_set)
                                    cur_bytes = completed_bytes
                                    if completed_parts >= part_count:
                                        done_event.set()
                                else:
                                    cur_bytes = completed_bytes
                            chunk_ok = True
                            consecutive_err = 0
                except asyncio.CancelledError:
                    break
                except Exception as chunk_err:
                    logger.debug(f"Bot #{idx} 拉取分片 {part_idx} 异常: {chunk_err}")

                if chunk_ok:
                    if progress_cb:
                        try:
                            progress_cb(cur_bytes, file_size)
                        except asyncio.CancelledError:
                            abort_event.set()
                            raise
                        except Exception:
                            pass
                    now = time.time()
                    if now - last_speed_ts >= 0.6 or cur_bytes >= file_size:
                        dt = max(now - last_speed_ts, 0.001)
                        speed_mb = ((cur_bytes - last_speed_bytes) / dt) / (1024 * 1024)
                        pct = int(cur_bytes * 100 / file_size) if file_size else 0
                        if speed_reporter:
                            speed_reporter(
                                f"⬇️ [Bot集群 x{len(active_bots)} 并发] 下载 {speed_mb:.1f} MB/s ({pct}%)"
                            )
                        last_speed_ts = now
                        last_speed_bytes = cur_bytes
                else:
                    consecutive_err += 1
                    if part_idx not in completed_parts_set:
                        retries = part_retries.get(part_idx, 0) + 1
                        part_retries[part_idx] = retries
                        if retries <= 20 and not abort_event.is_set():
                            part_queue.put_nowait(part_idx)
                        else:
                            abort_event.set()
                            break
                    if consecutive_err >= 5 and len(active_bots) > 2:
                        logger.debug(f"Bot #{idx} 连续分片超时，主动退出让位")
                        break
                    await asyncio.sleep(0.15)
        finally:
            work_loads[idx] = max(0, work_loads.get(idx, 0) - 1)

    workers = []
    workers_per_bot = 2 if len(active_bots) <= 8 and part_count >= len(active_bots) * 2 else 1
    for b in active_bots:
        for _ in range(workers_per_bot):
            workers.append(asyncio.create_task(_worker(b)))

    workers_task = asyncio.ensure_future(asyncio.gather(*workers, return_exceptions=True))
    try:
        done_waiter = asyncio.create_task(done_event.wait())
        abort_waiter = asyncio.create_task(abort_event.wait())
        await asyncio.wait(
            [done_waiter, abort_waiter, workers_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in [done_waiter, abort_waiter]:
            if not t.done():
                t.cancel()
    finally:
        for w in workers:
            if not w.done():
                w.cancel()
        if not workers_task.done():
            workers_task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        f.flush()
        f.close()

    if abort_event.is_set() or completed_parts < part_count:
        if os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception:
                pass
        raise RuntimeError(
            f"多 Bot 并发分片下载未完整获取 ({completed_parts}/{part_count} 分片)"
        )

    actual_size = os.path.getsize(temp_file_path)
    if actual_size != file_size:
        if os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception:
                pass
        raise RuntimeError(
            f"多 Bot 并发分片下载字节不匹配 (期望 {file_size}, 实际 {actual_size})"
        )

    return temp_file_path


async def _download_media_unified(
    dl_client: Any,
    msg: Any,
    temp_file_path: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    chat_target: Any = None,
    speed_reporter: Optional[Callable[[str], None]] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """兼容 Telethon、Pyrogram 及多 Bot 集群并发分片的高性能流式下载封装"""
    # 1. 尝试多 Bot 集群 1-to-N 并发分片下载（大文件 >= 8MB 且目标频道可由 Bot 访问）
    try:
        _, mo = get_media_type_and_obj(msg)
        f_size = getattr(mo, "file_size", 0) or getattr(mo, "size", 0) if mo else 0
        if f_size >= MULTIBOT_DOWNLOAD_THRESHOLD_BYTES:
            target_chat = chat_target
            if target_chat is None:
                chat_obj = getattr(msg, "chat", None)
                target_chat = (
                    getattr(chat_obj, "username", None)
                    or getattr(chat_obj, "id", None)
                    or getattr(msg, "chat_id", None)
                )

            res_path = await download_media_concurrent_multibot(
                msg=msg,
                chat_target=target_chat,
                temp_file_path=temp_file_path,
                progress_cb=progress_cb,
                speed_reporter=speed_reporter,
                log_fn=log_fn,
            )
            if res_path and os.path.exists(res_path) and os.path.getsize(res_path) > 0:
                return res_path
    except asyncio.CancelledError:
        raise
    except Exception as multibot_err:
        logger.debug(f"多 Bot 并发分片下载未命中 ({multibot_err})，平滑回退单客户端下载")

    if os.path.exists(temp_file_path) and os.path.getsize(temp_file_path) == 0:
        try:
            os.unlink(temp_file_path)
        except Exception:
            pass

    # 2. 单客户端回退下载：Telethon 客户端: download_media(msg, file=..., progress_callback=...)
    if hasattr(dl_client, "iter_messages") and not hasattr(dl_client, "copy_message"):
        if progress_cb:
            res = await dl_client.download_media(
                msg,
                file=temp_file_path,
                progress_callback=progress_cb,
            )
        else:
            res = await dl_client.download_media(
                msg,
                file=temp_file_path,
            )
        return str(res) if res else None

    # 3. 单客户端回退下载：Pyrogram 客户端或单元测试 Mock: download_media(msg, file_name=..., progress=...)
    if progress_cb:
        res = await dl_client.download_media(
            msg,
            file_name=temp_file_path,
            progress=progress_cb,
        )
    else:
        res = await dl_client.download_media(
            msg,
            file_name=temp_file_path,
        )
    return str(res) if res else None


async def harvest_single_message(
    msg: Any,
    user_client: Any = None,
    bot_client: Any = None,
    bin_channel: Optional[int] = None,
    rebrand_enabled: Optional[bool] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    upload_progress_cb: Optional[Callable[[int, int], None]] = None,
    fallback_caption: Optional[str] = None,
    custom_media_group_id: Optional[str] = None,
    dl_client: Any = None,
    chat_target: Any = None,
    speed_reporter: Optional[Callable[[str], None]] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    对单条目标频道消息执行智能双模转存（零流量秒传 vs 受限下载重传）并入库。
    """
    target_bin = bin_channel or Var.BIN_CHANNEL
    if not target_bin:
        raise ValueError("BIN_CHANNEL 未配置，无法转存媒体到网盘")

    write_bot = get_write_bot_client(bot_client, target_bin=target_bin)
    if write_bot is not None:
        await ensure_peer_cached(write_bot, target_bin)
    if write_bot is None and user_client is None:
        raise RuntimeError("无可用的 Bot 或协议号客户端执行转存")

    media_type, media_obj = get_media_type_and_obj(msg)
    if not media_obj:
        return {
            "status": "skipped",
            "msg_id": getattr(msg, "id", 0),
            "reason": "该消息不包含可转存的媒体文件",
        }

    # 读取洗白配置
    if rebrand_enabled is None:
        rebrand_enabled = bool(get_config_value("FORWARD_REBRAND_ENABLED", True))
    clean_filenames = bool(get_config_value("FORWARD_CLEAN_FILENAMES", True))
    target_channel = get_config_value("FORWARD_TARGET_CHANNEL", "")
    signature = get_config_value("FORWARD_CHANNEL_SIGNATURE", "")
    custom_rules = get_config_value("FORWARD_CUSTOM_REPLACE_RULES", "")

    raw_caption = getattr(msg, "caption", None)
    if raw_caption is None:
        raw_caption = getattr(msg, "message", None)
    if (not raw_caption or not str(raw_caption).strip()) and fallback_caption:
        raw_caption = fallback_caption

    raw_file_name = extract_raw_filename(
        msg=msg,
        media_type=media_type,
        media_obj=media_obj,
        effective_caption=raw_caption,
    )

    cleaned_file_name = (
        clean_drive_filename(
            raw_file_name,
            clean_enabled=clean_filenames,
            custom_rules=custom_rules,
        )
        if clean_filenames
        else raw_file_name
    )

    cleaned_caption = (
        clean_and_rebrand_caption(
            raw_caption,
            target_channel=target_channel,
            signature=signature,
            custom_rules=custom_rules,
        )
        if rebrand_enabled and (raw_caption or signature)
        else (raw_caption or "")
    )

    is_protected = is_message_protected(msg)
    chat_obj = getattr(msg, "chat", None)
    source_chat_id = getattr(chat_obj, "id", None) or getattr(msg, "chat_id", None)
    source_msg_id = getattr(msg, "id", None)

    log_msg = None
    used_mode = "fast_copy"

    # =========================================================================
    # 模式一：尝试零流量秒传 (fast_copy)
    # =========================================================================
    if not is_protected and source_chat_id and source_msg_id:
        # 若 source_chat_id 是 Telethon 返回的正整数 channel id，标准化为 -100 前缀以供 Bot API 识别
        bot_from_chat: Union[int, str] = source_chat_id
        chat_username = getattr(chat_obj, "username", None)
        if chat_username:
            bot_from_chat = chat_username
        elif isinstance(source_chat_id, int) and source_chat_id > 0 and not str(source_chat_id).startswith("-100"):
            bot_from_chat = int(f"-100{source_chat_id}")

        # 1) 优先尝试由具备频道写权限的 Bot 直接 copy_message
        if write_bot is not None and hasattr(write_bot, "copy_message"):
            try:
                log_msg = await write_bot.copy_message(
                    chat_id=target_bin,
                    from_chat_id=bot_from_chat,
                    message_id=source_msg_id,
                    caption=cleaned_caption,
                )
                used_mode = "fast_copy"
            except Exception as bot_copy_err:
                logger.debug(f"Bot 直接 copy_message 未命中 ({bot_copy_err})，尝试协议号中转或下载重传")
                log_msg = None

        # 2) 若 Bot 不在源频道，尝试由协议号直接 copy_message（仅当协议号客户端支持时）
        if log_msg is None and user_client is not None and hasattr(user_client, "copy_message"):
            try:
                log_msg = await user_client.copy_message(
                    chat_id=target_bin,
                    from_chat_id=source_chat_id,
                    message_id=source_msg_id,
                    caption=cleaned_caption,
                )
                used_mode = "fast_copy"
            except Exception as user_copy_err:
                logger.debug(f"协议号直接 copy_message 未命中 ({user_copy_err})，切换至受限下载重传管线")
                log_msg = None

    # =========================================================================
    # 模式二：受限破除下载重传 (restricted_relay)
    # =========================================================================
    if log_msg is None:
        used_mode = "restricted_relay"
        if dl_client is None:
            # 智能选路：若为公开频道（具备 username）且 bot_client 支持下载，强制优先由 Bot 执行流式下载
            is_priv = True
            if chat_obj and getattr(chat_obj, "username", None):
                is_priv = False
            if not is_priv and write_bot is not None and hasattr(write_bot, "download_media"):
                dl_client = write_bot
            else:
                dl_client = user_client or write_bot
        up_client = write_bot or user_client

        if dl_client is None or not hasattr(dl_client, "download_media"):
            raise RuntimeError("当前客户端不支持 download_media，无法拉取受限频道媒体")

        tmp_dir = get_harvester_temp_dir()
        safe_name = re.sub(r'[\\/:*?"<>|]+', "_", cleaned_file_name or f"media_{source_msg_id}")
        temp_file_path = os.path.join(tmp_dir, f"harvest_{source_msg_id}_{secrets.token_hex(4)}_{safe_name}")

        duration, width, height, _ = extract_media_dimensions(msg, media_obj)
        downloaded_path = None

        # 追踪 Bot 节点工作负载，防止大文件下载期间单节点过载
        bot_idx_to_release = None
        try:
            import WebStreamer.bot as bot_mod
            multi_clients = getattr(bot_mod, "multi_clients", {})
            work_loads = getattr(bot_mod, "work_loads", {})
            for idx, c in multi_clients.items():
                if c is dl_client:
                    bot_idx_to_release = idx
                    work_loads[idx] = work_loads.get(idx, 0) + 1
                    break
        except Exception:
            pass

        try:
            downloaded_path = await _download_media_unified(
                dl_client=dl_client,
                msg=msg,
                temp_file_path=temp_file_path,
                progress_cb=progress_cb,
                chat_target=chat_target,
                speed_reporter=speed_reporter,
                log_fn=log_fn,
            )

            if not downloaded_path or not os.path.exists(downloaded_path):
                raise RuntimeError(f"媒体文件下载失败或文件为空 (msg_id={source_msg_id})")

            if media_type == "video":
                await optimize_video_for_streaming(downloaded_path, log_fn=log_fn)

            up_extra_kwargs: Dict[str, Any] = {}
            if upload_progress_cb is not None:
                up_extra_kwargs["progress"] = upload_progress_cb

            if media_type == "video" and hasattr(up_client, "send_video"):
                log_msg = await up_client.send_video(
                    chat_id=target_bin,
                    video=downloaded_path,
                    caption=cleaned_caption,
                    file_name=cleaned_file_name,
                    duration=duration,
                    width=width,
                    height=height,
                    supports_streaming=True,
                    **up_extra_kwargs,
                )
            elif media_type == "audio" and hasattr(up_client, "send_audio"):
                log_msg = await up_client.send_audio(
                    chat_id=target_bin,
                    audio=downloaded_path,
                    caption=cleaned_caption,
                    file_name=cleaned_file_name,
                    duration=duration,
                    performer=getattr(media_obj, "performer", None),
                    title=getattr(media_obj, "title", None),
                    **up_extra_kwargs,
                )
            elif media_type == "photo" and hasattr(up_client, "send_photo"):
                log_msg = await up_client.send_photo(
                    chat_id=target_bin,
                    photo=downloaded_path,
                    caption=cleaned_caption,
                    **up_extra_kwargs,
                )
            else:
                log_msg = await up_client.send_document(
                    chat_id=target_bin,
                    document=downloaded_path,
                    caption=cleaned_caption,
                    file_name=cleaned_file_name,
                    **up_extra_kwargs,
                )
        finally:
            if bot_idx_to_release is not None:
                try:
                    import WebStreamer.bot as bot_mod
                    work_loads = getattr(bot_mod, "work_loads", {})
                    if bot_idx_to_release in work_loads:
                        work_loads[bot_idx_to_release] = max(0, work_loads[bot_idx_to_release] - 1)
                except Exception:
                    pass
            for p in (downloaded_path, temp_file_path):
                if p and isinstance(p, str) and os.path.exists(p):
                    try:
                        os.unlink(p)
                    except Exception as cleanup_err:
                        logger.debug(f"清理临时采集文件失败 ({p}): {cleanup_err}")

    if log_msg is None:
        raise RuntimeError(f"消息 #{source_msg_id} 转存后未返回有效频道消息对象")

    # =========================================================================
    # 入库 tg_media 并触发缩略图预生成
    # =========================================================================
    log_media = (
        getattr(log_msg, log_msg.media.value, None)
        if getattr(log_msg, "media", None) and hasattr(log_msg.media, "value")
        else None
    )
    if log_media is None:
        _, log_media = get_media_type_and_obj(log_msg)

    effective_group_id = (
        custom_media_group_id
        or (str( getattr(msg, "grouped_id", None) or getattr(msg, "media_group_id", None) ) if (getattr(msg, "grouped_id", None) or getattr(msg, "media_group_id", None)) else None)
    )

    file_unique_id = None
    if log_media is not None:
        try:
            file_unique_id = db.save_tg_media(
                log_msg,
                log_media,
                custom_file_name=cleaned_file_name if clean_filenames else None,
                custom_caption=cleaned_caption if rebrand_enabled else None,
                custom_media_group_id=effective_group_id,
            )
            try:
                from thumbnail_worker import get_thumbnail_worker
                get_thumbnail_worker().enqueue(log_msg.id, chat_id=target_bin)
            except Exception:
                pass
        except Exception as db_err:
            logger.error(f"采集媒体写入数据库失败: {db_err}", exc_info=True)

    try:
        file_hash = get_hash(log_msg, Var.HASH_LENGTH)
    except Exception:
        file_hash = "000000"

    base_url = Var.URL or "/"
    if not base_url.endswith("/"):
        base_url += "/"
    stream_link = f"{base_url}{log_msg.id}/{quote_plus(cleaned_file_name)}?hash={file_hash}"
    short_link = f"{base_url}{file_hash}{log_msg.id}"

    return {
        "status": "success",
        "mode": used_mode,
        "msg_id": log_msg.id,
        "source_msg_id": source_msg_id,
        "name": cleaned_file_name,
        "full_link": stream_link,
        "short_link": short_link,
        "file_unique_id": file_unique_id,
        "media_group_id": effective_group_id,
    }


async def harvest_media_group(
    album_msgs: List[Any],
    group_id_str: str,
    primary_caption: str = "",
    user_client: Any = None,
    bot_client: Any = None,
    bin_channel: Optional[int] = None,
    rebrand_enabled: Optional[bool] = None,
    chat_target: Any = None,
    dl_client: Any = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    upload_progress_cb: Optional[Callable[[int, int], None]] = None,
    speed_reporter: Optional[Callable[[str], None]] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, Any]]:
    """
    相册/媒体组（Media Group）整组聚合转存核心管线：
    支持零流量整组 copy_media_group 与受限整组下载 ➔ send_media_group 原生相册聚合重传，
    自动按 Telegram 上限每 10 个媒体切分批次，批量绑定并写入 tg_media 数据库。
    """
    target_bin = bin_channel or Var.BIN_CHANNEL
    if not target_bin:
        raise ValueError("BIN_CHANNEL 未配置，无法转存媒体到网盘")

    write_bot = get_write_bot_client(bot_client, target_bin=target_bin)
    if write_bot is not None:
        await ensure_peer_cached(write_bot, target_bin)
    if write_bot is None and user_client is None:
        raise RuntimeError("无可用的 Bot 或协议号客户端执行转存")

    valid_items = []
    for m in album_msgs:
        mt, mo = get_media_type_and_obj(m)
        if mt and mo:
            valid_items.append((m, mt, mo))

    if not valid_items:
        return []

    # 若相册展开后仅有 1 个媒体，回退单发模式
    if len(valid_items) == 1:
        single_res = await harvest_single_message(
            msg=valid_items[0][0],
            user_client=user_client,
            bot_client=bot_client,
            bin_channel=target_bin,
            rebrand_enabled=rebrand_enabled,
            progress_cb=progress_cb,
            upload_progress_cb=upload_progress_cb,
            fallback_caption=primary_caption,
            custom_media_group_id=group_id_str,
            dl_client=dl_client,
            chat_target=chat_target,
            speed_reporter=speed_reporter,
            log_fn=log_fn,
        )
        return [single_res]

    if rebrand_enabled is None:
        rebrand_enabled = bool(get_config_value("FORWARD_REBRAND_ENABLED", True))
    clean_filenames = bool(get_config_value("FORWARD_CLEAN_FILENAMES", True))
    target_channel = get_config_value("FORWARD_TARGET_CHANNEL", "")
    signature = get_config_value("FORWARD_CHANNEL_SIGNATURE", "")
    custom_rules = get_config_value("FORWARD_CUSTOM_REPLACE_RULES", "")

    effective_raw_caption = primary_caption or ""
    if not effective_raw_caption:
        for m, _, _ in valid_items:
            c = getattr(m, "caption", None) or getattr(m, "message", None)
            if c and str(c).strip():
                effective_raw_caption = str(c)
                break

    cleaned_group_caption = (
        clean_and_rebrand_caption(
            effective_raw_caption,
            target_channel=target_channel,
            signature=signature,
            custom_rules=custom_rules,
        )
        if rebrand_enabled and (effective_raw_caption or signature)
        else (effective_raw_caption or "")
    )

    seen_clean_names: Set[str] = set()
    prepared_items = []
    for m, mt, mo in valid_items:
        source_id = getattr(m, "id", None) or int(time.time())
        raw_name = extract_raw_filename(
            msg=m,
            media_type=mt,
            media_obj=mo,
            effective_caption=effective_raw_caption,
        )
        clean_name = (
            clean_drive_filename(
                raw_name,
                clean_enabled=clean_filenames,
                custom_rules=custom_rules,
            )
            if clean_filenames
            else raw_name
        )
        clean_name = re.sub(r'[\\/:*?"<>|]+', "_", clean_name or f"{mt}_{source_id}")
        if clean_name in seen_clean_names:
            stem, ext = os.path.splitext(clean_name)
            clean_name = f"{stem}_{source_id}{ext}"
        seen_clean_names.add(clean_name)
        prepared_items.append({
            "msg": m,
            "media_type": mt,
            "media_obj": mo,
            "source_msg_id": source_id,
            "raw_name": raw_name,
            "clean_name": clean_name,
        })

    is_protected = any(is_message_protected(it["msg"]) for it in prepared_items)
    first_msg = prepared_items[0]["msg"]
    chat_obj = getattr(first_msg, "chat", None)
    source_chat_id = getattr(chat_obj, "id", None) or getattr(first_msg, "chat_id", None)
    chat_username = getattr(chat_obj, "username", None)
    bot_from_chat = chat_username or (
        int(f"-100{source_chat_id}")
        if isinstance(source_chat_id, int) and source_chat_id > 0 and not str(source_chat_id).startswith("-100")
        else source_chat_id
    )

    batches = split_media_group_batches(prepared_items, max_size=10)
    all_results: List[Dict[str, Any]] = []

    for batch_idx, batch in enumerate(batches):
        copied_msgs = None
        used_mode = "fast_copy"

        # 模式一：尝试零流量整组秒传 (fast_copy)
        if not is_protected and bot_from_chat and write_bot is not None and hasattr(write_bot, "copy_media_group"):
            try:
                captions = [cleaned_group_caption if idx == 0 else "" for idx in range(len(batch))]
                first_id = batch[0]["source_msg_id"]
                res = write_bot.copy_media_group(
                    chat_id=target_bin,
                    from_chat_id=bot_from_chat,
                    message_id=first_id,
                    captions=captions,
                )
                if asyncio.iscoroutine(res):
                    copied_msgs = await res
                else:
                    copied_msgs = res
                if copied_msgs and isinstance(copied_msgs, list) and len(copied_msgs) == len(batch):
                    used_mode = "fast_copy"
                else:
                    copied_msgs = None
            except Exception as copy_err:
                logger.debug(f"copy_media_group 未命中 ({copy_err})，切换到整组下载聚合重传")
                copied_msgs = None

        sent_msgs = copied_msgs
        if sent_msgs is None:
            used_mode = "restricted_relay"
            up_client = write_bot or user_client
            if dl_client is None:
                is_priv = True
                if chat_obj and getattr(chat_obj, "username", None):
                    is_priv = False
                if not is_priv and write_bot is not None and hasattr(write_bot, "download_media"):
                    dl_client = write_bot
                else:
                    dl_client = user_client or write_bot

            batch_token = secrets.token_hex(4)
            batch_dir = os.path.join(get_harvester_temp_dir(), f"album_{group_id_str}_{batch_token}")
            os.makedirs(batch_dir, exist_ok=True)

            try:
                for item in batch:
                    item["download_path"] = os.path.join(batch_dir, item["clean_name"])

                small_items = [
                    it for it in batch
                    if (getattr(it["media_obj"], "file_size", 0) or getattr(it["media_obj"], "size", 0)) < MULTIBOT_DOWNLOAD_THRESHOLD_BYTES
                ]
                large_items = [
                    it for it in batch
                    if (getattr(it["media_obj"], "file_size", 0) or getattr(it["media_obj"], "size", 0)) >= MULTIBOT_DOWNLOAD_THRESHOLD_BYTES
                ]

                # 小文件（相册图片/封面）统一使用检索该批消息的源客户端（dl_client 或 write_bot）拉取。
                # Telegram MTProto 的 Message 对象内部封装了专属该 Bot 的 file_reference，
                # 只有通过签发该引用的客户端或通过 get_messages 刷新的客户端才能有效调用 GetFile，
                # 否则会被 Telegram 拒绝并导致 Pyrogram 生成 0 字节空文件。
                actual_source_dl = dl_client or write_bot or user_client

                # 小文件（预览图）与大视频并发拉取，彻底消除相册预览图串行等待
                async def _download_all_smalls():
                    if not small_items:
                        return
                    if log_fn:
                        log_fn(f"📸 正在并发拉取相册预览小图 ({len(small_items)} 张)...")
                    small_sem = asyncio.Semaphore(min(8, len(small_items)))

                    async def _download_one_small(it):
                        async with small_sem:
                            res = await _download_media_unified(
                                dl_client=actual_source_dl,
                                msg=it["msg"],
                                temp_file_path=it["download_path"],
                                chat_target=chat_target or bot_from_chat,
                                log_fn=log_fn,
                            )
                            it["downloaded_path"] = res

                    await asyncio.gather(*[_download_one_small(it) for it in small_items])
                    if log_fn:
                        log_fn(f"✅ 相册预览小图 ({len(small_items)} 张) 已全部下载完成")

                async def _download_all_larges():
                    for it in large_items:
                        res = await _download_media_unified(
                            dl_client=actual_source_dl,
                            msg=it["msg"],
                            temp_file_path=it["download_path"],
                            progress_cb=progress_cb,
                            chat_target=chat_target or bot_from_chat,
                            speed_reporter=speed_reporter,
                            log_fn=log_fn,
                        )
                        it["downloaded_path"] = res

                await asyncio.gather(_download_all_smalls(), _download_all_larges())

                for it in batch:
                    dp = it.get("downloaded_path")
                    if not dp or not os.path.exists(dp) or os.path.getsize(dp) == 0:
                        # 0 字节文件自动重试补救
                        s_id = it.get("source_msg_id")
                        logger.warning(
                            f"相册媒体 #{s_id} 下载异常或文件为空，尝试由主客户端重新拉取..."
                        )
                        dp = await _download_media_unified(
                            dl_client=actual_source_dl,
                            msg=it["msg"],
                            temp_file_path=it["download_path"],
                            chat_target=chat_target or bot_from_chat,
                            log_fn=log_fn,
                        )
                        it["downloaded_path"] = dp

                    if not dp or not os.path.exists(dp) or os.path.getsize(dp) == 0:
                        s_id = it.get("source_msg_id")
                        c_name = it.get("clean_name", "media")
                        raise RuntimeError(
                            f"相册媒体文件下载失败或为空 (0 B): #{s_id} ({c_name})"
                        )
                    if it.get("media_type") == "video":
                        await optimize_video_for_streaming(dp, log_fn=log_fn)

                media_group_input = []
                for idx, it in enumerate(batch):
                    m = it["msg"]
                    mt = it["media_type"]
                    mo = it["media_obj"]
                    dp = it["downloaded_path"]
                    item_caption = cleaned_group_caption if idx == 0 else ""
                    duration, width, height, _ = extract_media_dimensions(m, mo)

                    if mt == "photo":
                        media_group_input.append(InputMediaPhoto(media=dp, caption=item_caption))
                    elif mt == "video":
                        thumb_path = None
                        try:
                            from util import imgCoverFromFile
                            cand_thumb = os.path.join(batch_dir, f"thumb_{it['source_msg_id']}.jpg")
                            await imgCoverFromFile(dp, cand_thumb)
                            if os.path.exists(cand_thumb) and os.path.getsize(cand_thumb) > 0:
                                thumb_path = cand_thumb
                        except Exception:
                            thumb_path = None
                        media_group_input.append(
                            InputMediaVideo(
                                media=dp,
                                thumb=thumb_path,
                                caption=item_caption,
                                width=width,
                                height=height,
                                duration=duration,
                                supports_streaming=True,
                            )
                        )
                    elif mt == "audio":
                        media_group_input.append(
                            InputMediaAudio(
                                media=dp,
                                caption=item_caption,
                                duration=duration,
                                performer=getattr(mo, "performer", None),
                                title=getattr(mo, "title", None),
                            )
                        )
                    else:
                        media_group_input.append(InputMediaDocument(media=dp, caption=item_caption))

                files_to_preupload = []
                for inp in media_group_input:
                    med = getattr(inp, "media", None)
                    if isinstance(med, str) and os.path.exists(med) and os.path.getsize(med) > 0 and med not in files_to_preupload:
                        files_to_preupload.append(med)
                    th = getattr(inp, "thumb", None)
                    if isinstance(th, str) and os.path.exists(th) and os.path.getsize(th) > 0 and th not in files_to_preupload:
                        files_to_preupload.append(th)

                hook_token = None
                if upload_progress_cb is not None:
                    try:
                        from WebStreamer.utils.fast_uploader import set_upload_progress_hook
                        hook_token = set_upload_progress_hook(lambda cur, tot, conc: upload_progress_cb(cur, tot))
                    except Exception:
                        pass

                try:
                    # 全文件并发预上传：调动多通道同时并行上传相册内全部媒体分片与封面
                    if hasattr(up_client, "save_file") and len(files_to_preupload) > 1:
                        if log_fn:
                            log_fn(
                                f"⚡ [全文件并发预传] 调动多通道并行预上传相册全部 {len(files_to_preupload)} 个媒体/封面文件..."
                            )
                        if speed_reporter:
                            speed_reporter(f"⬆️ [并发预传] 并行上传相册 {len(files_to_preupload)} 个文件...")

                        async def _preupload_worker(fpath: str):
                            try:
                                save_fn = getattr(up_client, "save_file", None)
                                if callable(save_fn):
                                    r = save_fn(fpath)
                                    if asyncio.iscoroutine(r):
                                        r = await r
                                    if r is not None:
                                        try:
                                            from WebStreamer.utils.fast_uploader import register_preuploaded_file
                                            register_preuploaded_file(fpath, r)
                                        except Exception:
                                            pass
                                    return r
                            except Exception as up_err:
                                logger.debug(f"预上传分片异常 ({fpath}): {up_err}")
                            return None

                        await asyncio.gather(*[_preupload_worker(p) for p in files_to_preupload])

                    if log_fn:
                        log_fn(f"⬆️ 正在通过 send_media_group 聚合发布相册媒体组 ({len(batch)} 项)...")
                    if speed_reporter:
                        speed_reporter(f"⬆️ 正在聚合上传相册 ({len(batch)} 项)...")

                    if hasattr(up_client, "send_media_group"):
                        try:
                            res = up_client.send_media_group(chat_id=target_bin, media=media_group_input)
                            if asyncio.iscoroutine(res):
                                sent_msgs = await res
                            else:
                                sent_msgs = res
                        except Exception as smg_err:
                            logger.warning(f"send_media_group 聚合发送失败: {smg_err}，尝试单条兼容重传")
                            sent_msgs = None
                finally:
                    if hook_token is not None:
                        try:
                            from WebStreamer.utils.fast_uploader import reset_upload_progress_hook
                            reset_upload_progress_hook(hook_token)
                        except Exception:
                            pass
                    try:
                        from WebStreamer.utils.fast_uploader import clear_preuploaded_files
                        clear_preuploaded_files(files_to_preupload)
                    except Exception:
                        pass

                if not sent_msgs or not isinstance(sent_msgs, list) or len(sent_msgs) != len(batch):
                    sent_msgs = []
                    for idx, it in enumerate(batch):
                        m = it["msg"]
                        mt = it["media_type"]
                        mo = it["media_obj"]
                        dp = it["downloaded_path"]
                        item_cap = cleaned_group_caption if idx == 0 else ""
                        duration, width, height, _ = extract_media_dimensions(m, mo)

                        if mt == "video" and hasattr(up_client, "send_video"):
                            lm = await up_client.send_video(
                                chat_id=target_bin,
                                video=dp,
                                caption=item_cap,
                                file_name=it["clean_name"],
                                duration=duration,
                                width=width,
                                height=height,
                                supports_streaming=True,
                            )
                        elif mt == "photo" and hasattr(up_client, "send_photo"):
                            lm = await up_client.send_photo(
                                chat_id=target_bin,
                                photo=dp,
                                caption=item_cap,
                            )
                        elif mt == "audio" and hasattr(up_client, "send_audio"):
                            lm = await up_client.send_audio(
                                chat_id=target_bin,
                                audio=dp,
                                caption=item_cap,
                                file_name=it["clean_name"],
                                duration=duration,
                            )
                        else:
                            lm = await up_client.send_document(
                                chat_id=target_bin,
                                document=dp,
                                caption=item_cap,
                                file_name=it["clean_name"],
                            )
                        sent_msgs.append(lm)
            finally:
                shutil.rmtree(batch_dir, ignore_errors=True)

        if not sent_msgs or len(sent_msgs) != len(batch):
            raise RuntimeError(f"相册批次 #{batch_idx} 转存未返回等量消息对象")

        real_mg_id = None
        for sm in sent_msgs:
            mg_val = getattr(sm, "media_group_id", None) or getattr(sm, "grouped_id", None)
            if mg_val:
                real_mg_id = str(mg_val)
                break
        effective_group_id = real_mg_id or str(group_id_str)

        for it, log_msg in zip(batch, sent_msgs):
            log_media = (
                getattr(log_msg, log_msg.media.value, None)
                if getattr(log_msg, "media", None) and hasattr(log_msg.media, "value")
                else None
            )
            if log_media is None:
                _, log_media = get_media_type_and_obj(log_msg)

            file_unique_id = None
            if log_media is not None:
                try:
                    file_unique_id = db.save_tg_media(
                        log_msg,
                        log_media,
                        custom_file_name=it["clean_name"] if clean_filenames else None,
                        custom_caption=cleaned_group_caption if rebrand_enabled else None,
                        custom_media_group_id=effective_group_id,
                    )
                    try:
                        from thumbnail_worker import get_thumbnail_worker
                        get_thumbnail_worker().enqueue(log_msg.id, chat_id=target_bin)
                    except Exception:
                        pass
                except Exception as db_err:
                    logger.error(f"相册成员写入数据库失败: {db_err}", exc_info=True)

            try:
                file_hash = get_hash(log_msg, Var.HASH_LENGTH)
            except Exception:
                file_hash = "000000"

            base_url = Var.URL or "/"
            if not base_url.endswith("/"):
                base_url += "/"
            stream_link = f"{base_url}{log_msg.id}/{quote_plus(it['clean_name'])}?hash={file_hash}"
            short_link = f"{base_url}{file_hash}{log_msg.id}"

            all_results.append({
                "status": "success",
                "mode": used_mode,
                "msg_id": log_msg.id,
                "source_msg_id": it["source_msg_id"],
                "name": it["clean_name"],
                "full_link": stream_link,
                "short_link": short_link,
                "file_unique_id": file_unique_id,
                "media_group_id": effective_group_id,
            })

    return all_results


def select_active_protocol_account(account_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    从 tg_protocol_accounts 资产池中选择一个可用于频道采集的协议号。
    注意：即便协议号在 BotFather 达到 20 个 Bot 上限 (limit_reached)，其作为用户账号依然可以正常加群与拉取媒体。
    """
    if account_id is not None:
        acc = db.get_protocol_account_by_id(int(account_id))
        if acc and acc.get("session_data"):
            return acc
        return None

    accounts = db.list_protocol_accounts()
    valid_statuses = ("active", "limit_reached", "cooling_down")
    for acc in accounts:
        if acc.get("status") in valid_statuses and acc.get("session_data"):
            return acc
    for acc in accounts:
        if acc.get("session_data"):
            return acc
    return None


def _format_size(num_bytes: int) -> str:
    if not num_bytes or num_bytes <= 0:
        return "未知大小"
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


class HarvesterTaskManager:
    """私密/受限频道后台异步采集任务管理器"""

    _instance: Optional["HarvesterTaskManager"] = None

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._cancel_requested: bool = False
        self._state: Dict[str, Any] = {
            "status": "idle",  # idle | running | completed | failed | cancelled
            "task_id": "",
            "total_messages": 0,
            "current_index": 0,
            "success_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "current_mode": "idle",  # idle | fast_copy | restricted_relay
            "current_file": "",
            "speed_text": "",
            "logs": [],
            "results": [],
            "account_phone": None,
            "owner_uid": None,
            "owner_role": None,
            "error": None,
        }

    @classmethod
    def get_instance(cls) -> "HarvesterTaskManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _append_log(self, message: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {message}"
        logger.info(message)
        self._state["logs"].append(line)
        if len(self._state["logs"]) > 200:
            self._state["logs"] = self._state["logs"][-200:]

    def _set_speed_text(self, text: str):
        self._state["speed_text"] = text

    def get_status(self) -> Dict[str, Any]:
        return dict(self._state)

    async def cancel_task(self) -> Dict[str, Any]:
        if self._state["status"] != "running":
            return {"success": False, "error": "当前没有正在运行的采集任务"}
        self._cancel_requested = True
        self._append_log("🛑 收到中止指令，正在安全停止当前采集流水线...")
        return {"success": True, "message": "已发送中止信号，任务即将停止"}

    async def start_task(
        self,
        links_text: str,
        invite_link: Optional[str] = None,
        account_id: Optional[int] = None,
        rebrand_enabled: bool = True,
        bin_channel: Optional[Union[int, str]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
        owner_uid: Optional[int] = None,
        owner_role: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self._state["status"] == "running" and self._task and not self._task.done():
            return {"success": False, "error": "当前已有采集任务正在执行中，请等待完成或先取消"}
        if owner_role and owner_role != "admin" and not bin_channel:
            return {"success": False, "error": "普通租户未分配专属存储频道，无法执行采集任务"}

        targets, invite_links = parse_telegram_post_links(links_text, default_invite=invite_link)
        if not targets:
            return {
                "success": False,
                "error": "未解析到有效的 Telegram 频道帖子链接，请检查格式（如 https://t.me/COSAVMY/11164 或 https://t.me/c/123456/10-20）",
            }

        total_msgs = sum(len(t.msg_ids) for t in targets)
        task_id = f"harvest_{int(time.time())}_{secrets.token_hex(3)}"
        self._cancel_requested = False
        self._state = {
            "status": "running",
            "task_id": task_id,
            "total_messages": total_msgs,
            "current_index": 0,
            "success_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "current_mode": "fast_copy",
            "current_file": "正在初始化采集引擎...",
            "speed_text": "",
            "logs": [],
            "results": [],
            "account_phone": None,
            "owner_uid": owner_uid,
            "owner_role": owner_role,
            "error": None,
        }

        self._append_log(f"🚀 启动频道采集任务 ({task_id})，共解析到 {len(targets)} 个频道、{total_msgs} 条入口消息")

        self._task = asyncio.create_task(
            self._run_pipeline(
                targets=targets,
                invite_links=invite_links,
                account_id=account_id,
                rebrand_enabled=rebrand_enabled,
                bin_channel=bin_channel,
                progress_callback=progress_callback,
            )
        )
        return {
            "success": True,
            "task_id": task_id,
            "total_messages": total_msgs,
            "message": "私密/受限频道采集流水线已启动",
        }

    async def _notify_progress(self, progress_callback: Optional[Callable[[Dict[str, Any]], Any]]):
        if not progress_callback:
            return
        try:
            res = progress_callback(self.get_status())
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            logger.debug(f"进度回调执行失败: {e}")

    async def _process_album_group(
        self,
        album_msgs: List[Any],
        group_id_str: str,
        primary_caption: str,
        user_client: Any,
        write_bot: Any,
        target_reader: Any,
        chat_entity: Any,
        rebrand_enabled: bool,
        bin_channel: Optional[Union[int, str]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        """处理相册媒体组（整组并发拉取 ➔ copy_media_group / send_media_group 聚合重传）"""
        valid_msgs = [m for m in album_msgs if get_media_type_and_obj(m)[0] and get_media_type_and_obj(m)[1]]
        if not valid_msgs:
            self._state["skipped_count"] += len(album_msgs)
            self._state["current_index"] += len(album_msgs)
            self._append_log(f"⏭️ 相册 (Group: {group_id_str}) 中不含可识别媒体文件，跳过")
            return

        total_size = sum(extract_media_dimensions(m, get_media_type_and_obj(m)[1])[3] for m in valid_msgs)
        is_prot = any(is_message_protected(m) for m in valid_msgs)
        self._state["current_mode"] = "restricted_relay" if is_prot else "fast_copy"
        self._state["current_file"] = f"相册媒体组 ({len(valid_msgs)} 项, {_format_size(total_size)})"

        mode_label = "🔓受限相册聚合重传" if is_prot else "⚡相册零流量秒传"
        self._append_log(
            f"📸 [{mode_label}] 正在处理相册 (Group: {group_id_str})，共 {len(valid_msgs)} 个媒体项 ({_format_size(total_size)})..."
        )
        await self._notify_progress(progress_callback)

        last_dl_ts = time.time()
        last_dl_bytes = 0

        def _on_dl_prog(current: int, total: int):
            nonlocal last_dl_ts, last_dl_bytes
            if self._cancel_requested:
                raise asyncio.CancelledError("用户中止了采集任务")
            now = time.time()
            dt = now - last_dl_ts
            if dt >= 0.8 or (total and current >= total):
                speed_mb = ((current - last_dl_bytes) / max(dt, 0.001)) / (1024 * 1024)
                pct = int(current * 100 / total) if total else 0
                if not str(self._state.get("speed_text", "")).startswith("⬇️ [Bot集群"):
                    self._state["speed_text"] = f"⬇️ 下载 {speed_mb:.1f} MB/s ({pct}%)"
                last_dl_ts = now
                last_dl_bytes = current

        last_up_ts = time.time()
        last_up_bytes = 0

        def _on_up_prog(current: int, total: int):
            nonlocal last_up_ts, last_up_bytes
            if self._cancel_requested:
                raise asyncio.CancelledError("用户中止了采集任务")
            now = time.time()
            dt = now - last_up_ts
            if dt >= 0.8 or (total and current >= total):
                speed_mb = ((current - last_up_bytes) / max(dt, 0.001)) / (1024 * 1024)
                pct = int(current * 100 / total) if total else 0
                self._state["speed_text"] = f"⬆️ [8通道并发] 上传 {speed_mb:.1f} MB/s ({pct}%)"
                last_up_ts = now
                last_up_bytes = current

        def _report_speed(text: str):
            self._state["speed_text"] = text

        target_bin = bin_channel or Var.BIN_CHANNEL
        album_results = await harvest_media_group(
            album_msgs=valid_msgs,
            group_id_str=group_id_str,
            primary_caption=primary_caption,
            user_client=user_client,
            bot_client=write_bot,
            bin_channel=target_bin,
            rebrand_enabled=rebrand_enabled,
            chat_target=chat_entity,
            dl_client=target_reader,
            progress_cb=_on_dl_prog,
            upload_progress_cb=_on_up_prog,
            speed_reporter=_report_speed,
            log_fn=lambda txt: self._append_log(txt),
        )

        self._state["speed_text"] = ""
        for res in album_results:
            if res.get("status") == "success":
                self._state["success_count"] += 1
                self._state["current_mode"] = res.get("mode", "restricted_relay")
                self._state["results"].append(res)
                m_label = "⚡秒传" if res.get("mode") == "fast_copy" else "🔓相册聚合重传"
                self._append_log(
                    f"✅ [{m_label}] #{res.get('source_msg_id')} -> {res.get('name')} 入库成功 (ID: {res.get('msg_id')}, 相册: {res.get('media_group_id')})"
                )
            else:
                self._state["skipped_count"] += 1
                self._append_log(f"⏭️ #{res.get('source_msg_id')} 跳过: {res.get('reason')}")

        self._state["current_index"] += len(album_msgs)

    async def _process_one_media_item(
        self,
        msg: Any,
        user_client: Any,
        write_bot: Any,
        rebrand_enabled: bool,
        fallback_caption: Optional[str],
        custom_media_group_id: Optional[str],
        progress_callback: Optional[Callable[[Dict[str, Any]], Any]],
        dl_client: Any = None,
        dl_bot_idx: Optional[int] = None,
        chat_target: Any = None,
        bin_channel: Optional[Union[int, str]] = None,
    ):
        """处理单个已确认包含媒体的消息项（含下载/上传实时速率跟踪与入库）"""
        msg_id = getattr(msg, "id", 0)
        media_type, media_obj = get_media_type_and_obj(msg)
        if not media_type or not media_obj:
            self._state["skipped_count"] += 1
            self._append_log(f"⏭️ 消息 #{msg_id} 不含可识别媒体文件，跳过")
            return

        _, _, _, file_size = extract_media_dimensions(msg, media_obj)
        preview_name = extract_raw_filename(msg, media_type, media_obj, fallback_caption)
        self._state["current_file"] = preview_name

        is_prot = is_message_protected(msg)
        self._state["current_mode"] = "restricted_relay" if is_prot else "fast_copy"

        # 确定实际下载客户端标识 (Bot 或 协议号)
        actual_dl_client = dl_client or user_client or write_bot
        dl_label = "Bot"
        if actual_dl_client is not None:
            me_obj = getattr(actual_dl_client, "me", None)
            uname = getattr(me_obj, "username", None) if me_obj else getattr(actual_dl_client, "username", None)
            if uname:
                dl_label = f"Bot: @{uname}"
            elif dl_bot_idx is not None:
                dl_label = f"Bot #{dl_bot_idx}"
            elif hasattr(actual_dl_client, "iter_messages") or hasattr(actual_dl_client, "get_me"):
                phone = self._state.get("account_phone") or "协议号"
                dl_label = f"协议号: {phone}"
            elif hasattr(actual_dl_client, "name"):
                dl_label = str(actual_dl_client.name)

        if is_prot:
            self._append_log(
                f"🔓 [{dl_label}] 检测到受限内容，执行流式下载与破除重传: #{msg_id} ({preview_name}, {_format_size(file_size)})..."
            )
        else:
            self._append_log(
                f"⏳ [{self._state['current_index']}/{self._state['total_messages']}] "
                f"正在处理 #{msg_id} ({media_type}: {preview_name}, {_format_size(file_size)})..."
            )
        await self._notify_progress(progress_callback)

        last_dl_ts = time.time()
        last_dl_bytes = 0

        def _on_dl_progress(current: int, total: int):
            nonlocal last_dl_ts, last_dl_bytes
            if self._cancel_requested:
                raise asyncio.CancelledError("用户中止了采集任务")
            now = time.time()
            dt = now - last_dl_ts
            if dt >= 0.8 or (total and current >= total):
                speed_mb = ((current - last_dl_bytes) / max(dt, 0.001)) / (1024 * 1024)
                pct = int(current * 100 / total) if total else 0
                if not str(self._state.get("speed_text", "")).startswith("⬇️ [Bot集群"):
                    self._state["speed_text"] = f"⬇️ [{dl_label}] 下载 {speed_mb:.1f} MB/s ({pct}%)"
                last_dl_ts = now
                last_dl_bytes = current

        last_up_ts = time.time()
        last_up_bytes = 0

        def _on_up_progress(current: int, total: int):
            nonlocal last_up_ts, last_up_bytes
            if self._cancel_requested:
                raise asyncio.CancelledError("用户中止了采集任务")
            now = time.time()
            dt = now - last_up_ts
            if dt >= 0.8 or (total and current >= total):
                speed_mb = ((current - last_up_bytes) / max(dt, 0.001)) / (1024 * 1024)
                pct = int(current * 100 / total) if total else 0
                self._state["speed_text"] = f"⬆️ [8通道并发] 上传 {speed_mb:.1f} MB/s ({pct}%)"
                last_up_ts = now
                last_up_bytes = current

        target_bin = bin_channel or Var.BIN_CHANNEL
        res = await harvest_single_message(
            msg=msg,
            user_client=user_client,
            bot_client=write_bot,
            bin_channel=target_bin,
            rebrand_enabled=rebrand_enabled,
            progress_cb=_on_dl_progress,
            upload_progress_cb=_on_up_progress,
            fallback_caption=fallback_caption,
            custom_media_group_id=custom_media_group_id,
            dl_client=dl_client,
            chat_target=chat_target,
            speed_reporter=lambda txt: self._set_speed_text(txt),
            log_fn=lambda txt: self._append_log(txt),
        )
        self._state["speed_text"] = ""

        if res.get("status") == "success":
            self._state["success_count"] += 1
            self._state["current_mode"] = res.get("mode", "fast_copy")
            self._state["results"].append(res)
            mode_label = "⚡秒传" if res.get("mode") == "fast_copy" else "🔓受限重传"
            self._append_log(
                f"✅ [{mode_label}] #{msg_id} -> {res.get('name')} 入库成功 (ID: {res.get('msg_id')})"
            )
        else:
            self._state["skipped_count"] += 1
            self._append_log(f"⏭️ #{msg_id} 跳过: {res.get('reason')}")

    async def _run_pipeline(
        self,
        targets: List[HarvestTarget],
        invite_links: List[str],
        account_id: Optional[int],
        rebrand_enabled: bool,
        bin_channel: Optional[Union[int, str]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        user_client = None
        using_telethon = False
        write_bot = get_write_bot_client(target_bin=bin_channel)
        if write_bot is not None and bin_channel:
            await ensure_peer_cached(write_bot, bin_channel)

        has_private_target = any(t.is_private for t in targets)
        need_protocol_account = bool(has_private_target or invite_links)

        async def _ensure_user_client() -> Any:
            nonlocal user_client, using_telethon
            if user_client is not None:
                return user_client
            acc = select_active_protocol_account(account_id)
            if not acc:
                return None
            phone = acc.get("phone", f"ID:{acc.get('id')}")
            self._state["account_phone"] = phone
            self._append_log(f"🔐 选用协议号资产: {phone}，正在建立 MTProto 内存会话...")
            try:
                from telethon import TelegramClient
                from telethon.sessions import StringSession
                telethon_str = parse_session_to_telethon_string(acc["session_data"])
                user_client = TelegramClient(
                    StringSession(telethon_str),
                    Var.API_ID or 2040,
                    Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
                )
                await user_client.connect()
                if not await user_client.is_user_authorized():
                    raise RuntimeError(f"协议号 {phone} 会话未授权或已失效")
                using_telethon = True
                self._append_log(f"✅ 协议号 {phone} 已连接就绪 (MTProto Layer 227 深度解析引擎)")
            except ImportError:
                pyro_session = parse_session_to_pyrogram_string(
                    acc["session_data"],
                    default_api_id=Var.API_ID or 2040,
                )
                from pyrogram import Client
                user_client = Client(
                    name=f"harvester_{acc.get('id', 0)}_{secrets.token_hex(4)}",
                    api_id=Var.API_ID or 2040,
                    api_hash=Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
                    session_string=pyro_session,
                    in_memory=True,
                    no_updates=True,
                )
                await user_client.start()
                self._append_log(f"✅ 协议号 {phone} 已连接就绪")
            return user_client

        try:
            # 1. 判断是否需预先启动协议号
            if need_protocol_account:
                await _ensure_user_client()
                if user_client is None:
                    raise RuntimeError(
                        "检测到私密频道或邀请链接，但当前协议号资产池为空。请先在「自动铸机 (/botfather)」页面导入至少 1 个协议号。"
                    )
            else:
                if account_id is not None:
                    # 管理员显式指定了协议号，预先初始化备用
                    await _ensure_user_client()
                if user_client is None:
                    self._append_log("🤖 待采集目标均为公开频道，启用 Telegram Bot 集群直采模式（协议号零接入、零消耗）")

            # 2. 如果提供了私密频道邀请链接，由协议号自动申请加入
            if user_client and invite_links:
                for inv in invite_links:
                    if self._cancel_requested:
                        break
                    try:
                        self._append_log(f"🚪 正在通过邀请链接加入私密频道: {inv}")
                        if using_telethon:
                            from telethon.tl.functions.messages import ImportChatInviteRequest
                            from telethon.errors import UserAlreadyParticipantError
                            m_inv = INVITE_LINK_RE.search(inv)
                            inv_hash = m_inv.group(1) if m_inv else inv.lstrip("+")
                            try:
                                await user_client(ImportChatInviteRequest(inv_hash))
                                self._append_log(f"✅ 已成功加入频道: {inv}")
                            except UserAlreadyParticipantError:
                                self._append_log(f"ℹ️ 协议号已是该频道成员: {inv}")
                        else:
                            from pyrogram import errors as pyro_errors
                            try:
                                await user_client.join_chat(inv)
                                self._append_log(f"✅ 已成功加入频道: {inv}")
                            except getattr(pyro_errors, "UserAlreadyParticipant", Exception):
                                self._append_log(f"ℹ️ 协议号已是该频道成员: {inv}")
                    except Exception as join_err:
                        self._append_log(f"⚠️ 通过邀请链接 {inv} 加入频道时返回提示: {join_err}")

            # 3. 逐个频道、逐条消息深度拉取（支持相册自动展开与跳转帖递归追踪）
            target_idx = 0
            while target_idx < len(targets):
                if self._cancel_requested:
                    break

                target = targets[target_idx]
                target_idx += 1
                chat_id = target.chat_id
                self._append_log(f"📂 正在访问频道 {chat_id}，准备解析 {len(target.msg_ids)} 条目标链接...")

                # 智能选路：为当前频道分配 reader_client 与 dl_client
                target_reader = None
                target_bot_idx = None
                target_using_telethon = False

                if not target.is_private:
                    # 公开频道：强制优先指派 Worker Bot 独立读取与流式下载，保护协议号零消耗
                    best_idx, best_bot = get_worker_bot_client()
                    if best_bot is not None:
                        target_reader = best_bot
                        target_bot_idx = best_idx
                        target_using_telethon = False
                        me_obj = getattr(best_bot, "me", None)
                        uname = getattr(me_obj, "username", None) if me_obj else f"Worker_{best_idx if best_idx is not None else 0}"
                        self._append_log(f"🤖 [公开频道] 指派 Telegram Bot @{uname} 执行消息解析与底层流式下载（保护协议号零消耗）")

                # 若为私密频道或 Bot 未就绪，使用已连接的协议号或按需连接
                if target_reader is None:
                    if user_client is None:
                        await _ensure_user_client()
                    if user_client is not None:
                        target_reader = user_client
                        target_using_telethon = using_telethon
                    else:
                        target_reader = write_bot
                        target_using_telethon = False

                if target_reader is None:
                    raise RuntimeError("没有可用的 Telegram 客户端实例来读取目标频道")

                chat_entity: Any = chat_id
                try:
                    if target_using_telethon:
                        chat_entity = await target_reader.get_entity(chat_id)
                        prot_flag = "受保护: 禁止转发" if getattr(chat_entity, "noforwards", False) else "允许转发"
                        title_str = getattr(chat_entity, "title", chat_id)
                        self._append_log(f"📡 已锁定频道「{title_str}」({prot_flag})")
                    elif hasattr(target_reader, "get_chat"):
                        c_obj = await target_reader.get_chat(chat_id)
                        prot_flag = "受保护: 禁止转发" if getattr(c_obj, "has_protected_content", False) else "允许转发"
                        title_str = getattr(c_obj, "title", chat_id)
                        self._append_log(f"📡 已锁定频道「{title_str}」({prot_flag})")
                except Exception as peer_err:
                    logger.debug(f"预热频道 {chat_id} Peer 缓存提示: {peer_err}")
                    # 若 Bot 访问公开频道出现异常且协议号可用，自动平滑回退至协议号
                    if not target_using_telethon:
                        if user_client is None:
                            await _ensure_user_client()
                        if user_client is not None:
                            self._append_log(f"⚠️ Worker Bot 访问频道提示: {peer_err}，自动回退调度协议号")
                            target_reader = user_client
                            target_bot_idx = None
                            target_using_telethon = using_telethon
                            if target_using_telethon and hasattr(target_reader, "get_entity"):
                                try:
                                    chat_entity = await target_reader.get_entity(chat_id)
                                except Exception:
                                    pass

                processed_ids: Set[int] = set()
                pending_ids: List[int] = list(target.msg_ids)

                while pending_ids:
                    if self._cancel_requested:
                        break

                    msg_id = pending_ids.pop(0)
                    if msg_id in processed_ids:
                        continue

                    try:
                        # 深度拉取并探测是否为相册媒体组 (grouped_id)
                        expanded_msgs, group_id_str, primary_caption = await fetch_and_expand_post(
                            reader_client=target_reader,
                            chat_target=chat_entity,
                            msg_id=msg_id,
                        )

                        if not expanded_msgs:
                            processed_ids.add(msg_id)
                            self._state["current_index"] += 1
                            self._state["skipped_count"] += 1
                            self._append_log(f"⏭️ 消息 #{msg_id} 不存在或为空消息，跳过")
                            await self._notify_progress(progress_callback)
                            continue

                        # 情况 A：识别为多文件相册媒体组 (Album / Media Group)
                        if group_id_str and len(expanded_msgs) > 1:
                            unseen_album_msgs = [
                                m for m in expanded_msgs
                                if getattr(m, "id", None) not in processed_ids
                            ]
                            already_queued_count = sum(
                                1 for m in unseen_album_msgs
                                if (getattr(m, "id", None) == msg_id or getattr(m, "id", None) in pending_ids)
                            )
                            extra_count = max(0, len(unseen_album_msgs) - already_queued_count)
                            if extra_count > 0:
                                self._state["total_messages"] += extra_count

                            album_ids_list = [getattr(m, "id", 0) for m in unseen_album_msgs]
                            video_cnt = sum(1 for m in unseen_album_msgs if get_media_type_and_obj(m)[0] == "video")
                            photo_cnt = sum(1 for m in unseen_album_msgs if get_media_type_and_obj(m)[0] == "photo")
                            self._append_log(
                                f"📸 深度解析链接 #{msg_id}：发现相册媒体组 (Group: {group_id_str})，"
                                f"自动展开关联的 {len(unseen_album_msgs)} 个媒体 ({photo_cnt} 图 / {video_cnt} 视频): {album_ids_list}"
                            )
                            await self._notify_progress(progress_callback)

                            for album_item in unseen_album_msgs:
                                processed_ids.add(getattr(album_item, "id", 0))

                            try:
                                await self._process_album_group(
                                    album_msgs=unseen_album_msgs,
                                    group_id_str=group_id_str,
                                    primary_caption=primary_caption,
                                    user_client=user_client,
                                    write_bot=write_bot,
                                    target_reader=target_reader,
                                    chat_entity=chat_entity,
                                    rebrand_enabled=rebrand_enabled,
                                    bin_channel=bin_channel,
                                    progress_callback=progress_callback,
                                )
                            except asyncio.CancelledError:
                                self._cancel_requested = True
                                break
                            except Exception as album_err:
                                self._state["failed_count"] += len(unseen_album_msgs)
                                self._state["current_index"] += len(unseen_album_msgs)
                                self._append_log(f"❌ 聚合处理相册 (Group: {group_id_str}) 失败: {album_err}")
                                logger.warning(f"采集相册异常 (Group: {group_id_str}): {album_err}", exc_info=True)

                            await self._notify_progress(progress_callback)
                            continue

                        # 情况 B：单条消息
                        single_msg = expanded_msgs[0]
                        processed_ids.add(msg_id)
                        media_type, _ = get_media_type_and_obj(single_msg)

                        # 若单条消息不含媒体，深度检查是否包含跳转链接 / 导航按钮
                        if not media_type:
                            nested_targets, nested_invites = extract_nested_post_links(single_msg)
                            if nested_invites:
                                u_client = await _ensure_user_client()
                                if u_client and using_telethon:
                                    from telethon.tl.functions.messages import ImportChatInviteRequest
                                    from telethon.errors import UserAlreadyParticipantError
                                    for n_inv in nested_invites:
                                        m_inv = INVITE_LINK_RE.search(n_inv)
                                        inv_hash = m_inv.group(1) if m_inv else n_inv.lstrip("+")
                                        try:
                                            await u_client(ImportChatInviteRequest(inv_hash))
                                        except UserAlreadyParticipantError:
                                            pass
                                        except Exception:
                                            pass

                            if nested_targets and len(targets) < 10:
                                added_msgs = 0
                                for nt in nested_targets:
                                    if str(nt.chat_id).lower() == str(chat_id).lower():
                                        for n_mid in nt.msg_ids:
                                            if n_mid not in processed_ids and n_mid not in pending_ids:
                                                pending_ids.append(n_mid)
                                                added_msgs += 1
                                    else:
                                        targets.append(nt)
                                        added_msgs += len(nt.msg_ids)
                                if added_msgs > 0:
                                    self._state["total_messages"] += (added_msgs - 1)
                                    self._append_log(
                                        f"🔗 消息 #{msg_id} 为导航/索引帖，已深度提取出 {added_msgs} 条嵌套帖子链接并加入采集队列"
                                    )
                                    await self._notify_progress(progress_callback)
                                    continue

                            self._state["current_index"] += 1
                            self._state["skipped_count"] += 1
                            self._append_log(f"⏭️ 消息 #{msg_id} 不含媒体文件（纯文本/服务消息），跳过")
                            await self._notify_progress(progress_callback)
                            continue

                        # 正常处理单条含媒体消息
                        self._state["current_index"] += 1
                        _, single_mo = get_media_type_and_obj(single_msg)
                        single_size = getattr(single_mo, "file_size", 0) if single_mo else 0
                        cur_bot_idx, cur_bot, cur_msg = await _resolve_least_loaded_bot_for_msg(
                            current_bot_idx=target_bot_idx,
                            current_bot=target_reader,
                            chat_target=chat_entity,
                            msg=single_msg,
                            file_size=single_size,
                        )

                        await self._process_one_media_item(
                            msg=cur_msg,
                            user_client=user_client,
                            write_bot=write_bot,
                            rebrand_enabled=rebrand_enabled,
                            fallback_caption=primary_caption,
                            custom_media_group_id=group_id_str,
                            progress_callback=progress_callback,
                            dl_client=cur_bot,
                            dl_bot_idx=cur_bot_idx,
                            chat_target=chat_entity,
                            bin_channel=bin_channel,
                        )

                    except asyncio.CancelledError:
                        self._cancel_requested = True
                        break
                    except Exception as msg_err:
                        self._state["current_index"] += 1
                        self._state["failed_count"] += 1
                        self._append_log(f"❌ 处理消息 #{msg_id} 失败: {msg_err}")
                        logger.warning(f"采集消息 #{msg_id} 异常: {msg_err}", exc_info=True)

                    await self._notify_progress(progress_callback)
                    if not self._cancel_requested and self._state["current_index"] < self._state["total_messages"]:
                        await asyncio.sleep(1.2)

            if self._cancel_requested:
                self._state["status"] = "cancelled"
                self._state["current_file"] = "任务已取消"
                self._append_log(
                    f"🛑 采集任务已中止：成功 {self._state['success_count']}，跳过 {self._state['skipped_count']}，失败 {self._state['failed_count']}"
                )
            else:
                self._state["status"] = "completed"
                self._state["current_file"] = "全部处理完成"
                self._append_log(
                    f"🎉 采集任务圆满完成！成功入库 {self._state['success_count']} 个文件，跳过 {self._state['skipped_count']}，失败 {self._state['failed_count']}"
                )

        except Exception as e:
            self._state["status"] = "failed"
            self._state["error"] = str(e)
            self._state["current_file"] = "任务异常终止"
            self._append_log(f"💥 采集流水线异常终止: {e}")
            logger.error(f"采集流水线致命错误: {e}", exc_info=True)
        finally:
            self._state["speed_text"] = ""
            if user_client is not None:
                try:
                    from WebStreamer.utils.fast_uploader import close_upload_sessions
                    await close_upload_sessions(user_client)
                except Exception:
                    pass
                try:
                    if using_telethon and hasattr(user_client, "disconnect"):
                        await user_client.disconnect()
                    elif hasattr(user_client, "stop"):
                        await user_client.stop()
                    self._append_log("🔌 协议号临时内存会话已安全断开")
                except Exception:
                    pass
            await self._notify_progress(progress_callback)

