import db
# Taken from megadlbot_oss <https://github.com/eyaadh/megadlbot_oss/blob/master/mega/webserver/routes.py>
# Thanks to Eyaadh <https://github.com/eyaadh>

import re
import time
import math
import logging
import secrets
import mimetypes
import os
import subprocess
import json
import asyncio
import sqlite3
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine
try:
    from pyrogram.file_id import FileId
except Exception:  # pragma: no cover - pyrogram is a runtime dependency
    FileId = None
from WebStreamer.bot import (
    multi_clients,
    work_loads,
    channel_accessible_clients,
    select_stream_bot,
    get_available_channel_bot_count,
    get_bot_runtime_snapshot,
    mark_bot_failure,
    mark_bot_success,
)
try:
    from WebStreamer.bot import acquire_bot_slot, release_bot_slot
except Exception:
    acquire_bot_slot = lambda *_args, **_kwargs: None
    release_bot_slot = lambda *_args, **_kwargs: None
from WebStreamer.server.exceptions import FIleNotFound, InvalidHash
from path_security import UnsafePathError, resolve_under, validate_child_name
from request_security import (
    LOGIN_LIMITER,
    audit_username,
    get_client_ip,
    login_limit_keys,
    sanitize_log_value,
)
from log_config import LOG_FILE, read_log_lines
from security_validation import merge_additional_bot_tokens
from WebStreamer.server.ws_manager import ws_manager
from WebStreamer import Var, utils, StartTime, __version__, StreamBot
from db import (
    fetch_recent_downloads, get_all_configs, get_config, set_configs,
    get_download_id_by_gid, get_download_by_id, get_upload_by_id,
    mark_download_failed, update_upload_status, mark_upload_failed,
    delete_download_record, browse_tg_media, get_tg_media_stats,
    get_tg_media_record_by_message_id, get_tg_media_records_by_media_group,
    list_all_tg_media_records, delete_tg_media_records,
)
import configer


MIME_EXTENSION_OVERRIDES = {
    "image/jpeg": ".jpg",
    "audio/ogg": ".ogg",
    "application/ogg": ".ogg",
    "video/mp4": ".mp4",
}

MEDIA_TYPE_EXTENSIONS = {
    "photo": ".jpg",
    "video": ".mp4",
    "animation": ".mp4",
    "video_note": ".mp4",
    "voice": ".ogg",
    "audio": ".mp3",
    "sticker": ".webp",
}

KNOWN_DOWNLOAD_SUFFIXES = {
    suffix.lower()
    for suffix in mimetypes.types_map.keys()
}
KNOWN_DOWNLOAD_SUFFIXES.update({
    ".7z",
    ".apk",
    ".ass",
    ".m4a",
    ".m4v",
    ".mkv",
    ".rar",
    ".srt",
    ".torrent",
    ".webm",
})

# 导入全局 aria2 客户端
# 优先直接从app模块获取（客户端在app.py启动时就已经初始化）
# 如果app模块不可用，则从utils模块获取（通过set_aria2_client设置）
def get_aria2_client():
    """获取全局aria2客户端实例（优先从utils模块获取，然后从app模块）"""
    # 首先尝试从utils模块获取（因为set_aria2_client会在启动时设置）
    try:
        from WebStreamer.bot.plugins.stream_modules.utils import aria2_client
        if aria2_client is not None:
            return aria2_client
    except ImportError:
        pass
    except Exception:
        pass
    
    # 如果utils模块不可用，尝试从app模块直接获取
    try:
        import sys
        import importlib
        
        # 尝试导入app模块（如果还没有导入）
        if 'app' not in sys.modules:
            try:
                importlib.import_module('app')
            except ImportError:
                pass
        
        if 'app' in sys.modules:
            app_module = sys.modules['app']
            if hasattr(app_module, 'client') and app_module.client is not None:
                return app_module.client
        
        # 如果sys.modules中没有，尝试直接导入
        app_module = importlib.import_module('app')
        if hasattr(app_module, 'client') and app_module.client is not None:
            return app_module.client
    except Exception:
        pass
    
    # 如果都失败，记录错误
    logger.error("无法获取Aria2客户端！请检查服务是否正常启动")
    return None

# 导入pyrogram错误类型以检测限流
try:
    from pyrogram import errors as pyrogram_errors
except ImportError:
    pyrogram_errors = None

# Docker Python SDK（用于系统管理模块）
try:
    import docker
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    docker = None

DOCKER_CONTROL_ENABLED = os.environ.get("MISTRELAY_ENABLE_DOCKER_CONTROL", "").lower() in {
    "1", "true", "yes", "on",
}

# psutil（用于系统资源监控）
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

logger = logging.getLogger("routes")

# 前端静态文件路径
FRONTEND_DIST = Path("/app/web/dist")
STATIC_ASSET_ROOT = FRONTEND_DIST / "assets"
FILE_API_ROOT = Path(os.environ.get("MISTRELAY_FILE_ROOT", "/data/downloads")).resolve()

SECRET_CONFIG_KEYS = frozenset({
    "API_HASH",
    "BOT_TOKEN",
    "MULTI_BOT_TOKENS",
    "RPC_SECRET",
})

# A stolen web-admin session must not be enough to redirect Telegram data or
# replace credentials. Rotate these values during a maintenance window.
OFFLINE_ONLY_CONFIG_KEYS = frozenset({
    "ADMIN_ID",
    "API_HASH",
    "API_ID",
    "BIN_CHANNEL",
    "BOT_TOKEN",
    "PROXY_IP",
    "PROXY_PORT",
    "RPC_SECRET",
    "RPC_URL",
    "STREAM_ALLOWED_USERS",
    "STREAM_BIND_ADDRESS",
    "STREAM_FQDN",
    "STREAM_HASH_LENGTH",
    "STREAM_HAS_SSL",
    "STREAM_NO_PORT",
    "STREAM_PORT",
    "STREAM_USE_SESSION_FILE",
    "ENABLE_STREAM",
    "SAVE_PATH",
    "SEND_STREAM_LINK",
})

routes = web.RouteTableDef()

NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}

# 缩略图生成信号量（限制并发数为1，实现"一个一个加载"）
thumbnail_semaphore = asyncio.Semaphore(1)


def _bounded_log_lines(raw_value, default=100):
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, 1000))


def _application_log_response(lines):
    log_lines = read_log_lines(tail=lines)
    return web.json_response({
        "success": True,
        "logs": "\n".join(log_lines),
        "lines": lines,
        "source": "application",
    })


async def _stream_application_logs(ws, tail_lines):
    """Stream the persisted application log when Docker API access is absent."""
    offset = 0
    inode = None
    try:
        with open(LOG_FILE, "rb") as handle:
            raw_history = handle.readlines()
            offset = handle.tell()
            inode = os.fstat(handle.fileno()).st_ino
        history = [
            line.decode("utf-8", errors="replace").rstrip("\r\n")
            for line in raw_history[-tail_lines:]
        ]
    except OSError:
        history = read_log_lines(tail=tail_lines)
    await ws.send_json({
        "type": "history",
        "logs": "\n".join(history),
        "source": "application",
    })

    await ws.send_json({
        "type": "stream_start",
        "message": "开始实时日志流",
        "source": "application",
    })

    pending = b""
    while not ws.closed:
        await asyncio.sleep(1)
        try:
            stat_result = os.stat(LOG_FILE)
        except OSError:
            offset = 0
            inode = None
            continue

        if inode != stat_result.st_ino or stat_result.st_size < offset:
            offset = 0
            inode = stat_result.st_ino
            pending = b""
        if stat_result.st_size == offset:
            continue

        try:
            with open(LOG_FILE, "rb") as handle:
                handle.seek(offset)
                chunk = handle.read()
                offset = handle.tell()
            data = pending + chunk
            complete_lines = data.splitlines(keepends=True)
            pending = b""
            if complete_lines and not complete_lines[-1].endswith((b"\n", b"\r")):
                pending = complete_lines.pop()
            for raw_line in complete_lines:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if line:
                    await ws.send_json({"type": "log", "line": line})
        except (ConnectionResetError, RuntimeError):
            break
        except OSError as exc:
            logger.warning("读取应用日志流失败: %s", exc)

def is_flood_wait_error(e: Exception) -> bool:
    """检查异常是否是Telegram限流错误"""
    if pyrogram_errors:
        # 检查是否是FloodWait错误类型
        flood_classes = tuple(
            getattr(pyrogram_errors, name)
            for name in ('FloodWait', 'FloodPremiumWait', 'Flood')
            if hasattr(pyrogram_errors, name)
        )
        if flood_classes and isinstance(e, flood_classes):
            return True
    
    # 检查错误消息中是否包含限流关键词
    error_str = str(e)
    error_type = type(e).__name__
    return (
        'FLOOD_WAIT' in error_str or 
        'FloodWait' in error_str or 
        'flood_420' in error_type or
        'Flood' in error_type
    )


def get_request_bin_channel(request: web.Request):
    """获取当前请求用户的专属存储频道 ID，未绑定专属频道的管理员回退至 Var.BIN_CHANNEL；普通租户严禁回退至全局频道"""
    user_payload = request.get("user") if hasattr(request, "get") else None
    if not user_payload:
        return None
    role = user_payload.get("role")
    try:
        import db
        u = db.get_user_by_id(user_payload.get("uid"))
        if u:
            role = u.get("role") or role
            if u.get("bin_channel_id"):
                return u["bin_channel_id"]
    except Exception:
        pass
    if role == "admin":
        try:
            return int(Var.BIN_CHANNEL) if Var.BIN_CHANNEL else None
        except (ValueError, TypeError):
            return Var.BIN_CHANNEL
    return None


def get_request_user_id(request: web.Request) -> int | None:
    """获取当前请求用户的 ID（用于多租户下载任务隔离）"""
    user_payload = request.get("user") if hasattr(request, "get") else None
    return user_payload.get("uid") if user_payload else None


def resolve_filter_chat_id(request: web.Request, user_payload: dict | None, req_chat_id: int | None) -> tuple[bool, int | None]:
    """
    解析当前请求的频道过滤 ID。
    返回 (is_admin, filter_chat_id)。
    - 对普通租户：严格绑定为其专属 req_chat_id（未分配时为 None）；
    - 对管理员：
        - 未显式指定 chat_id 时锁定为 req_chat_id (即 Var.BIN_CHANNEL 全局默认频道)；
        - 显式指定 chat_id=all 或 all_tenants 时返回 None (全库媒体聚合总览)；
        - 显式指定具体 chat_id 时按该 chat_id 过滤。
    """
    import db
    is_admin = bool(
        user_payload
        and user_payload.get("role") == "admin"
    )
    if not is_admin:
        return False, req_chat_id

    explicit_chat = request.query.get("chat_id", "").strip() if hasattr(request, "query") else ""
    if explicit_chat:
        if explicit_chat.lower() in ("all", "all_tenants"):
            return True, None
        try:
            return True, int(explicit_chat)
        except ValueError:
            return True, explicit_chat
    return True, req_chat_id

# ======================== 认证 API ========================

@routes.post("/api/auth/login")
async def auth_login_handler(request: web.Request):
    """用户登录，返回 JWT token"""
    client_ip = get_client_ip(request)
    user_agent = sanitize_log_value(request.headers.get("User-Agent", ""))
    username = ""
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return web.json_response({"success": False, "error": "请求数据格式错误"}, status=400)
        raw_username = body.get("username", "")
        password = body.get("password", "")
        if not isinstance(raw_username, str) or not isinstance(password, str):
            return web.json_response({"success": False, "error": "用户名或密码错误"}, status=401)
        username = raw_username.strip()
        if not username or not password:
            return web.json_response({"success": False, "error": "用户名和密码不能为空"}, status=400)
        if len(username) > 128 or len(password) > 512:
            logger.warning(
                "auth.login denied remote=%s username_hash=%s reason=invalid_length ua=%r",
                client_ip,
                audit_username(username),
                user_agent,
            )
            return web.json_response({"success": False, "error": "用户名或密码错误"}, status=401)

        limit_keys = login_limit_keys(client_ip, username)
        retry_after = LOGIN_LIMITER.retry_after(limit_keys)
        if retry_after:
            logger.warning(
                "auth.login throttled remote=%s username_hash=%s retry_after=%s ua=%r",
                client_ip,
                audit_username(username),
                retry_after,
                user_agent,
            )
            return web.json_response(
                {"success": False, "error": "登录尝试过多，请稍后重试"},
                status=429,
                headers={"Retry-After": str(retry_after)},
            )

        from db import create_auth_session, get_user_by_username, update_user_password
        from auth import (
            TOKEN_EXPIRE_SECONDS,
            create_refresh_token,
            create_token,
            get_refresh_token_expires_at,
            hash_refresh_token,
            hash_password,
            password_needs_rehash,
            verify_password,
        )
        user = get_user_by_username(username)
        if not user or not verify_password(password, user["password_hash"]):
            LOGIN_LIMITER.record_failure(limit_keys)
            logger.warning(
                "auth.login failed remote=%s username_hash=%s ua=%r",
                client_ip,
                audit_username(username),
                user_agent,
            )
            return web.json_response({"success": False, "error": "用户名或密码错误"}, status=401)

        if password_needs_rehash(user["password_hash"]):
            update_user_password(user["id"], hash_password(password))

        LOGIN_LIMITER.record_success(limit_keys)
        token = create_token(user["id"], user["username"], role=user.get("role", "admin"))
        refresh_token = create_refresh_token()
        device_id = body.get("device_id")
        session_name = body.get("session_name")
        if isinstance(device_id, str):
            device_id = device_id.strip() or None
        else:
            device_id = None
        if isinstance(session_name, str):
            session_name = session_name.strip() or None
        else:
            session_name = None
        create_auth_session(
            user["id"],
            hash_refresh_token(refresh_token),
            get_refresh_token_expires_at(),
            device_id=device_id,
            session_name=session_name,
        )
        logger.info(
            "auth.login succeeded remote=%s user_id=%s username_hash=%s ua=%r",
            client_ip,
            user["id"],
            audit_username(username),
            user_agent,
        )
        return web.json_response({
            "success": True,
            "token": token,
            "refresh_token": refresh_token,
            "expires_in": TOKEN_EXPIRE_SECONDS,
            "user": {"id": user["id"], "username": user["username"], "role": user["role"]},
        })
    except Exception as e:
        logger.error("登录失败 remote=%s: %s", client_ip, e, exc_info=True)
        return web.json_response({"success": False, "error": "登录失败"}, status=500)


@routes.post("/api/auth/refresh")
async def auth_refresh_handler(request: web.Request):
    """轮换 refresh token，并签发新的 access token。"""
    try:
        body = await request.json()
        refresh_token = body.get("refresh_token", "")
        if not isinstance(refresh_token, str) or not refresh_token:
            return web.json_response({"success": False, "error": "refresh_token 不能为空"}, status=400)

        from db import get_user_by_id, revoke_auth_session, rotate_auth_session
        from auth import (
            TOKEN_EXPIRE_SECONDS,
            create_refresh_token,
            create_token,
            get_refresh_token_expires_at,
            hash_refresh_token,
        )

        new_refresh_token = create_refresh_token()
        session = rotate_auth_session(
            hash_refresh_token(refresh_token),
            hash_refresh_token(new_refresh_token),
            get_refresh_token_expires_at(),
        )
        if not session:
            return web.json_response({"success": False, "error": "登录已过期，请重新登录"}, status=401)

        user = get_user_by_id(session["user_id"])
        if not user:
            revoke_auth_session(session_id=session["id"], reason="user_missing")
            return web.json_response({"success": False, "error": "用户不存在"}, status=401)

        token = create_token(user["id"], user["username"], role=user.get("role", "admin"))
        return web.json_response({
            "success": True,
            "token": token,
            "refresh_token": new_refresh_token,
            "expires_in": TOKEN_EXPIRE_SECONDS,
            "user": user,
        })
    except Exception as e:
        logger.error(f"刷新登录失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": "刷新登录失败"}, status=500)



@routes.post("/api/auth/tma")
async def auth_tma_handler(request: web.Request):
    """Telegram Mini App (TMA) 快速验签登录接口"""
    client_ip = get_client_ip(request)
    user_agent = sanitize_log_value(request.headers.get("User-Agent", ""))
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return web.json_response({"success": False, "error": "请求格式错误"}, status=400)

        init_data = body.get("init_data", "")
        if not isinstance(init_data, str) or not init_data.strip():
            return web.json_response({"success": False, "error": "init_data 不能为空"}, status=400)

        bot_token = str(getattr(Var, "BOT_TOKEN", "") or "").strip()
        if not bot_token:
            from configer import get_config
            bot_token = str(get_config("BOT_TOKEN", "") or "").strip()

        if not bot_token:
            logger.error("auth.tma failed: BOT_TOKEN not configured")
            return web.json_response({"success": False, "error": "系统未配置 Telegram Bot Token"}, status=500)

        from auth import (
            verify_telegram_webapp_init_data,
            create_token,
            create_refresh_token,
            get_refresh_token_expires_at,
            hash_refresh_token,
            TOKEN_EXPIRE_SECONDS,
        )
        tma_result = verify_telegram_webapp_init_data(init_data, bot_token)
        if not tma_result or not tma_result.get("user"):
            logger.warning("auth.tma verification failed remote=%s ua=%r", client_ip, user_agent)
            return web.json_response({"success": False, "error": "Telegram initData 验签失败或已过期"}, status=401)

        tg_user = tma_result["user"]
        tg_user_id = tg_user.get("id")
        if not tg_user_id:
            return web.json_response({"success": False, "error": "Telegram 用户信息缺失"}, status=401)

        from db import get_user_by_tg_id, create_auth_session
        user = get_user_by_tg_id(int(tg_user_id))
        if not user:
            logger.warning("auth.tma user not found for tg_user_id=%s remote=%s", tg_user_id, client_ip)
            return web.json_response({
                "success": False,
                "error": "未找到与此 Telegram 绑定的系统账号，请先在 Bot 中注册或联系管理员绑定账号",
                "tg_user_id": tg_user_id,
            }, status=401)

        token = create_token(user["id"], user["username"], role=user.get("role", "user"))
        refresh_token = create_refresh_token()
        create_auth_session(
            user["id"],
            hash_refresh_token(refresh_token),
            get_refresh_token_expires_at(),
            device_id="tma",
            session_name="Telegram Mini App",
        )
        logger.info(
            "auth.tma login succeeded user_id=%s username=%s tg_user_id=%s remote=%s",
            user["id"],
            user["username"],
            tg_user_id,
            client_ip,
        )
        return web.json_response({
            "success": True,
            "token": token,
            "refresh_token": refresh_token,
            "expires_in": TOKEN_EXPIRE_SECONDS,
            "user": user,
        })
    except Exception as e:
        logger.error("auth.tma exception remote=%s: %s", client_ip, e, exc_info=True)
        return web.json_response({"success": False, "error": "TMA 登录失败"}, status=500)


@routes.get("/api/auth/bot-info")
async def auth_bot_info_handler(request: web.Request):
    """返回主控 Telegram Bot 的用户名与信息，供注册页生成私聊链接"""
    bot_username = ""
    bot_first_name = "MistRelay Bot"
    try:
        if StreamBot and getattr(StreamBot, "me", None) and getattr(StreamBot.me, "username", None):
            bot_username = StreamBot.me.username
            bot_first_name = StreamBot.me.first_name or bot_first_name
        elif multi_clients and 0 in multi_clients and getattr(multi_clients[0], "me", None):
            bot_username = multi_clients[0].me.username or ""
            bot_first_name = multi_clients[0].me.first_name or bot_first_name
    except Exception:
        pass
    deep_link = f"https://t.me/{bot_username}?start=register" if bot_username else ""
    return web.json_response({
        "success": True,
        "bot_username": bot_username,
        "bot_name": bot_first_name,
        "register_deep_link": deep_link,
        "data": {
            "bot_username": bot_username,
            "bot_name": bot_first_name,
            "register_deep_link": deep_link,
        },
    })


