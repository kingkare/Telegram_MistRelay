"""
Telegram 网盘媒体缩略图后台预生成与预热工作器 (TelegramThumbnailWorker)

职责：
1. 启动预热：服务就绪后，在后台静默扫描数据库中的存量媒体，对未生成缩略图的项目低速平滑入队预生成；
2. 增量即时：新媒体入库（save_tg_media）后立即排队异步生成，避免前端用户首次查看时等待；
3. 多租户隔离：支持按专属频道 chat_id 识别、调度与状态统计，避免不同租户同 ID 冲突；
4. 防限流平滑限速：每个项目处理完成后间隔 0.5s，并复用并发信号量，保障流播带宽；
5. 状态监测与手动控制：提供进度指标与手动重新触发预热功能。
"""

import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional, Set, Tuple

from db import get_tg_media_stats, list_all_tg_media_records
from thumbnail_generator import get_thumbnail_generator

logger = logging.getLogger("thumbnail_worker")


class TelegramThumbnailWorker:
    """Telegram 缩略图后台预热与异步生成工作器"""

    def __init__(self):
        self.running: bool = False
        self.current_message_id: Optional[int] = None
        self.current_chat_id: Optional[int] = None
        self.failed_ids: Set[int] = set()
        self.failed_tasks: Set[Tuple[Optional[int], int]] = set()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._queued_ids: Set[int] = set()
        self._queued_tasks: Set[Tuple[Optional[int], int]] = set()
        self._worker_task: Optional[asyncio.Task] = None
        self._scan_lock: asyncio.Lock = asyncio.Lock()
        self._ensure_func: Optional[Callable] = None

    def set_ensure_func(self, func: Callable):
        """显式设置缩略图生成核心函数（便于测试或依赖注入）"""
        self._ensure_func = func

    def _get_stream_routes_module(self):
        import sys
        mod = sys.modules.get("WebStreamer.server.stream_routes") or sys.modules.get("test_stream_routes")
        if mod is not None:
            return mod
        from WebStreamer.server import stream_routes
        return stream_routes

    def _get_ensure_func(self) -> Callable:
        if self._ensure_func is not None:
            return self._ensure_func
        return self._get_stream_routes_module().ensure_telegram_thumbnail

    def _ensure_worker_task(self):
        """确保后台消费协程处于运行状态"""
        if self._worker_task is None or self._worker_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._worker_task = loop.create_task(self._worker_loop())
            except RuntimeError:
                pass

    def enqueue(
        self,
        message_id: int,
        file_name: Optional[str] = None,
        force: bool = False,
        chat_id: Optional[int] = None,
    ) -> bool:
        """
        将 (message_id, chat_id) 加入后台生成队列。
        若已在队列或已存在有效缓存（force=False），则自动去重跳过。
        """
        cid = int(chat_id) if chat_id is not None else None
        mid = int(message_id)
        task_key = (cid, mid)

        if task_key in self._queued_tasks:
            return False

        if not force:
            generator = get_thumbnail_generator()
            default_bin = None
            try:
                from WebStreamer.vars import Var
                default_bin = getattr(Var, "BIN_CHANNEL", None)
            except Exception:
                pass

            if file_name:
                if cid is not None and str(cid) != str(default_bin):
                    cache_key = f"{cid}_{mid}_{file_name}"
                else:
                    cache_key = f"{mid}_{file_name}"
                if generator.is_cached("telegram", cache_key):
                    return False

        self._queued_tasks.add(task_key)
        self._queued_ids.add(mid)
        self._queue.put_nowait((mid, cid))
        self._ensure_worker_task()
        return True

    async def start_full_scan(self, force: bool = False, chat_id: Optional[int] = None) -> dict:
        """
        扫描数据库全部 tg_media 记录，将缺失缩略图的记录入队处理。
        支持指定 chat_id 仅扫描与入队该租户频道的媒体。
        """
        async with self._scan_lock:
            records = list_all_tg_media_records()
            generator = get_thumbnail_generator()
            sr = self._get_stream_routes_module()
            get_download_file_name = sr.get_download_file_name
            is_thumbnail_supported_mime = sr.is_thumbnail_supported_mime

            default_bin = None
            try:
                from WebStreamer.vars import Var
                default_bin = getattr(Var, "BIN_CHANNEL", None)
            except Exception:
                pass

            queued_count = 0
            scanned_count = 0
            for record in records:
                mid = record.get("message_id")
                r_cid = record.get("chat_id")
                r_cid_val = int(r_cid) if r_cid is not None else None

                if not mid or int(mid) <= 0:
                    continue

                if chat_id is not None and r_cid_val != int(chat_id):
                    continue

                scanned_count += 1
                mid_val = int(mid)
                task_key = (r_cid_val, mid_val)
                if task_key in self._queued_tasks:
                    continue

                # 检查格式是否支持生成缩略图
                mime = record.get("mime_type") or ""
                file_name = record.get("file_name") or ""
                is_supported = is_thumbnail_supported_mime(mime) or any(
                    file_name.lower().endswith(ext)
                    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".mp4", ".mkv", ".webm", ".mov", ".avi")
                )
                if not is_supported:
                    continue

                if not force:
                    dl_name = get_download_file_name(record)
                    if r_cid_val is not None and str(r_cid_val) != str(default_bin):
                        cache_key = f"{r_cid_val}_{mid_val}_{dl_name}"
                    else:
                        cache_key = f"{mid_val}_{dl_name}"
                    if generator.is_cached("telegram", cache_key):
                        continue

                self._queued_tasks.add(task_key)
                self._queued_ids.add(mid_val)
                self._queue.put_nowait((mid_val, r_cid_val))
                queued_count += 1

            if queued_count > 0:
                self._ensure_worker_task()
                logger.info(f"后台缩略图扫描完成，新增入队任务: {queued_count} 项")

            return {
                "total_scanned": scanned_count,
                "queued": queued_count,
                "running": bool(self.running or not self._queue.empty()),
            }

    async def delayed_startup_scan(self, delay_seconds: float = 5.0):
        """服务启动后延迟执行首次存量扫描预热"""
        try:
            await asyncio.sleep(delay_seconds)
            logger.info("开始执行服务启动后的后台缩略图自动预热扫描...")
            await self.start_full_scan(force=False)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"后台缩略图自动预热扫描失败: {e}", exc_info=True)

    def get_status(self, chat_id: Optional[int] = None) -> dict:
        """获取当前后台预热进度与统计数据（支持按租户 chat_id 隔离统计）"""
        try:
            stats = get_tg_media_stats(chat_id=chat_id) if chat_id is not None else get_tg_media_stats()
            total_media = (stats.get("videos") or 0) + (stats.get("images") or 0)
            if total_media == 0:
                total_media = stats.get("total_count") or 0
        except Exception:
            total_media = 0

        generator = get_thumbnail_generator()
        default_bin = None
        try:
            from WebStreamer.vars import Var
            default_bin = getattr(Var, "BIN_CHANNEL", None)
        except Exception:
            pass

        if chat_id is not None:
            target_cid = int(chat_id)
            cached_count = 0
            sr = self._get_stream_routes_module()
            get_download_file_name = getattr(sr, "get_download_file_name", lambda r: r.get("file_name") or "")
            try:
                records = list_all_tg_media_records()
                for rec in records:
                    r_cid = rec.get("chat_id")
                    if r_cid is not None and int(r_cid) == target_cid:
                        mid = rec.get("message_id")
                        if mid and int(mid) > 0:
                            dl_name = get_download_file_name(rec)
                            if str(target_cid) != str(default_bin):
                                ckey = f"{target_cid}_{mid}_{dl_name}"
                            else:
                                ckey = f"{mid}_{dl_name}"
                            if generator.is_cached("telegram", ckey):
                                cached_count += 1
            except Exception:
                cached_count = 0

            # 统计当前队列中属于该租户的在途任务数
            pending_count = sum(
                1 for task in list(getattr(self._queue, "_queue", ()))
                if (isinstance(task, tuple) and len(task) > 1 and task[1] is not None and int(task[1]) == target_cid)
            )
            is_running = bool(
                (self.running and self.current_chat_id == target_cid) or pending_count > 0
            )
            effective_total = max(total_media, cached_count + pending_count)
            current_mid = self.current_message_id if (is_running and self.current_chat_id == target_cid) else None
        else:
            cache_dir = generator.cache_dir / "telegram"
            cached_count = 0
            if cache_dir.exists():
                for f in cache_dir.glob("*.webp"):
                    if not f.name.startswith("fallback-") and f.stat().st_size > 64:
                        cached_count += 1
            pending_count = self._queue.qsize()
            effective_total = max(total_media, cached_count + pending_count)
            is_running = bool(self.running or not self._queue.empty())
            current_mid = self.current_message_id if is_running else None

        percent = round((cached_count / effective_total * 100), 1) if effective_total > 0 else 100.0
        percent = min(100.0, max(0.0, percent))

        return {
            "running": is_running,
            "total": effective_total,
            "cached": cached_count,
            "pending": pending_count,
            "percent": percent,
            "current_message_id": current_mid,
        }

    async def _worker_loop(self):
        """后台队列消费循环"""
        logger.info("后台缩略图处理 Worker 协程已启动")
        ensure_func = self._get_ensure_func()

        while True:
            try:
                task = await self._queue.get()
                if isinstance(task, tuple):
                    message_id = int(task[0])
                    chat_id = int(task[1]) if task[1] is not None else None
                else:
                    message_id = int(task)
                    chat_id = None

                task_key = (chat_id, message_id)
                self.running = True
                self.current_message_id = message_id
                self.current_chat_id = chat_id

                try:
                    try:
                        res = await ensure_func(message_id, chat_id=chat_id)
                    except TypeError:
                        res = await ensure_func(message_id)

                    path, cache_hit = res if isinstance(res, tuple) else (res, False)
                    if path is None or "fallback" in str(path):
                        self.failed_tasks.add(task_key)
                        self.failed_ids.add(message_id)
                    else:
                        self.failed_tasks.discard(task_key)
                        self.failed_ids.discard(message_id)
                except Exception as e:
                    self.failed_tasks.add(task_key)
                    self.failed_ids.add(message_id)
                    logger.debug(f"后台预生成缩略图失败 message_id={message_id}, chat_id={chat_id}: {e}")

                self._queued_tasks.discard(task_key)
                self._queued_ids.discard(message_id)
                self._queue.task_done()

                if self._queue.empty():
                    self.running = False
                    self.current_message_id = None
                    self.current_chat_id = None

                # 平滑休眠，防止触发 Telegram FloodWait
                await asyncio.sleep(0.5)

            except asyncio.CancelledError:
                self.running = False
                self.current_message_id = None
                self.current_chat_id = None
                break
            except Exception as e:
                logger.error(f"后台缩略图 Worker 异常: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    async def stop(self):
        """停止 Worker 任务"""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self.running = False
        self.current_message_id = None
        self.current_chat_id = None


_thumbnail_worker: Optional[TelegramThumbnailWorker] = None


def get_thumbnail_worker() -> TelegramThumbnailWorker:
    """获取全局缩略图工作器单例"""
    global _thumbnail_worker
    if _thumbnail_worker is None:
        _thumbnail_worker = TelegramThumbnailWorker()
    return _thumbnail_worker
