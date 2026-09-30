"""
MistRelay 缓存治理引擎 (Cache Manager)

统筹管理:
1. 缩略图缓存 (cache/thumbnails)
2. 本地下载与临时文件缓存 (downloads / SAVE_PATH)
3. Rclone VFS 挂载缓存 (cache/rclone)
4. 运行期内存缓存 (ThumbnailGenerator LRU, ByteStreamer 会话, 配置缓存)
5. 自动清理策略与容量指标统计
"""

import asyncio
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from download_cleanup import (
    DEFAULT_RETENTION_HOURS,
    DEFAULT_INTERVAL_SECONDS,
    _resolve_download_dir,
    _is_dangerous_root,
    _is_within,
    _collect_aria2_protected_paths,
    _collect_database_protected_paths,
    _path_age_seconds,
    run_download_cleanup_once,
    get_cleanup_settings,
)
from thumbnail_generator import get_thumbnail_generator

logger = logging.getLogger("cache_manager")

DEFAULT_THUMBNAIL_RETENTION_DAYS = 7


def _get_repo_root() -> Path:
    return Path(__file__).resolve().parent


def resolve_thumbnail_dir() -> Path:
    tg = get_thumbnail_generator()
    return tg.cache_dir


def resolve_downloads_dir() -> Path:
    from configer import get_config_value
    save_path = get_config_value("SAVE_PATH", "/data/downloads")
    resolved = _resolve_download_dir(save_path)
    if not resolved.exists():
        repo_downloads = _get_repo_root() / "downloads"
        if repo_downloads.exists():
            return repo_downloads
    return resolved


def resolve_rclone_dir() -> Path:
    rclone_path = _get_repo_root() / "cache" / "rclone"
    if not rclone_path.exists():
        rclone_path = Path("/app/cache/rclone")
    return rclone_path


def get_disk_stats() -> dict[str, Any]:
    """获取磁盘总体利用率与可用容量"""
    # 优先检测下载存储所在磁盘分区，其次检测根路径
    check_paths = [resolve_downloads_dir(), _get_repo_root(), Path("/")]
    for path in check_paths:
        try:
            if path.exists():
                usage = shutil.disk_usage(path)
                percent = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0
                return {
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                    "total_gb": round(usage.total / (1024 ** 3), 2),
                    "used_gb": round(usage.used / (1024 ** 3), 2),
                    "free_gb": round(usage.free / (1024 ** 3), 2),
                    "percent": percent,
                    "path": str(path),
                }
        except Exception:
            continue

    return {
        "total_bytes": 0,
        "used_bytes": 0,
        "free_bytes": 0,
        "total_gb": 0,
        "used_gb": 0,
        "free_gb": 0,
        "percent": 0,
        "path": "/",
    }


def get_thumbnail_stats() -> dict[str, Any]:
    """获取缩略图缓存统计数据"""
    tg = get_thumbnail_generator()
    thumb_dir = tg.cache_dir
    if not thumb_dir.exists():
        return {
            "total_files": 0,
            "total_bytes": 0,
            "total_size_mb": 0.0,
            "cache_dir": str(thumb_dir),
            "sub_sources": {},
            "expired_files": 0,
            "expired_bytes": 0,
        }

    from configer import get_config_value
    try:
        retention_days = int(get_config_value("THUMBNAIL_CACHE_MAX_AGE_DAYS", DEFAULT_THUMBNAIL_RETENTION_DAYS))
    except (TypeError, ValueError):
        retention_days = DEFAULT_THUMBNAIL_RETENTION_DAYS

    expiry_time = datetime.now() - timedelta(days=retention_days)

    total_files = 0
    total_bytes = 0
    expired_files = 0
    expired_bytes = 0
    sub_sources: dict[str, dict[str, Any]] = {}

    for item in thumb_dir.iterdir():
        if item.is_dir() and not item.is_symlink():
            sub_count = 0
            sub_bytes = 0
            for file_path in item.rglob("*.webp"):
                try:
                    stat = file_path.stat()
                    sub_count += 1
                    sub_bytes += stat.st_size
                    if datetime.fromtimestamp(stat.st_mtime) < expiry_time:
                        expired_files += 1
                        expired_bytes += stat.st_size
                except OSError:
                    continue
            sub_sources[item.name] = {
                "total_files": sub_count,
                "total_bytes": sub_bytes,
                "total_size_mb": round(sub_bytes / (1024 * 1024), 2),
            }
            total_files += sub_count
            total_bytes += sub_bytes
        elif item.is_file() and item.name.endswith(".webp"):
            try:
                stat = item.stat()
                total_files += 1
                total_bytes += stat.st_size
                if datetime.fromtimestamp(stat.st_mtime) < expiry_time:
                    expired_files += 1
                    expired_bytes += stat.st_size
            except OSError:
                continue

    return {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
        "cache_dir": str(thumb_dir),
        "sub_sources": sub_sources,
        "expired_files": expired_files,
        "expired_bytes": expired_bytes,
        "expired_size_mb": round(expired_bytes / (1024 * 1024), 2),
        "retention_days": retention_days,
    }


