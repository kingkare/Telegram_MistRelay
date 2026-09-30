"""
Telegram 网盘用户本地文件分片上传管理模块
支持断点分片、大文件并发流式汇聚、Pyrogram 自动媒体类型分类投递入库与缩略图预热。
"""
import os
import shutil
import math
import uuid
import time
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from path_security import validate_child_name, UnsafePathError

logger = logging.getLogger("user_uploader")

# 默认分片大小：5 MB (5,242,880 字节)，兼顾上传并发与网络利用率，规避 aiohttp 30MB 限制
DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024
# 单文件最大支持：2 GB (Telegram 官方上限)
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024


def get_temp_upload_dir() -> Path:
    """获取临时上传分片暂存目录"""
    env_dir = os.environ.get("MISTRELAY_TEMP_UPLOAD_DIR")
    if env_dir:
        p = Path(env_dir)
    elif os.environ.get("MISTRELAY_FILE_ROOT") and os.path.isdir(os.environ["MISTRELAY_FILE_ROOT"]):
        p = Path(os.environ["MISTRELAY_FILE_ROOT"]) / "temp_uploads"
    elif os.path.isdir("/data/downloads"):
        p = Path("/data/downloads/temp_uploads")
    elif os.path.isdir("/app/downloads"):
        p = Path("/app/downloads/temp_uploads")
    else:
        p = Path(__file__).resolve().parent / "downloads" / "temp_uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