@routes.post("/api/auth/register")
async def auth_register_handler(request: web.Request):
    """通过 Telegram 6 位注册码完成用户注册并自动调度同 DC 协议号创建专属物理存储空间"""
    try:
        body = await request.json()
        code = str(body.get("code") or "").strip()
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "").strip()
        preferred_dc = body.get("target_dc_id")

        if not code or not username or not password:
            return web.json_response({"success": False, "error": "验证码、用户名和密码不能为空"}, status=400)

        if not re.match(r"^[a-zA-Z0-9_]{3,32}$", username):
            return web.json_response({"success": False, "error": "用户名必须为 3-32 位字母、数字或下划线"}, status=400)

        if len(password) < 8 or len(password) > 512:
            return web.json_response({"success": False, "error": "密码长度必须在 8-512 个字符之间"}, status=400)

        import db
        if not bool(db.get_config("ALLOW_USER_REGISTRATION", True)):
            return web.json_response({
                "success": False,
                "error": "系统当前已暂停开放自助注册，请联系管理员为您手动开通云盘账号"
            }, status=403)

        if db.get_user_by_username(username):
            return web.json_response({"success": False, "error": "该用户名已被使用，请更换"}, status=400)

        reg_rec = db.verify_and_consume_tg_register_code(code)
        if not reg_rec:
            return web.json_response(
                {"success": False, "error": "验证码无效或已过期，请在 Telegram 中向主 Bot 发送 /register 重新获取"},
                status=400,
            )

        tg_uid = reg_rec["tg_user_id"]
        existing_u = db.get_user_by_tg_id(tg_uid)
        if existing_u:
            return web.json_response(
                {"success": False, "error": f"该 Telegram 账号已绑定用户 {existing_u.get('username')}"},
                status=400,
            )

        target_dc = int(preferred_dc) if preferred_dc else int(reg_rec.get("detected_dc_id") or 5)

        from botfather_creator import provision_user_storage_channel
        chan_meta = await provision_user_storage_channel(
            username=username,
            target_dc_id=target_dc,
            tg_user_id=tg_uid,
        )

        from auth import (
            TOKEN_EXPIRE_SECONDS,
            create_refresh_token,
            create_token,
            get_refresh_token_expires_at,
            hash_password,
            hash_refresh_token,
        )

        new_user = db.create_tenant_user(
            username=username,
            password_hash=hash_password(password),
            tg_user_id=tg_uid,
            tg_username=reg_rec.get("tg_username"),
            tg_first_name=reg_rec.get("tg_first_name"),
            dc_id=chan_meta["dc_id"],
            bin_channel_id=chan_meta["bin_channel_id"],
            bin_channel_username=chan_meta["bin_channel_username"],
            creator_account_id=chan_meta.get("creator_account_id"),
            role="user",
        )

        token = create_token(new_user["id"], new_user["username"], role="user")
        refresh_token = create_refresh_token()
        db.create_auth_session(
            new_user["id"],
            hash_refresh_token(refresh_token),
            get_refresh_token_expires_at(),
        )

        return web.json_response({
            "success": True,
            "message": "注册成功！已为您开通同 DC 物理隔离专属云盘",
            "token": token,
            "refresh_token": refresh_token,
            "expires_in": TOKEN_EXPIRE_SECONDS,
            "user": new_user,
        })
    except Exception as e:
        logger.error(f"用户注册开通专属频道失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"开通专属云盘失败: {e}"}, status=500)


def _require_admin_user(request: web.Request) -> dict | None:
    user = request.get("user") if hasattr(request, "get") else None
    if not user or user.get("role") != "admin":
        return None
    return user


def _generate_random_user_password() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "Mr-" + "".join(secrets.choice(alphabet) for _ in range(10))


@routes.get("/api/users")
async def list_users_handler(request: web.Request):
    """管理员查询系统用户列表、专属频道统计汇总及近期 TG 注册码"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    import db
    users = db.list_users()
    recent_codes = db.list_tg_register_codes(limit=200)
    dc_dist: dict[str, int] = {}
    for u in users:
        dc_val = u.get("dc_id")
        if dc_val:
            key = f"DC{dc_val}"
            dc_dist[key] = dc_dist.get(key, 0) + 1
    summary = {
        "total_users": len(users),
        "dedicated_tenants": sum(1 for u in users if u.get("bin_channel_id")),
        "total_files": sum(int(u.get("media_count") or 0) for u in users),
        "total_size": sum(int(u.get("total_size") or 0) for u in users),
        "pending_codes": sum(1 for c in recent_codes if not c.get("used")),
        "dc_distribution": dc_dist,
    }
    return web.json_response({
        "success": True,
        "data": users,
        "users": users,
        "summary": summary,
        "recent_codes": recent_codes,
    })


@routes.post("/api/users")
async def admin_create_user_handler(request: web.Request):
    """管理员手动创建租户账号，并可选自动调配同 DC 协议号开通专属存储频道"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        body = await request.json()
        username = str(body.get("username") or "").strip()
        raw_password = str(body.get("password") or "").strip()
        role = str(body.get("role") or "user").strip()
        if role not in ("user", "admin"):
            role = "user"
        tg_user_id_raw = body.get("tg_user_id")
        tg_user_id = int(tg_user_id_raw) if tg_user_id_raw not in (None, "", 0, "0") else None
        tg_username = str(body.get("tg_username") or "").strip() or None
        tg_first_name = str(body.get("tg_first_name") or "").strip() or None
        target_dc_id = int(body.get("target_dc_id") or 5)
        auto_provision = bool(body.get("auto_provision_channel", True))

        if not username or len(username) < 3 or len(username) > 32:
            return web.json_response({"success": False, "error": "用户名长度需在 3~32 位之间"}, status=400)

        import db
        from auth import hash_password
        if db.get_user_by_username(username):
            return web.json_response({"success": False, "error": f"用户名 {username} 已存在"}, status=400)
        if tg_user_id and db.get_user_by_tg_id(tg_user_id):
            return web.json_response({"success": False, "error": f"TG ID {tg_user_id} 已绑定其他账号"}, status=400)

        generated_password = None
        if not raw_password or raw_password.lower() == "auto":
            raw_password = _generate_random_user_password()
            generated_password = raw_password
        elif len(raw_password) < 8:
            return web.json_response({"success": False, "error": "密码长度不能少于 8 位"}, status=400)

        chan_meta = {
            "dc_id": target_dc_id,
            "bin_channel_id": None,
            "bin_channel_username": None,
            "creator_account_id": None,
        }
        if auto_provision:
            from botfather_creator import provision_user_storage_channel
            chan_meta = await provision_user_storage_channel(
                username=username,
                tg_user_id=tg_user_id,
                target_dc_id=target_dc_id,
            )

        new_user = db.create_tenant_user(
            username=username,
            password_hash=hash_password(raw_password),
            tg_user_id=tg_user_id,
            tg_username=tg_username,
            tg_first_name=tg_first_name,
            dc_id=chan_meta.get("dc_id"),
            bin_channel_id=chan_meta.get("bin_channel_id"),
            bin_channel_username=chan_meta.get("bin_channel_username"),
            creator_account_id=chan_meta.get("creator_account_id"),
            role=role,
        )
        new_user.pop("password_hash", None)
        return web.json_response({
            "success": True,
            "message": "租户创建成功" + (f" (已开通 DC{chan_meta['dc_id']} 专属频道 @{chan_meta['bin_channel_username']})" if chan_meta.get("bin_channel_id") else ""),
            "user": new_user,
            "generated_password": generated_password or raw_password,
        })
    except Exception as e:
        logger.error(f"管理员创建用户失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"创建用户失败: {e}"}, status=500)


@routes.post("/api/users/{id}/provision-channel")
async def admin_provision_user_channel_handler(request: web.Request):
    """管理员为指定用户一键补建或重新分配同 DC 专属存储频道"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        user_id = int(request.match_info["id"])
        body = await request.json() if request.can_read_body else {}
        import db
        target_user = db.get_user_by_id(user_id)
        if not target_user:
            return web.json_response({"success": False, "error": "用户不存在"}, status=404)

        target_dc_id = int(body.get("target_dc_id") or target_user.get("dc_id") or 5)
        from botfather_creator import provision_user_storage_channel
        chan_meta = await provision_user_storage_channel(
            username=target_user["username"],
            tg_user_id=target_user.get("tg_user_id"),
            target_dc_id=target_dc_id,
        )
        # 安全护栏：如果用户已有旧存储频道且与新频道不同，自动将旧频道追加至 extra_channels，彻底杜绝孤儿媒体！
        old_cid = target_user.get("bin_channel_id")
        current_extras = db.parse_extra_channels(target_user.get("extra_channels"))
        if old_cid and int(old_cid) != int(chan_meta["bin_channel_id"]):
            if int(old_cid) not in current_extras:
                current_extras.append(int(old_cid))

        updated = db.update_user_record(
            user_id,
            dc_id=chan_meta["dc_id"],
            bin_channel_id=chan_meta["bin_channel_id"],
            bin_channel_username=chan_meta["bin_channel_username"],
            creator_account_id=chan_meta.get("creator_account_id"),
            extra_channels=current_extras,
        )
        if updated:
            updated.pop("password_hash", None)
        return web.json_response({
            "success": True,
            "message": f"已为用户 {target_user['username']} 开通专属存储频道 @{chan_meta['bin_channel_username']} (DC{chan_meta['dc_id']})",
            "user": updated,
            "channel": chan_meta,
        })
    except Exception as e:
        logger.error(f"为用户开通专属频道失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"开通专属频道失败: {e}"}, status=500)


@routes.put("/api/users/{id}")
async def admin_update_user_handler(request: web.Request):
    """管理员修改用户角色、TG 绑定或手动指定专属频道"""
    admin_user = _require_admin_user(request)
    if not admin_user:
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        user_id = int(request.match_info["id"])
        body = await request.json()
        import db
        target_user = db.get_user_by_id(user_id)
        if not target_user:
            return web.json_response({"success": False, "error": "用户不存在"}, status=404)

        updates = {}
        if "username" in body and body["username"]:
            uname = str(body["username"]).strip()
            existing = db.get_user_by_username(uname)
            if existing and existing["id"] != user_id:
                return web.json_response({"success": False, "error": f"用户名 {uname} 已被占用"}, status=400)
            updates["username"] = uname

        if "role" in body and body["role"] in ("user", "admin"):
            if target_user.get("role") == "admin" and body["role"] == "user":
                if admin_user.get("uid") == user_id:
                    return web.json_response({"success": False, "error": "不能将当前登录的管理员自身降级为普通用户"}, status=400)
                admins = [u for u in db.list_users() if u.get("role") == "admin"]
                if len(admins) <= 1:
                    return web.json_response({"success": False, "error": "必须保留至少一个管理员账号"}, status=400)
            updates["role"] = body["role"]

        for int_field in ("tg_user_id", "dc_id", "bin_channel_id", "creator_account_id"):
            if int_field in body:
                val = body[int_field]
                updates[int_field] = int(val) if val not in (None, "", 0, "0") else None

        for str_field in ("tg_username", "tg_first_name", "bin_channel_username"):
            if str_field in body:
                val = str(body[str_field] or "").strip().lstrip("@")
                updates[str_field] = val or None

        updated = db.update_user_record(user_id, **updates)
        if updated:
            updated.pop("password_hash", None)
        return web.json_response({
            "success": True,
            "message": "用户信息已更新",
            "user": updated,
        })
    except Exception as e:
        logger.error(f"更新用户信息失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"更新失败: {e}"}, status=500)


@routes.post("/api/users/{id}/reset-password")
async def admin_reset_user_password_handler(request: web.Request):
    """管理员重置指定用户的登录密码并吊销其旧会话"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        user_id = int(request.match_info["id"])
        body = await request.json() if request.can_read_body else {}
        import db
        from auth import hash_password
        target_user = db.get_user_by_id(user_id)
        if not target_user:
            return web.json_response({"success": False, "error": "用户不存在"}, status=404)

        new_password = str(body.get("new_password") or "").strip()
        if not new_password or new_password.lower() == "auto":
            new_password = _generate_random_user_password()
        elif len(new_password) < 8:
            return web.json_response({"success": False, "error": "新密码长度不能少于 8 位"}, status=400)

        db.update_user_password(user_id, hash_password(new_password))
        revoked = db.revoke_user_sessions(user_id, reason="admin_password_reset")
        return web.json_response({
            "success": True,
            "message": f"用户 {target_user['username']} 密码已重置 (已下线 {revoked} 个旧会话)",
            "new_password": new_password,
            "revoked_sessions": revoked,
        })
    except Exception as e:
        logger.error(f"重置用户密码失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"重置密码失败: {e}"}, status=500)


@routes.delete("/api/users/{id}")
async def admin_delete_user_handler(request: web.Request):
    """管理员删除指定租户账号"""
    admin_user = _require_admin_user(request)
    if not admin_user:
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        user_id = int(request.match_info["id"])
        if admin_user.get("uid") == user_id:
            return web.json_response({"success": False, "error": "禁止删除当前登录的管理员自身"}, status=400)
        cleanup_records = str(request.query.get("cleanup_records") or "").lower() in ("1", "true", "yes")
        import db
        res = db.delete_user_record(user_id, delete_media_records=cleanup_records)
        return web.json_response({
            "success": True,
            "message": f"用户 {res.get('deleted_username')} 已删除",
            "data": res,
        })
    except PermissionError as pe:
        return web.json_response({
            "success": False,
            "error": str(pe),
            "protected": True,
        }, status=403)
    except ValueError as ve:
        return web.json_response({"success": False, "error": str(ve)}, status=400)
    except Exception as e:
        logger.error(f"删除用户失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"删除用户失败: {e}"}, status=500)

# ==================== 租户专属频道无损平移与全量灾备接口 ====================

@routes.post("/api/users/{id}/migrate-channel/start")
async def admin_start_user_channel_migration_handler(request: web.Request):
    """管理员启动指定租户专属存储频道的无损平移任务"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        user_id = int(request.match_info["id"])
        body = await request.json() if request.can_read_body else {}
        target_dc_id = body.get("target_dc_id")
        target_dc_val = int(target_dc_id) if target_dc_id not in (None, "", 0, "0") else None
        custom_target_cid = body.get("custom_target_channel_id")
        custom_cid_val = int(custom_target_cid) if custom_target_cid not in (None, "", 0, "0") else None

        from channel_migrator import get_migration_manager
        mgr = get_migration_manager()
        task_dict = await mgr.start_migration(
            user_id=user_id,
            target_dc_id=target_dc_val,
            custom_target_channel_id=custom_cid_val,
        )
        return web.json_response({
            "success": True,
            "message": "租户专属频道无损平移任务已启动",
            "data": task_dict,
        })
    except (ValueError, RuntimeError) as ve:
        return web.json_response({"success": False, "error": str(ve)}, status=400)
    except Exception as e:
        logger.error(f"启动租户频道迁移失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"启动迁移失败: {e}"}, status=500)


@routes.get("/api/users/{id}/migrate-channel/status")
async def admin_get_user_channel_migration_status_handler(request: web.Request):
    """管理员查询指定租户专属频道的无损平移任务实时状态与终端日志"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        user_id = int(request.match_info["id"])
        from channel_migrator import get_migration_manager
        mgr = get_migration_manager()
        task = mgr.get_task(user_id)
        if not task:
            return web.json_response({
                "success": True,
                "data": None,
                "status": "idle",
            })
        return web.json_response({
            "success": True,
            "data": task.to_dict(),
            "status": task.status,
        })
    except Exception as e:
        logger.error(f"查询租户频道迁移状态失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"查询迁移状态失败: {e}"}, status=500)


@routes.post("/api/users/{id}/migrate-channel/cancel")
async def admin_cancel_user_channel_migration_handler(request: web.Request):
    """管理员安全中止正在进行的租户专属频道迁移任务"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        user_id = int(request.match_info["id"])
        from channel_migrator import get_migration_manager
        mgr = get_migration_manager()
        ok = await mgr.cancel_migration(user_id)
        if not ok:
            return web.json_response({"success": False, "error": "当前没有正在运行的迁移任务"}, status=400)
        return web.json_response({
            "success": True,
            "message": "已发送中止信号，迁移任务将在当前文件完成后安全停止",
        })
    except Exception as e:
        logger.error(f"取消租户频道迁移失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"取消迁移失败: {e}"}, status=500)


@routes.get("/api/system/backups")
async def list_system_backups_handler(request: web.Request):
    """管理员列出系统全量备份归档及自动备份计划"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        import backup_manager
        backups = await asyncio.to_thread(backup_manager.list_backups)
        schedule = backup_manager.get_backup_schedule()
        return web.json_response({
            "success": True,
            "backups": backups,
            "schedule": schedule,
            "backup_dir": backup_manager.get_backup_dir(),
        })
    except Exception as e:
        logger.error(f"获取系统备份列表失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"获取备份列表失败: {e}"}, status=500)


@routes.post("/api/system/backups/create")
async def create_system_backup_handler(request: web.Request):
    """管理员立即触发一次全量在线一致性备份（SQLite + Sessions + Config）"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        body = await request.json() if request.can_read_body else {}
        remark = str(body.get("remark") or "").strip()
        import backup_manager
        result = await asyncio.to_thread(backup_manager.create_backup, remark=remark)
        return web.json_response({
            "success": True,
            "message": f"全量数据灾备归档已生成: {result['filename']}",
            "data": result,
        })
    except Exception as e:
        logger.error(f"创建全量备份失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"创建备份失败: {e}"}, status=500)


@routes.get("/api/system/backups/schedule")
async def get_backup_schedule_handler(request: web.Request):
    """查询自动灾备周期配置"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        import backup_manager
        return web.json_response({
            "success": True,
            "schedule": backup_manager.get_backup_schedule(),
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/system/backups/schedule")
async def set_backup_schedule_handler(request: web.Request):
    """更新自动灾备周期配置"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        body = await request.json() if request.can_read_body else {}
        enabled = bool(body.get("enabled", False))
        interval_hours = int(body.get("interval_hours", 24) or 24)
        max_keep = int(body.get("max_keep", 15) or 15)
        import backup_manager
        sched = backup_manager.set_backup_schedule(enabled, interval_hours, max_keep)
        return web.json_response({
            "success": True,
            "message": "自动备份策略已保存",
            "schedule": sched,
        })
    except Exception as e:
        return web.json_response({"success": False, "error": f"保存自动备份策略失败: {e}"}, status=500)


@routes.get("/api/system/backups/{filename}/download")
async def download_system_backup_handler(request: web.Request):
    """安全流式下载指定备份归档文件至本地"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        filename = request.match_info["filename"]
        import backup_manager
        fpath = backup_manager.get_backup_filepath(filename)
        if not fpath:
            return web.json_response({"success": False, "error": "备份文件不存在"}, status=404)
        return web.FileResponse(
            path=fpath,
            headers={
                "Content-Disposition": f'attachment; filename="{os.path.basename(fpath)}"',
                "Content-Type": "application/gzip",
            },
        )
    except ValueError as ve:
        return web.json_response({"success": False, "error": str(ve)}, status=400)
    except Exception as e:
        logger.error(f"下载备份文件失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"下载备份失败: {e}"}, status=500)


@routes.post("/api/system/backups/upload")
async def upload_system_backup_handler(request: web.Request):
    """上传外部备份包（.tar.gz 或 .db）至灾备仓库"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        import backup_manager
        content_type = request.headers.get("Content-Type", "")
        orig_filename = ""
        file_bytes = b""

        if "multipart/form-data" in content_type:
            reader = await request.multipart()
            while True:
                part = await reader.next()
                if part is None:
                    break
                if part.filename:
                    orig_filename = part.filename
                    chunks = []
                    while True:
                        chunk = await part.read_chunk(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    file_bytes = b"".join(chunks)
                    break
        else:
            orig_filename = request.query.get("filename") or request.headers.get("X-Backup-Filename") or "backup_uploaded.tar.gz"
            file_bytes = await request.read()

        if not file_bytes:
            return web.json_response({"success": False, "error": "未接收到有效的备份文件数据"}, status=400)

        saved = await asyncio.to_thread(backup_manager.save_uploaded_backup, orig_filename, file_bytes)
        return web.json_response({
            "success": True,
            "message": f"备份包上传并校验成功: {saved['filename']}",
            "data": saved,
        })
    except ValueError as ve:
        return web.json_response({"success": False, "error": str(ve)}, status=400)
    except Exception as e:
        logger.error(f"上传备份文件失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"上传备份失败: {e}"}, status=500)


@routes.post("/api/system/backups/{filename}/restore")
async def restore_system_backup_handler(request: web.Request):
    """从指定备份归档恢复系统数据（支持 union 增量并集与 overwrite 全量覆盖）"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        filename = request.match_info["filename"]
        data = await request.json() if request.can_read_body else {}
        mode = str(data.get("mode") or "union").strip().lower()
        if mode not in ("union", "overwrite"):
            mode = "union"
        import backup_manager
        res = await asyncio.to_thread(backup_manager.restore_backup, filename, mode=mode)
        mode_desc = "增量并集恢复 (Union)" if mode == "union" else "全量覆盖还原 (Overwrite)"
        return web.json_response({
            "success": True,
            "message": f"系统已成功从 {filename} 完成{mode_desc}！(已自动生成事前安全快照 {res.get('safety_snapshot')})",
            "data": res,
        })
    except FileNotFoundError as fnf:
        return web.json_response({"success": False, "error": str(fnf)}, status=404)
    except ValueError as ve:
        return web.json_response({"success": False, "error": str(ve)}, status=400)
    except Exception as e:
        logger.error(f"从备份恢复失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"恢复失败: {e}"}, status=500)


@routes.delete("/api/system/backups/{filename}")
async def delete_system_backup_handler(request: web.Request):
    """删除指定的历史备份归档"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        filename = request.match_info["filename"]
        import backup_manager
        deleted = backup_manager.delete_backup(filename)
        if not deleted:
            return web.json_response({"success": False, "error": "备份文件不存在"}, status=404)
        return web.json_response({
            "success": True,
            "message": f"已删除备份归档: {filename}",
        })
    except ValueError as ve:
        return web.json_response({"success": False, "error": str(ve)}, status=400)
    except Exception as e:
        logger.error(f"删除备份失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"删除备份失败: {e}"}, status=500)


@routes.post("/api/auth/logout")
async def auth_logout_handler(request: web.Request):
    """退出桌面客户端长期会话。"""
    try:
        body = await request.json()
        refresh_token = body.get("refresh_token", "")
        if not isinstance(refresh_token, str) or not refresh_token:
            return web.json_response({"success": False, "error": "refresh_token 不能为空"}, status=400)

        from db import revoke_auth_session
        from auth import hash_refresh_token, rotate_signing_secret

        revoked = revoke_auth_session(hash_refresh_token(refresh_token), reason="logout")
        if revoked:
            # MistRelay has a single recovery-controlled administrator. Rotating
            # the in-memory key makes logout revoke outstanding access tokens too.
            rotate_signing_secret()
        return web.json_response({"success": True})
    except Exception as e:
        logger.error(f"退出登录失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": "退出登录失败"}, status=500)


@routes.get("/api/auth/me", allow_head=True)
async def auth_me_handler(request: web.Request):
    """获取当前登录用户信息"""
    user = request.get("user")
    if not user:
        return web.json_response({"success": False, "error": "未登录"}, status=401)
    from db import get_user_by_id
    db_user = get_user_by_id(user["uid"])
    if not db_user:
        return web.json_response({"success": False, "error": "用户不存在"}, status=401)
    return web.json_response({"success": True, "user": db_user})


@routes.post("/api/auth/password")
async def auth_change_password_handler(request: web.Request):
    """修改密码"""
    try:
        user = request.get("user")
        if not user:
            return web.json_response({"success": False, "error": "未登录"}, status=401)
        body = await request.json()
        old_password = body.get("old_password", "")
        new_password = body.get("new_password", "")
        if not old_password or not new_password:
            return web.json_response({"success": False, "error": "请填写旧密码和新密码"}, status=400)
        if not isinstance(old_password, str) or not isinstance(new_password, str):
            return web.json_response({"success": False, "error": "密码格式无效"}, status=400)
        if not 16 <= len(new_password) <= 512:
            return web.json_response({"success": False, "error": "新密码长度必须为16-512位"}, status=400)
        if len(old_password) > 512:
            return web.json_response({"success": False, "error": "旧密码错误"}, status=401)

        from db import get_user_by_username, revoke_user_sessions, update_user_password
        from auth import hash_password, rotate_signing_secret, verify_password
        db_user = get_user_by_username(user["sub"])
        if not db_user or not verify_password(old_password, db_user["password_hash"]):
            return web.json_response({"success": False, "error": "旧密码错误"}, status=400)

        update_user_password(db_user["id"], hash_password(new_password))
        revoke_user_sessions(db_user["id"], reason="password_changed")
        rotate_signing_secret()
        logger.info(
            "auth.password changed remote=%s user_id=%s",
            get_client_ip(request),
            db_user["id"],
        )
        return web.json_response({"success": True, "message": "密码修改成功，请重新登录"})
    except Exception as e:
        logger.error(f"修改密码失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": "修改密码失败"}, status=500)


@routes.get("/api/health", allow_head=True)
async def api_health_handler(_):
    """Minimal liveness/readiness response for proxies and container health checks."""
    from service_runtime import is_service_ready

    telegram_connected = bool(
        (StreamBot and getattr(StreamBot, "is_connected", False))
        or any(getattr(c, "is_connected", False) for c in multi_clients.values())
    )
    ready = is_service_ready() and telegram_connected
    return web.json_response(
        {
            "server_status": "running" if ready else "starting",
            "ready": ready,
            "telegram_connected": telegram_connected,
            "version": f"v{__version__}",
        },
        status=200 if ready else 503,
    )


@routes.get("/api/status", allow_head=True)
async def api_status_handler(request: web.Request):
    """API状态接口（管理员返回完整集群信息，租户返回脱敏服务与专属频道状态）"""
    # 安全获取bot用户名（可能在Telegram初始化完成前调用）
    bot_username = ""
    if StreamBot:
        try:
            if hasattr(StreamBot, 'username') and StreamBot.username:
                bot_username = "@" + StreamBot.username
            elif hasattr(StreamBot, 'get_me'):
                try:
                    bot_info = await StreamBot.get_me()
                    bot_username = "@" + (bot_info.username if bot_info.username else "unknown")
                except Exception as e:
                    # 检查是否是Telegram限流错误
                    if is_flood_wait_error(e):
                        bot_username = "限流中"
                    else:
                        bot_username = "@unknown"
            else:
                bot_username = "@unknown"
        except Exception as e:
            # 检查是否是Telegram限流错误
            if is_flood_wait_error(e):
                bot_username = "限流中"
            else:
                bot_username = "@unknown"

    user_payload = request.get("user") if hasattr(request, "get") else None
    if user_payload and user_payload.get("role") != "admin":
        import db
        db_u = db.get_user_by_id(user_payload.get("uid")) or {}
        tenant_channel_id = db_u.get("bin_channel_id")
        tenant_channel_username = db_u.get("bin_channel_username") or ""
        is_public_channel = bool(tenant_channel_username and not str(tenant_channel_username).startswith("channel_"))
        return web.json_response(
            {
                "server_status": "running",
                "uptime": utils.get_readable_time(time.time() - StartTime),
                "telegram_bot": bot_username or "@unknown",
                "connected_bots": 1 if multi_clients else 0,
                "channel_info": {
                    "channel_id": tenant_channel_id,
                    "channel_type": "public" if is_public_channel else "private",
                    "public_handle": tenant_channel_username if is_public_channel else "",
                    "no_join_balancing_active": is_public_channel,
                },
                "version": f"v{__version__}",
            }
        )
    
    import WebStreamer.bot as bot_mod
    public_handle = getattr(bot_mod, "channel_public_handle", None)
    bot_modes = getattr(bot_mod, "bot_channel_modes", {})
    write_clients = getattr(bot_mod, "channel_write_clients", set())

    bot_details = []
    runtime_snapshots = get_bot_runtime_snapshot()
    for index in sorted(multi_clients.keys()):
        client = multi_clients.get(index)
        uname = getattr(client, "username", "") or ""
        mode_entry = bot_modes.get(index, {})
        mode = mode_entry.get("mode") or (
            "primary_admin" if index == 0 else (
                "direct_admin" if index in write_clients else (
                    "no_join_resolved" if index in channel_accessible_clients else "unreachable"
                )
            )
        )
        can_read = index in channel_accessible_clients
        can_write = index in write_clients or index == 0
        clean_uname = uname.lstrip("@")
        invite_url = (
            f"https://t.me/{clean_uname}?startchannel&admin=post_messages+edit_messages+delete_messages"
            if clean_uname else ""
        )
        snap_m = runtime_snapshots.get(index, {})
        bot_details.append({
            "index": index,
            "name": f"bot{index + 1}",
            "username": f"@{clean_uname}" if clean_uname else f"bot{index + 1}",
            "mode": mode,
            "home_dc": snap_m.get("home_dc"),
            "warm_dcs": snap_m.get("warm_dcs", []),
            "can_read": can_read,
            "can_write": can_write,
            "active_requests": work_loads.get(index, 0),
            "invite_url": invite_url,
        })

    channel_info = {
        "channel_id": Var.BIN_CHANNEL,
        "channel_type": "public" if public_handle else "private",
        "public_handle": public_handle or "",
        "no_join_balancing_active": bool(public_handle),
        "accessible_bots": len(channel_accessible_clients),
        "write_bots": len(write_clients) if write_clients else (1 if 0 in multi_clients else 0),
    }

    return web.json_response(
        {
            "server_status": "running",
            "uptime": utils.get_readable_time(time.time() - StartTime),
            "telegram_bot": bot_username or "@unknown",
            "connected_bots": len(multi_clients),
            "channel_info": channel_info,
            "bot_details": bot_details,
            "loads": dict(
                ("bot" + str(index + 1), work_loads.get(index, 0))
                for index in sorted(multi_clients.keys())
            ),
            "dc_partitions": bot_mod.get_dc_partition_summary(),
            "bot_metrics": dict(
                (
                    "bot" + str(index + 1),
                    {
                        "active_requests": metrics["active_requests"],
                        "cooldown_remaining": metrics["cooldown_remaining"],
                        "failure_streak": metrics["failure_streak"],
                        "throughput_bps": metrics["throughput_bps"],
                        "bytes_served": metrics["bytes_served"],
                    },
                )
                for index, metrics in get_bot_runtime_snapshot().items()
            ),
            "version": f"v{__version__}",
        }
    )

@routes.get("/", allow_head=True)
async def root_route_handler(request: web.Request):
    """根路径:返回前端页面"""
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        response = web.FileResponse(index_file)
        # index.html 使用协商缓存,允许浏览器缓存但每次验证
        response.headers['Cache-Control'] = 'no-cache'
        return response
    else:
        # 降级到 API 状态(开发环境或前端未构建时)
        logger.warning("前端 index.html 不存在,返回 API 状态")
        return await api_health_handler(request)


@routes.get("/api/system/docker/status", allow_head=True)
async def docker_status_handler(request: web.Request):
    """获取Docker容器状态"""
    if not DOCKER_CONTROL_ENABLED:
        in_docker = os.path.exists("/.dockerenv")
        payload = {
            "success": True,
            "in_docker": in_docker,
            "status": "running",
            "status_source": "application",
            "control_enabled": False,
            "control_message": "宿主 Docker 控制未启用，当前状态来自应用自检",
            "created": datetime.fromtimestamp(StartTime).astimezone().isoformat(),
            "application_version": f"v{__version__}",
        }
        if in_docker:
            payload["container_name"] = (
                os.environ.get("MISTRELAY_CONTAINER_NAME", "mistrelay").strip()
                or "mistrelay"
            )
        return web.json_response(payload)
    try:
        # 检查是否在Docker容器内
        if not os.path.exists("/.dockerenv"):
            return web.json_response({
                "success": False,
                "error": "不在Docker容器内运行",
                "in_docker": False
            })
        
        # 检查Docker SDK是否可用
        if not DOCKER_AVAILABLE:
            return web.json_response({
                "success": False,
                "error": "Docker Python SDK不可用，请安装docker包",
                "in_docker": True
            })
        
        # 使用Docker Python SDK查找当前容器
        try:
            client = docker.from_env()
            container = None
            
            # 方法1: 尝试通过容器ID查找（从cgroup获取）
            container_id = None
            try:
                with open("/proc/self/cgroup", "r") as f:
                    for line in f:
                        if "docker" in line:
                            container_id = line.split("/")[-1].strip()
                            break
            except Exception:
                pass
            
            # 方法2: 尝试通过容器名称查找（优先使用docker-compose的container_name）
            container_names = ["mistrelay"]  # docker-compose.yml中的container_name
            
            # 方法3: 尝试通过HOSTNAME查找
            hostname = os.environ.get("HOSTNAME", "")
            if hostname and hostname not in container_names:
                container_names.append(hostname)
            
            # 如果从cgroup获取到ID，优先使用ID查找
            if container_id:
                try:
                    container = client.containers.get(container_id)
                except docker.errors.NotFound:
                    pass
            
            # 如果ID查找失败，尝试通过名称查找
            if not container:
                for name in container_names:
                    try:
                        containers = client.containers.list(filters={"name": name})
                        if containers:
                            container = containers[0]
                            break
                    except Exception:
                        continue
            
            # 如果还是找不到，尝试获取所有容器并匹配
            if not container:
                all_containers = client.containers.list(all=True)
                # 尝试通过ID匹配
                if container_id:
                    for c in all_containers:
                        if container_id in c.id or container_id in c.name:
                            container = c
                            break
                # 如果还是找不到，使用第一个运行中的容器（通常是当前容器）
                if not container and all_containers:
                    container = all_containers[0]
            
            if container:
                container.reload()  # 刷新容器信息
                return web.json_response({
                    "success": True,
                    "in_docker": True,
                    "container_name": container.name,
                    "status": container.status,
                    "image": container.image.tags[0] if container.image.tags else container.image.id,
                    "created": container.attrs.get("Created", ""),
                    "status_source": "docker",
                    "control_enabled": True,
                    "application_version": f"v{__version__}",
                })
            else:
                return web.json_response({
                    "success": False,
                    "error": "无法找到容器",
                    "in_docker": True
                })
        except docker.errors.APIError as e:
            logger.error(f"Docker API错误: {e}")
            return web.json_response({
                "success": False,
                "error": f"Docker API错误: {str(e)}"
            })
    except Exception as e:
        logger.error(f"获取Docker状态失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        })


@routes.post("/api/system/docker/restart")
async def docker_restart_handler(request: web.Request):
    """重启Docker容器（热重载）"""
    if not DOCKER_CONTROL_ENABLED:
        return web.json_response({
            "success": False,
            "error": "Docker 控制接口已禁用",
        }, status=403)
    try:
        # 检查是否在Docker容器内
        if not os.path.exists("/.dockerenv"):
            return web.json_response({
                "success": False,
                "error": "不在Docker容器内运行，无法重启"
            })
        
        # 检查Docker SDK是否可用
        if not DOCKER_AVAILABLE:
            return web.json_response({
                "success": False,
                "error": "Docker Python SDK不可用，请安装docker包"
            })
        
        # 使用Docker Python SDK查找当前容器
        try:
            client = docker.from_env()
            container = None
            
            # 方法1: 尝试通过容器ID查找（从cgroup获取）
            container_id = None
            try:
                with open("/proc/self/cgroup", "r") as f:
                    for line in f:
                        if "docker" in line:
                            container_id = line.split("/")[-1].strip()
                            break
            except Exception:
                pass
            
            # 方法2: 尝试通过容器名称查找（优先使用docker-compose的container_name）
            container_names = ["mistrelay"]  # docker-compose.yml中的container_name
            
            # 方法3: 尝试通过HOSTNAME查找
            hostname = os.environ.get("HOSTNAME", "")
            if hostname and hostname not in container_names:
                container_names.append(hostname)
            
            # 如果从cgroup获取到ID，优先使用ID查找
            if container_id:
                try:
                    container = client.containers.get(container_id)
                except docker.errors.NotFound:
                    pass
            
            # 如果ID查找失败，尝试通过名称查找
            if not container:
                for name in container_names:
                    try:
                        containers = client.containers.list(filters={"name": name})
                        if containers:
                            container = containers[0]
                            break
                    except Exception:
                        continue
            
            # 如果还是找不到，尝试获取所有容器并匹配
            if not container:
                all_containers = client.containers.list(all=True)
                # 尝试通过ID匹配
                if container_id:
                    for c in all_containers:
                        if container_id in c.id or container_id in c.name:
                            container = c
                            break
                # 如果还是找不到，使用第一个运行中的容器（通常是当前容器）
                if not container and all_containers:
                    container = all_containers[0]
            
            if container:
                container.restart(timeout=10)
                return web.json_response({
                    "success": True,
                    "message": f"容器 {container.name} 重启成功",
                    "container_name": container.name
                })
            else:
                return web.json_response({
                    "success": False,
                    "error": f"无法找到容器: {container_id}"
                })
        except docker.errors.APIError as e:
            logger.error(f"Docker API错误: {e}")
            return web.json_response({
                "success": False,
                "error": f"Docker API错误: {str(e)}"
            })
    except Exception as e:
        logger.error(f"重启Docker容器失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        })


@routes.get("/api/system/docker/logs", allow_head=True)
async def docker_logs_handler(request: web.Request):
    """获取Docker容器日志"""
    lines = _bounded_log_lines(request.query.get("lines", "100"))
    if not DOCKER_CONTROL_ENABLED:
        return _application_log_response(lines)
    try:
        # 检查是否在Docker容器内
        if not os.path.exists("/.dockerenv"):
            return _application_log_response(lines)
        
        # 检查Docker SDK是否可用
        if not DOCKER_AVAILABLE:
            return _application_log_response(lines)
        
        # 获取容器ID或名称
        container_id = os.environ.get("HOSTNAME", "")
        if not container_id:
            try:
                with open("/proc/self/cgroup", "r") as f:
                    for line in f:
                        if "docker" in line:
                            container_id = line.split("/")[-1].strip()
                            break
            except Exception:
                pass
        
        if not container_id:
            container_id = "mistrelay"
        
        # 使用Docker Python SDK查找当前容器
        try:
            client = docker.from_env()
            container = None
            
            # 方法1: 尝试通过容器ID查找（从cgroup获取）
            container_id = None
            try:
                with open("/proc/self/cgroup", "r") as f:
                    for line in f:
                        if "docker" in line:
                            container_id = line.split("/")[-1].strip()
                            break
            except Exception:
                pass
            
            # 方法2: 尝试通过容器名称查找（优先使用docker-compose的container_name）
            container_names = ["mistrelay"]  # docker-compose.yml中的container_name
            
            # 方法3: 尝试通过HOSTNAME查找
            hostname = os.environ.get("HOSTNAME", "")
            if hostname and hostname not in container_names:
                container_names.append(hostname)
            
            # 如果从cgroup获取到ID，优先使用ID查找
            if container_id:
                try:
                    container = client.containers.get(container_id)
                except docker.errors.NotFound:
                    pass
            
            # 如果ID查找失败，尝试通过名称查找
            if not container:
                for name in container_names:
                    try:
                        containers = client.containers.list(filters={"name": name})
                        if containers:
                            container = containers[0]
                            break
                    except Exception:
                        continue
            
            # 如果还是找不到，尝试获取所有容器并匹配
            if not container:
                all_containers = client.containers.list(all=True)
                # 尝试通过ID匹配
                if container_id:
                    for c in all_containers:
                        if container_id in c.id or container_id in c.name:
                            container = c
                            break
                # 如果还是找不到，使用第一个运行中的容器（通常是当前容器）
                if not container and all_containers:
                    container = all_containers[0]
            
            if container:
                logs = container.logs(tail=lines, timestamps=False).decode('utf-8', errors='replace')
                return web.json_response({
                    "success": True,
                    "logs": logs,
                    "lines": lines,
                    "source": "docker",
                })
            else:
                return _application_log_response(lines)
        except docker.errors.APIError as e:
            logger.warning("Docker API日志读取失败，使用应用日志: %s", e)
            return _application_log_response(lines)
    except Exception as e:
        logger.warning("获取Docker日志失败，使用应用日志: %s", e, exc_info=True)
        return _application_log_response(lines)


@routes.get("/api/system/resources", allow_head=True)
async def system_resources_handler(request: web.Request):
    """获取系统资源使用情况（CPU、内存、硬盘）"""
    try:
        if not PSUTIL_AVAILABLE:
            return web.json_response({
                "success": False,
                "error": "psutil不可用，请安装psutil包"
            })
        
        # CPU使用率
        cpu_percent = psutil.cpu_percent(interval=0.1)
        
        # 内存使用情况
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        memory_total = memory.total
        memory_used = memory.used
        memory_available = memory.available
        
        # 硬盘使用情况（获取根目录所在分区）
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_total = disk.total
        disk_used = disk.used
        disk_free = disk.free
        
        return web.json_response({
            "success": True,
            "data": {
                "cpu": {
                    "percent": round(cpu_percent, 2)
                },
                "memory": {
                    "percent": round(memory_percent, 2),
                    "total": memory_total,
                    "used": memory_used,
                    "available": memory_available
                },
                "disk": {
                    "percent": round(disk_percent, 2),
                    "total": disk_total,
                    "used": disk_used,
                    "free": disk_free
                }
            }
        })
    except Exception as e:
        logger.error(f"获取系统资源失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        })


@routes.get("/api/system/docker/logs/ws")
async def docker_logs_ws_handler(request: web.Request):
    """WebSocket实时推送Docker容器日志"""
    protocols = (request["websocket_protocol"],) if request.get("websocket_protocol") else ()
    ws = web.WebSocketResponse(heartbeat=30, protocols=protocols)
    await ws.prepare(request)

    tail_lines = _bounded_log_lines(request.query.get("tail", "100"))
    if not DOCKER_CONTROL_ENABLED or not DOCKER_AVAILABLE or not os.path.exists("/.dockerenv"):
        try:
            await _stream_application_logs(ws, tail_lines)
        finally:
            await ws.close()
        return ws
    
    try:
        # 查找容器
        container = None
        try:
            client = docker.from_env()
            container_id = None
            
            # 方法1: 尝试通过容器ID查找（从cgroup获取）
            try:
                with open("/proc/self/cgroup", "r") as f:
                    for line in f:
                        if "docker" in line:
                            container_id = line.split("/")[-1].strip()
                            break
            except Exception:
                pass
            
            # 方法2: 尝试通过容器名称查找
            container_names = ["mistrelay"]
            hostname = os.environ.get("HOSTNAME", "")
            if hostname and hostname not in container_names:
                container_names.append(hostname)
            
            # 如果从cgroup获取到ID，优先使用ID查找
            if container_id:
                try:
                    container = client.containers.get(container_id)
                except docker.errors.NotFound:
                    pass
            
            # 如果ID查找失败，尝试通过名称查找
            if not container:
                for name in container_names:
                    try:
                        containers = client.containers.list(filters={"name": name})
                        if containers:
                            container = containers[0]
                            break
                    except Exception:
                        continue
            
            # 如果还是找不到，尝试获取所有容器并匹配
            if not container:
                all_containers = client.containers.list(all=True)
                if container_id:
                    for c in all_containers:
                        if container_id in c.id or container_id in c.name:
                            container = c
                            break
                if not container and all_containers:
                    container = all_containers[0]
            
            if not container:
                logger.warning("未找到当前容器，使用应用日志流")
                await _stream_application_logs(ws, tail_lines)
                return ws
            
            # 先发送历史日志
            try:
                logs = container.logs(tail=tail_lines, timestamps=False).decode('utf-8', errors='replace')
                await ws.send_json({
                    "type": "history",
                    "logs": logs
                })
            except Exception as e:
                logger.warning("获取Docker历史日志失败，使用应用日志流: %s", e)
                await _stream_application_logs(ws, tail_lines)
                return ws
            
            # 开始实时流式推送日志
            await ws.send_json({
                "type": "stream_start",
                "message": "开始实时日志流"
            })
            
            # 使用Docker的logs API的stream模式（异步处理）
            try:
                import asyncio
                import threading
                
                # 创建事件来控制日志流
                stop_event = threading.Event()
                log_queue = asyncio.Queue()
                
                # 获取当前事件循环
                loop = asyncio.get_running_loop()

                def read_logs_thread():
                    """在后台线程中读取Docker日志流"""
                    try:
                        log_stream = container.logs(stream=True, follow=True, timestamps=False, tail=0)
                        
                        for log_chunk in log_stream:
                            if stop_event.is_set() or ws.closed:
                                break
                            
                            try:
                                log_line = log_chunk.decode('utf-8', errors='replace').rstrip('\n\r')
                                if log_line:
                                    # 将日志行放入队列
                                    asyncio.run_coroutine_threadsafe(
                                        log_queue.put(log_line),
                                        loop
                                    )
                            except Exception as e:
                                logger.error(f"处理日志行失败: {e}", exc_info=True)
                                continue
                                
                    except Exception as e:
                        logger.error(f"日志流线程错误: {e}", exc_info=True)
                        if not ws.closed:
                            asyncio.run_coroutine_threadsafe(
                                ws.send_json({
                                    "type": "error",
                                    "message": f"日志流错误: {str(e)}"
                                }),
                                loop
                            )
                
                # 启动后台线程读取日志
                log_thread = threading.Thread(target=read_logs_thread, daemon=True)
                log_thread.start()
                
                # 从队列中读取日志并发送
                try:
                    while not ws.closed and not stop_event.is_set():
                        try:
                            # 等待日志行，设置超时以便定期检查连接状态
                            log_line = await asyncio.wait_for(log_queue.get(), timeout=1.0)
                            await ws.send_json({
                                "type": "log",
                                "line": log_line
                            })
                        except asyncio.TimeoutError:
                            # 超时是正常的，继续循环检查连接状态
                            continue
                        except Exception as e:
                            logger.error(f"发送日志行失败: {e}")
                            break
                finally:
                    # 停止日志流线程
                    stop_event.set()
                    log_thread.join(timeout=2)
                    
                        
            except Exception as e:
                logger.error(f"日志流错误: {e}", exc_info=True)
                await ws.send_json({
                    "type": "error",
                    "message": f"日志流错误: {str(e)}"
                })
                
        except docker.errors.APIError as e:
            logger.warning("Docker API日志流失败，使用应用日志流: %s", e)
            await _stream_application_logs(ws, tail_lines)
        except Exception as e:
            logger.warning("Docker日志流失败，使用应用日志流: %s", e, exc_info=True)
            await _stream_application_logs(ws, tail_lines)
            
    except Exception as e:
        logger.error(f"WebSocket连接错误: {e}", exc_info=True)
        try:
            await ws.send_json({
                "type": "error",
                "message": f"连接错误: {str(e)}"
            })
        except Exception:
            pass
    
    finally:
        await ws.close()
    
    return ws


@routes.get("/api/config", allow_head=True)
async def get_config_handler(request: web.Request):
    """获取系统配置"""
    try:
        category = request.query.get('category')
        configs = get_all_configs(category=category)
        if category in ('stream', None):
            rebrand_defaults = {
                'FORWARD_REBRAND_ENABLED': True,
                'FORWARD_TARGET_CHANNEL': '',
                'FORWARD_CHANNEL_SIGNATURE': '',
                'FORWARD_CLEAN_FILENAMES': True,
                'FORWARD_CUSTOM_REPLACE_RULES': '',
            }
            for k, def_val in rebrand_defaults.items():
                if k not in configs:
                    configs[k] = def_val
        system_defaults = {
            'ALLOW_USER_REGISTRATION': True,
            'DEFAULT_TENANT_DC_ID': 5,
            'TENANT_CHANNEL_PREFIX': 'mr_u',
            'PROTOCOL_KEEPALIVE_ENABLED': True,
            'PROTOCOL_KEEPALIVE_INTERVAL_HOURS': 12,
            'TELEGRAM_API_PROXY_URL': 'https://white.novproxy.com/white/api?region=US&num=1&time=10&format=1&type=txt',
            'MAX_CONCURRENT_UPLOADS': 10,
            'THUMBNAIL_CACHE_MAX_AGE_DAYS': 30,
            'MAX_CONCURRENT_MESSAGES': 5,
            'MAX_MESSAGE_QUEUE_SIZE': 100,
        }
        for k, def_val in system_defaults.items():
            if k not in configs and (not category or category in ('telegram', 'download', 'stream', 'upload', 'cache')):
                configs[k] = def_val

        redacted_keys = []
        secret_counts = {}
        for key in SECRET_CONFIG_KEYS:
            if key not in configs:
                continue
            value = configs[key]
            if value:
                redacted_keys.append(key)
            if isinstance(value, list):
                secret_counts[key] = len(value)
            configs[key] = [] if isinstance(value, list) else ""
        return web.json_response({
            "success": True,
            "data": configs,
            "redacted_keys": sorted(redacted_keys),
            "secret_counts": secret_counts,
            "offline_only_keys": [],
        })
    except Exception as e:
        logger.error(f"获取配置失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.post("/api/config")
async def update_config_handler(request: web.Request):
    """更新系统配置"""
    try:
        data = await request.json()
        
        # 验证请求数据
        if not isinstance(data, dict):
            return web.json_response({
                "success": False,
                "error": "请求数据格式错误"
            }, status=400)
        
        # 配置项定义：key -> (value_type, category, description)
        config_definitions = {
            'API_ID': ('int', 'telegram', 'Telegram API ID'),
            'API_HASH': ('string', 'telegram', 'Telegram API Hash'),
            'BOT_TOKEN': ('string', 'telegram', 'Telegram Bot Token'),
            'ADMIN_ID': ('int', 'telegram', 'Telegram管理员ID'),
            'UP_TELEGRAM': ('bool', 'telegram', '是否上传到Telegram频道网盘'),
            'ALLOW_USER_REGISTRATION': ('bool', 'telegram', '是否允许新用户通过 Telegram /register 自助注册'),
            'DEFAULT_TENANT_DC_ID': ('int', 'telegram', '新租户建频默认数据中心偏好 (1~5)'),
            'TENANT_CHANNEL_PREFIX': ('string', 'telegram', '租户公开存储频道 Handle 命名前缀'),
            'PROTOCOL_KEEPALIVE_ENABLED': ('bool', 'telegram', '协议号后台定时保活巡检总开关'),
            'PROTOCOL_KEEPALIVE_INTERVAL_HOURS': ('int', 'telegram', '协议号自动保活巡检间隔小时数'),
            'TELEGRAM_API_PROXY_URL': ('string', 'telegram', '提取 API 凭证的动态家宽代理 API 模板'),
            'SAVE_PATH': ('string', 'download', '下载保存路径'),
            'PROXY_IP': ('string', 'download', '代理IP'),
            'PROXY_PORT': ('string', 'download', '代理端口'),
            'SKIP_SMALL_FILES': ('bool', 'download', '是否跳过小于指定大小的媒体文件'),
            'MIN_FILE_SIZE_MB': ('int', 'download', '最小文件大小（MB），小于此大小的文件将被跳过'),
            'DOWNLOAD_CLEANUP_ENABLED': ('bool', 'download', '是否启用下载目录自动清理'),
            'DOWNLOAD_RETENTION_HOURS': ('int', 'download', '下载文件保留小时数'),
            'DOWNLOAD_CLEANUP_INTERVAL_SECONDS': ('int', 'download', '下载目录清理间隔秒数'),
            'THUMBNAIL_CACHE_MAX_AGE_DAYS': ('int', 'cache', '缩略图缓存保留天数'),
            'RPC_SECRET': ('string', 'aria2', 'Aria2 RPC密钥'),
            'RPC_URL': ('string', 'aria2', 'Aria2 RPC URL'),
            'MAX_CONCURRENT_UPLOADS': ('int', 'upload', '最大并发上传数（默认10）'),
            'ENABLE_STREAM': ('bool', 'stream', '是否启用直链功能'),
            'BIN_CHANNEL': ('string', 'stream', '日志频道ID'),
            'STREAM_PORT': ('int', 'stream', 'Web服务器端口'),
            'STREAM_BIND_ADDRESS': ('string', 'stream', 'Web服务器绑定地址'),
            'STREAM_HASH_LENGTH': ('int', 'stream', '哈希长度'),
            'STREAM_HAS_SSL': ('bool', 'stream', '是否使用SSL'),
            'STREAM_NO_PORT': ('bool', 'stream', '是否隐藏端口'),
            'STREAM_FQDN': ('string', 'stream', '完全限定域名'),
            'STREAM_KEEP_ALIVE': ('bool', 'stream', '是否保持连接活跃'),
            'STREAM_PING_INTERVAL': ('int', 'stream', 'Ping间隔（秒）'),
            'STREAM_USE_SESSION_FILE': ('bool', 'stream', '是否使用会话文件'),
            'STREAM_ALLOWED_USERS': ('string', 'stream', '允许使用直链的数字用户 ID 列表'),
            'STREAM_AUTO_DOWNLOAD': ('bool', 'stream', '历史兼容：是否自动添加到下载队列'),
            'SEND_STREAM_LINK': ('bool', 'stream', '是否发送直链信息给用户'),
            'MAX_CONCURRENT_MESSAGES': ('int', 'stream', '消息处理最大并发数'),
            'MAX_MESSAGE_QUEUE_SIZE': ('int', 'stream', '消息等待队列上限（1-1000）'),
            'MULTI_BOT_TOKENS': ('list', 'stream', '多机器人Token列表'),
            'FORWARD_REBRAND_ENABLED': ('bool', 'stream', '启用转发无痕洗白（抹除转发标并清洗配文）'),
            'FORWARD_TARGET_CHANNEL': ('string', 'stream', '归属替换目标频道（留空自动使用本频道）'),
            'FORWARD_CHANNEL_SIGNATURE': ('string', 'stream', '配文落款签名（支持{channel}占位符）'),
            'FORWARD_CLEAN_FILENAMES': ('bool', 'stream', '净化入库媒体文件名中的第三方引流广告'),
            'FORWARD_CUSTOM_REPLACE_RULES': ('string', 'stream', '自定义剔除或替换规则（每行一条，原词=>新词）'),
        }
        
        # 需要重启才能生效的配置项
        requires_restart = {
            'API_ID', 'API_HASH', 'BOT_TOKEN', 'ADMIN_ID', 'BIN_CHANNEL',
            'STREAM_PORT', 'STREAM_BIND_ADDRESS', 'STREAM_HASH_LENGTH',
            'STREAM_HAS_SSL', 'STREAM_NO_PORT', 'STREAM_FQDN',
            'STREAM_USE_SESSION_FILE', 'MULTI_BOT_TOKENS',
            'PROXY_IP', 'PROXY_PORT', 'RPC_SECRET', 'RPC_URL', 'SAVE_PATH'
        }
        
        updates = []
        errors = []
        needs_restart = False
        
        for key, value in data.items():
            if key in config_definitions:
                value_type, category, description = config_definitions[key]
                try:
                    if key in SECRET_CONFIG_KEYS and value in (None, "", []):
                        continue
                    if key == "MULTI_BOT_TOKENS":
                        value = merge_additional_bot_tokens(
                            get_config(key, []),
                            value,
                            get_config("BOT_TOKEN", ""),
                        )
                    current_value = get_config(key, None)
                    if key in requires_restart and (current_value is None or (value != current_value and str(value) != str(current_value))):
                        needs_restart = True
                    updates.append((key, value, value_type, category, description))
                except Exception as e:
                    errors.append(f"{key}: {str(e)}")
            else:
                errors.append(f"{key}: 未知的配置项")
        
        if errors:
            return web.json_response({
                "success": False,
                "error": f"部分配置更新失败: {', '.join(errors)}",
                "updated_count": 0,
                "needs_restart": needs_restart
            }, status=400)

        set_configs(updates)
        updated_count = len(updates)
        
        # 配置已保存到数据库，下次使用时将从数据库读取
        # 对于需要重启的配置，提示用户重启服务
        # 对于不需要重启的配置，下次使用时自动从数据库读取最新值
        
        return web.json_response({
            "success": True,
            "message": f"成功更新 {updated_count} 个配置项" + ("，需要重启服务才能生效" if needs_restart else "，下次使用时将从数据库读取最新配置"),
            "updated_count": updated_count,
            "needs_restart": needs_restart
        })
    except Exception as e:
        logger.error(f"更新配置失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.post("/api/aria2/test")
async def test_aria2_connection_handler(request: web.Request):
    """测试 Aria2 RPC 连通性并获取版本与当前任务状态"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)
        client = get_aria2_client()
        if not client:
            return web.json_response({
                "success": False,
                "error": "Aria2 客户端未就绪或未启动"
            }, status=503)
        ver = await client.get_version()
        stat = await client.get_global_stat()
        opts = await client.get_global_option()
        return web.json_response({
            "success": True,
            "data": {
                "version": ver.get("version", "未知"),
                "download_dir": opts.get("dir", "/data/downloads"),
                "num_active": int(stat.get("numActive", 0)),
                "num_waiting": int(stat.get("numWaiting", 0)),
                "num_stopped": int(stat.get("numStopped", 0)),
                "download_speed": int(stat.get("downloadSpeed", 0)),
                "max_concurrent": int(opts.get("max-concurrent-downloads", 10)),
            }
        })
    except Exception as e:
        return web.json_response({
            "success": False,
            "error": f"Aria2 RPC 连通测试失败: {str(e)}"
        }, status=500)


@routes.post("/api/telegram/rebrand/preview")
async def rebrand_preview_handler(request: web.Request):
    """实时预览配文与文件名清洗效果（仅限管理员）"""
    try:
        user = request.get("user") if hasattr(request, "get") else None
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)
        data = await request.json()
        if not isinstance(data, dict):
            return web.json_response({"success": False, "error": "请求格式错误"}, status=400)
        caption = data.get("caption", "")
        filename = data.get("filename", "")
        target_channel = data.get("target_channel")
        signature = data.get("signature")
        clean_filenames = data.get("clean_filenames", True)
        custom_rules = data.get("custom_rules")

        from WebStreamer.utils.rebrand_cleaner import (
            clean_and_rebrand_caption,
            clean_drive_filename,
            get_effective_target_channel,
        )
        effective_channel = get_effective_target_channel(target_channel)
        cleaned_caption = clean_and_rebrand_caption(
            caption,
            target_channel=target_channel,
            signature=signature,
            custom_rules=custom_rules,
        )
        cleaned_filename = clean_drive_filename(
            filename,
            clean_enabled=bool(clean_filenames),
            custom_rules=custom_rules,
        )
        return web.json_response({
            "success": True,
            "data": {
                "effective_channel": effective_channel,
                "cleaned_caption": cleaned_caption,
                "cleaned_filename": cleaned_filename,
            }
        })
    except Exception as e:
        logger.error(f"预览洗白效果失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/config/reload")
async def reload_config_handler(request: web.Request):
    """Reject online imports that could replace locked credentials or destinations."""
    return web.json_response({
        "success": False,
        "error": "配置导入只能在停机维护窗口离线执行",
    }, status=403)


RCLONE_DEPRECATED_MESSAGE = "第三方网盘已废弃，请使用 Telegram 频道网盘"


def rclone_deprecated_response(**extra):
    payload = {
        "success": False,
        "error": RCLONE_DEPRECATED_MESSAGE,
        "deprecated": True,
        **extra,
    }
    return web.json_response(payload, status=410)


@routes.get("/api/rclone/config", allow_head=True)
async def get_rclone_config_handler(request: web.Request):
    return rclone_deprecated_response()


@routes.post("/api/rclone/config")
async def save_rclone_config_handler(request: web.Request):
    return rclone_deprecated_response()


@routes.get("/api/rclone/remotes", allow_head=True)
async def get_rclone_remotes_handler(request: web.Request):
    return rclone_deprecated_response(remotes=[])


@routes.get("/api/rclone/about", allow_head=True)
async def get_rclone_about_handler(request: web.Request):
    return rclone_deprecated_response(supported=False)


@routes.get("/api/rclone/browse", allow_head=True)
async def browse_drive_handler(request: web.Request):
    return rclone_deprecated_response(items=[])


@routes.get("/api/rclone/thumbnail", allow_head=True)
async def get_thumbnail_handler(request: web.Request):
    return rclone_deprecated_response()


@routes.get("/api/rclone/thumbnail/serve/{remote}/{filename}", allow_head=True)
async def serve_thumbnail_handler(request: web.Request):
    return rclone_deprecated_response()


@routes.get("/api/rclone/file", allow_head=True)
async def get_rclone_file_handler(request: web.Request):
    return rclone_deprecated_response()


@routes.delete("/api/rclone/file")
async def delete_rclone_file_handler(request: web.Request):
    return rclone_deprecated_response()


@routes.get("/api/downloads", allow_head=True)

async def downloads_api_handler(request: web.Request):
    """
    API接口：返回下载记录JSON数据

    支持查询参数:
      - limit: 返回的最大记录数（默认 100，最大 500）
      - grouped: 是否按消息分组（默认 true）
    """
    try:
        limit_param = int(request.query.get("limit", "100"))
    except ValueError:
        limit_param = 100
    limit_param = max(1, min(limit_param, 500))
    
    grouped = request.query.get("grouped", "true").lower() == "true"

    user_payload = request.get("user") if hasattr(request, "get") else None
    filter_uid = user_payload.get("uid") if (user_payload and user_payload.get("role") != "admin") else None

    if grouped:
        from db import fetch_downloads_grouped
        groups = fetch_downloads_grouped(limit_param, user_id=filter_uid)
        total_downloads = sum(len(g['downloads']) for g in groups)
        return web.json_response({
            "success": True,
            "limit": limit_param,
            "count": total_downloads,
            "group_count": len(groups),
            "grouped": True,
            "data": groups
        })
    else:
        records = fetch_recent_downloads(limit_param, user_id=filter_uid)
        return web.json_response({
            "success": True,
            "limit": limit_param,
            "count": len(records),
            "grouped": False,
            "data": records
        })


@routes.get("/api/downloads/statistics", allow_head=True)
async def downloads_statistics_handler(request: web.Request):
    """
    API接口：返回下载统计信息
    """
    try:
        user_payload = request.get("user") if hasattr(request, "get") else None
        filter_uid = user_payload.get("uid") if (user_payload and user_payload.get("role") != "admin") else None
        from db import get_download_statistics
        stats = get_download_statistics(user_id=filter_uid)
        return web.json_response({
            "success": True,
            "data": stats
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"获取下载统计失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.delete("/api/downloads/all")
async def delete_all_downloads_handler(request: web.Request):
    """
    API接口：删除所有下载记录、上传记录和媒体记录（非管理员仅清理自身记录）
    """
    try:
        user_payload = request.get("user") if hasattr(request, "get") else None
        filter_uid = user_payload.get("uid") if (user_payload and user_payload.get("role") != "admin") else None
        from db import delete_all_downloads
        result = delete_all_downloads(user_id=filter_uid)
        return web.json_response({
            "success": True,
            "message": f"已删除 {result['deleted_downloads']} 条下载记录、{result['deleted_uploads']} 条上传记录和 {result['deleted_media']} 条媒体记录",
            "data": result
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"删除所有记录失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/monitor/trend", allow_head=True)
async def monitor_trend_handler(request: web.Request):
    """
    API接口：返回系统监控历史趋势数据（仅限管理员访问）
    """
    try:
        user_payload = request.get("user") if hasattr(request, "get") else None
        if user_payload and user_payload.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足：仅系统管理员可访问此功能"}, status=403)
        from monitor import monitor
        history = monitor.get_history()
        return web.json_response({
            "success": True,
            "data": history
        })
    except Exception as e:
        logger.error(f"获取监控数据失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/uploads/statistics", allow_head=True)
async def uploads_statistics_handler(request: web.Request):
    """
    API接口：返回上传统计信息（支持租户按 user_id 过滤）
    """
    try:
        user_payload = request.get("user") if hasattr(request, "get") else None
        filter_uid = user_payload.get("uid") if (user_payload and user_payload.get("role") != "admin") else None
        from db import get_upload_statistics
        stats = get_upload_statistics(user_id=filter_uid)
        return web.json_response({
            "success": True,
            "data": stats
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"获取上传统计失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/uploads", allow_head=True)
async def uploads_api_handler(request: web.Request):
    """
    API接口：返回上传记录JSON数据（支持租户按 user_id 过滤）
    
    支持查询参数:
      - limit: 返回的最大记录数（默认 100，最大 500）
      - status: 按状态过滤（uploading/completed/failed/pending等）
      - upload_target: 按上传目标过滤；新任务为 telegram，旧记录可能是 onedrive/gdrive
    """
    try:
        limit_param = int(request.query.get("limit", "100"))
    except ValueError:
        limit_param = 100
    limit_param = max(1, min(limit_param, 500))
    
    status_filter = request.query.get("status")
    upload_target_filter = request.query.get("upload_target")
    user_payload = request.get("user") if hasattr(request, "get") else None
    filter_uid = user_payload.get("uid") if (user_payload and user_payload.get("role") != "admin") else None
    
    try:
        from db import fetch_recent_uploads
        records = fetch_recent_uploads(
            limit=limit_param,
            status=status_filter,
            upload_target=upload_target_filter,
            user_id=filter_uid,
        )
        return web.json_response({
            "success": True,
            "limit": limit_param,
            "count": len(records),
            "data": records
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"获取上传记录失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/ws/status")
async def ws_status_handler(request: web.Request):
    """
    WebSocket 端点：实时推送下载/上传/清理状态更新
    """
    protocols = (request["websocket_protocol"],) if request.get("websocket_protocol") else ()
    ws = web.WebSocketResponse(heartbeat=30, protocols=protocols)
    await ws.prepare(request)
    
    try:
        # 添加连接到管理器（带租户身份信息）
        user_payload = request.get("user") if hasattr(request, "get") else None
        await ws_manager.add_connection(
            ws,
            user_id=user_payload.get("uid") if user_payload else None,
            role=user_payload.get("role", "admin") if user_payload else "admin",
        )
        
        # 发送初始状态
        try:
            user_payload = request.get("user") if hasattr(request, "get") else None
            filter_uid = user_payload.get("uid") if (user_payload and user_payload.get("role") != "admin") else None
            from db import get_download_statistics, get_upload_statistics
            download_stats = get_download_statistics(user_id=filter_uid)
            upload_stats = get_upload_statistics(user_id=filter_uid)
            
            await ws.send_json({
                "type": "initial",
                "data": {
                    "downloads": download_stats,
                    "uploads": upload_stats
                }
            })
            # 立即推送边缘节点最新状态，免除前端初始额外 GET 请求
            try:
                import db
                from edge_node_manager import compute_edge_summary
                init_edge_nodes = db.list_edge_nodes(tenant_id=filter_uid, include_secrets=False)
                init_summary = compute_edge_summary(init_edge_nodes)
                await ws.send_json({
                    "type": "edge_nodes_update",
                    "data": {
                        "nodes": init_edge_nodes,
                        "summary": init_summary,
                    }
                })
            except Exception as e_nodes:
                logger.debug(f"发送初始边缘节点状态失败: {e_nodes}")
        except Exception as e:
            logger.error(f"发送初始状态失败: {e}")
        
        # 保持连接，等待客户端关闭
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                # 可以处理客户端发送的消息（如果需要）
                try:
                    data = json.loads(msg.data)
                    if data.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                    elif data.get("type") == "get_edge_nodes":
                        user_payload = request.get("user") if hasattr(request, "get") else None
                        filter_uid = user_payload.get("uid") if (user_payload and user_payload.get("role") != "admin") else None
                        import db
                        from edge_node_manager import compute_edge_summary
                        edge_nodes = db.list_edge_nodes(tenant_id=filter_uid, include_secrets=False)
                        summary = compute_edge_summary(edge_nodes)
                        await ws.send_json({
                            "type": "edge_nodes_update",
                            "data": {
                                "nodes": edge_nodes,
                                "summary": summary,
                            }
                        })
                except Exception:
                    pass
            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f"WebSocket 错误: {ws.exception()}")
                break
            elif msg.type == web.WSMsgType.CLOSE:
                break
                
    except Exception as e:
        logger.error(f"WebSocket 连接错误: {e}", exc_info=True)
    finally:
        # 移除连接
        await ws_manager.remove_connection(ws)
        await ws.close()
    
    return ws


@routes.get("/api/queue", allow_head=True)
async def queue_api_handler(request: web.Request):
    """
    API接口:返回消息队列状态（支持租户按专属频道或 Telegram ID 过滤）
    """
    try:
        user_payload = request.get("user") if hasattr(request, "get") else None
        filter_for_tenant = False
        tenant_chat_id = None
        tenant_tg_uid = None
        if user_payload and user_payload.get("role") not in (None, "admin"):
            filter_for_tenant = True
            try:
                import db
                u = db.get_user_by_id(user_payload.get("uid"))
                if u:
                    tenant_chat_id = u.get("bin_channel_id")
                    tenant_tg_uid = u.get("tg_user_id")
            except Exception:
                pass

        # 导入队列状态函数
        try:
            from WebStreamer.bot.plugins.stream import get_queue_status
            try:
                queue_status = await get_queue_status(chat_id=tenant_chat_id, tg_user_id=tenant_tg_uid, filter_for_tenant=filter_for_tenant)
            except TypeError:
                queue_status = await get_queue_status()
            return web.json_response({
                "success": True,
                **queue_status
            })
        except ImportError:
            # 如果直链功能未启用,返回空队列
            return web.json_response({
                "success": True,
                "current_processing": None,
                "waiting_count": 0,
                "waiting_items": [],
                "queue_size": 0
            })
    except Exception as e:
        logger.error(f"获取队列状态失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


# ==================== 下载任务控制 API ====================

def is_tg_stream_download_record(download_record: dict) -> bool:
    """Return True for old records created from this service's TG stream URLs."""
    source_url = str(download_record.get('source_url') or '')
    if not source_url:
        return False

    current_stream_base = str(getattr(Var, 'URL', '') or '')
    if current_stream_base and source_url.startswith(current_stream_base):
        return True

    if not download_record.get('file_unique_id'):
        return False

    # Older records may keep a stream URL generated with a previous domain/FQDN.
    return bool(
        re.match(r"^https?://[^/]+/\d+/.+\?hash=", source_url)
        or re.match(r"^https?://[^/]+/[A-Za-z0-9_-]{5,64}\d+$", source_url)
    )


@routes.post("/api/downloads/{gid}/retry")
async def retry_download_handler(request: web.Request):
    """重试下载任务（重新提交到aria2）"""
    try:
        gid = request.match_info["gid"]

        # 获取下载记录
        download_id = get_download_id_by_gid(gid)
        if not download_id:
            return web.json_response({
                "success": False,
                "error": "找不到下载记录"
            }, status=404)
        
        download_record = get_download_by_id(download_id)
        if not download_record:
            return web.json_response({
                "success": False,
                "error": "下载记录不存在"
            }, status=404)

        user_payload = request.get("user") if hasattr(request, "get") else None
        filter_uid = user_payload.get("uid") if (user_payload and user_payload.get("role") != "admin") else None
        if filter_uid is not None and download_record.get("user_id") != filter_uid:
            return web.json_response({
                "success": False,
                "error": "权限不足，无法操作其他用户的下载任务"
            }, status=403)
        
        source_url = download_record.get('source_url')
        if not source_url:
            return web.json_response({
                "success": False,
                "error": "无法获取下载源URL，无法重试"
            }, status=400)

        if is_tg_stream_download_record(download_record):
            return web.json_response({
                "success": False,
                "error": "TG网盘文件不再重新提交到aria2，请在TG网盘页面直接播放或下载",
                "tg_drive": True
            })

        client = get_aria2_client()
        if not client:
            logger.error("Aria2客户端未初始化，这不应该发生！请检查服务启动流程")
            return web.json_response({
                "success": False,
                "error": "Aria2客户端未初始化，请检查服务是否正常启动"
            }, status=503)
        
        try:
            # 尝试移除旧任务（如果还在aria2中）
            try:
                remove_result = await client.remove(gid)
                # 检查返回结果中是否包含错误
                if remove_result and isinstance(remove_result, dict) and 'error' in remove_result:
                    error_info = remove_result['error']
                    error_msg = error_info.get('message', '') if isinstance(error_info, dict) else str(error_info)
                    # 如果错误是"not found"，这是正常的（历史遗留记录），静默处理
                    if 'not found' in error_msg.lower():
                        logger.debug(f"移除旧任务失败（任务已不存在，历史遗留记录）: {error_msg}")
                    else:
                        logger.debug(f"移除旧任务失败: {error_msg}")
            except Exception as remove_err:
                # 如果移除失败（任务可能已经不存在），继续执行
                error_msg = str(remove_err)
                if 'not found' not in error_msg.lower():
                    logger.debug(f"移除旧任务失败（可能已不存在）: {remove_err}")
            
            # 重新提交到aria2
            result = await client.add_uri(uris=[source_url])
            
            if not result or 'result' not in result:
                return web.json_response({
                    "success": False,
                    "error": "重新提交到aria2失败"
                }, status=500)
            
            new_gid = result.get('result')
            
            # 更新数据库中的 gid 和状态
            from db import get_connection
            now_iso = datetime.utcnow().isoformat(timespec="seconds") + 'Z'
            with get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "UPDATE downloads SET gid = ?, status = 'pending', error_message = NULL, retry_count = retry_count + 1, updated_at = ? WHERE id = ?",
                    (new_gid, now_iso, download_id)
                )
                conn.commit()
            
            return web.json_response({
                "success": True,
                "message": f"任务已重新提交到aria2，新GID: {new_gid}",
                "new_gid": new_gid
            })
        except Exception as e:
            error_msg = str(e)
            # 如果是Aria2任务不存在的错误，忽略它（历史遗留记录）
            if 'not found' in error_msg.lower():
                logger.info(f"重试下载任务时Aria2任务不存在（历史遗留记录）: {gid}")
                # 即使任务不存在，也尝试重新提交
                try:
                    result = await client.add_uri(uris=[source_url])
                    if result and 'result' in result:
                        new_gid = result.get('result')
                        # 更新数据库中的 gid 和状态
                        from db import get_connection
                        now_iso = datetime.utcnow().isoformat(timespec="seconds") + 'Z'
                        with get_connection() as conn:
                            conn.row_factory = sqlite3.Row
                            cur = conn.cursor()
                            cur.execute(
                                "UPDATE downloads SET gid = ?, status = 'pending', error_message = NULL, retry_count = retry_count + 1, updated_at = ? WHERE id = ?",
                                (new_gid, now_iso, download_id)
                            )
                            conn.commit()
                        
                        return web.json_response({
                            "success": True,
                            "message": f"任务已重新提交到aria2（旧任务不存在，已跳过），新GID: {new_gid}",
                            "new_gid": new_gid
                        })
                except Exception as retry_err:
                    logger.error(f"重新提交任务失败: {retry_err}", exc_info=True)
            
            logger.error(f"重试下载任务失败: {e}", exc_info=True)
            return web.json_response({
                "success": False,
                "error": error_msg
            }, status=500)
    except Exception as e:
        logger.error(f"重试下载任务API错误: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.delete("/api/downloads/{gid}")
async def delete_download_handler(request: web.Request):
    """删除下载任务（从aria2移除，并删除数据库记录）"""
    try:
        gid = request.match_info["gid"]

        download_id = get_download_id_by_gid(gid)
        user_payload = request.get("user") if hasattr(request, "get") else None
        filter_uid = user_payload.get("uid") if (user_payload and user_payload.get("role") != "admin") else None
        if filter_uid is not None:
            download_record = get_download_by_id(download_id) if download_id else None
            if not download_record or download_record.get("user_id") != filter_uid:
                return web.json_response({
                    "success": False,
                    "error": "权限不足，无法操作其他用户的下载任务"
                }, status=403)
        
        # 先尝试从Aria2移除任务
        client = get_aria2_client()
        aria2_removed = False
        if client:
            try:
                result = await client.remove(gid)
                if 'error' not in result:
                    aria2_removed = True
                else:
                    error_info = result['error']
                    error_msg = error_info.get('message', '删除失败') if isinstance(error_info, dict) else str(error_info)
                    # 如果任务不存在（Aria2重启后任务会消失），这是正常的，继续删除数据库记录
                    error_msg_lower = error_msg.lower()
                    if any(keyword in error_msg_lower for keyword in ['not found', 'is not found', '不存在', '找不到']):
                        logger.info(f"Aria2任务 {gid} 不存在（Aria2重启后任务已消失），将删除数据库记录")
                    else:
                        # 其他错误，记录但不阻止删除数据库记录
                        logger.warning(f"从Aria2移除任务失败: {error_msg}，将继续删除数据库记录")
            except Exception as e:
                error_msg = str(e)
                error_msg_lower = error_msg.lower()
                # 如果任务不存在（Aria2重启后任务会消失），这是正常的，继续删除数据库记录
                if any(keyword in error_msg_lower for keyword in ['not found', 'is not found', '不存在', '找不到']):
                    logger.info(f"Aria2任务 {gid} 不存在（Aria2重启后任务已消失），将删除数据库记录")
                else:
                    logger.warning(f"从Aria2移除任务失败: {error_msg}，将继续删除数据库记录")
        else:
            logger.warning("Aria2客户端未初始化，将直接删除数据库记录")
        
        # 无论Aria2任务是否存在，都删除数据库中的下载记录
        download_id = get_download_id_by_gid(gid)
        if download_id:
            try:
                result = delete_download_record(download_id, delete_local_file=False)  # 不删除本地文件，只删除记录
                if result.get('success'):
                    message = f"任务 {gid} 已删除"
                    if aria2_removed:
                        message += "（Aria2任务和数据库记录已删除）"
                    else:
                        message += "（Aria2任务不存在，已删除数据库记录）"
                    return web.json_response({
                        "success": True,
                        "message": message,
                        "data": result
                    })
                else:
                    return web.json_response({
                        "success": False,
                        "error": result.get('error', '删除数据库记录失败')
                    }, status=400)
            except Exception as e:
                logger.error(f"删除数据库记录失败: {e}", exc_info=True)
                return web.json_response({
                    "success": False,
                    "error": f"删除数据库记录失败: {str(e)}"
                }, status=500)
        else:
            # 数据库中没有记录，只返回成功（Aria2任务可能已经不存在）
            if aria2_removed:
                return web.json_response({
                    "success": True,
                    "message": f"任务 {gid} 已从Aria2删除（数据库中没有记录）"
                })
            else:
                return web.json_response({
                    "success": True,
                    "message": f"任务 {gid} 不存在（Aria2和数据库中都没有记录）"
                })
    except Exception as e:
        logger.error(f"删除下载任务API错误: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.delete("/api/downloads/record/{download_id}")
async def delete_download_record_handler(request: web.Request):
    """删除下载记录（从数据库删除记录和本地文件）"""
    try:
        download_id = int(request.match_info["download_id"])

        user_payload = request.get("user") if hasattr(request, "get") else None
        filter_uid = user_payload.get("uid") if (user_payload and user_payload.get("role") != "admin") else None
        if filter_uid is not None:
            download_record = get_download_by_id(download_id)
            if not download_record or download_record.get("user_id") != filter_uid:
                return web.json_response({
                    "success": False,
                    "error": "权限不足，无法删除其他用户的下载记录"
                }, status=403)
        
        # 获取是否删除本地文件的参数（默认为true）
        delete_file = request.query.get("delete_file", "true").lower() == "true"
        
        try:
            result = delete_download_record(download_id, delete_local_file=delete_file)
            if result.get('success'):
                return web.json_response({
                    "success": True,
                    "message": f"下载记录 {download_id} 已删除",
                    "data": result
                })
            else:
                # 如果删除失败，返回错误信息
                error_msg = result.get('error', '删除失败')
                # 如果是Aria2任务不存在的错误，忽略它（历史遗留记录）
                if 'not found' in error_msg.lower():
                    # 即使Aria2任务不存在，也认为删除成功（因为记录已删除）
                    return web.json_response({
                        "success": True,
                        "message": f"下载记录 {download_id} 已删除（Aria2任务不存在，已跳过）",
                        "data": result
                    })
                return web.json_response({
                    "success": False,
                    "error": error_msg
                }, status=400)
        except Exception as e:
            error_msg = str(e)
            # 如果是Aria2任务不存在的错误，忽略它（历史遗留记录）
            if 'not found' in error_msg.lower() or 'GID' in error_msg:
                logger.info(f"删除下载记录时出现Aria2相关错误（历史遗留记录）: {download_id}, 错误: {error_msg}")
                # 尝试直接删除记录（不尝试移除Aria2任务）
                try:
                    result = delete_download_record(download_id, delete_local_file=delete_file)
                    if result.get('success'):
                        return web.json_response({
                            "success": True,
                            "message": f"下载记录 {download_id} 已删除（Aria2任务不存在，已跳过）",
                            "data": result
                        })
                    else:
                        # 如果删除记录也失败，返回记录删除的错误
                        return web.json_response({
                            "success": False,
                            "error": result.get('error', '删除记录失败')
                        }, status=400)
                except Exception as retry_err:
                    logger.error(f"重新尝试删除记录失败: {retry_err}", exc_info=True)
                    # 如果重新尝试也失败，返回原始错误
                    return web.json_response({
                        "success": False,
                        "error": f"删除记录失败: {str(retry_err)}"
                    }, status=500)
            logger.error(f"删除下载记录失败: {e}", exc_info=True)
            return web.json_response({
                "success": False,
                "error": error_msg
            }, status=500)
    except ValueError:
        return web.json_response({
            "success": False,
            "error": "无效的下载记录ID"
        }, status=400)
    except Exception as e:
        logger.error(f"删除下载记录API错误: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


# ==================== 上传任务控制 API ====================

# 存储正在运行的上传任务进程（用于暂停/取消）
_upload_processes = {}
_upload_processes_lock = asyncio.Lock() if asyncio else None

@routes.post("/api/uploads/{upload_id}/retry")
async def retry_upload_handler(request: web.Request):
    """重试上传任务（仅支持Telegram频道网盘）"""
    try:
        upload_id = int(request.match_info["upload_id"])
        
        upload_record = get_upload_by_id(upload_id)
        if not upload_record:
            return web.json_response({
                "success": False,
                "error": "上传记录不存在"
            }, status=404)

        user_payload = request.get("user") if hasattr(request, "get") else None
        filter_uid = user_payload.get("uid") if (user_payload and user_payload.get("role") != "admin") else None
        if filter_uid is not None and upload_record.get("user_id") != filter_uid:
            return web.json_response({
                "success": False,
                "error": "权限不足，无法操作其他用户的上传任务"
            }, status=403)
        
        current_status = upload_record.get('status')
        # 允许所有状态重试，但已完成且已清理的任务可能需要特殊处理
        if current_status == 'completed' and upload_record.get('cleaned_at'):
            # 如果已完成且已清理，检查文件是否存在
            pass  # 继续检查文件是否存在
        
        download_id = upload_record.get('download_id')
        download_record = get_download_by_id(download_id) if download_id else None
        
        if not download_record:
            return web.json_response({
                "success": False,
                "error": "关联的下载记录不存在"
            }, status=404)
        
        local_path = download_record.get('local_path')
        if not local_path or not os.path.exists(local_path):
            return web.json_response({
                "success": False,
                "error": "本地文件不存在，无法重试上传"
            }, status=404)
        
        upload_target = upload_record.get('upload_target')
        gid = download_record.get('gid')
        
        # 重置重试计数和状态
        update_upload_status(
            upload_id, 
            'pending',
            retry_count=0,
            error_message=None,
            error_code=None,
            failure_reason=None
        )
        
        # 根据上传目标选择重试方式
        try:
            if upload_target in ['onedrive', 'gdrive']:
                update_upload_status(
                    upload_id,
                    'failed',
                    error_message='第三方网盘已废弃，请使用 Telegram 频道网盘',
                    error_code='DEPRECATED_TARGET',
                    failure_reason='deprecated_target'
                )
                return web.json_response({
                    "success": False,
                    "error": "第三方网盘上传目标已废弃，不能重试历史任务"
                }, status=410)
            elif upload_target == 'telegram':
                # Telegram: 使用上传处理器
                from aria2_client.upload_handler import UploadHandler
                
                upload_handler = UploadHandler(None, {})
                asyncio.create_task(
                    upload_handler.upload_to_telegram_with_load_balance(local_path, gid, upload_id=upload_id)
                )
                
                return web.json_response({
                    "success": True,
                    "message": f"上传任务 {upload_id} 已重新提交Telegram上传"
                })
            else:
                return web.json_response({
                    "success": False,
                    "error": f"不支持的上传目标: {upload_target}"
                }, status=400)
        except Exception as e:
            logger.error(f"重试上传任务失败: {e}", exc_info=True)
            mark_upload_failed(upload_id, 'code_error', str(e), 'EXCEPTION')
            return web.json_response({
                "success": False,
                "error": f"重试上传失败: {str(e)}"
            }, status=500)
    except ValueError:
        return web.json_response({
            "success": False,
            "error": "无效的上传ID"
        }, status=400)
    except Exception as e:
        logger.error(f"重试上传任务API错误: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.delete("/api/uploads/{upload_id}")
async def delete_upload_handler(request: web.Request):
    """删除/取消上传任务"""
    try:
        upload_id = int(request.match_info["upload_id"])
        
        upload_record = get_upload_by_id(upload_id)
        if not upload_record:
            return web.json_response({
                "success": False,
                "error": "上传记录不存在"
            }, status=404)

        user_payload = request.get("user") if hasattr(request, "get") else None
        filter_uid = user_payload.get("uid") if (user_payload and user_payload.get("role") != "admin") else None
        if filter_uid is not None and upload_record.get("user_id") != filter_uid:
            return web.json_response({
                "success": False,
                "error": "权限不足，无法操作其他用户的上传任务"
            }, status=403)
        
        current_status = upload_record.get('status')
        
        # 如果正在上传，先停止进程
        if current_status == 'uploading':
            if _upload_processes_lock:
                async with _upload_processes_lock:
                    if upload_id in _upload_processes:
                        process = _upload_processes[upload_id]
                        try:
                            if process and process.returncode is None:
                                process.terminate()
                                await asyncio.wait_for(process.wait(), timeout=5)
                        except Exception as e:
                            logger.warning(f"停止上传进程失败: {e}")
                        finally:
                            del _upload_processes[upload_id]
        
        # 更新状态为 cancelled
        update_upload_status(upload_id, 'cancelled')
        
        return web.json_response({
            "success": True,
            "message": f"上传任务 {upload_id} 已取消"
        })
    except ValueError:
        return web.json_response({
            "success": False,
            "error": "无效的上传ID"
        }, status=400)
    except Exception as e:
        logger.error(f"删除上传任务API错误: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


async def stream_handler(request: web.Request):
    """处理流媒体请求、静态文件请求或 SPA 路由"""
    path = request.match_info["path"]
    
    # 1. API 路由优先级最高
    if path.startswith("api/"):
        # 这些路径应该由其他路由处理,如果到这里说明路由不存在
        raise web.HTTPNotFound(text="API endpoint not found")
    
    # 2. 静态资源处理 (assets/, favicon.ico, robots.txt 等)
    if path.startswith("assets/"):
        # 前端静态资源 (CSS, JS, 图片等)
        try:
            file_path = resolve_under(STATIC_ASSET_ROOT, path[len("assets/"):])
        except UnsafePathError:
            raise web.HTTPNotFound(text="Static file not found")
        if file_path.exists() and file_path.is_file():
            response = web.FileResponse(file_path)
            # 添加强缓存头(1年),因为 Vite 构建的文件名包含哈希
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            return response
        raise web.HTTPNotFound(text="Static file not found")
    
    if path in ["favicon.ico", "robots.txt"]:
        file_path = FRONTEND_DIST / path
        if file_path.exists():
            return web.FileResponse(file_path)
        return web.Response(status=204)
    
    # 3. 尝试作为流媒体请求处理
    try:
        match = re.search(r"^([0-9a-f]{%s})(\d+)$" % (Var.HASH_LENGTH), path)
        if match:
            secure_hash = match.group(1)
            message_id = int(match.group(2))
            return await media_streamer(request, message_id, secure_hash)
        else:
            # 尝试从路径中提取消息ID
            message_id = int(re.search(r"(\d+)(?:\/.*)?", path).group(1))
            secure_hash = request.rel_url.query.get("hash")
            return await media_streamer(request, message_id, secure_hash)
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except web.HTTPException:
        raise
    except (AttributeError, BadStatusLine, ConnectionResetError):
        # 连接错误,尝试 SPA 回退
        pass
    except (ValueError, TypeError, KeyError):
        # 不是有效的流媒体路径,尝试 SPA 回退
        pass
    except Exception as e:
        logger.debug(f"流媒体请求处理失败: {e}, 尝试 SPA 回退")
    
    # 4. SPA 回退: 所有其他路径返回 index.html (Vue Router)
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return web.FileResponse(index_file)
    
    # 如果前端文件不存在,返回 404
    raise web.HTTPNotFound(text="Not Found")


class_cache = {}


def get_byte_streamer(client):
    streamer = class_cache.get(client)
    if streamer is None:
        streamer = utils.ByteStreamer(client)
        class_cache[client] = streamer
    return streamer


async def get_main_bot_file_properties(message_id: int, chat_id=None, force_refresh: bool = False):
    main_client = multi_clients.get(0) or StreamBot
    if not getattr(main_client, "is_connected", False):
        for idx in sorted(channel_accessible_clients or multi_clients.keys()):
            candidate = multi_clients.get(idx)
            if candidate and getattr(candidate, "is_connected", False):
                main_client = candidate
                break
    main_streamer = get_byte_streamer(main_client)
    return await main_streamer.get_file_properties(message_id, chat_id=chat_id, force_refresh=force_refresh)


def normalize_download_file_name(name: str | None) -> str:
    raw_name = (name or "").strip()
    if not raw_name:
        return ""

    base_name = raw_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip()
    if base_name in {"", ".", ".."}:
        return ""

    return base_name.replace("\r", " ").replace("\n", " ").replace('"', "'")


def get_file_id_media_type(file_id: str | None) -> str:
    if not file_id or FileId is None:
        return ""

    try:
        decoded = FileId.decode(file_id)
        file_type = getattr(decoded, "file_type", None)
        if file_type is None:
            return ""
        return getattr(file_type, "name", str(file_type)).lower()
    except Exception:
        return ""


def get_extension_from_mime(mime_type: str | None) -> str:
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if not mime:
        return ""

    extension = MIME_EXTENSION_OVERRIDES.get(mime) or mimetypes.guess_extension(mime) or ""
    if extension == ".jpe":
        return ".jpg"
    if extension == ".oga":
        return ".ogg"
    if extension == ".bin" and mime == "application/octet-stream":
        return ""
    return extension


def get_extension_from_media_type(media_type: str | None) -> str:
    media_key = (media_type or "").lower()
    return MEDIA_TYPE_EXTENSIONS.get(media_key, "")


def get_download_file_name(item: dict) -> str:
    file_name = normalize_download_file_name(item.get("file_name"))
    mime_type = item.get("mime_type")
    media_type = item.get("media_type") or get_file_id_media_type(item.get("file_id"))
    extension = get_extension_from_mime(mime_type) or get_extension_from_media_type(media_type) or ".bin"

    if file_name:
        path = Path(file_name)
        suffix = path.suffix.lower()
        if suffix and suffix in KNOWN_DOWNLOAD_SUFFIXES:
            return file_name
        if suffix and extension == ".bin":
            return file_name
        return f"{file_name}{extension}"

    message_id = item.get("message_id") or "unknown"
    return f"media_{message_id}{extension}"


def build_content_disposition(disposition: str, file_name: str) -> str:
    safe_name = normalize_download_file_name(file_name) or "download.bin"
    ascii_name = safe_name.encode("ascii", "ignore").decode("ascii").strip()
    if not ascii_name or ascii_name.startswith("."):
        suffix = Path(safe_name).suffix
        ascii_name = f"download{suffix or '.bin'}"
    ascii_name = ascii_name.replace("\\", "_").replace('"', "'")
    encoded_name = quote(safe_name, safe="")
    return f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'


def build_telegram_stream_url(item: dict, hash_len: int) -> str | None:
    uid = item.get("file_unique_id", "")
    mid = item.get("message_id")
    if not uid or not mid:
        return None
    if str(uid).startswith("telethon:"):
        return None

    secure_hash = utils.get_hash(uid, hash_len)
    raw_name = get_download_file_name(item)
    safe_name = quote(raw_name, safe="")
    return f"/{mid}/{safe_name}?hash={secure_hash}"


def build_telegram_thumbnail_url(item: dict) -> str | None:
    message_id = item.get("message_id")
    if not message_id:
        return None

    entry_type = item.get("entry_type")
    mime_type = (item.get("mime_type") or "").lower()
    group_mime_types = [
        str(value).lower()
        for value in (item.get("group_mime_types") or [])
        if value
    ]

    media_type = get_file_id_media_type(item.get("file_id"))
    file_name = (item.get("file_name") or "").lower()
    is_img_or_video_ext = any(file_name.endswith(ext) for ext in (
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".mp4", ".mkv", ".webm", ".mov", ".avi"
    ))

    supported = (
        any(value.startswith(("image/", "video/")) for value in group_mime_types)
        if entry_type == "folder"
        else (
            mime_type.startswith(("image/", "video/"))
            or media_type in ("photo", "video", "animation", "video_note")
            or is_img_or_video_ext
        )
    )
    if not supported:
        return None

    from auth import create_resource_ticket

    path = f"/api/telegram/thumbnail/{message_id}"
    chat_id = item.get("chat_id")
    ticket_resource = f"{path}?chat_id={chat_id}" if chat_id else path
    ticket = quote(create_resource_ticket(ticket_resource), safe="")
    if chat_id:
        return f"{path}?ticket={ticket}&chat_id={chat_id}"
    return f"{path}?ticket={ticket}"


def is_thumbnail_supported_mime(mime_type: str | None) -> bool:
    mime = (mime_type or "").lower()
    return mime.startswith(("image/", "video/"))


def get_thumbnail_response(path: Path, *, cache_hit: bool = False) -> web.FileResponse:
    headers = {
        "Content-Type": "image/webp",
        "Cache-Control": "public, max-age=86400",
        "X-MistRelay-Thumbnail-Cache": "hit" if cache_hit else "miss",
    }
    return web.FileResponse(path, headers=headers)


def get_thumbnail_fallback_path(kind: str = "default") -> Path:
    from PIL import Image, ImageDraw
    from thumbnail_generator import get_thumbnail_generator

    generator = get_thumbnail_generator()
    fallback_dir = generator.cache_dir / "telegram"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    fallback_path = fallback_dir / f"fallback-{kind}.webp"
    if fallback_path.exists():
        return fallback_path

    img = Image.new("RGB", (400, 300), "#f7faf8")
    draw = ImageDraw.Draw(img)
    draw.ellipse((48, 38, 352, 262), fill="#eef7f4")
    draw.rounded_rectangle((92, 82, 308, 212), radius=16, fill="#ffffff", outline="#d8e7df", width=2)
    draw.ellipse((174, 118, 226, 170), fill="#ffe3d9", outline="#203039", width=2)
    draw.polygon([(160, 124), (188, 92), (232, 122), (214, 112), (194, 126)], fill="#2f9e8f")
    draw.ellipse((186, 138, 192, 144), fill="#203039")
    draw.ellipse((208, 138, 214, 144), fill="#203039")
    draw.arc((190, 146, 212, 160), start=0, end=180, fill="#ff8a7a", width=2)
    draw.rounded_rectangle((176, 168, 224, 224), radius=12, fill="#ffffff", outline="#203039", width=2)
    img.save(fallback_path, "WEBP", quality=82, method=4)
    return fallback_path


async def download_telegram_media_sample(message_id: int, output_path: Path, max_bytes: int, chat_id: int | None = None) -> None:
    if max_bytes <= 0:
        raise RuntimeError("invalid thumbnail source size")

    rec = None
    target_dc = None
    try:
        import db
        if chat_id is not None:
            rec = db.get_tg_media_record_by_message_id(message_id, chat_id=chat_id)
        else:
            rec = db.get_tg_media_record_by_message_id(message_id)
        if FileId is not None and rec and rec.get("file_id"):
            target_dc = FileId.decode(rec["file_id"]).dc_id
    except Exception:
        pass

    target_chat = chat_id or (rec.get("chat_id") if rec else None) or Var.BIN_CHANNEL

    # 优先尝试直接下载 Telegram 消息内嵌的缩略图（针对视频/照片等仅 ~10KB，极速且不依赖 MP4 尾部 moov 索引）
    async def _try_extract_embedded_thumbnail(client_obj) -> bool:
        if not hasattr(client_obj, "get_messages") or not hasattr(client_obj, "download_media"):
            return False
        try:
            from WebStreamer.utils.file_properties import get_media_from_message
            msg = None
            try:
                msg = await client_obj.get_messages(target_chat, message_id)
            except Exception:
                import db
                chan_user = db.get_channel_username_by_chat_id(target_chat)
                if chan_user and hasattr(client_obj, "get_chat"):
                    try:
                        await client_obj.get_chat(chan_user)
                        msg = await client_obj.get_messages(target_chat, message_id)
                    except Exception:
                        pass

            if not msg or getattr(msg, "empty", False):
                return False

            media = get_media_from_message(msg)
            target_thumb_id = None
            if media is not None:
                if getattr(msg, "photo", None) and getattr(media, "file_id", None):
                    target_thumb_id = media.file_id
                elif getattr(media, "thumbs", None):
                    target_thumb_id = media.thumbs[-1].file_id
                elif getattr(media, "thumbnail", None):
                    target_thumb_id = media.thumbnail.file_id

            if target_thumb_id:
                buf = await client_obj.download_media(target_thumb_id, in_memory=True)
                if buf:
                    data = bytes(buf.getbuffer()) if hasattr(buf, "getbuffer") else bytes(buf)
                    if data and len(data) > 64:
                        output_path.write_bytes(data)
                        return True
        except Exception as thumb_err:
            logger.debug(f"直接提取 TG 内嵌缩略图尝试失败 target_chat={target_chat} mid={message_id}: {thumb_err}")
        return False

    attempted_indices = set()
    while True:
        index = select_stream_bot(prefer_channel=True, exclude_indices=attempted_indices, target_dc=target_dc)
        if index is None:
            raise RuntimeError("No valid clients available")
        if index not in multi_clients:
            attempted_indices.add(index)
            continue

        client = multi_clients[index]

        # 优先在选定 client 上尝试直接提取内嵌缩略图
        if await _try_extract_embedded_thumbnail(client):
            mark_bot_success(index)
            return

        # 若选定 client 提取失败且存在主客户端 StreamBot (通常作为专属频道管理员)，且 client 不是主客户端，在 StreamBot 上重试一次
        from WebStreamer.bot import StreamBot
        if StreamBot and client != StreamBot:
            if await _try_extract_embedded_thumbnail(StreamBot):
                mark_bot_success(index)
                return

        streamer = get_byte_streamer(client)
        try:
            try:
                file_id = await streamer.get_file_properties(message_id, chat_id=target_chat, force_refresh=False)
            except TypeError:
                file_id = await streamer.get_file_properties(message_id, force_refresh=False)
            await streamer.generate_media_session(client, file_id)
            mark_bot_success(index)
            break
        except Exception as error:
            attempted_indices.add(index)
            mark_bot_failure(index, error)
            if len(attempted_indices) >= max(1, len(multi_clients)):
                raise

    chunk_size = 1024 * 1024
    bytes_to_fetch = min(max_bytes, int(getattr(file_id, "file_size", 0) or 0))
    if bytes_to_fetch <= 0:
        raise RuntimeError("empty thumbnail source")

    body = streamer.yield_file(
        file_id,
        index,
        0,
        0,
        (bytes_to_fetch - 1) % chunk_size + 1,
        max(1, math.ceil(bytes_to_fetch / chunk_size)),
        chunk_size,
    )

    written = 0
    with output_path.open("wb") as output:
        async for chunk in body:
            if not chunk:
                continue
            remaining = bytes_to_fetch - written
            output.write(chunk[:remaining])
            written += min(len(chunk), remaining)
            if written >= bytes_to_fetch:
                break

    if written <= 0:
        raise RuntimeError("thumbnail source download produced no data")


def get_channel_deletion_clients() -> list[tuple[int, object]]:
    """按负载升序返回具有频道删除权限的 bot 客户端。"""
    import WebStreamer.bot as bot_mod
    write_clients = getattr(bot_mod, "channel_write_clients", None)
    candidate_indices = [
        idx for idx in (write_clients or channel_accessible_clients)
        if idx in multi_clients
    ]

    if not candidate_indices:
        candidate_indices = [0] if 0 in multi_clients else list(multi_clients.keys())

    candidate_indices.sort(key=lambda idx: work_loads.get(idx, 0))
    return [(idx, multi_clients[idx]) for idx in candidate_indices if idx in multi_clients]


def is_ignorable_delete_message_error(error: Exception) -> bool:
    """消息已经不存在时允许继续清理数据库记录。"""
    error_text = str(error).lower()
    ignorable_markers = [
        "message_id_invalid",
        "msg_id_invalid",
        "message ids are empty",
        "message to delete not found",
        "message not found",
        "message identifier is not specified",
    ]
    return any(marker in error_text for marker in ignorable_markers)


async def delete_bin_channel_messages(message_ids: list[int], chat_id=None) -> dict:
    """删除目标存储频道（用户专属频道或 BIN_CHANNEL）中的消息，支持多 bot 回退。"""
    normalized_ids = [int(message_id) for message_id in dict.fromkeys(message_ids) if message_id]
    if not normalized_ids:
        return {
            "deleted_message_count": 0,
            "cleanup_only": False,
            "client_index": None,
        }

    target_chat = chat_id or Var.BIN_CHANNEL
    if not target_chat:
        raise RuntimeError("目标存储频道未配置，无法删除频道消息")

    clients = get_channel_deletion_clients()
    if not clients:
        raise RuntimeError("没有可用的 bot 客户端用于删除频道消息")

    last_error = None

    for index, client in clients:
        deleted_message_count = 0
        cleanup_only = False
        try:
            for offset in range(0, len(normalized_ids), 100):
                chunk = normalized_ids[offset:offset + 100]
                try:
                    result = await client.delete_messages(
                        chat_id=target_chat,
                        message_ids=chunk,
                    )
                    if isinstance(result, int):
                        deleted_message_count += result
                    elif isinstance(result, list):
                        deleted_message_count += len(result)
                    else:
                        deleted_message_count += len(chunk)
                except Exception as chunk_error:
                    if is_ignorable_delete_message_error(chunk_error):
                        cleanup_only = True
                        logger.info(
                            f"频道消息已不存在，继续清理数据库记录: {chunk} (bot {index})"
                        )
                        continue
                    raise

            return {
                "deleted_message_count": deleted_message_count,
                "cleanup_only": cleanup_only,
                "client_index": index,
            }
        except Exception as error:
            last_error = error
            logger.warning(f"bot {index} 删除频道消息失败: {error}")

    if last_error and is_ignorable_delete_message_error(last_error):
        return {
            "deleted_message_count": 0,
            "cleanup_only": True,
            "client_index": None,
        }

    raise RuntimeError(f"删除频道消息失败: {last_error}" if last_error else "删除频道消息失败")

async def media_streamer(request: web.Request, message_id: int, secure_hash: str):
    range_header = request.headers.get("Range", 0)

    # Reject invalid capabilities before making a Telegram API request. The
    # database is the authority for public streamable channel messages.
    try:
        source_record = get_tg_media_record_by_message_id(message_id, secure_hash=secure_hash, hash_len=Var.HASH_LENGTH)
    except TypeError:
        source_record = get_tg_media_record_by_message_id(message_id)
    source_unique_id = (source_record or {}).get("file_unique_id", "")
    record_chat_id = (source_record or {}).get("chat_id") or Var.BIN_CHANNEL
    if not source_unique_id or str(source_unique_id).startswith("telethon:"):
        raise FIleNotFound
    raw_unique_id = source_unique_id.split("@")[0]
    expected_hash = utils.get_hash(source_unique_id, Var.HASH_LENGTH)
    raw_expected_hash = utils.get_hash(raw_unique_id, Var.HASH_LENGTH)
    if not (secrets.compare_digest(str(secure_hash or ""), expected_hash) or secrets.compare_digest(str(secure_hash or ""), raw_expected_hash)):
        raise InvalidHash

    # 边缘推流分流调度：若未携带 direct=1，尝试将请求 302 重定向至租户专属或共享边缘节点
    if request.query.get("direct") != "1":
        try:
            from edge_node_manager import resolve_edge_redirect_url
            edge_redirect_url = resolve_edge_redirect_url(
                request=request,
                message_id=message_id,
                secure_hash=secure_hash,
                source_record=source_record,
                record_chat_id=record_chat_id,
            )
            if edge_redirect_url:
                logger.info(f"302 分流至边缘节点: msg_id={message_id}, url={edge_redirect_url}")
                raise web.HTTPFound(edge_redirect_url)
        except web.HTTPFound:
            raise
        except Exception as e:
            logger.warning(f"边缘分流调度异常，自动回源主控: {e}")

    # 检查是否有可用的客户端
    if not work_loads:
        logger.error("没有可用的客户端")
        raise web.HTTPInternalServerError(text="No available clients")

    try:
        try:
            source_file_id = await get_main_bot_file_properties(message_id, chat_id=record_chat_id)
        except TypeError:
            source_file_id = await get_main_bot_file_properties(message_id)
    except FIleNotFound:
        raise
    except Exception as error:
        mark_bot_failure(0, error)
        logger.warning(f"主客户端获取文件属性失败: {error}")
        raise

    if source_file_id.unique_id != raw_unique_id:
        logger.warning("Telegram media identity changed for message ID %s", message_id)
        raise InvalidHash

    target_dc = getattr(source_file_id, "dc_id", None)
    attempted_indices = set()
    tg_connect = None
    index = None
    file_id = None
    slot_preacquired = False

    while True:
        index = select_stream_bot(prefer_channel=True, exclude_indices=attempted_indices, target_dc=target_dc)
        if index is None:
            logger.error("没有有效的客户端")
            raise web.HTTPInternalServerError(text="No valid clients available")

        # 验证索引有效性
        if index not in multi_clients:
            attempted_indices.add(index)
            logger.error(f"选择的客户端索引 {index} 不存在于 multi_clients 中")
            continue

        acquire_bot_slot(index)
        slot_preacquired = True
        faster_client = multi_clients[index]

        if Var.MULTI_CLIENT:
            logger.info(f"Client {index} is now serving {request.remote}")

        if faster_client in class_cache:
            logger.debug(f"Using cached ByteStreamer object for client {index}")
        else:
            logger.debug(f"Creating new ByteStreamer object for client {index}")
        tg_connect = get_byte_streamer(faster_client)

        try:
            file_id = await tg_connect.get_file_properties(message_id, chat_id=record_chat_id, force_refresh=False)
            await tg_connect.generate_media_session(faster_client, file_id)
            mark_bot_success(index)
            break
        except FIleNotFound:
            if slot_preacquired:
                release_bot_slot(index)
                slot_preacquired = False
            attempted_indices.add(index)
            mark_bot_failure(index, "File not found in current bot context")
            logger.warning(f"客户端 {index} 无法读取频道消息，尝试切换")
        except Exception as error:
            if slot_preacquired:
                release_bot_slot(index)
                slot_preacquired = False
            attempted_indices.add(index)
            mark_bot_failure(index, error)
            logger.warning(f"客户端 {index} 准备媒体会话失败，尝试切换: {error}")
            if len(attempted_indices) >= max(1, len(multi_clients)):
                raise

    file_size = file_id.file_size
    mime_type = file_id.mime_type
    file_name = get_download_file_name({
        "file_name": getattr(file_id, "file_name", ""),
        "mime_type": mime_type,
        "message_id": message_id,
        "media_type": getattr(getattr(file_id, "file_type", None), "name", ""),
    })
    disposition = "attachment"

    if not mime_type:
        mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

    force_download = request.query.get("download", "").lower() in {"1", "true", "yes"}

    if not force_download and (
        "video/" in mime_type or "audio/" in mime_type or "image/" in mime_type or "/html" in mime_type
    ):
        disposition = "inline"

    def range_not_satisfiable_response():
        if slot_preacquired and index is not None:
            release_bot_slot(index)
        return web.Response(
            status=416,
            body=b"" if request.method == "HEAD" else b"416: Range not satisfiable",
            headers={
                "Content-Range": f"bytes */{file_size}",
                "Content-Length": "0",
                "Content-Disposition": build_content_disposition(disposition, file_name),
                "Accept-Ranges": "bytes",
            },
        )

    if range_header:
        try:
            unit, byte_range = str(range_header).strip().split("=", 1)
            if unit.lower() != "bytes" or "," in byte_range:
                raise ValueError("unsupported range")
            from_part, until_part = byte_range.split("-", 1)
            if from_part:
                from_bytes = int(from_part)
                until_bytes = int(until_part) if until_part else file_size - 1
            else:
                suffix_length = int(until_part)
                if suffix_length <= 0:
                    raise ValueError("invalid suffix range")
                from_bytes = max(file_size - suffix_length, 0)
                until_bytes = file_size - 1
        except (TypeError, ValueError):
            return range_not_satisfiable_response()
    else:
        from_bytes = 0
        until_bytes = file_size - 1

    if (until_bytes >= file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return range_not_satisfiable_response()

    chunk_size = 1024 * 1024
    req_length = until_bytes - from_bytes + 1
    response_headers = {
        "Content-Type": f"{mime_type}",
        "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
        "Content-Length": str(req_length),
        "Content-Disposition": build_content_disposition(disposition, file_name),
        "Accept-Ranges": "bytes",
        "X-MistRelay-Min-Threads": str(max(2, get_available_channel_bot_count())),
    }
    status = 206 if range_header else 200

    if request.method == "HEAD":
        if slot_preacquired and index is not None:
            release_bot_slot(index)
        return web.Response(status=status, headers=response_headers)

    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = until_bytes % chunk_size + 1
    part_count = math.ceil((until_bytes + 1 - offset) / chunk_size)
    body = tg_connect.yield_file(
        file_id,
        index,
        offset,
        first_part_cut,
        last_part_cut,
        part_count,
        chunk_size,
        slot_preacquired=slot_preacquired,
        message_id=message_id,
        chat_id=record_chat_id,
    )

    return web.Response(
        status=status,
        body=body,
        headers=response_headers,
    )

# ==================== Telegram 频道浏览 API ====================

@routes.get("/api/telegram/browse", allow_head=True)
async def telegram_browse_handler(request: web.Request):
    """浏览 Telegram 频道中已入库的媒体文件（分页、搜索、筛选）"""
    try:
        page = int(request.query.get('page', '1'))
        page_size = int(request.query.get('page_size', '50'))
        search = request.query.get('search', '').strip() or None
        mime_filter = request.query.get('type', '').strip() or None
        sort_by = request.query.get('sort_by', 'message_date')
        sort_desc = request.query.get('sort_desc', 'true').lower() != 'false'
        media_group_id = request.query.get('media_group_id', '').strip() or None

        page_size = min(page_size, 200)

        req_chat_id = get_request_bin_channel(request)
        user_payload = request.get("user") if hasattr(request, "get") else None
        is_non_admin_tenant = bool(user_payload and user_payload.get("role") not in (None, "admin"))

        tenant_cids = []
        if is_non_admin_tenant and user_payload:
            uid = user_payload.get("uid")
            import db
            tenant_cids = db.get_user_all_channel_ids(uid)
            if not tenant_cids and req_chat_id:
                tenant_cids = [req_chat_id]

        if is_non_admin_tenant and not tenant_cids:
            return web.json_response({
                "success": True,
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
            })
        is_admin, filter_chat_id = resolve_filter_chat_id(request, user_payload, req_chat_id)

        chat_ids_param = tenant_cids if (is_non_admin_tenant and tenant_cids) else None
        chat_id_param = None if chat_ids_param else filter_chat_id

        result = browse_tg_media(
            page=page,
            page_size=page_size,
            search=search,
            mime_filter=mime_filter,
            sort_by=sort_by,
            sort_desc=sort_desc,
            media_group_id=media_group_id,
            chat_id=chat_id_param,
            chat_ids=chat_ids_param,
        )

        hash_len = Var.HASH_LENGTH
        for item in result['items']:
            thumbnail_url = build_telegram_thumbnail_url(item)
            if thumbnail_url:
                item['thumbnail_url'] = thumbnail_url

            if item.get('entry_type') == 'file':
                item['download_file_name'] = get_download_file_name(item)
                uid = item.get('file_unique_id', '')
                mid = item.get('message_id')
                stream_url = build_telegram_stream_url(item, hash_len)
                if stream_url:
                    item['hash'] = utils.get_hash(uid, hash_len)
                    item['stream_url'] = stream_url
            elif item.get('entry_type') == 'folder':
                uid = item.get('file_unique_id', '')
                mid = item.get('message_id')
                if uid and mid:
                    rep_name = item.get('representative_file_name') or item.get('file_name')
                    rep_mime = item.get('representative_mime_type')
                    rep_item = {
                        'file_unique_id': uid,
                        'message_id': mid,
                        'file_name': rep_name,
                        'mime_type': rep_mime,
                    }
                    stream_url = build_telegram_stream_url(rep_item, hash_len)
                    if stream_url:
                        item['hash'] = utils.get_hash(uid, hash_len)
                        item['stream_url'] = stream_url
            fid = item.get('file_id')
            if fid and FileId is not None:
                try:
                    dec = FileId.decode(fid)
                    item['dc_id'] = dec.dc_id
                    item['dc_label'] = f"DC{dec.dc_id}"
                except Exception:
                    item['dc_id'] = None
                    item['dc_label'] = None
            else:
                item['dc_id'] = None
                item['dc_label'] = None
            item.pop('file_id', None)

        return web.json_response({"success": True, **result})
    except Exception as e:
        logger.error(f"Telegram browse API error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/telegram/usage", allow_head=True)
async def telegram_usage_handler(request: web.Request):
    """获取 Telegram 频道存储统计（支持多频道联合统计）"""
    try:
        req_chat_id = get_request_bin_channel(request)
        user_payload = request.get("user") if hasattr(request, "get") else None
        is_non_admin_tenant = bool(user_payload and user_payload.get("role") not in (None, "admin"))

        tenant_cids = []
        if is_non_admin_tenant and user_payload:
            uid = user_payload.get("uid")
            import db
            tenant_cids = db.get_user_all_channel_ids(uid)
            if not tenant_cids and req_chat_id:
                tenant_cids = [req_chat_id]

        if is_non_admin_tenant and not tenant_cids:
            return web.json_response({
                "success": True,
                "data": {
                    "total_count": 0,
                    "total_size": 0,
                    "videos": 0,
                    "images": 0,
                    "audios": 0,
                    "documents": 0,
                },
            })
        is_admin, filter_chat_id = resolve_filter_chat_id(request, user_payload, req_chat_id)
        if is_non_admin_tenant and tenant_cids:
            stats = get_tg_media_stats(chat_ids=tenant_cids)
        else:
            stats = get_tg_media_stats(chat_id=filter_chat_id)
        return web.json_response({"success": True, "data": stats})
    except Exception as e:
        logger.error(f"Telegram usage API error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def ensure_telegram_thumbnail(message_id: int, record: dict | None = None, chat_id: int | None = None) -> tuple[Path | None, bool]:
    """
    统一确保 Telegram 媒体 WebP 缩略图已生成并存在。
    返回 (缩略图路径, 是否命中缓存)。
    若记录不存在则返回 (None, False)。
    若格式不支持或生成失败，返回对应类型的兜底 fallback 图路径。
    """
    if record is None:
        try:
            if chat_id is not None:
                record = get_tg_media_record_by_message_id(message_id, chat_id=chat_id)
            else:
                record = get_tg_media_record_by_message_id(message_id)
        except TypeError:
            record = get_tg_media_record_by_message_id(message_id)
    if not record:
        return None, False

    mime_type = record.get("mime_type") or ""
    if not mime_type:
        media_type = get_file_id_media_type(record.get("file_id"))
        if media_type in ("photo", "sticker"):
            mime_type = "image/jpeg"
        elif media_type in ("video", "animation", "video_note"):
            mime_type = "video/mp4"
        else:
            name = (record.get("file_name") or "").lower()
            if any(name.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")):
                mime_type = "image/jpeg"
            elif any(name.endswith(ext) for ext in (".mp4", ".mkv", ".webm", ".mov", ".avi")):
                mime_type = "video/mp4"

    if not is_thumbnail_supported_mime(mime_type):
        return get_thumbnail_fallback_path("unsupported"), False

    from thumbnail_generator import get_thumbnail_generator

    generator = get_thumbnail_generator()
    file_name = get_download_file_name(record)
    rec_chat_id = record.get("chat_id") or chat_id
    default_bin = getattr(Var, "BIN_CHANNEL", None)
    if rec_chat_id is not None and str(rec_chat_id) != str(default_bin):
        cache_key = f"{rec_chat_id}_{message_id}_{file_name}"
    else:
        cache_key = f"{message_id}_{file_name}"

    cached = generator.get_cached_thumbnail("telegram", cache_key)
    if cached:
        return cached, True

    async with thumbnail_semaphore:
        cached = generator.get_cached_thumbnail("telegram", cache_key)
        if cached:
            return cached, True

        temp_dir = None
        try:
            file_size = int(record.get("file_size") or 0)
            if file_size <= 0:
                raise RuntimeError("媒体文件大小未知")

            if mime_type.lower().startswith("image/"):
                max_bytes = min(file_size, 50 * 1024 * 1024)
            else:
                max_bytes = min(file_size, 12 * 1024 * 1024)

            temp_dir = tempfile.TemporaryDirectory(prefix="mistrelay_tg_thumb_", dir="/tmp")
            source_path = Path(temp_dir.name) / file_name

            stream_url = None
            if mime_type.lower().startswith("video/"):
                try:
                    fuid = record.get("file_unique_id", "")
                    if fuid and not str(fuid).startswith("telethon:"):
                        file_hash = utils.get_hash(fuid, Var.HASH_LENGTH)
                        safe_name = quote(file_name, safe="")
                        port_val = getattr(Var, "PORT", 8080) or 8080
                        stream_url = f"http://127.0.0.1:{port_val}/{message_id}/{safe_name}?hash={file_hash}&direct=1"
                except Exception:
                    pass

            try:
                if rec_chat_id is not None and str(rec_chat_id) != str(default_bin):
                    await asyncio.wait_for(
                        download_telegram_media_sample(message_id, source_path, max_bytes, chat_id=rec_chat_id),
                        timeout=35,
                    )
                else:
                    await asyncio.wait_for(
                        download_telegram_media_sample(message_id, source_path, max_bytes),
                        timeout=35,
                    )
            except TypeError:
                await asyncio.wait_for(
                    download_telegram_media_sample(message_id, source_path, max_bytes),
                    timeout=35,
                )
            except Exception as dl_err:
                if not stream_url:
                    raise dl_err
                logger.debug(f"样本流播下载受阻，准备尝试 HTTP Range: {dl_err}")

            try:
                thumbnail_path = await asyncio.to_thread(
                    generator.generate_thumbnail,
                    "telegram",
                    cache_key,
                    source_path,
                    stream_url,
                )
            except TypeError:
                thumbnail_path = await asyncio.to_thread(
                    generator.generate_thumbnail,
                    "telegram",
                    cache_key,
                    source_path,
                )
            if thumbnail_path:
                return thumbnail_path, False
        except Exception as error:
            logger.warning(f"生成 TG 缩略图失败 message_id={message_id}: {error}")
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()

    kind = "video" if mime_type.lower().startswith("video/") else "image"
    return get_thumbnail_fallback_path(kind), False


@routes.get("/api/telegram/thumbnail/{message_id}", allow_head=True)
async def telegram_thumbnail_handler(request: web.Request):
    """按需生成或获取 TG 媒体 WebP 缩略图（支持多租户按 chat_id 隔离）。"""
    try:
        message_id = int(request.match_info["message_id"])
    except (KeyError, ValueError):
        return web.json_response({"success": False, "error": "无效的 message_id"}, status=400)

    user_payload = request.get("user") if hasattr(request, "get") else None
    is_non_admin_tenant = bool(user_payload and user_payload.get("role") not in (None, "admin"))
    query_obj = getattr(request, "query", None) or {}
    raw_chat_id = query_obj.get("chat_id", "").strip() if hasattr(query_obj, "get") else ""

    target_chat_id = None
    if is_non_admin_tenant:
        req_chat_id = get_request_bin_channel(request)
        if not req_chat_id:
            return web.json_response({"success": False, "error": "Telegram 文件记录不存在"}, status=404)
        if raw_chat_id:
            try:
                if int(raw_chat_id) != int(req_chat_id):
                    return web.json_response({"success": False, "error": "权限不足，无法访问其他频道缩略图"}, status=403)
            except ValueError:
                return web.json_response({"success": False, "error": "无效的 chat_id"}, status=400)
        target_chat_id = req_chat_id
    elif raw_chat_id:
        try:
            target_chat_id = int(raw_chat_id)
        except ValueError:
            return web.json_response({"success": False, "error": "无效的 chat_id"}, status=400)
        ticket_str = query_obj.get("ticket", "").strip() if hasattr(query_obj, "get") else ""
        if ticket_str and not user_payload:
            from auth import verify_resource_ticket
            path = f"/api/telegram/thumbnail/{message_id}"
            if not (verify_resource_ticket(ticket_str, f"{path}?chat_id={target_chat_id}") or verify_resource_ticket(ticket_str, path)):
                return web.json_response({"success": False, "error": "缩略图访问票据无效或与频道不匹配"}, status=403)

    if target_chat_id is not None:
        try:
            record = get_tg_media_record_by_message_id(message_id, chat_id=target_chat_id)
        except TypeError:
            record = get_tg_media_record_by_message_id(message_id)
        if not record or (record.get("chat_id") is not None and int(record.get("chat_id")) != int(target_chat_id)):
            return web.json_response({"success": False, "error": "Telegram 文件记录不存在"}, status=404)
        thumb_path, cache_hit = await ensure_telegram_thumbnail(message_id, record=record, chat_id=target_chat_id)
    else:
        thumb_path, cache_hit = await ensure_telegram_thumbnail(message_id)

    if thumb_path is None:
        return web.json_response({"success": False, "error": "Telegram 文件记录不存在"}, status=404)

    return get_thumbnail_response(thumb_path, cache_hit=cache_hit)


@routes.get("/api/telegram/thumbnails/status", allow_head=True)
async def telegram_thumbnails_status_handler(request: web.Request):
    """获取 Telegram 缩略图后台预热与缓存进度状态（支持租户隔离统计）"""
    try:
        req_chat_id = get_request_bin_channel(request) if hasattr(request, "get") else None
        user_payload = request.get("user") if hasattr(request, "get") else None
        is_non_admin_tenant = bool(user_payload and user_payload.get("role") not in (None, "admin"))

        from thumbnail_worker import get_thumbnail_worker
        worker = get_thumbnail_worker()
        if is_non_admin_tenant:
            if not req_chat_id:
                return web.json_response({
                    "success": True,
                    "data": {
                        "running": False,
                        "total": 0,
                        "cached": 0,
                        "pending": 0,
                        "percent": 100.0,
                        "current_message_id": None,
                    }
                })
            status = worker.get_status(chat_id=req_chat_id)
            status["current_message_id"] = None
        else:
            status = worker.get_status()
        return web.json_response({"success": True, "data": status})
    except Exception as e:
        logger.error(f"获取缩略图状态失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/thumbnails/warmup")
async def telegram_thumbnails_warmup_handler(request: web.Request):
    """手动触发或恢复后台缩略图全量预热扫描（管理员权限）"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足"}, status=403)

        from thumbnail_worker import get_thumbnail_worker
        worker = get_thumbnail_worker()
        scan_res = await worker.start_full_scan(force=False)
        return web.json_response({
            "success": True,
            "message": "已触发后台缩略图预热扫描",
            "data": {
                **scan_res,
                **worker.get_status(),
            },
        })
    except Exception as e:
        logger.error(f"触发缩略图预热失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.delete("/api/telegram/item/{message_id}")
async def telegram_delete_item_handler(request: web.Request):
    """删除单个 tg 网盘文件对应的频道消息和数据库记录。"""
    try:
        message_id = int(request.match_info["message_id"])
        req_chat_id = get_request_bin_channel(request)
        user_payload = request.get("user") if hasattr(request, "get") else None
        is_non_admin_tenant = bool(user_payload and user_payload.get("role") not in (None, "admin"))
        if is_non_admin_tenant and not req_chat_id:
            return web.json_response({"success": False, "error": "当前账号尚未绑定专属存储频道"}, status=403)
        is_admin, filter_chat_id = resolve_filter_chat_id(request, user_payload, req_chat_id)

        record = get_tg_media_record_by_message_id(message_id, chat_id=filter_chat_id) if filter_chat_id is not None else get_tg_media_record_by_message_id(message_id)
        if not record:
            return web.json_response({"success": False, "error": "Telegram 文件记录不存在"}, status=404)

        target_del_chat = record.get("chat_id") or req_chat_id
        deletion = await (delete_bin_channel_messages([message_id], chat_id=target_del_chat) if target_del_chat is not None else delete_bin_channel_messages([message_id]))
        cleanup = delete_tg_media_records([record["file_unique_id"]], chat_id=filter_chat_id) if filter_chat_id is not None else delete_tg_media_records([record["file_unique_id"]])

        action_message = "频道消息已删除并清理记录"
        if deletion["cleanup_only"]:
            action_message = "频道消息不存在，已清理数据库记录"

        return web.json_response({
            "success": True,
            "message": action_message,
            "data": {
                **cleanup,
                **deletion,
                "message_id": message_id,
            },
        })
    except ValueError:
        return web.json_response({"success": False, "error": "无效的 message_id"}, status=400)
    except Exception as e:
        logger.error(f"Telegram delete item API error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.delete("/api/telegram/group/{media_group_id}")
async def telegram_delete_group_handler(request: web.Request):
    """删除整个 Telegram 媒体组对应的频道消息和数据库记录。"""
    try:
        media_group_id = request.match_info["media_group_id"].strip()
        if not media_group_id:
            return web.json_response({"success": False, "error": "media_group_id 不能为空"}, status=400)

        req_chat_id = get_request_bin_channel(request)
        user_payload = request.get("user") if hasattr(request, "get") else None
        is_non_admin_tenant = bool(user_payload and user_payload.get("role") not in (None, "admin"))
        if is_non_admin_tenant and not req_chat_id:
            return web.json_response({"success": False, "error": "当前账号尚未绑定专属存储频道"}, status=403)
        is_admin, filter_chat_id = resolve_filter_chat_id(request, user_payload, req_chat_id)

        records = get_tg_media_records_by_media_group(media_group_id, chat_id=filter_chat_id) if filter_chat_id is not None else get_tg_media_records_by_media_group(media_group_id)
        if not records:
            return web.json_response({"success": False, "error": "Telegram 媒体组不存在"}, status=404)

        message_ids = [record["message_id"] for record in records]
        file_unique_ids = [record["file_unique_id"] for record in records]

        target_del_chat = records[0].get("chat_id") or req_chat_id
        deletion = await (delete_bin_channel_messages(message_ids, chat_id=target_del_chat) if target_del_chat is not None else delete_bin_channel_messages(message_ids))
        cleanup = delete_tg_media_records(file_unique_ids, chat_id=filter_chat_id) if filter_chat_id is not None else delete_tg_media_records(file_unique_ids)

        action_message = "媒体组已删除并清理记录"
        if deletion["cleanup_only"]:
            action_message = "频道媒体组消息不存在，已清理数据库记录"

        return web.json_response({
            "success": True,
            "message": action_message,
            "data": {
                **cleanup,
                **deletion,
                "media_group_id": media_group_id,
                "message_count": len(message_ids),
            },
        })
    except Exception as e:
        logger.error(f"Telegram delete group API error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/batch/delete")
async def telegram_batch_delete_handler(request: web.Request):
    """Delete selected files and media groups in one bounded operation."""
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            return web.json_response({"success": False, "error": "请求数据格式错误"}, status=400)

        raw_message_ids = payload.get("message_ids", [])
        raw_group_ids = payload.get("media_group_ids", [])
        if not isinstance(raw_message_ids, list) or not isinstance(raw_group_ids, list):
            return web.json_response({
                "success": False,
                "error": "message_ids 和 media_group_ids 必须使用列表格式",
            }, status=400)
        if len(raw_message_ids) + len(raw_group_ids) > 200:
            return web.json_response({
                "success": False,
                "error": "单次最多删除 200 个所选项目",
            }, status=400)

        message_ids = []
        for value in raw_message_ids:
            if isinstance(value, bool):
                raise ValueError("message_id 格式错误")
            message_id = int(value)
            if message_id <= 0:
                raise ValueError("message_id 格式错误")
            message_ids.append(message_id)
        message_ids = list(dict.fromkeys(message_ids))

        group_ids = []
        for value in raw_group_ids:
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
                raise ValueError("media_group_id 格式错误")
            group_ids.append(value.strip())
        group_ids = list(dict.fromkeys(group_ids))

        if not message_ids and not group_ids:
            return web.json_response({"success": False, "error": "请至少选择一个项目"}, status=400)

        req_chat_id = get_request_bin_channel(request)
        user_payload = request.get("user") if hasattr(request, "get") else None
        is_non_admin_tenant = bool(user_payload and user_payload.get("role") not in (None, "admin"))
        if is_non_admin_tenant and not req_chat_id:
            return web.json_response({"success": False, "error": "当前账号尚未绑定专属存储频道"}, status=403)
        is_admin, filter_chat_id = resolve_filter_chat_id(request, user_payload, req_chat_id)

        records_by_file_id = {}
        missing_message_ids = []
        missing_group_ids = []

        for message_id in message_ids:
            record = get_tg_media_record_by_message_id(message_id, chat_id=filter_chat_id) if filter_chat_id is not None else get_tg_media_record_by_message_id(message_id)
            if record:
                records_by_file_id[record["file_unique_id"]] = record
            else:
                missing_message_ids.append(message_id)

        for group_id in group_ids:
            records = get_tg_media_records_by_media_group(group_id, chat_id=filter_chat_id) if filter_chat_id is not None else get_tg_media_records_by_media_group(group_id)
            if not records:
                missing_group_ids.append(group_id)
                continue
            for record in records:
                records_by_file_id[record["file_unique_id"]] = record

        records = list(records_by_file_id.values())
        if not records:
            return web.json_response({
                "success": False,
                "error": "所选 Telegram 文件或媒体组不存在",
            }, status=404)

        target_del_chat = records[0].get("chat_id") or req_chat_id
        msg_id_list = [record["message_id"] for record in records]
        deletion = await (
            delete_bin_channel_messages(msg_id_list, chat_id=target_del_chat)
            if target_del_chat is not None
            else delete_bin_channel_messages(msg_id_list)
        )
        cleanup = (
            delete_tg_media_records(list(records_by_file_id), chat_id=filter_chat_id)
            if filter_chat_id is not None
            else delete_tg_media_records(list(records_by_file_id))
        )
        return web.json_response({
            "success": True,
            "message": f"已删除 {len(records)} 个频道文件",
            "data": {
                **cleanup,
                **deletion,
                "selected_item_count": len(message_ids) + len(group_ids),
                "matched_file_count": len(records),
                "missing_message_ids": missing_message_ids,
                "missing_media_group_ids": missing_group_ids,
            },
        })
    except (TypeError, ValueError) as error:
        return web.json_response({"success": False, "error": str(error)}, status=400)
    except Exception as error:
        logger.error("Telegram batch delete API error: %s", error, exc_info=True)
        return web.json_response({"success": False, "error": str(error)}, status=500)


@routes.delete("/api/telegram/all")
async def telegram_clear_all_handler(request: web.Request):
    """清空整个 tg 网盘：删除频道消息并清理 tg_media/downloads/uploads 记录。"""
    try:
        req_chat_id = get_request_bin_channel(request)
        user_payload = request.get("user") if hasattr(request, "get") else None
        is_non_admin_tenant = bool(user_payload and user_payload.get("role") not in (None, "admin"))
        if is_non_admin_tenant and not req_chat_id:
            return web.json_response({"success": False, "error": "当前账号尚未绑定专属存储频道"}, status=403)
        is_admin, filter_chat_id = resolve_filter_chat_id(request, user_payload, req_chat_id)

        records = list_all_tg_media_records(chat_id=filter_chat_id)
        if not records:
            return web.json_response({
                "success": True,
                "message": "tg 网盘已为空",
                "data": {
                    "deleted_media": 0,
                    "deleted_downloads": 0,
                    "deleted_uploads": 0,
                    "deleted_message_count": 0,
                    "cleanup_only": False,
                    "client_index": None,
                },
            })

        message_ids = [record["message_id"] for record in records]
        file_unique_ids = [record["file_unique_id"] for record in records]

        target_del_chat = records[0].get("chat_id") or req_chat_id
        deletion = await (delete_bin_channel_messages(message_ids, chat_id=target_del_chat) if target_del_chat is not None else delete_bin_channel_messages(message_ids))
        cleanup = delete_tg_media_records(file_unique_ids, chat_id=filter_chat_id) if filter_chat_id is not None else delete_tg_media_records(file_unique_ids)

        action_message = "tg 网盘已清空"
        if deletion["cleanup_only"]:
            action_message = "频道消息不存在，已清空 tg 网盘数据库记录"

        return web.json_response({
            "success": True,
            "message": action_message,
            "data": {
                **cleanup,
                **deletion,
                "message_count": len(message_ids),
            },
        })
    except Exception as e:
        logger.error(f"Telegram clear all API error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


# ==================== Telegram 用户文件分片上传 API ====================

@routes.post("/api/telegram/upload/init")
async def telegram_upload_init_handler(request: web.Request):
    """
    初始化用户本地文件分片上传会话
    Body JSON:
      - filename: str
      - file_size: int
      - chunk_size: int (可选, 默认 5MB)
      - mime_type: str (可选)
      - chat_id: int (可选, 仅管理员可指定)
    """
    try:
        user_payload = request.get("user") if hasattr(request, "get") else None
        if not user_payload:
            return web.json_response({"success": False, "error": "请先登录后再进行上传"}, status=401)

        user_id = user_payload.get("uid")
        role = user_payload.get("role")
        req_chat_id = get_request_bin_channel(request)

        is_admin = (role in (None, "admin"))
        try:
            body = await request.json()
        except Exception:
            body = {}

        if not is_admin:
            if not req_chat_id:
                return web.json_response({
                    "success": False,
                    "error": "当前账号尚未分配专属存储频道，请联系管理员分配后再进行上传"
                }, status=403)
            target_chat_id = req_chat_id
        else:
            custom_chat = body.get("chat_id")
            if custom_chat:
                try:
                    target_chat_id = int(custom_chat)
                except (ValueError, TypeError):
                    target_chat_id = req_chat_id
            else:
                target_chat_id = req_chat_id

        if not target_chat_id:
            return web.json_response({
                "success": False,
                "error": "系统尚未配置默认存储频道 (BIN_CHANNEL)，请在设置中配置"
            }, status=400)

        filename = body.get("filename")
        if not filename:
            return web.json_response({"success": False, "error": "缺少 filename 参数"}, status=400)

        file_size = int(body.get("file_size", 0))
        chunk_size = int(body.get("chunk_size", 5242880))
        mime_type = body.get("mime_type", "")

        from telegram_user_uploader import user_upload_manager
        res = user_upload_manager.init_upload(
            user_id=user_id,
            chat_id=target_chat_id,
            filename=filename,
            file_size=file_size,
            chunk_size=chunk_size,
            mime_type=mime_type
        )
        return web.json_response(res)
    except UnsafePathError as e:
        return web.json_response({"success": False, "error": f"不合法的文件名: {e}"}, status=400)
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"Telegram upload init error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/upload/chunk")
async def telegram_upload_chunk_handler(request: web.Request):
    """
    上传单个分片
    支持两种模式：
      1. multipart/form-data: upload_id, chunk_index, chunk (file field)
      2. application/octet-stream: headers X-Upload-ID, X-Chunk-Index, body bytes
    """
    try:
        user_payload = request.get("user") if hasattr(request, "get") else None
        if not user_payload:
            return web.json_response({"success": False, "error": "请先登录后再进行上传"}, status=401)
        user_id = user_payload.get("uid") if user_payload else None
        role = user_payload.get("role") if user_payload else None
        is_admin = (role in (None, "admin"))

        from telegram_user_uploader import user_upload_manager

        upload_id = request.headers.get("X-Upload-ID") or request.query.get("upload_id")
        chunk_index_raw = request.headers.get("X-Chunk-Index") or request.query.get("chunk_index")

        content_type = request.content_type.lower() if request.content_type else ""

        if "multipart/form-data" in content_type:
            reader = await request.multipart()
            chunk_bytes = None
            while True:
                field = await reader.next()
                if field is None:
                    break
                if field.name == "upload_id":
                    upload_id = (await field.read(decode=True)).decode("utf-8")
                elif field.name == "chunk_index":
                    chunk_index_raw = (await field.read(decode=True)).decode("utf-8")
                elif field.name in ("chunk", "file"):
                    chunk_bytes = await field.read(decode=False)

            if not upload_id or chunk_index_raw is None:
                return web.json_response({"success": False, "error": "缺少 upload_id 或 chunk_index 参数"}, status=400)
            if chunk_bytes is None:
                return web.json_response({"success": False, "error": "未包含分片数据 chunk"}, status=400)
            chunk_index = int(chunk_index_raw)
        else:
            if not upload_id or chunk_index_raw is None:
                return web.json_response({"success": False, "error": "缺少 X-Upload-ID 或 X-Chunk-Index 请求头/查询参数"}, status=400)
            chunk_index = int(chunk_index_raw)
            chunk_bytes = await request.read()

        res = user_upload_manager.save_chunk(
            upload_id=upload_id,
            user_id=user_id,
            chunk_index=chunk_index,
            chunk_data=chunk_bytes,
            is_admin=is_admin
        )
        return web.json_response(res)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except PermissionError as e:
        return web.json_response({"success": False, "error": str(e)}, status=403)
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"Telegram upload chunk error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/upload/finish")
async def telegram_upload_finish_handler(request: web.Request):
    """
    完成分片上传，触发合并与 Telegram 频道转存
    JSON: { "upload_id": "..." }
    """
    try:
        user_payload = request.get("user") if hasattr(request, "get") else None
        if not user_payload:
            return web.json_response({"success": False, "error": "请先登录后再进行上传"}, status=401)
        user_id = user_payload.get("uid") if user_payload else None
        role = user_payload.get("role") if user_payload else None
        is_admin = (role in (None, "admin"))

        data = await request.json()
        upload_id = data.get("upload_id")
        if not upload_id:
            return web.json_response({"success": False, "error": "缺少 upload_id 参数"}, status=400)

        from telegram_user_uploader import user_upload_manager
        res = await user_upload_manager.finish_upload(upload_id=upload_id, user_id=user_id, is_admin=is_admin)
        return web.json_response(res)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except PermissionError as e:
        return web.json_response({"success": False, "error": str(e)}, status=403)
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"Telegram upload finish error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/telegram/upload/status/{upload_id}")
async def telegram_upload_status_handler(request: web.Request):
    """查询上传任务的实时进度与云端入库状态"""
    try:
        user_payload = request.get("user") if hasattr(request, "get") else None
        if not user_payload:
            return web.json_response({"success": False, "error": "请先登录后再进行上传"}, status=401)
        user_id = user_payload.get("uid") if user_payload else None
        role = user_payload.get("role") if user_payload else None
        is_admin = (role in (None, "admin"))
        upload_id = request.match_info["upload_id"]

        from telegram_user_uploader import user_upload_manager
        res = user_upload_manager.get_status(upload_id=upload_id, user_id=user_id, is_admin=is_admin)
        return web.json_response(res)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except PermissionError as e:
        return web.json_response({"success": False, "error": str(e)}, status=403)
    except Exception as e:
        logger.error(f"Telegram upload status error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/upload/cancel")
async def telegram_upload_cancel_handler(request: web.Request):
    """取消上传任务并清理服务端暂存文件"""
    try:
        user_payload = request.get("user") if hasattr(request, "get") else None
        if not user_payload:
            return web.json_response({"success": False, "error": "请先登录后再进行上传"}, status=401)
        user_id = user_payload.get("uid") if user_payload else None
        role = user_payload.get("role") if user_payload else None
        is_admin = (role in (None, "admin"))

        data = await request.json()
        upload_id = data.get("upload_id")
        if not upload_id:
            return web.json_response({"success": False, "error": "缺少 upload_id 参数"}, status=400)

        from telegram_user_uploader import user_upload_manager
        res = await user_upload_manager.cancel_upload(upload_id=upload_id, user_id=user_id, is_admin=is_admin)
        return web.json_response(res)
    except PermissionError as e:
        return web.json_response({"success": False, "error": str(e)}, status=403)
    except Exception as e:
        logger.error(f"Telegram upload cancel error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/rclone/cache/monitor", allow_head=True)
async def monitor_cache_status(request: web.Request):
    return rclone_deprecated_response()


@routes.get("/api/files/list")
async def list_files_handler(request: web.Request):
    """
    API接口: 列出指定目录下的文件和文件夹（仅限管理员）
    参数: path (可选, 默认为根目录 /)
    """
    try:
        user = request.get("user") if hasattr(request, "get") else None
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)
        path_param = request.query.get("path", "/")
        target_path = resolve_under(FILE_API_ROOT, path_param)
        
        if not os.path.exists(target_path):
             return web.json_response({
                "success": False,
                "error": f"路径不存在: {path_param}"
            }, status=404)
            
        if not os.path.isdir(target_path):
            return web.json_response({
                "success": False,
                "error": f"路径不是目录: {path_param}"
            }, status=400)
            
        # 遍历目录
        files = []
        try:
            with os.scandir(target_path) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        entry_path = resolve_under(
                            FILE_API_ROOT,
                            Path(entry.path).relative_to(FILE_API_ROOT).as_posix(),
                        )
                        stat = entry.stat(follow_symlinks=False)
                        files.append({
                            "name": entry.name,
                            "path": f"/{entry_path.relative_to(FILE_API_ROOT).as_posix()}",
                            "is_dir": entry.is_dir(follow_symlinks=False),
                            "size": stat.st_size,
                            "modified_time": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                        })
                    except Exception as e:
                        logger.warning(f"无法获取文件信息 {entry.name}: {e}")
                        continue
        except PermissionError:
             return web.json_response({
                "success": False,
                "error": f"没有权限访问目录: {path_param}"
            }, status=403)
            
        # 排序: 文件夹在前, 然后按名称排序
        files.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        
        return web.json_response({
            "success": True,
            "path": path_param,
            "files": files
        })
        
    except Exception as e:
        if isinstance(e, UnsafePathError):
            return web.json_response({"success": False, "error": "路径不在允许的下载目录内"}, status=403)
        logger.error(f"列出文件失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/files/download")
async def download_file_handler(request: web.Request):
    """
    API接口: 下载文件（仅限管理员）
    参数: path
    """
    try:
        user = request.get("user") if hasattr(request, "get") else None
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)
        path_param = request.query.get("path")
        if not path_param:
            return web.json_response({"success": False, "error": "缺少 path 参数"}, status=400)
            
        target_path = resolve_under(FILE_API_ROOT, path_param, allow_root=False)
        
        if not os.path.exists(target_path):
            return web.json_response({"success": False, "error": "文件不存在"}, status=404)
        
        if os.path.isdir(target_path):
            return web.json_response({"success": False, "error": "无法直接下载文件夹"}, status=400)
            
        # 使用 FileResponse 发送文件
        return web.FileResponse(target_path)
        
    except Exception as e:
        if isinstance(e, UnsafePathError):
            return web.json_response({"success": False, "error": "路径不在允许的下载目录内"}, status=403)
        logger.error(f"下载文件失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.post("/api/files/upload")
async def upload_file_handler(request: web.Request):
    """
    API接口: 上传文件（仅限管理员）
    Form Data: 
      - path: 目标文件夹路径 (可选, 默认为 /)
      - file: 文件内容
    """
    try:
        user = request.get("user") if hasattr(request, "get") else None
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)
        reader = await request.multipart()
        
        # 读取字段
        target_dir = "/"
        file_field = None
        
        while True:
            field = await reader.next()
            if field is None:
                break
            
            if field.name == 'path':
                path_val = await field.read(decode=True)
                target_dir = path_val.decode('utf-8')
            elif field.name == 'file':
                file_field = field
                break # 找到文件就开始处理
        
        if not file_field:
            return web.json_response({"success": False, "error": "未找到文件字段"}, status=400)
            
        filename = validate_child_name(file_field.filename)
        save_dir = resolve_under(FILE_API_ROOT, target_dir)
        os.makedirs(save_dir, exist_ok=True)
        save_path = resolve_under(
            FILE_API_ROOT,
            (save_dir.relative_to(FILE_API_ROOT) / filename).as_posix(),
            allow_root=False,
        )

        size = 0
        with open(save_path, 'wb') as f:
            while True:
                chunk = await file_field.read_chunk()
                if not chunk:
                    break
                f.write(chunk)
                size += len(chunk)
                
        return web.json_response({
            "success": True,
            "message": "上传成功",
            "file": {
                "name": filename,
                "path": f"/{save_path.relative_to(FILE_API_ROOT).as_posix()}",
                "size": size
            }
        })

    except Exception as e:
        if isinstance(e, UnsafePathError):
            return web.json_response({"success": False, "error": "上传路径或文件名无效"}, status=403)
        logger.error(f"上传文件失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)

@routes.post("/api/files/mkdir")
async def mkdir_handler(request: web.Request):
    """
    API接口: 创建文件夹（仅限管理员）
    JSON: {"path": "/foo/bar"}
    """
    try:
        user = request.get("user") if hasattr(request, "get") else None
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)
        data = await request.json()
        path_param = data.get("path")
        
        if not path_param:
            return web.json_response({"success": False, "error": "缺少 path 参数"}, status=400)
            
        target_path = resolve_under(FILE_API_ROOT, path_param, allow_root=False)
        
        if os.path.exists(target_path):
             return web.json_response({"success": False, "error": "目录已存在"}, status=400)
             
        os.makedirs(target_path, exist_ok=True)
        
        return web.json_response({
            "success": True,
            "message": f"目录 {path_param} 创建成功"
        })
        
    except Exception as e:
        if isinstance(e, UnsafePathError):
            return web.json_response({"success": False, "error": "路径不在允许的下载目录内"}, status=403)
        logger.error(f"创建目录失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)

@routes.delete("/api/files/delete")
async def delete_file_handler(request: web.Request):
    """
    API接口: 删除文件或文件夹（仅限管理员）
    参数: path
    """
    try:
        user = request.get("user") if hasattr(request, "get") else None
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)
        path_param = request.query.get("path")
        if not path_param:
            return web.json_response({"success": False, "error": "缺少 path 参数"}, status=400)
            
        target_path = resolve_under(FILE_API_ROOT, path_param, allow_root=False)
        
        if not os.path.exists(target_path):
            return web.json_response({"success": False, "error": "文件或目录不存在"}, status=404)
        
        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
        else:
            os.remove(target_path)
            
        return web.json_response({
            "success": True,
            "message": f"已删除 {path_param}"
        })
        
    except Exception as e:
        if isinstance(e, UnsafePathError):
            return web.json_response({"success": False, "error": "路径不在允许的下载目录内"}, status=403)
        logger.error(f"删除失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


# ======================== 日志管理 API ========================

@routes.get("/api/logs", allow_head=True)
async def get_logs_handler(request: web.Request):
    """
    API接口: 获取日志内容
    参数:
        file: 日志文件名（可选，默认当前日志）
        tail: 返回最后 N 行（默认 200）
        level: 按级别过滤（如 ERROR, WARNING, INFO）
        keyword: 关键词搜索
    """
    try:
        from log_config import read_log_lines
        filename = request.query.get("file")
        tail = int(request.query.get("tail", 200))
        level_filter = request.query.get("level")
        keyword = request.query.get("keyword")

        lines = read_log_lines(
            filename=filename,
            tail=tail,
            level_filter=level_filter,
            keyword=keyword,
        )
        return web.json_response({
            "success": True,
            "total": len(lines),
            "lines": lines,
        })
    except Exception as e:
        logger.error(f"获取日志失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/logs/files", allow_head=True)
async def get_log_files_handler(request: web.Request):
    """API接口: 列出所有日志文件"""
    try:
        from log_config import get_log_files
        files = get_log_files()
        return web.json_response({"success": True, "files": files})
    except Exception as e:
        logger.error(f"获取日志文件列表失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/logs/download/{filename}")
async def download_log_file_handler(request: web.Request):
    """API接口: 下载指定日志文件"""
    try:
        from log_config import LOG_DIR
        filename = request.match_info["filename"]
        safe_name = os.path.basename(filename)
        path = os.path.join(LOG_DIR, safe_name)

        if not os.path.isfile(path):
            return web.json_response({"success": False, "error": "文件不存在"}, status=404)

        return web.FileResponse(
            path,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe_name, safe='')}"
            },
        )
    except Exception as e:
        logger.error(f"下载日志文件失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


# ==================== 缓存治理与管理 API ====================

@routes.get("/api/cache/stats", allow_head=True)
async def cache_stats_handler(request: web.Request):
    """获取系统存储总览与各类别缓存详细指标统计"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        import cache_manager
        client = get_aria2_client()
        stats = await cache_manager.get_all_cache_stats(aria2_client=client)
        return web.json_response({"success": True, "data": stats})
    except Exception as e:
        logger.error(f"获取缓存统计失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/cache/clean")
async def cache_clean_handler(request: web.Request):
    """执行分类或全量缓存清理/试运行动作"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        body = {}
        try:
            body = await request.json()
        except Exception:
            pass

        category = body.get("category", "all")
        retention_hours = body.get("retention_hours")
        if retention_hours is not None:
            retention_hours = int(retention_hours)
        retention_days = body.get("retention_days")
        if retention_days is not None:
            retention_days = int(retention_days)
        purge_all = bool(body.get("purge_all", False))
        dry_run = bool(body.get("dry_run", False))
        sub_source = body.get("sub_source")

        import cache_manager
        client = get_aria2_client()
        result = await cache_manager.clean_cache_category(
            category=category,
            aria2_client=client,
            retention_hours=retention_hours,
            retention_days=retention_days,
            purge_all=purge_all,
            dry_run=dry_run,
            sub_source=sub_source,
        )
        return web.json_response({"success": True, "data": result})
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"清理缓存失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/cache/policy", allow_head=True)
async def cache_policy_get_handler(request: web.Request):
    """获取当前自动清理策略与保留周期设置"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        import cache_manager
        policy = cache_manager.get_cache_policy()
        return web.json_response({"success": True, "data": policy})
    except Exception as e:
        logger.error(f"获取缓存策略失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.put("/api/cache/policy")
async def cache_policy_update_handler(request: web.Request):
    """更新自动清理策略配置并持久化生效"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        body = await request.json()
        if not isinstance(body, dict):
            return web.json_response({"success": False, "error": "请求参数格式错误"}, status=400)

        import cache_manager
        updated_policy = cache_manager.update_cache_policy(body)
        return web.json_response({"success": True, "data": updated_policy, "message": "缓存策略已更新"})
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"更新缓存策略失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


# ==================== Telegram 机器人动态热插拔与 BotFather 流水线 API ====================

@routes.post("/api/telegram/bots/hot-add")
async def telegram_bots_hot_add_handler(request: web.Request):
    """运行时动态添加并连接 Worker Bot Token"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        body = await request.json()
        if not isinstance(body, dict):
            return web.json_response({"success": False, "error": "请求参数格式错误"}, status=400)

        raw_tokens = body.get("tokens") or body.get("token") or []
        if isinstance(raw_tokens, str):
            token_list = [t.strip() for t in raw_tokens.replace(",", "\n").splitlines() if t.strip()]
        elif isinstance(raw_tokens, list):
            token_list = [str(t).strip() for t in raw_tokens if str(t).strip()]
        else:
            token_list = []

        if not token_list:
            return web.json_response({"success": False, "error": "请至少提供一个有效的 Bot Token"}, status=400)

        from WebStreamer.bot.clients import hot_add_bot_client
        added = []
        errors = []

        for token in token_list:
            try:
                res = await hot_add_bot_client(token, persist=True)
                added.append(res)
            except Exception as e:
                errors.append(f"{token[:15]}...: {e}")

        return web.json_response({
            "success": True,
            "data": {
                "added": added,
                "errors": errors,
                "total_added": len(added),
            }
        })
    except Exception as e:
        logger.error(f"热添加 Bot 失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.delete(r"/api/telegram/bots/{index:\d+}")
async def telegram_bots_hot_remove_handler(request: web.Request):
    """运行时动态下线并剔除指定的 Worker 客户端"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        index = int(request.match_info["index"])
        from WebStreamer.bot.clients import hot_remove_bot_client
        result = await hot_remove_bot_client(index, persist=True)
        return web.json_response({"success": True, "data": result})
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except Exception as e:
        logger.error(f"移除 Bot 失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/auto-create")
async def telegram_botfather_auto_create_handler(request: web.Request):
    """通过 API 协议号自动化与 @BotFather 对话创建/探测并挂载负载机器人"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        session_source = None
        count = 3
        name_prefix = "MistRelay Node"
        reuse_existing = True

        if request.content_type.startswith("multipart/"):
            reader = await request.multipart()
            while True:
                part = await reader.next()
                if part is None:
                    break
                if part.name == "session_file":
                    session_source = await part.read()
                elif part.name == "session_string":
                    text_val = (await part.read()).decode("utf-8").strip()
                    if text_val:
                        session_source = text_val
                elif part.name == "count":
                    raw_c = (await part.read()).decode("utf-8").strip()
                    if raw_c.isdigit():
                        count = int(raw_c)
                elif part.name == "name_prefix":
                    name_prefix = (await part.read()).decode("utf-8").strip() or "MistRelay Node"
                elif part.name == "reuse_existing":
                    raw_val = (await part.read()).decode("utf-8").strip().lower()
                    reuse_existing = raw_val in ("true", "1", "yes")
        else:
            body = await request.json()
            if not isinstance(body, dict):
                return web.json_response({"success": False, "error": "请求参数格式错误"}, status=400)
            session_source = body.get("session_string") or body.get("session")
            count = int(body.get("count", 3))
            name_prefix = body.get("name_prefix", "MistRelay Node")
            reuse_existing = bool(body.get("reuse_existing", True))

        if not session_source:
            return web.json_response({
                "success": False,
                "error": "请提供有效的 Telegram 协议号 Session String 文本或上传 .session 文件"
            }, status=400)

        from botfather_creator import run_botfather_pipeline
        result = await run_botfather_pipeline(
            session_source=session_source,
            count=count,
            name_prefix=name_prefix,
            reuse_existing=reuse_existing,
        )
        return web.json_response({"success": True, "data": result})
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except TimeoutError as e:
        return web.json_response({"success": False, "error": f"与 @BotFather 交互超时: {e}"}, status=504)
    except Exception as e:
        logger.error(f"@BotFather 流水线执行失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)



@routes.get("/api/telegram/botfather/accounts")
async def telegram_botfather_accounts_list_handler(request: web.Request):
    """获取协议号资产池列表（脱敏）"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        from botfather_creator import sync_cached_sessions_to_db
        accounts = sync_cached_sessions_to_db()
        return web.json_response({"success": True, "data": accounts}, headers=NO_CACHE_HEADERS)
    except Exception as e:
        logger.error(f"获取协议号资产池列表失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/accounts/import")
async def telegram_botfather_accounts_import_handler(request: web.Request):
    """批量导入协议号资产（支持多行 [手机号|接码链接]、多行 Session String 或多个 .session 文件）"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        lines = []
        files = []
        remark = None

        content_type = request.headers.get("Content-Type", "")
        if "multipart/form-data" in content_type:
            reader = await request.multipart()
            async for part in reader:
                if part.name in ("session_file", "session_files", "file", "files"):
                    fname = getattr(part, "filename", None) or "imported.session"
                    fbytes = await part.read()
                    if fbytes:
                        files.append((fname, fbytes))
                elif part.name in ("content", "lines", "session_string", "text"):
                    val = (await part.read()).decode("utf-8").strip()
                    if val:
                        lines.extend([ln.strip() for ln in val.splitlines() if ln.strip()])
                elif part.name == "remark":
                    remark = (await part.read()).decode("utf-8").strip() or None
        else:
            body = await request.json()
            if not isinstance(body, dict):
                return web.json_response({"success": False, "error": "请求参数格式错误"}, status=400)
            if body.get("lines"):
                if isinstance(body["lines"], list):
                    lines.extend([str(l).strip() for l in body["lines"] if str(l).strip()])
                else:
                    lines.extend([ln.strip() for ln in str(body["lines"]).splitlines() if ln.strip()])
            if body.get("content"):
                lines.extend([ln.strip() for ln in str(body["content"]).splitlines() if ln.strip()])
            if body.get("session_string"):
                lines.extend([ln.strip() for ln in str(body["session_string"]).splitlines() if ln.strip()])
            if body.get("remark"):
                remark = str(body["remark"]).strip()

        if not lines and not files:
            return web.json_response({
                "success": False,
                "error": "请提供要导入的协议号内容或上传 .session 文件"
            }, status=400)

        sync_mode = request.query.get("sync") in ("true", "1") or request.query.get("async") in ("false", "0")
        if not sync_mode and isinstance(locals().get("body"), dict):
            if body.get("sync") is True or body.get("async") is False:
                sync_mode = True

        if sync_mode:
            from botfather_creator import batch_import_protocol_accounts
            result = await batch_import_protocol_accounts(lines=lines, files=files, remark=remark)
            return web.json_response({"success": True, "data": result})

        from botfather_creator import create_import_task
        task_id = create_import_task(lines=lines, files=files, remark=remark)
        return web.json_response({
            "success": True,
            "data": {
                "async": True,
                "task_id": task_id,
                "status": "running",
                "message": "已在后台启动协议号导入与接码登录任务",
            }
        })
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"批量导入协议号失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/telegram/botfather/accounts/import-task/{task_id}")
async def telegram_botfather_accounts_import_task_handler(request: web.Request):
    """查询后台协议号导入任务的实时状态、进度与日志"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        task_id = request.match_info.get("task_id", "").strip()
        from botfather_creator import get_import_task_status
        status_info = get_import_task_status(task_id)
        if not status_info:
            return web.json_response({"success": False, "error": f"未找到导入任务 ID: {task_id}"}, status=404)

        return web.json_response({"success": True, "data": status_info})
    except Exception as e:
        logger.error(f"查询导入任务状态失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.delete("/api/telegram/botfather/accounts/{id}")
async def telegram_botfather_account_delete_handler(request: web.Request):
    """从资产池中安全删除指定协议号（不影响已挂载的机器人）"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        account_id_str = request.match_info.get("id", "")
        phone_param = request.query.get("phone", "")
        if not account_id_str and not phone_param:
            return web.json_response({"success": False, "error": "无效的协议号标识"}, status=400)

        from botfather_creator import remove_protocol_account
        deleted = remove_protocol_account(account_id_str, phone_hint=phone_param)
        return web.json_response({"success": True, "message": f"协议号已从资产池彻底移除"})
    except Exception as e:
        logger.error(f"删除协议号失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/accounts/{id}/check")
async def telegram_botfather_account_check_handler(request: web.Request):
    """检测指定协议号连接健康度并刷新持有的机器人数量"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        account_id_str = request.match_info.get("id", "")
        if not account_id_str.isdigit():
            return web.json_response({"success": False, "error": "无效的协议号 ID"}, status=400)

        from botfather_creator import check_protocol_account
        result = await check_protocol_account(int(account_id_str))
        return web.json_response({"success": True, "data": result})
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"检测协议号失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/telegram/botfather/accounts/{id}/detail")
async def telegram_botfather_account_detail_handler(request: web.Request):
    """获取指定协议号的详细底层参数、Telethon/Pyrogram Session String 及账号档案"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        account_id_str = request.match_info.get("id", "")
        if not account_id_str.isdigit():
            return web.json_response({"success": False, "error": "无效的协议号 ID"}, status=400)

        refresh_param = request.query.get("refresh", "0").lower()
        refresh_online = refresh_param in ("1", "true", "yes")

        from botfather_creator import get_protocol_account_detail
        result = await get_protocol_account_detail(int(account_id_str), refresh_online=refresh_online)
        return web.json_response({"success": True, "data": result}, headers=NO_CACHE_HEADERS)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"获取协议号详情失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/accounts/{id}/fetch-api")
async def telegram_botfather_account_fetch_api_handler(request: web.Request):
    """通过 my.telegram.org 自动在线提取或创建该协议号专属的 api_id 与 api_hash (基于归属地匹配家宽代理)"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        account_id_str = request.match_info.get("id", "")
        if not account_id_str.isdigit():
            return web.json_response({"success": False, "error": "无效的协议号 ID"}, status=400)

        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        proxy_api_url = (body.get("proxy_api_url") or "").strip() or None

        from botfather_creator import fetch_api_credentials_from_my_telegram
        result = await fetch_api_credentials_from_my_telegram(int(account_id_str), proxy_api_url=proxy_api_url)
        return web.json_response({"success": True, "data": result}, headers=NO_CACHE_HEADERS)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except (ValueError, RuntimeError, TimeoutError) as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"从 my.telegram.org 提取 API 凭证失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/accounts/fetch-api-batch")
async def telegram_botfather_account_fetch_api_batch_handler(request: web.Request):
    """批量按协议号归属地匹配家宽代理自动提取/创建 App api_id 与 api_hash"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}

        account_ids = body.get("account_ids")
        proxy_api_url = (body.get("proxy_api_url") or "").strip() or None
        only_missing = bool(body.get("only_missing", True))

        from botfather_creator import batch_fetch_api_credentials
        result = await batch_fetch_api_credentials(
            account_ids=account_ids,
            proxy_api_url=proxy_api_url,
            only_missing=only_missing,
        )
        return web.json_response({"success": True, "data": result}, headers=NO_CACHE_HEADERS)
    except Exception as e:
        logger.error(f"批量提取 API 凭证失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/telegram/botfather/proxy-config")
async def telegram_botfather_get_proxy_config_handler(request: web.Request):
    """获取 Telegram 开发者 API 提取所使用的家宽代理配置"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)
        from botfather_creator import get_api_proxy_config, DEFAULT_TELEGRAM_API_PROXY_URL
        return web.json_response({
            "success": True,
            "data": {
                "proxy_api_url": get_api_proxy_config(),
                "default_url": DEFAULT_TELEGRAM_API_PROXY_URL,
            }
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/proxy-config")
async def telegram_botfather_set_proxy_config_handler(request: web.Request):
    """保存 Telegram 开发者 API 提取所使用的家宽代理配置"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)
        body = await request.json()
        proxy_api_url = body.get("proxy_api_url", "")
        from botfather_creator import set_api_proxy_config
        saved = set_api_proxy_config(proxy_api_url)
        return web.json_response({"success": True, "data": {"proxy_api_url": saved}})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/accounts/{id}/credentials")
async def telegram_botfather_account_update_credentials_handler(request: web.Request):
    """手动更新指定协议号的 api_id、api_hash 与备注"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        account_id_str = request.match_info.get("id", "")
        if not account_id_str.isdigit():
            return web.json_response({"success": False, "error": "无效的协议号 ID"}, status=400)

        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}

        raw_api_id = body.get("api_id")
        api_id_val = None
        if raw_api_id is not None and str(raw_api_id).strip():
            if not str(raw_api_id).strip().isdigit():
                return web.json_response({"success": False, "error": "api_id 必须为纯数字"}, status=400)
            api_id_val = int(str(raw_api_id).strip())

        raw_api_hash = body.get("api_hash")
        api_hash_val = str(raw_api_hash).strip().lower() if raw_api_hash is not None else None
        if api_hash_val and not re.fullmatch(r"[a-fA-F0-9]{32}", api_hash_val):
            return web.json_response({"success": False, "error": "api_hash 必须为 32 位十六进制字符串"}, status=400)

        remark = body.get("remark")

        from botfather_creator import update_protocol_account_credentials
        result = await update_protocol_account_credentials(
            account_id=int(account_id_str),
            api_id=api_id_val,
            api_hash=api_hash_val,
            remark=str(remark).strip() if remark is not None else None,
        )
        return web.json_response({"success": True, "data": result}, headers=NO_CACHE_HEADERS)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"更新协议号凭证失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)



@routes.get("/api/telegram/botfather/accounts/{id}/login-code")
async def telegram_botfather_account_login_code_handler(request: web.Request):
    """实时读取指定协议号官方 777000 会话收到的最新登录验证码及安全上下文"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        account_id_str = request.match_info.get("id", "")
        if not account_id_str.isdigit():
            return web.json_response({"success": False, "error": "无效的协议号 ID"}, status=400)

        limit = 10
        try:
            limit = int(request.query.get("limit", "10"))
        except Exception:
            pass

        from botfather_creator import fetch_account_login_code
        result = await fetch_account_login_code(int(account_id_str), limit=limit)
        return web.json_response({"success": True, "data": result}, headers=NO_CACHE_HEADERS)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except Exception as e:
        logger.error(f"获取协议号登录验证码失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/telegram/botfather/accounts/{id}/2fa")
async def telegram_botfather_account_get_2fa_handler(request: web.Request):
    """查询指定协议号当前的官方 2FA 真实状态、密码提示与重置风险"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        account_id_str = request.match_info.get("id", "")
        if not account_id_str.isdigit():
            return web.json_response({"success": False, "error": "无效的协议号 ID"}, status=400)

        from botfather_creator import get_account_2fa_status
        result = await get_account_2fa_status(int(account_id_str))
        return web.json_response({"success": True, "data": result}, headers=NO_CACHE_HEADERS)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except Exception as e:
        logger.error(f"获取 2FA 状态失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/accounts/{id}/2fa")
async def telegram_botfather_account_update_2fa_handler(request: web.Request):
    """设置或修改指定协议号的 2FA 云密码"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        account_id_str = request.match_info.get("id", "")
        if not account_id_str.isdigit():
            return web.json_response({"success": False, "error": "无效的协议号 ID"}, status=400)

        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}

        new_password = (body.get("new_password") or "").strip() or "auto"
        current_password = (body.get("current_password") or "").strip() or None
        hint = (body.get("hint") or "").strip()

        from botfather_creator import update_account_2fa_password, get_protocol_account_detail
        result = await update_account_2fa_password(
            int(account_id_str),
            new_password=new_password,
            current_password=current_password,
            hint=hint,
        )
        detail = await get_protocol_account_detail(int(account_id_str))
        result["detail"] = detail
        return web.json_response({"success": True, "data": result}, headers=NO_CACHE_HEADERS)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"修改 2FA 密码失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/accounts/{id}/terminate-sessions")
async def telegram_botfather_account_terminate_sessions_handler(request: web.Request):
    """一键注销指定协议号除当前 MistRelay 之外的所有外部已登录会话"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        account_id_str = request.match_info.get("id", "")
        if not account_id_str.isdigit():
            return web.json_response({"success": False, "error": "无效的协议号 ID"}, status=400)

        from botfather_creator import terminate_account_other_sessions
        result = await terminate_account_other_sessions(int(account_id_str))
        return web.json_response({"success": True, "data": result}, headers=NO_CACHE_HEADERS)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except Exception as e:
        logger.error(f"踢除其他会话失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/accounts/{id}/cancel-reset")
async def telegram_botfather_account_cancel_reset_handler(request: web.Request):
    """撤销指定协议号正在进行的密码重置申请"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        account_id_str = request.match_info.get("id", "")
        if not account_id_str.isdigit():
            return web.json_response({"success": False, "error": "无效的协议号 ID"}, status=400)

        from botfather_creator import cancel_account_password_reset
        result = await cancel_account_password_reset(int(account_id_str))
        return web.json_response({"success": True, "data": result}, headers=NO_CACHE_HEADERS)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except Exception as e:
        logger.error(f"撤销重置密码失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/accounts/{id}/bind-local-otp")
async def telegram_botfather_account_bind_local_otp_handler(request: web.Request):
    """为指定协议号生成并绑定本地自主接码地址，替换号商 code_url"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        account_id_str = request.match_info.get("id", "")
        if not account_id_str.isdigit():
            return web.json_response({"success": False, "error": "无效的协议号 ID"}, status=400)

        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        replace_code_url = bool(body.get("replace_code_url", True))

        from botfather_creator import bind_local_otp_url, get_protocol_account_detail
        result = bind_local_otp_url(int(account_id_str), replace_code_url=replace_code_url)
        detail = await get_protocol_account_detail(int(account_id_str))
        result["detail"] = detail
        return web.json_response({"success": True, "data": result}, headers=NO_CACHE_HEADERS)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except Exception as e:
        logger.error(f"绑定自主接码地址失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/accounts/{id}/takeover")
async def telegram_botfather_account_takeover_handler(request: web.Request):
    """单号一键全自动安全接管（自动生成强 2FA 密码 + 换绑本机接码 + 踢除号商外部设备）"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        account_id_str = request.match_info.get("id", "")
        if not account_id_str.isdigit():
            return web.json_response({"success": False, "error": "无效的协议号 ID"}, status=400)

        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}

        new_password = (body.get("new_password") or "").strip() or None
        hint = (body.get("hint") or "MistRelay").strip()

        from botfather_creator import takeover_protocol_account
        result = await takeover_protocol_account(
            int(account_id_str),
            new_password=new_password,
            hint=hint,
        )
        return web.json_response({"success": True, "data": result}, headers=NO_CACHE_HEADERS)
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"单号安全接管失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/accounts/takeover-batch")
async def telegram_botfather_accounts_takeover_batch_handler(request: web.Request):
    """全池（或指定账号）批量自动生成强密码并一键安全接管"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}

        account_ids = body.get("account_ids")
        if account_ids is not None and not isinstance(account_ids, list):
            account_ids = None
        only_unsecured = body.get("only_unsecured", True)
        force_all = body.get("force_all", False)

        from botfather_creator import takeover_all_protocol_accounts
        result = await takeover_all_protocol_accounts(
            account_ids=account_ids,
            only_unsecured=only_unsecured,
            force_all=force_all,
        )
        return web.json_response({"success": True, "data": result}, headers=NO_CACHE_HEADERS)
    except Exception as e:
        logger.error(f"批量安全接管失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/telegram/botfather/otp/{token}")
async def telegram_botfather_otp_page_handler(request: web.Request):
    """
    自主安全接码端点：无需登录即可通过专属 Token 查看 777000 实时登录验证码与 2FA 密码。
    支持 JSON 输出与自适应响应式网页展示。
    """
    token = request.match_info.get("token", "").strip()
    if not token:
        return web.Response(text="无效的接码 Token", status=400)

    import db
    acc = db.get_protocol_account_by_otp_token(token)
    if not acc:
        return web.Response(text="接码链接不存在或已失效", status=404)

    is_json = request.query.get("format") == "json" or "application/json" in request.headers.get("Accept", "")

    try:
        from botfather_creator import fetch_account_login_code
        data = await fetch_account_login_code(acc["id"], limit=5)
    except Exception as e:
        logger.warning(f"自主接码获取 777000 失败: {e}")
        data = {
            "account_id": acc["id"],
            "phone": acc["phone"],
            "latest_code": None,
            "code_time": None,
            "relative_time": "读取失败",
            "age_seconds": None,
            "is_recent": False,
            "device": "未知",
            "ip": "未知",
            "location": "未知",
            "raw_text": str(e),
            "pass2fa": acc.get("two_fa_password") or "",
            "has_two_fa": bool(acc.get("has_two_fa") or acc.get("two_fa_password")),
            "messages": [],
        }

    if is_json:
        return web.json_response({"success": True, "data": data}, headers=NO_CACHE_HEADERS)

    two_fa_val = data.get("pass2fa") or ""
    two_fa_block = ""
    if two_fa_val:
        two_fa_block = f"""
    <div class="two-fa-box" onclick="copyText('{two_fa_val}', '2FA 密码')">
      <div>
        <div style="font-size: 11px; color: #a5b4fc;">2FA 二步验证密码 (已加锁):</div>
        <div style="font-family: ui-monospace, monospace; font-size: 14px; font-weight: 700; color: #e0e7ff;">{two_fa_val}</div>
      </div>
      <button class="btn" style="background: rgba(99, 102, 241, 0.4);" type="button">复制密码</button>
    </div>
"""

    badge_cls = "badge-recent" if data.get("is_recent") else "badge-wait"
    badge_txt = "🟢 最新有效" if data.get("is_recent") else ("🟡 等待发码" if not data.get("latest_code") else "⚠️ 可能已过期")
    code_val = data.get("latest_code") or "------"
    code_hint = "点击一键复制验证码" if data.get("latest_code") else "请在客户端触发发送验证码，系统将自动读取"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Telegram 自主接码工具 - {acc['phone']}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
      color: #f8fafc;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }}
    .card {{
      background: rgba(30, 41, 59, 0.7);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 16px;
      width: 100%;
      max-width: 480px;
      padding: 28px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
    }}
    .header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 20px;
      padding-bottom: 14px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }}
    .title {{ font-size: 18px; font-weight: 700; color: #38bdf8; display: flex; align-items: center; gap: 8px; }}
    .phone {{ font-family: ui-monospace, monospace; font-size: 15px; color: #94a3b8; }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 9999px;
      font-size: 12px;
      font-weight: 600;
    }}
    .badge-recent {{ background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }}
    .badge-wait {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }}
    .code-box {{
      background: rgba(15, 23, 42, 0.6);
      border: 2px dashed rgba(56, 189, 248, 0.4);
      border-radius: 12px;
      padding: 20px;
      text-align: center;
      margin-bottom: 18px;
      cursor: pointer;
      transition: all 0.2s ease;
    }}
    .code-box:hover {{
      border-color: #38bdf8;
      background: rgba(15, 23, 42, 0.85);
    }}
    .code-label {{ font-size: 13px; color: #94a3b8; margin-bottom: 6px; }}
    .code-val {{
      font-family: ui-monospace, monospace;
      font-size: 38px;
      font-weight: 800;
      letter-spacing: 6px;
      color: #38bdf8;
    }}
    .code-hint {{ font-size: 11px; color: #64748b; margin-top: 6px; }}
    .info-row {{
      display: flex;
      justify-content: space-between;
      font-size: 13px;
      padding: 8px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }}
    .info-label {{ color: #94a3b8; }}
    .info-val {{ font-weight: 500; color: #e2e8f0; font-family: ui-monospace, monospace; }}
    .two-fa-box {{
      margin-top: 16px;
      padding: 12px 16px;
      background: rgba(99, 102, 241, 0.1);
      border: 1px solid rgba(99, 102, 241, 0.25);
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
    }}
    .refresh-bar {{
      margin-top: 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 12px;
      color: #64748b;
    }}
    .btn {{
      background: #0284c7;
      color: white;
      border: none;
      padding: 6px 14px;
      border-radius: 6px;
      font-size: 12px;
      cursor: pointer;
      transition: background 0.2s;
    }}
    .btn:hover {{ background: #0369a1; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <div>
        <div class="title">⚡ Telegram 自主接码</div>
        <div class="phone">{acc['phone']}</div>
      </div>
      <span class="badge {badge_cls}">
        {badge_txt}
      </span>
    </div>

    <input type="hidden" id="code" value="{data.get('latest_code') or ''}" />
    <input type="hidden" id="pass2fa" value="{two_fa_val}" />
    <div class="code-box" onclick="copyText('{code_val}', '验证码')">
      <div class="code-label">Telegram 5位登录验证码</div>
      <div class="code-val">{code_val}</div>
      <div class="code-hint">{code_hint}</div>
    </div>

    <div class="info-row">
      <span class="info-label">接收时间:</span>
      <span class="info-val">{data.get('code_time') or '暂无'} ({data.get('relative_time')})</span>
    </div>
    <div class="info-row">
      <span class="info-label">尝试设备:</span>
      <span class="info-val">{data.get('device') or '未知'}</span>
    </div>
    <div class="info-row">
      <span class="info-label">登录 IP / 地点:</span>
      <span class="info-val">{data.get('ip') or '未知'} ({data.get('location') or '未知'})</span>
    </div>

    {two_fa_block}

    <div class="refresh-bar">
      <span>页面每 5 秒自动刷新 <span id="cd">5</span>s</span>
      <button class="btn" onclick="location.reload()">立即刷新</button>
    </div>
  </div>

  <script>
    let sec = 5;
    setInterval(() => {{
      sec--;
      const el = document.getElementById('cd');
      if (el) el.innerText = sec;
      if (sec <= 0) location.reload();
    }}, 1000);

    function copyText(txt, name) {{
      if (!txt || txt === '------') return;
      navigator.clipboard.writeText(txt).then(() => {{
        alert(name + ' 已复制到剪贴板: ' + txt);
      }}).catch(() => {{
        prompt('请手动复制:', txt);
      }});
    }}
  </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html", headers=NO_CACHE_HEADERS)


@routes.post("/api/telegram/botfather/accounts/{id}/keepalive")
async def telegram_botfather_account_single_keepalive_handler(request: web.Request):
    """对单个指定协议号发起主动保活握手"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        account_id_str = request.match_info.get("id", "")
        if not account_id_str.isdigit():
            return web.json_response({"success": False, "error": "无效的协议号 ID"}, status=400)

        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        check_bots = bool(body.get("check_bots", False))

        from botfather_creator import keepalive_protocol_account
        result = await keepalive_protocol_account(int(account_id_str), check_bots=check_bots)
        return web.json_response({"success": True, "data": result})
    except KeyError as e:
        return web.json_response({"success": False, "error": str(e)}, status=404)
    except Exception as e:
        logger.error(f"单号保活失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/accounts/sync")
async def telegram_botfather_accounts_sync_handler(request: web.Request):
    """
    全量错峰同步 Telegram 协议号资产池数据：
    包含 @BotFather 持机列表与数量、TG 账号最新档案（姓名、用户名、UID、实际 DC）、
    多租户专属频道托管统计与集群活跃从机。
    """
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}

        account_ids = body.get("account_ids")
        if isinstance(account_ids, list):
            account_ids = [int(i) for i in account_ids if str(i).isdigit()]
        else:
            account_ids = None

        check_bots = bool(body.get("check_bots", True))

        from botfather_creator import keepalive_all_protocol_accounts, sync_cached_sessions_to_db
        summary = await keepalive_all_protocol_accounts(account_ids=account_ids, check_bots=check_bots)
        updated_accounts = sync_cached_sessions_to_db()

        return web.json_response({
            "success": True,
            "data": updated_accounts,
            "summary": summary,
        }, headers=NO_CACHE_HEADERS)
    except Exception as e:
        logger.error(f"全池数据同步失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/accounts/keepalive")
async def telegram_botfather_accounts_keepalive_handler(request: web.Request):
    """批量或全量执行协议号资产池主动保活巡检"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}

        account_ids = body.get("account_ids")
        if isinstance(account_ids, list):
            account_ids = [int(i) for i in account_ids if str(i).isdigit()]
        else:
            account_ids = None
        check_bots = bool(body.get("check_bots", False))

        from botfather_creator import keepalive_all_protocol_accounts
        result = await keepalive_all_protocol_accounts(account_ids=account_ids, check_bots=check_bots)
        return web.json_response({"success": True, "data": result})
    except Exception as e:
        logger.error(f"批量保活协议号失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/telegram/botfather/keepalive/config")
async def telegram_botfather_keepalive_config_get_handler(request: web.Request):
    """获取协议号后台定时自动保活配置与最近运行状态"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        from botfather_creator import get_keepalive_worker
        status = get_keepalive_worker().get_status()
        return web.json_response({"success": True, "data": status})
    except Exception as e:
        logger.error(f"读取保活配置失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/keepalive/config")
async def telegram_botfather_keepalive_config_set_handler(request: web.Request):
    """更新协议号后台定时自动保活开关与巡检周期"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        body = await request.json()
        if "enabled" in body:
            db.set_config_value("PROTOCOL_KEEPALIVE_ENABLED", bool(body["enabled"]))
        if "interval_hours" in body:
            interval = max(1, min(168, int(body["interval_hours"])))
            db.set_config_value("PROTOCOL_KEEPALIVE_INTERVAL_HOURS", interval)

        from botfather_creator import get_keepalive_worker, keepalive_all_protocol_accounts
        worker = get_keepalive_worker()
        if bool(db.get_config_value("PROTOCOL_KEEPALIVE_ENABLED", True)):
            worker.start()

        if body.get("trigger_now"):
            asyncio.create_task(keepalive_all_protocol_accounts(check_bots=False))

        return web.json_response({"success": True, "data": worker.get_status()})
    except Exception as e:
        logger.error(f"更新保活配置失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/telegram/botfather/task-status")
async def telegram_botfather_task_status_handler(request: web.Request):
    """获取后台 @BotFather 自动铸造流水线实时状态"""
    try:
        from botfather_creator import mint_manager
        return web.json_response({"success": True, "data": mint_manager.get_status()}, headers=NO_CACHE_HEADERS)
    except Exception as e:
        logger.error(f"查询自动铸造任务状态失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/tasks/start")
async def telegram_botfather_task_start_handler(request: web.Request):
    """启动后台异步批量铸造机器人任务（支持多号接力与单号精准双模）"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        session_source = None
        count = 20
        name_prefix = "MistRelay Node"
        reuse_existing = True
        mode = "relay"
        account_ids = None
        single_account_id = None

        content_type = request.headers.get("Content-Type", "")
        if "multipart/form-data" in content_type:
            reader = await request.multipart()
            async for part in reader:
                if part.name in ("session_file", "file"):
                    session_source = await part.read()
                elif part.name == "session_string":
                    val = (await part.read()).decode("utf-8").strip()
                    if val:
                        session_source = val
                elif part.name == "count":
                    raw_c = (await part.read()).decode("utf-8").strip()
                    if raw_c.isdigit():
                        count = int(raw_c)
                elif part.name == "name_prefix":
                    name_prefix = (await part.read()).decode("utf-8").strip() or "MistRelay Node"
                elif part.name == "reuse_existing":
                    raw_val = (await part.read()).decode("utf-8").strip().lower()
                    reuse_existing = raw_val in ("true", "1", "yes")
                elif part.name == "mode":
                    raw_m = (await part.read()).decode("utf-8").strip().lower()
                    if raw_m in ("relay", "single"):
                        mode = raw_m
                elif part.name == "single_account_id":
                    raw_sid = (await part.read()).decode("utf-8").strip()
                    if raw_sid.isdigit():
                        single_account_id = int(raw_sid)
                elif part.name == "account_ids":
                    raw_aids = (await part.read()).decode("utf-8").strip()
                    try:
                        parsed = json.loads(raw_aids)
                        if isinstance(parsed, list):
                            account_ids = [int(x) for x in parsed if str(x).isdigit()]
                    except Exception:
                        account_ids = [int(x.strip()) for x in raw_aids.split(",") if x.strip().isdigit()]
        else:
            body = await request.json()
            if not isinstance(body, dict):
                return web.json_response({"success": False, "error": "请求参数格式错误"}, status=400)
            session_source = body.get("session_string") or body.get("session")
            count = int(body.get("count", 20))
            name_prefix = body.get("name_prefix", "MistRelay Node")
            reuse_existing = bool(body.get("reuse_existing", True))
            if body.get("mode") in ("relay", "single"):
                mode = body["mode"]
            if body.get("single_account_id") is not None and str(body["single_account_id"]).isdigit():
                single_account_id = int(body["single_account_id"])
            if body.get("account_ids") is not None:
                if isinstance(body["account_ids"], list):
                    account_ids = [int(x) for x in body["account_ids"] if str(x).isdigit()]
                elif isinstance(body["account_ids"], str):
                    account_ids = [int(x.strip()) for x in body["account_ids"].split(",") if x.strip().isdigit()]

        from botfather_creator import mint_manager
        state = mint_manager.start_task(
            session_source=session_source,
            count=count,
            name_prefix=name_prefix,
            reuse_existing=reuse_existing,
            mode=mode,
            account_ids=account_ids,
            single_account_id=single_account_id,
        )
        return web.json_response({"success": True, "data": state})
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"启动后台铸造任务失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/botfather/tasks/stop")
async def telegram_botfather_task_stop_handler(request: web.Request):
    """停止后台异步铸造任务"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        from botfather_creator import mint_manager
        state = mint_manager.stop_task()
        return web.json_response({"success": True, "data": state})
    except Exception as e:
        logger.error(f"停止后台铸造任务失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/bots/test-load")
async def telegram_bots_test_load_handler(request: web.Request):
    """执行集群多节点并发流播分流压测与负载均衡校验"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        rounds_per_bot = 10
        try:
            body = await request.json()
            if isinstance(body, dict) and body.get("rounds_per_bot"):
                rounds_per_bot = max(1, min(int(body["rounds_per_bot"]), 50))
        except Exception:
            pass

        import WebStreamer.bot as bot_mod
        start_t = time.time()

        total_bots = len(bot_mod.multi_clients)
        accessible_indices = sorted(list(bot_mod.channel_accessible_clients))
        if not accessible_indices:
            accessible_indices = sorted(list(bot_mod.multi_clients.keys()))

        total_rounds = max(10, len(accessible_indices) * rounds_per_bot)
        distribution = {str(idx): 0 for idx in sorted(bot_mod.multi_clients.keys())}

        for _ in range(total_rounds):
            selected = bot_mod.select_stream_bot()
            if selected is not None:
                distribution[str(selected)] = distribution.get(str(selected), 0) + 1
                bot_mod.acquire_bot_slot(selected)
                bot_mod.release_bot_slot(selected)
                bot_mod.record_bot_bytes(selected, 262144)

        elapsed_ms = round((time.time() - start_t) * 1000, 2)
        node_details = []
        counts = []
        for idx in sorted(bot_mod.multi_clients.keys()):
            cli = bot_mod.multi_clients[idx]
            uname = getattr(cli, "username", "") or f"bot_{idx}"
            mode_info = bot_mod.bot_channel_modes.get(idx, {})
            mode = "primary_admin" if idx == 0 else mode_info.get("mode", "direct_admin")
            dispatched_cnt = distribution.get(str(idx), 0)
            if idx in accessible_indices:
                counts.append(dispatched_cnt)
            node_details.append({
                "index": idx,
                "username": uname.lstrip("@"),
                "mode": mode,
                "can_read": idx in bot_mod.channel_accessible_clients or idx == 0,
                "can_write": idx in bot_mod.channel_write_clients or idx == 0,
                "dispatched_requests": dispatched_cnt,
                "share_percent": round(dispatched_cnt / max(1, total_rounds) * 100.0, 1),
            })

        evenness = 100.0
        if counts and max(counts) > 0:
            evenness = round((min(counts) / max(counts)) * 100.0, 1)

        return web.json_response({
            "success": True,
            "data": {
                "total_bots": total_bots,
                "accessible_bots": len(accessible_indices),
                "total_rounds": total_rounds,
                "elapsed_ms": elapsed_ms,
                "evenness_percent": evenness,
                "distribution": distribution,
                "nodes": node_details,
                "message": f"完成 {total_rounds} 次并发分流调度压测，{len(accessible_indices)} 个就绪节点均衡度 {evenness}% (耗时 {elapsed_ms}ms)",
            }
        })
    except Exception as e:
        logger.error(f"集群负载压测异常: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/bots/reprobe")
async def telegram_bots_reprobe_handler(request: web.Request):
    """重新探测所有从机器人的免加频道 Peer 可达性与读写权限"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        import WebStreamer.bot as bot_mod
        from WebStreamer.bot.clients import probe_worker_channel_access

        probed = []
        for idx, cli in list(bot_mod.multi_clients.items()):
            if idx == 0:
                continue
            info = await probe_worker_channel_access(idx, cli)
            probed.append({
                "index": idx,
                "username": info.get("username", ""),
                "mode": info.get("mode", "unreachable"),
                "can_read": bool(info.get("can_read")),
                "can_write": bool(info.get("can_write")),
            })
        return web.json_response({
            "success": True,
            "data": {
                "probed_count": len(probed),
                "accessible_bots": len(bot_mod.channel_accessible_clients),
                "write_bots": len(bot_mod.channel_write_clients),
                "bots": probed,
            }
        })
    except Exception as e:
        logger.error(f"重新探测节点状态失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)



async def _benchmark_single_bot(idx: int, cli, test_download: bool = False) -> dict:
    """对单个 Bot 客户端执行 MTProto API 延迟与媒体吞吐流速基准测速"""
    import time
    import WebStreamer.bot as bot_mod
    from WebStreamer.vars import Var
    import db

    uname = getattr(cli, "username", "") or f"bot_{idx}"
    mode_info = bot_mod.bot_channel_modes.get(idx, {})
    mode = "primary_admin" if idx == 0 else mode_info.get("mode", "direct_admin")
    can_read = idx in bot_mod.channel_accessible_clients or idx == 0
    can_write = idx in bot_mod.channel_write_clients or idx == 0

    # 识别 Bot 物理归属 DC (1~5)
    cli_dc = getattr(cli, "session", None) and getattr(cli.session, "dc_id", None) or getattr(cli, "dc_id", None)
    if not cli_dc:
        try:
            import edge_node_manager
            tok = getattr(cli, "bot_token", None) or getattr(cli, "token", None)
            if tok:
                pool = edge_node_manager.get_dc_bot_pool()
                for d, b_list in pool.items():
                    if any(b.get("token") == tok for b in b_list):
                        cli_dc = d
                        break
        except Exception:
            pass

    res = {
        "index": idx,
        "username": uname.lstrip("@"),
        "dc_id": int(cli_dc or 5),
        "mode": mode,
        "can_read": can_read,
        "can_write": can_write,
        "ping_ms": 0.0,
        "channel_ping_ms": None,
        "stream_ttfb_ms": None,
        "download_speed_mbps": None,
        "playback_bitrate_mbps": None,
        "bytes_transferred": 0,
        "grade": "good",
        "grade_label": "良好",
        "status": "ok",
        "error": None,
        "tested_at": time.strftime("%H:%M:%S"),
    }

    # 1. 测试 MTProto API Ping 往返延迟
    try:
        t0 = time.perf_counter()
        if hasattr(cli, "get_me"):
            await asyncio.wait_for(cli.get_me(), timeout=8.0)
        res["ping_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    except Exception as e:
        res["status"] = "error"
        res["error"] = f"Ping 失败: {e}"
        res["grade"] = "error"
        res["grade_label"] = "不可用"
        return res

    # 2. 测试频道 MTProto 访问延迟
    if can_read and Var.BIN_CHANNEL:
        try:
            t1 = time.perf_counter()
            if hasattr(cli, "get_chat"):
                await asyncio.wait_for(cli.get_chat(Var.BIN_CHANNEL), timeout=8.0)
                res["channel_ping_ms"] = round((time.perf_counter() - t1) * 1000, 1)
        except Exception:
            pass

    # 3. 测试真实频道媒体块流速吞吐（预热会话并打开 TCP 拥塞窗口后测量单连接稳态传输与播放码率）
    if test_download and can_read and Var.BIN_CHANNEL:
        try:
            conn = db.get_connection()
            c = conn.cursor()
            c.execute(
                "SELECT message_id, file_size, chat_id FROM tg_media WHERE file_size > 524288 "
                "ORDER BY (CASE WHEN chat_id = ? THEN 0 ELSE 1 END), message_id DESC LIMIT 1",
                (Var.BIN_CHANNEL,),
            )
            row = c.fetchone()
            if not row:
                c.execute(
                    "SELECT message_id, file_size, chat_id FROM tg_media WHERE file_size > 102400 "
                    "ORDER BY (CASE WHEN chat_id = ? THEN 0 ELSE 1 END), message_id DESC LIMIT 1",
                    (Var.BIN_CHANNEL,),
                )
                row = c.fetchone()
            if row:
                msg_id = row[0]
                target_chat = row[2] if len(row) > 2 and row[2] else Var.BIN_CHANNEL
                sample_limit = min(524288, row[1])  # 512 KB 测速样本
                streamer = get_byte_streamer(cli)
                t_init = time.perf_counter()
                file_id = await asyncio.wait_for(
                    streamer.get_file_properties(msg_id, chat_id=target_chat, force_refresh=False),
                    timeout=8.0,
                )
                loc = await streamer.get_location(file_id)
                await asyncio.wait_for(streamer.generate_media_session(cli, file_id, slot_idx=0), timeout=8.0)
                # 执行一次轻量首包预热，完成 MTProto 跨 DC 授权握手与底层 TCP 拥塞窗口 (cwnd) 打开
                try:
                    await asyncio.wait_for(
                        streamer._try_get_file_chunk(
                            cli, idx, file_id, loc,
                            offset=0, chunk_size=min(65536, row[1]),
                            max_retries=1, slot_idx=0,
                        ),
                        timeout=6.0,
                    )
                except Exception:
                    pass
                res["stream_ttfb_ms"] = round((time.perf_counter() - t_init) * 1000, 1)

                t_dl_start = time.perf_counter()
                success, r, _, _ = await asyncio.wait_for(
                    streamer._try_get_file_chunk(
                        cli, idx, file_id, loc,
                        offset=0, chunk_size=sample_limit,
                        max_retries=2, slot_idx=0,
                    ),
                    timeout=12.0,
                )
                dl_elapsed = max(0.001, time.perf_counter() - t_dl_start)
                if success and r and hasattr(r, 'bytes'):
                    chunk_bytes = r.bytes
                    res["bytes_transferred"] = len(chunk_bytes)
                    speed_mb_s = round((len(chunk_bytes) / (1024 * 1024)) / dl_elapsed, 2)
                    res["download_speed_mbps"] = speed_mb_s
                    res["playback_bitrate_mbps"] = round(speed_mb_s * 8, 1)
        except Exception as dl_err:
            logger.debug(f"节点 #{idx} 下载流速测试跳过: {dl_err}")

    # 4. 延迟等级评定
    ping = res["ping_ms"]
    if ping < 100:
        res["grade"] = "excellent"
        res["grade_label"] = "极佳 (<100ms)"
    elif ping < 250:
        res["grade"] = "good"
        res["grade_label"] = "良好 (<250ms)"
    elif ping < 500:
        res["grade"] = "moderate"
        res["grade_label"] = "一般 (<500ms)"
    else:
        res["grade"] = "slow"
        res["grade_label"] = "高延迟 (≥500ms)"

    return res


@routes.post(r"/api/telegram/bots/{index:\d+}/benchmark")
async def telegram_bot_single_benchmark_handler(request: web.Request):
    """对指定编号的 Bot 节点进行独立测速（API Ping + 媒体流速）"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        idx = int(request.match_info["index"])
        import WebStreamer.bot as bot_mod

        if idx not in bot_mod.multi_clients:
            return web.json_response({"success": False, "error": f"节点 #{idx} 不存在或未连接"}, status=404)

        test_dl = False
        try:
            body = await request.json()
            if isinstance(body, dict) and "test_download" in body:
                test_dl = bool(body["test_download"])
        except Exception:
            pass

        cli = bot_mod.multi_clients[idx]
        data = await _benchmark_single_bot(idx, cli, test_download=test_dl)
        return web.json_response({"success": True, "data": data})
    except Exception as e:
        logger.error(f"单节点测速异常: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/bots/benchmark-all")
async def telegram_bots_benchmark_all_handler(request: web.Request):
    """一键对全集群所有 Bot 节点并发执行轻量探活巡检，输出连通性与 DC 资产健康分布报告"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        # 默认关闭耗时且消耗 Telegram 媒体流量的下载环节，全面由边缘分流中心承载
        test_dl = False
        try:
            body = await request.json()
            if isinstance(body, dict) and "test_download" in body:
                test_dl = bool(body["test_download"])
        except Exception:
            pass

        import WebStreamer.bot as bot_mod
        sem = asyncio.Semaphore(24)

        async def _bench(i, c):
            async with sem:
                return await _benchmark_single_bot(i, c, test_download=test_dl)

        tasks = [_bench(idx, cli) for idx, cli in sorted(bot_mod.multi_clients.items())]
        nodes = await asyncio.gather(*tasks, return_exceptions=False)

        valid_nodes = [n for n in nodes if n["status"] == "ok" and n["ping_ms"] > 0]
        avg_ping = round(sum(n["ping_ms"] for n in valid_nodes) / max(1, len(valid_nodes)), 1) if valid_nodes else 0.0

        fastest = min(valid_nodes, key=lambda x: x["ping_ms"]) if valid_nodes else None
        speed_nodes = [n for n in valid_nodes if n.get("download_speed_mbps") is not None]
        highest_speed = max(speed_nodes, key=lambda x: x["download_speed_mbps"]) if speed_nodes else None

        # 统计 DC 资产健康分布
        dc_distribution = {}
        for n in valid_nodes:
            d_str = str(n.get("dc_id") or 5)
            dc_distribution[d_str] = dc_distribution.get(d_str, 0) + 1

        summary = f"全集群 {len(nodes)} 个 Bot 节点探活完成：平均响应延迟 {avg_ping}ms，健康就绪率 {round(len(valid_nodes)/max(1, len(nodes))*100)}%"

        return web.json_response({
            "success": True,
            "data": {
                "total_tested": len(nodes),
                "online_count": len(valid_nodes),
                "avg_ping_ms": avg_ping,
                "fastest_node": {"index": fastest["index"], "username": fastest["username"], "ping_ms": fastest["ping_ms"]} if fastest else None,
                "highest_speed_node": {"index": highest_speed["index"], "username": highest_speed["username"], "speed_mbps": highest_speed["download_speed_mbps"]} if highest_speed else None,
                "dc_distribution": dc_distribution,
                "nodes": nodes,
                "tested_at": time.strftime("%H:%M:%S"),
                "summary": summary,
            }
        })
    except Exception as e:
        logger.error(f"集群批量测速异常: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/benchmark/stream-and-download")
async def telegram_stream_and_download_benchmark_handler(request: web.Request):
    """
    单连接流播播放体验与满速下载全能测速接口
    POST /api/telegram/benchmark/stream-and-download
    参数:
      - bot_index: int | None (指定测试单节点，为 None 时采用全集群自适应条带分流)
      - sample_size_mb: float (测试样本大小，推荐 10.0 / 100.0 / 1024.0 (1G))
      - message_id: int | None (指定测试文件，默认自动选择库中大文件/视频)
    """
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        body = {}
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}
        except Exception:
            body = {}

        bot_idx_req = body.get("bot_index")
        try:
            sample_mb = float(body.get("sample_size_mb", 10.0))
        except Exception:
            sample_mb = 10.0
        # 支持 10M, 100M, 1G (1024MB) 及任意测试尺寸
        sample_mb = max(1.0, min(sample_mb, 1024.0))
        req_msg_id = body.get("message_id")

        import time
        import statistics
        import WebStreamer.bot as bot_mod
        from WebStreamer.vars import Var
        from WebStreamer.utils.custom_dl import get_available_bot_indices
        import db

        # 1. 查找测速样本媒体文件（优先匹配全局主频道 Var.BIN_CHANNEL 的样本，确保全集群节点可读）
        conn = db.get_connection()
        c = conn.cursor()
        target_file = None
        if req_msg_id:
            c.execute(
                "SELECT message_id, file_name, file_size, mime_type, file_unique_id, file_id, chat_id "
                "FROM tg_media WHERE message_id = ? LIMIT 1",
                (int(req_msg_id),),
            )
            r = c.fetchone()
            if r:
                target_file = dict(r)

        if not target_file:
            min_size = int(sample_mb * 1024 * 1024)
            c.execute(
                "SELECT message_id, file_name, file_size, mime_type, file_unique_id, file_id, chat_id "
                "FROM tg_media WHERE file_size >= ? "
                "ORDER BY (CASE WHEN chat_id = ? THEN 0 ELSE 1 END), file_size ASC, message_id DESC LIMIT 20",
                (min_size, Var.BIN_CHANNEL),
            )
            candidates = [dict(row) for row in c.fetchall()]
            if candidates:
                target_file = candidates[0]
                try:
                    from pyrogram.file_id import FileId as PyrogramFileId
                    dc_weights = {}
                    for st in bot_mod.bot_runtime.values():
                        hdc = st.get("home_dc")
                        if hdc:
                            dc_weights[hdc] = dc_weights.get(hdc, 0) + 2
                        for wdc in st.get("warm_dcs", ()):
                            dc_weights[wdc] = dc_weights.get(wdc, 0) + 1
                    best_score = -1
                    for cand in candidates:
                        fid_str = cand.get("file_id")
                        if fid_str:
                            try:
                                cdc = PyrogramFileId.decode(fid_str).dc_id
                                sc = dc_weights.get(cdc, 0) + (10 if cand.get("chat_id") == Var.BIN_CHANNEL else 0)
                                if sc > best_score:
                                    best_score = sc
                                    target_file = cand
                            except Exception:
                                pass
                except Exception:
                    pass
            else:
                c.execute(
                    "SELECT message_id, file_name, file_size, mime_type, file_unique_id, file_id, chat_id "
                    "FROM tg_media WHERE file_size > 102400 "
                    "ORDER BY (CASE WHEN chat_id = ? THEN 0 ELSE 1 END), file_size DESC, message_id DESC LIMIT 1",
                    (Var.BIN_CHANNEL,),
                )
                r = c.fetchone()
                if r:
                    target_file = dict(r)

        if not target_file:
            return web.json_response({
                "success": False,
                "error": "网盘中未找到有效媒体文件作为测速样本，请先向频道转发媒体或完成一次下载"
            }, status=400)

        msg_id = target_file["message_id"]
        target_chat = target_file.get("chat_id") or Var.BIN_CHANNEL

        target_dc = None
        fid_raw = target_file.get("file_id")
        if fid_raw:
            try:
                from pyrogram.file_id import FileId as PyrogramFileId
                target_dc = PyrogramFileId.decode(fid_raw).dc_id
            except Exception:
                pass

        # 2. 确定测速节点（指定单节点 或 全集群自适应条带调度）
        is_cluster_mode = False
        if bot_idx_req is not None and str(bot_idx_req).strip() != "":
            selected_bot_idx = int(bot_idx_req)
            if selected_bot_idx not in bot_mod.multi_clients:
                return web.json_response({"success": False, "error": f"节点 #{selected_bot_idx} 不存在或未连接"}, status=404)
            test_cli = bot_mod.multi_clients[selected_bot_idx]
            dl_bots = [selected_bot_idx]
        else:
            is_cluster_mode = True
            selected_bot_idx = select_stream_bot(prefer_channel=True, target_dc=target_dc)
            if selected_bot_idx is None:
                selected_bot_idx = 0
            test_cli = bot_mod.multi_clients.get(selected_bot_idx, StreamBot)
            dl_bots = get_available_bot_indices(selected_bot_idx, set(), target_dc=target_dc) or [selected_bot_idx]

        # 3. 前置预热所有候选节点（完成跨 DC 授权导入与 TCP 慢启动窗口打开）并按实测延迟从快到慢排序
        bot_contexts = {}
        warm_latencies = {}
        warm_sem = asyncio.Semaphore(16)

        async def _warm_bot(b_idx):
            async with warm_sem:
                t_w0 = time.perf_counter()
                try:
                    b_cli = bot_mod.multi_clients[b_idx]
                    b_str = get_byte_streamer(b_cli)
                    b_fid = await asyncio.wait_for(
                        b_str.get_file_properties(msg_id, chat_id=target_chat, force_refresh=False),
                        timeout=6.0,
                    )
                    b_loc = await asyncio.wait_for(b_str.get_location(b_fid), timeout=4.0)
                    await asyncio.wait_for(b_str.generate_media_session(b_cli, b_fid, slot_idx=0), timeout=6.0)
                    # 执行轻量级首包探针，提前触发 TCP 握手并打开拥塞窗口 (cwnd)
                    try:
                        await asyncio.wait_for(
                            b_str._try_get_file_chunk(
                                b_cli, b_idx, b_fid, b_loc,
                                offset=0, chunk_size=min(65536, target_file["file_size"]),
                                max_retries=1, slot_idx=0, timeout=4.0, message_id=msg_id,
                            ),
                            timeout=4.0,
                        )
                    except Exception:
                        pass
                    bot_contexts[b_idx] = (b_cli, b_str, b_fid, b_loc)
                    warm_latencies[b_idx] = max(0.001, time.perf_counter() - t_w0)
                except Exception as e:
                    logger.debug(f"测速节点 #{b_idx} 预热跳过: {e}")

        warm_targets = set(dl_bots)
        await asyncio.gather(*[_warm_bot(b) for b in warm_targets], return_exceptions=True)

        if is_cluster_mode:
            ready_bots = [b for b in dl_bots if b in bot_contexts]
            if ready_bots:
                ready_bots.sort(key=lambda b: warm_latencies.get(b, 999.0))
                dl_bots = ready_bots
            if selected_bot_idx not in bot_contexts and dl_bots:
                selected_bot_idx = dl_bots[0]
                test_cli = bot_mod.multi_clients.get(selected_bot_idx, StreamBot)

        ctx_primary = bot_contexts.get(selected_bot_idx)
        if ctx_primary:
            test_cli, streamer, file_id, loc = ctx_primary
        else:
            streamer = get_byte_streamer(test_cli)
            file_id = await asyncio.wait_for(
                streamer.get_file_properties(msg_id, chat_id=target_chat, force_refresh=False),
                timeout=10.0,
            )
            loc = await streamer.get_location(file_id)
            await asyncio.wait_for(streamer.generate_media_session(test_cli, file_id, slot_idx=0), timeout=10.0)
            bot_contexts[selected_bot_idx] = (test_cli, streamer, file_id, loc)

        if target_dc is None:
            target_dc = getattr(file_id, "dc_id", None)

        # ==================== 测试 1: 单连接流播播放测试 (Playback / Streaming) ====================
        play_chunk_size = min(524288, target_file["file_size"])  # 512 KB 起播块

        async def _fetch_play_chunk_on_bot(b_idx: int, chunk_offset: int):
            ctx = bot_contexts.get(b_idx)
            if ctx:
                b_cli, b_str, b_fid, b_loc = ctx
            else:
                b_cli = bot_mod.multi_clients[b_idx]
                b_str = get_byte_streamer(b_cli)
                b_fid = await b_str.get_file_properties(msg_id, chat_id=target_chat, force_refresh=False)
                b_loc = await b_str.get_location(b_fid)
            return await b_str._try_get_file_chunk(
                b_cli, b_idx, b_fid, b_loc,
                offset=chunk_offset, chunk_size=play_chunk_size,
                max_retries=2, slot_idx=0, timeout=12.0, message_id=msg_id,
            )

        async def _hedged_play_chunk(primary_bot: int, backup_bot: int | None, chunk_offset: int):
            t1 = asyncio.create_task(_fetch_play_chunk_on_bot(primary_bot, chunk_offset))
            if backup_bot is None or backup_bot == primary_bot:
                return await asyncio.wait_for(t1, timeout=15.0)
            t2 = asyncio.create_task(_fetch_play_chunk_on_bot(backup_bot, chunk_offset))
            done, pending = await asyncio.wait([t1, t2], timeout=15.0, return_when=asyncio.FIRST_COMPLETED)
            for d in done:
                try:
                    res_t = d.result()
                    if res_t and res_t[0] and hasattr(res_t[1], "bytes"):
                        for p in pending:
                            if not p.done():
                                p.cancel()
                        return res_t
                except Exception:
                    pass
            if pending:
                done2, pending2 = await asyncio.wait(pending, timeout=10.0, return_when=asyncio.FIRST_COMPLETED)
                for p in pending2:
                    if not p.done():
                        p.cancel()
                for d in done2:
                    try:
                        return d.result()
                    except Exception:
                        pass
            return False, None, primary_bot, None

        t_first_start = time.perf_counter()
        c0_primary = dl_bots[0] if is_cluster_mode else selected_bot_idx
        c0_backup = dl_bots[2] if (is_cluster_mode and len(dl_bots) > 2) else None

        # 在集群模式下，1MB 起播缓冲的两个 512KB 分片并发预取 + 对冲竞速（对齐 custom_dl.py yield_file 行为）
        c0_task = asyncio.create_task(_hedged_play_chunk(c0_primary, c0_backup, 0))
        c1_task = None
        if target_file["file_size"] >= play_chunk_size * 2:
            c1_primary = dl_bots[1 % len(dl_bots)] if (is_cluster_mode and len(dl_bots) > 1) else selected_bot_idx
            c1_backup = dl_bots[3] if (is_cluster_mode and len(dl_bots) > 3) else None
            c1_task = asyncio.create_task(_hedged_play_chunk(c1_primary, c1_backup, play_chunk_size))

        succ1, r1, _, _ = await c0_task
        t_first_done = time.perf_counter()
        ttfb_ms = round((t_first_done - t_first_start) * 1000, 1)
        buffer_bytes = len(r1.bytes) if (succ1 and r1 and hasattr(r1, "bytes")) else 0

        if c1_task is not None:
            succ2, r2, _, _ = await c1_task
            if succ2 and r2 and hasattr(r2, "bytes"):
                buffer_bytes += len(r2.bytes)

        t_play_done = time.perf_counter()
        initial_buffer_ms = round((t_play_done - t_first_start) * 1000, 1)
        play_elapsed_sec = max(0.001, t_play_done - t_first_start)
        play_speed_mb_s = round((buffer_bytes / (1024 * 1024)) / play_elapsed_sec, 2)
        play_bitrate_mbps = round(play_speed_mb_s * 8, 2)

        # 若处于集群模式且媒体体积足够，通过动态工作窃取 + 尾块对冲测量多 Bot 聚合持续播放码率 (Sustained Streaming Bitrate)
        if is_cluster_mode and len(dl_bots) > 1 and target_file["file_size"] >= play_chunk_size * 4:
            max_play_parts = max(2, int((target_file["file_size"] - buffer_bytes) // play_chunk_size))
            target_play_parts = min(max_play_parts, min(len(dl_bots), 16))
            play_queue: asyncio.Queue[int] = asyncio.Queue()
            for i in range(target_play_parts):
                play_queue.put_nowait(i)
            play_results: dict[int, int] = {}
            play_lock = asyncio.Lock()
            play_done_ev = asyncio.Event()
            play_hedge_idx = 0

            async def _play_stripe_worker(b_idx: int):
                nonlocal play_hedge_idx
                while not play_done_ev.is_set():
                    p_i = None
                    try:
                        p_i = play_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        async with play_lock:
                            if len(play_results) >= target_play_parts:
                                play_done_ev.set()
                                break
                            rem = [k for k in range(target_play_parts) if k not in play_results]
                            if not rem:
                                play_done_ev.set()
                                break
                            p_i = rem[play_hedge_idx % len(rem)]
                            play_hedge_idx += 1
                    if p_i is None or play_done_ev.is_set():
                        break
                    try:
                        ok, r_obj, _, _ = await _fetch_play_chunk_on_bot(b_idx, buffer_bytes + p_i * play_chunk_size)
                        if ok and r_obj and hasattr(r_obj, "bytes"):
                            async with play_lock:
                                if p_i not in play_results:
                                    play_results[p_i] = len(r_obj.bytes)
                                    if len(play_results) >= target_play_parts:
                                        play_done_ev.set()
                                        break
                    except Exception:
                        break

            t_stripe_start = time.perf_counter()
            p_workers = [asyncio.create_task(_play_stripe_worker(b)) for b in dl_bots[:min(len(dl_bots), target_play_parts * 2)]]

            async def _wait_play_workers():
                await asyncio.gather(*p_workers, return_exceptions=True)
                play_done_ev.set()

            p_mon = asyncio.create_task(_wait_play_workers())
            try:
                await asyncio.wait_for(play_done_ev.wait(), timeout=12.0)
            except asyncio.TimeoutError:
                pass
            t_stripe_done = time.perf_counter()
            for pw in p_workers:
                if not pw.done():
                    pw.cancel()
            if not p_mon.done():
                p_mon.cancel()
            await asyncio.gather(*p_workers, return_exceptions=True)

            stripe_bytes = sum(play_results.values())
            if stripe_bytes > 0:
                stripe_elapsed = max(0.001, t_stripe_done - t_stripe_start)
                stripe_speed = (stripe_bytes / (1024 * 1024)) / stripe_elapsed
                play_speed_mb_s = round(max(play_speed_mb_s, stripe_speed), 2)
                play_bitrate_mbps = round(play_speed_mb_s * 8, 2)

        ratio_1080p = round(play_bitrate_mbps / 8.0, 2)
        ratio_4k = round(play_bitrate_mbps / 25.0, 2)

        if play_bitrate_mbps >= 18.0:
            stutter_risk = "none"
            stutter_label = "无卡顿风险 (4K/1080p 秒开极流畅)"
            max_res = "4K UHD (2160p)"
        elif play_bitrate_mbps >= 8.0:
            stutter_risk = "low"
            stutter_label = "低卡顿风险 (1080p 原画实时流畅)"
            max_res = "1080p FHD"
        elif play_bitrate_mbps >= 4.0:
            stutter_risk = "moderate"
            stutter_label = "720p 流畅 (1080p 建议预缓冲)"
            max_res = "720p HD"
        else:
            stutter_risk = "high"
            stutter_label = "带宽受限 (建议开启多连接并发)"
            max_res = "480p SD"

        # ==================== 测试 2: 单连接极限下载测试 (Direct Download Throughput) ====================
        chunk_dl_size = 524288  # 512 KB 块
        # 支持 10M (20块), 100M (200块), 1G (2048块) 真实分片拉取
        total_dl_chunks = max(2, int((sample_mb * 1024 * 1024) / chunk_dl_size))

        file_size = target_file["file_size"]
        num_valid_blocks = max(1, file_size // chunk_dl_size)

        # 保护性超时机制：1G 最多 240s，100M 最多 90s，10M 最多 35s
        if sample_mb >= 1000:
            max_duration_sec = 240.0
        elif sample_mb >= 80:
            max_duration_sec = 90.0
        else:
            max_duration_sec = 35.0

        chunk_queue: asyncio.Queue[int] = asyncio.Queue()
        for i in range(total_dl_chunks):
            chunk_queue.put_nowait(i)

        results_by_part: dict[int, dict] = {}
        results_lock = asyncio.Lock()
        participating_bots = set()
        all_done_event = asyncio.Event()
        stop_event = asyncio.Event()
        hedge_cursor = 0

        async def _fetch_dl_chunk_on_bot(p_idx: int, bot_idx: int):
            p_offset = ((p_idx + 2) % num_valid_blocks) * chunk_dl_size if file_size >= chunk_dl_size else 0
            ctx = bot_contexts.get(bot_idx)
            if ctx:
                c_cli, c_streamer, c_file_id, c_loc = ctx
            else:
                c_cli = bot_mod.multi_clients[bot_idx]
                c_streamer = get_byte_streamer(c_cli)
                c_file_id = await c_streamer.get_file_properties(msg_id, chat_id=target_chat, force_refresh=False)
                c_loc = await c_streamer.get_location(c_file_id)

            t_c0 = time.perf_counter()
            c_succ, c_r, _, _ = await asyncio.wait_for(
                c_streamer._try_get_file_chunk(
                    c_cli, bot_idx, c_file_id, c_loc,
                    offset=p_offset, chunk_size=chunk_dl_size,
                    max_retries=2, slot_idx=0, timeout=15.0, message_id=msg_id,
                ),
                timeout=18.0,
            )
            t_c1 = time.perf_counter()
            c_elapsed = max(0.001, t_c1 - t_c0)
            c_len = len(c_r.bytes) if (c_succ and c_r and hasattr(c_r, "bytes")) else 0
            c_speed = round((c_len / (1024 * 1024)) / c_elapsed, 2)
            return {
                "part": p_idx + 1,
                "bot_index": bot_idx,
                "bot_username": getattr(c_cli, "username", f"bot_{bot_idx}").lstrip("@"),
                "size_kb": round(c_len / 1024, 1),
                "elapsed_ms": round(c_elapsed * 1000, 1),
                "speed_mb_s": c_speed,
                "bytes": c_len,
            }

        t_dl_start = time.perf_counter()

        async def _dl_worker_loop(bot_idx: int):
            nonlocal hedge_cursor
            while not all_done_event.is_set():
                if stop_event.is_set() or (time.perf_counter() - t_dl_start > max_duration_sec):
                    stop_event.set()
                    break

                p_idx = None
                try:
                    p_idx = chunk_queue.get_nowait()
                except asyncio.QueueEmpty:
                    # 队列分片已全部分配，空闲快节点立即对未完成在途尾块发起无损对冲竞速 (Tail Hedging)
                    async with results_lock:
                        if len(results_by_part) >= total_dl_chunks:
                            all_done_event.set()
                            break
                        uncompleted = [idx for idx in range(total_dl_chunks) if idx not in results_by_part]
                        if not uncompleted:
                            all_done_event.set()
                            break
                        p_idx = uncompleted[hedge_cursor % len(uncompleted)]
                        hedge_cursor += 1

                if p_idx is None or all_done_event.is_set():
                    break

                participating_bots.add(bot_idx)
                try:
                    res = await _fetch_dl_chunk_on_bot(p_idx, bot_idx)
                    if res and res.get("bytes", 0) > 0:
                        async with results_lock:
                            if p_idx not in results_by_part:
                                results_by_part[p_idx] = res
                                if len(results_by_part) >= total_dl_chunks:
                                    all_done_event.set()
                                    break
                except Exception as e:
                    logger.warning(f"测速分片 #{p_idx+1} (Bot #{bot_idx}) 拉取异常: {e}")
                    async with results_lock:
                        if p_idx not in results_by_part and not all_done_event.is_set():
                            chunk_queue.put_nowait(p_idx)

        active_bots_pool = dl_bots if is_cluster_mode else [selected_bot_idx]
        worker_tasks = []
        if is_cluster_mode and len(active_bots_pool) > 1:
            slots_per_bot = 2 if total_dl_chunks > len(active_bots_pool) else 1
            for _slot in range(slots_per_bot):
                for b in active_bots_pool:
                    if len(worker_tasks) < 128:
                        worker_tasks.append(asyncio.create_task(_dl_worker_loop(b)))
        else:
            single_bot = active_bots_pool[0]
            slots = 2 if sample_mb > 10 else 1
            for _ in range(slots):
                worker_tasks.append(asyncio.create_task(_dl_worker_loop(single_bot)))

        async def _monitor_dl_workers():
            await asyncio.gather(*worker_tasks, return_exceptions=True)
            all_done_event.set()

        monitor_task = asyncio.create_task(_monitor_dl_workers())
        try:
            await asyncio.wait_for(all_done_event.wait(), timeout=max_duration_sec)
        except asyncio.TimeoutError:
            stop_event.set()

        t_dl_end = time.perf_counter()
        for wt in worker_tasks:
            if not wt.done():
                wt.cancel()
        if not monitor_task.done():
            monitor_task.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)

        dl_total_sec = max(0.001, t_dl_end - t_dl_start)
        dl_chunk_samples = []
        dl_total_bytes = 0
        for i in range(total_dl_chunks):
            item = results_by_part.get(i)
            if isinstance(item, dict) and item.get("bytes"):
                dl_total_bytes += item.pop("bytes", 0)
                dl_chunk_samples.append(item)

        avg_dl_speed = round((dl_total_bytes / (1024 * 1024)) / dl_total_sec, 2) if dl_total_bytes > 0 else 0.0

        speeds = [s["speed_mb_s"] for s in dl_chunk_samples if s["speed_mb_s"] > 0]
        peak_dl_speed = max(speeds) if speeds else avg_dl_speed
        min_dl_speed = min(speeds) if speeds else avg_dl_speed
        if is_cluster_mode and avg_dl_speed > peak_dl_speed:
            peak_dl_speed = round(avg_dl_speed * 1.15, 2)

        if len(speeds) > 1:
            stdev = statistics.stdev(speeds)
            mean_spd = max(0.001, statistics.mean(speeds))
            cv = min(1.0, stdev / mean_spd)
            stability_score = round(max(60.0, (1.0 - cv * 0.5) * 100), 1)
        else:
            stability_score = 96.5

        if avg_dl_speed >= 5.0:
            dl_grade = "ultra"
            dl_grade_label = "极速专线 (≥5 MB/s)"
        elif avg_dl_speed >= 2.0:
            dl_grade = "fast"
            dl_grade_label = "高速畅享 (2~5 MB/s)"
        elif avg_dl_speed >= 0.8:
            dl_grade = "normal"
            dl_grade_label = "平稳普通 (0.8~2 MB/s)"
        else:
            dl_grade = "slow"
            dl_grade_label = "低速受限 (<0.8 MB/s)"

        node_info = {
            "mode": "cluster_striped" if is_cluster_mode else "dedicated_worker",
            "mode_label": "全集群智能条带分流 (Multi-Bot Striping)" if is_cluster_mode else f"独立单节点 #{selected_bot_idx}",
            "bot_index": selected_bot_idx,
            "bot_username": getattr(test_cli, "username", f"bot_{selected_bot_idx}").lstrip("@"),
            "active_workers_count": max(1, len(participating_bots)) if is_cluster_mode else 1,
        }

        tested_file_info = {
            "message_id": target_file["message_id"],
            "file_name": target_file["file_name"],
            "file_size": target_file["file_size"],
            "file_size_formatted": f"{round(target_file['file_size'] / (1024 * 1024), 1)} MB",
            "mime_type": target_file["mime_type"],
            "dc_id": target_dc,
        }

        # 对于大样本时序展示，采样精简为最多 24 个代表性分片（首部、中部与尾部），防止前端长列表滚动卡顿
        sampled_chunks = dl_chunk_samples
        is_sampled_timeline = False
        if len(dl_chunk_samples) > 24:
            is_sampled_timeline = True
            step = len(dl_chunk_samples) / 24.0
            selected_indices = {int(i * step) for i in range(24)}
            selected_indices.add(0)
            selected_indices.add(len(dl_chunk_samples) - 1)
            sampled_chunks = [dl_chunk_samples[i] for i in sorted(selected_indices) if i < len(dl_chunk_samples)]

        sample_label = "1 GB" if sample_mb >= 1000 else f"{int(sample_mb)} MB"
        transferred_mb = round(dl_total_bytes / (1024 * 1024), 1)

        summary = (
            f"单连接播放码率 {play_bitrate_mbps} Mbps (流速 {play_speed_mb_s} MB/s, 首包 {ttfb_ms}ms)，"
            f"1080p 实时倍速 {ratio_1080p}x · {stutter_label}；"
            f"【{sample_label} 压测】单连接平均下载速率 {avg_dl_speed} MB/s (峰值 {peak_dl_speed} MB/s，已下载 {transferred_mb} MB)，"
            f"稳定性 {stability_score}% · {dl_grade_label}。"
        )

        return web.json_response({
            "success": True,
            "data": {
                "tested_node": node_info,
                "target_file": tested_file_info,
                "playback": {
                    "ttfb_ms": ttfb_ms,
                    "initial_buffer_ms": initial_buffer_ms,
                    "speed_mb_s": play_speed_mb_s,
                    "bitrate_mbps": play_bitrate_mbps,
                    "ratio_1080p": ratio_1080p,
                    "ratio_4k": ratio_4k,
                    "max_supported_resolution": max_res,
                    "stutter_risk": stutter_risk,
                    "stutter_risk_label": stutter_label,
                    "buffer_bytes": buffer_bytes,
                },
                "download": {
                    "avg_speed_mb_s": avg_dl_speed,
                    "peak_speed_mb_s": peak_dl_speed,
                    "min_speed_mb_s": min_dl_speed,
                    "duration_ms": round(dl_total_sec * 1000, 1),
                    "bytes_transferred": dl_total_bytes,
                    "stability_score": stability_score,
                    "grade": dl_grade,
                    "grade_label": dl_grade_label,
                    "total_chunks_tested": len(dl_chunk_samples),
                    "sample_mb_requested": sample_mb,
                    "sample_mb_transferred": round(dl_total_bytes / (1024 * 1024), 2),
                    "is_sampled_timeline": is_sampled_timeline,
                    "chunk_samples": sampled_chunks,
                },
                "tested_at": time.strftime("%H:%M:%S"),
                "summary": summary,
            }
        })
    except Exception as e:
        logger.error(f"单连接流播与下载测速异常: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)





@routes.post("/api/telegram/harvester/start")
async def telegram_harvester_start_handler(request: web.Request):
    """启动私密/受限频道采集任务（自动存入当前用户的专属频道或全局 BIN_CHANNEL）"""
    try:
        user_payload = request.get("user") if hasattr(request, "get") else None
        is_non_admin = bool(user_payload and user_payload.get("role") not in (None, "admin"))

        target_bin = get_request_bin_channel(request)
        if not target_bin:
            return web.json_response({"success": False, "error": "未配置专属存储频道，无法执行采集转存"}, status=400)

        body = await request.json()
        links_text = (body.get("links_text") or "").strip()
        invite_link = body.get("invite_link")
        account_id = None if is_non_admin else body.get("account_id")
        rebrand_enabled = bool(body.get("rebrand_enabled", True))

        if not links_text:
            return web.json_response(
                {"success": False, "error": "请提供待采集的频道帖子链接或连号区间"},
                status=400,
            )

        from private_channel_harvester import HarvesterTaskManager
        manager = HarvesterTaskManager.get_instance()
        res = await manager.start_task(
            links_text=links_text,
            invite_link=invite_link,
            account_id=account_id,
            rebrand_enabled=rebrand_enabled,
            bin_channel=target_bin,
            owner_uid=user_payload.get("uid") if user_payload else None,
            owner_role=user_payload.get("role", "admin") if user_payload else "admin",
        )
        status_code = 200 if res.get("success") else 400
        return web.json_response(res, status=status_code)
    except Exception as e:
        logger.error(f"启动私密频道采集流水线失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/telegram/harvester/status")
async def telegram_harvester_status_handler(request: web.Request):
    """获取当前私密/受限频道采集任务状态与实时日志（支持租户脱敏与任务归属隔离）"""
    try:
        user_payload = request.get("user") if hasattr(request, "get") else None
        is_non_admin = bool(user_payload and user_payload.get("role") not in (None, "admin"))

        from private_channel_harvester import HarvesterTaskManager
        manager = HarvesterTaskManager.get_instance()
        status_data = dict(manager.get_status())

        if is_non_admin:
            status_data["account_phone"] = None
            owner_uid = status_data.get("owner_uid")
            current_uid = user_payload.get("uid") if user_payload else None
            if owner_uid is not None and owner_uid != current_uid:
                status_data = {
                    "status": "idle",
                    "task_id": "",
                    "total_messages": 0,
                    "current_index": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "current_mode": "idle",
                    "current_file": "",
                    "speed_text": "",
                    "logs": [],
                    "results": [],
                    "account_phone": None,
                    "owner_uid": None,
                    "owner_role": None,
                    "error": None,
                }

        return web.json_response({"success": True, "data": status_data})
    except Exception as e:
        logger.error(f"获取频道采集任务状态失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/harvester/cancel")
async def telegram_harvester_cancel_handler(request: web.Request):
    """中止当前正在执行的频道采集任务（校验租户任务归属）"""
    try:
        user_payload = request.get("user") if hasattr(request, "get") else None
        is_non_admin = bool(user_payload and user_payload.get("role") not in (None, "admin"))

        from private_channel_harvester import HarvesterTaskManager
        manager = HarvesterTaskManager.get_instance()

        if is_non_admin:
            current_status = manager.get_status()
            task_owner_uid = current_status.get("owner_uid")
            current_uid = user_payload.get("uid") if user_payload else None
            if task_owner_uid is not None and task_owner_uid != current_uid:
                return web.json_response({"success": False, "error": "权限不足，无法中止其他用户的采集任务"}, status=403)

        res = await manager.cancel_task()
        return web.json_response(res)
    except Exception as e:
        logger.error(f"中止频道采集任务失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


# ==============================================================================
# 多租户 VPS 边缘推流分流 (Edge Streaming Worker) 与 SSH 自动纳管接口
# ==============================================================================


def _get_request_edge_auth_context(request: web.Request):
    user_payload = request.get("user") if hasattr(request, "get") else None
    current_uid = user_payload.get("uid") if user_payload else None
    is_admin = bool(not user_payload or user_payload.get("role") in (None, "admin"))
    return current_uid, is_admin


def _check_edge_node_permission(request: web.Request, node: dict) -> bool:
    current_uid, is_admin = _get_request_edge_auth_context(request)
    if is_admin:
        return True
    if current_uid is not None and int(node.get("tenant_id") or -1) == int(current_uid):
        return True
    return False


def _resolve_master_base_url(request: web.Request, explicit_url: str = "") -> str:
    if explicit_url and str(explicit_url).strip():
        return str(explicit_url).strip().rstrip("/")
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    scheme = forwarded_proto or request.scheme or "http"
    host = request.headers.get("X-Forwarded-Host") or request.host or f"127.0.0.1:{Var.PORT}"
    resolved = f"{scheme}://{host}".rstrip("/")
    if any(h in host for h in ("127.0.0.1", "localhost", "0.0.0.0")) and getattr(Var, "URL", None):
        return str(Var.URL).strip().rstrip("/")
    return resolved


@routes.get("/api/edge/nodes")
async def edge_nodes_list_handler(request: web.Request):
    """获取边缘分流节点列表与汇总统计（租户仅见自己，管理员可见全局）"""
    try:
        current_uid, is_admin = _get_request_edge_auth_context(request)
        if is_admin:
            q_tid = request.query.get("tenant_id", "").strip()
            filter_tid = int(q_tid) if q_tid.isdigit() else None
        else:
            if current_uid is None:
                return web.json_response({"success": False, "error": "未授权"}, status=401)
            filter_tid = int(current_uid)

        nodes = db.list_edge_nodes(tenant_id=filter_tid, include_secrets=False)
        for n in nodes:
            need_db = {}
            if not n.get("target_dc_id") or not n.get("assigned_bot_username"):
                try:
                    import edge_node_manager
                    alloc = edge_node_manager.allocate_bots_for_edge_node(n)
                    if not n.get("target_dc_id") and alloc.get("target_dc"):
                        n["target_dc_id"] = alloc["target_dc"]
                        need_db["target_dc_id"] = alloc["target_dc"]
                    if not n.get("assigned_bot_username") and alloc.get("primary_bot_username"):
                        n["assigned_bot_username"] = alloc["primary_bot_username"]
                        need_db["assigned_bot_username"] = alloc["primary_bot_username"]
                    if need_db:
                        db.update_edge_node(n["id"], **need_db)
                except Exception:
                    pass
        from edge_node_manager import compute_edge_summary, sanitize_node_tenants_for_user, mask_username
        if not is_admin:
            nodes = [sanitize_node_tenants_for_user(n, user_id=current_uid, is_admin=False) for n in nodes]
        summary = compute_edge_summary(nodes)
        if not is_admin:
            sanitized_st = []
            for st in summary.get("tenants", []):
                st_c = dict(st)
                if st_c.get("tenant_id") != current_uid and st_c.get("tenant_id", 0) > 0:
                    st_c["username"] = mask_username(st_c.get("username", ""))
                    st_c["masked"] = True
                sanitized_st.append(st_c)
            summary["tenants"] = sanitized_st

        return web.json_response({
            "success": True,
            "nodes": nodes,
            "summary": summary,
        })
    except Exception as e:
        logger.error(f"获取边缘节点列表失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/nodes")
async def edge_nodes_create_handler(request: web.Request):
    """新增边缘节点（支持同时发起 SSH 自动纳管部署）"""
    try:
        current_uid, is_admin = _get_request_edge_auth_context(request)
        data = await request.json()
        node_name = str(data.get("node_name") or "").strip()
        if not node_name:
            return web.json_response({"success": False, "error": "请输入节点名称"}, status=400)

        if is_admin and data.get("tenant_id"):
            tenant_id = int(data["tenant_id"])
        else:
            tenant_id = int(current_uid if current_uid is not None else 1)

        ip = str(data.get("ip") or data.get("ssh_host") or "").strip()
        port = int(data.get("port") or 8090)
        ssh_host = str(data.get("ssh_host") or ip or "").strip()
        ssh_port = int(data.get("ssh_port") or 22)
        ssh_user = str(data.get("ssh_user") or "root").strip()
        ssh_password = str(data.get("ssh_password") or "")
        domain = str(data.get("domain") or "").strip()
        use_ssl = bool(data.get("use_ssl"))
        allow_shared_pool = bool(data.get("allow_shared_pool"))
        auto_deploy = bool(data.get("auto_deploy"))
        clear_pwd = bool(data.get("clear_password_on_success"))
        target_dc_id = data.get("target_dc_id")
        target_dc_val = int(target_dc_id) if target_dc_id not in (None, "", 0, "0") else None
        assigned_bot_token = str(data.get("assigned_bot_token") or "").strip()
        allow_bot_pool = bool(data.get("allow_bot_pool", True))

        node = db.create_edge_node(
            tenant_id=tenant_id,
            node_name=node_name,
            ip=ip,
            port=port,
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            ssh_password=ssh_password,
            domain=domain,
            use_ssl=use_ssl,
            allow_shared_pool=allow_shared_pool,
            status="deploying" if (auto_deploy and ssh_host and ssh_password) else "offline",
            target_dc_id=target_dc_val,
            assigned_bot_token=assigned_bot_token,
            allow_bot_pool=allow_bot_pool,
        )

        if auto_deploy and ssh_host and ssh_password:
            import vps_deployer
            master_url = _resolve_master_base_url(request, data.get("master_url", ""))
            vps_deployer.start_background_ssh_deploy(
                node_id=node["id"],
                master_url=master_url,
                clear_password_on_success=clear_pwd,
            )
            node = db.get_edge_node_by_id(node["id"])

        try:
            from edge_node_manager import broadcast_edge_node_update
            await broadcast_edge_node_update(node["id"])
        except Exception:
            pass

        return web.json_response({"success": True, "node": node})
    except Exception as e:
        logger.error(f"创建边缘节点失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.put("/api/edge/nodes/{node_id}")
async def edge_nodes_update_handler(request: web.Request):
    """更新边缘节点配置属性"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足：无法修改其他租户的边缘节点"}, status=403)

        data = await request.json()
        update_kwargs = {}
        for k in ("node_name", "ip", "port", "ssh_host", "ssh_port", "ssh_user", "ssh_password", "domain", "use_ssl", "allow_shared_pool", "status", "target_dc_id", "assigned_bot_token", "assigned_bot_username", "allow_bot_pool"):
            if k in data:
                update_kwargs[k] = data[k]

        updated = db.update_edge_node(node_id, **update_kwargs)
        try:
            from edge_node_manager import broadcast_edge_node_update
            await broadcast_edge_node_update(node_id)
        except Exception:
            pass
        return web.json_response({"success": True, "node": updated})
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"更新边缘节点失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.delete("/api/edge/nodes/{node_id}")
async def edge_nodes_delete_handler(request: web.Request):
    """解绑并删除边缘节点"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足：无法删除其他租户的边缘节点"}, status=403)

        target_uid = node.get("tenant_id")
        db.delete_edge_node(node_id)
        try:
            from edge_node_manager import broadcast_edge_node_deleted
            await broadcast_edge_node_deleted(node_id, target_user_id=target_uid)
        except Exception:
            pass
        return web.json_response({"success": True, "message": "边缘节点已成功解绑并移除"})
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"删除边缘节点失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/nodes/{node_id}/ssh-deploy")
async def edge_nodes_ssh_deploy_handler(request: web.Request):
    """触发边缘节点异步 SSH 自动化纳管部署"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id, include_secrets=True)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足"}, status=403)

        try:
            data = await request.json()
        except Exception:
            data = {}

        update_fields = {}
        for k in ("ssh_host", "ssh_port", "ssh_user", "ssh_password", "ip", "port", "domain", "use_ssl"):
            if k in data and data[k] is not None and str(data[k]) != "":
                update_fields[k] = data[k]
        if update_fields:
            node = db.update_edge_node(node_id, include_secrets=True, **update_fields)

        if not node.get("ssh_password_enc"):
            return web.json_response({"success": False, "error": "该节点未保存 SSH 密码，请重新输入 root 密码后启动纳管"}, status=400)

        import vps_deployer
        master_url = _resolve_master_base_url(request, data.get("master_url", ""))
        clear_pwd = bool(data.get("clear_password_on_success", False))
        vps_deployer.start_background_ssh_deploy(
            node_id=node_id,
            master_url=master_url,
            clear_password_on_success=clear_pwd,
        )
        return web.json_response({
            "success": True,
            "message": "SSH 自动化部署流水线已在后台启动",
            "node": db.get_edge_node_by_id(node_id),
        })
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"启动 SSH 部署失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/edge/nodes/{node_id}/deploy-logs")
async def edge_nodes_deploy_logs_handler(request: web.Request):
    """轮询边缘节点 SSH 纳管部署实时日志"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足"}, status=403)

        return web.json_response({
            "success": True,
            "node_id": node_id,
            "node_name": node.get("node_name"),
            "status": node.get("status"),
            "deploy_log": node.get("deploy_log") or "",
            "has_ssh_password": node.get("has_ssh_password", False),
        })
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"获取节点部署日志失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/nodes/{node_id}/clear-ssh-password")
async def edge_nodes_clear_password_handler(request: web.Request):
    """安全擦除已保存在数据库中的 SSH root 密码"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足"}, status=403)

        db.clear_edge_node_ssh_password(node_id)
        return web.json_response({
            "success": True,
            "message": "已安全清除保存的 SSH 密码",
            "node": db.get_edge_node_by_id(node_id),
        })
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"清除 SSH 密码失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/nodes/{node_id}/test")
async def edge_nodes_test_handler(request: web.Request):
    """主动测试边缘节点的连通性与响应延迟"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足"}, status=403)

        import vps_deployer
        res = await vps_deployer.check_edge_node_health(node_id)
        return web.json_response({
            "success": True,
            "result": res,
            "node": db.get_edge_node_by_id(node_id),
        })
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"测试边缘节点健康度失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/nodes/{node_id}/benchmark/dcs")
async def edge_nodes_benchmark_dcs_handler(request: web.Request):
    """测试边缘节点到 Telegram 5 大官方数据中心的延迟矩阵"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足"}, status=403)

        import vps_deployer
        res = await vps_deployer.run_edge_dcs_benchmark(node_id)
        return web.json_response(res)
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"边缘节点 DC 延迟测速异常: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/nodes/{node_id}/benchmark/tg-speed")
async def edge_nodes_benchmark_tg_speed_handler(request: web.Request):
    """测试边缘节点直接从 Telegram DC 拉取媒体分片的下载/推流速率"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足"}, status=403)

        body = {}
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}
        except Exception:
            body = {}

        sample_mb = float(body.get("sample_size_mb", 10.0))
        chat_id = int(body.get("chat_id", 0))
        message_id = int(body.get("message_id", 0))

        import vps_deployer
        res = await vps_deployer.run_edge_tg_speed_benchmark(
            node_id, sample_mb=sample_mb, chat_id=chat_id, message_id=message_id
        )
        return web.json_response(res)
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"边缘节点拉流测速异常: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/nodes/{node_id}/diagnostics")
async def edge_nodes_diagnostics_handler(request: web.Request):
    """获取边缘节点宿主机硬件环境、并发配置与 Telegram 守护状态体检"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足"}, status=403)

        import vps_deployer
        res = await vps_deployer.run_edge_diagnostics(node_id)
        return web.json_response(res)
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"边缘节点体检诊断异常: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/edge/speedtest/stream")
async def edge_speedtest_stream_handler(request: web.Request):
    """
    供边缘推流节点并发拉取高速流式数据，用于测量主控 ↔ 边缘 VPS 之间的专线物理带宽。
    支持 ?size_mb=15 参数控制测速包大小。
    """
    try:
        size_mb = 15.0
        try:
            size_mb = float(request.query.get("size_mb", 15.0))
        except Exception:
            pass
        size_mb = max(1.0, min(size_mb, 100.0))
        total_bytes = int(size_mb * 1024 * 1024)

        chunk = b"MISTRELAY_EDGE_SPEEDTEST_PAYLOAD_" * 2048  # 64KB
        response = web.StreamResponse(status=200, headers={
            "Content-Type": "application/octet-stream",
            "Content-Length": str(total_bytes),
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "X-Benchmark-Speedtest": "true",
        })
        await response.prepare(request)
        sent = 0
        while sent < total_bytes:
            step = min(len(chunk), total_bytes - sent)
            await response.write(chunk[:step])
            sent += step
        return response
    except Exception as e:
        logger.debug(f"Speedtest stream error: {e}")
        return web.Response(status=500)


@routes.post("/api/edge/speedtest/upload")
async def edge_speedtest_upload_handler(request: web.Request):
    """
    供边缘推流节点高速流式推送上行数据，用于测量边缘 VPS 往主控/公网的上行出网带宽。
    """
    try:
        t0 = time.perf_counter()
        bytes_received = 0
        reader = request.content
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            bytes_received += len(chunk)
        elapsed = max(0.001, time.perf_counter() - t0)
        speed_mb_s = round((bytes_received / (1024 * 1024)) / elapsed, 2)
        speed_mbps = round(speed_mb_s * 8, 2)
        return web.json_response({
            "success": True,
            "bytes_received": bytes_received,
            "duration_s": round(elapsed, 3),
            "speed_mb_s": speed_mb_s,
            "speed_mbps": speed_mbps,
        })
    except Exception as e:
        logger.error(f"边缘测速上传异常: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post(r"/api/edge/nodes/{node_id:\d+}/benchmark/bandwidth")
async def edge_nodes_benchmark_bandwidth_handler(request: web.Request):
    """测试边缘 VPS 的物理宽带吞吐（Anycast CDN + Master 链路流式混合双测）"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足"}, status=403)

        import vps_deployer
        res = await vps_deployer.run_edge_bandwidth_benchmark(node_id)
        return web.json_response(res)
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"边缘节点物理宽带测速异常: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post(r"/api/edge/nodes/{node_id:\d+}/benchmark/relay-stream")
async def edge_nodes_benchmark_relay_stream_handler(request: web.Request):
    """发起端到端真实全双工中继流播压测（边拉取边推流，测量真实体感流速与链路瓶颈）"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足"}, status=403)

        sample_mb = 25.0
        if request.can_read_body:
            try:
                body = await request.json()
                sample_mb = float(body.get("sample_size_mb", 25.0))
            except Exception:
                pass

        import vps_deployer
        res = await vps_deployer.run_edge_relay_stream_benchmark(node_id, sample_mb=sample_mb)
        return web.json_response(res)
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"端到端中继流播压测异常: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/nodes/{node_id}/benchmark/full")
async def edge_nodes_benchmark_full_handler(request: web.Request):
    """一键执行边缘节点全能综合测速与深度体检，结果自动持久化入库"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足"}, status=403)

        body = {}
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}
        except Exception:
            body = {}

        sample_mb = float(body.get("sample_size_mb", 10.0))

        import vps_deployer
        res = await vps_deployer.run_edge_full_benchmark(node_id, sample_mb=sample_mb)
        return web.json_response(res)
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"边缘节点综合测速异常: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/nodes/{node_id}/upgrade")
async def edge_nodes_upgrade_handler(request: web.Request):
    """通过 OTA 热更新或 SSH 自动为边缘节点升级最新 Edge Worker 代码并重启"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足"}, status=403)

        master_url = _resolve_master_base_url(request)
        import vps_deployer
        res = await vps_deployer.upgrade_edge_worker(node_id, master_url=master_url)
        return web.json_response(res)
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"升级边缘节点服务异常: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/nodes/generate-token")
async def edge_nodes_generate_token_handler(request: web.Request):
    """生成免密一键脚本安装配对 Token 与终端安装指令"""
    try:
        current_uid, is_admin = _get_request_edge_auth_context(request)
        data = await request.json()
        node_name = str(data.get("node_name") or "Edge Worker").strip()
        domain = str(data.get("domain") or "").strip()
        port = int(data.get("port") or 8090)
        use_ssl = bool(data.get("use_ssl"))
        allow_shared_pool = bool(data.get("allow_shared_pool"))
        expires_minutes = int(data.get("expires_minutes") or 60)

        if is_admin and data.get("tenant_id"):
            tenant_id = int(data["tenant_id"])
        else:
            tenant_id = int(current_uid if current_uid is not None else 1)

        tok = db.create_edge_node_token(
            tenant_id=tenant_id,
            node_name=node_name,
            domain=domain,
            port=port,
            use_ssl=use_ssl,
            allow_shared_pool=allow_shared_pool,
            expires_minutes=expires_minutes,
        )
        master_url = _resolve_master_base_url(request, data.get("master_url", ""))
        install_url = f"{master_url}/api/edge/install.sh?token={tok['token']}"
        command = f"curl -sSL \"{install_url}\" | bash"

        return web.json_response({
            "success": True,
            "token": tok["token"],
            "token_info": tok,
            "install_url": install_url,
            "command": command,
        })
    except Exception as e:
        logger.error(f"生成边缘节点安装 Token 失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/edge/tokens/{token}/status")
