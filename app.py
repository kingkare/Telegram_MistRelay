import pyrogram_patch
import asyncio
import datetime
import logging
import re
import shutil
from typing import Any

# 在所有其他模块之前初始化日志系统（控制台 + 文件双输出）
from log_config import setup_logging, cleanup_old_logs
setup_logging(level=logging.INFO)

import python_socks

from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
import coloredlogs
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.types import BotCommand, BotCommandScopeDefault, Message

from async_aria2_client import AsyncAria2Client
from db import init_db
from download_cleanup import start_download_cleanup_loop
from service_runtime import set_service_ready
from configer import (
    API_ID, API_HASH, PROXY_IP, PROXY_PORT, BOT_TOKEN, ADMIN_ID, RPC_SECRET, RPC_URL,
    ENABLE_STREAM
)
from util import get_file_name, progress, byte2_readable, hum_convert

coloredlogs.install(level='INFO')
log = logging.getLogger('bot')

# 导入直链功能（默认启用，作为TG媒体文件下载的前置功能）
stream_server = None
StreamBot = None
Var = None
utils = None
web = None
web_server = None
initialize_clients = None

if ENABLE_STREAM:
    try:
        from aiohttp import web
        from WebStreamer.server import web_server
        from WebStreamer.bot.clients import initialize_clients, StreamBot
        from WebStreamer import Var, utils
        from WebStreamer.bot import multi_clients, work_loads, channel_accessible_clients
        # 导入上传负载（从async_aria2_client模块）
        try:
            from async_aria2_client import upload_work_loads
        except Exception:
            upload_work_loads = {}
    except ImportError as e:
        log.warning(f"直链功能导入失败: {e}，将禁用直链功能")
        ENABLE_STREAM = False
        multi_clients = {}
        work_loads = {}
        channel_accessible_clients = set()
        upload_work_loads = {}
else:
    multi_clients = {}
    work_loads = {}
    channel_accessible_clients = set()
    upload_work_loads = {}

# 如果RPC_URL中的主机名不是localhost或IP地址，则在Docker环境中使用localhost
url_parts = RPC_URL.split(':')
host = url_parts[0]
if not (host == 'localhost' or host == '127.0.0.1' or all(c.isdigit() or c == '.' for c in host)):
    # 在Docker环境中，使用localhost
    host = 'localhost'
    port_path = ':'.join(url_parts[1:])
    docker_rpc_url = f"{host}:{port_path}"
    log.info(f"在Docker环境中使用本地RPC URL: {docker_rpc_url}")
else:
    docker_rpc_url = RPC_URL

import os as _os
_sessions_dir = _os.environ.get("MISTRELAY_SESSION_DIR", "/app/db/sessions")
_os.makedirs(_sessions_dir, mode=0o700, exist_ok=True)
_telethon_bot_id = str(BOT_TOKEN or "default").split(":", 1)[0]
_telethon_session_path = _os.path.join(_sessions_dir, f"telethon_bot_{_telethon_bot_id}")

proxy = (python_socks.ProxyType.HTTP, PROXY_IP, PROXY_PORT) if PROXY_IP is not None else None
bot = TelegramClient(_telethon_session_path, API_ID, API_HASH, proxy=proxy)
client = AsyncAria2Client(RPC_SECRET, f'ws://{docker_rpc_url}', bot)

# 将aria2客户端设置为全局变量，供直链功能使用
aria2_client = client


def _is_authorized_tg_user(sender_id: int) -> bool:
    if not sender_id:
        return False
    try:
        if ADMIN_ID and int(sender_id) == int(ADMIN_ID):
            return True
    except (ValueError, TypeError):
        pass
    if Var and Var.ALLOWED_USERS and str(sender_id) in Var.ALLOWED_USERS:
        return True
    try:
        import db
        u = db.get_user_by_tg_id(int(sender_id))
        return bool(u)
    except Exception:
        return False


