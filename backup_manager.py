"""
系统全量数据灾备与恢复管理器 (Backup & Disaster Recovery Manager)
================================================================
负责对 MistRelay 进行在线一致性热备（SQLite online backup API）、Telegram 协议号
Session 凭据目录、JWT 密钥以及配置文件进行打包归档、流式导出、安全校验与灾备还原。
"""

import os
import re
import time
import json
import shutil
import tarfile
import hashlib
import sqlite3
import logging
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import db

logger = logging.getLogger("backup_manager")

_BACKUP_LOCK = asyncio.Lock()
_SCHEDULER_TASK: Optional[asyncio.Task] = None


def get_db_path() -> str:
    return getattr(db, "DB_PATH", "/app/db/downloads.db")


def get_db_dir() -> str:
    return os.path.dirname(get_db_path()) or "/app/db"


def get_backup_dir() -> str:
    bdir = os.path.join(get_db_dir(), "backups")
    try:
        os.makedirs(bdir, exist_ok=True)
        if os.access(bdir, os.R_OK | os.W_OK | os.X_OK):
            return bdir
    except OSError:
        pass
    fallback_dir = os.path.join(get_db_dir(), "disaster_backups")
    os.makedirs(fallback_dir, exist_ok=True)
    return fallback_dir


def get_sessions_dir() -> str:
    sdir = os.environ.get("MISTRELAY_SESSION_DIR")
    if sdir and os.path.exists(sdir):
        return sdir
    return os.path.join(get_db_dir(), "sessions")


def _format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.2f} {units[i]}" if i > 0 else f"{int(size)} B"


def _safe_backup_filename(name: str) -> str:
    clean = os.path.basename(name).strip()
    clean = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", clean)
    if not clean.endswith((".tar.gz", ".db")):
        clean += ".tar.gz"
    return clean



# 核心灾备基线与受保护快照模式
PROTECTED_BACKUP_PATTERNS = [
    "backup_mistrelay_20260928_125911",  # 关键全量网盘数据恢复基线
    "safety_before_media_restore_",      # 媒体恢复前安全快照
    "downloads-before-",                 # 历史数据库重大变更前快照
    "immutable",
    "golden_baseline",
]


def is_protected_backup(filename: str) -> bool:
    """
    检查指定备份是否属于受保护的核心灾备基线或安全快照。
    受保护备份严禁通过任何 API、脚本或轮转策略删除。
    """
    if not filename:
        return False
    clean = os.path.basename(filename).strip()
    if clean.startswith("safety_"):
        return True
    for pat in PROTECTED_BACKUP_PATTERNS:
        if pat in clean:
            return True
    return False


def get_immutable_baseline_dir() -> str:
    """获取受只读保护的灾备基线存储目录"""
    bdir = os.path.join(get_backup_dir(), ".immutable_baseline")
    try:
        os.makedirs(bdir, exist_ok=True)
    except OSError:
        pass
    return bdir


def ensure_baseline_backups():
    """
    自愈机制：检查并确保核心灾备基线文件完整。
    若工作备份目录中核心基线丢失，自动从只读基线镜像目录恢复。
    """
    backup_dir = get_backup_dir()
    baseline_dir = get_immutable_baseline_dir()
    if not os.path.exists(baseline_dir):
        return

    try:
        for fname in os.listdir(baseline_dir):
            if not fname.endswith((".tar.gz", ".db")):
                continue
            src = os.path.join(baseline_dir, fname)
            dest = os.path.join(backup_dir, fname)
            if not os.path.exists(dest) and os.path.isfile(src):
                try:
                    shutil.copy2(src, dest)
                    logger.warning(f"自愈机制：已从只读基线恢复缺失的核心备份文件: {fname}")
                except Exception as e:
                    logger.error(f"自愈机制同步基线失败 ({fname}): {e}")
    except Exception as scan_err:
        logger.warning(f"检查只读基线目录异常: {scan_err}")


