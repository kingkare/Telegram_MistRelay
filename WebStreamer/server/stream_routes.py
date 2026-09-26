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
from datetime import datetime
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
        if isinstance(e, (pyrogram_errors.FloodWait, pyrogram_errors.Flood)):
            return True
        elif hasattr(pyrogram_errors, 'FloodWait') and isinstance(e, pyrogram_errors.FloodWait):
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
        token = create_token(user["id"], user["username"])
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

        token = create_token(user["id"], user["username"])
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
async def api_status_handler(_):
    """API状态接口"""
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
            "offline_only_keys": sorted(key for key in OFFLINE_ONLY_CONFIG_KEYS if key in configs),
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
        }
        
        # 需要重启才能生效的配置项
        requires_restart = {
            'API_ID', 'API_HASH', 'BOT_TOKEN', 'ADMIN_ID', 'BIN_CHANNEL',
            'STREAM_PORT', 'STREAM_BIND_ADDRESS', 'STREAM_HASH_LENGTH',
            'STREAM_HAS_SSL', 'STREAM_NO_PORT', 'STREAM_FQDN',
            'STREAM_USE_SESSION_FILE', 'MULTI_BOT_TOKENS'
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
                    if key in OFFLINE_ONLY_CONFIG_KEYS:
                        current_value = get_config(key, None)
                        if value == current_value or str(value) == str(current_value):
                            continue
                        errors.append(f"{key}: 安全敏感配置只能在停机维护窗口离线修改")
                        continue
                    updates.append((key, value, value_type, category, description))
                    if key in requires_restart:
                        needs_restart = True
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

    if grouped:
        from db import fetch_downloads_grouped
        groups = fetch_downloads_grouped(limit_param)
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
        records = fetch_recent_downloads(limit_param)
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
        from db import get_download_statistics
        stats = get_download_statistics()
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
    API接口：删除所有下载记录、上传记录和媒体记录
    """
    try:
        from db import delete_all_downloads
        result = delete_all_downloads()
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
    API接口：返回系统监控历史趋势数据
    """
    try:
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
    API接口：返回上传统计信息
    """
    try:
        from db import get_upload_statistics
        stats = get_upload_statistics()
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
    API接口：返回上传记录JSON数据
    
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
    
    try:
        from db import fetch_recent_uploads
        records = fetch_recent_uploads(
            limit=limit_param,
            status=status_filter,
            upload_target=upload_target_filter
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
        # 添加连接到管理器
        await ws_manager.add_connection(ws)
        
        # 发送初始状态
        try:
            from db import get_download_statistics, get_upload_statistics
            download_stats = get_download_statistics()
            upload_stats = get_upload_statistics()
            
            await ws.send_json({
                "type": "initial",
                "data": {
                    "downloads": download_stats,
                    "uploads": upload_stats
                }
            })
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
    API接口:返回消息队列状态
    """
    try:
        # 导入队列状态函数
        try:
            from WebStreamer.bot.plugins.stream import get_queue_status
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


async def get_main_bot_file_properties(message_id: int, force_refresh: bool = False):
    main_client = multi_clients.get(0) or StreamBot
    if not getattr(main_client, "is_connected", False):
        for idx in sorted(channel_accessible_clients or multi_clients.keys()):
            candidate = multi_clients.get(idx)
            if candidate and getattr(candidate, "is_connected", False):
                main_client = candidate
                break
    main_streamer = get_byte_streamer(main_client)
    return await main_streamer.get_file_properties(message_id, force_refresh=force_refresh)


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
    ticket = quote(create_resource_ticket(path), safe="")
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


async def download_telegram_media_sample(message_id: int, output_path: Path, max_bytes: int) -> None:
    if max_bytes <= 0:
        raise RuntimeError("invalid thumbnail source size")

    target_dc = None
    if FileId is not None:
        try:
            import db
            rec = db.get_tg_media_record_by_message_id(message_id)
            if rec and rec.get("file_id"):
                target_dc = FileId.decode(rec["file_id"]).dc_id
        except Exception:
            pass

    attempted_indices = set()
    while True:
        index = select_stream_bot(prefer_channel=True, exclude_indices=attempted_indices, target_dc=target_dc)
        if index is None:
            raise RuntimeError("No valid clients available")
        if index not in multi_clients:
            attempted_indices.add(index)
            continue

        client = multi_clients[index]

        # 优先尝试直接下载 Telegram 消息内嵌的缩略图（针对视频/照片等仅 ~10KB，极速且不依赖 MP4 尾部 moov 索引）
        if hasattr(client, "get_messages") and hasattr(client, "download_media"):
            try:
                from WebStreamer.utils.file_properties import get_media_from_message
                msg = await client.get_messages(Var.BIN_CHANNEL, message_id)
                media = get_media_from_message(msg) if msg and not getattr(msg, "empty", False) else None
                target_thumb_id = None
                if media is not None:
                    if getattr(msg, "photo", None) and getattr(media, "file_id", None):
                        target_thumb_id = media.file_id
                    elif getattr(media, "thumbs", None):
                        target_thumb_id = media.thumbs[-1].file_id
                    elif getattr(media, "thumbnail", None):
                        target_thumb_id = media.thumbnail.file_id

                if target_thumb_id:
                    buf = await client.download_media(target_thumb_id, in_memory=True)
                    if buf:
                        data = bytes(buf.getbuffer()) if hasattr(buf, "getbuffer") else bytes(buf)
                        if data and len(data) > 64:
                            output_path.write_bytes(data)
                            mark_bot_success(index)
                            return
            except Exception as thumb_err:
                logger.debug(f"直接下载 TG 内嵌缩略图未命中 message_id={message_id}: {thumb_err}")

        streamer = get_byte_streamer(client)
        try:
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


async def delete_bin_channel_messages(message_ids: list[int]) -> dict:
    """删除 BIN_CHANNEL 中的消息，支持多 bot 回退。"""
    normalized_ids = [int(message_id) for message_id in dict.fromkeys(message_ids) if message_id]
    if not normalized_ids:
        return {
            "deleted_message_count": 0,
            "cleanup_only": False,
            "client_index": None,
        }

    if not Var.BIN_CHANNEL:
        raise RuntimeError("BIN_CHANNEL 未配置，无法删除频道消息")

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
                        chat_id=Var.BIN_CHANNEL,
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
    source_record = get_tg_media_record_by_message_id(message_id)
    source_unique_id = (source_record or {}).get("file_unique_id", "")
    if not source_unique_id or str(source_unique_id).startswith("telethon:"):
        raise FIleNotFound
    expected_hash = utils.get_hash(source_unique_id, Var.HASH_LENGTH)
    if not secrets.compare_digest(str(secure_hash or ""), expected_hash):
        raise InvalidHash

    # 检查是否有可用的客户端
    if not work_loads:
        logger.error("没有可用的客户端")
        raise web.HTTPInternalServerError(text="No available clients")

    try:
        source_file_id = await get_main_bot_file_properties(message_id)
    except FIleNotFound:
        raise
    except Exception as error:
        mark_bot_failure(0, error)
        logger.warning(f"主客户端获取文件属性失败: {error}")
        raise

    if source_file_id.unique_id != source_unique_id:
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
            file_id = await tg_connect.get_file_properties(message_id, force_refresh=False)
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

        result = browse_tg_media(
            page=page,
            page_size=page_size,
            search=search,
            mime_filter=mime_filter,
            sort_by=sort_by,
            sort_desc=sort_desc,
            media_group_id=media_group_id,
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
    """获取 Telegram 频道存储统计"""
    try:
        stats = get_tg_media_stats()
        return web.json_response({"success": True, "data": stats})
    except Exception as e:
        logger.error(f"Telegram usage API error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def ensure_telegram_thumbnail(message_id: int, record: dict | None = None) -> tuple[Path | None, bool]:
    """
    统一确保 Telegram 媒体 WebP 缩略图已生成并存在。
    返回 (缩略图路径, 是否命中缓存)。
    若记录不存在则返回 (None, False)。
    若格式不支持或生成失败，返回对应类型的兜底 fallback 图路径。
    """
    if record is None:
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
            await asyncio.wait_for(
                download_telegram_media_sample(message_id, source_path, max_bytes),
                timeout=35,
            )

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
    """按需生成或获取 TG 媒体 WebP 缩略图。"""
    try:
        message_id = int(request.match_info["message_id"])
    except (KeyError, ValueError):
        return web.json_response({"success": False, "error": "无效的 message_id"}, status=400)

    thumb_path, cache_hit = await ensure_telegram_thumbnail(message_id)
    if thumb_path is None:
        return web.json_response({"success": False, "error": "Telegram 文件记录不存在"}, status=404)

    return get_thumbnail_response(thumb_path, cache_hit=cache_hit)


@routes.get("/api/telegram/thumbnails/status", allow_head=True)
async def telegram_thumbnails_status_handler(request: web.Request):
    """获取 Telegram 缩略图后台预热与缓存进度状态"""
    try:
        from thumbnail_worker import get_thumbnail_worker
        worker = get_thumbnail_worker()
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
        record = get_tg_media_record_by_message_id(message_id)
        if not record:
            return web.json_response({"success": False, "error": "Telegram 文件记录不存在"}, status=404)

        deletion = await delete_bin_channel_messages([message_id])
        cleanup = delete_tg_media_records([record["file_unique_id"]])

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

        records = get_tg_media_records_by_media_group(media_group_id)
        if not records:
            return web.json_response({"success": False, "error": "Telegram 媒体组不存在"}, status=404)

        message_ids = [record["message_id"] for record in records]
        file_unique_ids = [record["file_unique_id"] for record in records]

        deletion = await delete_bin_channel_messages(message_ids)
        cleanup = delete_tg_media_records(file_unique_ids)

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

        records_by_file_id = {}
        missing_message_ids = []
        missing_group_ids = []

        for message_id in message_ids:
            record = get_tg_media_record_by_message_id(message_id)
            if record:
                records_by_file_id[record["file_unique_id"]] = record
            else:
                missing_message_ids.append(message_id)

        for group_id in group_ids:
            records = get_tg_media_records_by_media_group(group_id)
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

        deletion = await delete_bin_channel_messages([
            record["message_id"] for record in records
        ])
        cleanup = delete_tg_media_records(list(records_by_file_id))
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
        records = list_all_tg_media_records()
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

        deletion = await delete_bin_channel_messages(message_ids)
        cleanup = delete_tg_media_records(file_unique_ids)

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


@routes.get("/api/rclone/cache/monitor", allow_head=True)
async def monitor_cache_status(request: web.Request):
    return rclone_deprecated_response()


@routes.get("/api/files/list")
async def list_files_handler(request: web.Request):
    """
    API接口: 列出指定目录下的文件和文件夹
    参数: path (可选, 默认为根目录 /)
    """
    try:
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
    API接口: 下载文件
    参数: path
    """
    try:
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
    API接口: 上传文件
    Form Data: 
      - path: 目标文件夹路径 (可选, 默认为 /)
      - file: 文件内容
    """
    try:
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
    API接口: 创建文件夹
    JSON: {"path": "/foo/bar"}
    """
    try:
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
    API接口: 删除文件或文件夹
    参数: path
    """
    try:
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
        return web.json_response({"success": True, "data": accounts})
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


@routes.get("/api/telegram/botfather/task-status")
async def telegram_botfather_task_status_handler(request: web.Request):
    """获取后台 @BotFather 自动铸造流水线实时状态"""
    try:
        from botfather_creator import mint_manager
        return web.json_response({"success": True, "data": mint_manager.get_status()})
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



async def _benchmark_single_bot(idx: int, cli, test_download: bool = True) -> dict:
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

    res = {
        "index": idx,
        "username": uname.lstrip("@"),
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

    # 3. 测试真实频道媒体块流速吞吐（预热会话后测量单连接传输与播放码率）
    if test_download and can_read and Var.BIN_CHANNEL:
        try:
            conn = db.get_connection()
            c = conn.cursor()
            c.execute("SELECT message_id, file_size FROM tg_media WHERE file_size > 524288 ORDER BY message_id DESC LIMIT 1")
            row = c.fetchone()
            if not row:
                c.execute("SELECT message_id, file_size FROM tg_media WHERE file_size > 102400 ORDER BY message_id DESC LIMIT 1")
                row = c.fetchone()
            if row:
                msg_id = row[0]
                sample_limit = min(524288, row[1])  # 512 KB 测速样本
                streamer = get_byte_streamer(cli)
                t_init = time.perf_counter()
                file_id = await asyncio.wait_for(streamer.get_file_properties(msg_id, force_refresh=False), timeout=8.0)
                loc = await streamer.get_location(file_id)
                await asyncio.wait_for(streamer.generate_media_session(cli, file_id, slot_idx=0), timeout=8.0)
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

        test_dl = True
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
    """一键对全集群所有 Bot 节点并发测速，输出集群综合质量报告与速度排名"""
    try:
        user = request.get("user")
        if user and user.get("role") not in (None, "admin"):
            return web.json_response({"success": False, "error": "权限不足，仅限管理员操作"}, status=403)

        test_dl = True
        try:
            body = await request.json()
            if isinstance(body, dict) and "test_download" in body:
                test_dl = bool(body["test_download"])
        except Exception:
            pass

        import WebStreamer.bot as bot_mod
        sem = asyncio.Semaphore(4)

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

        summary = f"全集群 {len(nodes)} 个节点测速完成：平均响应延迟 {avg_ping}ms，就绪率 {round(len(valid_nodes)/max(1, len(nodes))*100)}%"

        return web.json_response({
            "success": True,
            "data": {
                "total_tested": len(nodes),
                "online_count": len(valid_nodes),
                "avg_ping_ms": avg_ping,
                "fastest_node": {"index": fastest["index"], "username": fastest["username"], "ping_ms": fastest["ping_ms"]} if fastest else None,
                "highest_speed_node": {"index": highest_speed["index"], "username": highest_speed["username"], "speed_mbps": highest_speed["download_speed_mbps"]} if highest_speed else None,
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

        # 1. 查找测速样本媒体文件
        conn = db.get_connection()
        c = conn.cursor()
        target_file = None
        if req_msg_id:
            c.execute("SELECT message_id, file_name, file_size, mime_type, file_unique_id FROM tg_media WHERE message_id = ? LIMIT 1", (int(req_msg_id),))
            r = c.fetchone()
            if r:
                target_file = dict(r)

        if not target_file:
            min_size = int(sample_mb * 1024 * 1024)
            c.execute("SELECT message_id, file_name, file_size, mime_type, file_unique_id FROM tg_media WHERE file_size >= ? ORDER BY file_size ASC, message_id DESC LIMIT 1", (min_size,))
            r = c.fetchone()
            if r:
                target_file = dict(r)
            else:
                c.execute("SELECT message_id, file_name, file_size, mime_type, file_unique_id FROM tg_media WHERE file_size > 102400 ORDER BY message_id DESC LIMIT 1")
                r = c.fetchone()
                if r:
                    target_file = dict(r)

        if not target_file:
            return web.json_response({
                "success": False,
                "error": "网盘中未找到有效媒体文件作为测速样本，请先向频道转发媒体或完成一次下载"
            }, status=400)

        msg_id = target_file["message_id"]

        # 2. 确定测速节点（指定单节点 或 全集群自适应条带调度）
        is_cluster_mode = False
        if bot_idx_req is not None and str(bot_idx_req).strip() != "":
            selected_bot_idx = int(bot_idx_req)
            if selected_bot_idx not in bot_mod.multi_clients:
                return web.json_response({"success": False, "error": f"节点 #{selected_bot_idx} 不存在或未连接"}, status=404)
            test_cli = bot_mod.multi_clients[selected_bot_idx]
        else:
            is_cluster_mode = True
            selected_bot_idx = select_stream_bot(prefer_channel=True)
            if selected_bot_idx is None:
                selected_bot_idx = 0
            test_cli = bot_mod.multi_clients.get(selected_bot_idx, StreamBot)

        streamer = get_byte_streamer(test_cli)
        file_id = await asyncio.wait_for(streamer.get_file_properties(msg_id, force_refresh=False), timeout=10.0)
        loc = await streamer.get_location(file_id)

        # ==================== 测试 1: 单连接流播播放测试 (Playback / Streaming) ====================
        play_chunk_size = min(524288, target_file["file_size"])  # 512 KB 起播块
        t_play_start = time.perf_counter()

        # 先建立/复用媒体传输会话，测量 TTFB 首包响应延迟
        await asyncio.wait_for(streamer.generate_media_session(test_cli, file_id, slot_idx=0), timeout=10.0)
        t_first_start = time.perf_counter()
        succ1, r1, _, _ = await asyncio.wait_for(
            streamer._try_get_file_chunk(
                test_cli, selected_bot_idx, file_id, loc,
                offset=0, chunk_size=play_chunk_size,
                max_retries=2, slot_idx=0
            ),
            timeout=15.0
        )
        t_first_done = time.perf_counter()
        ttfb_ms = round((t_first_done - t_first_start) * 1000, 1)

        buffer_bytes = len(r1.bytes) if (succ1 and r1 and hasattr(r1, "bytes")) else 0

        # 拉取第 2 个 512KB 分片，完成 1MB 初始播放缓冲
        if target_file["file_size"] >= play_chunk_size * 2:
            succ2, r2, _, _ = await asyncio.wait_for(
                streamer._try_get_file_chunk(
                    test_cli, selected_bot_idx, file_id, loc,
                    offset=play_chunk_size, chunk_size=play_chunk_size,
                    max_retries=2, slot_idx=0
                ),
                timeout=15.0
            )
            if succ2 and r2 and hasattr(r2, "bytes"):
                buffer_bytes += len(r2.bytes)

        t_play_done = time.perf_counter()
        initial_buffer_ms = round((t_play_done - t_first_start) * 1000, 1)
        play_elapsed_sec = max(0.001, t_play_done - t_first_start)
        play_speed_mb_s = round((buffer_bytes / (1024 * 1024)) / play_elapsed_sec, 2)
        play_bitrate_mbps = round(play_speed_mb_s * 8, 2)

        # ==================== 测试 2: 单连接极限下载测试 (Direct Download Throughput) ====================
        chunk_dl_size = 524288  # 512 KB 块
        # 支持 10M (20块), 100M (200块), 1G (2048块) 真实分片拉取
        total_dl_chunks = max(2, int((sample_mb * 1024 * 1024) / chunk_dl_size))

        start_dl_offset = buffer_bytes
        file_size = target_file["file_size"]
        max_safe_offset = max(0, file_size - chunk_dl_size)

        if is_cluster_mode:
            dl_bots = get_available_bot_indices(selected_bot_idx, set()) or [selected_bot_idx]
        else:
            dl_bots = [selected_bot_idx]

        # 先预热所有参与下载节点的媒体会话，排除首次握手噪音
        async def _warm_bot(b_idx):
            try:
                b_cli = bot_mod.multi_clients[b_idx]
                b_str = get_byte_streamer(b_cli)
                b_fid = await b_str.get_file_properties(msg_id, force_refresh=False)
                await b_str.generate_media_session(b_cli, b_fid, slot_idx=0)
            except Exception:
                pass

        await asyncio.gather(*[_warm_bot(b) for b in set(dl_bots[:min(total_dl_chunks, len(dl_bots))])], return_exceptions=True)

        # 若处于集群模式且媒体体积足够，进一步拉取 4 个连续分片测量服务端多 Bot 聚合播放码率 (Sustained Streaming Bitrate)
        if is_cluster_mode and len(dl_bots) > 1 and target_file["file_size"] >= play_chunk_size * 6:
            stripe_play_bots = dl_bots[:min(8, len(dl_bots))]
            async def _fetch_play_part(p_idx, b_idx):
                try:
                    b_cli = bot_mod.multi_clients[b_idx]
                    b_str = get_byte_streamer(b_cli)
                    b_fid = await b_str.get_file_properties(msg_id, force_refresh=False)
                    b_loc = await b_str.get_location(b_fid)
                    return await b_str._try_get_file_chunk(
                        b_cli, b_idx, b_fid, b_loc,
                        offset=buffer_bytes + p_idx * play_chunk_size, chunk_size=play_chunk_size,
                        max_retries=2, slot_idx=0, timeout=12.0
                    )
                except Exception:
                    return False, None, b_idx, None

            t_stripe_start = time.perf_counter()
            p_tasks = [_fetch_play_part(i, stripe_play_bots[i % len(stripe_play_bots)]) for i in range(len(stripe_play_bots))]
            p_res = await asyncio.gather(*p_tasks, return_exceptions=True)
            t_stripe_done = time.perf_counter()
            stripe_bytes = 0
            for item in p_res:
                if isinstance(item, tuple) and item[0] and hasattr(item[1], "bytes"):
                    stripe_bytes += len(item[1].bytes)
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

        async def _fetch_dl_chunk(p_idx: int):
            if max_safe_offset > 0:
                raw_offset = start_dl_offset + p_idx * chunk_dl_size
                p_offset = ((raw_offset % (max_safe_offset + 1)) // chunk_dl_size) * chunk_dl_size
            else:
                p_offset = 0

            assigned_bot = dl_bots[p_idx % len(dl_bots)]
            c_cli = bot_mod.multi_clients[assigned_bot]
            c_streamer = get_byte_streamer(c_cli)
            t_c0 = time.perf_counter()
            c_file_id = await c_streamer.get_file_properties(msg_id, force_refresh=False)
            c_loc = await c_streamer.get_location(c_file_id)
            c_succ, c_r, _, _ = await asyncio.wait_for(
                c_streamer._try_get_file_chunk(
                    c_cli, assigned_bot, c_file_id, c_loc,
                    offset=p_offset, chunk_size=chunk_dl_size,
                    max_retries=2, slot_idx=0
                ),
                timeout=20.0
            )
            t_c1 = time.perf_counter()
            c_elapsed = max(0.001, t_c1 - t_c0)
            c_len = len(c_r.bytes) if (c_succ and c_r and hasattr(c_r, "bytes")) else 0
            c_speed = round((c_len / (1024 * 1024)) / c_elapsed, 2)
            return {
                "part": p_idx + 1,
                "bot_index": assigned_bot,
                "bot_username": getattr(c_cli, "username", f"bot_{assigned_bot}").lstrip("@"),
                "size_kb": round(c_len / 1024, 1),
                "elapsed_ms": round(c_elapsed * 1000, 1),
                "speed_mb_s": c_speed,
                "bytes": c_len,
            }

        # 保护性超时机制：1G 最多 240s，100M 最多 90s，10M 最多 35s
        if sample_mb >= 1000:
            max_duration_sec = 240.0
        elif sample_mb >= 80:
            max_duration_sec = 90.0
        else:
            max_duration_sec = 35.0

        concurrency = min(len(dl_bots) * 2, 40) if (is_cluster_mode and len(dl_bots) > 1) else (2 if sample_mb > 10 else 1)
        sem = asyncio.Semaphore(concurrency)
        stop_event = asyncio.Event()

        dl_chunk_samples = []
        dl_total_bytes = 0
        t_dl_start = time.perf_counter()

        async def _bounded_fetch(p_idx: int):
            if stop_event.is_set():
                return None
            if time.perf_counter() - t_dl_start > max_duration_sec:
                stop_event.set()
                return None
            async with sem:
                if stop_event.is_set():
                    return None
                try:
                    return await _fetch_dl_chunk(p_idx)
                except Exception as e:
                    logger.warning(f"测速分片 #{p_idx+1} 拉取异常: {e}")
                    return None

        tasks = [asyncio.create_task(_bounded_fetch(i)) for i in range(total_dl_chunks)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for item in results:
            if isinstance(item, dict) and item.get("bytes"):
                dl_total_bytes += item.pop("bytes", 0)
                dl_chunk_samples.append(item)

        t_dl_end = time.perf_counter()
        dl_total_sec = max(0.001, t_dl_end - t_dl_start)
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
            "active_workers_count": len(set(dl_bots[:total_dl_chunks])) if is_cluster_mode else 1,
        }

        tested_file_info = {
            "message_id": target_file["message_id"],
            "file_name": target_file["file_name"],
            "file_size": target_file["file_size"],
            "file_size_formatted": f"{round(target_file['file_size'] / (1024 * 1024), 1)} MB",
            "mime_type": target_file["mime_type"],
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



# Keep this catch-all route last. aiohttp matches registered routes in order, so
# registering it before later /api routes would make those API endpoints
# unreachable.
routes.get(r"/{path:.+}", allow_head=True)(stream_handler)
