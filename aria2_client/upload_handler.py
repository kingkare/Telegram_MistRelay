"""
Aria2上传处理模块 - 处理Telegram频道网盘上传
"""
import logging
import asyncio
import functools
import os

from configer import get_config_value
from util import byte2_readable, progress as util_progress
from db import (
    mark_upload_started, mark_upload_completed, mark_upload_failed,
    update_upload_status, save_tg_media
)
from util import imgCoverFromFile

from .constants import (
    DOWNLOAD_PROGRESS_UPDATE_INTERVAL,
    pyrogram_clients,
    channel_accessible_clients,
    channel_write_clients,
    upload_work_loads,
    get_upload_semaphore
)



logger = logging.getLogger(__name__)

async def ensure_peer_cached(client, chat_id: int | str):
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


class UploadHandler:
    """处理文件上传到Telegram频道网盘"""

    def __init__(self, bot, progress_cache):
        """
        初始化上传处理器

        Args:
            bot: Telegram bot实例
            progress_cache: 进度缓存字典
        """
        self.bot = bot
        self.progress_cache = progress_cache

    def _get_fallback_bot(self):
        """Return a Pyrogram bot so uploaded messages can be indexed for TG drive."""
        try:
            from WebStreamer.bot import StreamBot
            if StreamBot is not None:
                return StreamBot
        except Exception:
            pass
        return self.bot

    def _get_upload_chat_id(self, upload_id=None, gid=None):
        """TG drive uploads land in user target_channel_id if specified, otherwise BIN_CHANNEL (only for admin/system)."""
        dl = None
        if upload_id or gid:
            try:
                import db
                if upload_id:
                    up = db.get_upload_by_id(upload_id)
                    if up and up.get("download_id"):
                        dl = db.get_download_by_id(up["download_id"])
                elif gid:
                    did = db.get_download_id_by_gid(gid)
                    if did:
                        dl = db.get_download_by_id(did)
            except Exception as e:
                logger.debug(f"查询下载任务目标频道失败: {e}")

        if dl:
            if dl.get("target_channel_id"):
                return int(dl["target_channel_id"])
            if dl.get("user_id"):
                try:
                    import db
                    u = db.get_user_by_id(dl["user_id"])
                    if u:
                        if u.get("bin_channel_id"):
                            return int(u["bin_channel_id"])
                        if u.get("role") != "admin":
                            raise RuntimeError(
                                f"普通租户 (user_id={dl['user_id']}) 尚未分配专属存储频道，严禁上传至全局默认频道 BIN_CHANNEL"
                            )
                except RuntimeError:
                    raise
                except Exception as e:
                    logger.debug(f"查询下载任务所属用户专属频道失败: {e}")

        target = get_config_value('BIN_CHANNEL', None)
        try:
            return int(target) if target not in (None, '') else None
        except (TypeError, ValueError):
            return target

    def _record_uploaded_media(self, message, fallback_name: str) -> str:
        """Persist an uploaded Telegram message so the PC TG-drive page can browse it."""
        try:
            media = None
            message_media = getattr(message, "media", None)
            media_attr = getattr(message_media, "value", None)
            if media_attr:
                media = getattr(message, media_attr, None)
            if media is None:
                media = (
                    getattr(message, "audio", None)
                    or getattr(message, "document", None)
                    or getattr(message, "photo", None)
                    or getattr(message, "sticker", None)
                    or getattr(message, "animation", None)
                    or getattr(message, "video", None)
                    or getattr(message, "voice", None)
                    or getattr(message, "video_note", None)
                )
            if media:
                save_tg_media(message, media)
                chat_id = getattr(getattr(message, "chat", None), "id", None)
                if chat_id is None:
                    chat_id = getattr(message, "chat_id", None)
                message_id = getattr(message, "id", None)
                if message_id is None:
                    message_id = getattr(message, "message_id", None)
                if message_id:
                    try:
                        from thumbnail_worker import get_thumbnail_worker
                        get_thumbnail_worker().enqueue(message_id, chat_id=chat_id)
                    except Exception:
                        pass
                if chat_id and message_id:
                    return f"telegram://{chat_id}/{message_id}"
        except Exception as e:
            raise RuntimeError(f"记录上传媒体到TG网盘索引失败: {e}") from e
        raise RuntimeError(f"上传完成但无法识别Telegram媒体消息: {fallback_name}")

    async def _set_task_tracker_status(self, gid, status: str):
        if not gid:
            return
        try:
            from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock

            if task_completion_lock:
                async with task_completion_lock:
                    task_completion_tracker[gid] = {
                        'status': status,
                        'completed_at': asyncio.get_event_loop().time()
                    }
                    logger.info(f"任务 {gid} 已标记为{status}（Telegram上传）")
        except Exception as e:
            logger.error(f"更新任务{status}状态失败: {e}")

    async def _mark_uploaded(self, gid):
        await self._set_task_tracker_status(gid, 'uploaded')

    async def _mark_cleaned(self, gid):
        await self._set_task_tracker_status(gid, 'cleaned')

    async def _mark_failed(self, gid):
        await self._set_task_tracker_status(gid, 'failed')

    async def upload_to_telegram_with_load_balance(self, file_path, gid, upload_id=None):
        """
        使用多客户端负载均衡上传文件到Telegram

        Args:
            file_path: 文件路径
            gid: 下载任务GID
            upload_id: 上传记录ID
        """
        # 获取上传并发控制信号量
        upload_semaphore = get_upload_semaphore()
        if upload_semaphore:
            await upload_semaphore.acquire()

        try:
            # 标记上传开始并设置文件大小
            if upload_id:
                try:
                    # 检查并更新下载记录状态（如果文件已存在且下载记录状态为pending）
                    if os.path.exists(file_path):
                        from db import check_and_update_download_status_if_file_exists
                        check_and_update_download_status_if_file_exists(upload_id, file_path)

                    # 获取文件大小，用于设置 total_size
                    file_size_bytes = 0
                    if os.path.exists(file_path):
                        try:
                            file_size_bytes = os.path.getsize(file_path)
                        except Exception:
                            pass
                    # 在上传开始时设置 total_size
                    mark_upload_started(upload_id, total_size=file_size_bytes if file_size_bytes > 0 else None)
                except Exception as e:
                    logger.warning(f"操作失败(已忽略): {e}")
                    pass

            try:
                upload_chat_id = self._get_upload_chat_id(upload_id=upload_id, gid=gid)
            except RuntimeError as target_err:
                logger.error(f"解析目标存储频道失败: {target_err}")
                if upload_id:
                    mark_upload_failed(upload_id, 'config_error', str(target_err), 'NO_DEDICATED_CHANNEL')
                return

            default_bin = get_config_value('BIN_CHANNEL', None)
            is_dedicated_channel = bool(
                upload_chat_id and default_bin and str(upload_chat_id) != str(default_bin)
            )

            client_index = None
            upload_client = None

            if not is_dedicated_channel and pyrogram_clients and len(pyrogram_clients) > 0:
                # 仅上传到全局公用 BIN_CHANNEL 时才在多客户端间负载均衡；专属频道由已提权的主控 Bot 上传
                import aria2_client.constants as a2_const
                write_candidates = getattr(a2_const, "channel_write_clients", None) or channel_write_clients
                if not write_candidates and 0 in pyrogram_clients:
                    write_candidates = {0}

                if write_candidates:
                    available_loads = {
                        k: v for k, v in upload_work_loads.items()
                        if k in write_candidates and k in pyrogram_clients
                    }
                    if available_loads:
                        client_index = min(available_loads, key=available_loads.get)
                    elif 0 in pyrogram_clients:
                        client_index = 0
                elif 0 in pyrogram_clients:
                    client_index = 0

                if client_index is not None and client_index in pyrogram_clients:
                    upload_client = pyrogram_clients[client_index]
                    upload_work_loads[client_index] = upload_work_loads.get(client_index, 0) + 1
                    logger.info(f"使用Pyrogram写权限客户端 {client_index} 上传文件（上传负载: {upload_work_loads[client_index]}）")

            if upload_client is None:
                upload_client = self._get_fallback_bot()
                logger.info(f"使用主控 StreamBot 上传文件 (目标频道: {upload_chat_id})")

            if upload_client is None or not upload_chat_id:
                error_text = "Telegram上传客户端或存储频道未初始化"
                logger.error(error_text)
                if upload_id:
                    mark_upload_failed(upload_id, 'config_error', error_text, 'NO_TELEGRAM_TARGET')
                return

            try:
                await ensure_peer_cached(upload_client, upload_chat_id)
            except Exception as cache_err:
                logger.debug(f"Peer 预热已尝试: {cache_err}")

            # 静默处理：不再发送Telegram消息，上传开始状态通过WebSocket推送
            # WebSocket推送已在 mark_upload_started 中实现
            msg = None  # 不再使用msg对象

            # 根据文件类型上传
            lower_file_path = file_path.lower()
            try:
                if lower_file_path.endswith(('.jpg', '.jpeg', '.png', '.gif')):
                    # 图片文件
                    if hasattr(upload_client, 'send_file'):  # Telethon
                        partial_callback = functools.partial(self.callback, gid=gid, msg=msg, path=file_path, upload_id=upload_id)
                        temp_msg = await upload_client.send_file(upload_chat_id, file_path, progress_callback=partial_callback)
                    else:  # Pyrogram
                        temp_msg = await upload_client.send_photo(upload_chat_id, file_path)

                    remote_path = self._record_uploaded_media(temp_msg, os.path.basename(file_path))

                    # 标记图片上传完成
                    if upload_id:
                        try:
                            mark_upload_completed(upload_id, remote_path=remote_path)
                        except Exception as e:
                            logger.warning(f"标记图片上传完成失败(已忽略): {e}")

                    await self._mark_uploaded(gid)

                    # 图片上传后，上传成功后清理本地文件
                    if os.path.exists(file_path):
                        try:
                            os.unlink(file_path)

                            # 更新数据库中的清理状态
                            if upload_id:
                                try:
                                    from db import mark_upload_cleaned
                                    mark_upload_cleaned(upload_id)
                                    logger.info(f"已更新上传记录 {upload_id} 的清理状态（Telegram上传）")
                                except Exception as e:
                                    logger.error(f"更新数据库清理状态失败: {e}")

                            await self._mark_cleaned(gid)
                        except Exception as e:
                            logger.error(f"删除图片文件失败: {e}")
                            if upload_id:
                                mark_upload_failed(upload_id, 'cleanup_failed', f"上传完成，但删除本地图片失败: {e}", 'CLEANUP_FAILED')
                            await self._mark_failed(gid)
                    else:
                        logger.info(f"图片上传完成，本地文件已不存在，按已清理处理: {file_path}")
                        if upload_id:
                            try:
                                from db import mark_upload_cleaned
                                mark_upload_cleaned(upload_id)
                            except Exception as e:
                                logger.error(f"更新数据库清理状态失败: {e}")
                        await self._mark_cleaned(gid)

                elif lower_file_path.endswith(('.mp4', '.mkv', '.avi', '.mov')):
                    # 视频文件
                    pat = os.path.dirname(file_path)
                    filename = os.path.basename(file_path).split('.')[0]
                    thumb_path = pat + '/' + filename + '.jpg'

                    # 生成视频封面失败不应阻断主文件上传。
                    try:
                        await imgCoverFromFile(file_path, thumb_path)
                    except Exception as e:
                        logger.warning(f"生成视频封面失败，将不带封面继续上传: {e}")
                        thumb_path = None

                    if hasattr(upload_client, 'send_file'):  # Telethon
                        partial_callback = functools.partial(self.callback, gid=gid, msg=msg, path=file_path, upload_id=upload_id)
                        temp_msg = await upload_client.send_file(
                            upload_chat_id,
                            file_path,
                            thumb=thumb_path,
                            progress_callback=partial_callback
                        )
                    else:  # Pyrogram
                        if thumb_path:
                            temp_msg = await upload_client.send_video(upload_chat_id, file_path, thumb=thumb_path)
                        else:
                            temp_msg = await upload_client.send_video(upload_chat_id, file_path)

                    remote_path = self._record_uploaded_media(temp_msg, os.path.basename(file_path))

                    # 标记视频上传完成
                    if upload_id:
                        try:
                            mark_upload_completed(upload_id, remote_path=remote_path)
                        except Exception as e:
                            logger.warning(f"标记视频上传完成失败(已忽略): {e}")

                    await self._mark_uploaded(gid)

                    # 删除封面
                    if thumb_path and os.path.exists(thumb_path):
                        try:
                            os.unlink(thumb_path)
                        except Exception as e:
                            logger.warning(f"删除视频封面失败(已忽略): {e}")

                    if os.path.exists(file_path):
                        try:
                            os.unlink(file_path)

                            # 更新数据库中的清理状态
                            if upload_id:
                                try:
                                    from db import mark_upload_cleaned
                                    mark_upload_cleaned(upload_id)
                                    logger.info(f"已更新上传记录 {upload_id} 的清理状态（Telegram上传-视频）")
                                except Exception as e:
                                    logger.error(f"更新数据库清理状态失败: {e}")

                            await self._mark_cleaned(gid)
                        except Exception as e:
                            logger.error(f"删除视频文件失败: {e}")
                            if upload_id:
                                mark_upload_failed(upload_id, 'cleanup_failed', f"上传完成，但删除本地视频失败: {e}", 'CLEANUP_FAILED')
                            await self._mark_failed(gid)
                    else:
                        logger.info(f"视频上传完成，本地文件已不存在，按已清理处理: {file_path}")
                        if upload_id:
                            try:
                                from db import mark_upload_cleaned
                                mark_upload_cleaned(upload_id)
                            except Exception as e:
                                logger.error(f"更新数据库清理状态失败: {e}")
                        await self._mark_cleaned(gid)
                else:
                    # 其他文件类型
                    if hasattr(upload_client, 'send_file'):  # Telethon
                        partial_callback = functools.partial(self.callback, gid=gid, msg=msg, path=file_path, upload_id=upload_id)
                        temp_msg = await upload_client.send_file(upload_chat_id, file_path, progress_callback=partial_callback)
                    else:  # Pyrogram
                        temp_msg = await upload_client.send_document(upload_chat_id, file_path)

                    remote_path = self._record_uploaded_media(temp_msg, os.path.basename(file_path))

                    if hasattr(msg, 'delete'):
                        await msg.delete()

                    # 标记上传完成（如果上面的逻辑没有抛出异常）
                    if upload_id:
                        try:
                            mark_upload_completed(upload_id, remote_path=remote_path)
                        except Exception as e:
                            logger.warning(f"操作失败(已忽略): {e}")
                    await self._mark_uploaded(gid)

                    if os.path.exists(file_path):
                        try:
                            os.unlink(file_path)

                            # 更新数据库中的清理状态
                            if upload_id:
                                try:
                                    from db import mark_upload_cleaned
                                    mark_upload_cleaned(upload_id)
                                    logger.info(f"已更新上传记录 {upload_id} 的清理状态（Telegram上传-其他）")
                                except Exception as e:
                                    logger.error(f"更新数据库清理状态失败: {e}")

                            await self._mark_cleaned(gid)
                        except Exception as e:
                            logger.error(f"删除文件失败: {e}")
                            if upload_id:
                                mark_upload_failed(upload_id, 'cleanup_failed', f"上传完成，但删除本地文件失败: {e}", 'CLEANUP_FAILED')
                            await self._mark_failed(gid)
                    else:
                        logger.info(f"文件上传完成，本地文件已不存在，按已清理处理: {file_path}")
                        if upload_id:
                            try:
                                from db import mark_upload_cleaned
                                mark_upload_cleaned(upload_id)
                            except Exception as e:
                                logger.error(f"更新数据库清理状态失败: {e}")
                        await self._mark_cleaned(gid)

            finally:
                # 减少上传负载
                if client_index is not None and client_index in upload_work_loads:
                    upload_work_loads[client_index] = max(0, upload_work_loads[client_index] - 1)

        except Exception as e:
            logger.exception(f"上传到Telegram失败: {e}")
            error_msg = (
                f'❌ <b>上传失败</b>\n\n'
                f'📂 <b>路径:</b> <code>{file_path}</code>\n\n'
                f'⚠️ <b>错误:</b> {str(e)}'
            )

            if upload_id:
                try:
                    mark_upload_failed(upload_id, 'code_error', str(e), 'EXCEPTION')
                except Exception as e:
                    logger.warning(f"操作失败(已忽略): {e}")
                    pass
            await self._mark_failed(gid)

            # 静默处理：不再发送Telegram消息，错误信息已通过数据库记录
            logger.error(f"Telegram上传错误: {error_msg}")
            # 注意：负载递减已在内层 finally 中处理，此处不再重复递减
        finally:
            # 释放上传并发控制信号量
            if upload_semaphore:
                upload_semaphore.release()

    async def callback(self, current, total, gid, msg=None, path=None, upload_id=None):
        """
        上传进度回调函数

        Args:
            current: 当前上传字节数
            total: 总字节数
            gid: 下载任务GID
            msg: 消息对象
            path: 文件路径
            upload_id: 上传记录ID
        """
        if upload_id:
            try:
                import time
                # 使用实例变量存储上次更新时间，避免频繁更新
                if not hasattr(self, '_last_telegram_update_time'):
                    self._last_telegram_update_time = {}

                current_time = time.time()
                last_update_time = self._last_telegram_update_time.get(upload_id, 0)

                # 限制更新频率，类似下载的3秒间隔
                if current_time - last_update_time >= DOWNLOAD_PROGRESS_UPDATE_INTERVAL:
                    # 更新进度（注意：Telegram上传没有速度信息）
                    update_upload_status(upload_id, 'uploading', uploaded_size=current, total_size=total)
                    self._last_telegram_update_time[upload_id] = current_time
            except Exception:
                pass

        if not msg or not path:
            return

        gid_progress = self.progress_cache.get(gid, 0)
        new_progress = current / total
        formatted_progress = "{:.2%}".format(new_progress)
        if abs(new_progress - gid_progress) >= 0.05:
            self.progress_cache[gid] = new_progress
            file_name = os.path.basename(path)
            file_size = byte2_readable(total)
            current_size = byte2_readable(current)
            progress_bar = util_progress(int(total), int(current))

            new_message_text = (
                f'📤 <b>上传到 Telegram</b>\n\n'
                f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                f'📂 <b>路径:</b> <code>{path}</code>\n\n'
                f'📊 <b>进度:</b> {progress_bar}\n'
                f'💾 <b>已上传:</b> {current_size} / {file_size}\n'
                f'📈 <b>完成度:</b> {formatted_progress}'
            )
            # 静默处理：不再发送Telegram消息，上传进度通过WebSocket推送
            # WebSocket推送已在 update_upload_status 中实现
