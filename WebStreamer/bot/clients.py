# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

import asyncio
import logging
from ..vars import Var
from pyrogram import Client
from . import (
    multi_clients,
    work_loads,
    sessions_dir,
    StreamBot,
    channel_accessible_clients,
    channel_write_clients,
    bot_channel_modes,
    channel_public_handle,
    register_bot_client,
    unregister_bot_client,
    set_bot_home_dc,
)

_client_mutation_lock = asyncio.Lock()
_health_check_task = None

logger = logging.getLogger("multi_client")

# 配置 Pyrogram 日志级别，降低连接警告的级别
# 这些警告通常是正常的网络波动，Pyrogram 会自动重连
pyrogram_transport_logger = logging.getLogger('pyrogram.connection.transport.tcp.tcp')
pyrogram_transport_logger.setLevel(logging.ERROR)  # 只显示 ERROR 及以上级别

# 过滤 asyncio 的 socket.send() 警告
pyrogram_asyncio_logger = logging.getLogger('asyncio')
class BrokenPipeFilter(logging.Filter):
    """过滤 BrokenPipeError 相关的警告，这些通常是正常的网络波动"""
    def filter(self, record):
        msg = str(record.getMessage())
        # 过滤 BrokenPipeError 和 socket.send() 相关的警告
        if any(keyword in msg for keyword in ['BrokenPipeError', 'Broken pipe', 'socket.send() raised exception']):
            # 将警告降级为 DEBUG 级别，不显示在日志中
            record.levelno = logging.DEBUG
            record.levelname = 'DEBUG'
        return True

broken_pipe_filter = BrokenPipeFilter()
pyrogram_asyncio_logger.addFilter(broken_pipe_filter)

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

encryption_error_filter = EncryptionErrorFilter()
pyrogram_asyncio_logger.addFilter(encryption_error_filter)

def extract_channel_public_handle(chat) -> str | None:
    """提取频道的公开标识（用户名或关联讨论组用户名）"""
    if not chat:
        return None
    username = getattr(chat, "username", None)
    if username:
        return str(username).lstrip("@")
    linked_chat = getattr(chat, "linked_chat", None)
    if linked_chat:
        linked_username = getattr(linked_chat, "username", None)
        if linked_username:
            return str(linked_username).lstrip("@")
    return None


async def probe_worker_channel_access(
    index: int,
    client: Client,
    bin_channel: int,
    public_handle: str | None = None,
) -> dict:
    """探测 Worker 机器人对 BIN_CHANNEL 的访问权限，并在需要时通过公开 Handle 自动解析 Peer"""
    import WebStreamer.bot as bot_mod

    can_read = False
    can_write = False
    mode = "unreachable"
    error_msg = ""

    # 1. 尝试直接获取频道
    step1_success = False
    try:
        await client.get_chat(bin_channel)
        step1_success = True
    except Exception as e:
        error_msg = str(e)
        logger.debug(f"客户端 {index} 直接 get_chat({bin_channel}) 失败: {e}")

    if step1_success:
        can_read = True
        # 验证是否为频道内真实管理员/成员（抑或仅是先前已缓存 Peer 的非成员）
        try:
            member = await client.get_chat_member(bin_channel, "me")
            privileges = getattr(member, "privileges", None)
            if privileges and getattr(privileges, "can_post_messages", False):
                can_write = True
                mode = "direct_admin"
            else:
                status = getattr(member, "status", None)
                status_str = str(status).lower() if status else ""
                if "admin" in status_str or "owner" in status_str or "creator" in status_str:
                    can_write = True
                    mode = "direct_admin"
                else:
                    mode = "direct_member"
        except Exception as member_err:
            member_err_str = str(member_err).lower()
            if any(k in member_err_str for k in ["user_not_participant", "participant", "chat_admin_required", "channel_private"]):
                mode = "no_join_resolved"
                can_write = False
            else:
                mode = "direct_admin"
                can_write = True
    else:
        # 2. 直接访问失败，若存在公开 handle，尝试通过公开标识解析 Peer
        active_handle = public_handle or getattr(bot_mod, "channel_public_handle", None)
        if active_handle:
            try:
                logger.info(f"客户端 {index} 尝试通过公开标识 @{active_handle} 级联解析 Peer...")
                await client.get_chat(active_handle)
                await client.get_chat(bin_channel)
                can_read = True
                can_write = False
                mode = "no_join_resolved"
                logger.info(f"客户端 {index} (@{getattr(client, 'username', '')}) 通过 @{active_handle} 成功激活免加频道负载均衡！")
            except Exception as resolve_err:
                logger.warning(f"客户端 {index} 通过公开标识 @{active_handle} 解析 Peer 失败: {resolve_err}")
                error_msg = str(resolve_err)
        else:
            logger.warning(f"客户端 {index} 无法访问私密频道 {bin_channel} (无公开 Handle 可用)")

    if can_read:
        bot_mod.channel_accessible_clients.add(index)
    else:
        bot_mod.channel_accessible_clients.discard(index)

    if can_write:
        bot_mod.channel_write_clients.add(index)
    else:
        bot_mod.channel_write_clients.discard(index)

    result = {
        "mode": mode,
        "can_read": can_read,
        "can_write": can_write,
        "username": getattr(client, "username", "") or "",
        "last_error": error_msg,
    }
    bot_mod.bot_channel_modes[index] = result
    return result