async def get_downloads_stats(aria2_client: Any = None) -> dict[str, Any]:
    """获取下载目录与临时文件缓存统计"""
    root = resolve_downloads_dir()
    settings = get_cleanup_settings()
    retention_hours = settings["retention_hours"]

    if _is_dangerous_root(root) or not root.exists() or not root.is_dir():
        return {
            "root": str(root),
            "total_files": 0,
            "total_bytes": 0,
            "total_size_mb": 0.0,
            "protected_files": 0,
            "cleanable_files": 0,
            "cleanable_bytes": 0,
            "cleanable_size_mb": 0.0,
            "recent_files": 0,
            "retention_hours": retention_hours,
        }

    protected: set[Path] = set()
    try:
        if aria2_client is not None:
            protected.update(await _collect_aria2_protected_paths(aria2_client, root))
    except Exception:
        logger.warning("查询 aria2 保护任务失败", exc_info=True)
    protected.update(_collect_database_protected_paths(root))

    cutoff_seconds = retention_hours * 3600
    now = time.time()

    total_files = 0
    total_bytes = 0
    protected_count = 0
    cleanable_files = 0
    cleanable_bytes = 0
    recent_files = 0

    for path in root.rglob("*"):
        try:
            if path.is_dir() and not path.is_symlink():
                continue
            resolved = path.resolve(strict=False)
            if not _is_within(resolved, root):
                continue

            total_files += 1
            size = path.lstat().st_size
            total_bytes += size

            if resolved in protected:
                protected_count += 1
                continue

            if _path_age_seconds(path, now) < cutoff_seconds:
                recent_files += 1
                continue

            cleanable_files += 1
            cleanable_bytes += size
        except (FileNotFoundError, OSError):
            continue

    return {
        "root": str(root),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
        "protected_files": protected_count,
        "cleanable_files": cleanable_files,
        "cleanable_bytes": cleanable_bytes,
        "cleanable_size_mb": round(cleanable_bytes / (1024 * 1024), 2),
        "recent_files": recent_files,
        "retention_hours": retention_hours,
    }


def get_rclone_stats() -> dict[str, Any]:
    """获取 Rclone VFS 挂载缓存统计"""
    rclone_dir = resolve_rclone_dir()
    if not rclone_dir.exists() or not rclone_dir.is_dir():
        return {
            "root": str(rclone_dir),
            "total_files": 0,
            "total_bytes": 0,
            "total_size_mb": 0.0,
        }

    total_files = 0
    total_bytes = 0
    for file_path in rclone_dir.rglob("*"):
        try:
            if file_path.is_file() and not file_path.is_symlink():
                total_files += 1
                total_bytes += file_path.stat().st_size
        except OSError:
            continue

    return {
        "root": str(rclone_dir),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
    }


def get_memory_stats() -> dict[str, Any]:
    """获取运行期内存缓存状态"""
    tg = get_thumbnail_generator()
    lru_info = {}
    if hasattr(tg, "_get_cached_path") and hasattr(tg._get_cached_path, "cache_info"):
        info = tg._get_cached_path.cache_info()
        lru_info = {
            "hits": info.hits,
            "misses": info.misses,
            "maxsize": info.maxsize,
            "currsize": info.currsize,
        }

    stream_sessions = 0
    try:
        from WebStreamer.server.stream_routes import class_cache
        stream_sessions = len(class_cache)
    except Exception:
        pass

    config_cache_entries = 0
    try:
        from configer import _config_cache
        config_cache_entries = len(_config_cache)
    except Exception:
        pass

    return {
        "thumbnail_lru": lru_info,
        "stream_sessions": stream_sessions,
        "config_cache_entries": config_cache_entries,
    }


