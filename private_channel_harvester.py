"""
Telegram 私密/受限频道采集与无痕洗白转存引擎 (Private & Restricted Channel Harvester)
====================================================================================
支持：
1. 私密频道帖子链接 (https://t.me/c/<raw_id>/<msg_id>) 及连号区间 (100-150) 解析；
2. 公开频道帖子链接 (https://t.me/<username>/<msg_id>) 及连号区间解析；
3. 私密入群邀请码 (https://t.me/+<hash> / joinchat/<hash>) 自动加群；
4. 智能双模转存管线：
   - 模式一 (fast_copy)：未开启内容保护时，优先通过 copy_message 零流量秒传并清洗配文；
   - 模式二 (restricted_relay)：开启禁止转发 (has_protected_content) 时，通过协议号底层流式下载、
     执行文件名去广告与配文洗白后，由频道写入客户端重新上传至 BIN_CHANNEL 并自动清理临时文件。
"""

import os
import re
import time
import asyncio
import logging
import secrets
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any, Callable, Union
from urllib.parse import quote_plus

import db
from configer import get_config_value
from session_adapter import parse_session_to_pyrogram_string
from WebStreamer.vars import Var
from WebStreamer.utils import get_hash, get_name
from WebStreamer.utils.rebrand_cleaner import (
    clean_and_rebrand_caption,
    clean_drive_filename,
)

logger = logging.getLogger("private_harvester")

# 正则表达式定义
INVITE_LINK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
RAW_INVITE_HASH_RE = re.compile(r"^\+([A-Za-z0-9_-]{8,64})$")

PRIVATE_POST_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/c/(\d+)/(\d+)(?:\s*-\s*(\d+))?",
    re.IGNORECASE,
)

PUBLIC_POST_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?!c/|\+|joinchat/)([A-Za-z0-9_]{4,32})/(\d+)(?:\s*-\s*(\d+))?",
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
    解析输入文本中的私密/公开频道帖子链接（支持连号区间）及私密频道邀请链接。

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
        if username.lower() in ("c", "joinchat", "addstickers", "addtheme", "proxy", "socks", "share"):
            continue
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
    """从 Pyrogram Message 中提取媒体类型与媒体对象"""
    if not msg or getattr(msg, "empty", False):
        return None, None
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
        if obj is not None:
            return attr, obj
    return None, None


def get_write_bot_client(preferred_bot: Any = None) -> Any:
    """获取具备 BIN_CHANNEL 写入权限的 Bot 客户端"""
    if preferred_bot is not None:
        return preferred_bot
    try:
        import WebStreamer.bot as bot_mod
        write_indices = getattr(bot_mod, "channel_write_clients", set())
        multi_clients = getattr(bot_mod, "multi_clients", {})
        work_loads = getattr(bot_mod, "work_loads", {})
        if write_indices and multi_clients:
            valid = [i for i in write_indices if i in multi_clients]
            if valid:
                best_idx = min(valid, key=lambda idx: work_loads.get(idx, 0))
                return multi_clients[best_idx]
        return getattr(bot_mod, "StreamBot", None)
    except Exception:
        return None