class UserUploadManager:
    """管理用户本地文件分片上传会话与 Telegram 转存生命周期"""

    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup = time.time()
        try:
            self.cleanup_stale_uploads()
        except Exception as e:
            logger.debug(f"启动自动清理暂存分片异常: {e}")

    def cleanup_stale_uploads(self, max_age_seconds: int = 7200) -> Dict[str, Any]:
        """清理已过期未完成的暂存分片目录与内存任务"""
        staging_root = get_temp_upload_dir()
        now = time.time()
        cleaned_dirs = 0
        cleaned_bytes = 0

        if staging_root.exists():
            for item in staging_root.iterdir():
                if item.is_dir():
                    try:
                        mtime = item.stat().st_mtime
                        age = now - mtime
                        task = self._tasks.get(item.name)
                        should_clean = age > max_age_seconds
                        if task and task.get("status") in ("completed", "failed", "cancelled"):
                            should_clean = True

                        if should_clean:
                            dir_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                            shutil.rmtree(item, ignore_errors=True)
                            cleaned_dirs += 1
                            cleaned_bytes += dir_size
                            if item.name in self._tasks:
                                self._tasks.pop(item.name, None)
                    except Exception as e:
                        logger.debug(f"清理暂存目录 {item} 异常: {e}")

        stale_task_ids = []
        for uid, t in self._tasks.items():
            if t.get("status") in ("completed", "failed", "cancelled"):
                if now - t.get("updated_at", now) > max_age_seconds:
                    stale_task_ids.append(uid)
            elif now - t.get("updated_at", now) > max_age_seconds * 2:
                stale_task_ids.append(uid)

        for uid in stale_task_ids:
            self._tasks.pop(uid, None)

        if cleaned_dirs > 0:
            logger.info(f"清理暂存分片目录完成: 共清理 {cleaned_dirs} 个目录, 释放 {round(cleaned_bytes / (1024*1024), 2)} MB")

        return {
            "cleaned_dirs": cleaned_dirs,
            "cleaned_bytes": cleaned_bytes,
            "cleaned_mb": round(cleaned_bytes / (1024 * 1024), 2),
        }

    def init_upload(
        self,
        user_id: Optional[int],
        chat_id: int,
        filename: str,
        file_size: int,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        mime_type: str = ""
    ) -> Dict[str, Any]:
        """初始化一个分片上传会话"""
        if time.time() - self._last_cleanup > 300:
            try:
                self.cleanup_stale_uploads()
            except Exception:
                pass
            self._last_cleanup = time.time()
        safe_filename = validate_child_name(filename)

        if file_size <= 0:
            raise ValueError("文件大小必须大于 0 字节")
        if file_size > MAX_FILE_SIZE:
            raise ValueError(f"文件大小超出上限 (最大 2GB，当前 {file_size} 字节)")

        if chunk_size < 1024 * 1024 or chunk_size > 20 * 1024 * 1024:
            chunk_size = DEFAULT_CHUNK_SIZE

        total_chunks = max(1, math.ceil(file_size / chunk_size))
        upload_id = uuid.uuid4().hex

        staging_dir = get_temp_upload_dir() / upload_id
        staging_dir.mkdir(parents=True, exist_ok=True)

        task_record = {
            "upload_id": upload_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "filename": safe_filename,
            "file_size": file_size,
            "chunk_size": chunk_size,
            "total_chunks": total_chunks,
            "mime_type": mime_type or "",
            "received_chunks": set(),
            "created_at": time.time(),
            "updated_at": time.time(),
            "status": "pending",  # pending | uploading_chunks | merging | uploading_tg | completed | failed | cancelled
            "tg_progress": 0.0,
            "error": None,
            "media": None,
            "staging_dir": staging_dir,
            "assembled_file": None,
            "async_task": None,
        }

        self._tasks[upload_id] = task_record
        logger.info(f"创建用户上传会话 {upload_id}: {safe_filename} ({file_size} 字节, {total_chunks} 分片, 目标频道 {chat_id})")

        return {
            "success": True,
            "upload_id": upload_id,
            "chunk_size": chunk_size,
            "total_chunks": total_chunks,
            "target_channel_id": chat_id,
            "filename": safe_filename,
        }

    def save_chunk(
        self,
        upload_id: str,
        user_id: Optional[int],
        chunk_index: int,
        chunk_data: bytes,
        is_admin: bool = False
    ) -> Dict[str, Any]:
        """保存单个分片数据到暂存目录"""
        task = self._tasks.get(upload_id)
        if not task:
            raise KeyError(f"未找到上传会话: {upload_id}")

        if not is_admin and task["user_id"] is not None and user_id is not None and task["user_id"] != user_id:
            raise PermissionError("无权操作此上传任务")

        if chunk_index < 0 or chunk_index >= task["total_chunks"]:
            raise ValueError(f"分片索引超出范围 (0 ~ {task['total_chunks'] - 1}): {chunk_index}")

        chunk_path = task["staging_dir"] / f"chunk_{chunk_index}"
        with open(chunk_path, "wb") as f:
            f.write(chunk_data)

        task["received_chunks"].add(chunk_index)
        task["updated_at"] = time.time()
        if task["status"] == "pending":
            task["status"] = "uploading_chunks"

        return {
            "success": True,
            "upload_id": upload_id,
            "chunk_index": chunk_index,
            "received_count": len(task["received_chunks"]),
            "total_chunks": task["total_chunks"],
        }

    async def finish_upload(
        self,
        upload_id: str,
        user_id: Optional[int],
        wait_seconds: float = 0.5,
        is_admin: bool = False
    ) -> Dict[str, Any]:
        """完成所有分片上传，合并文件并发起 Telegram 转存"""
        task = self._tasks.get(upload_id)
        if not task:
            raise KeyError(f"未找到上传会话: {upload_id}")

        if not is_admin and task["user_id"] is not None and user_id is not None and task["user_id"] != user_id:
            raise PermissionError("无权操作此上传任务")

        missing_chunks = [
            i for i in range(task["total_chunks"])
            if i not in task["received_chunks"] or not (task["staging_dir"] / f"chunk_{i}").exists()
        ]
        if missing_chunks:
            raise ValueError(f"分片未完整就绪，缺少 {len(missing_chunks)} 个分片 (如分片 #{missing_chunks[0]})")

        task["status"] = "merging"
        safe_filename = task["filename"]
        merged_file = task["staging_dir"] / safe_filename

        # 流式合并分片，边写边删分片文件以节省磁盘空间
        with open(merged_file, "wb") as out_f:
            for idx in range(task["total_chunks"]):
                chunk_file = task["staging_dir"] / f"chunk_{idx}"
                with open(chunk_file, "rb") as in_f:
                    while True:
                        buf = in_f.read(1024 * 1024)
                        if not buf:
                            break
                        out_f.write(buf)
                try:
                    chunk_file.unlink(missing_ok=True)
                except Exception:
                    pass

        task["assembled_file"] = merged_file
        task["status"] = "uploading_tg"

        # 启动后台 Telegram 上传任务
        tg_task = asyncio.create_task(self._process_telegram_upload(upload_id))
        task["async_task"] = tg_task

        # 若提供了短暂等待时间且转存已瞬间完成（例如小文件或 Mock），直接返回最新状态
        if wait_seconds > 0:
            try:
                await asyncio.wait_for(asyncio.shield(tg_task), timeout=wait_seconds)
            except (asyncio.TimeoutError, Exception):
                pass

        return {
            "success": True,
            "upload_id": upload_id,
            "status": task["status"],
            "tg_progress": task["tg_progress"],
            "media": task["media"],
            "error": task["error"],
            "message": "分片已合并完成，正在转存至 Telegram 频道",
        }

    def get_status(self, upload_id: str, user_id: Optional[int], is_admin: bool = False) -> Dict[str, Any]:
        """获取指定上传任务的实时状态与云端转存进度"""
        task = self._tasks.get(upload_id)
        if not task:
            raise KeyError(f"未找到上传会话: {upload_id}")

        if not is_admin and task["user_id"] is not None and user_id is not None and task["user_id"] != user_id:
            raise PermissionError("无权查询此上传任务")

        return {
            "success": True,
            "upload_id": upload_id,
            "status": task["status"],
            "tg_progress": task["tg_progress"],
            "filename": task["filename"],
            "file_size": task["file_size"],
            "received_chunks": len(task["received_chunks"]),
            "total_chunks": task["total_chunks"],
            "media": task["media"],
            "error": task["error"],
        }

    async def cancel_upload(self, upload_id: str, user_id: Optional[int], is_admin: bool = False) -> Dict[str, Any]:
        """取消上传任务并物理清理暂存文件"""
        task = self._tasks.get(upload_id)
        if not task:
            return {"success": True, "message": "会话已不存在或已清理"}

        if not is_admin and task["user_id"] is not None and user_id is not None and task["user_id"] != user_id:
            raise PermissionError("无权取消此上传任务")

        task["status"] = "cancelled"
        if task.get("async_task") and not task["async_task"].done():
            task["async_task"].cancel()

        staging_dir = task.get("staging_dir")
        if staging_dir and os.path.exists(staging_dir):
            try:
                shutil.rmtree(staging_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"清理暂存目录失败: {e}")

        self._tasks.pop(upload_id, None)
        return {"success": True, "message": "上传任务已取消并清理暂存文件"}

    def _resolve_client(self, chat_id: int):
        """选择合适的 Pyrogram 客户端进行上传"""
        try:
            from configer import get_config_value
            default_bin = get_config_value("BIN_CHANNEL", None)
            is_dedicated = bool(
                chat_id and default_bin and str(chat_id) != str(default_bin)
            )

            client = None
            if not is_dedicated:
                import aria2_client.constants as a2_const
                from aria2_client.constants import pyrogram_clients, upload_work_loads, channel_write_clients
                write_candidates = getattr(a2_const, "channel_write_clients", None) or channel_write_clients
                if not write_candidates and 0 in pyrogram_clients:
                    write_candidates = {0}
                if write_candidates:
                    avail = {
                        k: v for k, v in upload_work_loads.items()
                        if k in write_candidates and k in pyrogram_clients
                    }
                    if avail:
                        c_idx = min(avail, key=avail.get)
                        client = pyrogram_clients.get(c_idx)
                    elif 0 in pyrogram_clients:
                        client = pyrogram_clients.get(0)
            if client is None:
                from WebStreamer.bot import StreamBot
                client = StreamBot
            return client
        except Exception as e:
            logger.debug(f"解析上传客户端回退至 StreamBot: {e}")
            try:
                from WebStreamer.bot import StreamBot
                return StreamBot
            except Exception:
                return None

    async def _ensure_peer(self, client, chat_id: int | str):
        """预热 Pyrogram Peer 缓存"""
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
                clean = uname.lstrip("@")
                if not clean.startswith("channel_"):
                    await client.get_chat(f"@{clean}")
        except Exception as e:
            logger.debug(f"Peer 预热失败 ({chat_id}): {e}")

    async def _process_telegram_upload(self, upload_id: str):
        """实际执行向 Telegram 频道的媒体投递与元数据入库"""
        task = self._tasks.get(upload_id)
        if not task:
            return

        file_path = task.get("assembled_file")
        safe_filename = task.get("filename")
        chat_id = task.get("chat_id")

        try:
            if not file_path or not os.path.exists(file_path):
                raise FileNotFoundError(f"暂存文件不存在: {file_path}")

            client = self._resolve_client(chat_id)
            if not client:
                raise RuntimeError("未找到可用的 Telegram 上传客户端或 Bot 尚未就绪")

            await self._ensure_peer(client, chat_id)

            def progress_callback(current, total):
                if total > 0:
                    task["tg_progress"] = round(current / total, 4)

            lower_name = safe_filename.lower()
            thumb_path = None
            sent_msg = None

            if lower_name.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                if hasattr(client, "send_photo"):
                    try:
                        sent_msg = await client.send_photo(
                            chat_id=chat_id,
                            photo=str(file_path),
                            progress=progress_callback
                        )
                    except Exception as pe:
                        logger.warning(f"以图片格式上传失败，自动回退以文档上传: {pe}")
                        sent_msg = await client.send_document(
                            chat_id=chat_id,
                            document=str(file_path),
                            file_name=safe_filename,
                            progress=progress_callback
                        )
                else:
                    sent_msg = await client.send_file(chat_id, str(file_path), progress_callback=progress_callback)

            elif lower_name.endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv')):
                thumb_path = str(file_path) + ".thumb.jpg"
                try:
                    from util import imgCoverFromFile
                    await imgCoverFromFile(str(file_path), thumb_path)
                except Exception as te:
                    logger.warning(f"生成视频封面失败，无封面继续上传: {te}")
                    thumb_path = None

                has_thumb = bool(thumb_path and os.path.exists(thumb_path))
                if hasattr(client, "send_video"):
                    sent_msg = await client.send_video(
                        chat_id=chat_id,
                        video=str(file_path),
                        file_name=safe_filename,
                        thumb=thumb_path if has_thumb else None,
                        supports_streaming=True,
                        progress=progress_callback
                    )
                else:
                    sent_msg = await client.send_file(
                        chat_id,
                        str(file_path),
                        thumb=thumb_path if has_thumb else None,
                        progress_callback=progress_callback
                    )

            elif lower_name.endswith(('.mp3', '.m4a', '.flac', '.wav', '.ogg', '.opus', '.aac')):
                if hasattr(client, "send_audio"):
                    sent_msg = await client.send_audio(
                        chat_id=chat_id,
                        audio=str(file_path),
                        file_name=safe_filename,
                        progress=progress_callback
                    )
                else:
                    sent_msg = await client.send_file(chat_id, str(file_path), progress_callback=progress_callback)

            else:
                if hasattr(client, "send_document"):
                    sent_msg = await client.send_document(
                        chat_id=chat_id,
                        document=str(file_path),
                        file_name=safe_filename,
                        progress=progress_callback
                    )
                else:
                    sent_msg = await client.send_file(chat_id, str(file_path), progress_callback=progress_callback)

            if not sent_msg:
                raise RuntimeError("Telegram 未返回有效消息对象")

            from db import save_tg_media
            media = None
            msg_media = getattr(sent_msg, "media", None)
            media_val = getattr(msg_media, "value", None)
            if media_val:
                media = getattr(sent_msg, media_val, None)
            if media is None:
                media = (
                    getattr(sent_msg, "audio", None)
                    or getattr(sent_msg, "document", None)
                    or getattr(sent_msg, "photo", None)
                    or getattr(sent_msg, "video", None)
                    or getattr(sent_msg, "voice", None)
                    or getattr(sent_msg, "video_note", None)
                    or getattr(sent_msg, "animation", None)
                )

            if media is None:
                raise RuntimeError(f"已上传到频道但未能解析 Telegram 媒体元数据: {safe_filename}")

            file_unique_id = save_tg_media(sent_msg, media, custom_file_name=safe_filename)

            msg_id = getattr(sent_msg, "id", None) or getattr(sent_msg, "message_id", None)
            chat_obj = getattr(sent_msg, "chat", None)
            actual_chat_id = getattr(chat_obj, "id", None) or chat_id

            if msg_id:
                try:
                    from thumbnail_worker import get_thumbnail_worker
                    get_thumbnail_worker().enqueue(msg_id, chat_id=actual_chat_id)
                except Exception as te:
                    logger.debug(f"派发缩略图生成任务异常(已忽略): {te}")

            if thumb_path and os.path.exists(thumb_path):
                try:
                    os.unlink(thumb_path)
                except Exception:
                    pass

            from db import get_tg_media_record_by_message_id
            record = get_tg_media_record_by_message_id(msg_id, chat_id=actual_chat_id)

            task["status"] = "completed"
            task["tg_progress"] = 1.0
            task["media"] = record or {
                "file_unique_id": file_unique_id,
                "message_id": msg_id,
                "chat_id": actual_chat_id,
                "file_name": safe_filename,
                "file_size": task.get("file_size", 0),
            }
            logger.info(f"Telegram 用户上传任务 {upload_id} 成功入库: {safe_filename} (msg_id={msg_id})")

        except Exception as exc:
            logger.error(f"Telegram 用户上传任务 {upload_id} 失败: {exc}", exc_info=True)
            task["status"] = "failed"
            task["error"] = str(exc)

        finally:
            try:
                if file_path and os.path.exists(file_path):
                    os.unlink(file_path)
                staging_dir = task.get("staging_dir")
                if staging_dir and os.path.exists(staging_dir):
                    shutil.rmtree(staging_dir, ignore_errors=True)
            except Exception as ce:
                logger.debug(f"清理暂存目录异常: {ce}")


# 单例实例
user_upload_manager = UserUploadManager()