async def get_all_cache_stats(aria2_client: Any = None) -> dict[str, Any]:
    """获取全站缓存与存储健康度综合数据"""
    disk = get_disk_stats()
    thumbnails = get_thumbnail_stats()
    downloads = await get_downloads_stats(aria2_client)
    rclone = get_rclone_stats()
    memory = get_memory_stats()

    total_cache_bytes = thumbnails["total_bytes"] + downloads["total_bytes"] + rclone["total_bytes"]
    total_cache_files = thumbnails["total_files"] + downloads["total_files"] + rclone["total_files"]

    return {
        "disk": disk,
        "total_cache_bytes": total_cache_bytes,
        "total_cache_size_mb": round(total_cache_bytes / (1024 * 1024), 2),
        "total_cache_files": total_cache_files,
        "thumbnails": thumbnails,
        "downloads": downloads,
        "rclone": rclone,
        "memory": memory,
    }


def clean_orphaned_telegram_thumbnails(dry_run: bool = False) -> dict[str, Any]:
    """
    全量审计并清理 cache/thumbnails/telegram/ 目录下与 tg_media 表失联的孤儿缩略图
    """
    tg = get_thumbnail_generator()
    tg_thumb_dir = tg.cache_dir / "telegram"
    if not tg_thumb_dir.exists():
        return {
            "category": "orphaned_telegram_thumbnails",
            "scanned_files": 0,
            "deleted_files": 0,
            "deleted_bytes": 0,
            "deleted_size_mb": 0.0,
            "dry_run": dry_run,
        }

    import db
    default_bin = None
    try:
        from WebStreamer.vars import Var
        default_bin = getattr(Var, "BIN_CHANNEL", None)
    except Exception:
        pass

    valid_hashes = set()
    try:
        with db.db_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT message_id, file_name, chat_id FROM tg_media").fetchall()
            for r in rows:
                mid = r["message_id"]
                fname = r["file_name"] or ""
                cid = r["chat_id"]
                keys = [f"{mid}_{fname}"]
                if cid is not None and str(cid) != str(default_bin):
                    keys.append(f"{cid}_{mid}_{fname}")
                for k in keys:
                    h = tg._get_cache_key("telegram", k)
                    valid_hashes.add(f"{h}.webp")
    except Exception as e:
        logger.debug(f"查询有效 tg_media 缩略图键异常: {e}")

    scanned_files = 0
    deleted_files = 0
    deleted_bytes = 0

    for item in tg_thumb_dir.glob("*.webp"):
        if not item.is_file():
            continue
        scanned_files += 1
        name = item.name
        if name.startswith("fallback-"):
            continue

        if name not in valid_hashes:
            try:
                stat = item.stat()
                deleted_bytes += stat.st_size
                deleted_files += 1
                if not dry_run:
                    item.unlink(missing_ok=True)
            except OSError:
                continue

    if not dry_run and hasattr(tg, "_get_cached_path"):
        try:
            tg._get_cached_path.cache_clear()
        except Exception:
            pass

    return {
        "category": "orphaned_telegram_thumbnails",
        "scanned_files": scanned_files,
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
        "deleted_size_mb": round(deleted_bytes / (1024 * 1024), 2),
        "dry_run": dry_run,
    }


def clean_thumbnails(
    retention_days: Optional[int] = None,
    purge_all: bool = False,
    dry_run: bool = False,
    sub_source: Optional[str] = None,
    purge_orphans: bool = False,
) -> dict[str, Any]:
    """清理缩略图缓存"""
    from path_security import validate_child_name
    tg = get_thumbnail_generator()
    thumb_dir = tg.cache_dir
    target_dir = thumb_dir
    if sub_source:
        safe_sub = validate_child_name(sub_source)
        target_dir = (thumb_dir / safe_sub).resolve(strict=False)
        if not _is_within(target_dir, thumb_dir.resolve(strict=False)):
            raise ValueError("非法的子缓存目录路径")

    if _is_dangerous_root(thumb_dir) or not target_dir.exists():
        return {
            "category": "thumbnails",
            "scanned_files": 0,
            "deleted_files": 0,
            "deleted_bytes": 0,
            "deleted_size_mb": 0.0,
            "dry_run": dry_run,
        }

    if retention_days is None:
        from configer import get_config_value
        try:
            retention_days = int(get_config_value("THUMBNAIL_CACHE_MAX_AGE_DAYS", DEFAULT_THUMBNAIL_RETENTION_DAYS))
        except (TypeError, ValueError):
            retention_days = DEFAULT_THUMBNAIL_RETENTION_DAYS

    expiry_time = datetime.now() - timedelta(days=retention_days)

    scanned_files = 0
    deleted_files = 0
    deleted_bytes = 0

    for item in target_dir.rglob("*.webp"):
        try:
            if not _is_within(item.resolve(strict=False), thumb_dir):
                continue
            scanned_files += 1
            stat = item.stat()
            should_delete = purge_all or (datetime.fromtimestamp(stat.st_mtime) < expiry_time)
            if should_delete:
                deleted_files += 1
                deleted_bytes += stat.st_size
                if not dry_run:
                    item.unlink(missing_ok=True)
        except (FileNotFoundError, OSError):
            continue

    if not dry_run and hasattr(tg, "_get_cached_path"):
        tg._get_cached_path.cache_clear()

    # 执行时间策略清理后，核销已在数据库中删除的孤儿缩略图
    orphan_deleted_files = 0
    orphan_deleted_bytes = 0
    if purge_orphans and not purge_all and (sub_source is None or sub_source == "telegram"):
        try:
            orphan_res = clean_orphaned_telegram_thumbnails(dry_run=dry_run)
            orphan_deleted_files = orphan_res.get("deleted_files", 0)
            orphan_deleted_bytes = orphan_res.get("deleted_bytes", 0)
            deleted_files += orphan_deleted_files
            deleted_bytes += orphan_deleted_bytes
        except Exception as e:
            logger.debug(f"核销孤儿缩略图异常: {e}")

    return {
        "category": "thumbnails",
        "purge_all": purge_all,
        "retention_days": retention_days,
        "scanned_files": scanned_files,
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
        "deleted_size_mb": round(deleted_bytes / (1024 * 1024), 2),
        "dry_run": dry_run,
    }