async def harvest_single_message(
    msg: Any,
    user_client: Any = None,
    bot_client: Any = None,
    bin_channel: Optional[int] = None,
    rebrand_enabled: Optional[bool] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """
    对单条目标频道消息执行智能双模转存（零流量秒传 vs 受限下载重传）并入库。
    """
    target_bin = bin_channel or Var.BIN_CHANNEL
    if not target_bin:
        raise ValueError("BIN_CHANNEL 未配置，无法转存媒体到网盘")

    write_bot = get_write_bot_client(bot_client)
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

    try:
        raw_file_name = get_name(msg) or f"media_{getattr(msg, 'id', int(time.time()))}"
    except Exception:
        raw_file_name = getattr(media_obj, "file_name", None) or f"media_{getattr(msg, 'id', int(time.time()))}.bin"

    cleaned_file_name = (
        clean_drive_filename(
            raw_file_name,
            clean_enabled=clean_filenames,
            custom_rules=custom_rules,
        )
        if clean_filenames
        else raw_file_name
    )

    raw_caption = getattr(msg, "caption", None)
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

    # 判断是否受内容保护限制 (has_protected_content / noforwards)
    chat_obj = getattr(msg, "chat", None)
    is_protected = bool(
        getattr(msg, "has_protected_content", False)
        or getattr(chat_obj, "has_protected_content", False)
    )

    log_msg = None
    used_mode = "fast_copy"
    source_chat_id = getattr(chat_obj, "id", None)
    source_msg_id = getattr(msg, "id", None)

    # =========================================================================
    # 模式一：尝试零流量秒传 (fast_copy)
    # =========================================================================
    if not is_protected and source_chat_id and source_msg_id:
        # 1) 优先尝试由具备频道写权限的 Bot 直接 copy_message（适用于公开频道或 Bot 已在源频道）
        if write_bot is not None and hasattr(write_bot, "copy_message"):
            try:
                log_msg = await write_bot.copy_message(
                    chat_id=target_bin,
                    from_chat_id=source_chat_id,
                    message_id=source_msg_id,
                    caption=cleaned_caption,
                )
                used_mode = "fast_copy"
            except Exception as bot_copy_err:
                logger.debug(f"Bot 直接 copy_message 未命中 ({bot_copy_err})，尝试协议号中转或下载重传")
                log_msg = None

        # 2) 若 Bot 不在私密源频道，尝试由协议号直接 copy_message 到目标频道（若协议号也是目标频道管理员）
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
        dl_client = user_client or write_bot
        up_client = write_bot or user_client

        if dl_client is None or not hasattr(dl_client, "download_media"):
            raise RuntimeError("当前客户端不支持 download_media，无法破除受限内容")

        tmp_dir = get_harvester_temp_dir()
        safe_base = re.sub(r'[\\/:*?"<>|]+', "_", cleaned_file_name)
        temp_file_path = os.path.join(
            tmp_dir,
            f"harvest_{abs(int(source_chat_id or 0))}_{source_msg_id or 0}_{secrets.token_hex(3)}_{safe_base}",
        )
        downloaded_path = None
        try:
            if progress_cb:
                downloaded_path = await dl_client.download_media(
                    msg,
                    file_name=temp_file_path,
                    progress=progress_cb,
                )
            else:
                downloaded_path = await dl_client.download_media(
                    msg,
                    file_name=temp_file_path,
                )

            if not downloaded_path or not os.path.exists(downloaded_path):
                raise RuntimeError(f"媒体文件下载失败或文件为空 (msg_id={source_msg_id})")

            if media_type == "video" and hasattr(up_client, "send_video"):
                log_msg = await up_client.send_video(
                    chat_id=target_bin,
                    video=downloaded_path,
                    caption=cleaned_caption,
                    file_name=cleaned_file_name,
                    duration=int(getattr(media_obj, "duration", 0) or 0),
                    width=int(getattr(media_obj, "width", 0) or 0),
                    height=int(getattr(media_obj, "height", 0) or 0),
                    supports_streaming=True,
                )
            elif media_type == "audio" and hasattr(up_client, "send_audio"):
                log_msg = await up_client.send_audio(
                    chat_id=target_bin,
                    audio=downloaded_path,
                    caption=cleaned_caption,
                    file_name=cleaned_file_name,
                    duration=int(getattr(media_obj, "duration", 0) or 0),
                    performer=getattr(media_obj, "performer", None),
                    title=getattr(media_obj, "title", None),
                )
            elif media_type == "photo" and hasattr(up_client, "send_photo"):
                log_msg = await up_client.send_photo(
                    chat_id=target_bin,
                    photo=downloaded_path,
                    caption=cleaned_caption,
                )
            else:
                log_msg = await up_client.send_document(
                    chat_id=target_bin,
                    document=downloaded_path,
                    caption=cleaned_caption,
                    file_name=cleaned_file_name,
                )
        finally:
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
        if getattr(log_msg, "media", None)
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
                custom_file_name=cleaned_file_name if clean_filenames else None,
                custom_caption=cleaned_caption if rebrand_enabled else None,
            )
            try:
                from thumbnail_worker import get_thumbnail_worker
                get_thumbnail_worker().enqueue(log_msg.id)
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
    }


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
    # 兜底：只要有 session_data 的账号均可尝试
    for acc in accounts:
        if acc.get("session_data"):
            return acc
    return None


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
        progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        if self._state["status"] == "running" and self._task and not self._task.done():
            return {"success": False, "error": "当前已有采集任务正在执行中，请等待完成或先取消"}

        targets, invite_links = parse_telegram_post_links(links_text, default_invite=invite_link)
        if not targets:
            return {
                "success": False,
                "error": "未解析到有效的 Telegram 频道帖子链接，请检查格式（如 https://t.me/c/123456/10-20）",
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
            "error": None,
        }

        self._append_log(f"🚀 启动频道采集任务 ({task_id})，共解析到 {len(targets)} 个频道、{total_msgs} 条目标消息")

        self._task = asyncio.create_task(
            self._run_pipeline(
                targets=targets,
                invite_links=invite_links,
                account_id=account_id,
                rebrand_enabled=rebrand_enabled,
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

    async def _run_pipeline(
        self,
        targets: List[HarvestTarget],
        invite_links: List[str],
        account_id: Optional[int],
        rebrand_enabled: bool,
        progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        user_client = None
        write_bot = get_write_bot_client()
        has_private_target = any(t.is_private for t in targets)

        try:
            # 1. 选择并启动协议号客户端
            acc = select_active_protocol_account(account_id)
            if acc:
                phone = acc.get("phone", f"ID:{acc.get('id')}")
                self._state["account_phone"] = phone
                self._append_log(f"🔐 选用协议号资产: {phone}，正在建立 MTProto 内存会话...")
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
            else:
                if has_private_target or invite_links:
                    raise RuntimeError(
                        "检测到私密频道或邀请链接，但当前协议号资产池为空。请先在「自动铸机 (/botfather)」页面导入至少 1 个协议号。"
                    )
                self._append_log("ℹ️ 协议号资产池为空，将使用主控 Bot 尝试读取公开频道内容")

            # 2. 如果提供了私密频道邀请链接，由协议号自动申请加入
            if user_client and invite_links:
                from pyrogram import errors as pyro_errors
                for inv in invite_links:
                    if self._cancel_requested:
                        break
                    try:
                        self._append_log(f"🚪 正在通过邀请链接加入私密频道: {inv}")
                        await user_client.join_chat(inv)
                        self._append_log(f"✅ 已成功加入频道: {inv}")
                    except getattr(pyro_errors, "UserAlreadyParticipant", Exception):
                        self._append_log(f"ℹ️ 协议号已是该频道成员: {inv}")
                    except Exception as join_err:
                        self._append_log(f"⚠️ 通过邀请链接 {inv} 加入频道时返回提示: {join_err}")

            reader_client = user_client or write_bot
            if reader_client is None:
                raise RuntimeError("没有可用的 Telegram 客户端实例来读取目标频道")

            # 3. 逐个频道、逐条消息拉取并转存
            for target in targets:
                if self._cancel_requested:
                    break

                chat_id = target.chat_id
                self._append_log(f"📂 正在访问频道 {chat_id}，准备拉取 {len(target.msg_ids)} 条消息...")

                # 预热 Peer 缓存
                try:
                    await reader_client.get_chat(chat_id)
                except Exception as peer_err:
                    logger.debug(f"预解析频道 Peer ({chat_id}) 提示: {peer_err}")
                    # 若协议号未缓存该私密频道 Peer，遍历对话列表刷新 Peer 缓存
                    if user_client and target.is_private and hasattr(user_client, "get_dialogs"):
                        try:
                            async for _ in user_client.get_dialogs(limit=100):
                                pass
                        except Exception:
                            pass

                for msg_id in target.msg_ids:
                    if self._cancel_requested:
                        break

                    self._state["current_index"] += 1
                    self._state["current_file"] = f"消息 #{msg_id}"
                    await self._notify_progress(progress_callback)

                    try:
                        msg = await reader_client.get_messages(chat_id, msg_id)
                        if isinstance(msg, list):
                            msg = msg[0] if msg else None

                        if not msg or getattr(msg, "empty", False):
                            self._state["skipped_count"] += 1
                            self._append_log(f"⏭️ 消息 #{msg_id} 不存在或已被删除，跳过")
                            continue

                        media_type, _ = get_media_type_and_obj(msg)
                        if not media_type:
                            self._state["skipped_count"] += 1
                            self._append_log(f"⏭️ 消息 #{msg_id} 不含媒体文件（纯文本/服务消息），跳过")
                            continue

                        try:
                            preview_name = get_name(msg)
                        except Exception:
                            preview_name = f"media_{msg_id}"
                        self._state["current_file"] = preview_name

                        is_prot = bool(
                            getattr(msg, "has_protected_content", False)
                            or getattr(getattr(msg, "chat", None), "has_protected_content", False)
                        )
                        self._state["current_mode"] = "restricted_relay" if is_prot else "fast_copy"
                        await self._notify_progress(progress_callback)

                        last_dl_ts = time.time()
                        last_dl_bytes = 0

                        def _on_dl_progress(current: int, total: int):
                            nonlocal last_dl_ts, last_dl_bytes
                            now = time.time()
                            dt = now - last_dl_ts
                            if dt >= 0.8:
                                speed_mb = ((current - last_dl_bytes) / dt) / (1024 * 1024)
                                pct = int(current * 100 / total) if total else 0
                                self._state["speed_text"] = f"{speed_mb:.1f} MB/s ({pct}%)"
                                last_dl_ts = now
                                last_dl_bytes = current

                        res = await harvest_single_message(
                            msg=msg,
                            user_client=user_client,
                            bot_client=write_bot,
                            bin_channel=Var.BIN_CHANNEL,
                            rebrand_enabled=rebrand_enabled,
                            progress_cb=_on_dl_progress,
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

                    except Exception as msg_err:
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
                    await user_client.stop()
                    self._append_log("🔌 协议号临时内存会话已安全断开")
                except Exception:
                    pass
            await self._notify_progress(progress_callback)
