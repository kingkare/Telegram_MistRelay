try:
    import pyrogram.errors.rpc_error
    _orig_rpc_init = pyrogram.errors.rpc_error.RPCError.__init__
    def _safe_rpc_init(self, *args, **kwargs):
        try:
            if "is_unknown" in kwargs:
                kwargs["is_unknown"] = False
            _orig_rpc_init(self, *args, **kwargs)
        except OSError:
            pass
    pyrogram.errors.rpc_error.RPCError.__init__ = _safe_rpc_init
except Exception:
    pass

"""
@BotFather 自动化流水线与协议号资产池服务 (BotFather Creator & Account Pool)
========================================================================
使用 Telegram API 协议号自动化与 @BotFather 对话：
1. 协议号资产池持久化纳管（支持多行 [手机号|接码链接]、Session String、多 .session 文件批量导入）；
2. 多号跨账号自动接力扩容（单号达 20 上限或受限时自动无缝切换下一账号，突破单号 20 机器人限制）；
3. 单号精准独立铸造（指定特定协议号提取存量或新建机器人）；
4. 签发 Token 即时热挂载至负载均衡集群。
"""

import os
import re
import json
import time
import hashlib
import secrets
import asyncio
import logging
from typing import List, Dict, Tuple, Optional, Any, Callable, Union

try:
    from pyrogram import Client
    from pyrogram.errors import FloodWait, RPCError
except ImportError:
    Client = None
    FloodWait = Exception
    RPCError = Exception

import db
from session_adapter import (
    parse_session_to_pyrogram_string,
    pack_pyrogram_session,
    extract_dc_and_auth_key_from_telethon_string,
    extract_from_pyrogram_string,
)
from WebStreamer.vars import Var

logger = logging.getLogger("botfather_creator")

TOKEN_REGEX = re.compile(r"(\d{5,12}:[A-Za-z0-9_-]{30,})")

_PHONE_SESSION_CACHE: Dict[str, str] = {}
_CACHE_FILES = [
    "/app/db/sessions/tg_phone_sessions.json",
    "/tmp/tg_phone_sessions.json",
    "db/sessions/tg_phone_sessions.json",
]


def _normalize_session_str(sess_str: str) -> str:
    if sess_str and sess_str.startswith("1") and len(sess_str) > 280:
        try:
            dc_id, auth_key = extract_dc_and_auth_key_from_telethon_string(sess_str)
            return pack_pyrogram_session(
                dc_id=dc_id,
                auth_key=auth_key,
                api_id=Var.API_ID or 2040,
                user_id=1,
            )
        except Exception:
            pass
    return sess_str