async def clean_downloads(
    aria2_client: Any = None,
    retention_hours: Optional[int] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """清理下载目录中的过期临时文件（保留活跃任务）"""
    res = await run_download_cleanup_once(
        aria2_client,
        retention_hours=retention_hours,
        dry_run=dry_run,
    )
    stale_uploads_info = {}
    try:
        from telegram_user_uploader import user_upload_manager
        stale_uploads_info = user_upload_manager.cleanup_stale_uploads()
    except Exception as e:
        logger.debug(f"清理废弃上传分片异常: {e}")
    return {
        "category": "downloads",
        "root": res.get("root"),
        "retention_hours": res.get("retention_hours"),
        "scanned_files": res.get("scanned_files", 0),
        "deleted_files": res.get("deleted_files", 0),
        "deleted_bytes": res.get("deleted_bytes", 0),
        "deleted_size_mb": round(res.get("deleted_bytes", 0) / (1024 * 1024), 2),
        "deleted_dirs": res.get("deleted_dirs", 0),
        "skipped_protected": res.get("skipped_protected", 0),
        "skipped_recent": res.get("skipped_recent", 0),
        "dry_run": dry_run,
    }


def clean_rclone(dry_run: bool = False) -> dict[str, Any]:
    """清空 Rclone VFS 挂载缓存"""
    rclone_dir = resolve_rclone_dir()
    if _is_dangerous_root(rclone_dir) or not rclone_dir.exists() or not rclone_dir.is_dir():
        return {
            "category": "rclone",
            "scanned_files": 0,
            "deleted_files": 0,
            "deleted_bytes": 0,
            "deleted_size_mb": 0.0,
            "dry_run": dry_run,
        }

    scanned_files = 0
    deleted_files = 0
    deleted_bytes = 0

    for file_path in rclone_dir.rglob("*"):
        try:
            if file_path.is_file() and not file_path.is_symlink():
                if not _is_within(file_path.resolve(strict=False), rclone_dir):
                    continue
                scanned_files += 1
                size = file_path.stat().st_size
                deleted_files += 1
                deleted_bytes += size
                if not dry_run:
                    file_path.unlink(missing_ok=True)
        except (FileNotFoundError, OSError):
            continue

    return {
        "category": "rclone",
        "scanned_files": scanned_files,
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
        "deleted_size_mb": round(deleted_bytes / (1024 * 1024), 2),
        "dry_run": dry_run,
    }


def clean_memory() -> dict[str, Any]:
    """重置与刷新运行期内存缓存"""
    tg = get_thumbnail_generator()
    if hasattr(tg, "_get_cached_path"):
        tg._get_cached_path.cache_clear()

    sessions_cleared = 0
    try:
        from WebStreamer.server.stream_routes import class_cache
        sessions_cleared = len(class_cache)
        class_cache.clear()
    except Exception:
        pass

    try:
        from configer import reload_config
        reload_config()
    except Exception:
        pass

    try:
        import db
        db.cleanup_expired_auth_sessions()
        db.cleanup_expired_edge_node_tokens()
        db.cleanup_expired_tg_register_codes()
    except Exception as e:
        logger.debug(f"内存清理阶段核销过期会话与凭证异常: {e}")

    return {
        "category": "memory",
        "status": "cleared",
        "sessions_cleared": sessions_cleared,
        "dry_run": False,
    }


async def clean_cache_category(
    category: str,
    aria2_client: Any = None,
    retention_hours: Optional[int] = None,
    retention_days: Optional[int] = None,
    purge_all: bool = False,
    dry_run: bool = False,
    sub_source: Optional[str] = None,
) -> dict[str, Any]:
    """分类或全量执行缓存治理动作"""
    if category == "thumbnails":
        return clean_thumbnails(
            retention_days=retention_days,
            purge_all=purge_all,
            dry_run=dry_run,
            sub_source=sub_source,
        )
    elif category == "downloads":
        return await clean_downloads(aria2_client=aria2_client, retention_hours=retention_hours, dry_run=dry_run)
    elif category == "rclone":
        return clean_rclone(dry_run=dry_run)
    elif category == "memory":
        return clean_memory()
    elif category == "all":
        thumb_res = clean_thumbnails(retention_days=retention_days, purge_all=purge_all, dry_run=dry_run)
        down_res = await clean_downloads(aria2_client=aria2_client, retention_hours=retention_hours, dry_run=dry_run)
        rclone_res = clean_rclone(dry_run=dry_run)
        mem_res = clean_memory() if not dry_run else {"category": "memory", "status": "skipped_in_dry_run"}

        total_deleted_files = (
            thumb_res.get("deleted_files", 0) + down_res.get("deleted_files", 0) + rclone_res.get("deleted_files", 0)
        )
        total_deleted_bytes = (
            thumb_res.get("deleted_bytes", 0) + down_res.get("deleted_bytes", 0) + rclone_res.get("deleted_bytes", 0)
        )

        return {
            "category": "all",
            "deleted_files": total_deleted_files,
            "deleted_bytes": total_deleted_bytes,
            "deleted_size_mb": round(total_deleted_bytes / (1024 * 1024), 2),
            "dry_run": dry_run,
            "details": {
                "thumbnails": thumb_res,
                "downloads": down_res,
                "rclone": rclone_res,
                "memory": mem_res,
            },
        }
    else:
        raise ValueError(f"未知的缓存类别: {category}")


def get_cache_policy() -> dict[str, Any]:
    """读取自动清理策略配置"""
    from configer import get_config_value
    settings = get_cleanup_settings()
    try:
        thumb_days = int(get_config_value("THUMBNAIL_CACHE_MAX_AGE_DAYS", DEFAULT_THUMBNAIL_RETENTION_DAYS))
    except (TypeError, ValueError):
        thumb_days = DEFAULT_THUMBNAIL_RETENTION_DAYS

    return {
        "DOWNLOAD_CLEANUP_ENABLED": bool(settings.get("enabled", True)),
        "DOWNLOAD_RETENTION_HOURS": int(settings.get("retention_hours", DEFAULT_RETENTION_HOURS)),
        "DOWNLOAD_CLEANUP_INTERVAL_SECONDS": int(settings.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)),
        "THUMBNAIL_CACHE_MAX_AGE_DAYS": thumb_days,
    }