async def register_primary_streambot():
    """当主 StreamBot 已连接时，将其注册为客户端 0"""
    import WebStreamer.bot as bot_mod

    if not getattr(StreamBot, "is_connected", False):
        logger.warning("主客户端 0 (StreamBot) 当前尚未连接，暂缓加入活跃客户端池")
        return False
    multi_clients[0] = StreamBot
    work_loads.setdefault(0, 0)
    register_bot_client(0)
    try:
        if hasattr(StreamBot, "storage") and hasattr(StreamBot.storage, "dc_id"):
            h_dc = await StreamBot.storage.dc_id()
            set_bot_home_dc(0, h_dc)
    except Exception:
        pass

    try:
        if not getattr(StreamBot, "username", None):
            bot_info = await StreamBot.get_me()
            StreamBot.username = bot_info.username
    except Exception:
        pass

    if Var.BIN_CHANNEL:
        try:
            chat = await StreamBot.get_chat(Var.BIN_CHANNEL)
            bot_mod.channel_accessible_clients.add(0)
            bot_mod.channel_write_clients.add(0)

            handle = extract_channel_public_handle(chat)
            if handle:
                bot_mod.channel_public_handle = handle
                logger.info(f"主客户端已探测到频道公开标识符: @{handle}，将用于多 Bot 免加频道分流")

            bot_mod.bot_channel_modes[0] = {
                "mode": "primary_admin",
                "can_read": True,
                "can_write": True,
                "username": getattr(StreamBot, "username", "") or "",
            }
            logger.info(f"客户端 0 (主控) 已成功访问并纳管 BIN_CHANNEL: {Var.BIN_CHANNEL}")
        except Exception as e:
            logger.warning(f"客户端 0 无法访问 BIN_CHANNEL: {e}")
            bot_mod.bot_channel_modes[0] = {
                "mode": "unreachable",
                "can_read": False,
                "can_write": False,
                "username": getattr(StreamBot, "username", "") or "",
                "last_error": str(e),
            }
    return True


