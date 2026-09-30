import pyrogram_patch
"""
租户专属存储频道无损平移与容灾迁移调度器 (Channel Migration Manager)
====================================================================
支持在 Telegram 协议号母号异常、风控封禁或 DC 迁移时，自动调配健康协议号开通新频道，
并通过 Telegram MTProto 原生 copy_message 在服务端极速无损镜像原频道历史媒体，
原子更新数据库指针与缩略图缓存映射，原频道原始数据全量保留，实现前台直链与网盘零感知平滑过渡。
"""

import os
import time
import shutil
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import db

logger = logging.getLogger("channel_migrator")


class ChannelMigrationTask:
    def __init__(
        self,
        task_id: str,
        user_id: int,
        username: str,
        source_channel_id: int,
        source_channel_username: Optional[str] = None,
        target_dc_id: int = 5,
        custom_target_channel_id: Optional[int] = None,
    ):
        self.task_id = task_id
        self.user_id = user_id
        self.username = username
        self.source_channel_id = source_channel_id
        self.source_channel_username = source_channel_username
        self.target_dc_id = target_dc_id
        self.custom_target_channel_id = custom_target_channel_id

        self.target_channel_id: Optional[int] = None
        self.target_channel_username: Optional[str] = None
        self.target_creator_id: Optional[int] = None
        self.actual_dc_id: int = target_dc_id

        self.status: str = "pending"  # pending, running, completed, failed, cancelled
        self.total_files: int = 0
        self.migrated_files: int = 0
        self.skipped_files: int = 0
        self.failed_files: int = 0
        self.progress_percent: float = 0.0
        self.current_file_name: str = ""

        self.error_message: Optional[str] = None
        self.started_at: str = datetime.now(timezone.utc).isoformat()
        self.finished_at: Optional[str] = None
        self.cancel_requested: bool = False
        self.logs: List[Dict[str, Any]] = []

    def add_log(self, msg: str, level: str = "info"):
        t_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.logs.append({"time": t_str, "level": level, "msg": msg})
        if len(self.logs) > 300:
            self.logs = self.logs[-250:]
        if level == "error":
            logger.error(f"[{self.username} 迁移] {msg}")
        elif level == "warning":
            logger.warning(f"[{self.username} 迁移] {msg}")
        else:
            logger.info(f"[{self.username} 迁移] {msg}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "username": self.username,
            "source_channel_id": self.source_channel_id,
            "source_channel_username": self.source_channel_username,
            "target_channel_id": self.target_channel_id,
            "target_channel_username": self.target_channel_username,
            "target_dc_id": self.actual_dc_id,
            "status": self.status,
            "total_files": self.total_files,
            "migrated_files": self.migrated_files,
            "skipped_files": self.skipped_files,
            "failed_files": self.failed_files,
            "progress_percent": round(self.progress_percent, 1),
            "current_file_name": self.current_file_name,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "logs": self.logs,
        }