@bot.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def handle_private_message(event):
    """
    处理 Telegram 私聊消息：
    - 所有指令 (如 /start, /help, /register) 均由 Pyrogram StreamBot 统一响应并自动清除历史残留键盘
    - 支持授权用户直接发送 HTTP 链接、磁力链接 (magnet:) 或种子文件 (.torrent) 投递 Aria2 下载
    """
    sender_id = event.sender_id
    if not _is_authorized_tg_user(sender_id):
        return

    text = (event.raw_text or "").strip()

    # 指令由 Pyrogram StreamBot 统一处理并清除客户端旧版键盘，Telethon 忽略
    if text.startswith("/"):
        return

    log.info(
        "%s: authorized private message received from %s (length=%d, media=%s)",
        datetime.datetime.now(datetime.timezone.utc).isoformat(),
        sender_id,
        len(text),
        bool(event.media),
    )

    # 查询发送者绑定的租户账号与专属频道
    import db
    db_u = None
    try:
        db_u = db.get_user_by_tg_id(int(sender_id))
    except Exception:
        pass

    is_admin = False
    try:
        if ADMIN_ID and int(sender_id) == int(ADMIN_ID):
            is_admin = True
    except (ValueError, TypeError):
        pass
    if db_u and db_u.get("role") == "admin":
        is_admin = True

    # 非管理员普通租户若未分配专属存储频道，禁止投递下载，避免文件无处存放或物理流入公用频道
    if not is_admin:
        if not db_u or not db_u.get("bin_channel_id"):
            log.warning("拒绝未分配专属存储频道的普通租户投递下载任务 sender_id=%s", sender_id)
            await event.reply(
                "⚠️ 您尚未开通或绑定专属存储频道，无法接收转存文件。\n"
                "请先使用 /register 完成注册开通专属空间后再试。"
            )
            return

    user_id = db_u["id"] if db_u else None
    target_channel_id = db_u.get("bin_channel_id") if db_u else None
    if is_admin and not target_channel_id:
        try:
            target_channel_id = int(Var.BIN_CHANNEL) if getattr(Var, "BIN_CHANNEL", None) else None
        except (ValueError, TypeError):
            target_channel_id = getattr(Var, "BIN_CHANNEL", None)

    # 1. 磁力链接下载 (支持 40位Hex、32位Base32、混排文本及附加参数)
    magnet_matches = list(dict.fromkeys(re.findall(
        r'magnet:\?xt=urn:btih:(?:[0-9a-fA-F]{40,64}|[2-7a-zA-Z]{32})(?:&[^\s<>"\'`]+)?',
        text,
        flags=re.IGNORECASE,
    )))
    if magnet_matches:
        for magnet_uri in magnet_matches:
            res = await client.add_uri(
                uris=[magnet_uri],
            )
            gid = res.get("result") if isinstance(res, dict) else None
            if gid:
                try:
                    db.create_download(
                        file_unique_id=f"aria2_{gid}",
                        gid=gid,
                        source_url=magnet_uri,
                        user_id=user_id,
                        target_channel_id=target_channel_id,
                    )
                except Exception as db_err:
                    log.error("创建磁力下载记录关联租户失败 gid=%s: %s", gid, db_err)
    # 2. HTTP 链接下载
    elif text.startswith("http"):
        url_arr = [u.strip() for u in text.split("\n") if u.strip()]
        # 过滤掉 Telegram 链接（由 Pyrogram 频道采集器/直链功能处理，避免误入 Aria2）
        aria2_urls = [
            u for u in url_arr
            if not re.search(r"(?:https?://)?(?:t\.me|telegram\.me)/", u, re.IGNORECASE)
        ]
        if aria2_urls:
            for url in aria2_urls:
                res = await client.add_uri(
                    uris=[url],
                )
                gid = res.get("result") if isinstance(res, dict) else None
                if gid:
                    try:
                        db.create_download(
                            file_unique_id=f"aria2_{gid}",
                            gid=gid,
                            source_url=url,
                            user_id=user_id,
                            target_channel_id=target_channel_id,
                        )
                    except Exception as db_err:
                        log.error("创建下载记录关联租户失败 gid=%s: %s", gid, db_err)
        if not aria2_urls:
            log.debug("检测到 Telegram 频道/帖子链接，跳过 Aria2，交由 Pyrogram 采集器处理")
            return
    # 3. 种子文件处理
    elif event.media:
        if hasattr(event.media, "document") and event.media.document:
            if event.media.document.mime_type == "application/x-bittorrent":
                await event.reply("📥 已收到种子文件，正在解析并添加到 Aria2 离线下载队列...")
                path = await bot.download_media(event.message)
                res = await client.add_torrent(path)
                gid = res.get("result") if isinstance(res, dict) else None
                if gid:
                    try:
                        db.create_download(
                            file_unique_id=f"aria2_{gid}",
                            gid=gid,
                            source_url=f"torrent:{os.path.basename(path)}",
                            user_id=user_id,
                            target_channel_id=target_channel_id,
                        )
                    except Exception as db_err:
                        log.error("创建种子下载记录关联租户失败 gid=%s: %s", gid, db_err)
            else:
                log.debug("媒体文件由Pyrogram直链功能处理，Telethon跳过")
                return
        else:
            log.debug("媒体文件由Pyrogram直链功能处理，Telethon跳过")
            return