async def initialize_clients():
    """
    初始化客户端
    如果配置了多个BOT_TOKEN，将创建多个客户端以实现负载均衡
    """
    await register_primary_streambot()
    
    # 调试日志：检查配置状态
    logger.info(f"🔍 多客户端初始化检查: MULTI_CLIENT={Var.MULTI_CLIENT}, MULTI_BOT_TOKENS数量={len(Var.MULTI_BOT_TOKENS) if Var.MULTI_BOT_TOKENS else 0}")
    if Var.MULTI_BOT_TOKENS:
        logger.info(f"已配置额外BOT_TOKEN数量: {len(Var.MULTI_BOT_TOKENS)}")
    
    # 如果配置了额外的BOT_TOKEN，创建额外的客户端
    if Var.MULTI_CLIENT and Var.MULTI_BOT_TOKENS and len(Var.MULTI_BOT_TOKENS) > 0:
        # 多客户端模式：为每个额外的BOT_TOKEN创建客户端
        total_clients = 1 + len(Var.MULTI_BOT_TOKENS)
        logger.info(f"启用多机器人负载均衡模式，将初始化 {total_clients} 个客户端（1个默认 + {len(Var.MULTI_BOT_TOKENS)}个额外）")
        logger.info(f"客户端 0 已初始化（默认客户端，使用主BOT_TOKEN）")
        
        # 为额外的BOT_TOKEN创建客户端
        for index, bot_token in enumerate(Var.MULTI_BOT_TOKENS, start=1):
            try:
                bot_id_prefix = str(bot_token).split(":", 1)[0]
                client_name = f"pyrogram_bot_{bot_id_prefix}"
                client = Client(
                    name=client_name,
                    api_id=Var.API_ID,
                    api_hash=Var.API_HASH,
                    workdir=sessions_dir,
                    bot_token=bot_token,
                    sleep_threshold=Var.SLEEP_THRESHOLD,
                    workers=Var.WORKERS,
                    in_memory=False,
                    no_updates=True,
                )
                
                # 启动客户端
                await client.start()
                bot_info = await client.get_me()
                client.username = bot_info.username
                
                # 智能接入 BIN_CHANNEL（免加频道自动 Peer 解析与权限嗅探）
                if Var.BIN_CHANNEL:
                    import WebStreamer.bot as bot_mod
                    probe_res = await probe_worker_channel_access(
                        index=index,
                        client=client,
                        bin_channel=Var.BIN_CHANNEL,
                        public_handle=getattr(bot_mod, "channel_public_handle", None),
                    )
                    if probe_res["can_read"]:
                        if probe_res["mode"] == "no_join_resolved":
                            logger.info(f"客户端 {index} (@{client.username}) 已激活【免加频道】负载均衡模式")
                        else:
                            logger.info(f"客户端 {index} (@{client.username}) 已直接连接频道 ({probe_res['mode']})")
                    else:
                        logger.warning(f"客户端 {index} (@{client.username}) 暂无法访问频道 {Var.BIN_CHANNEL}: {probe_res.get('last_error')}")
                        logger.warning(f"💡 提示: 为频道设置公开用户名或关联公开讨论组，从机器人即可全自动免加频道分流！")
                
                client.bot_token = bot_token
                client.bot_id_prefix = bot_id_prefix
                multi_clients[index] = client
                work_loads[index] = 0
                register_bot_client(index)
                try:
                    if hasattr(client, "storage") and hasattr(client.storage, "dc_id"):
                        h_dc = await client.storage.dc_id()
                        set_bot_home_dc(index, h_dc)
                except Exception:
                    pass
                logger.info(f"客户端 {index} 已初始化: @{bot_info.username}")
            except Exception as e:
                logger.error(f"初始化客户端 {index} 失败: {e}", exc_info=True)
                # 继续初始化其他客户端，不因单个失败而停止
        
        successful_clients = len(multi_clients)
        logger.info(f"多机器人负载均衡初始化完成，共 {successful_clients} 个客户端可用")
        
        # 启动客户端健康检查与跨 DC 会话静默预热任务（仅多客户端模式）
        if Var.MULTI_CLIENT:
            global _health_check_task, _prewarm_task
            _health_check_task = asyncio.create_task(client_health_check())
            _prewarm_task = asyncio.create_task(background_dc_prewarm())
    else:
        # 单客户端模式：只使用默认的StreamBot
        logger.info("使用单客户端模式（默认客户端）")