class ChannelMigrationManager:
    def __init__(self):
        self._tasks: Dict[int, ChannelMigrationTask] = {}
        self._running_async_tasks: Dict[int, asyncio.Task] = {}

    def get_task(self, user_id: int) -> Optional[ChannelMigrationTask]:
        return self._tasks.get(user_id)

    def is_running(self, user_id: int) -> bool:
        t = self._tasks.get(user_id)
        return t is not None and t.status in ("pending", "running")

    async def start_migration(
        self,
        user_id: int,
        target_dc_id: Optional[int] = None,
        custom_target_channel_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if self.is_running(user_id):
            raise RuntimeError("当前用户已有正在运行的专属频道迁移任务")

        u = db.get_user_by_id(user_id)
        if not u:
            raise ValueError("用户不存在")
        if not u.get("bin_channel_id"):
            raise ValueError("该用户尚未开通任何专属存储频道，无法执行迁移")

        source_cid = int(u["bin_channel_id"])
        source_uname = u.get("bin_channel_username")
        dc_val = int(target_dc_id or u.get("dc_id") or 5)

        task_id = f"mig_{user_id}_{int(time.time())}"
        task = ChannelMigrationTask(
            task_id=task_id,
            user_id=user_id,
            username=u["username"],
            source_channel_id=source_cid,
            source_channel_username=source_uname,
            target_dc_id=dc_val,
            custom_target_channel_id=int(custom_target_channel_id) if custom_target_channel_id else None,
        )
        self._tasks[user_id] = task

        async_task = asyncio.create_task(self._run_migration(task))
        self._running_async_tasks[user_id] = async_task
        return task.to_dict()

    async def cancel_migration(self, user_id: int) -> bool:
        task = self._tasks.get(user_id)
        if not task or task.status not in ("pending", "running"):
            return False
        task.cancel_requested = True
        task.add_log("收到用户中止请求，正在安全停止任务...", level="warning")
        return True

    async def _run_migration(self, task: ChannelMigrationTask):
        task.status = "running"
        task.add_log(f"启动专属频道平移任务 (用户: {task.username}, 原频道: {task.source_channel_id})")

        try:
            # Step 1: 准备目标新频道
            if task.custom_target_channel_id:
                task.target_channel_id = task.custom_target_channel_id
                task.target_channel_username = f"channel_{abs(task.target_channel_id)}"
                task.add_log(f"使用用户指定的已有目标存储频道: {task.target_channel_id}")
            else:
                task.add_log(f"正在从协议号资产池优选 DC{task.target_dc_id} 健康协议号创建新专属频道...")
                from botfather_creator import provision_user_storage_channel
                chan_meta = await provision_user_storage_channel(
                    username=task.username,
                    target_dc_id=task.target_dc_id,
                    tg_user_id=None,
                )
                task.target_channel_id = chan_meta["bin_channel_id"]
                task.target_channel_username = chan_meta["bin_channel_username"]
                task.target_creator_id = chan_meta.get("creator_account_id")
                task.actual_dc_id = chan_meta.get("dc_id", task.target_dc_id)
                task.add_log(
                    f"新存储频道创建成功: @{task.target_channel_username} (ID: {task.target_channel_id}, DC{task.actual_dc_id})",
                    level="success",
                )

            # Step 2: 预热机器人 Peer 映射
            from WebStreamer.bot import StreamBot
            if StreamBot and getattr(StreamBot, "is_connected", False):
                for ch_id, ch_uname in [
                    (task.source_channel_id, task.source_channel_username),
                    (task.target_channel_id, task.target_channel_username),
                ]:
                    try:
                        if hasattr(StreamBot, "get_chat"):
                            await StreamBot.get_chat(ch_id)
                        elif hasattr(StreamBot, "resolve_peer"):
                            await StreamBot.resolve_peer(ch_id)
                    except Exception:
                        if ch_uname and not str(ch_uname).startswith("channel_"):
                            try:
                                await StreamBot.get_chat(f"@{str(ch_uname).lstrip('@')}")
                            except Exception as e:
                                logger.debug(f"预热 @{ch_uname} 忽略: {e}")

            # Step 3: 查询源频道全部历史媒体记录
            records = db.fetch_channel_media_records(task.source_channel_id)
            task.total_files = len(records)
            task.add_log(f"源频道共检索到 {task.total_files} 个媒体记录需要平移")

            if task.total_files == 0:
                task.add_log("原频道无媒体文件，直接完成专属频道指针绑定", level="success")
                db.finalize_channel_migration(
                    user_id=task.user_id,
                    old_chat_id=task.source_channel_id,
                    new_chat_id=task.target_channel_id,
                    new_username=task.target_channel_username,
                    new_dc_id=task.actual_dc_id,
                    new_creator_id=task.target_creator_id,
                )
                task.progress_percent = 100.0
                task.status = "completed"
                task.finished_at = datetime.now(timezone.utc).isoformat()
                return

            # Step 4: 逐批执行 Telegram 原生 copy_message 极速无损克隆
            from WebStreamer.bot import StreamBot
            cloning_bot = StreamBot
            if not cloning_bot or not getattr(cloning_bot, "is_connected", False):
                from WebStreamer.bot.clients import multi_clients
                for bot_cli in multi_clients.values():
                    if getattr(bot_cli, "is_connected", False):
                        cloning_bot = bot_cli
                        break

            if not cloning_bot:
                raise RuntimeError("机器人集群无可用在线 Bot 客户端执行媒体克隆")

            task.add_log(f"使用机器人 @{getattr(cloning_bot, 'username', 'StreamBot')} 执行服务端媒体无损克隆...")

            thumb_cache_dir = Path("/app/cache/thumbnails/telegram")
            if not thumb_cache_dir.exists():
                thumb_cache_dir = Path("cache/thumbnails/telegram")

            for idx, rec in enumerate(records):
                if task.cancel_requested:
                    task.status = "cancelled"
                    task.add_log("迁移任务已被用户手动中止", level="warning")
                    task.finished_at = datetime.now(timezone.utc).isoformat()
                    return

                old_mid = int(rec["message_id"])
                fname = rec.get("file_name") or f"msg_{old_mid}"
                task.current_file_name = fname

                copied_mid = None
                copied_file_id = None

                # 尝试执行 copy_message 并捕获 FloodWait
                for attempt in range(3):
                    try:
                        copied_msg = await cloning_bot.copy_message(
                            chat_id=task.target_channel_id,
                            from_chat_id=task.source_channel_id,
                            message_id=old_mid,
                        )
                        if copied_msg:
                            copied_mid = copied_msg.id
                            for media_attr in ("video", "document", "audio", "photo"):
                                obj = getattr(copied_msg, media_attr, None)
                                if obj and hasattr(obj, "file_id"):
                                    copied_file_id = obj.file_id
                                    break
                        break
                    except Exception as e:
                        err_str = str(e)
                        if "FLOOD_WAIT" in err_str:
                            wait_s = 5
                            import re
                            m = re.search(r"FLOOD_WAIT_(\d+)", err_str)
                            if m:
                                wait_s = int(m.group(1)) + 1
                            task.add_log(f"触发 Telegram 频控，安全等待 {wait_s} 秒后自动重试...", level="warning")
                            await asyncio.sleep(wait_s)
                            continue
                        elif any(k in err_str for k in ("MESSAGE_ID_INVALID", "MESSAGE_EMPTY", "CHAT_WRITE_FORBIDDEN")):
                            task.add_log(f"跳过源消息 #{old_mid} ({fname}): {e}", level="warning")
                            break
                        else:
                            if attempt == 2:
                                task.add_log(f"克隆消息 #{old_mid} ({fname}) 失败: {e}", level="error")
                            await asyncio.sleep(0.5)

                if copied_mid:
                    # 原子重定向数据库单条媒体指针
                    db.remap_single_media_pointer(
                        old_chat_id=task.source_channel_id,
                        old_msg_id=old_mid,
                        new_chat_id=task.target_channel_id,
                        new_msg_id=copied_mid,
                        new_file_id=copied_file_id or rec.get("file_id"),
                    )

                    # 迁移缩略图缓存文件 (平滑重定向，前端无需重新造图)
                    if thumb_cache_dir.exists():
                        try:
                            old_prefix = f"{task.source_channel_id}_{old_mid}_"
                            for f in thumb_cache_dir.glob(f"{old_prefix}*.webp"):
                                new_name = f.name.replace(old_prefix, f"{task.target_channel_id}_{copied_mid}_")
                                new_thumb = thumb_cache_dir / new_name
                                if not new_thumb.exists():
                                    try:
                                        shutil.copy2(f, new_thumb)
                                    except Exception:
                                        pass
                        except Exception:
                            pass

                    task.migrated_files += 1
                else:
                    task.skipped_files += 1

                task.progress_percent = ((idx + 1) / task.total_files) * 100.0

                if (idx + 1) % 10 == 0 or (idx + 1) == task.total_files:
                    task.add_log(
                        f"平移进度: {idx + 1}/{task.total_files} ({task.progress_percent:.1f}%) · 已无损克隆: {task.migrated_files} 个"
                    )

                # 极短微延迟，平滑请求节奏
                await asyncio.sleep(0.1)

            # Step 5: 完成频道与用户专属绑定指针切换
            task.add_log("正在原子切换租户专属存储频道与关联任务指针...", level="info")
            db.finalize_channel_migration(
                user_id=task.user_id,
                old_chat_id=task.source_channel_id,
                new_chat_id=task.target_channel_id,
                new_username=task.target_channel_username,
                new_dc_id=task.actual_dc_id,
                new_creator_id=task.target_creator_id,
            )

            task.progress_percent = 100.0
            task.status = "completed"
            task.finished_at = datetime.now(timezone.utc).isoformat()
            task.add_log(
                f"🎉 专属频道无损平移全部圆满完成！新专属频道: @{task.target_channel_username} (已克隆 {task.migrated_files} 个文件，原频道历史消息完整保留)",
                level="success",
            )
        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            task.finished_at = datetime.now(timezone.utc).isoformat()
            task.add_log(f"专属频道平移失败: {e}", level="error")
        finally:
            self._running_async_tasks.pop(task.user_id, None)


_migration_manager: Optional[ChannelMigrationManager] = None


def get_migration_manager() -> ChannelMigrationManager:
    global _migration_manager
    if _migration_manager is None:
        _migration_manager = ChannelMigrationManager()
    return _migration_manager