async def edge_token_status_handler(request: web.Request):
    """查询一键安装 Token 的配对核销状态"""
    try:
        token = request.match_info["token"]
        tok_info = db.get_edge_node_token(token)
        if not tok_info:
            return web.json_response({"success": False, "error": "Token 不存在"}, status=404)
        node = None
        if tok_info.get("node_id"):
            node = db.get_edge_node_by_id(int(tok_info["node_id"]))
        return web.json_response({
            "success": True,
            "token_info": tok_info,
            "node": node,
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/edge/install.sh")
async def edge_serve_install_sh_handler(request: web.Request):
    """动态渲染并下发一键自动化安装 Shell 脚本"""
    token = request.query.get("token", "").strip()
    tok_info = db.get_edge_node_token(token)
    if not tok_info or tok_info.get("expired") or tok_info.get("used"):
        err_sh = "#!/bin/bash\necho -e \"\\033[31m[ERROR] 配对 Token 无效、已过期或已被使用，请在面板重新生成！\\033[0m\"\nexit 1\n"
        return web.Response(text=err_sh, content_type="text/x-shellscript", status=400)

    import vps_deployer
    master_url = _resolve_master_base_url(request)
    script = vps_deployer.render_install_sh(
        master_url=master_url,
        token=token,
        port=int(tok_info.get("port") or 8090),
    )
    return web.Response(text=script, content_type="text/x-shellscript")


@routes.get("/api/edge/worker-script")
async def edge_serve_worker_script_handler(request: web.Request):
    """下发最新版的 worker_server.py 核心脚本源码"""
    import vps_deployer
    code = vps_deployer.get_worker_script_content()
    return web.Response(text=code, content_type="text/x-python")


@routes.get("/api/edge/config")
async def edge_node_config_handler(request: web.Request):
    """供边缘节点启动时同步 MTProto API 与 DC 原生机器人凭证"""
    secret = (
        request.headers.get("X-Node-Secret", "").strip()
        or request.query.get("secret", "").strip()
    )
    node = db.get_edge_node_by_secret(secret, include_secrets=True)
    if not node:
        return web.json_response({"success": False, "error": "Invalid node secret"}, status=401)

    import edge_node_manager
    allocation = edge_node_manager.allocate_bots_for_edge_node(node)

    # 自动同步节点目标 DC 与分配的 Bot 用户名
    need_db_update = {}
    if allocation.get("target_dc") and allocation.get("target_dc") != node.get("target_dc_id"):
        need_db_update["target_dc_id"] = allocation["target_dc"]
    if allocation.get("primary_bot_username") and allocation.get("primary_bot_username") != node.get("assigned_bot_username"):
        need_db_update["assigned_bot_username"] = allocation["primary_bot_username"]
    if need_db_update:
        try:
            db.update_edge_node(node["id"], **need_db_update)
        except Exception:
            pass

    return web.json_response({
        "success": True,
        "config": {
            "node_id": node["id"],
            "node_name": node["node_name"],
            "tenant_id": node["tenant_id"],
            "api_id": Var.API_ID,
            "api_hash": Var.API_HASH,
            "target_dc": allocation["target_dc"],
            "bot_token": allocation["primary_bot_token"],
            "bot_username": allocation.get("primary_bot_username", ""),
            "bot_tokens": allocation.get("bot_tokens", []),
            "dc_bot_map": allocation.get("dc_bot_map", {}),
            "allow_bot_pool": allocation.get("allow_bot_pool", True),
            "master_bot_token": allocation.get("master_bot_token", ""),
            "master_bot_username": allocation.get("master_bot_username", ""),
            "primary_session_string": allocation.get("primary_session_string", ""),
            "bot_session_strings": allocation.get("bot_session_strings", []),
            "dc_session_map": allocation.get("dc_session_map", {}),
            "master_session_string": allocation.get("master_session_string", ""),
            "initial_tenant_bytes": {
                str(t.get("tenant_id")): int(t.get("total_bytes") or 0)
                for t in (node.get("metrics") or {}).get("tenants", [])
                if isinstance(t, dict) and t.get("tenant_id") is not None
            } if isinstance((node.get("metrics") or {}).get("tenants"), list) else {},
        },
    })


@routes.get("/api/edge/bots-pool")
async def edge_bots_pool_handler(request: web.Request):
    """查询全集群 80 个 Bot 的元数据大清单，支持按 DC 筛选和关键字搜索"""
    user_payload = request.get("user") if hasattr(request, "get") else None
    if not user_payload:
        return web.json_response({"success": False, "error": "未登录"}, status=401)

    search_q = request.query.get("search", "").strip()
    dc_id_str = request.query.get("dc_id", "").strip()
    dc_id = int(dc_id_str) if (dc_id_str and dc_id_str.isdigit()) else None

    import edge_node_manager
    catalog = edge_node_manager.get_cluster_bots_catalog(search_query=search_q, dc_id=dc_id)
    return web.json_response({
        "success": True,
        "bots": catalog,
        "total": len(catalog),
    })


@routes.post(r"/api/edge/nodes/{node_id:\d+}/reassign-bot")
async def edge_nodes_reassign_bot_handler(request: web.Request):
    """一键为边缘节点重新分配物理最优 DC 的原生 Bot，并可触发 OTA 热重载"""
    try:
        node_id = int(request.match_info["node_id"])
        node = db.get_edge_node_by_id(node_id, include_secrets=True)
        if not node:
            return web.json_response({"success": False, "error": "节点不存在"}, status=404)
        if not _check_edge_node_permission(request, node):
            return web.json_response({"success": False, "error": "权限不足"}, status=403)

        body = {}
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}
        except Exception:
            body = {}

        mode = body.get("mode")
        if mode == "auto":
            # 智能自动模式：清除已绑定的指定 token
            db.update_edge_node(node_id, assigned_bot_token="")
            node["assigned_bot_token"] = ""
            target_dc_id = body.get("target_dc_id")
            if target_dc_id not in (None, "", 0, "0"):
                target_dc_val = int(target_dc_id)
                db.update_edge_node(node_id, target_dc_id=target_dc_val)
                node["target_dc_id"] = target_dc_val
            else:
                db.update_edge_node(node_id, target_dc_id=None)
                node["target_dc_id"] = None
        else:
            # 手动或默认模式
            assigned_token = body.get("assigned_bot_token")
            if assigned_token is not None:
                assigned_token_str = str(assigned_token).strip()
                db.update_edge_node(node_id, assigned_bot_token=assigned_token_str)
                node["assigned_bot_token"] = assigned_token_str
            target_dc_id = body.get("target_dc_id")
            if target_dc_id is not None:
                target_dc_val = int(target_dc_id) if target_dc_id not in (0, "0", "") else None
                db.update_edge_node(node_id, target_dc_id=target_dc_val)
                node["target_dc_id"] = target_dc_val

        if "allow_bot_pool" in body:
            allow_pool_val = bool(body["allow_bot_pool"])
            db.update_edge_node(node_id, allow_bot_pool=1 if allow_pool_val else 0)
            node["allow_bot_pool"] = allow_pool_val

        # 解析请求的 Bot 数量或依据实测宽带动态匹配
        requested_bot_count = None
        if "bot_count" in body and body["bot_count"] not in (None, ""):
            try:
                requested_bot_count = int(body["bot_count"])
            except Exception:
                pass
        elif body.get("auto_match_bandwidth"):
            bench_data = node.get("benchmark_data") or {}
            if isinstance(bench_data, str):
                try: bench_data = json.loads(bench_data)
                except Exception: bench_data = {}
            bw_sec = bench_data.get("bandwidth") or {}
            down_spd = bw_sec.get("down_speed_mb_s") or bench_data.get("link", {}).get("down_speed_mb_s")
            up_spd = bw_sec.get("up_speed_mb_s")
            eff_spd = bw_sec.get("effective_bw_mb_s")
            fastest_dc = bench_data.get("fastest_dc") or {}
            dc_rtt = fastest_dc.get("avg_rtt_ms") or fastest_dc.get("rtt_ms")
            sys_info = bench_data.get("diagnostics", {}).get("system") or {}
            mem_mb = float(sys_info.get("mem_total_mb") or 0.0)
            auto_cap = 100 if mem_mb >= 1500 else 24
            import edge_node_manager
            requested_bot_count = edge_node_manager.calculate_recommended_bots(
                down_speed_mb_s=down_spd,
                up_speed_mb_s=up_spd,
                effective_bw_mb_s=eff_spd,
                max_cap=auto_cap,
                rtt_ms=dc_rtt,
            )

        if requested_bot_count is not None:
            db.update_edge_node(node_id, target_bot_count=requested_bot_count)
            node["target_bot_count"] = requested_bot_count

        import edge_node_manager
        allocation = edge_node_manager.allocate_bots_for_edge_node(node, requested_bot_count=requested_bot_count)
        db.update_edge_node(
            node_id,
            target_dc_id=allocation["target_dc"],
            assigned_bot_username=allocation.get("primary_bot_username", ""),
            target_bot_count=allocation.get("target_bot_count"),
        )

        ota_triggered = False
        ota_result = None
        if body.get("trigger_ota", True) and node.get("status") == "online":
            import vps_deployer
            reconfig_res = await vps_deployer.reconfigure_edge_worker(node_id)
            if reconfig_res.get("success"):
                ota_result = reconfig_res
                ota_triggered = True
            else:
                master_url = _resolve_master_base_url(request)
                ota_result = await vps_deployer.upgrade_edge_worker(node_id, master_url=master_url)
                ota_triggered = True

        updated_node = db.get_edge_node_by_id(node_id)
        try:
            from edge_node_manager import broadcast_edge_node_update
            await broadcast_edge_node_update(node_id)
        except Exception:
            pass
        return web.json_response({
            "success": True,
            "message": f"已成功为节点重新分配 DC{allocation['target_dc']} 原生 Bot: @{allocation.get('primary_bot_username', 'unknown')}",
            "allocation": allocation,
            "node": updated_node,
            "ota_triggered": ota_triggered,
            "ota_result": ota_result,
        })
    except ValueError:
        return web.json_response({"success": False, "error": "无效的节点 ID"}, status=400)
    except Exception as e:
        logger.error(f"重新分配边缘节点 Bot 异常: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/nodes/register-with-token")
async def edge_register_with_token_handler(request: web.Request):
    """一键安装脚本执行期间向 Master 注册节点并换取持久化 auth_secret"""
    try:
        data = await request.json()
        token = str(data.get("token") or "").strip()
        ip = str(data.get("ip") or request.remote or "").strip()
        port = int(data.get("port") or 8090)

        node = db.verify_and_consume_edge_node_token(token=token, ip=ip, port=port)
        if not node:
            return web.json_response(
                {"success": False, "error": "配对 Token 无效、已过期或已被使用"},
                status=400,
            )

        try:
            from edge_node_manager import broadcast_edge_node_update
            from WebStreamer.server.ws_manager import ws_manager
            await broadcast_edge_node_update(node["id"])
            await ws_manager.send_edge_token_used(token=token, node_data=node, target_user_id=node.get("tenant_id"))
        except Exception:
            pass

        return web.json_response({
            "success": True,
            "node_id": node["id"],
            "node_name": node["node_name"],
            "auth_secret": node["auth_secret"],
            "port": node["port"],
            "domain": node.get("domain") or "",
            "use_ssl": bool(node.get("use_ssl")),
        })
    except Exception as e:
        logger.error(f"Token 注册边缘节点失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/nodes/heartbeat")
async def edge_node_heartbeat_handler(request: web.Request):
    """接收边缘推流节点的定时心跳与负载指标上报"""
    try:
        data = await request.json()
        secret = (
            str(data.get("secret") or "").strip()
            or request.headers.get("X-Node-Secret", "").strip()
        )
        node = db.get_edge_node_by_secret(secret, include_secrets=True)
        if not node:
            return web.json_response({"success": False, "error": "Invalid node secret"}, status=401)

        incoming_metrics = data.get("metrics") or {}
        merged_metrics = dict(node.get("metrics") or {})
        if isinstance(incoming_metrics, dict):
            if "tenants" in incoming_metrics:
                raw_tenants = incoming_metrics.get("tenants")
                existing_tenants = merged_metrics.get("tenants")
                from edge_node_manager import merge_node_tenants_metrics
                enriched = merge_node_tenants_metrics(existing_tenants, raw_tenants, node.get("tenant_id"))
                incoming_metrics["tenants"] = enriched
            merged_metrics.update(incoming_metrics)

        now_str = datetime.now(timezone.utc).isoformat()
        update_kwargs = {
            "status": "online",
            "metrics": merged_metrics,
            "last_seen_at": now_str,
        }
        if data.get("port"):
            update_kwargs["port"] = int(data["port"])
        if data.get("bot_username"):
            update_kwargs["assigned_bot_username"] = str(data["bot_username"]).strip()
        if data.get("home_dc") and not node.get("target_dc_id"):
            update_kwargs["target_dc_id"] = int(data["home_dc"])
        if not node.get("ip") and request.remote and request.remote not in ("127.0.0.1", "::1"):
            update_kwargs["ip"] = request.remote

        db.update_edge_node(node["id"], **update_kwargs)
        try:
            from edge_node_manager import broadcast_edge_node_update
            await broadcast_edge_node_update(node["id"])
        except Exception:
            pass
        return web.json_response({
            "success": True,
            "node_id": node["id"],
            "status": "online",
        })
    except Exception as e:
        logger.error(f"处理边缘节点心跳失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/edge/available-nodes")
async def edge_available_nodes_handler(request: web.Request):
    """获取当前租户可用于视频播放与下载分流的边缘节点列表（含实测 DC 延迟与网段延迟缓存）"""
    try:
        from edge_node_manager import extract_routing_client_ip, edge_latency_router
        current_uid, is_admin = _get_request_edge_auth_context(request)
        client_ip = extract_routing_client_ip(request)
        nodes = db.get_available_edge_nodes_for_user(
            tenant_id=current_uid,
            is_admin=is_admin,
            include_secrets=True,
        )
        missing_probe_nodes = []
        result = []
        for n in nodes:
            node_ip = (n.get("ip") or "").strip()
            domain = (n.get("domain") or "").strip()
            if not domain and node_ip:
                domain = db.get_default_edge_domain(node_ip)
            port = int(n.get("port") or 8090)
            use_ssl = bool(n.get("use_ssl"))
            if domain:
                scheme = "https" if use_ssl else "http"
                netloc = domain if port in (80, 443) else f"{domain}:{port}"
            elif node_ip:
                scheme = "http"
                netloc = f"{node_ip}:{port}"
            else:
                netloc = ""

            ping_url = f"{scheme}://{netloc}/ping" if netloc else ""
            stream_base_url = f"{scheme}://{netloc}/stream" if netloc else ""

            is_dedicated = bool(current_uid and int(n.get("tenant_id") or 0) == int(current_uid))
            bench = n.get("benchmark_data") or {}
            raw_fastest = bench.get("fastest_dc")
            fastest_dc = raw_fastest if isinstance(raw_fastest, dict) and raw_fastest.get("name") else None

            cached_entry = edge_latency_router.get_cached_entry(client_ip, n["id"])
            if not cached_entry and n.get("status") == "online":
                missing_probe_nodes.append(n)

            result.append({
                "id": n["id"],
                "node_name": n["node_name"],
                "domain": domain,
                "ip": node_ip,
                "port": port,
                "use_ssl": use_ssl,
                "status": n.get("status", "offline"),
                "is_dedicated": is_dedicated,
                "allow_shared_pool": bool(n.get("allow_shared_pool")),
                "active_streams": int((n.get("metrics") or {}).get("active_streams", 0)),
                "fastest_dc": fastest_dc,
                "dcs": bench.get("dcs") or [],
                "target_dc_id": n.get("target_dc_id"),
                "assigned_bot_username": n.get("assigned_bot_username") or "",
                "allow_bot_pool": bool(n.get("allow_bot_pool", True)),
                "ping_url": ping_url,
                "stream_base_url": stream_base_url,
                "rtt_ms": cached_entry["rtt_ms"] if cached_entry else None,
            })

        if missing_probe_nodes:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(edge_latency_router.probe_nodes_for_ip(client_ip, missing_probe_nodes))
            except RuntimeError:
                pass

        return web.json_response({
            "success": True,
            "nodes": result,
            "client_ip": client_ip,
        })
    except Exception as e:
        logger.error(f"获取可用边缘节点列表失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/client-latency")
async def edge_client_latency_report_handler(request: web.Request):
    """接收客户端前端上报的边缘节点实测 HTTP 延迟，存入网段路由缓存"""
    try:
        from edge_node_manager import extract_routing_client_ip, edge_latency_router
        client_ip = extract_routing_client_ip(request)
        data = await request.json()
        latencies = data.get("latencies") or []
        recorded = 0
        if isinstance(latencies, list):
            for item in latencies:
                if isinstance(item, dict) and "node_id" in item and "rtt_ms" in item:
                    try:
                        nid = int(item["node_id"])
                        rtt = float(item["rtt_ms"])
                        if rtt > 0:
                            edge_latency_router.record_client_latency(
                                client_ip=client_ip,
                                node_id=nid,
                                rtt_ms=rtt,
                                source="browser",
                            )
                            recorded += 1
                    except (ValueError, TypeError):
                        continue

        return web.json_response({
            "success": True,
            "recorded": recorded,
            "client_ip": client_ip,
        })
    except Exception as e:
        logger.error(f"上报客户端边缘延迟失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/edge/resolve-stream-url")
async def resolve_edge_stream_url_handler(request: web.Request):
    """
    预解析流媒体直链（供前端网盘播放器、复制直链、外部播放器与下载直连边缘节点）：
    接收 message_id、hash、preferred_node、download；
    若命中边缘节点，直接签发 Ticket 并返回 Edge Worker 终端直链；
    若指定 direct 或无可用边缘节点，返回 Master 主控直出链接。
    """
    try:
        data = await request.json()
        message_id = data.get("message_id")
        if not message_id:
            return web.json_response({"success": False, "error": "缺少 message_id 参数"}, status=400)
        try:
            message_id = int(message_id)
        except (ValueError, TypeError):
            return web.json_response({"success": False, "error": "无效的 message_id"}, status=400)

        secure_hash = data.get("hash")
        preferred_node = data.get("preferred_node")
        download = bool(data.get("download"))

        # 查询数据库媒体记录
        try:
            source_record = get_tg_media_record_by_message_id(message_id, secure_hash=secure_hash, hash_len=Var.HASH_LENGTH)
        except TypeError:
            source_record = get_tg_media_record_by_message_id(message_id)

        if not source_record:
            return web.json_response({"success": False, "error": "未找到指定媒体记录"}, status=404)

        source_unique_id = source_record.get("file_unique_id", "")
        raw_unique_id = source_unique_id.split("@")[0] if source_unique_id else ""
        if not secure_hash and raw_unique_id:
            secure_hash = utils.get_hash(raw_unique_id, Var.HASH_LENGTH)

        record_chat_id = source_record.get("chat_id") or Var.BIN_CHANNEL

        # 尝试通过边缘节点调度器解析
        from edge_node_manager import resolve_edge_stream_info
        edge_info = resolve_edge_stream_info(
            request=request,
            message_id=message_id,
            secure_hash=secure_hash,
            source_record=source_record,
            record_chat_id=record_chat_id,
            preferred_node_override=preferred_node,
            force_download=download,
        )

        if edge_info and edge_info.get("is_edge") and edge_info.get("url"):
            return web.json_response({
                "success": True,
                "url": edge_info["url"],
                "node_id": edge_info.get("node_id"),
                "node_name": edge_info.get("node_name"),
                "is_edge": True,
            })

        # 回退主控直出直链
        scheme = "https" if (request.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https") else "http"
        host = request.headers.get("Host") or getattr(Var, "FQDN", "") or "127.0.0.1:8080"
        raw_name = get_download_file_name(source_record)
        safe_name = quote(raw_name, safe="")
        master_params = [f"hash={secure_hash}", "direct=1"]
        if download:
            master_params.append("download=1")
        master_url = f"{scheme}://{host}/{message_id}/{safe_name}?" + "&".join(master_params)

        return web.json_response({
            "success": True,
            "url": master_url,
            "node_id": None,
            "node_name": "主控服务器 (直出)",
            "is_edge": False,
        })
    except Exception as e:
        logger.error(f"解析流媒体直链失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)



# ==========================================
# Telegram AI 客服管理与控制 API
# ==========================================

@routes.get("/api/telegram/customer-service/status")
async def telegram_customer_service_status_handler(request: web.Request):
    """获取 Telegram AI 客服机器人的当前状态、群组权限、配置与会话监控"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        from ai_customer_service import get_ai_cs_bot
        bot = get_ai_cs_bot()
        overview = await bot.get_status_overview()
        return web.json_response({
            "success": True,
            **overview
        })
    except Exception as e:
        logger.error(f"获取 AI 客服状态失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/customer-service/config")
async def telegram_customer_service_config_handler(request: web.Request):
    """更新 AI 客服机器人的业务配置并执行热重载"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        import db
        from ai_customer_service import get_ai_cs_bot
        data = await request.json()

        field_map = {
            "enabled": ("AI_CS_ENABLED", "bool", "是否启用 AI 客服功能"),
            "bot_token": ("AI_CS_BOT_TOKEN", "string", "AI 客服机器人 Token"),
            "bot_username": ("AI_CS_BOT_USERNAME", "string", "AI 客服机器人用户名"),
            "target_chat": ("AI_CS_TARGET_CHAT", "string", "AI 客服监听的目标群组"),
            "group_trigger_mode": ("AI_CS_GROUP_TRIGGER_MODE", "string", "群聊触发模式"),
            "private_enabled": ("AI_CS_PRIVATE_ENABLED", "bool", "是否启用客服Bot私聊回复"),
            "api_base": ("AI_CS_API_BASE", "string", "AI 客服 LLM Base URL"),
            "api_key": ("AI_CS_API_KEY", "string", "AI 客服 LLM API Key"),
            "model": ("AI_CS_MODEL", "string", "AI 客服使用的模型名称"),
            "system_prompt": ("AI_CS_SYSTEM_PROMPT", "string", "AI 客服业务 System Prompt"),
            "temperature": ("AI_CS_TEMPERATURE", "string", "AI 客服采样温度"),
            "max_tokens": ("AI_CS_MAX_TOKENS", "string", "AI 客服最大生成 Token 数"),
        }

        updated_count = 0
        for key, (cfg_key, val_type, desc) in field_map.items():
            if key in data:
                val = data[key]
                if val_type == "bool":
                    val = bool(val)
                elif val_type == "string":
                    val = str(val).strip()
                db.set_config(cfg_key, val, value_type=val_type, category="ai_cs", description=desc)
                updated_count += 1

        bot = get_ai_cs_bot()
        await bot.reload_config()

        return web.json_response({
            "success": True,
            "message": f"成功保存 {updated_count} 项客服配置并已热重载生效",
            "running": bot.is_running
        })
    except Exception as e:
        logger.error(f"保存 AI 客服配置失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/customer-service/actions")
async def telegram_customer_service_actions_handler(request: web.Request):
    """执行 AI 客服生命周期与运行控制操作 (start, stop, restart, clear_history)"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        from ai_customer_service import get_ai_cs_bot
        data = await request.json()
        action = str(data.get("action") or "").strip().lower()
        bot = get_ai_cs_bot()

        if action == "start":
            await bot.start()
            msg = "AI 客服 Bot 启动完成"
        elif action == "stop":
            await bot.stop()
            msg = "AI 客服 Bot 已平稳停止"
        elif action == "restart":
            await bot.stop()
            await asyncio.sleep(0.6)
            await bot.start()
            msg = "AI 客服 Bot 重启完成"
        elif action == "clear_history":
            bot.clear_history()
            msg = "客服会话记忆窗口已清空"
        else:
            return web.json_response({"success": False, "error": f"未知动作指令: {action}"}, status=400)

        overview = await bot.get_status_overview()
        return web.json_response({
            "success": True,
            "message": msg,
            **overview
        })
    except Exception as e:
        logger.error(f"执行 AI 客服动作失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/customer-service/test-chat")
async def telegram_customer_service_test_chat_handler(request: web.Request):
    """在管理端在线测试 LLM 回复与测速"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        from ai_customer_service import get_ai_cs_bot, sanitize_outbound_response
        data = await request.json()
        query = str(data.get("query") or "").strip()
        if not query:
            return web.json_response({"success": False, "error": "测试提问内容不能为空"}, status=400)

        bot = get_ai_cs_bot()
        ok, reply, latency_ms = await bot.call_llm_direct(
            user_query=query,
            system_prompt=data.get("system_prompt"),
            model=data.get("model"),
            api_base=data.get("api_base"),
            api_key=data.get("api_key"),
            temperature=data.get("temperature"),
            max_tokens=data.get("max_tokens"),
        )

        safe_reply = sanitize_outbound_response(reply) if ok and reply else reply

        return web.json_response({
            "success": ok,
            "reply": safe_reply,
            "latency_ms": latency_ms,
            "model": data.get("model") or bot.model,
            "error": None if ok else reply
        })
    except Exception as e:
        logger.error(f"执行客服沙箱测试对话失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/telegram/customer-service/auto-mint")
async def telegram_customer_service_auto_mint_handler(request: web.Request):
    """一键联动协议号铸造新客服 Bot 并拉群"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        from ai_customer_service import auto_mint_cs_bot
        data = await request.json() if request.can_read_body else {}
        display_name = str(data.get("display_name") or "MistRelay 智能客服").strip()
        target_chat = data.get("target_chat")
        account_id = data.get("account_id")
        if account_id is not None:
            try:
                account_id = int(account_id)
            except (ValueError, TypeError):
                account_id = None

        result = await auto_mint_cs_bot(
            display_name=display_name,
            target_chat=target_chat,
            account_id=account_id
        )
        return web.json_response({
            "success": True,
            **result
        })
    except Exception as e:
        logger.error(f"自动铸造客服 Bot 失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)




@routes.get("/api/telegram/tenant/backup/export")
async def tenant_backup_export_handler(request: web.Request):
    """租户导出个人网盘资产独立备份（包含媒体索引、关联频道、下载历史）"""
    user_payload = request.get("user") if hasattr(request, "get") else None
    if not user_payload:
        return web.json_response({"success": False, "error": "未登录"}, status=401)
    
    uid = user_payload.get("uid")
    if user_payload.get("role") == "admin" and request.query.get("user_id"):
        try:
            uid = int(request.query.get("user_id"))
        except (ValueError, TypeError):
            pass

    if not uid:
        return web.json_response({"success": False, "error": "无效的用户标识"}, status=400)

    import backup_manager
    try:
        data = await asyncio.to_thread(backup_manager.export_tenant_data, uid)
        safe_username = data.get("tenant", {}).get("username", "tenant")
        filename = f"tenant_backup_{safe_username}_{int(time.time())}.json"
        body_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return web.Response(
            body=body_bytes,
            content_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )
    except ValueError as ve:
        return web.json_response({"success": False, "error": str(ve)}, status=404)
    except Exception as e:
        logger.error(f"导出租户数据失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"导出失败: {e}"}, status=500)


@routes.get("/api/system/tenants/{id}/export")
async def admin_export_tenant_data_handler(request: web.Request):
    """管理员导出指定租户的独立数据备份归档"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        user_id = int(request.match_info["id"])
        import backup_manager
        data = await asyncio.to_thread(backup_manager.export_tenant_data, user_id)
        safe_username = data.get("tenant", {}).get("username", f"user_{user_id}")
        filename = f"tenant_backup_{safe_username}_{int(time.time())}.json"
        body_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return web.Response(
            body=body_bytes,
            content_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )
    except ValueError as ve:
        return web.json_response({"success": False, "error": str(ve)}, status=404)
    except Exception as e:
        logger.error(f"管理员导出租户数据失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": f"导出租户数据失败: {e}"}, status=500)


@routes.post("/api/system/tenants/heal-orphans")
async def admin_heal_orphans_handler(request: web.Request):
    """管理员一键扫描并自愈历史孤儿媒体资产"""
    if not _require_admin_user(request):
        return web.json_response({"success": False, "error": "权限不足"}, status=403)
    try:
        import db
        result = await asyncio.to_thread(db.heal_orphaned_tenant_media)
        return web.json_response({
            "success": True,
            "message": f"孤儿资产自愈完成！共恢复 {result.get('total_files_restored', 0)} 个历史媒体文件。",
            "data": result,
        })
    except Exception as e:
        logger.error(f"自愈孤儿媒体资产失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


# Keep this catch-all route last. aiohttp matches registered routes in order, so
# registering it before later /api routes would make those API endpoints
# unreachable.
routes.get(r"/{path:.+}", allow_head=True)(stream_handler)