async def background_dc_prewarm():
    """
    在后台静默并发预热跨 DC 媒体会话。
    避免用户在播放或多线程并发下载时，因从机器人临时创建 DC 会话 (Auth.create + ExportAuthorization)
    导致首包阻塞或队头延迟，实现集群所有 Worker 均以零延迟直接就绪。
    """
    try:
        await asyncio.sleep(3.0)
        from collections import Counter
        from types import SimpleNamespace
        import db
        import WebStreamer.bot as bot_mod
        from WebStreamer.utils.custom_dl import ByteStreamer
        from pyrogram.file_id import FileId

        records = db.list_all_tg_media_records()[:100]
        dc_counts = Counter()
        for r in records:
            fid_str = r.get("file_id")
            if fid_str:
                try:
                    dc_counts[FileId.decode(fid_str).dc_id] += 1
                except Exception:
                    pass

        # 优先预热主媒体分区（如 DC5）
        target_dcs = [dc for dc, cnt in dc_counts.most_common() if cnt >= 5] or [5]
        logger.info(f"🚀 开始执行多机器人后台跨 DC 媒体会话并发预热: 目标主分区 DC={target_dcs}...")

        sem = asyncio.Semaphore(4)

        async def _warm_one(idx: int, cli, dc_id: int):
            async with sem:
                st = bot_mod.bot_runtime.get(idx, {})
                if st.get("home_dc") == dc_id or dc_id in st.get("warm_dcs", set()):
                    return
                if not getattr(cli, "is_connected", False):
                    return
                try:
                    streamer = ByteStreamer.for_client(cli)
                    await streamer.generate_media_session(cli, SimpleNamespace(dc_id=dc_id))
                    logger.info(f"✨ 客户端 {idx} (@{getattr(cli, 'username', idx)}) DC{dc_id} 跨区媒体会话预热完成")
                except Exception as e:
                    logger.debug(f"客户端 {idx} 预热 DC{dc_id} 跳过: {e}")

        for dc_id in target_dcs:
            tasks = [_warm_one(idx, cli, dc_id) for idx, cli in list(multi_clients.items())]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("🎉 多机器人后台跨 DC 媒体会话预热全部就绪！")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning(f"后台跨 DC 会话预热任务异常: {e}")

async def client_health_check():
    """
    定期检查客户端连接健康状态
    如果客户端断开连接，尝试重新连接
    """
    check_interval = 300  # 每5分钟检查一次
    logger.info(f"启动客户端健康检查任务（每 {check_interval} 秒检查一次）")
    
    async def reconnect_client(index, client):
        """安全地重新连接客户端"""
        try:
            # 先停止客户端（如果已连接），确保完全清理状态
            try:
                if hasattr(client, 'is_connected') and client.is_connected:
                    await client.stop()
                    # 等待一小段时间，确保连接完全关闭
                    await asyncio.sleep(1)
            except Exception as stop_error:
                logger.debug(f"停止客户端 {index} 时出错（可能已断开）: {stop_error}")
            
            # 重新启动客户端
            await client.start()
            
            # 验证连接是否正常
            await client.get_me()
            
            logger.info(f"客户端 {index} 重新连接成功")
            return True
        except Exception as reconnect_error:
            error_msg = str(reconnect_error)
            error_type = type(reconnect_error).__name__
            
            # 检查是否是加密相关的错误（这是已知问题，会在重连时自动修复）
            if 'Value after * must be an iterable' in error_msg or 'NoneType' in error_msg:
                logger.debug(f"客户端 {index} 加密状态异常（将在下次检查时重连）: {error_type}")
            else:
                logger.error(f"客户端 {index} 重新连接失败: {reconnect_error}")
            return False
    
    while True:
        try:
            await asyncio.sleep(check_interval)
            
            # 检查所有客户端
            for index, client in list(multi_clients.items()):
                try:
                    # 检查连接状态
                    is_connected = False
                    if hasattr(client, 'is_connected'):
                        is_connected = client.is_connected
                    
                    if not is_connected:
                        logger.warning(f"客户端 {index} 连接已断开，尝试重新连接...")
                        await reconnect_client(index, client)
                    else:
                        # 若已连接但尚未取得频道访问权，尝试使用最新探测到的 public_handle 自愈接入
                        import WebStreamer.bot as bot_mod
                        if index not in bot_mod.channel_accessible_clients and Var.BIN_CHANNEL:
                            if getattr(bot_mod, "channel_public_handle", None):
                                try:
                                    await probe_worker_channel_access(
                                        index=index,
                                        client=client,
                                        bin_channel=Var.BIN_CHANNEL,
                                        public_handle=getattr(bot_mod, "channel_public_handle", None),
                                    )
                                except Exception as heal_err:
                                    logger.debug(f"客户端 {index} 健康检查自愈接入异常: {heal_err}")

                        # 连接正常，尝试一个简单的 API 调用来验证
                        try:
                            await asyncio.wait_for(client.get_me(), timeout=10)
                        except asyncio.TimeoutError:
                            logger.warning(f"客户端 {index} API 调用超时，尝试重新连接...")
                            await reconnect_client(index, client)
                        except TypeError as e:
                            # 捕获加密相关的 TypeError（Value after * must be an iterable）
                            error_msg = str(e)
                            if 'Value after * must be an iterable' in error_msg or 'NoneType' in error_msg:
                                logger.warning(f"客户端 {index} 加密状态异常，尝试重新连接...")
                                await reconnect_client(index, client)
                            else:
                                raise
                        except Exception as check_error:
                            error_msg = str(check_error)
                            error_type = type(check_error).__name__
                            
                            # 检查是否是加密相关的错误
                            if 'Value after * must be an iterable' in error_msg or 'NoneType' in error_msg:
                                logger.warning(f"客户端 {index} 加密状态异常，尝试重新连接...")
                                await reconnect_client(index, client)
                            else:
                                logger.warning(f"客户端 {index} 连接检查失败: {check_error}，尝试重新连接...")
                                await reconnect_client(index, client)
                except Exception as e:
                    error_msg = str(e)
                    # 过滤加密相关的错误，这些是已知问题
                    if 'Value after * must be an iterable' in error_msg or 'NoneType' in error_msg:
                        logger.debug(f"客户端 {index} 检查时出现加密状态异常（将在下次检查时重连）: {type(e).__name__}")
                    else:
                        logger.debug(f"检查客户端 {index} 时出错: {e}")
                    
        except Exception as e:
            logger.error(f"客户端健康检查任务出错: {e}", exc_info=True)
            await asyncio.sleep(60)  # 出错后等待1分钟再继续