def _get_cached_session(phone: str) -> Optional[str]:
    norm_phone = phone.strip()
    if re.fullmatch(r"\d{8,15}", norm_phone):
        norm_phone = "+" + norm_phone

    # 1. 优先从 SQLite 协议号资产池查询
    try:
        acc = db.get_protocol_account_by_phone(norm_phone)
        if acc and acc.get("session_data"):
            sess = _normalize_session_str(acc["session_data"])
            _PHONE_SESSION_CACHE[norm_phone] = sess
            return sess
    except Exception:
        pass

    # 2. 内存与 JSON 文件兜底
    if norm_phone in _PHONE_SESSION_CACHE:
        return _PHONE_SESSION_CACHE[norm_phone]
    for cpath in _CACHE_FILES:
        if os.path.exists(cpath):
            try:
                with open(cpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get(norm_phone):
                        sess = _normalize_session_str(data[norm_phone])
                        _PHONE_SESSION_CACHE[norm_phone] = sess
                        try:
                            db.upsert_protocol_account(phone=norm_phone, session_data=sess)
                        except Exception:
                            pass
                        return sess
            except Exception:
                pass
    return None


def _save_cached_session(
    phone: str,
    session_str: str,
    code_url: Optional[str] = None,
    bot_count: Optional[int] = None,
    status: Optional[str] = None,
    remark: Optional[str] = None,
    session_type: str = "pyrogram_string",
) -> Optional[Dict]:
    norm_phone = phone.strip()
    if re.fullmatch(r"\d{8,15}", norm_phone):
        norm_phone = "+" + norm_phone
    session_str = _normalize_session_str(session_str)

    _PHONE_SESSION_CACHE[norm_phone] = session_str
    for cpath in _CACHE_FILES:
        try:
            os.makedirs(os.path.dirname(cpath), exist_ok=True)
            data = {}
            if os.path.exists(cpath):
                with open(cpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data[norm_phone] = session_str
            with open(cpath, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    try:
        return db.upsert_protocol_account(
            phone=norm_phone,
            session_data=session_str,
            session_type=session_type,
            code_url=code_url,
            bot_count=bot_count,
            status=status,
            remark=remark,
        )
    except Exception as e:
        logger.debug(f"持久化协议号到数据库异常: {e}")
        return None


def sanitize_account_record(row: Dict) -> Dict:
    """脱敏协议号记录，隐藏底层 auth_key 密文，保留管理所需的元数据"""
    code_url = row.get("code_url") or ""
    masked_url = ""
    if code_url:
        parts = code_url.split("/")
        masked_url = "/".join(parts[:3]) + "/***" if len(parts) >= 3 else "***"

    bot_count = int(row.get("bot_count") or 0)
    status = row.get("status") or "active"
    if bot_count >= 20 and status == "active":
        status = "limit_reached"

    return {
        "id": row.get("id"),
        "phone": row.get("phone"),
        "session_type": row.get("session_type") or "pyrogram_string",
        "has_code_url": bool(code_url),
        "masked_code_url": masked_url,
        "bot_count": bot_count,
        "max_bots": 20,
        "remaining_quota": max(0, 20 - bot_count),
        "status": status,
        "last_used_at": row.get("last_used_at"),
        "remark": row.get("remark") or "",
        "created_at": row.get("created_at"),
    }


def remove_protocol_account(account_identifier: Union[int, str]) -> bool:
    """
    从 SQLite 协议号资产池、内存缓存及所有磁盘 JSON 缓存中彻底移除指定协议号。
    彻底杜绝移除协议号后又被旧 JSON 缓存重新复活的问题。
    支持传入账号 ID (int/str) 或手机号 (str)。
    """
    phone = None
    account_id = None
    if isinstance(account_identifier, int) or (isinstance(account_identifier, str) and account_identifier.isdigit()):
        account_id = int(account_identifier)
        acc = db.get_protocol_account_by_id(account_id)
        if acc:
            phone = acc.get("phone")
    else:
        phone = str(account_identifier).strip()
        acc = db.get_protocol_account_by_phone(phone)
        if acc:
            account_id = acc.get("id")

    deleted = False
    if account_id:
        deleted = db.delete_protocol_account(account_id)
    elif phone:
        try:
            with db.db_conn() as conn:
                cur = conn.execute("DELETE FROM tg_protocol_accounts WHERE phone = ? OR phone = ?", (phone, phone.lstrip("+")))
                deleted = cur.rowcount > 0
        except Exception as e:
            logger.debug(f"通过手机号删除协议号失败: {e}")

    # 清理内存缓存和所有磁盘 JSON 缓存
    phones_to_remove = set()
    if phone:
        norm_phone = phone.strip()
        if re.fullmatch(r"\d{8,15}", norm_phone):
            norm_phone = "+" + norm_phone
        phones_to_remove.update({phone, norm_phone, phone.lstrip("+"), norm_phone.lstrip("+")})

    for p in phones_to_remove:
        _PHONE_SESSION_CACHE.pop(p, None)

    for cpath in _CACHE_FILES:
        if os.path.exists(cpath):
            try:
                with open(cpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    changed = False
                    for p in phones_to_remove:
                        if p in data:
                            del data[p]
                            changed = True
                    if changed:
                        with open(cpath, "w", encoding="utf-8") as f:
                            json.dump(data, f)
            except Exception as e:
                logger.debug(f"清理文件缓存异常 {cpath}: {e}")

    return deleted or bool(phones_to_remove)


def sync_cached_sessions_to_db() -> List[Dict]:
    """
    获取所有已纳管的协议号资产列表。
    当且仅当数据库表为空时（如首次系统启动、历史升级迁移），才从历史 JSON 文件和内存会话中同步迁移数据，
    避免反复将管理员已主动移除的协议号从磁盘遗留缓存中重新复原。
    """
    try:
        existing_rows = db.list_protocol_accounts()
        if existing_rows:
            return [sanitize_account_record(r) for r in existing_rows]

        # 仅当数据库完全为空时执行一次初始化历史迁移
        found = dict(_PHONE_SESSION_CACHE)
        for cpath in _CACHE_FILES:
            if os.path.exists(cpath):
                try:
                    with open(cpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            for k, v in data.items():
                                if v:
                                    found[k] = v
                except Exception:
                    pass

        existing_phones = {r["phone"] for r in existing_rows}
        for phone_k, sess_v in found.items():
            norm_p = phone_k.strip()
            if re.fullmatch(r"\d{8,15}", norm_p):
                norm_p = "+" + norm_p
            if norm_p not in existing_phones:
                db.upsert_protocol_account(
                    phone=norm_p,
                    session_data=_normalize_session_str(sess_v),
                    session_type="pyrogram_string",
                    status="active",
                )
        return [sanitize_account_record(r) for r in db.list_protocol_accounts()]
    except Exception as e:
        logger.debug(f"获取或同步协议号资产列表异常: {e}")
        return [sanitize_account_record(r) for r in db.list_protocol_accounts()]


def list_cached_phone_sessions() -> List[Dict[str, Any]]:
    """列出已纳管的协议号会话（兼容旧版 cached_sessions 字段）"""
    accounts = sync_cached_sessions_to_db()
    return [{"phone": a["phone"], "cached": True, **a} for a in accounts]


async def wait_for_botfather_reply(
    client: Client,
    after_id: int,
    timeout: float = 12.0,
    poll_interval: float = 0.5,
):
    """轮询等待 @BotFather 的最新回复消息"""
    start_t = time.time()
    while time.time() - start_t < timeout:
        try:
            async for msg in client.get_chat_history("BotFather", limit=5):
                if msg.id > after_id and not (msg.from_user and msg.from_user.is_self):
                    return msg
        except Exception as e:
            logger.debug(f"轮询 BotFather 回复异常: {e}")
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"等待 @BotFather 响应超时 (>{timeout}s)")


async def fetch_existing_bot_tokens(client: Client, max_limit: int = 20) -> List[Dict[str, str]]:
    """向 @BotFather 发送 /token 命令，尝试解析已有机器人的 Token"""
    existing = []
    try:
        await client.send_message("BotFather", "/cancel")
        await asyncio.sleep(0.8)

        sent = await client.send_message("BotFather", "/token")
        reply = await wait_for_botfather_reply(client, sent.id, timeout=8.0)

        if not reply or not reply.reply_markup:
            logger.info("BotFather 未返回机器人列表按钮，可能该账号尚无已建机器人")
            return []

        kb_rows = getattr(reply.reply_markup, "keyboard", None)
        if kb_rows and isinstance(kb_rows, list):
            kb_buttons = []
            for row in kb_rows:
                for btn in row:
                    text = getattr(btn, "text", btn) if btn else ""
                    if isinstance(text, str) and text.strip().startswith("@"):
                        kb_buttons.append(text.strip())

            if kb_buttons:
                logger.info(f"检测到 ReplyKeyboard 存量机器人按钮 {len(kb_buttons)} 个")
                for idx_b, b_text in enumerate(kb_buttons[:max_limit]):
                    try:
                        if idx_b > 0:
                            sent_t = await client.send_message("BotFather", "/token")
                            await wait_for_botfather_reply(client, sent_t.id, timeout=6.0)
                        sent_u = await client.send_message("BotFather", b_text)
                        res_msg = await wait_for_botfather_reply(client, sent_u.id, timeout=8.0)
                        if res_msg and res_msg.text:
                            match = TOKEN_REGEX.search(res_msg.text)
                            if match:
                                token = match.group(1)
                                uname = b_text.lstrip("@")
                                existing.append({"username": uname, "token": token})
                                logger.info(f"成功探测并提取存量 Bot: @{uname}")
                        await asyncio.sleep(0.8)
                    except Exception as kb_err:
                        logger.debug(f"通过 ReplyKeyboard 提取 {b_text} 异常: {kb_err}")
                return existing

        inline_rows = getattr(reply.reply_markup, "inline_keyboard", None)
        if not inline_rows:
            logger.info("BotFather 未返回机器人列表按钮，可能该账号尚无已建机器人")
            return []

        buttons = []
        for row in inline_rows:
            for btn in row:
                if btn.text and btn.callback_data:
                    buttons.append(btn)

        logger.info(f"检测到存量机器人候选按钮 {len(buttons)} 个")
        for btn in buttons[:max_limit]:
            try:
                if hasattr(reply, "click"):
                    res_msg = await reply.click(btn.text)
                else:
                    await client.request_callback_answer(
                        chat_id="BotFather",
                        message_id=reply.id,
                        callback_data=btn.callback_data,
                    )
                    res_msg = await wait_for_botfather_reply(client, reply.id, timeout=6.0)

                if res_msg and res_msg.text:
                    match = TOKEN_REGEX.search(res_msg.text)
                    if match:
                        token = match.group(1)
                        uname = btn.text.lstrip("@")
                        existing.append({"username": uname, "token": token})
                        logger.info(f"成功探测并提取存量 Bot: @{uname}")
                await asyncio.sleep(1.0)
            except Exception as click_err:
                logger.debug(f"点击 Bot 按钮 {btn.text} 提取 Token 异常: {click_err}")
    except Exception as e:
        logger.warning(f"获取存量 Bot Token 过程异常: {e}")

    return existing


async def create_single_bot(
    client: Client,
    display_name: str,
    username_prefix: str = "mr_node",
    max_cooldown_wait: int = 60,
    cooldown_callback=None,
    cancel_check=None,
) -> Tuple[str, str]:
    """与 @BotFather 交互创建单个机器人并返回 (username, token)"""
    reply1 = None
    for newbot_attempt in range(5):
        try:
            await client.send_message("BotFather", "/cancel")
            await asyncio.sleep(0.8)
        except Exception:
            pass

        sent_newbot = await client.send_message("BotFather", "/newbot")
        reply1 = await wait_for_botfather_reply(client, sent_newbot.id, timeout=10.0)

        reply1_text = (reply1.text or "").lower()
        if "cannot create new bots" in reply1_text or "spambot" in reply1_text:
            raise ValueError("该 Telegram 协议号账号受限 (被 Telegram @SpamBot 限制)，@BotFather 拒绝创建新机器人。")
        if "sorry" in reply1_text and ("20 bots" in reply1_text or "limit" in reply1_text):
            raise ValueError("该 Telegram 账号已达到单号 20 个机器人的最大上限，无法再新建")
        if "flood" in reply1_text or "too many" in reply1_text or "please try again" in reply1_text:
            m_wait = re.search(r"(\d+)\s*second", reply1_text)
            wait_sec = int(m_wait.group(1)) if m_wait else 4
            if wait_sec <= max_cooldown_wait and newbot_attempt < 8:
                logger.info(f"@BotFather 提示冷却 {wait_sec}s，休眠 {wait_sec + 2}s 后自动重试创建...")
                if max_cooldown_wait <= 60 and cooldown_callback is None and cancel_check is None:
                    await asyncio.sleep(wait_sec + 1.5)
                else:
                    total_wait = wait_sec + 2
                    for rem in range(total_wait, 0, -1):
                        if cancel_check and cancel_check():
                            raise asyncio.CancelledError("自动铸造任务已被手动中止")
                        if cooldown_callback:
                            try:
                                cooldown_callback(rem, total_wait)
                            except Exception:
                                pass
                        await asyncio.sleep(1.0)
                continue
            raise ValueError(f"@BotFather 触发限流: {reply1.text}")
        break

    sent_name = await client.send_message("BotFather", display_name)
    reply2 = await wait_for_botfather_reply(client, sent_name.id, timeout=10.0)

    clean_prefix = re.sub(r"[^a-zA-Z0-9]+", "_", username_prefix).strip("_").lower()
    if not clean_prefix or len(clean_prefix) < 2 or not clean_prefix[0].isalpha():
        clean_prefix = "mistrelay"
    clean_prefix = clean_prefix[:14].rstrip("_")

    token_found = None
    username_used = None

    for attempt in range(5):
        random_suffix = secrets.token_hex(3)
        candidate_uname = f"{clean_prefix}_{random_suffix}_bot"

        sent_uname = await client.send_message("BotFather", candidate_uname)
        reply3 = await wait_for_botfather_reply(client, sent_uname.id, timeout=10.0)
        reply3_text = reply3.text or ""

        if "taken" in reply3_text.lower() or "invalid" in reply3_text.lower():
            logger.info(f"用户名 {candidate_uname} 不可用 ({reply3_text[:40]}), 进行第 {attempt + 1} 次重试...")
            await asyncio.sleep(0.8)
            continue

        match = TOKEN_REGEX.search(reply3_text)
        if match:
            token_found = match.group(1)
            username_used = candidate_uname
            logger.info(f"BotFather 成功签发机器人: @{username_used}")
            break
        else:
            logger.warning(f"BotFather 回复未包含有效 Token (回复: {reply3_text[:60]}...)，重试...")
            await asyncio.sleep(0.8)

    if not token_found or not username_used:
        raise RuntimeError("多次尝试未能成功获取 @BotFather 签发的有效 Token")

    return username_used, token_found


async def login_via_phone_and_code_url(
    phone_and_url_str: str,
    on_progress: Optional[Callable[[str, Optional[str], int], None]] = None,
) -> str:
    """
    通过 '手机号|接码链接' 格式全自动完成接码与 2FA 登录并返回 Pyrogram Session String。
    支持 on_progress(msg, phone, cooldown) 实时汇报当前阶段与频率保护冷却倒计时。
    """
    import urllib.request
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import SessionPasswordNeededError

    parts = phone_and_url_str.split("|", 1)
    raw_phone = parts[0].strip()
    raw_url_part = parts[1].strip()

    phone_match = re.search(r"(\+?\d{8,15})", raw_phone)
    if not phone_match:
        raise ValueError(f"未能从输入中识别出有效的国际手机号: {raw_phone}")
    phone = phone_match.group(1)
    if not phone.startswith("+"):
        phone = "+" + phone

    url_match = re.search(r"https?://[^\s()\"\x27<>|]+", raw_url_part)
    if not url_match:
        raise ValueError(f"未能从输入中识别出有效的 HTTP 接码链接: {raw_url_part}")
    code_url = url_match.group(0).rstrip(")>]\x27\x22")

    def report_progress(msg: str, cooldown: int = 0):
        if on_progress:
            try:
                on_progress(msg, phone, cooldown)
            except Exception:
                pass

    # 1. 优先检查本地已登录缓存
    cached_sess = _get_cached_session(phone)
    if cached_sess:
        cached_sess = _normalize_session_str(cached_sess)
        if Client is not None:
            logger.info(f"发现手机号 {phone} 的已登录会话缓存，正在验证有效性...")
            report_progress(f"发现手机号 {phone} 已登录会话缓存，正在验证有效性...")
            test_cli = Client(
                name=f"verify_cache_{secrets.token_hex(4)}",
                api_id=Var.API_ID or 2040,
                api_hash=Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
                session_string=cached_sess,
                in_memory=True,
                no_updates=True,
            )
            try:
                await test_cli.start()
                me = await test_cli.get_me()
                if me:
                    logger.info(f"成功复用已缓存会话: {me.first_name} (@{me.username or '无用户名'}, ID: {me.id})")
                    report_progress(f"成功复用已缓存会话: {me.first_name}")
                    _save_cached_session(phone, cached_sess, code_url=code_url, status="active")
                    return cached_sess
            except Exception as e:
                logger.warning(f"缓存会话已失效 ({e})，将重新发起接码登录")
                report_progress("缓存会话已失效，正在重新发起接码登录...")
            finally:
                try:
                    if getattr(test_cli, "is_connected", False):
                        await test_cli.stop()
                except Exception:
                    pass
        else:
            return cached_sess

    logger.info(f"正在为手机号 {phone} 启动 Telethon 自动接码登录，接码地址: {code_url}")
    report_progress(f"正在为手机号 {phone} 建立 Telegram 连接并请求下发验证码...")

    t_client = TelegramClient(
        StringSession(),
        Var.API_ID or 2040,
        Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
        device_model="Desktop",
        system_version="Windows 10",
        app_version="4.16.8 x64",
    )

    try:
        await asyncio.wait_for(t_client.connect(), timeout=25.0)
    except Exception as conn_err:
        report_progress(f"连接 Telegram MTProto 网关失败: {conn_err}")
        raise TimeoutError(f"连接 Telegram MTProto 网关超时或失败: {conn_err}")

    try:
        try:
            sent = await asyncio.wait_for(t_client.send_code_request(phone), timeout=30.0)
        except Exception as send_err:
            err_str = str(send_err)
            if "PHONE_NUMBER_BANNED" in err_str or "banned" in err_str.lower():
                raise ValueError(f"手机号 {phone} 已被 Telegram 官方封禁 (PHONE_NUMBER_BANNED)")
            if "PHONE_NUMBER_INVALID" in err_str:
                raise ValueError(f"无效的国际手机号: {phone}")
            if "FLOOD_WAIT" in err_str:
                raise ValueError(f"Telegram 官方触发下发验证码限流: {err_str}")
            raise RuntimeError(f"请求 Telegram 下发验证码失败: {send_err}")

        phone_code_hash = sent.phone_code_hash
        logger.info(f"Telegram 已向 {phone} 签发验证码 (hash={phone_code_hash[:8]}...)")
        report_progress(f"Telegram 已向 {phone} 签发验证码，正在监听接码平台返回...")

        html_content = ""
        verification_code = None
        two_fa_password = None
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

        async def _fetch_code_html() -> str:
            try:
                import aiohttp
                if hasattr(aiohttp, "ClientTimeout"):
                    timeout_cfg = aiohttp.ClientTimeout(total=12)
                    connector = aiohttp.TCPConnector(ssl=False) if hasattr(aiohttp, "TCPConnector") else None
                    async with aiohttp.ClientSession(timeout=timeout_cfg, connector=connector, headers={"User-Agent": ua}) as http_sess:
                        async with http_sess.get(code_url) as resp:
                            return await resp.text(errors="ignore")
            except Exception:
                pass

            def _sync_get() -> str:
                import ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(code_url, headers={"User-Agent": ua})
                with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
                    return resp.read().decode("utf-8", errors="ignore")

            return await asyncio.to_thread(_sync_get)

        await asyncio.sleep(2.5)
        # 后台支持长达 240 秒的轮询时间窗口，足够跨越多轮接码平台频率冷却保护
        poll_deadline = time.monotonic() + 240.0

        for attempt in range(60):
            if time.monotonic() >= poll_deadline:
                break
            try:
                html_content = await _fetch_code_html()
            except Exception as req_err:
                logger.warning(f"第 {attempt + 1} 次轮询接码链接异常: {req_err}")
                report_progress(f"第 {attempt + 1} 次轮询接码链接异常，3 秒后重试...")
                await asyncio.sleep(3.0)
                continue

            clean_html = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", html_content, flags=re.DOTALL | re.IGNORECASE)

            # 致命错误快速探测：发卡网/接码平台明确提示账号死亡、已失效或订单错误，立即终止避免无效轮询
            if any(w in clean_html for w in ("账号死亡", "账号已死", "账号失效", "账号被封", "已封禁", "账号已注销")):
                raise ValueError("接码平台提示：该账号已死亡或被 Telegram 官方封禁（请向号商反馈或更换号码）")
            if any(w in clean_html for w in ("订单不存在", "卡密错误", "记录不存在")):
                raise ValueError("接码平台提示：订单或卡密链接不存在")
            if "已退款" in clean_html:
                raise ValueError("接码平台提示：该号码订单已退款")

            if "请求过于频繁" in html_content or ("等待" in html_content and "秒" in html_content):
                m_wait = re.search(r"等待\s*(\d+)\s*秒", html_content) or re.search(r"(\d+)\s*秒", html_content)
                wait_sec = min(int(m_wait.group(1)) if m_wait else 15, 65)
                remaining_budget = poll_deadline - time.monotonic()
                if remaining_budget <= 2:
                    break
                actual_sleep = min(wait_sec + 2.0, remaining_budget)
                logger.info(f"接码链接触发频率保护，等待 {actual_sleep:.0f} 秒后重试...")
                for sec_left in range(int(actual_sleep), 0, -1):
                    report_progress(
                        f"接码平台触发频率保护，冷却倒计时: 剩余 {sec_left} 秒后自动重试...",
                        cooldown=sec_left,
                    )
                    await asyncio.sleep(1.0)
                report_progress("频率保护冷却结束，正在重新读取验证码...", cooldown=0)
                continue

            if "无三十分钟内的登录消息" in html_content:
                logger.info(f"第 {attempt + 1} 次轮询: 接码页面暂未收到验证码，继续等待...")
                report_progress(f"第 {attempt + 1} 次轮询: 接码页面暂未收到验证码，继续等待...")
                await asyncio.sleep(3.5)
                continue

            clean_html = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", html_content, flags=re.DOTALL | re.IGNORECASE)
            m_code = re.search(r"id=[\x22\x27]code[\x22\x27][^>]+value=[\x22\x27](\d{5,6})[\x22\x27]", clean_html)
            m_pass = re.search(r"id=[\x22\x27]pass2fa[\x22\x27][^>]+value=[\x22\x27]([^\x22\x27]+)[\x22\x27]", clean_html)
            if m_code:
                verification_code = m_code.group(1)
                if m_pass:
                    two_fa_password = m_pass.group(1).strip()
                break

            code_matches = re.findall(r"\b(\d{5,6})\b", clean_html)
            if code_matches:
                verification_code = code_matches[0]
                break

            await asyncio.sleep(3.0)

        if not verification_code:
            raise TimeoutError("等待接码超时：未能在接码页面提取到 5 位验证码")

        logger.info(f"成功获取到登录验证码: {verification_code}")
        report_progress(f"成功捕获验证码: {verification_code}，正在执行登录校验...", cooldown=0)

        if not two_fa_password:
            clean_html = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", html_content, flags=re.DOTALL | re.IGNORECASE)
            inputs = re.findall(r"value=[\x22\x27]([^\x22\x27]+)[\x22\x27]", clean_html)
            if len(inputs) >= 3:
                two_fa_password = inputs[2].strip()
            elif inputs:
                for val in inputs:
                    val = val.strip()
                    if val and val != verification_code and val != phone and val != phone.lstrip("+"):
                        two_fa_password = val
                        break

        try:
            await t_client.sign_in(phone=phone, code=verification_code, phone_code_hash=phone_code_hash)
            logger.info("验证码校验通过，无需 2FA 直接登录成功！")
            report_progress("验证码校验通过，登录成功！")
        except SessionPasswordNeededError:
            if not two_fa_password:
                raise ValueError("Telegram 要求两步验证(2FA)密码，但接码页面中未能自动识别出密码")
            logger.info(f"正在验证两步验证密码: {two_fa_password}")
            report_progress("正在校验两步验证(2FA)密码...")
            await t_client.sign_in(password=two_fa_password)
            logger.info("两步验证校验通过，登录成功！")
            report_progress("两步验证校验通过，登录成功！")

        me = await t_client.get_me()
        t_session_str = t_client.session.save()
        dc_id, auth_key = extract_dc_and_auth_key_from_telethon_string(t_session_str)
        pyro_session = pack_pyrogram_session(
            dc_id=dc_id,
            auth_key=auth_key,
            api_id=Var.API_ID or 2040,
            user_id=me.id if me else 1,
        )
        _save_cached_session(
            phone,
            pyro_session,
            code_url=code_url,
            status="active",
            session_type="telethon_string",
        )
        logger.info(f"协议号登录并转换完成: {me.first_name} (@{me.username or '无用户名'}, ID: {me.id})")
        report_progress(f"协议号 {phone} 登录并转换完成 ({me.first_name})")
        return pyro_session
    finally:
        try:
            await t_client.disconnect()
        except Exception:
            pass


async def _resolve_account_entry(
    source: str | bytes | bytearray,
    filename: Optional[str] = None,
    remark: Optional[str] = None,
    on_progress: Optional[Callable[[str, Optional[str], int], None]] = None,
) -> Dict:
    """
    解析任意单条协议号来源（手机号|链接、已缓存手机号、Session String、.session 字节），
    写入或更新协议号资产池并返回数据库记录。
    """
    if isinstance(source, (bytes, bytearray)):
        pyro_session = parse_session_to_pyrogram_string(source, default_api_id=Var.API_ID or 2040)
        phone = None
        if filename:
            m = re.search(r"(\+?\d{8,15})", filename)
            if m:
                phone = m.group(1)
                if not phone.startswith("+"):
                    phone = "+" + phone
        if not phone:
            try:
                _, _, _, _, uid, _ = extract_from_pyrogram_string(pyro_session)
                if uid and uid > 1:
                    phone = f"+uid_{uid}"
            except Exception:
                pass
        if not phone:
            h = hashlib.sha1(pyro_session.encode("utf-8")).hexdigest()[:10]
            phone = f"+sess_{h}"

        rec = _save_cached_session(
            phone=phone,
            session_str=pyro_session,
            remark=remark or (filename or "上传 .session 文件"),
            status="active",
            session_type="session_file",
        )
        if on_progress:
            try:
                on_progress(f"文件 {filename or phone} 解析入库成功", phone, 0)
            except Exception:
                pass
        return rec or {"phone": phone, "session_data": pyro_session, "status": "active", "bot_count": 0}

    raw_str = str(source or "").strip()
    if not raw_str:
        raise ValueError("空的协议号输入内容")

    # 1. [手机号|接码链接] 或 [手机号|接码链接|备注]
    if "|" in raw_str and "http" in raw_str:
        parts = raw_str.split("|")
        phone_match = re.search(r"(\+?\d{8,15})", parts[0])
        phone = phone_match.group(1) if phone_match else parts[0].strip()
        if not phone.startswith("+"):
            phone = "+" + phone
        url_match = re.search(r"https?://[^\s()\"\x27<>|]+", raw_str)
        code_url = url_match.group(0).rstrip(")>]\x27\x22") if url_match else ""
        line_remark = remark or (parts[2].strip() if len(parts) >= 3 else None)

        if on_progress is not None:
            try:
                pyro_session = await login_via_phone_and_code_url(raw_str, on_progress=on_progress)
            except TypeError:
                pyro_session = await login_via_phone_and_code_url(raw_str)
        else:
            pyro_session = await login_via_phone_and_code_url(raw_str)

        rec = _save_cached_session(
            phone=phone,
            session_str=pyro_session,
            code_url=code_url,
            remark=line_remark,
            status="active",
            session_type="telethon_string",
        )
        return rec or {"phone": phone, "session_data": pyro_session, "code_url": code_url, "status": "active", "bot_count": 0}

    # 2. 纯手机号（从已缓存资产池读取）
    if re.fullmatch(r"\+?\d{8,15}", raw_str):
        phone_key = raw_str if raw_str.startswith("+") else f"+{raw_str}"
        cached = _get_cached_session(phone_key)
        if not cached:
            raise ValueError(f"手机号 {phone_key} 尚无已缓存会话，请提供 [手机号|接码链接] 格式")
        rec = _save_cached_session(phone=phone_key, session_str=cached, remark=remark)
        if on_progress:
            try:
                on_progress(f"成功复用手机号 {phone_key} 已缓存会话", phone_key, 0)
            except Exception:
                pass
        return rec or {"phone": phone_key, "session_data": cached, "status": "active", "bot_count": 0}

    # 3. Session String (Pyrogram / Telethon)
    s_type = "telethon_string" if (raw_str.startswith("1") and len(raw_str) > 280) else "pyrogram_string"
    pyro_session = parse_session_to_pyrogram_string(raw_str, default_api_id=Var.API_ID or 2040)
    phone = None
    try:
        _, _, _, _, uid, _ = extract_from_pyrogram_string(pyro_session)
        if uid and uid > 1:
            phone = f"+uid_{uid}"
    except Exception:
        pass
    if not phone:
        h = hashlib.sha1(pyro_session.encode("utf-8")).hexdigest()[:10]
        phone = f"+sess_{h}"

    rec = _save_cached_session(
        phone=phone,
        session_str=pyro_session,
        remark=remark,
        status="active",
        session_type=s_type,
    )
    if on_progress:
        try:
            on_progress(f"成功解析 Session 字符串并入库 ({phone})", phone, 0)
        except Exception:
            pass
    return rec or {"phone": phone, "session_data": pyro_session, "status": "active", "bot_count": 0}


async def batch_import_protocol_accounts(
    lines: Optional[List[str]] = None,
    files: Optional[List[Tuple[str, bytes]]] = None,
    remark: Optional[str] = None,
    on_progress: Optional[Callable[[str, Optional[str], int], None]] = None,
) -> Dict:
    """
    批量导入多个协议号到资产池（支持多行 [手机号|接码链接]、多行 Session String、多个 .session 文件）。
    采用受控并发（Semaphore=3）处理，避免多账号串行接码导致整体耗时叠加超时。
    """
    imported: List[Dict] = []
    errors: List[str] = []
    sem = asyncio.Semaphore(3)

    async def _import_line(idx: int, clean_line: str):
        async with sem:
            try:
                if on_progress:
                    try:
                        on_progress(f"开始解析第 {idx} 行协议号...", None, 0)
                    except Exception:
                        pass
                rec = await _resolve_account_entry(clean_line, remark=remark, on_progress=on_progress)
                return ("ok", sanitize_account_record(rec))
            except Exception as e:
                err_msg = f"第 {idx} 行 ({clean_line[:24]}...) 导入失败: {e}"
                logger.warning(err_msg)
                if on_progress:
                    try:
                        on_progress(err_msg, None, 0)
                    except Exception:
                        pass
                return ("err", err_msg)

    async def _import_file(fname: str, fbytes: bytes):
        async with sem:
            try:
                if on_progress:
                    try:
                        on_progress(f"开始解析文件 {fname}...", None, 0)
                    except Exception:
                        pass
                rec = await _resolve_account_entry(fbytes, filename=fname, remark=remark, on_progress=on_progress)
                return ("ok", sanitize_account_record(rec))
            except Exception as e:
                err_msg = f"文件 {fname} 导入失败: {e}"
                logger.warning(err_msg)
                if on_progress:
                    try:
                        on_progress(err_msg, None, 0)
                    except Exception:
                        pass
                return ("err", err_msg)

    tasks = []
    if lines:
        for idx, line in enumerate(lines, start=1):
            clean_line = str(line or "").strip()
            if not clean_line or clean_line.startswith("#"):
                continue
            tasks.append(_import_line(idx, clean_line))

    if files:
        for fname, fbytes in files:
            tasks.append(_import_file(fname, fbytes))

    if tasks:
        results = await asyncio.gather(*tasks)
        for status_tag, payload in results:
            if status_tag == "ok":
                imported.append(payload)
            else:
                errors.append(payload)

    pool = sync_cached_sessions_to_db()
    return {
        "imported_count": len(imported),
        "failed_count": len(errors),
        "imported": imported,
        "errors": errors,
        "pool": pool,
    }


# 后台异步导入任务存储池（彻底规避 Cloudflare 100~120s HTTP 524 代理超时）
_IMPORT_TASKS: Dict[str, Dict[str, Any]] = {}
# 强引用集合：防止 Python 垃圾回收机制 (GC) 销毁正在运行的 asyncio.Task
_RUNNING_IMPORT_TASKS: set = set()


def create_import_task(
    lines: Optional[List[str]] = None,
    files: Optional[List[Tuple[str, bytes]]] = None,
    remark: Optional[str] = None,
) -> str:
    """
    创建并启动后台异步协议号导入任务，立即返回 task_id。
    """
    now = time.time()
    for tid, info in list(_IMPORT_TASKS.items()):
        if now - info.get("created_at", now) > 3600:
            _IMPORT_TASKS.pop(tid, None)

    task_id = f"import_{secrets.token_hex(6)}"
    _IMPORT_TASKS[task_id] = {
        "task_id": task_id,
        "status": "running",
        "progress": 5,
        "progress_msg": "正在初始化协议号后台导入任务...",
        "current_phone": "",
        "cooldown_remaining": 0,
        "imported_count": 0,
        "failed_count": 0,
        "imported": [],
        "errors": [],
        "logs": [],
        "pool": [],
        "created_at": now,
        "updated_at": now,
    }

    t = asyncio.create_task(_run_import_task(task_id, lines, files, remark))
    _RUNNING_IMPORT_TASKS.add(t)
    t.add_done_callback(_RUNNING_IMPORT_TASKS.discard)
    return task_id


def get_import_task_status(task_id: str) -> Optional[Dict[str, Any]]:
    """获取指定协议号导入任务的状态与实时进度"""
    return _IMPORT_TASKS.get(task_id)


async def _run_import_task(
    task_id: str,
    lines: Optional[List[str]],
    files: Optional[List[Tuple[str, bytes]]],
    remark: Optional[str],
):
    task_info = _IMPORT_TASKS.get(task_id)
    if not task_info:
        return

    def on_progress(msg: str, phone: Optional[str] = None, cooldown: int = 0):
        if not task_info:
            return
        now_str = time.strftime("%H:%M:%S")
        task_info["updated_at"] = time.time()
        task_info["progress_msg"] = msg
        if phone:
            task_info["current_phone"] = phone
        task_info["cooldown_remaining"] = int(cooldown or 0)
        task_info["logs"].append({"time": now_str, "msg": msg})
        if len(task_info["logs"]) > 80:
            task_info["logs"] = task_info["logs"][-80:]

    try:
        on_progress("已启动后台接码入库流水线，正在连接 Telegram...")
        res = await batch_import_protocol_accounts(
            lines=lines,
            files=files,
            remark=remark,
            on_progress=on_progress,
        )
        task_info["status"] = "completed"
        task_info["progress"] = 100
        task_info["cooldown_remaining"] = 0
        task_info["imported_count"] = res.get("imported_count", 0)
        task_info["failed_count"] = res.get("failed_count", 0)
        task_info["imported"] = res.get("imported", [])
        task_info["errors"] = res.get("errors", [])
        task_info["pool"] = res.get("pool", [])
        task_info["updated_at"] = time.time()
        summary_msg = f"导入完成：成功 {res.get('imported_count', 0)} 个，失败 {res.get('failed_count', 0)} 个"
        task_info["progress_msg"] = summary_msg
        on_progress(summary_msg, task_info.get("current_phone"), 0)
    except BaseException as e:
        logger.error(f"[ImportTask {task_id}] 异常终止: {e}", exc_info=True)
        task_info["status"] = "failed"
        task_info["error"] = str(e)
        task_info["cooldown_remaining"] = 0
        task_info["progress_msg"] = f"导入任务异常终止: {e}"
        task_info["updated_at"] = time.time()
        on_progress(f"导入任务异常终止: {e}", task_info.get("current_phone"), 0)


async def check_protocol_account(account_id: int) -> Dict:
    """
    检测指定协议号资产的连接健康状态，并向 @BotFather 查询该账号当前已持有的机器人数量
    """
    acc = db.get_protocol_account_by_id(int(account_id))
    if not acc:
        raise KeyError(f"未找到 ID={account_id} 的协议号记录")

    phone = acc["phone"]
    pyro_session = _normalize_session_str(acc["session_data"])

    if Client is None:
        raise RuntimeError("Pyrogram Client 环境未就绪")

    user_client = Client(
        name=f"check_acc_{account_id}_{secrets.token_hex(3)}",
        api_id=Var.API_ID or 2040,
        api_hash=Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
        session_string=pyro_session,
        in_memory=True,
        no_updates=True,
    )

    try:
        try:
            await user_client.start()
        except Exception as conn_err:
            if acc.get("code_url"):
                logger.info(f"协议号 {phone} 会话失效 ({conn_err})，尝试通过接码链接重新登录...")
                pyro_session = await login_via_phone_and_code_url(f"{phone}|{acc['code_url']}")
                user_client = Client(
                    name=f"recheck_acc_{account_id}_{secrets.token_hex(3)}",
                    api_id=Var.API_ID or 2040,
                    api_hash=Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
                    session_string=pyro_session,
                    in_memory=True,
                    no_updates=True,
                )
                await user_client.start()
            else:
                db.update_protocol_account(account_id, status="invalid")
                raise ValueError(f"协议号 {phone} 会话已失效且无接码链接: {conn_err}")

        me = await user_client.get_me()
        real_phone = f"+{me.phone_number}" if getattr(me, "phone_number", None) else phone
        existing_bots = await fetch_existing_bot_tokens(user_client, max_limit=20)
        bot_count = len(existing_bots)
        new_status = "limit_reached" if bot_count >= 20 else "active"

        db.update_protocol_account(
            account_id,
            phone=real_phone if real_phone == phone else phone,
            bot_count=bot_count,
            status=new_status,
            last_used_at=db._now_iso(),
        )
        updated = db.get_protocol_account_by_id(account_id)
        return {
            "account": sanitize_account_record(updated),
            "user_info": {
                "id": getattr(me, "id", None),
                "first_name": getattr(me, "first_name", ""),
                "username": getattr(me, "username", ""),
            },
            "bots_found": bot_count,
            "bots": [{"username": b["username"]} for b in existing_bots],
        }
    finally:
        try:
            if getattr(user_client, "is_connected", False):
                await user_client.stop()
        except Exception:
            pass


async def run_botfather_pipeline(
    session_source: str | bytes | bytearray,
    count: int = 3,
    name_prefix: str = "MistRelay Node",
    reuse_existing: bool = True,
) -> Dict:
    """
    全自动协议号 BotFather 对接入网流水线（兼容单号或多行输入）
    """
    from WebStreamer.bot.clients import hot_add_bot_client
    import WebStreamer.bot as bot_mod

    count = max(1, min(int(count), 100))

    sources: List[Any] = []
    if isinstance(session_source, (bytes, bytearray)):
        sources = [session_source]
    else:
        raw_lines = [ln.strip() for ln in str(session_source or "").splitlines() if ln.strip()]
        sources = raw_lines if raw_lines else [str(session_source or "").strip()]

    results = {
        "reused_count": 0,
        "created_count": 0,
        "total_active_workers": 0,
        "bots": [],
        "errors": [],
        "accounts_used": 0,
    }

    handled_tokens = set()

    for src in sources:
        if len(handled_tokens) >= count:
            break

        raw_str = str(src).strip() if not isinstance(src, (bytes, bytearray)) else ""
        phone_label = "协议号"
        acc_record = None
        if isinstance(src, (bytes, bytearray)):
            pyro_session = parse_session_to_pyrogram_string(src, default_api_id=Var.API_ID or 2040)
        elif "|" in raw_str and "http" in raw_str:
            p_m = re.search(r"(\+?\d{8,15})", raw_str.split("|", 1)[0])
            phone_label = p_m.group(1) if p_m else raw_str.split("|", 1)[0].strip()
            if not phone_label.startswith("+") and phone_label.isdigit():
                phone_label = "+" + phone_label
            pyro_session = await login_via_phone_and_code_url(raw_str)
            acc_record = db.get_protocol_account_by_phone(phone_label)
        elif re.fullmatch(r"\+?\d{8,15}", raw_str):
            phone_label = raw_str if raw_str.startswith("+") else f"+{raw_str}"
            cached = _get_cached_session(phone_label)
            if not cached:
                raise ValueError(f"手机号 {phone_label} 尚无已缓存会话，请提供 [手机号|接码链接] 格式")
            pyro_session = _normalize_session_str(cached)
            acc_record = db.get_protocol_account_by_phone(phone_label)
        else:
            pyro_session = parse_session_to_pyrogram_string(src, default_api_id=Var.API_ID or 2040)
            acc_record = _save_cached_session(
                phone=f"+sess_{hashlib.sha1(pyro_session.encode('utf-8')).hexdigest()[:8]}",
                session_str=pyro_session,
            )

        user_client = Client(
            name=f"botfather_flow_{secrets.token_hex(4)}",
            api_id=Var.API_ID or 2040,
            api_hash=Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
            session_string=pyro_session,
            in_memory=True,
            no_updates=True,
        )

        await user_client.start()
        results["accounts_used"] += 1
        try:
            user_info = await user_client.get_me()
            logger.info(f"协议号已登录: {user_info.first_name} (@{user_info.username or '无用户名'}, ID: {user_info.id})")

            acc_bot_count = 0
            if reuse_existing:
                existing_bots = await fetch_existing_bot_tokens(user_client, max_limit=20)
                acc_bot_count = len(existing_bots)
                for item in existing_bots:
                    tok = item["token"]
                    if tok in handled_tokens:
                        continue
                    try:
                        mount_res = await hot_add_bot_client(tok, persist=True)
                        results["bots"].append(mount_res)
                        handled_tokens.add(tok)
                        results["reused_count"] += 1
                        if len(handled_tokens) >= count:
                            break
                    except Exception as add_err:
                        results["errors"].append(f"挂载存量 Bot (@{item.get('username')}) 失败: {add_err}")

            if acc_record and acc_record.get("id"):
                db.update_protocol_account(
                    acc_record["id"],
                    bot_count=acc_bot_count,
                    status="limit_reached" if acc_bot_count >= 20 else "active",
                    last_used_at=db._now_iso(),
                )

            needed = count - len(handled_tokens)
            if needed > 0 and acc_bot_count < 20:
                can_mint = min(needed, 20 - acc_bot_count)
                existing_total = len(bot_mod.multi_clients)
                for i in range(1, can_mint + 1):
                    display_name = f"{name_prefix} #{existing_total + i}"
                    try:
                        uname, tok = await create_single_bot(
                            user_client,
                            display_name=display_name,
                            username_prefix=name_prefix.replace(" ", "_").lower(),
                        )
                        mount_res = await hot_add_bot_client(tok, persist=True)
                        results["bots"].append(mount_res)
                        handled_tokens.add(tok)
                        results["created_count"] += 1
                        acc_bot_count += 1
                        if acc_record and acc_record.get("id"):
                            db.update_protocol_account(
                                acc_record["id"],
                                bot_count=acc_bot_count,
                                status="limit_reached" if acc_bot_count >= 20 else "active",
                                last_used_at=db._now_iso(),
                            )
                        if len(handled_tokens) >= count:
                            break
                    except Exception as create_err:
                        err_msg = f"创建第 {i} 个机器人失败: {create_err}"
                        logger.error(err_msg)
                        results["errors"].append(err_msg)
                        low_err = str(create_err).lower()
                        if acc_record and acc_record.get("id"):
                            if "上限" in low_err or "20" in low_err or "limit" in low_err:
                                db.update_protocol_account(acc_record["id"], bot_count=20, status="limit_reached")
                            elif "受限" in low_err or "spambot" in low_err:
                                db.update_protocol_account(acc_record["id"], status="restricted")
                            elif "限流" in low_err or "flood" in low_err:
                                db.update_protocol_account(acc_record["id"], status="cooling_down")
                        if any(k in low_err for k in ["上限", "limit", "限流", "受限", "spambot"]):
                            break

                    await asyncio.sleep(3.5)
        finally:
            try:
                if hasattr(user_client, "is_connected") and user_client.is_connected:
                    await user_client.stop()
            except Exception:
                pass

    results["total_active_workers"] = max(0, len(bot_mod.multi_clients) - 1)
    return results


class BackgroundMintManager:
    """
    后台异步批量铸造机器人任务管理器
    支持：
    - 多号跨账号自动接力扩容（Relay Mode，突破单号 20 上限，达上限/限流自动切下一账号）
    - 单号精准独立铸造（Single Mode，指定单号独立操作）
    """
    def __init__(self):
        self.task_id: Optional[str] = None
        self.mode: str = "relay"  # "relay" | "single"
        self.status: str = "idle"  # idle, running, cooling_down, completed, stopped, failed
        self.target_count: int = 0
        self.created_count: int = 0
        self.reused_count: int = 0
        self.total_workers: int = 0
        self.cooldown_remaining: int = 0
        self.cooldown_total: int = 0
        self.current_step: str = ""
        self.current_account_phone: str = ""
        self.account_index: int = 0
        self.total_accounts: int = 0
        self.account_history: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, str]] = []
        self.bots: List[Dict] = []
        self.error: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._cancel_requested: bool = False

    def add_log(self, level: str, msg: str):
        now_str = time.strftime("%H:%M:%S")
        self.logs.append({"time": now_str, "level": level, "msg": msg})
        if len(self.logs) > 150:
            self.logs = self.logs[-150:]
        logger.info(f"[MintTask][{level.upper()}] {msg}")

    def get_status(self) -> Dict:
        import WebStreamer.bot as bot_mod
        self.total_workers = max(0, len(bot_mod.multi_clients) - 1)
        done_cnt = self.reused_count + self.created_count
        pct = round(min(100.0, done_cnt / max(1, self.target_count) * 100.0), 1) if self.target_count > 0 else 0.0
        accounts = sync_cached_sessions_to_db()
        return {
            "task_id": self.task_id,
            "mode": self.mode,
            "status": self.status,
            "target_count": self.target_count,
            "created_count": self.created_count,
            "reused_count": self.reused_count,
            "total_active_workers": self.total_workers,
            "cooldown_remaining": self.cooldown_remaining,
            "cooldown_total": self.cooldown_total,
            "current_step": self.current_step,
            "current_account_phone": self.current_account_phone,
            "account_index": self.account_index,
            "total_accounts": self.total_accounts,
            "account_history": self.account_history,
            "percent": pct,
            "logs": self.logs[-60:],
            "bots": self.bots,
            "error": self.error,
            "cached_sessions": [{"phone": a["phone"], "cached": True, **a} for a in accounts],
            "accounts": accounts,
        }

    def start_task(
        self,
        session_source: Optional[str | bytes | bytearray] = None,
        count: int = 20,
        name_prefix: str = "MistRelay Node",
        reuse_existing: bool = True,
        mode: str = "relay",
        account_ids: Optional[List[int]] = None,
        single_account_id: Optional[int] = None,
    ) -> Dict:
        if self.status in ("running", "cooling_down") and self._task and not self._task.done():
            raise ValueError("后台已有正在执行的自动铸造任务，请等待或先点击停止")

        sync_cached_sessions_to_db()
        norm_mode = "single" if mode == "single" else "relay"

        # 构建待执行的账号队列
        queue_items: List[Dict[str, Any]] = []

        if norm_mode == "single":
            if single_account_id is not None:
                acc = db.get_protocol_account_by_id(int(single_account_id))
                if not acc:
                    raise ValueError(f"未找到指定的协议号 (ID={single_account_id})")
                queue_items.append({"type": "db_account", "account": acc, "label": acc["phone"]})
            elif session_source is not None:
                if isinstance(session_source, (bytes, bytearray)):
                    queue_items.append({"type": "raw", "source": session_source, "label": "上传.session文件"})
                else:
                    lines = [ln.strip() for ln in str(session_source).splitlines() if ln.strip()]
                    if not lines:
                        raise ValueError("请提供有效的协议号或选择资产池账号")
                    queue_items.append({"type": "raw", "source": lines[0], "label": lines[0].split("|")[0][:20]})
            else:
                raise ValueError("单号精准模式请指定一个协议号账号")
            max_allowed = 20
        else:
            # 多号接力模式 (Relay Mode)
            if account_ids:
                for aid in account_ids:
                    acc = db.get_protocol_account_by_id(int(aid))
                    if acc:
                        queue_items.append({"type": "db_account", "account": acc, "label": acc["phone"]})
            if session_source is not None:
                if isinstance(session_source, (bytes, bytearray)):
                    queue_items.append({"type": "raw", "source": session_source, "label": "上传.session文件"})
                else:
                    lines = [ln.strip() for ln in str(session_source).splitlines() if ln.strip()]
                    for ln in lines:
                        lbl = ln.split("|")[0][:20]
                        # 避免与已选 db_account 重复
                        if not any(item["label"] == lbl for item in queue_items):
                            queue_items.append({"type": "raw", "source": ln, "label": lbl})
            if not queue_items:
                # 默认使用资产池中所有未失效账号
                all_accs = db.list_protocol_accounts()
                usable = [a for a in all_accs if a.get("status") not in ("invalid", "restricted")]
                if not usable:
                    usable = all_accs
                for acc in usable:
                    queue_items.append({"type": "db_account", "account": acc, "label": acc["phone"]})

            if not queue_items:
                raise ValueError("协议号资产池为空且未提供新协议号，请先导入或输入协议号")
            max_allowed = max(20, min(200, len(queue_items) * 20))

        self.task_id = f"mint_{int(time.time())}_{secrets.token_hex(3)}"
        self.mode = norm_mode
        self.status = "running"
        self.target_count = max(1, min(int(count), max_allowed))
        self.created_count = 0
        self.reused_count = 0
        self.cooldown_remaining = 0
        self.cooldown_total = 0
        self.current_account_phone = queue_items[0]["label"]
        self.account_index = 1
        self.total_accounts = len(queue_items)
        self.account_history = []
        self.current_step = f"正在启动{'多号接力' if norm_mode == 'relay' else '单号精准'}铸造流水线 (共 {len(queue_items)} 个账号候选)..."
        self.logs.clear()
        self.bots.clear()
        self.error = None
        self._cancel_requested = False

        mode_label = f"多号接力模式 (候选账号 {len(queue_items)} 个)" if norm_mode == "relay" else f"单号精准模式 ({queue_items[0]['label']})"
        self.add_log("info", f"启动自动化铸造流水线 [{mode_label}]，目标总节点数: {self.target_count}")
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(
            self._worker(queue_items, self.target_count, name_prefix, reuse_existing)
        )
        return self.get_status()

    def stop_task(self) -> Dict:
        self._cancel_requested = True
        if self._task and not self._task.done():
            self._task.cancel()
        self.status = "stopped"
        self.cooldown_remaining = 0
        self.current_step = "已手动停止任务"
        self.add_log("warn", "管理员手动中止了铸造流水线")
        return self.get_status()

    async def _prepare_account_session(self, item: Dict[str, Any]) -> Tuple[str, Optional[int], str]:
        """返回 (pyro_session, db_account_id, phone_label)"""
        if item["type"] == "db_account":
            acc = item["account"]
            phone = acc["phone"]
            sess = _normalize_session_str(acc["session_data"])
            return sess, acc["id"], phone

        raw_source = item["source"]
        if isinstance(raw_source, (bytes, bytearray)):
            rec = await _resolve_account_entry(raw_source)
            return rec["session_data"], rec.get("id"), rec.get("phone", "上传.session")

        raw_str = str(raw_source).strip()
        if "|" in raw_str and "http" in raw_str:
            self.current_step = f"正在通过接码链接为 {item['label']} 自动获取验证码..."
            self.add_log("info", f"检测到 [{item['label']}] 接码链接，正在执行自动接码登录...")
            rec = await _resolve_account_entry(raw_str)
            return rec["session_data"], rec.get("id"), rec.get("phone", item["label"])
        elif re.fullmatch(r"\+?\d{8,15}", raw_str):
            phone_key = raw_str if raw_str.startswith("+") else f"+{raw_str}"
            cached = _get_cached_session(phone_key)
            if not cached:
                raise ValueError(f"手机号 {phone_key} 尚无缓存会话，请附带接码链接")
            rec = _save_cached_session(phone_key, cached)
            return _normalize_session_str(cached), (rec["id"] if rec else None), phone_key
        else:
            rec = await _resolve_account_entry(raw_str)
            return rec["session_data"], rec.get("id"), rec.get("phone", item["label"])

    async def _worker(
        self,
        queue_items: List[Dict[str, Any]],
        count: int,
        name_prefix: str,
        reuse_existing: bool,
    ):
        from WebStreamer.bot.clients import hot_add_bot_client
        import WebStreamer.bot as bot_mod

        handled_tokens = set()

        try:
            for idx_acc, item in enumerate(queue_items, start=1):
                if self._cancel_requested:
                    raise asyncio.CancelledError("任务已被停止")

                if len(handled_tokens) >= count:
                    break

                self.account_index = idx_acc
                self.current_account_phone = item["label"]
                acc_reused = 0
                acc_created = 0
                acc_id = None
                user_client = None

                try:
                    pyro_session, acc_id, phone_label = await self._prepare_account_session(item)
                    self.current_account_phone = phone_label
                    self.current_step = f"[账号 {idx_acc}/{len(queue_items)}: {phone_label}] 正在建立加密连接..."
                    self.add_log("info", f"🚀 开始调度第 {idx_acc}/{len(queue_items)} 个协议号: {phone_label}")

                    user_client = Client(
                        name=f"bf_bg_{idx_acc}_{secrets.token_hex(3)}",
                        api_id=Var.API_ID or 2040,
                        api_hash=Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
                        session_string=pyro_session,
                        in_memory=True,
                        no_updates=True,
                    )

                    await user_client.start()
                    me = await user_client.get_me()
                    self.add_log("success", f"[{phone_label}] 协议号连接成功: {getattr(me, 'first_name', 'User')} (ID: {getattr(me, 'id', '')})")

                    acc_bot_total = 0
                    if reuse_existing:
                        self.current_step = f"[{phone_label}] 正在向 @BotFather 探测存量机器人..."
                        existing_bots = await fetch_existing_bot_tokens(user_client, max_limit=20)
                        acc_bot_total = len(existing_bots)
                        self.add_log("info", f"[{phone_label}] 探测到 {acc_bot_total} 个存量机器人")

                        if acc_id:
                            db.update_protocol_account(
                                acc_id,
                                bot_count=acc_bot_total,
                                status="limit_reached" if acc_bot_total >= 20 else "active",
                                last_used_at=db._now_iso(),
                            )

                        for b_item in existing_bots:
                            if self._cancel_requested:
                                raise asyncio.CancelledError("任务已被停止")
                            tok = b_item["token"]
                            if tok in handled_tokens:
                                continue
                            try:
                                mount_res = await hot_add_bot_client(tok, persist=True)
                                self.bots.append(mount_res)
                                handled_tokens.add(tok)
                                self.reused_count += 1
                                acc_reused += 1
                                self.add_log(
                                    "success",
                                    f"[{phone_label}] 复用并挂载节点 #{mount_res.get('index')}: @{b_item.get('username')} ({mount_res.get('mode')})"
                                )
                                if len(handled_tokens) >= count:
                                    break
                            except Exception as add_err:
                                self.add_log("warn", f"[{phone_label}] 挂载存量 Bot @{b_item.get('username')} 异常: {add_err}")

                    if len(handled_tokens) >= count:
                        self.account_history.append({
                            "phone": phone_label,
                            "reused": acc_reused,
                            "created": acc_created,
                            "status": "completed",
                        })
                        break

                    if acc_bot_total >= 20:
                        if acc_id:
                            db.update_protocol_account(acc_id, bot_count=20, status="limit_reached")
                        self.account_history.append({
                            "phone": phone_label,
                            "reused": acc_reused,
                            "created": 0,
                            "status": "limit_reached",
                        })
                        if idx_acc < len(queue_items):
                            self.add_log("warn", f"⚡ [{phone_label}] 存量已满 20 个机器人上限，自动接力切换至下一个账号！")
                        else:
                            self.add_log("warn", f"[{phone_label}] 已满 20 个机器人上限，无更多候选账号")
                        continue

                    needed = count - len(handled_tokens)
                    can_create_on_this_acc = min(needed, 20 - acc_bot_total)
                    self.add_log("info", f"[{phone_label}] 准备在本账号上新铸造最多 {can_create_on_this_acc} 个机器人 (总剩余差额: {needed})...")

                    for i in range(1, can_create_on_this_acc + 1):
                        if self._cancel_requested:
                            raise asyncio.CancelledError("任务已被停止")

                        existing_total = len(bot_mod.multi_clients)
                        display_name = f"{name_prefix} #{existing_total + 1}"
                        self.status = "running"
                        self.cooldown_remaining = 0
                        self.current_step = f"[{phone_label} ({idx_acc}/{len(queue_items)})] 正在铸造第 {i}/{can_create_on_this_acc} 个新机器人 ({display_name})..."

                        def _on_cd(rem: int, total: int):
                            self.status = "cooling_down"
                            self.cooldown_remaining = rem
                            self.cooldown_total = total
                            self.current_step = f"[{phone_label}] @BotFather 冷却保护中，剩余 {rem}s 后自动继续..."
                            if rem == total or rem % 30 == 0 or rem == 5:
                                self.add_log("warn", f"[{phone_label}] BotFather 冷却等待: 剩余 {rem}s / {total}s")

                        try:
                            # 若有后续账号可接力，单号最长冷却容忍设为 30s，超过则直接切号免等待！
                            max_cd = 30 if idx_acc < len(queue_items) else 600
                            uname, tok = await create_single_bot(
                                user_client,
                                display_name=display_name,
                                username_prefix=name_prefix.replace(" ", "_").lower(),
                                max_cooldown_wait=max_cd,
                                cooldown_callback=_on_cd,
                                cancel_check=lambda: self._cancel_requested,
                            )
                            self.status = "running"
                            self.cooldown_remaining = 0
                            self.current_step = f"[{phone_label}] 正在热挂载新机器人 @{uname}..."
                            mount_res = await hot_add_bot_client(tok, persist=True)
                            self.bots.append(mount_res)
                            handled_tokens.add(tok)
                            self.created_count += 1
                            acc_created += 1
                            acc_bot_total += 1

                            if acc_id:
                                db.update_protocol_account(
                                    acc_id,
                                    bot_count=acc_bot_total,
                                    status="limit_reached" if acc_bot_total >= 20 else "active",
                                    last_used_at=db._now_iso(),
                                )

                            self.add_log(
                                "success",
                                f"[{phone_label}] 成功铸造并激活节点 #{mount_res.get('index')}: @{uname} (模式: {mount_res.get('mode')})"
                            )
                            if len(handled_tokens) >= count:
                                break
                        except asyncio.CancelledError:
                            raise
                        except Exception as create_err:
                            err_str = str(create_err)
                            low_err = err_str.lower()
                            self.add_log("error", f"[{phone_label}] 创建机器人异常: {err_str}")

                            if "上限" in low_err or "20 bots" in low_err or "20 个" in low_err or "limit" in low_err:
                                if acc_id:
                                    db.update_protocol_account(acc_id, bot_count=20, status="limit_reached")
                                if idx_acc < len(queue_items):
                                    self.add_log("warn", f"⚡ [跨号接力] 账号 {phone_label} 已达到单号 20 个机器人上限，立即无缝切换至下一个协议号接力铸造！")
                                else:
                                    self.add_log("warn", f"账号 {phone_label} 已达到单号 20 个机器人上限")
                                break

                            if "受限" in low_err or "spambot" in low_err or "cannot create new bots" in low_err:
                                if acc_id:
                                    db.update_protocol_account(acc_id, status="restricted")
                                if idx_acc < len(queue_items):
                                    self.add_log("warn", f"⚡ [跨号接力] 账号 {phone_label} 被 @SpamBot 限制建机，自动切换下一个协议号接力！")
                                break

                            if "限流" in low_err or "flood" in low_err or "too many" in low_err:
                                if acc_id:
                                    db.update_protocol_account(acc_id, status="cooling_down")
                                if idx_acc < len(queue_items):
                                    self.add_log("warn", f"⚡ [跨号接力] 账号 {phone_label} 触发频率冷却，自动切换下一个协议号免等待接力！")
                                break

                        await asyncio.sleep(3.2)

                    self.account_history.append({
                        "phone": phone_label,
                        "reused": acc_reused,
                        "created": acc_created,
                        "status": "limit_reached" if acc_bot_total >= 20 else "ok",
                    })

                except asyncio.CancelledError:
                    raise
                except Exception as acc_err:
                    self.add_log("error", f"[{item['label']}] 账号执行异常: {acc_err}")
                    self.account_history.append({
                        "phone": item["label"],
                        "reused": acc_reused,
                        "created": acc_created,
                        "status": "error",
                        "error": str(acc_err),
                    })
                    if idx_acc < len(queue_items):
                        self.add_log("warn", f"⚡ [跨号接力] 账号 {item['label']} 异常跳过，自动切换至下一个候选账号...")
                        continue
                    elif self.reused_count + self.created_count == 0:
                        raise
                finally:
                    try:
                        if user_client and getattr(user_client, "is_connected", False):
                            await user_client.stop()
                    except Exception:
                        pass

            self.status = "completed"
            self.cooldown_remaining = 0
            self.total_workers = max(0, len(bot_mod.multi_clients) - 1)
            self.current_step = (
                f"流水线完成！共调度 {len(self.account_history)} 个协议号，"
                f"复用 {self.reused_count} 个，新造 {self.created_count} 个，集群当前活跃从机 {self.total_workers} 个。"
            )
            self.add_log("success", self.current_step)

        except asyncio.CancelledError:
            self.status = "stopped"
            self.cooldown_remaining = 0
            self.current_step = "任务已手动停止"
        except Exception as e:
            self.status = "failed"
            self.cooldown_remaining = 0
            self.error = str(e)
            self.current_step = f"任务执行失败: {e}"
            self.add_log("error", f"流水线失败: {e}")


mint_manager = BackgroundMintManager()