@events.register(events.CallbackQuery)
async def BotCallbackHandler(event):
    if int(event.sender_id or 0) != int(ADMIN_ID):
        await event.answer("Unauthorized", alert=True)
        return
    d = str(event.data, encoding="utf-8")
    [type, gid] = d.split('.', 1)
    if type == 'pause-task':
        await client.pause(gid)
    elif type == 'unpause-task':
        await client.unpause(gid)
    elif type == 'del-task':
        data = await client.remove(gid)
        if 'error' in data:
            error_msg = (
                f'❌ <b>操作失败</b>\n\n'
                f'⚠️ <b>错误信息:</b>\n<code>{data["error"]["message"]}</code>'
            )
            await bot.send_message(ADMIN_ID, error_msg, parse_mode='html')
        else:
            success_msg = (
                f'✅ <b>删除成功</b>\n\n'
                f'🗑️ 任务已从下载队列中移除'
            )
            await bot.send_message(ADMIN_ID, success_msg, parse_mode='html')


# 入口
async def main():
    set_service_ready(False)
    # 初始化本地 SQLite 数据库（用于记录下载与媒体信息）
    try:
        init_db()
        log.info("本地下载数据库初始化完成")
        from db import ensure_default_admin
        ensure_default_admin()
    except Exception as e:
        log.error(f"初始化本地下载数据库失败，拒绝继续启动: {e}")
        raise

    # 启动日志定时清理任务（每小时检查一次，删除超过 24 小时的日志）
    async def _log_cleanup_loop():
        while True:
            await asyncio.sleep(3600)
            cleanup_old_logs()

    asyncio.create_task(_log_cleanup_loop())
    start_download_cleanup_loop(client, log)

    await client.connect()
    bot.add_event_handler(BotCallbackHandler)

    async def _init_telethon_bot():
        await bot.start(bot_token=BOT_TOKEN)
        bot_me = await bot.get_me()
        commands = [
            BotCommand(command="start", description='启动云盘服务并查看绑定状态'),
            BotCommand(command="register", description='获取注册验证码 / 查看专属存储频道'),
            BotCommand(command="help", description='查看使用指南与功能说明'),
        ]
        await bot(
            SetBotCommandsRequest(
                scope=BotCommandScopeDefault(),
                lang_code='',
                commands=commands
            )
        )
        log.info(f'{bot_me.username} bot启动成功...')

    try:
        await _init_telethon_bot()
    except Exception as e:
        wait_match = re.search(r'wait of (\d+)', str(e), re.IGNORECASE) or re.search(r'(\d+)\s*seconds?', str(e), re.IGNORECASE)
        if wait_match or 'FloodWait' in type(e).__name__:
            wait_sec = int(wait_match.group(1)) if wait_match else 300
            log.warning(f'Telethon 主 Bot 登录遇到 FloodWait ({wait_sec}s)，转入后台延迟启动，不阻塞 Web 与直链多 Bot 服务...')
            async def _delayed_telethon():
                await asyncio.sleep(wait_sec + 5)
                try:
                    await _init_telethon_bot()
                except Exception as ex:
                    log.error(f'后台延迟启动 Telethon 主 Bot 失败: {ex}')
            asyncio.create_task(_delayed_telethon())
        else:
            raise
    
    # 启动直链功能（默认启用，作为TG媒体文件下载的前置功能）
    if ENABLE_STREAM and StreamBot is not None:
        try:
            log.info('正在启动直链功能（作为TG媒体文件前置处理）...')
            
            # 启动系统监控
            from monitor import monitor
            monitor.start()

            # 先启动Web服务器（独立于Telegram初始化，避免被限流阻塞）
            global stream_server
            if web and web_server:
                try:
                    # 配置 aiohttp 日志记录器，将协议级错误降级为 DEBUG
                    aiohttp_logger = logging.getLogger('aiohttp.server')
                    
                    # 创建自定义过滤器来过滤协议级错误（BadStatusLine / BadHttpMessage / PRI 等）
                    class BadRequestFilter(logging.Filter):
                        _NOISE_KEYWORDS = (
                            'BadStatusLine', 'BadHttpMessage', 'Invalid method',
                            'PRI', 'Pause on PRI',
                        )
                        _NOISE_EXC_TYPES = ('BadStatusLine', 'BadHttpMessage')

                        def filter(self, record):
                            msg = str(record.getMessage())
                            if any(kw in msg for kw in self._NOISE_KEYWORDS):
                                record.levelno = logging.DEBUG
                                record.levelname = 'DEBUG'
                                return True
                            if hasattr(record, 'exc_info') and record.exc_info:
                                exc_type = record.exc_info[0]
                                if exc_type:
                                    name = getattr(exc_type, '__name__', str(exc_type))
                                    if any(t in name for t in self._NOISE_EXC_TYPES):
                                        record.levelno = logging.DEBUG
                                        record.levelname = 'DEBUG'
                                        return True
                            return True
                    
                    aiohttp_logger.addFilter(BadRequestFilter())
                    
                    # 在启动Web服务器之前，先设置aria2客户端（确保路由可以访问）
                    try:
                        from WebStreamer.bot.plugins.stream import set_aria2_client
                        set_aria2_client(client)
                        log.info('已提前设置aria2客户端到直链功能（Web服务器启动前）')
                    except Exception as e:
                        log.warning(f'提前设置aria2客户端失败: {e}')
                    
                    # Nginx keeps a query/path-redacted access log. Disable aiohttp's
                    # raw request log so thumbnail tickets and stream capabilities
                    # are not persisted a second time.
                    stream_server = web.AppRunner(web_server(), access_log=None)
                    await stream_server.setup()
                    
                    # 支持IPv6双栈：如果绑定地址是0.0.0.0，同时绑定IPv6
                    if Var.BIND_ADDRESS == "0.0.0.0":
                        site_ipv4 = web.TCPSite(stream_server, "0.0.0.0", Var.PORT)
                        await site_ipv4.start()
                        try:
                            site_ipv6 = web.TCPSite(stream_server, "::", Var.PORT)
                            await site_ipv6.start()
                            log.info(f'Web服务器启动成功（IPv4+IPv6双栈）: {Var.URL}')
                        except OSError as e:
                            log.warning(f'IPv6绑定失败，仅使用IPv4: {e}')
                            log.info(f'Web服务器启动成功（仅IPv4）: {Var.URL}')
                    else:
                        site = web.TCPSite(stream_server, Var.BIND_ADDRESS, Var.PORT)
                        await site.start()
                        log.info(f'Web服务器启动成功: {Var.URL}')
                except Exception as e:
                    log.error(f'启动Web服务器失败: {e}', exc_info=True)
                    raise RuntimeError('Web服务器启动失败') from e
            
            # 配置 Pyrogram 日志级别，屏蔽速率限制等待的警告消息
            # 这些警告是正常的速率限制行为，不需要显示
            pyrogram_session_logger = logging.getLogger('pyrogram.session.session')
            pyrogram_session_logger.setLevel(logging.ERROR)  # 只显示 ERROR 及以上级别
            
            # 配置 Pyrogram 连接传输日志，降低 BrokenPipeError 警告级别
            # 这些错误通常是正常的网络波动，Pyrogram 会自动重连
            pyrogram_transport_logger = logging.getLogger('pyrogram.connection.transport.tcp.tcp')
            pyrogram_transport_logger.setLevel(logging.ERROR)  # 只显示 ERROR 及以上级别
            
            # 过滤 asyncio 的 socket.send() 警告
            asyncio_logger = logging.getLogger('asyncio')
            class BrokenPipeFilter(logging.Filter):
                """过滤 BrokenPipeError 相关的警告"""
                def filter(self, record):
                    msg = str(record.getMessage())
                    if any(keyword in msg for keyword in ['BrokenPipeError', 'Broken pipe', 'socket.send() raised exception']):
                        # 将警告降级为 DEBUG 级别
                        record.levelno = logging.DEBUG
                        record.levelname = 'DEBUG'
                    return True
            asyncio_logger.addFilter(BrokenPipeFilter())
            
            # 过滤 Pyrogram 加密相关的错误（客户端断开连接时的已知问题）
            class EncryptionErrorFilter(logging.Filter):
                """过滤 Pyrogram 加密状态异常的错误，这些通常在客户端断开连接时发生"""
                def filter(self, record):
                    msg = str(record.getMessage())
                    # 过滤加密相关的 TypeError（Value after * must be an iterable）
                    if any(keyword in msg for keyword in [
                        'Value after * must be an iterable',
                        'not NoneType',
                        'Task exception was never retrieved',
                        'handle_packet',
                        'ctr256_encrypt'
                    ]):
                        # 检查是否是加密相关的错误
                        if 'encrypt' in msg.lower() or 'NoneType' in msg:
                            # 将错误降级为 DEBUG 级别，不显示在日志中
                            # 这个错误会在健康检查时自动修复
                            record.levelno = logging.DEBUG
                            record.levelname = 'DEBUG'
                    return True
            asyncio_logger.addFilter(EncryptionErrorFilter())
            
            if not Var or not Var.BIN_CHANNEL:
                log.warning('BIN_CHANNEL未配置，直链功能可能无法正常工作')
            
            # 启动主直链机器人；若主 Bot 遇到 FLOOD_WAIT，转入后台延迟启动，优先初始化 MULTI_BOT_TOKENS
            try:
                await StreamBot.start()
                bot_info = await StreamBot.get_me()
                StreamBot.username = bot_info.username
                log.info(f'直链机器人启动成功: @{bot_info.username}')
                try:
                    from WebStreamer.bot.plugins.stream_modules.media_processor import register_stream_handlers
                    register_stream_handlers(StreamBot)
                except Exception as reg_err:
                    log.warning(f'通过 StreamBot 注册消息处理器失败: {reg_err}')
                try:
                    from pyrogram.types import BotCommand as PyrogramBotCommand
                    await StreamBot.set_bot_commands([
                        PyrogramBotCommand("start", "启动云盘服务并查看绑定状态"),
                        PyrogramBotCommand("register", "获取注册验证码 / 查看专属存储频道"),
                        PyrogramBotCommand("help", "查看使用指南与功能说明"),
                    ])
                    log.info("已通过 StreamBot 同步更新 Telegram 官方指令菜单 (start, register, help)")
                except Exception as cmd_err:
                    log.warning(f"通过 StreamBot 设置指令菜单失败（非致命）: {cmd_err}")
            except Exception as e:
                error_str = str(e)
                error_type = type(e).__name__
                if 'FLOOD_WAIT' in error_str or 'FloodWait' in error_str or 'flood_420' in error_type:
                    wait_match = (
                        re.search(r'(\d+)\s+seconds?', error_str, re.IGNORECASE)
                        or re.search(r'FLOOD_WAIT_X.*?(\d+)', error_str, re.IGNORECASE)
                        or re.search(r'wait of (\d+)', error_str, re.IGNORECASE)
                    )
                    wait_time = int(wait_match.group(1)) if wait_match else 600
                    log.warning(f'主 StreamBot (客户端 0) 遇到 Telegram 限流 ({wait_time}s)，先启动其余多 Bot 客户端，后台等待恢复...')
                    async def _delayed_streambot_start(delay_sec: int):
                        await asyncio.sleep(delay_sec + 5)
                        try:
                            await StreamBot.start()
                            info = await StreamBot.get_me()
                            StreamBot.username = info.username
                            from WebStreamer.bot.plugins.stream_modules.media_processor import register_stream_handlers
                            register_stream_handlers(StreamBot)
                            from WebStreamer.bot.clients import register_primary_streambot
                            await register_primary_streambot()
                            log.info(f'主 StreamBot (客户端 0) 后台恢复启动成功: @{info.username}')
                        except Exception as ex:
                            log.error(f'主 StreamBot 后台延迟启动失败: {ex}')
                    asyncio.create_task(_delayed_streambot_start(wait_time))
                else:
                    raise
            
            # 然后初始化Telegram客户端（可能被限流阻塞）
            await initialize_clients()
            if not channel_accessible_clients:
                raise RuntimeError("没有机器人能够访问配置的 BIN_CHANNEL")
            
            # 将aria2客户端传递给直链功能
            try:
                from WebStreamer.bot.plugins.stream import set_aria2_client
                set_aria2_client(client)
                log.info('已设置aria2客户端到直链功能')
            except Exception as e:
                log.warning(f'设置aria2客户端失败: {e}')
            
            if Var and Var.KEEP_ALIVE and utils:
                asyncio.create_task(utils.ping_server())
            
            auto_download_status = "启用" if (Var and Var.AUTO_DOWNLOAD) else "禁用"
            log.info(f'直链功能已启用，将作为Telegram媒体文件的前置处理')
            log.info(f'自动下载兼容开关: {auto_download_status}')
        except Exception as e:
            log.error(f'启动直链功能失败: {e}', exc_info=True)
            raise RuntimeError('直链功能启动失败') from e

    set_service_ready(True)
    if ENABLE_STREAM:
        try:
            from thumbnail_worker import get_thumbnail_worker
            asyncio.create_task(get_thumbnail_worker().delayed_startup_scan(5.0))
            log.info("已安排后台缩略图自动预热扫描（启动5秒后执行）")
        except Exception as e:
            log.warning(f"安排后台缩略图预热失败: {e}")
        try:
            from botfather_creator import get_keepalive_worker
            get_keepalive_worker().start()
            log.info("已启动 Telegram 协议号后台自动保活巡检 Worker")
        except Exception as e:
            log.warning(f"启动协议号保活 Worker 失败: {e}")
        try:
            from ai_customer_service import get_ai_cs_bot
            asyncio.create_task(get_ai_cs_bot().start())
            log.info("已安排启动 MistRelay 专属 AI 客服机器人守护任务")
        except Exception as e:
            log.warning(f"启动 AI 客服机器人失败: {e}")