async def hot_add_bot_client(bot_token: str, persist: bool = True) -> dict:
    """
    运行时动态接入新的 Worker Bot 客户端，执行免加频道权限嗅探并纳入分流调度器。
    无需重启服务，即刻生效。
    """
    from security_validation import BOT_TOKEN_PATTERN
    import WebStreamer.bot as bot_mod

    bot_token = str(bot_token or "").strip()
    if not BOT_TOKEN_PATTERN.fullmatch(bot_token):
        raise ValueError("Bot Token 格式无效")

    if bot_token == str(Var.BOT_TOKEN or "").strip():
        raise ValueError("不能添加与主控制机器人相同的主 Token")

    bot_id_prefix = bot_token.split(":", 1)[0]

    async with _client_mutation_lock:
        # 检查是否已在运行中
        for idx, existing in list(bot_mod.multi_clients.items()):
            if idx == 0:
                continue
            if getattr(existing, "bot_token", None) == bot_token or getattr(existing, "bot_id_prefix", None) == bot_id_prefix:
                mode_info = bot_mod.bot_channel_modes.get(idx, {})
                return {
                    "index": idx,
                    "username": getattr(existing, "username", "") or "",
                    "mode": mode_info.get("mode", "unknown"),
                    "can_read": idx in bot_mod.channel_accessible_clients,
                    "can_write": idx in bot_mod.channel_write_clients,
                    "already_exists": True,
                }

        new_index = max(bot_mod.multi_clients.keys(), default=0) + 1
        client_name = f"pyrogram_bot_{bot_id_prefix}"
        client = Client(
            name=client_name,
            api_id=Var.API_ID,
            api_hash=Var.API_HASH,
            workdir=sessions_dir,
            bot_token=bot_token,
            sleep_threshold=Var.SLEEP_THRESHOLD,
            workers=Var.WORKERS,
            in_memory=False,
            no_updates=True,
        )

        await client.start()
        bot_info = await client.get_me()
        client.username = bot_info.username
        client.bot_token = bot_token
        client.bot_id_prefix = bot_id_prefix

        probe_res = {"mode": "unreachable", "can_read": False, "can_write": False}
        if Var.BIN_CHANNEL:
            probe_res = await probe_worker_channel_access(
                index=new_index,
                client=client,
                bin_channel=Var.BIN_CHANNEL,
                public_handle=getattr(bot_mod, "channel_public_handle", None),
            )
            if probe_res.get("can_read"):
                bot_mod.channel_accessible_clients.add(new_index)
                if probe_res.get("mode") == "no_join_resolved":
                    logger.info(f"客户端 {new_index} (@{client.username}) 已激活【免加频道】负载均衡模式")
                else:
                    logger.info(f"客户端 {new_index} (@{client.username}) 已直接连接频道 ({probe_res.get('mode')})")
            else:
                bot_mod.channel_accessible_clients.discard(new_index)
                logger.warning(f"客户端 {new_index} (@{client.username}) 暂无法访问频道 {Var.BIN_CHANNEL}: {probe_res.get('last_error')}")
            if probe_res.get("can_write"):
                bot_mod.channel_write_clients.add(new_index)
            else:
                bot_mod.channel_write_clients.discard(new_index)
            bot_mod.bot_channel_modes[new_index] = probe_res

        bot_mod.multi_clients[new_index] = client
        work_loads[new_index] = 0
        register_bot_client(new_index)
        try:
            if hasattr(client, "storage") and hasattr(client.storage, "dc_id"):
                h_dc = await client.storage.dc_id()
                set_bot_home_dc(new_index, h_dc)
        except Exception:
            pass

        # 同步更新 Var.MULTI_BOT_TOKENS
        if Var.MULTI_BOT_TOKENS is None:
            Var.MULTI_BOT_TOKENS = []
        if bot_token not in Var.MULTI_BOT_TOKENS:
            Var.MULTI_BOT_TOKENS.append(bot_token)
        Var.MULTI_CLIENT = True

        if persist:
            try:
                from db import set_config
                set_config("MULTI_BOT_TOKENS", list(Var.MULTI_BOT_TOKENS), "list", "stream", "多机器人Token列表")
            except Exception as db_err:
                logger.warning(f"持久化 MULTI_BOT_TOKENS 到数据库失败: {db_err}")

        # 确保后台健康检查运行
        global _health_check_task
        if _health_check_task is None or _health_check_task.done():
            _health_check_task = asyncio.create_task(client_health_check())

        logger.info(f"客户端 {new_index} (@{client.username}) 已成功热挂载入网！")
        return {
            "index": new_index,
            "username": client.username,
            "mode": probe_res["mode"],
            "can_read": probe_res["can_read"],
            "can_write": probe_res["can_write"],
            "already_exists": False,
        }