def create_backup(prefix: str = "backup_mistrelay", remark: str = "") -> Dict[str, Any]:
    """
    执行在线安全一致性快照并打包为 .tar.gz 归档。
    """
    db_path = get_db_path()
    db_dir = get_db_dir()
    backup_dir = get_backup_dir()
    sessions_dir = get_sessions_dir()

    now = datetime.now(timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    clean_prefix = re.sub(r"[^a-zA-Z0-9_\-]", "_", prefix.strip()) or "backup_mistrelay"
    tar_filename = f"{clean_prefix}_{ts_str}.tar.gz"
    tar_path = os.path.join(backup_dir, tar_filename)

    staging_dir = os.path.join(backup_dir, f".staging_{ts_str}_{os.getpid()}")
    os.makedirs(staging_dir, exist_ok=True)

    try:
        # 1. 采用 SQLite 官方在线 backup API 进行无锁安全快照 (保证事务强一致)
        snapshot_db_path = os.path.join(staging_dir, "downloads.db")
        if os.path.exists(db_path):
            src_conn = sqlite3.connect(db_path, timeout=15)
            dest_conn = sqlite3.connect(snapshot_db_path)
            try:
                with dest_conn:
                    src_conn.backup(dest_conn, pages=100)
            finally:
                dest_conn.close()
                src_conn.close()
        else:
            open(snapshot_db_path, "wb").close()

        # 计算数据库大小与 SHA256 校验和
        db_sha256 = ""
        with open(snapshot_db_path, "rb") as f:
            h = hashlib.sha256()
            while chunk := f.read(65536):
                h.update(chunk)
            db_sha256 = h.hexdigest()

        # 统计数据库内的核心指标
        db_stats = {"users": 0, "media": 0, "tg_media": 0, "protocol_accounts": 0, "downloads": 0}
        try:
            stat_conn = sqlite3.connect(snapshot_db_path)
            stat_cur = stat_conn.cursor()
            for tbl, key in [
                ("users", "users"),
                ("tg_media", "media"),
                ("tg_protocol_accounts", "protocol_accounts"),
                ("downloads", "downloads"),
            ]:
                try:
                    stat_cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                    db_stats[key] = int(stat_cur.fetchone()[0])
                except Exception:
                    pass
            db_stats["tg_media"] = db_stats["media"]
            stat_conn.close()
        except Exception:
            pass

        # 2. 复制 Sessions 凭据目录 (排除锁文件)
        staging_sessions = os.path.join(staging_dir, "sessions")
        os.makedirs(staging_sessions, exist_ok=True)
        session_files_count = 0
        if os.path.exists(sessions_dir) and os.path.isdir(sessions_dir):
            for fname in os.listdir(sessions_dir):
                if fname.endswith(("-wal", "-shm", "-journal")):
                    continue
                fpath = os.path.join(sessions_dir, fname)
                if os.path.isfile(fpath):
                    shutil.copy2(fpath, os.path.join(staging_sessions, fname))
                    session_files_count += 1

        # 3. 复制核心配置文件 (如存在)
        config_files_copied = []
        for cfg_name in ("config.yml", "jwt_signing.key", "admin-password"):
            src_cfg = os.path.join(db_dir, cfg_name)
            if os.path.exists(src_cfg) and os.path.isfile(src_cfg):
                shutil.copy2(src_cfg, os.path.join(staging_dir, cfg_name))
                config_files_copied.append(cfg_name)

        # 4. 生成 manifest.json 清单
        manifest = {
            "version": "1.0",
            "backup_format": "mistrelay_tar_gz",
            "created_at": now.isoformat(),
            "prefix": clean_prefix,
            "remark": remark or "全量数据与凭据灾备",
            "db_sha256": db_sha256,
            "db_size": os.path.getsize(snapshot_db_path),
            "session_files_count": session_files_count,
            "sessions_count": session_files_count,
            "config_files": config_files_copied,
            "stats": db_stats,
            "db_tables": db_stats,
        }
        with open(os.path.join(staging_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        # 5. 打包为 .tar.gz
        with tarfile.open(tar_path, "w:gz") as tar:
            for item in os.listdir(staging_dir):
                item_full = os.path.join(staging_dir, item)
                tar.add(item_full, arcname=item)

        file_size = os.path.getsize(tar_path)
        logger.info(f"全量数据备份成功: {tar_filename} ({_format_size(file_size)})")

        # 6. 执行保留份数轮转清理 (自动清理过旧备份)
        _enforce_retention_policy()

        return {
            "filename": tar_filename,
            "path": tar_path,
            "size": file_size,
            "size_formatted": _format_size(file_size),
            "created_at": now.isoformat(),
            "stats": db_stats,
            "session_count": session_files_count,
            "manifest": manifest,
        }
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def list_backups() -> List[Dict[str, Any]]:
    """列出备份目录中的所有备份文件，按时间倒序排列"""
    ensure_baseline_backups()
    backup_dir = get_backup_dir()
    result = []
    if not os.path.exists(backup_dir):
        return result

    for fname in os.listdir(backup_dir):
        if fname.startswith(".staging_") or fname.startswith(".tmp_"):
            continue
        if not fname.endswith((".tar.gz", ".db")):
            continue

        fpath = os.path.join(backup_dir, fname)
        if not os.path.isfile(fpath):
            continue

        stat = os.stat(fpath)
        size = stat.st_size
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        manifest = None
        is_tar = fname.endswith(".tar.gz")
        if is_tar:
            try:
                with tarfile.open(fpath, "r:gz") as tar:
                    try:
                        mf = tar.extractfile("manifest.json")
                        if mf:
                            manifest = json.loads(mf.read().decode("utf-8"))
                    except KeyError:
                        pass
            except Exception:
                pass

        remark = ""
        stats = {}
        if manifest:
            remark = manifest.get("remark", "")
            stats = manifest.get("stats", {})

        result.append({
            "filename": fname,
            "size": size,
            "size_formatted": _format_size(size),
            "created_at": mtime,
            "is_archive": is_tar,
            "type": "archive" if is_tar else "sqlite_raw",
            "is_safety_snapshot": fname.startswith("safety_pre_restore_"),
            "is_protected": is_protected_backup(fname),
            "remark": remark,
            "stats": stats,
            "manifest": manifest,
        })

    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result


def get_backup_filepath(filename: str) -> Optional[str]:
    """校验并返回备份文件的绝对安全路径（防路径遍历）"""
    clean_name = os.path.basename(filename)
    if clean_name != filename or ".." in filename or "/" in filename or "\\" in filename:
        return None
    full_path = os.path.join(get_backup_dir(), clean_name)
    if os.path.isfile(full_path):
        return full_path
    return None


def restore_backup(filename: str, mode: str = "union") -> Dict[str, Any]:
    """
    从指定备份文件恢复系统数据。
    - mode="union"（默认）：无损增量并集还原。保留现有租户与新增媒体，自动合并历史频道到 extra_channels，不覆盖现有文件。
    - mode="overwrite"：全量镜像覆盖还原。原样还原数据库与配置（仅在明确指定时执行）。
    恢复前强制执行一次「safety_pre_restore」安全快照，确保任何异常均可原路回滚。
    """
    target_path = get_backup_filepath(filename)
    if not target_path:
        raise FileNotFoundError(f"未找到指定的备份文件: {filename}")

    backup_dir = get_backup_dir()
    db_path = get_db_path()
    db_dir = get_db_dir()
    sessions_dir = get_sessions_dir()

    # 1. 恢复前安全快照 (Pre-restore safety snapshot)
    logger.info(f"开始恢复备份 {filename} (模式: {mode})，正在生成还原前安全快照...")
    safety_snap = create_backup(prefix="safety_pre_restore", remark=f"在还原 {filename} ({mode}) 前由系统自动创建的安全快照")

    staging_dir = os.path.join(backup_dir, f".restore_staging_{int(time.time())}_{os.getpid()}")
    os.makedirs(staging_dir, exist_ok=True)

    try:
        restored_db_file = None
        if filename.endswith(".tar.gz"):
            # 解压并校验
            with tarfile.open(target_path, "r:gz") as tar:
                # 校验成员路径防止目录遍历
                for member in tar.getmembers():
                    if member.name.startswith("/") or ".." in member.name:
                        raise ValueError(f"备份归档包含不安全的相对路径: {member.name}")
                tar.extractall(path=staging_dir)

            cand_db = os.path.join(staging_dir, "downloads.db")
            if os.path.isfile(cand_db):
                restored_db_file = cand_db
            else:
                # 兼容直接打包文件名
                for root, _, files in os.walk(staging_dir):
                    for f in files:
                        if f.endswith(".db"):
                            restored_db_file = os.path.join(root, f)
                            break
                    if restored_db_file:
                        break
        elif filename.endswith(".db"):
            restored_db_file = target_path

        if not restored_db_file or not os.path.isfile(restored_db_file):
            raise ValueError("备份归档中缺少有效的 SQLite 数据库文件 (downloads.db)")

        # 校验待恢复数据库完整性
        chk_conn = sqlite3.connect(restored_db_file)
        try:
            res = chk_conn.execute("PRAGMA integrity_check").fetchone()
            if not res or res[0] != "ok":
                raise ValueError(f"待还原的数据库完整性校验失败: {res}")
        finally:
            chk_conn.close()

        union_stats = {}
        restored_sessions_count = 0
        restored_configs = []

        if mode == "union":
            logger.info(f"正在以非破坏性增量并集模式 (union) 合并数据到 {db_path}...")
            restore_src = sqlite3.connect(restored_db_file)
            live_dest = sqlite3.connect(db_path, timeout=30)
            try:
                live_dest.row_factory = sqlite3.Row
                restore_src.row_factory = sqlite3.Row

                # 确保 live_dest 结构具有 extra_channels
                try:
                    live_dest.execute("ALTER TABLE users ADD COLUMN extra_channels TEXT DEFAULT '[]'")
                except sqlite3.OperationalError:
                    pass

                # 1. 迁移/合并 users
                src_users = restore_src.execute("SELECT * FROM users").fetchall()
                src_cols = [desc[0] for desc in restore_src.execute("SELECT * FROM users LIMIT 1").description]
                dest_users_map = {row["username"]: dict(row) for row in live_dest.execute("SELECT * FROM users").fetchall()}
                dest_ids_set = {int(row["id"]) for row in dest_users_map.values()}

                users_inserted = 0
                users_channels_merged = 0
                with live_dest:
                    for su in src_users:
                        uname = su["username"]
                        if uname not in dest_users_map:
                            if su["id"] not in dest_ids_set:
                                cols_to_use = src_cols
                                vals = tuple(su[c] for c in cols_to_use)
                            else:
                                cols_to_use = [c for c in src_cols if c != "id"]
                                vals = tuple(su[c] for c in cols_to_use)
                            cols_str = ", ".join(cols_to_use)
                            placeholders = ", ".join(["?"] * len(cols_to_use))
                            live_dest.execute(
                                f"INSERT OR IGNORE INTO users ({cols_str}) VALUES ({placeholders})",
                                vals
                            )
                            users_inserted += 1
                        else:
                            du = dest_users_map[uname]
                            src_cid = su["bin_channel_id"] if "bin_channel_id" in su.keys() else None
                            if src_cid and src_cid != du.get("bin_channel_id"):
                                current_extras = db.parse_extra_channels(du.get("extra_channels"))
                                if int(src_cid) not in current_extras:
                                    current_extras.append(int(src_cid))
                                    live_dest.execute(
                                        "UPDATE users SET extra_channels = ? WHERE id = ?",
                                        (json.dumps(current_extras), du["id"])
                                    )
                                    users_channels_merged += 1
                union_stats["users"] = {"inserted": users_inserted, "channels_merged": users_channels_merged}

                # 2. 合并其他关键数据表 (INSERT OR IGNORE)
                merge_tables = [
                    "tg_media", "tg_channel_files", "downloads", "uploads",
                    "edge_nodes", "tg_protocol_accounts", "config_settings"
                ]
                with live_dest:
                    for table in merge_tables:
                        try:
                            has_s = restore_src.execute(f"SELECT 1 FROM sqlite_master WHERE type='table' AND name='{table}'").fetchone()
                            has_d = live_dest.execute(f"SELECT 1 FROM sqlite_master WHERE type='table' AND name='{table}'").fetchone()
                            if not has_s or not has_d:
                                continue

                            s_cols = {d[0] for d in restore_src.execute(f"SELECT * FROM {table} LIMIT 1").description}
                            d_cols = {d[0] for d in live_dest.execute(f"SELECT * FROM {table} LIMIT 1").description}
                            common_cols = sorted(list(s_cols & d_cols))
                            if not common_cols:
                                continue

                            cols_str = ", ".join(common_cols)
                            placeholders = ", ".join(["?"] * len(common_cols))

                            count_before = live_dest.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                            cursor = restore_src.execute(f"SELECT {cols_str} FROM {table}")
                            while True:
                                batch = cursor.fetchmany(500)
                                if not batch:
                                    break
                                live_dest.executemany(
                                    f"INSERT OR IGNORE INTO {table} ({cols_str}) VALUES ({placeholders})",
                                    [tuple(row[c] for c in common_cols) for row in batch]
                                )
                            count_after = live_dest.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                            union_stats[table] = {
                                "inserted": count_after - count_before,
                                "total_now": count_after
                            }
                        except Exception as tbl_err:
                            logger.warning(f"增量并集合并表 {table} 异常 (已跳过): {tbl_err}")
            finally:
                live_dest.close()
                restore_src.close()

            # 3. 恢复缺失的会话文件 (不覆盖已有会话，保护最新登录状态)
            cand_sessions_dir = os.path.join(staging_dir, "sessions")
            if os.path.isdir(cand_sessions_dir):
                os.makedirs(sessions_dir, exist_ok=True)
                for fname in os.listdir(cand_sessions_dir):
                    sf = os.path.join(cand_sessions_dir, fname)
                    df = os.path.join(sessions_dir, fname)
                    if os.path.isfile(sf) and not os.path.exists(df):
                        shutil.copy2(sf, df)
                        restored_sessions_count += 1

            # 4. 恢复缺失的配置文件 (不覆盖已有配置)
            for cfg_name in ("config.yml", "jwt_signing.key", "admin-password"):
                cand_cfg = os.path.join(staging_dir, cfg_name)
                dest_cfg = os.path.join(db_dir, cfg_name)
                if os.path.isfile(cand_cfg) and not os.path.exists(dest_cfg):
                    shutil.copy2(cand_cfg, dest_cfg)
                    restored_configs.append(cfg_name)

            logger.info(f"从备份 {filename} 增量并集恢复完成！合并统计: {union_stats}")

        else:
            # 覆盖恢复 SQLite 数据库 (采用在线 backup API 原地写入，兼容 WAL 模式)
            logger.info(f"正在全量覆盖恢复数据库到 {db_path}...")
            restore_src = sqlite3.connect(restored_db_file)
            live_dest = sqlite3.connect(db_path, timeout=30)
            try:
                with live_dest:
                    restore_src.backup(live_dest, pages=100)
            finally:
                live_dest.close()
                restore_src.close()

            cand_sessions_dir = os.path.join(staging_dir, "sessions")
            if os.path.isdir(cand_sessions_dir):
                os.makedirs(sessions_dir, exist_ok=True)
                for fname in os.listdir(cand_sessions_dir):
                    sf = os.path.join(cand_sessions_dir, fname)
                    if os.path.isfile(sf):
                        shutil.copy2(sf, os.path.join(sessions_dir, fname))
                        restored_sessions_count += 1

            for cfg_name in ("config.yml", "jwt_signing.key", "admin-password"):
                cand_cfg = os.path.join(staging_dir, cfg_name)
                if os.path.isfile(cand_cfg):
                    shutil.copy2(cand_cfg, os.path.join(db_dir, cfg_name))
                    restored_configs.append(cfg_name)

            logger.info(f"从备份 {filename} 全量覆盖恢复完成！(还原 {restored_sessions_count} 个会话凭据, {len(restored_configs)} 个配置文件)")

        return {
            "success": True,
            "filename": filename,
            "mode": mode,
            "safety_snapshot": safety_snap["filename"],
            "sessions_restored": restored_sessions_count,
            "configs_restored": restored_configs,
            "union_stats": union_stats if mode == "union" else None,
        }
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def delete_backup(filename: str, force: bool = False) -> bool:
    """删除指定的备份文件。严禁删除核心灾备基线和安全快照。"""
    clean_name = os.path.basename(filename).strip()
    if is_protected_backup(clean_name) and not force:
        logger.error(f"安全阻断：拒绝删除受保护的核心灾备基线文件: {clean_name}")
        raise PermissionError(
            f"CRITICAL SAFETY VIOLATION: '{clean_name}' 是系统核心灾备基线或安全快照，严禁删除！"
        )

    path = get_backup_filepath(filename)
    if path and os.path.isfile(path):
        os.remove(path)
        logger.info(f"已删除备份文件: {filename}")
        return True
    return False


def save_uploaded_backup(orig_filename: str, file_bytes: bytes) -> Dict[str, Any]:
    """保存外部上传的备份文件，并执行完整性校验"""
    clean_name = _safe_backup_filename(orig_filename)
    if not clean_name.startswith("backup_"):
        clean_name = f"backup_uploaded_{int(time.time())}_{clean_name}"

    backup_dir = get_backup_dir()
    dest_path = os.path.join(backup_dir, clean_name)

    temp_path = os.path.join(backup_dir, f".tmp_upload_{os.getpid()}_{clean_name}")
    try:
        with open(temp_path, "wb") as f:
            f.write(file_bytes)

        # 校验归档合法性
        if clean_name.endswith(".tar.gz"):
            with tarfile.open(temp_path, "r:gz") as tar:
                names = tar.getnames()
                has_db = any(n.endswith(".db") for n in names)
                if not has_db:
                    raise ValueError("上传的归档中不包含有效 SQLite 数据库文件 (*.db)")
        elif clean_name.endswith(".db"):
            conn = sqlite3.connect(temp_path)
            try:
                res = conn.execute("PRAGMA integrity_check").fetchone()
                if not res or res[0] != "ok":
                    raise ValueError("上传的文件并非合法的 SQLite 数据库文件")
            finally:
                conn.close()

        os.replace(temp_path, dest_path)
        size = os.path.getsize(dest_path)
        logger.info(f"成功保存上传备份: {clean_name} ({_format_size(size)})")
        return {
            "filename": clean_name,
            "size": size,
            "size_formatted": _format_size(size),
        }
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _enforce_retention_policy():
    """根据配置的 BACKUP_MAX_KEEP 轮转清理超额旧备份"""
    try:
        max_keep = int(db.get_config("BACKUP_MAX_KEEP", 15) or 15)
        if max_keep <= 0:
            return
        backups = list_backups()
        if len(backups) > max_keep:
            # 严格过滤掉所有受保护基线与安全快照，永不淘汰
            candidates = [b for b in backups if not b.get("is_protected") and not is_protected_backup(b["filename"])]
            if len(candidates) > max_keep:
                to_delete = candidates[max_keep:]
                for b in to_delete:
                    try:
                        delete_backup(b["filename"])
                    except Exception as del_err:
                        logger.warning(f"轮转清理备份失败 ({b['filename']}): {del_err}")
    except Exception as e:
        logger.warning(f"备份轮转清理检查失败 (已忽略): {e}")


def get_backup_schedule() -> Dict[str, Any]:
    return {
        "enabled": bool(db.get_config("BACKUP_AUTO_ENABLED", False)),
        "interval_hours": int(db.get_config("BACKUP_INTERVAL_HOURS", 24) or 24),
        "max_keep": int(db.get_config("BACKUP_MAX_KEEP", 15) or 15),
        "last_run": str(db.get_config("BACKUP_LAST_RUN", "") or ""),
    }


def set_backup_schedule(enabled: bool, interval_hours: int, max_keep: int) -> Dict[str, Any]:
    db.set_config("BACKUP_AUTO_ENABLED", bool(enabled))
    db.set_config("BACKUP_INTERVAL_HOURS", max(1, min(168, int(interval_hours))))
    db.set_config("BACKUP_MAX_KEEP", max(3, min(100, int(max_keep))))
    return get_backup_schedule()


def export_tenant_data(user_id: int) -> Dict[str, Any]:
    """
    导出指定租户的独立数据备份归档（元数据、媒体索引、关联频道、下载历史）。
    严格剔除全局 Bot Token、系统密钥及其他租户的隐私数据。
    """
    user = db.get_user_by_id(user_id)
    if not user:
        raise ValueError(f"租户不存在: ID {user_id}")

    safe_user = {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "tg_user_id": user.get("tg_user_id"),
        "tg_username": user.get("tg_username"),
        "tg_first_name": user.get("tg_first_name"),
        "dc_id": user.get("dc_id"),
        "bin_channel_id": user.get("bin_channel_id"),
        "bin_channel_username": user.get("bin_channel_username"),
        "extra_channels": db.parse_extra_channels(user.get("extra_channels")),
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
    }

    channel_ids = db.get_user_all_channel_ids(user)

    media_records = []
    if channel_ids:
        placeholders = ",".join(["?"] * len(channel_ids))
        with db.db_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT file_unique_id, chat_id, message_id, file_id,
                       file_name, mime_type, file_size, duration,
                       width, height, caption, message_date,
                       media_group_id, supports_streaming
                FROM tg_media
                WHERE chat_id IN ({placeholders})
                ORDER BY message_date DESC
                """,
                tuple(channel_ids),
            ).fetchall()
            media_records = [dict(r) for r in rows]

    channel_files = []
    with db.db_conn() as conn:
        conn.row_factory = sqlite3.Row
        has_tc_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tg_channel_files'").fetchone()
        if has_tc_table and channel_ids:
            placeholders = ",".join(["?"] * len(channel_ids))
            rows = conn.execute(
                f"""
                SELECT id, file_unique_id, owner_tg_user_id, owner_tg_username,
                       source_chat_id, source_message_id, source_media_group_id,
                       storage_channel_id, storage_message_id, storage_file_id,
                       file_name, mime_type, file_size, duration, width, height,
                       caption, message_date, archive_hash, stream_url,
                       supports_streaming, flow_status, created_at, updated_at
                FROM tg_channel_files
                WHERE storage_channel_id IN ({placeholders})
                ORDER BY created_at DESC
                """,
                tuple(channel_ids),
            ).fetchall()
            channel_files = [dict(r) for r in rows]

    downloads_records = []
    with db.db_conn() as conn:
        conn.row_factory = sqlite3.Row
        has_dl_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='downloads'").fetchone()
        if has_dl_table:
            where_conds = ["user_id = ?"]
            params = [user_id]
            if channel_ids:
                placeholders = ",".join(["?"] * len(channel_ids))
                where_conds.append(f"target_channel_id IN ({placeholders})")
                params.extend(channel_ids)
            rows = conn.execute(
                f"""
                SELECT *
                FROM downloads
                WHERE {' OR '.join(where_conds)}
                ORDER BY id DESC
                """,
                tuple(params),
            ).fetchall()
            downloads_records = [dict(r) for r in rows]

    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "export_version": "1.0",
        "exported_at": now_iso,
        "tenant": safe_user,
        "channel_ids": channel_ids,
        "stats": {
            "media_count": len(media_records),
            "media_total_bytes": sum(int(m.get("file_size") or 0) for m in media_records),
            "channel_files_count": len(channel_files),
            "downloads_count": len(downloads_records),
        },
        "media": media_records,
        "channel_files": channel_files,
        "downloads": downloads_records,
    }