async def cleanup():
    try:
        from thumbnail_worker import get_thumbnail_worker
        await get_thumbnail_worker().stop()
    except Exception:
        pass
    try:
        from botfather_creator import get_keepalive_worker
        await get_keepalive_worker().stop()
    except Exception:
        pass
    try:
        from ai_customer_service import get_ai_cs_bot
        await get_ai_cs_bot().stop()
    except Exception:
        pass
    set_service_ready(False)
    """清理资源"""
    if stream_server:
        try:
            await stream_server.cleanup()
        except Exception as e:
            log.warning(f"清理 Web 服务器时出错: {e}")
    if ENABLE_STREAM:
        try:
            # 停止所有客户端（包括多客户端模式下的额外客户端）
            from WebStreamer.bot import multi_clients
            for index, client in multi_clients.items():
                try:
                    if client and client.is_connected:
                        await client.stop()
                        log.info(f"客户端 {index} 已停止")
                except Exception as e:
                    log.warning(f"停止客户端 {index} 时出错: {e}")
        except Exception as e:
            log.warning(f"清理客户端时出错: {e}")


if __name__ == "__main__":
    from service_runtime import run_event_loop

    loop = asyncio.get_event_loop()
    try:
        run_event_loop(loop, main, cleanup)
    except KeyboardInterrupt:
        pass