async def hot_remove_bot_client(index: int, persist: bool = True) -> dict:
    """
    运行时安全下线并剔除指定的 Worker 客户端。
    禁止移除主控制机器人 (index 0)。
    """
    from . import unregister_bot_client
    import WebStreamer.bot as bot_mod

    if index == 0:
        raise ValueError("不能移除主控制机器人 (Client 0)")

    async with _client_mutation_lock:
        if index not in bot_mod.multi_clients:
            raise KeyError(f"未找到客户端编号 {index}")

        client = bot_mod.multi_clients.pop(index)
        bot_token = getattr(client, "bot_token", None)
        bot_id_prefix = getattr(client, "bot_id_prefix", None)
        username = getattr(client, "username", "") or ""

        unregister_bot_client(index)

        try:
            if hasattr(client, "is_connected") and client.is_connected:
                await client.stop()
        except Exception as stop_err:
            logger.debug(f"停止客户端 {index} 异常: {stop_err}")

        if Var.MULTI_BOT_TOKENS and (bot_token or bot_id_prefix):
            Var.MULTI_BOT_TOKENS = [
                t for t in Var.MULTI_BOT_TOKENS
                if t != bot_token and not (bot_id_prefix and str(t).startswith(f"{bot_id_prefix}:"))
            ]
            Var.MULTI_CLIENT = len(Var.MULTI_BOT_TOKENS) > 0
            if persist:
                try:
                    from db import set_config
                    set_config("MULTI_BOT_TOKENS", list(Var.MULTI_BOT_TOKENS), "list", "stream", "多机器人Token列表")
                except Exception as db_err:
                    logger.warning(f"持久化 MULTI_BOT_TOKENS 到数据库失败: {db_err}")

        logger.info(f"客户端 {index} (@{username}) 已成功安全下线并剔除")
        return {
            "removed_index": index,
            "username": username,
            "remaining_workers": max(0, len(bot_mod.multi_clients) - 1),
        }