def update_cache_policy(updates: dict[str, Any]) -> dict[str, Any]:
    """更新自动清理策略配置并即时持久化到数据库"""
    from db import set_configs
    from configer import reload_config

    db_updates = []
    if "DOWNLOAD_CLEANUP_ENABLED" in updates:
        val = bool(updates["DOWNLOAD_CLEANUP_ENABLED"])
        db_updates.append(("DOWNLOAD_CLEANUP_ENABLED", val, "bool", "download", "是否启用下载目录自动清理"))

    if "DOWNLOAD_RETENTION_HOURS" in updates:
        val = max(1, int(updates["DOWNLOAD_RETENTION_HOURS"]))
        db_updates.append(("DOWNLOAD_RETENTION_HOURS", val, "int", "download", "下载文件保留小时数"))

    if "DOWNLOAD_CLEANUP_INTERVAL_SECONDS" in updates:
        val = max(60, int(updates["DOWNLOAD_CLEANUP_INTERVAL_SECONDS"]))
        db_updates.append(("DOWNLOAD_CLEANUP_INTERVAL_SECONDS", val, "int", "download", "下载目录清理间隔秒数"))

    if "THUMBNAIL_CACHE_MAX_AGE_DAYS" in updates:
        val = max(1, int(updates["THUMBNAIL_CACHE_MAX_AGE_DAYS"]))
        db_updates.append(("THUMBNAIL_CACHE_MAX_AGE_DAYS", val, "int", "cache", "缩略图缓存保留天数"))

    if db_updates:
        set_configs(db_updates)
        reload_config()

    return get_cache_policy()
