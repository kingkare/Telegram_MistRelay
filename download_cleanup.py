import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from configer import get_config_value


DEFAULT_RETENTION_HOURS = 24
DEFAULT_INTERVAL_SECONDS = 3600
DEFAULT_INITIAL_DELAY_SECONDS = 60

ACTIVE_DOWNLOAD_STATUSES = {"pending", "downloading", "waiting", "paused"}
ACTIVE_UPLOAD_STATUSES = {"pending", "waiting_download", "uploading", "paused"}


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "enabled"}:
            return True
        if text in {"0", "false", "no", "off", "disabled"}:
            return False
    return default


def _as_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(number, minimum)


def get_cleanup_settings() -> dict[str, Any]:
    return {
        "enabled": _as_bool(get_config_value("DOWNLOAD_CLEANUP_ENABLED", True), True),
        "retention_hours": _as_int(
            get_config_value("DOWNLOAD_RETENTION_HOURS", DEFAULT_RETENTION_HOURS),
            DEFAULT_RETENTION_HOURS,
        ),
        "interval_seconds": _as_int(
            get_config_value("DOWNLOAD_CLEANUP_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS),
            DEFAULT_INTERVAL_SECONDS,
            minimum=60,
        ),
        "save_path": get_config_value("SAVE_PATH", "/data/downloads"),
    }


def _resolve_download_dir(raw_path: str | os.PathLike[str] | None) -> Path:
    if not raw_path:
        raw_path = "/data/downloads"
    path = Path(str(raw_path)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve(strict=False)


def _is_dangerous_root(path: Path) -> bool:
    dangerous = {
        Path("/"),
        Path("/app"),
        Path("/root"),
        Path.home().resolve(strict=False),
        Path.cwd().resolve(strict=False),
    }
    return path in dangerous


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _iter_task_paths(task: dict[str, Any]) -> set[Path]:
    paths: set[Path] = set()
    for file_info in task.get("files") or []:
        file_path = file_info.get("path")
        if file_path:
            path = Path(str(file_path)).expanduser()
            paths.add(path)
            paths.add(Path(f"{path}.aria2"))
    return paths


async def _collect_aria2_protected_paths(aria2_client: Any, root: Path) -> set[Path]:
    protected: set[Path] = set()
    if aria2_client is None:
        return protected

    tasks: list[dict[str, Any]] = []
    tasks.extend(await aria2_client.tell_active())
    tasks.extend(await aria2_client.tell_waiting(0, 1000))

    for task in tasks:
        for path in _iter_task_paths(task):
            resolved = path.resolve(strict=False)
            if _is_within(resolved, root):
                protected.add(resolved)
    return protected


def _collect_database_protected_paths(root: Path) -> set[Path]:
    try:
        from db import db_conn
    except Exception:
        return set()

    protected: set[Path] = set()
    try:
        with db_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT name
                  FROM sqlite_master
                 WHERE type = 'table'
                   AND name IN ('downloads', 'uploads')
                """
            )
            tables = {row[0] for row in cur.fetchall()}
            if {'downloads', 'uploads'} - tables:
                return protected

            download_placeholders = ",".join("?" for _ in ACTIVE_DOWNLOAD_STATUSES)
            upload_placeholders = ",".join("?" for _ in ACTIVE_UPLOAD_STATUSES)
            cur.execute(
                f"""
                SELECT DISTINCT d.local_path
                  FROM downloads AS d
                  LEFT JOIN uploads AS u ON u.download_id = d.id
                 WHERE d.local_path IS NOT NULL
                   AND d.local_path != ''
                   AND (
                        d.status IN ({download_placeholders})
                        OR u.status IN ({upload_placeholders})
                   )
                """,
                tuple(ACTIVE_DOWNLOAD_STATUSES) + tuple(ACTIVE_UPLOAD_STATUSES),
            )
            for (raw_path,) in cur.fetchall():
                path = Path(str(raw_path)).expanduser().resolve(strict=False)
                if _is_within(path, root):
                    protected.add(path)
                    protected.add(Path(f"{path}.aria2").resolve(strict=False))
    except Exception:
        logging.getLogger("bot").warning("读取下载清理保护列表失败", exc_info=True)
    return protected


def _path_age_seconds(path: Path, now: float) -> float:
    stat = path.lstat()
    return now - max(stat.st_mtime, stat.st_ctime)


def _delete_empty_dirs(root: Path, protected: set[Path], logger: logging.Logger, dry_run: bool) -> int:
    removed = 0
    dirs = [path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()]
    for directory in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        resolved = directory.resolve(strict=False)
        if resolved in protected:
            continue
        try:
            if any(directory.iterdir()):
                continue
            if not dry_run:
                directory.rmdir()
            removed += 1
        except OSError:
            continue
        except Exception:
            logger.warning("删除空下载目录失败: %s", directory, exc_info=True)
    return removed


async def run_download_cleanup_once(
    aria2_client: Any,
    *,
    logger: logging.Logger | None = None,
    save_path: str | os.PathLike[str] | None = None,
    retention_hours: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    logger = logger or logging.getLogger("bot")
    settings = get_cleanup_settings()
    root = _resolve_download_dir(save_path if save_path is not None else settings["save_path"])
    retention = _as_int(retention_hours or settings["retention_hours"], DEFAULT_RETENTION_HOURS)

    result: dict[str, Any] = {
        "root": str(root),
        "retention_hours": retention,
        "scanned_files": 0,
        "deleted_files": 0,
        "deleted_bytes": 0,
        "deleted_dirs": 0,
        "skipped_protected": 0,
        "skipped_recent": 0,
        "errors": 0,
        "dry_run": dry_run,
    }

    if _is_dangerous_root(root):
        logger.warning("下载清理跳过危险路径: %s", root)
        result["skipped_reason"] = "dangerous_root"
        return result
    if not root.exists() or not root.is_dir():
        logger.info("下载清理跳过不存在的目录: %s", root)
        result["skipped_reason"] = "missing_root"
        return result

    try:
        protected = await _collect_aria2_protected_paths(aria2_client, root)
    except Exception:
        logger.warning("下载清理无法查询 aria2 任务，跳过本轮以避免误删", exc_info=True)
        result["skipped_reason"] = "aria2_unavailable"
        return result
    protected.update(_collect_database_protected_paths(root))

    cutoff_seconds = retention * 3600
    now = time.time()

    for path in root.rglob("*"):
        try:
            if path.is_dir() and not path.is_symlink():
                continue
            resolved = path.resolve(strict=False)
            if not _is_within(resolved, root):
                continue
            result["scanned_files"] += 1
            if resolved in protected:
                result["skipped_protected"] += 1
                continue
            if _path_age_seconds(path, now) < cutoff_seconds:
                result["skipped_recent"] += 1
                continue

            size = path.lstat().st_size
            if not dry_run:
                path.unlink()
            result["deleted_files"] += 1
            result["deleted_bytes"] += size
        except FileNotFoundError:
            continue
        except Exception:
            result["errors"] += 1
            logger.warning("删除过期下载文件失败: %s", path, exc_info=True)

    result["deleted_dirs"] = _delete_empty_dirs(root, protected, logger, dry_run)
    logger.info(
        "下载目录清理完成: root=%s retention=%sh scanned=%s deleted=%s bytes=%s dirs=%s protected=%s recent=%s errors=%s",
        result["root"],
        result["retention_hours"],
        result["scanned_files"],
        result["deleted_files"],
        result["deleted_bytes"],
        result["deleted_dirs"],
        result["skipped_protected"],
        result["skipped_recent"],
        result["errors"],
    )
    return result


async def download_cleanup_loop(aria2_client: Any, logger: logging.Logger | None = None) -> None:
    logger = logger or logging.getLogger("bot")
    await asyncio.sleep(DEFAULT_INITIAL_DELAY_SECONDS)
    while True:
        settings = get_cleanup_settings()
        if settings["enabled"]:
            await run_download_cleanup_once(
                aria2_client,
                logger=logger,
                retention_hours=settings["retention_hours"],
            )
        await asyncio.sleep(settings["interval_seconds"])


def start_download_cleanup_loop(aria2_client: Any, logger: logging.Logger | None = None) -> asyncio.Task:
    logger = logger or logging.getLogger("bot")
    settings = get_cleanup_settings()
    logger.info(
        "下载目录清理策略已启用: enabled=%s retention=%sh interval=%ss path=%s",
        settings["enabled"],
        settings["retention_hours"],
        settings["interval_seconds"],
        settings["save_path"],
    )
    return asyncio.create_task(download_cleanup_loop(aria2_client, logger))
