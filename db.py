import secrets
"""
SQLite 数据库模块
=================

本模块主要用于记录两个维度的数据：

- tg_media  表：存放从 Telegram（Pyrogram Message/Media）解析出来的“媒体元数据”
  - file_unique_id       : Telegram 提供的全局唯一 ID，作为主键
  - chat_id / message_id : 消息所在聊天与消息 ID，用于去重与回查原消息
  - from_user_id         : 发送用户 ID（私聊/群聊）
  - sender_chat_id       : 频道 ID（频道帖子）
  - file_id              : 真正下载用的 file_id（bot 专属）
  - file_name            : 文件名
  - mime_type            : MIME 类型（video/mp4 等）
  - file_size            : 文件大小（字节）
  - duration/width/height: 媒体时长与分辨率
  - caption              : 说明文本
  - caption_entities     : 说明文本中的实体（hashtag、粗体等），JSON 字符串
  - message_date         : 消息时间（ISO8601 字符串）
  - media_group_id       : 媒体组 ID，相册/多媒体时使用
  - has_media_spoiler    : 是否剧透遮罩（0/1）
  - supports_streaming   : 是否支持流式播放（0/1）
  - thumbs               : 缩略图相关信息，预留为 JSON 字符串
  - extra                : 预留扩展字段（JSON 字符串）

- downloads 表：存放下载任务（aria2）与本地/网盘路径信息
  - id               : 自增主键
  - file_unique_id   : 外键，关联 tg_media
  - gid              : aria2 任务 ID
  - source_url       : 用于下载的直链 URL（WebStreamer 生成）
  - status           : 下载状态（pending/downloading/completed/failed）
  - total_length     : 文件总大小（字节）
  - completed_length : 已完成大小（字节）
  - download_speed   : 当前下载速度（字节/秒）
  - error_message    : 失败原因
  - retry_count      : 重试次数
  - local_path       : 本地最终文件路径
  - save_dir         : 本地保存目录
  - remote_path      : 历史远程路径（兼容旧第三方网盘记录）
  - upload_status    : 上传状态（pending/uploading/uploaded/failed 等）
  - created_at       : 创建时间（加入下载队列）
  - started_at       : 实际开始下载时间
  - completed_at     : 完成时间
  - updated_at       : 最近更新时间
"""

import os
import sys
import re
import tempfile
from typing import Optional, Dict, Any, List
import ipaddress
import sqlite3
import hashlib
import hmac
import base64
import json
import logging
import stat
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from legacy_config import (
    legacy_config_path,
    legacy_yaml_bootstrap_enabled,
    load_legacy_config,
    retire_legacy_config,
)

logger = logging.getLogger(__name__)

# 数据库路径：优先使用环境变量，否则使用 /app/db/downloads.db（确保在挂载的卷中）
_script_dir = os.path.dirname(os.path.abspath(__file__))
_repo_db_dir = os.path.join(_script_dir, "db")
if os.path.exists(_repo_db_dir):
    _default_db_path = os.path.join(_repo_db_dir, "downloads.db")
else:
    _default_db_path = os.path.join("/app/db", "downloads.db")
DB_PATH = os.environ.get("MISTRELAY_DB_PATH", _default_db_path)

# 确保数据库目录存在
_db_dir = os.path.dirname(DB_PATH)
if _db_dir and not os.path.exists(_db_dir):
    os.makedirs(_db_dir, exist_ok=True)


def _now_iso() -> str:
    """返回UTC时间的ISO8601格式字符串，带'Z'后缀表示UTC时区"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def get_default_edge_domain(ip: str) -> str:
    """
    根据 IPv4/IPv6 地址自动生成标准 sslip.io 泛解析域名。
    例如: 16.162.23.244 -> edge.16-162-23-244.sslip.io
    若输入已经是自定义域名则保留原域名；若为空或环回/私网地址则返回空。
    """
    if not ip or not isinstance(ip, str):
        return ""
    clean_ip = ip.strip().lower()
    if not clean_ip:
        return ""
    if any(c.isalpha() for c in clean_ip) and not clean_ip.startswith("127."):
        if clean_ip in ("localhost", "local"):
            return ""
        return clean_ip
    try:
        ip_obj = ipaddress.ip_address(clean_ip)
        if ip_obj.is_loopback:
            return ""
        if isinstance(ip_obj, ipaddress.IPv4Address):
            dashed = str(ip_obj).replace(".", "-")
            return f"edge.{dashed}.sslip.io"
        elif isinstance(ip_obj, ipaddress.IPv6Address):
            dashed = str(ip_obj).replace(":", "-")
            return f"edge.{dashed}.sslip.io"
    except ValueError:
        pass
    if "." in clean_ip and not any(c.isalpha() for c in clean_ip):
        dashed = clean_ip.replace(".", "-")
        return f"edge.{dashed}.sslip.io"
    return ""


def _format_message_date(msg_date) -> str:
    """格式化消息日期为ISO8601格式，确保带时区信息"""
    if not msg_date:
        return _now_iso()
    # Pyrogram的message.date是UTC时间的datetime对象
    # 转换为ISO格式并添加'Z'后缀表示UTC
    iso_str = msg_date.isoformat()
    # 如果已经有时区信息（带+或-），保持不变；否则添加'Z'
    if 'Z' in iso_str or '+' in iso_str or (len(iso_str) > 10 and iso_str[-6] in '+-'):
        return iso_str
    # 移除微秒部分（如果有），只保留秒级精度
    if '.' in iso_str:
        iso_str = iso_str.split('.')[0]
    return iso_str + 'Z'


def is_production_db_path(path: Optional[str] = None) -> bool:
    """检查给定的数据库路径是否指向真实的生产数据库"""
    target = os.path.abspath(path or DB_PATH)
    # 临时目录、内存数据库或包含 _test / sandbox 的路径视为非生产沙箱
    temp_dir = tempfile.gettempdir()
    if target.startswith(temp_dir) or "tmp" in target.lower() or "_test" in target or "sandbox" in target:
        return False
    prod_candidates = [
        os.path.abspath(os.path.join(_script_dir, "db", "downloads.db")),
        os.path.abspath("/app/db/downloads.db"),
        os.path.abspath("/root/MistRelay-dev/db/downloads.db"),
    ]
    return target in prod_candidates


def is_testing_environment() -> bool:
    """检测当前运行时是否处于测试模式"""
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("MISTRELAY_TEST_MODE") == "1":
        return True
    if "pytest" in sys.modules:
        return True
    return False


def _test_mode_authorizer(action, arg1, arg2, dbname, source):
    """
    SQLite 引擎层内核级只读防护 Authorizer 回调函数。
    当处于测试模式且目标连接为生产数据库时，强行拦截所有破坏性 / 写入性 SQL 操作。
    """
    DENIED_ACTIONS = (
        sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_DROP_TEMP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_INDEX,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_DROP_VIEW,
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_ALTER_TABLE,
    )
    if action in DENIED_ACTIONS:
        logger.critical(
            f"CRITICAL SAFETY VIOLATION BLOCKED: Refused test-mode mutating action ({action}) "
            f"on production database '{DB_PATH}'! Tests must use an isolated sandbox database."
        )
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-64000;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA mmap_size=268435456;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")

    # 铁律防护：若在测试环境中且连接目标是生产库，强行安装 authorizer 阻断所有写入和删除
    if is_testing_environment() and is_production_db_path(DB_PATH):
        logger.warning(
            f"SAFETY GUARD ENGAGED: Connection opened to production database '{DB_PATH}' during testing! "
            f"Mutating queries will be blocked by SQLite authorizer."
        )
        conn.set_authorizer(_test_mode_authorizer)

    return conn


@contextmanager
def db_conn():
    """获取数据库连接的上下文管理器，退出时自动 commit + close。"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        yield conn.cursor()
        conn.commit()
    finally:
        conn.close()


def init_db():
    """初始化 SQLite 数据库（如果不存在就建表）"""
    with db_cursor() as cur:
        # Telegram 媒体信息
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tg_media (
                file_unique_id     TEXT PRIMARY KEY, -- Telegram 提供的全局唯一 ID，主键
                chat_id            INTEGER NOT NULL, -- 消息所属聊天 ID（频道/群/私聊）
                message_id         INTEGER NOT NULL, -- 消息 ID
                from_user_id       INTEGER,          -- 发送用户 ID（私聊/群聊）
                sender_chat_id     INTEGER,          -- 发送频道 ID（频道帖子）
                file_id            TEXT NOT NULL,    -- 实际用于下载的 file_id（bot 专属）
                file_name          TEXT,             -- 文件名
                mime_type          TEXT,             -- MIME 类型，如 video/mp4
                file_size          INTEGER,          -- 文件大小（字节）
                duration           INTEGER,          -- 媒体时长（秒）
                width              INTEGER,          -- 媒体宽度（像素）
                height             INTEGER,          -- 媒体高度（像素）
                caption            TEXT,             -- 说明文本
                caption_entities   TEXT,             -- 说明文本中的实体（hashtag 等），JSON 字符串
                message_date       TEXT NOT NULL,    -- 消息时间，ISO8601 字符串
                media_group_id     TEXT,             -- 媒体组 ID（相册/多媒体）
                has_media_spoiler  INTEGER,          -- 是否启用剧透遮罩（0/1）
                supports_streaming INTEGER,          -- 是否支持流式播放（0/1）
                thumbs             TEXT,             -- 缩略图信息，JSON 字符串（预留）
                extra              TEXT              -- 扩展字段，JSON 字符串（预留）
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_tg_media_chat_message ON tg_media (chat_id, message_id)"
        )
        cur.execute(
            "DROP INDEX IF EXISTS idx_tg_media_chat_msg"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_tg_media_chat_date ON tg_media (chat_id, message_date DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_tg_media_media_group ON tg_media (media_group_id)"
        )

        # 下载任务信息
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS downloads (
                id               INTEGER PRIMARY KEY AUTOINCREMENT, -- 自增主键
                file_unique_id   TEXT NOT NULL,                     -- 关联 tg_media.file_unique_id
                gid              TEXT,                              -- aria2 任务 ID
                source_url       TEXT,                              -- 用于下载的直链 URL
                status           TEXT NOT NULL DEFAULT 'pending',   -- 下载状态：pending/downloading/completed/failed
                total_length     INTEGER,                           -- 文件总大小（字节）
                completed_length INTEGER,                           -- 已完成大小（字节）
                download_speed   INTEGER,                           -- 当前下载速度（字节/秒）
                error_message    TEXT,                              -- 错误信息（失败原因）
                retry_count      INTEGER DEFAULT 0,                 -- 重试次数
                local_path       TEXT,                              -- 本地最终文件路径
                save_dir         TEXT,                              -- 本地保存目录
                remote_path      TEXT,                              -- 历史远程路径（兼容旧第三方网盘记录）
                upload_status    TEXT,                              -- 上传状态：pending/uploading/uploaded/failed
                created_at       TEXT NOT NULL,                     -- 创建时间（加入下载队列）
                started_at       TEXT,                              -- 实际开始下载时间
                completed_at     TEXT,                              -- 下载完成时间
                updated_at       TEXT NOT NULL,                     -- 最近更新时间
                FOREIGN KEY (file_unique_id) REFERENCES tg_media(file_unique_id) ON DELETE CASCADE -- 关联 Telegram 媒体
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_downloads_file_unique_id ON downloads (file_unique_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads (status)"
        )

        # 上传任务信息
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS uploads (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT, -- 自增主键
                download_id         INTEGER NOT NULL,                  -- 关联 downloads.id
                upload_target       TEXT NOT NULL,                     -- 上传目标：telegram；旧库可能包含 onedrive/gdrive
                remote_path         TEXT,                              -- 远程路径
                status              TEXT NOT NULL DEFAULT 'pending',   -- 上传状态：pending/waiting_download/uploading/completed/failed/cancelled/paused
                failure_reason      TEXT,                              -- 失败原因分类：download_failed/code_error/network_error等
                error_message       TEXT,                              -- 详细错误信息
                error_code          TEXT,                              -- 错误代码
                total_size          INTEGER,                           -- 文件总大小（字节）
                uploaded_size       INTEGER DEFAULT 0,                 -- 已上传大小（字节）
                upload_speed        INTEGER,                           -- 上传速度（字节/秒）
                retry_count         INTEGER DEFAULT 0,                 -- 重试次数
                max_retries         INTEGER DEFAULT 3,                 -- 最大重试次数
                created_at          TEXT NOT NULL,                     -- 创建时间
                started_at          TEXT,                              -- 开始上传时间
                completed_at        TEXT,                              -- 完成时间
                updated_at          TEXT NOT NULL,                     -- 最近更新时间
                extra               TEXT,                              -- 扩展字段（JSON）
                FOREIGN KEY (download_id) REFERENCES downloads(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploads_download_id ON uploads (download_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploads_status ON uploads (status)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploads_target ON uploads (upload_target)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploads_failure_reason ON uploads (failure_reason)"
        )
        
        # 数据库迁移：为 uploads 表添加 cleaned_at 字段（如果不存在）
        try:
            cur.execute("ALTER TABLE uploads ADD COLUMN cleaned_at TEXT")
            logging.info("已为 uploads 表添加 cleaned_at 字段")
        except sqlite3.OperationalError as e:
            # 字段已存在，忽略错误
            if "duplicate column name" not in str(e).lower():
                logging.warning(f"添加 cleaned_at 字段时出错（可能已存在）: {e}")

        # 系统配置表
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS config_settings (
                key             TEXT PRIMARY KEY,  -- 配置键名
                value           TEXT,              -- 配置值（JSON字符串，支持复杂类型）
                value_type      TEXT NOT NULL,     -- 值类型：string, int, bool, list, json
                category        TEXT NOT NULL,     -- 配置分类：telegram, rclone, aria2, stream, etc.
                description     TEXT,              -- 配置说明
                updated_at      TEXT NOT NULL      -- 更新时间
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_config_category ON config_settings (category)"
        )

        # 用户表
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                username        TEXT NOT NULL UNIQUE,
                password_hash   TEXT NOT NULL,
                role            TEXT NOT NULL DEFAULT 'admin',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
            """
        )

        # 桌面客户端长期登录会话表
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                token_hash      TEXT NOT NULL,
                device_id       TEXT,
                session_name    TEXT,
                expires_at      TEXT NOT NULL,
                revoked_at      TEXT,
                revoked_reason  TEXT,
                replaced_by     INTEGER,
                created_at      TEXT NOT NULL,
                last_used_at    TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (replaced_by) REFERENCES auth_sessions(id) ON DELETE SET NULL
            )
            """
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_sessions_token_hash ON auth_sessions (token_hash)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions (user_id)"
        )

        # users 表多租户扩展字段迁移
        for col_name, col_type in [
            ("tg_user_id", "INTEGER"),
            ("tg_username", "TEXT"),
            ("tg_first_name", "TEXT"),
            ("dc_id", "INTEGER"),
            ("bin_channel_id", "INTEGER"),
            ("bin_channel_username", "TEXT"),
            ("creator_account_id", "INTEGER"),
            ("extra_channels", "TEXT DEFAULT '[]'"),
        ]:
            try:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass

        try:
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_tg_user_id ON users (tg_user_id) WHERE tg_user_id IS NOT NULL"
            )
        except sqlite3.OperationalError:
            pass

        # Telegram 注册验证码表
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tg_register_codes (
                code TEXT PRIMARY KEY,
                tg_user_id INTEGER NOT NULL,
                tg_username TEXT,
                tg_first_name TEXT,
                detected_dc_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_tg_reg_codes_user ON tg_register_codes (tg_user_id)"
        )

        # downloads 表扩展字段迁移 (多租户隔离)
        for col_name, col_type in [
            ("user_id", "INTEGER"),
            ("target_channel_id", "INTEGER"),
        ]:
            try:
                cur.execute(f"ALTER TABLE downloads ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass

        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_downloads_user_id ON downloads (user_id)"
        )

        # Telegram 协议号资产池表
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tg_protocol_accounts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                phone          TEXT NOT NULL UNIQUE,
                session_type   TEXT NOT NULL DEFAULT 'pyrogram_string',
                session_data   TEXT NOT NULL,
                code_url       TEXT,
                bot_count      INTEGER NOT NULL DEFAULT 0,
                status         TEXT NOT NULL DEFAULT 'active',
                last_used_at   TEXT,
                remark         TEXT,
                api_id         INTEGER,
                api_hash       TEXT,
                created_at     TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tg_protocol_accounts_phone ON tg_protocol_accounts (phone)"
        )

        # 协议号资产池表扩展字段迁移
        for col_name, col_type in [
            ("dc_id", "INTEGER"),
            ("tg_user_id", "INTEGER"),
            ("username", "TEXT"),
            ("first_name", "TEXT"),
            ("last_keepalive_at", "TEXT"),
            ("keepalive_ping_ms", "INTEGER"),
            ("last_error", "TEXT"),
            ("api_id", "INTEGER"),
            ("api_hash", "TEXT"),
            ("two_fa_password", "TEXT"),
            ("two_fa_hint", "TEXT"),
            ("has_two_fa", "INTEGER DEFAULT 0"),
            ("local_otp_token", "TEXT"),
            ("is_taken_over", "INTEGER DEFAULT 0"),
            ("taken_over_at", "TEXT"),
            ("bot_usernames", "TEXT"),
        ]:
            try:
                cur.execute(f"ALTER TABLE tg_protocol_accounts ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass

        # Older releases created this now-unused index table but did not enable
        # SQLite foreign keys. Preserve its records while applying the declared
        # ON DELETE SET NULL result to already-orphaned links.
        # 为缺失 local_otp_token 的历史协议号补齐专属安全接码 Token
        try:
            missing_tokens = cur.execute(
                "SELECT id FROM tg_protocol_accounts WHERE local_otp_token IS NULL OR local_otp_token = \x27\x27"
            ).fetchall()
            for r in missing_tokens:
                cur.execute(
                    "UPDATE tg_protocol_accounts SET local_otp_token = ? WHERE id = ?",
                    (secrets.token_hex(16), r[0]),
                )
        except Exception:
            pass

        # 为存量协议号自愈补齐历史号商 2FA 原密码 (避免修改 2FA 时因缺失旧密码受阻)
        try:
            legacy_2fa_map = {
                "+16813086196": "qq1122",
                "+959757485895": "8899",
                "+18048484620": "qq1122",
            }
            cur.execute(
                """
                UPDATE tg_protocol_accounts
                   SET two_fa_password = 'z4422404', has_two_fa = 1
                 WHERE (two_fa_password IS NULL OR two_fa_password = '')
                   AND (phone LIKE '+1941%' OR phone LIKE '+1940%')
                """
            )
            for p, pwd in legacy_2fa_map.items():
                cur.execute(
                    """
                    UPDATE tg_protocol_accounts
                       SET two_fa_password = ?, has_two_fa = 1
                     WHERE phone = ? AND (two_fa_password IS NULL OR two_fa_password = '')
                    """,
                    (pwd, p),
                )
        except Exception:
            pass

        # 自动回填已完成本机接码 + 专属 2FA 强密码的协议号为已接管状态
        try:
            cur.execute(
                """
                UPDATE tg_protocol_accounts
                   SET is_taken_over = 1
                 WHERE COALESCE(is_taken_over, 0) = 0
                   AND code_url LIKE '/api/telegram/botfather/otp/%'
                   AND two_fa_password IS NOT NULL
                   AND two_fa_password NOT IN ('', 'z4422404', 'qq1122', '8899', '123456', '666888', '888888', '112233')
                """
            )
        except Exception:
            pass

        # 边缘推流分流节点表 (多租户 VPS Edge Worker)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS edge_nodes (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id         INTEGER NOT NULL,
                node_name         TEXT NOT NULL,
                ip                TEXT,
                port              INTEGER NOT NULL DEFAULT 8090,
                ssh_host          TEXT,
                ssh_port          INTEGER NOT NULL DEFAULT 22,
                ssh_user          TEXT NOT NULL DEFAULT 'root',
                ssh_password_enc  TEXT,
                domain            TEXT,
                use_ssl           INTEGER NOT NULL DEFAULT 0,
                auth_secret       TEXT NOT NULL,
                status            TEXT NOT NULL DEFAULT 'offline',
                deploy_log        TEXT,
                allow_shared_pool INTEGER NOT NULL DEFAULT 0,
                metrics           TEXT,
                benchmark_data    TEXT DEFAULT '{}',
                target_dc_id      INTEGER,
                assigned_bot_token TEXT,
                assigned_bot_username TEXT,
                allow_bot_pool    INTEGER NOT NULL DEFAULT 1,
                last_seen_at      TEXT,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_edge_nodes_tenant ON edge_nodes (tenant_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_edge_nodes_status ON edge_nodes (status)"
        )

        cur.execute("PRAGMA table_info(edge_nodes)")
        _edge_cols = {row[1] for row in cur.fetchall()}
        if "benchmark_data" not in _edge_cols:
            try:
                cur.execute("ALTER TABLE edge_nodes ADD COLUMN benchmark_data TEXT DEFAULT '{}'")
            except Exception:
                pass
        for col_name, col_type in (
            ("target_dc_id", "INTEGER DEFAULT NULL"),
            ("assigned_bot_token", "TEXT DEFAULT NULL"),
            ("assigned_bot_username", "TEXT DEFAULT NULL"),
            ("allow_bot_pool", "INTEGER NOT NULL DEFAULT 1"),
            ("target_bot_count", "INTEGER DEFAULT NULL"),
        ):
            if col_name not in _edge_cols:
                try:
                    cur.execute(f"ALTER TABLE edge_nodes ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass

        # 存量边缘节点平滑自愈迁移：为缺失 domain 或 domain 等于裸 IP 的节点自动补齐 sslip.io 域名并启用 SSL
        try:
            cur.execute("SELECT id, ip, domain, use_ssl FROM edge_nodes WHERE ip IS NOT NULL AND ip != ''")
            for r in cur.fetchall():
                node_id = r[0]
                node_ip = (r[1] or "").strip()
                node_dom = (r[2] or "").strip()
                node_ssl = r[3]
                if not node_dom or node_dom == node_ip:
                    auto_dom = get_default_edge_domain(node_ip)
                    if auto_dom:
                        cur.execute(
                            "UPDATE edge_nodes SET domain = ?, use_ssl = 1, updated_at = ? WHERE id = ?",
                            (auto_dom, _now_iso(), node_id),
                        )
        except Exception as e:
            logger.debug(f"边缘节点存量迁移跳过: {e}")

        # 存量边缘节点数据中心 (DC) 亲和归属自动推导自愈
        try:
            cur.execute("SELECT id, node_name, ip, benchmark_data, target_dc_id FROM edge_nodes")
            for r in cur.fetchall():
                nid, nname, nip, nbench, cur_dc = r[0], r[1] or "", r[2] or "", r[3] or "{}", r[4]
                if cur_dc is not None:
                    continue
                assigned_dc = 5
                try:
                    parsed_b = json.loads(nbench) if isinstance(nbench, str) else nbench
                    fastest = (parsed_b or {}).get("fastest_dc") or {}
                    fid = fastest.get("id")
                    if fid in (1, 3):
                        assigned_dc = 1
                    elif fid in (2, 4):
                        assigned_dc = 4
                    elif fid == 5:
                        assigned_dc = 5
                    else:
                        lower_name = (nname + " " + nip).lower()
                        if any(k in lower_name for k in ("美", "us", "america", "rn-")):
                            assigned_dc = 1
                        elif any(k in lower_name for k in ("欧", "eu", "de", "fr", "uk")):
                            assigned_dc = 4
                        else:
                            assigned_dc = 5
                except Exception:
                    pass
                cur.execute(
                    "UPDATE edge_nodes SET target_dc_id = ?, updated_at = ? WHERE id = ?",
                    (assigned_dc, _now_iso(), nid),
                )
        except Exception as e:
            logger.debug(f"边缘节点 DC 归属自愈跳过: {e}")

        # 边缘节点一键脚本安装配对 Token 表
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS edge_node_tokens (
                token             TEXT PRIMARY KEY,
                tenant_id         INTEGER NOT NULL,
                node_name         TEXT NOT NULL,
                domain            TEXT,
                port              INTEGER NOT NULL DEFAULT 8090,
                use_ssl           INTEGER NOT NULL DEFAULT 0,
                allow_shared_pool INTEGER NOT NULL DEFAULT 0,
                node_id           INTEGER,
                expires_at        TEXT NOT NULL,
                used              INTEGER NOT NULL DEFAULT 0,
                created_at        TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_edge_tokens_tenant ON edge_node_tokens (tenant_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_edge_tokens_node ON edge_node_tokens (node_id)"
        )

        has_legacy_channel_files = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tg_channel_files'"
        ).fetchone()
        if has_legacy_channel_files:
            repaired_links = cur.execute(
                """
                UPDATE tg_channel_files
                   SET file_unique_id = NULL
                 WHERE file_unique_id IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1
                         FROM tg_media
                        WHERE tg_media.file_unique_id = tg_channel_files.file_unique_id
                   )
                """
            ).rowcount
            if repaired_links:
                logger.warning(
                    "已将 %d 条历史频道索引孤儿外键安全置空",
                    repaired_links,
                )
    
    # 检查是否需要从config.yml迁移配置（在with块外执行，因为需要独立的连接）
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as count FROM config_settings")
        count = cur.fetchone()['count']
        if legacy_yaml_bootstrap_enabled():
            # The explicit recovery path also retries retirement after an earlier
            # successful database commit followed by a filesystem cleanup error.
            try:
                if init_config_from_yaml():
                    logger.info("已从config.yml成功导入配置到数据库")
                else:
                    logger.info("旧YAML配置已退休或无需迁移")
            except Exception as e:
                raise RuntimeError("旧YAML配置导入或安全退休失败") from e
        elif count == 0:
            logger.warning("配置表为空，且旧YAML引导未授权")


def save_tg_media(message, media=None, custom_file_name=None, custom_caption=None, custom_media_group_id=None) -> str:
    """
    保存一条 Telegram 媒体元数据，返回 file_unique_id。

    当同一个 file_unique_id 已存在时，使用最新消息元数据覆盖，
    以便 tg 网盘始终指向 bot 实际转发到频道中的那条消息。
    """
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
    if media is None:
        raise ValueError("message does not contain supported media")

    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    if chat_id is None:
        chat_id = getattr(message, "chat_id", None)
    message_id = getattr(message, "id", None)
    if message_id is None:
        message_id = getattr(message, "message_id", None)

    if chat_id is None or message_id is None:
        raise ValueError("message does not contain a valid chat/message id")

    file_unique_id = getattr(media, "file_unique_id", None)
    file_id = getattr(media, "file_id", None)
    if not file_unique_id:
        file_unique_id = f"telethon:{chat_id}:{message_id}"
    if not file_id:
        file_id = file_unique_id

    caption_entities = getattr(message, "caption_entities", None) or []
    try:
        ce_json = json.dumps([
            e.__dict__ if hasattr(e, "__dict__") else dict(e)
            for e in caption_entities
        ], ensure_ascii=False)
    except Exception:
        ce_json = "[]"

    from_user = getattr(message, "from_user", None)
    sender_chat = getattr(message, "sender_chat", None)
    message_date = getattr(message, "date", None)
    if message_date is None:
        message_date = getattr(message, "message_date", None)
    if message_date is None:
        message_date = _now_iso()
    elif not isinstance(message_date, str):
        message_date = _format_message_date(message_date)

    resolved_media_group_id = (
        custom_media_group_id
        if custom_media_group_id is not None
        else (getattr(message, "media_group_id", None) or getattr(message, "grouped_id", None))
    )
    if resolved_media_group_id is not None:
        resolved_media_group_id = str(resolved_media_group_id)

    file_info = getattr(message, "file", None)
    file_name = custom_file_name or getattr(media, "file_name", None) or getattr(file_info, "name", None)
    caption = custom_caption if custom_caption is not None else getattr(message, "caption", None)
    mime_type = getattr(media, "mime_type", None) or getattr(file_info, "mime_type", None)
    file_size = getattr(media, "file_size", None) or getattr(file_info, "size", None)

    if not mime_type:
        if getattr(message, "photo", None) is not None or (getattr(media, "width", None) and not getattr(media, "duration", None)):
            mime_type = "image/jpeg"
        elif getattr(message, "video", None) is not None or getattr(message, "animation", None) is not None or getattr(message, "video_note", None) is not None:
            mime_type = "video/mp4"
        elif getattr(message, "audio", None) is not None:
            mime_type = "audio/mpeg"
        elif getattr(message, "voice", None) is not None:
            mime_type = "audio/ogg"

    if not file_name:
        if mime_type == "image/jpeg":
            file_name = f"photo_{message_id}.jpg"
        elif mime_type == "video/mp4":
            file_name = f"video_{message_id}.mp4"
        elif mime_type == "audio/mpeg":
            file_name = f"audio_{message_id}.mp3"
        elif mime_type == "audio/ogg":
            file_name = f"voice_{message_id}.ogg"
        else:
            file_name = f"media_{message_id}"

    # thumbs 可以以后再扩展，现在先占位为空列表
    thumbs_json = "[]"

    with db_cursor() as cur:
        # 多租户兼容：若相同 file_unique_id 存在于不同 chat_id 频道，追加 @chat_id 后缀以隔离存储
        final_unique_id = file_unique_id
        cur.execute(
            "SELECT chat_id FROM tg_media WHERE file_unique_id = ?",
            (file_unique_id,),
        )
        existing_row = cur.fetchone()
        if existing_row:
            existing_chat = existing_row[0] if isinstance(existing_row, (list, tuple)) else existing_row["chat_id"]
            if str(existing_chat) != str(chat_id):
                final_unique_id = f"{file_unique_id}@{chat_id}"

        cur.execute(
            """
            INSERT INTO tg_media (
                file_unique_id, chat_id, message_id, from_user_id, sender_chat_id,
                file_id, file_name, mime_type, file_size,
                duration, width, height,
                caption, caption_entities, message_date,
                media_group_id, has_media_spoiler, supports_streaming,
                thumbs
            ) VALUES (?, ?, ?, ?, ?,
                      ?, ?, ?, ?,
                      ?, ?, ?,
                      ?, ?, ?,
                      ?, ?, ?,
                      ?)
            ON CONFLICT(file_unique_id) DO UPDATE SET
                chat_id = excluded.chat_id,
                message_id = excluded.message_id,
                from_user_id = excluded.from_user_id,
                sender_chat_id = excluded.sender_chat_id,
                file_id = excluded.file_id,
                file_name = excluded.file_name,
                mime_type = excluded.mime_type,
                file_size = excluded.file_size,
                duration = excluded.duration,
                width = excluded.width,
                height = excluded.height,
                caption = excluded.caption,
                caption_entities = excluded.caption_entities,
                message_date = excluded.message_date,
                media_group_id = excluded.media_group_id,
                has_media_spoiler = excluded.has_media_spoiler,
                supports_streaming = excluded.supports_streaming,
                thumbs = excluded.thumbs
            """,
            (
                final_unique_id,
                chat_id,
                message_id,
                getattr(from_user, "id", None),
                getattr(sender_chat, "id", None),
                file_id,
                file_name,
                mime_type,
                file_size,
                getattr(media, "duration", None),
                getattr(media, "width", None),
                getattr(media, "height", None),
                caption,
                ce_json,
                message_date,
                resolved_media_group_id,
                int(bool(getattr(message, "has_media_spoiler", False) or getattr(media, "has_media_spoiler", False))),
                int(bool(getattr(media, "supports_streaming", False))),
                thumbs_json,
            ),
        )

    return final_unique_id


def create_download(
    file_unique_id: str,
    gid: str | None,
    source_url: str | None,
    user_id: int | None = None,
    target_channel_id: int | None = None,
) -> int:
    """创建一条下载记录，返回 downloads.id。支持按用户和目标频道进行租户绑定。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM tg_media WHERE file_unique_id = ?", (file_unique_id,))
        if not cur.fetchone():
            cur.execute(
                """
                INSERT OR IGNORE INTO tg_media (
                    file_unique_id, chat_id, message_id, file_id, message_date
                ) VALUES (?, ?, 0, ?, ?)
                """,
                (file_unique_id, target_channel_id or 0, file_unique_id, now),
            )
        cur.execute(
            """
            INSERT INTO downloads (
                file_unique_id, gid, source_url, status,
                user_id, target_channel_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (file_unique_id, gid, source_url, user_id, target_channel_id, now, now),
        )
        download_id = cur.lastrowid
    # 如果有 gid，推送 WebSocket 更新（新记录通知）
    if gid:
        _notify_ws_download_update(gid)
    # 推送统计更新，确保前端刷新列表
    _notify_ws_statistics_update()
    return download_id


def mark_download_started(gid: str):
    """标记下载开始时间。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE downloads
               SET status = 'downloading',
                   started_at = COALESCE(started_at, ?),
                   updated_at = ?
             WHERE gid = ?
            """,
            (now, now, gid),
        )
    # 推送 WebSocket 更新
    _notify_ws_download_update(gid)


def get_download_id_by_gid(gid: str) -> int | None:
    """根据 GID 获取下载记录 ID。"""
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM downloads WHERE gid = ?", (gid,))
        row = cur.fetchone()
        return row['id'] if row else None


def get_download_by_id(download_id: int):
    """根据 ID 获取下载记录。"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM downloads
            WHERE id = ?
            """,
            (download_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def _notify_ws_download_update(gid: str):
    """通过 WebSocket 推送下载状态更新（异步，不阻塞）"""
    try:
        from WebStreamer.server.ws_manager import ws_manager
        import asyncio
        
        # 获取下载记录
        download_id = get_download_id_by_gid(gid)
        if download_id:
            download = get_download_by_id(download_id)
            if download:
                # 获取关联的上传记录，确保数据一致性
                uploads = get_uploads_by_download(download_id)
                uploads_data = []
                for upload in uploads:
                    uploads_data.append({
                        "id": upload.get('id'),
                        "upload_target": upload.get('upload_target'),
                        "status": upload.get('status'),
                        "uploaded_size": upload.get('uploaded_size'),
                        "total_size": upload.get('total_size'),
                        "upload_speed": upload.get('upload_speed'),
                        "cleaned_at": upload.get('cleaned_at'),
                    })
                
                # 异步推送更新
                loop = None
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    # 如果没有事件循环，创建一个新的
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                if loop and not loop.is_closed():
                    asyncio.create_task(ws_manager.send_download_update({
                        "gid": gid,
                        "download_id": download_id,
                        "user_id": download.get('user_id'),
                        "status": download.get('status'),
                        "completed_length": download.get('completed_length'),
                        "total_length": download.get('total_length'),
                        "download_speed": download.get('download_speed'),
                        "uploads": uploads_data,  # 包含上传信息，确保数据一致性
                    }))
    except Exception as e:
        # 静默失败，不影响主流程
        pass


def _notify_ws_upload_update(upload_id: int):
    """通过 WebSocket 推送上传状态更新（异步，不阻塞）"""
    try:
        from WebStreamer.server.ws_manager import ws_manager
        import asyncio
        
        upload = get_upload_by_id(upload_id)
        if upload:
            dl_id = upload.get('download_id')
            dl_rec = get_download_by_id(dl_id) if dl_id else None
            loop = None
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            if loop and not loop.is_closed():
                asyncio.create_task(ws_manager.send_upload_update({
                    "upload_id": upload_id,
                    "download_id": dl_id,
                    "user_id": dl_rec.get('user_id') if dl_rec else None,
                    "status": upload.get('status'),
                    "uploaded_size": upload.get('uploaded_size'),
                    "total_size": upload.get('total_size'),
                    "upload_speed": upload.get('upload_speed'),
                    "cleaned_at": upload.get('cleaned_at'),  # 包含清理状态
                }))
    except Exception as e:
        pass


def _notify_ws_cleanup_update(upload_id: int):
    """通过 WebSocket 推送清理状态更新（异步，不阻塞）"""
    try:
        from WebStreamer.server.ws_manager import ws_manager
        import asyncio
        
        upload = get_upload_by_id(upload_id)
        if upload:
            dl_id = upload.get('download_id')
            dl_rec = get_download_by_id(dl_id) if dl_id else None
            loop = None
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            if loop and not loop.is_closed():
                asyncio.create_task(ws_manager.send_cleanup_update({
                    "upload_id": upload_id,
                    "download_id": dl_id,
                    "user_id": dl_rec.get('user_id') if dl_rec else None,
                    "cleaned_at": upload.get('cleaned_at'),
                }))
    except Exception as e:
        pass


def _notify_ws_statistics_update():
    """通过 WebSocket 推送统计信息更新（异步，不阻塞，按角色隔离推送）"""
    try:
        from WebStreamer.server.ws_manager import ws_manager
        import asyncio
        
        # 获取全局统计信息（推送给管理员）
        download_stats = get_download_statistics()
        upload_stats = get_upload_statistics()
        
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop and not loop.is_closed():
            asyncio.create_task(ws_manager.send_statistics_update({
                "downloads": download_stats,
                "uploads": upload_stats,
            }))
            if hasattr(ws_manager, "get_connected_tenant_user_ids"):
                for uid in ws_manager.get_connected_tenant_user_ids():
                    u_dl_stats = get_download_statistics(user_id=uid)
                    u_up_stats = get_upload_statistics(user_id=uid)
                    asyncio.create_task(
                        ws_manager.send_statistics_update(
                            {
                                "downloads": u_dl_stats,
                                "uploads": u_up_stats,
                            },
                            target_user_id=uid,
                        )
                    )
    except Exception as e:
        # 静默失败，不影响主流程
        pass


def mark_download_completed(gid: str, local_path: str | None, total_length: int | None):
    """
    标记下载完成状态和本地路径。
    注意：这里不立即标记为 completed，而是保持当前状态（downloading）。
    只有在清理完成后，才会通过 mark_upload_cleaned 更新为 completed。
    """
    now = _now_iso()
    with db_cursor() as cur:
        # 检查是否有上传任务，如果有，保持 downloading 状态；如果没有，标记为 completed
        download_id = get_download_id_by_gid(gid)
        has_uploads = False
        if download_id:
            cur.execute("SELECT COUNT(*) FROM uploads WHERE download_id = ?", (download_id,))
            upload_count = cur.fetchone()[0]
            has_uploads = upload_count > 0
        
        # 如果有上传任务，保持 downloading 状态；否则标记为 completed
        if has_uploads:
            # 保持当前状态（通常是 downloading），只更新路径和大小
            cur.execute(
                """
                UPDATE downloads
                   SET local_path = COALESCE(?, local_path),
                       total_length = COALESCE(?, total_length),
                       completed_length = COALESCE(?, completed_length),
                       updated_at = ?
                 WHERE gid = ?
                """,
                (local_path, total_length, total_length, now, gid),
            )
        else:
            # 没有上传任务，直接标记为 completed
            cur.execute(
                """
                UPDATE downloads
                   SET status = 'completed',
                       local_path = COALESCE(?, local_path),
                       total_length = COALESCE(?, total_length),
                       completed_length = COALESCE(?, completed_length),
                       completed_at = ?,
                       updated_at = ?
                 WHERE gid = ?
                """,
                (local_path, total_length, total_length, now, now, gid),
            )
    # 推送 WebSocket 更新
    _notify_ws_download_update(gid)


def mark_download_failed(gid: str, error_message: str | None):
    """标记下载失败。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE downloads
               SET status = 'failed',
                   error_message = ?,
                   updated_at = ?
             WHERE gid = ?
            """,
            (error_message, now, gid),
        )
    # 推送 WebSocket 更新
    _notify_ws_download_update(gid)


def mark_download_paused(gid: str):
    """标记下载暂停。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE downloads
               SET status = 'paused',
                   download_speed = 0,
                   updated_at = ?
             WHERE gid = ?
            """,
            (now, gid),
        )
    # 推送 WebSocket 更新
    _notify_ws_download_update(gid)


def mark_download_resumed(gid: str):
    """标记下载恢复。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE downloads
               SET status = 'downloading',
                   updated_at = ?
             WHERE gid = ? AND status = 'paused'
            """,
            (now, gid),
        )
    # 推送 WebSocket 更新
    _notify_ws_download_update(gid)


def update_download_progress(gid: str, completed_length: int | None = None, 
                             total_length: int | None = None, 
                             download_speed: int | None = None):
    """更新下载进度。"""
    now = _now_iso()
    updates = ["updated_at = ?"]
    values = [now]
    
    if completed_length is not None:
        updates.append("completed_length = ?")
        values.append(completed_length)
    
    if total_length is not None:
        updates.append("total_length = ?")
        values.append(total_length)
    
    if download_speed is not None:
        updates.append("download_speed = ?")
        values.append(download_speed)
    
    values.append(gid)
    
    with db_cursor() as cur:
        cur.execute(
            f"""
            UPDATE downloads
               SET {', '.join(updates)}
             WHERE gid = ?
            """,
            tuple(values),
        )
    # 推送 WebSocket 更新
    _notify_ws_download_update(gid)


def fetch_recent_downloads(limit: int = 100, user_id: int | None = None):
    """
    查询最近的下载记录（按创建时间倒序），包含部分 Telegram 媒体字段和上传信息，
    用于 Web 管理页面展示。支持按 user_id 租户过滤。
    """
    where_sql = "WHERE d.user_id = ?" if user_id is not None else ""
    params = [int(user_id), limit] if user_id is not None else [limit]

    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT
                d.id,
                d.gid,
                d.source_url,
                d.status,
                d.total_length,
                d.completed_length,
                d.download_speed,
                d.local_path,
                d.remote_path,
                d.upload_status,
                d.created_at,
                d.started_at,
                d.completed_at,
                d.updated_at,
                m.file_name,
                m.mime_type,
                m.file_size,
                m.chat_id,
                m.message_id,
                m.media_group_id,
                m.caption,
                m.message_date,
                u.id as upload_id,
                u.upload_target,
                u.remote_path as upload_remote_path,
                u.status as upload_status_detail,
                u.total_size as upload_total_size,
                u.uploaded_size,
                u.upload_speed,
                u.failure_reason,
                u.error_message as upload_error_message,
                u.created_at as upload_created_at,
                u.started_at as upload_started_at,
                u.completed_at as upload_completed_at,
                u.cleaned_at as upload_cleaned_at
            FROM downloads AS d
            LEFT JOIN tg_media AS m
              ON d.file_unique_id = m.file_unique_id
            LEFT JOIN uploads AS u
              ON u.download_id = d.id
            {where_sql}
            ORDER BY d.created_at DESC, u.created_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        rows = cur.fetchall()
        # 将结果转换为字典，并处理多个上传记录的情况
        result_dict = {}
        for row in rows:
            download_id = row['id']
            if download_id not in result_dict:
                # 创建下载记录
                download_record = {
                    'id': row['id'],
                    'gid': row['gid'],
                    'source_url': row['source_url'],
                    'status': row['status'],
                    'total_length': row['total_length'],
                    'completed_length': row['completed_length'],
                    'download_speed': row['download_speed'],
                    'local_path': row['local_path'],
                    'remote_path': row['remote_path'],
                    'upload_status': row['upload_status'],
                    'created_at': row['created_at'],
                    'started_at': row['started_at'],
                    'completed_at': row['completed_at'],
                    'updated_at': row['updated_at'],
                    'file_name': row['file_name'],
                    'mime_type': row['mime_type'],
                    'file_size': row['file_size'],
                    'chat_id': row['chat_id'],
                    'message_id': row['message_id'],
                    'media_group_id': row['media_group_id'],
                    'caption': row['caption'],
                    'message_date': row['message_date'],
                    'uploads': []
                }
                result_dict[download_id] = download_record
            
            # 添加上传记录（如果有）
            if row['upload_id']:
                upload_id = row['upload_id']
                # 检查是否已经添加过这个上传记录
                existing_upload_ids = [u['id'] for u in result_dict[download_id]['uploads']]
                if upload_id not in existing_upload_ids:
                    upload_record = {
                        'id': upload_id,
                        'upload_target': row['upload_target'],
                        'remote_path': row['upload_remote_path'],
                        'status': row['upload_status_detail'],
                        'total_size': row['upload_total_size'],
                        'uploaded_size': row['uploaded_size'],
                        'upload_speed': row['upload_speed'],
                        'failure_reason': row['failure_reason'],
                        'error_message': row['upload_error_message'],
                        'created_at': row['upload_created_at'],
                        'started_at': row['upload_started_at'],
                        'completed_at': row['upload_completed_at'],
                        'cleaned_at': row['upload_cleaned_at']
                    }
                    result_dict[download_id]['uploads'].append(upload_record)
        
        # 对每个下载记录的上传列表按创建时间倒序排序（保持稳定排序）
        # 使用ID作为次要排序键，确保排序稳定
        for download_record in result_dict.values():
            if download_record.get('uploads'):
                download_record['uploads'].sort(key=lambda u: (
                    u.get('created_at') or '',  # 字符串排序（ISO格式天然支持）
                    u.get('id') or 0
                ), reverse=False)  # 正序：先创建的在前，后创建的在后
        
        return list(result_dict.values())


def fetch_downloads_grouped(limit: int = 100, user_id: int | None = None):
    """
    查询下载记录并按消息分组。支持按 user_id 租户过滤。
    返回格式：按消息组（media_group_id 或 chat_id+message_id）分组的数据
    """
    records = fetch_recent_downloads(limit, user_id=user_id)
    
    # 按消息分组
    groups: dict[str, list] = {}
    
    for record in records:
        # 确定分组键：优先使用 media_group_id，否则使用 chat_id+message_id
        if record.get('media_group_id'):
            group_key = f"group_{record['media_group_id']}"
        elif record.get('chat_id') and record.get('message_id'):
            group_key = f"msg_{record['chat_id']}_{record['message_id']}"
        else:
            # 如果没有分组信息，使用下载ID作为独立组
            group_key = f"single_{record['id']}"
        
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(record)
    
    # 转换为列表格式，每个组包含组信息和下载列表
    result = []
    for group_key, downloads in groups.items():
        # 获取组的第一条记录作为组信息
        first_record = downloads[0]
        
        # 计算组统计信息
        total_files = len(downloads)
        
        def upload_statuses(download_record):
            return [upload.get('status') for upload in download_record.get('uploads', [])]

        def has_upload_failure(download_record):
            return any(status in ['failed', 'cancelled'] for status in upload_statuses(download_record))

        def has_upload_pending(download_record):
            return any(status in ['pending', 'waiting_download'] for status in upload_statuses(download_record))

        def has_upload_active(download_record):
            return any(status == 'uploading' for status in upload_statuses(download_record))

        def has_upload_cleanup_pending(download_record):
            return any(
                upload.get('status') == 'completed' and not upload.get('cleaned_at')
                for upload in download_record.get('uploads', [])
            )

        def is_truly_completed(download_record):
            """判断一个下载记录是否真正完成（下载完成且上传已完成并清理）"""
            if download_record.get('status') != 'completed':
                return False

            uploads = download_record.get('uploads', [])
            if not uploads:
                return True

            for upload in uploads:
                if upload.get('status') != 'completed':
                    return False
                if not upload.get('cleaned_at'):
                    return False

            return True
        
        completed = sum(1 for d in downloads if is_truly_completed(d))
        downloading = sum(1 for d in downloads if d.get('status') == 'downloading' or has_upload_active(d))
        failed = sum(1 for d in downloads if d.get('status') == 'failed' or has_upload_failure(d))
        pending = sum(1 for d in downloads if d.get('status') == 'pending' or has_upload_pending(d) or has_upload_cleanup_pending(d))
        # 统计跳过的文件（状态为failed且错误信息包含"跳过"）
        skipped = sum(1 for d in downloads if d.get('status') == 'failed' and d.get('error_message', '').find('跳过') != -1)
        
        total_size = sum(d.get('total_length') or d.get('file_size') or 0 for d in downloads)
        completed_size = sum(
            (d.get('total_length') or d.get('file_size') or d.get('completed_length') or 0)
            for d in downloads
            if is_truly_completed(d)
        )
        
        # 对组内的下载记录按创建时间正序排序（保持稳定排序）
        # 使用ID作为次要排序键，确保排序稳定
        # 正序：先创建的在前，后创建的在后
        downloads_sorted = sorted(downloads, key=lambda d: (
            d.get('created_at') or '',  # 字符串排序（ISO格式天然支持）
            d.get('id') or 0
        ), reverse=False)
        
        result.append({
            'group_key': group_key,
            'group_type': 'media_group' if first_record.get('media_group_id') else 'message',
            'chat_id': first_record.get('chat_id'),
            'message_id': first_record.get('message_id'),
            'media_group_id': first_record.get('media_group_id'),
            'caption': first_record.get('caption'),
            'message_date': first_record.get('message_date') or first_record.get('created_at'),
            'created_at': min(d.get('created_at', '') for d in downloads if d.get('created_at')),
            'stats': {
                'total_files': total_files,
                'completed': completed,
                'downloading': downloading,
                'failed': failed,
                'pending': pending,
                'skipped': skipped,
                'total_size': total_size,
                'completed_size': completed_size
            },
            'downloads': downloads_sorted
        })
    
    # 按创建时间倒序排序（后创建的在前，先创建的在后）
    result.sort(key=lambda x: x['created_at'], reverse=True)
    
    return result


def get_config(key: str, default=None):
    """获取配置值"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT value, value_type FROM config_settings WHERE key = ?",
            (key,)
        )
        row = cur.fetchone()
        if row:
            value = row['value']
            value_type = row['value_type']
            # 根据类型转换值
            if value_type == 'int':
                return int(value) if value else default
            elif value_type == 'bool':
                return value.lower() in ('true', '1', 'yes', 'on') if value else default
            elif value_type == 'list':
                return json.loads(value) if value else default
            elif value_type == 'json':
                return json.loads(value) if value else default
            else:
                return value if value else default
        return default


def _serialize_config_value(value, value_type: str) -> str:
    if value_type == 'list' or value_type == 'json':
        return json.dumps(value, ensure_ascii=False) if value else ''
    return str(value) if value is not None else ''


def set_configs(updates: list[tuple]):
    """Atomically update multiple configuration values."""
    now = _now_iso()
    with db_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO config_settings (key, value, value_type, category, description, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    key,
                    _serialize_config_value(value, value_type),
                    value_type,
                    category,
                    description,
                    now,
                )
                for key, value, value_type, category, description in updates
            ],
        )


def set_config(key: str, value: any, value_type: str = 'string', category: str = 'general', description: str = None):
    """设置配置值"""
    if value_type == 'string' and isinstance(value, bool):
        value_type = 'bool'
    elif value_type == 'string' and isinstance(value, int):
        value_type = 'int'
    set_configs([(key, value, value_type, category, description)])

get_config_value = get_config
set_config_value = set_config


def get_all_configs(category: str = None):
    """获取所有配置或指定分类的配置"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if category:
            cur.execute(
                "SELECT key, value, value_type, category, description FROM config_settings WHERE category = ? ORDER BY key",
                (category,)
            )
        else:
            cur.execute(
                "SELECT key, value, value_type, category, description FROM config_settings ORDER BY category, key"
            )
        rows = cur.fetchall()
        result = {}
        for row in rows:
            key = row['key']
            value = row['value']
            value_type = row['value_type']
            # 根据类型转换值
            if value_type == 'int':
                result[key] = int(value) if value else None
            elif value_type == 'bool':
                result[key] = value.lower() in ('true', '1', 'yes', 'on') if value else False
            elif value_type == 'list':
                result[key] = json.loads(value) if value else []
            elif value_type == 'json':
                result[key] = json.loads(value) if value else {}
            else:
                result[key] = value if value else ''
        return result


def init_config_from_yaml():
    """Perform an explicitly authorized, one-shot migration from config.yml."""
    if not legacy_yaml_bootstrap_enabled():
        return False
    config_file = legacy_config_path(DB_PATH)
    yaml_config = load_legacy_config(config_file)

    # 配置项定义：key -> (value_type, category, description)
    config_definitions = {
            # Telegram配置
            'API_ID': ('int', 'telegram', 'Telegram API ID'),
            'API_HASH': ('string', 'telegram', 'Telegram API Hash'),
            'BOT_TOKEN': ('string', 'telegram', 'Telegram Bot Token'),
            'ADMIN_ID': ('int', 'telegram', 'Telegram管理员ID'),
            'UP_TELEGRAM': ('bool', 'telegram', '是否上传到Telegram频道网盘'),
            
            # 下载配置
            'SAVE_PATH': ('string', 'download', '下载保存路径'),
            'PROXY_IP': ('string', 'download', '代理IP'),
            'PROXY_PORT': ('string', 'download', '代理端口'),
            'SKIP_SMALL_FILES': ('bool', 'download', '是否跳过小于指定大小的媒体文件'),
            'MIN_FILE_SIZE_MB': ('int', 'download', '最小文件大小（MB），小于此大小的文件将被跳过'),
            'DOWNLOAD_CLEANUP_ENABLED': ('bool', 'download', '是否启用下载目录自动清理'),
            'DOWNLOAD_RETENTION_HOURS': ('int', 'download', '下载文件保留小时数'),
            'DOWNLOAD_CLEANUP_INTERVAL_SECONDS': ('int', 'download', '下载目录清理间隔秒数'),
            
            # Aria2配置
            'RPC_SECRET': ('string', 'aria2', 'Aria2 RPC密钥'),
            'RPC_URL': ('string', 'aria2', 'Aria2 RPC URL'),
            'MAX_CONCURRENT_UPLOADS': ('int', 'upload', '最大并发上传数（默认10）'),
            
            # 直链功能配置
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

    updates = [
        (key, yaml_config[key], value_type, category, description)
        for key, (value_type, category, description) in config_definitions.items()
        if key in yaml_config
    ]
    with db_conn() as connection:
        existing_count = connection.execute(
            "SELECT COUNT(*) FROM config_settings"
        ).fetchone()[0]
    if not updates:
        if existing_count == 0:
            raise RuntimeError("legacy configuration contains no supported settings")
        return False

    now = _now_iso()
    imported = existing_count == 0
    if imported:
        with db_conn() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO config_settings
                    (key, value, value_type, category, description, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        key,
                        _serialize_config_value(value, value_type),
                        value_type,
                        category,
                        description,
                        now,
                    )
                    for key, value, value_type, category, description in updates
                ],
            )

    expected = {
        key: (_serialize_config_value(value, value_type), value_type)
        for key, value, value_type, _category, _description in updates
    }
    placeholders = ",".join("?" for _ in expected)
    with db_conn() as connection:
        actual = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                f"SELECT key, value, value_type FROM config_settings "
                f"WHERE key IN ({placeholders})",
                tuple(expected),
            )
        }
    if actual != expected:
        raise RuntimeError(
            "existing SQLite settings do not match the explicitly supplied legacy YAML"
        )

    # SQLite is committed and verified before touching the separate YAML file.
    # If retirement fails, the explicit bootstrap command can safely be rerun.
    retire_legacy_config(config_file)
    return imported


# ============================================================================
# 上传任务相关函数
# ============================================================================

def create_upload(download_id: int, upload_target: str, remote_path: str = None, max_retries: int = 3) -> int:
    """
    创建一条上传记录，返回 uploads.id。

    Args:
        download_id: 关联的下载任务 ID
        upload_target: 上传目标；新任务固定为 telegram，旧库可能包含 onedrive/gdrive
        remote_path: 远程路径（可选）
        max_retries: 最大重试次数（默认3次）

    Returns:
        上传记录的 ID
    """
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO uploads (
                download_id, upload_target, remote_path, status,
                max_retries, created_at, updated_at
            ) VALUES (?, ?, ?, 'pending', ?, ?, ?)
            """,
            (download_id, upload_target, remote_path, max_retries, now, now),
        )
        upload_id = cur.lastrowid
    # 推送 WebSocket 更新（新记录通知）
    _notify_ws_upload_update(upload_id)
    # 推送统计更新，确保前端刷新列表
    _notify_ws_statistics_update()
    return upload_id


def update_upload_status(upload_id: int, status: str, **kwargs):
    """
    更新上传状态及其他字段。
    
    Args:
        upload_id: 上传记录 ID
        status: 新状态
        **kwargs: 其他要更新的字段（uploaded_size, upload_speed, error_message等）
    """
    now = _now_iso()
    
    # 构建动态更新语句
    fields = ["status = ?", "updated_at = ?"]
    values = [status, now]
    
    for key, value in kwargs.items():
        if key in ['uploaded_size', 'upload_speed', 'error_message', 'error_code', 
                   'failure_reason', 'retry_count', 'remote_path', 'total_size', 'extra']:
            fields.append(f"{key} = ?")
            values.append(value)
    
    values.append(upload_id)
    
    with db_cursor() as cur:
        cur.execute(
            f"""
            UPDATE uploads
               SET {', '.join(fields)}
             WHERE id = ?
            """,
            tuple(values),
        )
    # 推送 WebSocket 更新（仅在状态变化或关键字段更新时）
    if status == 'uploading' or 'uploaded_size' in kwargs or 'upload_speed' in kwargs:
        _notify_ws_upload_update(upload_id)


def check_and_update_download_status_if_file_exists(upload_id: int, file_path: str):
    """
    检查并更新下载记录状态：如果文件已存在且下载记录状态为pending，则标记为completed。
    
    Args:
        upload_id: 上传记录 ID
        file_path: 文件路径
    """
    import os
    try:
        # 获取关联的下载ID
        download_id = None
        with db_cursor() as cur:
            cur.execute("SELECT download_id FROM uploads WHERE id = ?", (upload_id,))
            row = cur.fetchone()
            if row:
                download_id = row[0]
        
        if not download_id:
            return
        
        # 获取下载记录
        download_record = get_download_by_id(download_id)
        if not download_record:
            return
        
        # 如果下载记录状态为pending且文件已存在，更新为completed
        if download_record.get('status') == 'pending' and os.path.exists(file_path):
            try:
                file_size = os.path.getsize(file_path)
                now = _now_iso()
                with db_cursor() as cur:
                    cur.execute(
                        """
                        UPDATE downloads
                           SET status = 'completed',
                               local_path = COALESCE(?, local_path),
                               total_length = COALESCE(?, total_length),
                               completed_length = COALESCE(?, completed_length),
                               completed_at = COALESCE(completed_at, ?),
                               updated_at = ?
                         WHERE id = ?
                        """,
                        (file_path, file_size, file_size, now, now, download_id),
                    )
                # 推送 WebSocket 更新
                gid = download_record.get('gid')
                if gid:
                    _notify_ws_download_update(gid)
                else:
                    _notify_ws_statistics_update()
                logging.info(f"下载记录 {download_id} 已更新为completed（文件已存在）")
            except Exception as e:
                logging.warning(f"更新下载记录状态失败: {e}")
    except Exception as e:
        logging.debug(f"检查下载记录状态失败: {e}")


def mark_upload_started(upload_id: int, total_size: int = None):
    """
    标记上传开始时间。
    
    Args:
        upload_id: 上传记录 ID
        total_size: 可选，文件总大小（字节）
    """
    now = _now_iso()
    with db_cursor() as cur:
        if total_size and total_size > 0:
            cur.execute(
                """
                UPDATE uploads
                   SET status = 'uploading',
                       started_at = COALESCE(started_at, ?),
                       total_size = COALESCE(total_size, ?),
                       updated_at = ?
                 WHERE id = ?
                """,
                (now, total_size, now, upload_id),
            )
        else:
            cur.execute(
                """
                UPDATE uploads
                   SET status = 'uploading',
                       started_at = COALESCE(started_at, ?),
                       updated_at = ?
                 WHERE id = ?
                """,
                (now, now, upload_id),
            )
    # 推送 WebSocket 更新
    _notify_ws_upload_update(upload_id)


def mark_upload_completed(upload_id: int, remote_path: str = None):
    """标记上传完成状态和远程路径。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE uploads
               SET status = 'completed',
                   remote_path = COALESCE(?, remote_path),
                   uploaded_size = COALESCE(total_size, uploaded_size),
                   completed_at = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (remote_path, now, now, upload_id),
        )
    # 推送 WebSocket 更新
    _notify_ws_upload_update(upload_id)


def mark_upload_failed(upload_id: int, failure_reason: str, error_message: str = None, error_code: str = None):
    """
    标记上传失败。
    
    Args:
        upload_id: 上传记录 ID
        failure_reason: 失败原因分类（download_failed/code_error/network_error等）
        error_message: 详细错误信息
        error_code: 错误代码
    """
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE uploads
               SET status = 'failed',
                   failure_reason = ?,
                   error_message = ?,
                   error_code = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (failure_reason, error_message, error_code, now, upload_id),
        )
    # 推送 WebSocket 更新
    _notify_ws_upload_update(upload_id)


def mark_upload_cleaned(upload_id: int):
    """
    标记上传任务对应的文件已被清理（删除）。
    如果该下载任务的所有上传都已清理完成，则将下载状态更新为 completed。
    
    Args:
        upload_id: 上传记录 ID
    """
    now = _now_iso()
    download_id = None
    
    with db_cursor() as cur:
        # 获取关联的下载ID
        cur.execute("SELECT download_id FROM uploads WHERE id = ?", (upload_id,))
        row = cur.fetchone()
        if row:
            download_id = row[0]
        
        # 更新清理状态
        cur.execute(
            """
            UPDATE uploads
               SET cleaned_at = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (now, now, upload_id),
        )
        
        # 如果有关联的下载任务，检查是否所有上传都已清理
        if download_id:
            # 获取该下载任务的所有上传记录
            cur.execute(
                """
                SELECT id, status, cleaned_at
                FROM uploads
                WHERE download_id = ?
                """,
                (download_id,)
            )
            uploads = cur.fetchall()
            
            # 检查是否所有上传都已清理完成
            if uploads:
                all_cleaned = all(
                    upload[2] is not None  # cleaned_at 不为空
                    for upload in uploads
                )
                
                # 如果所有上传都已清理，更新下载状态为 completed
                if all_cleaned:
                    cur.execute(
                        """
                        UPDATE downloads
                           SET status = 'completed',
                               updated_at = ?
                         WHERE id = ? AND status != 'failed'
                        """,
                        (now, download_id)
                    )
                    # 获取 gid 以便推送 WebSocket 更新和更新队列通知消息
                    cur.execute("SELECT gid FROM downloads WHERE id = ?", (download_id,))
                    gid_row = cur.fetchone()
                    if gid_row and gid_row[0]:
                        gid = gid_row[0]
                        _notify_ws_download_update(gid)
                        # 更新队列通知消息（如果存在）
                        try:
                            from WebStreamer.bot.plugins.stream_modules.utils import update_queue_msg_on_cleanup
                            import asyncio
                            loop = None
                            try:
                                loop = asyncio.get_event_loop()
                            except RuntimeError:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                            
                            if loop.is_running():
                                loop.create_task(update_queue_msg_on_cleanup(gid))
                            else:
                                loop.run_until_complete(update_queue_msg_on_cleanup(gid))
                        except Exception as update_e:
                            logging.debug(f"更新队列通知消息失败: {update_e}")
    
    # 推送 WebSocket 更新
    # 同时推送清理更新和上传更新（因为清理状态是上传记录的一部分）
    _notify_ws_cleanup_update(upload_id)
    _notify_ws_upload_update(upload_id)  # 推送上传更新，包含清理状态


def increment_upload_retry(upload_id: int) -> int:
    """
    增加上传重试次数，返回新的重试次数。
    
    Returns:
        新的重试次数
    """
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE uploads
               SET retry_count = retry_count + 1,
                   updated_at = ?
             WHERE id = ?
            """,
            (now, upload_id),
        )
        
        # 查询新的重试次数
        cur.execute("SELECT retry_count FROM uploads WHERE id = ?", (upload_id,))
        row = cur.fetchone()
        return row[0] if row else 0


def get_upload_by_id(upload_id: int):
    """根据 ID 获取上传记录。"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.*, d.local_path, d.status as download_status, d.user_id as user_id
            FROM uploads AS u
            LEFT JOIN downloads AS d ON u.download_id = d.id
            WHERE u.id = ?
            """,
            (upload_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_uploads_by_download(download_id: int):
    """获取某个下载任务的所有上传记录。"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM uploads
            WHERE download_id = ?
            ORDER BY created_at DESC
            """,
            (download_id,),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def fetch_recent_uploads(limit: int = 100, status: str = None, upload_target: str = None, user_id: int | None = None):
    """
    查询最近的上传记录（按创建时间倒序）。支持租户按 user_id 过滤。
    
    Args:
        limit: 返回记录数量限制
        status: 可选，按状态过滤
        upload_target: 可选，按上传目标过滤
        user_id: 可选，按所属租户 user_id 过滤
    
    Returns:
        上传记录列表
    """
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        conditions = []
        params = []
        
        if status:
            conditions.append("u.status = ?")
            params.append(status)
        
        if upload_target:
            conditions.append("u.upload_target = ?")
            params.append(upload_target)

        if user_id is not None:
            conditions.append("d.user_id = ?")
            params.append(int(user_id))
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        
        cur.execute(
            f"""
            SELECT
                u.*,
                d.local_path,
                d.status as download_status,
                d.gid,
                d.user_id,
                m.file_name,
                m.file_size,
                m.chat_id,
                m.message_id
            FROM uploads AS u
            LEFT JOIN downloads AS d ON u.download_id = d.id
            LEFT JOIN tg_media AS m ON d.file_unique_id = m.file_unique_id
            {where_clause}
            ORDER BY u.created_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def count_uploads_by_status(user_id: int | None = None):
    """统计各状态的上传数量。支持租户按 user_id 过滤。"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if user_id is not None:
            cur.execute(
                """
                SELECT u.status, COUNT(*) as count
                FROM uploads AS u
                INNER JOIN downloads AS d ON u.download_id = d.id
                WHERE d.user_id = ?
                GROUP BY u.status
                """,
                (int(user_id),),
            )
        else:
            cur.execute(
                """
                SELECT status, COUNT(*) as count
                FROM uploads
                GROUP BY status
                """
            )
        rows = cur.fetchall()
        return {row['status']: row['count'] for row in rows}


def count_uploads_by_failure_reason(user_id: int | None = None):
    """统计各失败原因的数量。支持租户按 user_id 过滤。"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if user_id is not None:
            cur.execute(
                """
                SELECT u.failure_reason, COUNT(*) as count
                FROM uploads AS u
                INNER JOIN downloads AS d ON u.download_id = d.id
                WHERE u.status = 'failed' AND u.failure_reason IS NOT NULL AND d.user_id = ?
                GROUP BY u.failure_reason
                """,
                (int(user_id),),
            )
        else:
            cur.execute(
                """
                SELECT failure_reason, COUNT(*) as count
                FROM uploads
                WHERE status = 'failed' AND failure_reason IS NOT NULL
                GROUP BY failure_reason
                """
            )
        rows = cur.fetchall()
        return {row['failure_reason']: row['count'] for row in rows}


def get_download_statistics(user_id: int | None = None):
    """
    获取下载统计信息（按消息分组统计，而不是按下载记录统计）。支持租户按 user_id 过滤。
    
    Returns:
        包含各种统计数据的字典
    """
    where_sql = "WHERE d.user_id = ?" if user_id is not None else ""
    params = [int(user_id)] if user_id is not None else []

    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # 获取所有下载记录，包含消息分组和上传状态信息
        cur.execute(
            f"""
            SELECT
                d.id,
                d.status,
                d.total_length,
                d.completed_length,
                m.media_group_id,
                m.chat_id,
                m.message_id,
                u.id AS upload_id,
                u.status AS upload_status,
                u.cleaned_at AS upload_cleaned_at
            FROM downloads AS d
            LEFT JOIN tg_media AS m ON d.file_unique_id = m.file_unique_id
            LEFT JOIN uploads AS u ON u.download_id = d.id
            {where_sql}
            """,
            tuple(params),
        )
        rows = cur.fetchall()

        downloads_by_id = {}
        for row in rows:
            row_dict = dict(row)
            download_id = row_dict['id']
            if download_id not in downloads_by_id:
                downloads_by_id[download_id] = {
                    'id': row_dict['id'],
                    'status': row_dict['status'],
                    'total_length': row_dict['total_length'],
                    'completed_length': row_dict['completed_length'],
                    'media_group_id': row_dict['media_group_id'],
                    'chat_id': row_dict['chat_id'],
                    'message_id': row_dict['message_id'],
                    'uploads': [],
                }
            if row_dict.get('upload_id'):
                downloads_by_id[download_id]['uploads'].append({
                    'id': row_dict['upload_id'],
                    'status': row_dict.get('upload_status'),
                    'cleaned_at': row_dict.get('upload_cleaned_at'),
                })
        
        # 按消息分组
        message_groups: dict[str, list] = {}
        
        for row_dict in downloads_by_id.values():
            # 确定分组键：优先使用 media_group_id，否则使用 chat_id+message_id
            if row_dict.get('media_group_id'):
                group_key = f"group_{row_dict['media_group_id']}"
            elif row_dict.get('chat_id') and row_dict.get('message_id'):
                group_key = f"msg_{row_dict['chat_id']}_{row_dict['message_id']}"
            else:
                # 如果没有分组信息，使用下载ID作为独立消息
                group_key = f"single_{row_dict['id']}"
            
            if group_key not in message_groups:
                message_groups[group_key] = []
            message_groups[group_key].append(row_dict)
        
        # 统计消息状态
        total_messages = len(message_groups)
        completed_messages = 0
        downloading_messages = 0
        failed_messages = 0
        pending_messages = 0
        total_size = 0
        completed_size = 0
        
        for group_key, downloads in message_groups.items():
            def upload_statuses(download_record):
                return [upload.get('status') for upload in download_record.get('uploads', [])]

            def has_upload_failure(download_record):
                return any(status in ['failed', 'cancelled'] for status in upload_statuses(download_record))

            def has_upload_pending(download_record):
                return any(status in ['pending', 'waiting_download'] for status in upload_statuses(download_record))

            def has_upload_active(download_record):
                return any(status == 'uploading' for status in upload_statuses(download_record))

            def has_upload_cleanup_pending(download_record):
                return any(
                    upload.get('status') == 'completed' and not upload.get('cleaned_at')
                    for upload in download_record.get('uploads', [])
                )

            def download_completed(download_record):
                if download_record.get('status') != 'completed':
                    return False
                uploads = download_record.get('uploads', [])
                if not uploads:
                    return True
                return all(upload.get('status') == 'completed' and upload.get('cleaned_at') for upload in uploads)

            def completed_bytes(download_record):
                if not download_completed(download_record):
                    return 0
                return download_record.get('total_length') or download_record.get('completed_length') or 0
            
            # 计算消息状态（优先级：downloading/uploading > failed > pending > completed）
            if any(d.get('status') == 'downloading' or has_upload_active(d) for d in downloads):
                downloading_messages += 1
            elif any(d.get('status') == 'failed' or has_upload_failure(d) for d in downloads):
                failed_messages += 1
            elif any(d.get('status') == 'pending' or has_upload_pending(d) or has_upload_cleanup_pending(d) for d in downloads):
                pending_messages += 1
            elif all(download_completed(d) for d in downloads):
                completed_messages += 1
            
            # 累计文件大小
            for d in downloads:
                total_size += d.get('total_length') or 0
                completed_size += completed_bytes(d)
        
        stats = {
            'total': total_messages,
            'completed': completed_messages,
            'downloading': downloading_messages,
            'failed': failed_messages,
            'pending': pending_messages,
            'waiting': pending_messages,  # waiting 和 pending 相同
            'total_size': total_size or 0,
            'completed_size': completed_size or 0
        }
        
        return stats


def delete_all_downloads(user_id: int | None = None):
    """
    删除所有下载记录、上传记录和关联的 Telegram 媒体记录。
    当传入 user_id 时，仅删除属于该租户的下载、上传及不再被其他下载引用的媒体记录。
    """
    with db_conn() as conn:
        cur = conn.cursor()

        if user_id is not None:
            uid = int(user_id)
            cur.execute(
                "SELECT DISTINCT file_unique_id FROM downloads WHERE user_id = ? AND file_unique_id IS NOT NULL",
                (uid,),
            )
            file_unique_ids = [row[0] for row in cur.fetchall() if row[0]]

            cur.execute("SELECT COUNT(*) FROM downloads WHERE user_id = ?", (uid,))
            download_count = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM uploads WHERE download_id IN (SELECT id FROM downloads WHERE user_id = ?)",
                (uid,),
            )
            upload_count = cur.fetchone()[0]

            cur.execute(
                "DELETE FROM uploads WHERE download_id IN (SELECT id FROM downloads WHERE user_id = ?)",
                (uid,),
            )
            cur.execute("DELETE FROM downloads WHERE user_id = ?", (uid,))

            media_count = 0
            for fuid in file_unique_ids:
                cur.execute("SELECT COUNT(*) FROM downloads WHERE file_unique_id = ?", (fuid,))
                if cur.fetchone()[0] == 0:
                    cur.execute("DELETE FROM tg_media WHERE file_unique_id = ?", (fuid,))
                    media_count += cur.rowcount

            conn.commit()
            return {
                'deleted_downloads': download_count,
                'deleted_uploads': upload_count,
                'deleted_media': media_count,
            }
        
        # 先统计要删除的记录数
        cur.execute("SELECT COUNT(*) FROM downloads")
        download_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM uploads")
        upload_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM tg_media")
        media_count = cur.fetchone()[0]
        
        # 删除所有上传记录（先删除，避免外键约束问题）
        cur.execute("DELETE FROM uploads")
        
        # 删除所有下载记录
        cur.execute("DELETE FROM downloads")
        
        # 删除所有 Telegram 媒体记录（因为下载记录已删除，这些媒体记录也没有用了）
        cur.execute("DELETE FROM tg_media")
        
        conn.commit()
        
        return {
            'deleted_downloads': download_count,
            'deleted_uploads': upload_count,
            'deleted_media': media_count
        }


def delete_download_record(download_id: int, delete_local_file: bool = True):
    """
    删除单个下载记录及其关联的上传记录和本地文件。
    
    Args:
        download_id: 下载记录ID
        delete_local_file: 是否删除本地文件（默认True）
    
    Returns:
        dict: 包含删除结果的字典
    """
    import os
    
    with db_conn() as conn:
        cur = conn.cursor()
        
        # 获取下载记录信息（包括GID和本地路径）
        cur.execute(
            """
            SELECT gid, local_path, file_unique_id
            FROM downloads
            WHERE id = ?
            """,
            (download_id,)
        )
        download_row = cur.fetchone()
        
        if not download_row:
            return {
                'success': False,
                'error': '下载记录不存在'
            }
        
        gid = download_row[0]
        local_path = download_row[1]
        file_unique_id = download_row[2]
        
        # 注意：删除记录时不尝试从Aria2移除任务
        # 因为删除记录是删除数据库记录，不是删除Aria2任务
        # 如果用户想删除Aria2任务，应该使用删除任务的API（DELETE /api/downloads/{gid}）
        # 这样可以避免历史遗留记录（GID已不存在）导致的错误
        
        # 删除本地文件（如果存在且需要删除）
        deleted_file = False
        if delete_local_file and local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
                deleted_file = True
            except Exception as e:
                logging.warning(f"删除本地文件失败: {e}")
        
        # 删除上传记录（外键约束会自动级联删除，但显式删除更清晰）
        cur.execute("DELETE FROM uploads WHERE download_id = ?", (download_id,))
        upload_count = cur.rowcount
        
        # 删除下载记录
        cur.execute("DELETE FROM downloads WHERE id = ?", (download_id,))
        download_deleted = cur.rowcount > 0
        
        # 检查是否还有其他下载记录使用同一个 file_unique_id
        cur.execute(
            "SELECT COUNT(*) FROM downloads WHERE file_unique_id = ?",
            (file_unique_id,)
        )
        remaining_downloads = cur.fetchone()[0]
        
        # 如果没有其他下载记录使用这个媒体，删除媒体记录
        media_deleted = False
        if remaining_downloads == 0:
            cur.execute("DELETE FROM tg_media WHERE file_unique_id = ?", (file_unique_id,))
            media_deleted = cur.rowcount > 0
        
        conn.commit()
        
        return {
            'success': True,
            'download_deleted': download_deleted,
            'upload_count': upload_count,
            'media_deleted': media_deleted,
            'file_deleted': deleted_file,
            'local_path': local_path if deleted_file else None
        }


def get_upload_statistics(user_id: int | None = None):
    """
    获取上传统计信息。支持租户按 user_id 过滤。
    
    Returns:
        包含各种统计数据的字典
    """
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        if user_id is not None:
            uid = int(user_id)
            cur.execute(
                """
                SELECT u.status, COUNT(*) as count
                FROM uploads AS u
                INNER JOIN downloads AS d ON u.download_id = d.id
                WHERE d.user_id = ?
                GROUP BY u.status
                """,
                (uid,),
            )
            status_counts = {row['status']: row['count'] for row in cur.fetchall()}

            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM uploads AS u
                INNER JOIN downloads AS d ON u.download_id = d.id
                WHERE u.cleaned_at IS NOT NULL AND d.user_id = ?
                """,
                (uid,),
            )
            cleaned_count = cur.fetchone()['count']

            cur.execute(
                """
                SELECT
                    SUM(u.total_size) as total_size,
                    SUM(u.uploaded_size) as uploaded_size
                FROM uploads AS u
                INNER JOIN downloads AS d ON u.download_id = d.id
                WHERE d.user_id = ?
                """,
                (uid,),
            )
            size_stats = dict(cur.fetchone())

            cur.execute(
                """
                SELECT u.upload_target, COUNT(*) as count
                FROM uploads AS u
                INNER JOIN downloads AS d ON u.download_id = d.id
                WHERE d.user_id = ?
                GROUP BY u.upload_target
                """,
                (uid,),
            )
            by_target = {row['upload_target']: row['count'] for row in cur.fetchall()}
        else:
            # 统计各状态的数量
            cur.execute(
                """
                SELECT status, COUNT(*) as count
                FROM uploads
                GROUP BY status
                """
            )
            status_counts = {row['status']: row['count'] for row in cur.fetchall()}
            
            # 统计已清理的数量
            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM uploads
                WHERE cleaned_at IS NOT NULL
                """
            )
            cleaned_count = cur.fetchone()['count']
            
            # 总体统计
            cur.execute(
                """
                SELECT
                    SUM(total_size) as total_size,
                    SUM(uploaded_size) as uploaded_size
                FROM uploads
                """
            )
            size_stats = dict(cur.fetchone())
            
            # 按目标统计
            cur.execute(
                """
                SELECT upload_target, COUNT(*) as count
                FROM uploads
                GROUP BY upload_target
                """
            )
            by_target = {row['upload_target']: row['count'] for row in cur.fetchall()}
        
        # 失败原因统计
        by_failure_reason = count_uploads_by_failure_reason(user_id=user_id)
        
        return {
            'total': sum(status_counts.values()),
            'uploading': status_counts.get('uploading', 0),
            'completed': status_counts.get('completed', 0),
            'failed': status_counts.get('failed', 0),
            'pending': status_counts.get('pending', 0) + status_counts.get('waiting_download', 0),
            'cleaned': cleaned_count,
            'total_size': size_stats.get('total_size'),
            'uploaded_size': size_stats.get('uploaded_size') or 0,
            'by_target': by_target,
            'by_failure_reason': by_failure_reason
        }


def get_pending_uploads(upload_target: str = None):
    """
    获取待上传的记录（状态为 pending 且关联的下载已完成）。
    
    Args:
        upload_target: 可选，按上传目标过滤
    
    Returns:
        待上传记录列表
    """
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        target_filter = "AND u.upload_target = ?" if upload_target else ""
        params = [upload_target] if upload_target else []
        
        cur.execute(
            f"""
            SELECT
                u.*,
                d.local_path,
                d.status as download_status,
                m.file_name,
                m.file_size
            FROM uploads AS u
            INNER JOIN downloads AS d ON u.download_id = d.id
            LEFT JOIN tg_media AS m ON d.file_unique_id = m.file_unique_id
            WHERE u.status = 'pending'
              AND d.status = 'completed'
              {target_filter}
            ORDER BY u.created_at ASC
            """,
            tuple(params),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def migrate_upload_data():
    """
    将 downloads 表中的上传数据迁移到 uploads 表。
    仅迁移有 upload_status 或 remote_path 的记录。
    """
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # 查询所有有上传信息的下载记录
        cur.execute(
            """
            SELECT id, upload_status, remote_path, created_at
            FROM downloads
            WHERE upload_status IS NOT NULL OR remote_path IS NOT NULL
            """
        )
        downloads = cur.fetchall()
        
        migrated_count = 0
        for download in downloads:
            download_id = download['id']
            old_status = download['upload_status'] or 'pending'
            remote_path = download['remote_path']
            created_at = download['created_at']
            
            # 映射旧状态到新状态
            status_map = {
                'pending': 'pending',
                'uploading': 'uploading',
                'uploaded': 'completed',
                'failed': 'failed'
            }
            new_status = status_map.get(old_status, 'pending')
            
            # 检查是否已经迁移过
            cur.execute(
                "SELECT COUNT(*) as count FROM uploads WHERE download_id = ?",
                (download_id,)
            )
            if cur.fetchone()['count'] > 0:
                continue  # 已迁移，跳过
            
            upload_target = 'telegram' if str(remote_path or '').startswith('telegram://') else 'onedrive'

            # 创建上传记录：TG 索引记录迁移为 telegram，其余保留为历史第三方网盘记录
            cur.execute(
                """
                INSERT INTO uploads (
                    download_id, upload_target, remote_path, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (download_id, upload_target, remote_path, new_status, created_at, created_at)
            )
            migrated_count += 1
        
        conn.commit()
        logger.info(f"已迁移 {migrated_count} 条上传记录")
        return migrated_count


# ======================== 用户管理 ========================

def ensure_default_admin():
    """Create the first administrator only from an explicit strong secret."""
    from auth import hash_password
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            password_file = os.environ.get(
                "MISTRELAY_ADMIN_PASSWORD_FILE",
                "/app/db/admin-password",
            )
            try:
                password_stat = os.stat(password_file, follow_symlinks=False)
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "initial administrator password file does not exist"
                ) from exc
            if not stat.S_ISREG(password_stat.st_mode):
                raise RuntimeError("initial administrator password must be a regular file")
            if password_stat.st_uid != os.geteuid():
                raise RuntimeError("initial administrator password file must be owned by the runtime user")
            if stat.S_IMODE(password_stat.st_mode) & 0o077:
                raise RuntimeError("initial administrator password file permissions must not allow group or other access")
            with open(password_file, "r", encoding="utf-8") as handle:
                password = handle.read().strip()
            if not 16 <= len(password) <= 512:
                raise RuntimeError(
                    "initial administrator password must be provided via "
                    "MISTRELAY_ADMIN_PASSWORD_FILE and contain 16-512 characters"
                )
            now = _now_iso()
            cur.execute(
                "INSERT INTO users (username, password_hash, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("admin", hash_password(password), "admin", now, now),
            )
            cur.execute(
                """
                INSERT OR REPLACE INTO config_settings
                    (key, value, value_type, category, description, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "SECURITY_BASELINE_VERSION",
                    "2",
                    "int",
                    "security",
                    "Applied security baseline version",
                    now,
                ),
            )
            logger.info("已从显式初始密码文件创建管理员账号 admin")


def browse_tg_media(
    page: int = 1,
    page_size: int = 50,
    search: str = None,
    mime_filter: str = None,
    sort_by: str = 'message_date',
    sort_desc: bool = True,
    media_group_id: str = None,
    chat_id: int | None = None,
    chat_ids: list[int] | None = None,
) -> dict:
    """
    分页浏览 tg_media 表中的媒体文件。支持单频道隔离或多频道联合挂载查询。

    默认将 media_group_id 聚合成虚拟文件夹；传入 media_group_id 时返回组内真实文件。
    """
    allowed_sort = {'message_date', 'file_size', 'file_name'}
    if sort_by not in allowed_sort:
        sort_by = 'message_date'

    conditions = ["message_id > 0"]
    params: list = []

    target_cids = []
    if chat_ids is not None:
        target_cids = [int(c) for c in chat_ids if c is not None]
    elif chat_id is not None:
        target_cids = [int(chat_id)]

    if len(target_cids) == 1:
        conditions.append("chat_id = ?")
        params.append(target_cids[0])
    elif len(target_cids) > 1:
        placeholders = ",".join(["?"] * len(target_cids))
        conditions.append(f"chat_id IN ({placeholders})")
        params.extend(target_cids)

    if media_group_id:
        conditions.append("media_group_id = ?")
        params.append(media_group_id)

    if search:
        conditions.append("(file_name LIKE ? OR caption LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])

    if mime_filter:
        mime_map = {
            'video': 'video/%',
            'image': 'image/%',
            'audio': 'audio/%',
            'document': None,
        }
        if mime_filter in mime_map:
            if mime_filter == 'document':
                conditions.append(
                    "mime_type NOT LIKE 'video/%' AND mime_type NOT LIKE 'image/%' AND mime_type NOT LIKE 'audio/%'"
                )
            else:
                conditions.append("mime_type LIKE ?")
                params.append(mime_map[mime_filter])

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    offset = (page - 1) * page_size

    if media_group_id:
        with db_conn() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            cur.execute(f"SELECT COUNT(*) as cnt FROM tg_media {where}", tuple(params))
            count_row = cur.fetchone()
            total = count_row['cnt'] if count_row else 0

            order_col = {
                'file_size': 'COALESCE(file_size, 0)',
                'file_name': 'LOWER(COALESCE(file_name, ""))',
                'message_date': 'COALESCE(message_date, "")',
            }.get(sort_by, 'COALESCE(message_date, "")')
            order_dir = 'DESC' if sort_desc else 'ASC'

            cur.execute(
                f"""
                SELECT
                    file_unique_id, chat_id, message_id, file_id,
                    file_name, mime_type, file_size,
                    duration, width, height,
                    caption, message_date,
                    media_group_id, supports_streaming
                FROM tg_media
                {where}
                ORDER BY {order_col} {order_dir}
                LIMIT ? OFFSET ?
                """,
                tuple(params) + (page_size, offset),
            )
            items = [dict(r) for r in cur.fetchall()]

        for item in items:
            item['entry_type'] = 'file'

        return {
            'items': items,
            'total': total,
            'page': page,
            'page_size': page_size,
            'grouped': False,
            'media_group_id': media_group_id,
        }

    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute(
            f"""
            SELECT
                file_unique_id, chat_id, message_id, file_id,
                file_name, mime_type, file_size,
                duration, width, height,
                caption, message_date,
                media_group_id, supports_streaming
            FROM tg_media
            {where}
            """,
            tuple(params),
        )
        rows = [dict(r) for r in cur.fetchall()]

    entries: list[dict] = []
    groups: dict[str, list[dict]] = {}

    for row in rows:
        group_id = row.get('media_group_id')
        if group_id:
            groups.setdefault(group_id, []).append(row)
        else:
            row['entry_type'] = 'file'
            entries.append(row)

    for group_id, group_items in groups.items():
        group_items.sort(key=lambda item: item.get('message_date') or '', reverse=True)
        representative = next((item for item in group_items if item.get('file_name')), group_items[0])
        total_size = sum(int(item.get('file_size') or 0) for item in group_items)
        latest_date = max((item.get('message_date') or '' for item in group_items), default='')
        display_name = _tg_media_folder_name(representative.get('file_name'), group_id)
        mime_types = {item.get('mime_type') or '' for item in group_items}

        folder = {
            **representative,
            'entry_type': 'folder',
            'media_group_id': group_id,
            'file_name': display_name,
            'representative_file_name': representative.get('file_name'),
            'representative_mime_type': representative.get('mime_type'),
            'message_date': latest_date,
            'file_size': total_size,
            'total_size': total_size,
            'item_count': len(group_items),
            'mime_type': 'application/x-mistrelay-media-group',
            'group_mime_types': sorted(mime for mime in mime_types if mime),
        }
        entries.append(folder)

    entries.sort(key=lambda item: _tg_media_sort_value(item, sort_by), reverse=sort_desc)
    total = len(entries)

    return {
        'items': entries[offset:offset + page_size],
        'total': total,
        'page': page,
        'page_size': page_size,
        'grouped': True,
    }



def _tg_media_folder_name(file_name: str | None, group_id: str) -> str:
    name = (file_name or '').strip()
    if not name:
        return f"媒体组 {group_id}"

    path_name = name.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
    if path_name in ('', '.', '..'):
        return name

    dot_index = path_name.rfind('.')
    if dot_index <= 0:
        return name

    stem = path_name[:dot_index].strip()
    return stem or name

def _tg_media_sort_value(item: dict, sort_by: str):
    if sort_by == 'file_size':
        return int(item.get('total_size') or item.get('file_size') or 0)
    if sort_by == 'file_name':
        return (item.get('file_name') or '').lower()
    return item.get('message_date') or ''


def get_tg_media_stats(chat_id: int | None = None, chat_ids: list[int] | None = None) -> dict:
    """统计 tg_media 表的概览信息。支持按单个 chat_id 或多频道 chat_ids 进行租户频道隔离。"""
    conditions = ["message_id > 0"]
    params = []

    target_cids = []
    if chat_ids is not None:
        target_cids = [int(c) for c in chat_ids if c is not None]
    elif chat_id is not None:
        target_cids = [int(chat_id)]

    if len(target_cids) == 1:
        conditions.append("chat_id = ?")
        params.append(target_cids[0])
    elif len(target_cids) > 1:
        placeholders = ",".join(["?"] * len(target_cids))
        conditions.append(f"chat_id IN ({placeholders})")
        params.extend(target_cids)

    where_sql = f"WHERE {' AND '.join(conditions)}"

    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute(
            f"""
            SELECT
                COUNT(*) as cnt,
                COALESCE(SUM(file_size), 0) as total_size,
                SUM(CASE WHEN mime_type LIKE 'video/%' THEN 1 ELSE 0 END) as videos,
                SUM(CASE WHEN mime_type LIKE 'image/%' THEN 1 ELSE 0 END) as images,
                SUM(CASE WHEN mime_type LIKE 'audio/%' THEN 1 ELSE 0 END) as audios,
                SUM(CASE WHEN mime_type NOT LIKE 'video/%'
                          AND mime_type NOT LIKE 'image/%'
                          AND mime_type NOT LIKE 'audio/%' THEN 1 ELSE 0 END) as documents
            FROM tg_media
            {where_sql}
            """,
            tuple(params),
        )
        row = cur.fetchone()

    return {
        'total_count': (row['cnt'] if row else 0) or 0,
        'total_size': (row['total_size'] if row else 0) or 0,
        'videos': (row['videos'] if row else 0) or 0,
        'images': (row['images'] if row else 0) or 0,
        'audios': (row['audios'] if row else 0) or 0,
        'documents': (row['documents'] if row else 0) or 0,
    }


def get_tg_media_record_by_message_id(
    message_id: int,
    chat_id: int | None = None,
    secure_hash: str | None = None,
    hash_len: int = 6,
) -> dict | None:
    """根据频道消息 ID 获取单条 tg_media 记录。支持按 chat_id 或 secure_hash 跨频道精确匹配。"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if chat_id is not None:
            cur.execute(
                """
                SELECT
                    file_unique_id, chat_id, message_id, file_id,
                    file_name, mime_type, file_size, duration,
                    width, height, caption, message_date,
                    media_group_id, supports_streaming, thumbs
                FROM tg_media
                WHERE message_id = ? AND chat_id = ?
                """,
                (message_id, int(chat_id)),
            )
            row = cur.fetchone()
            return dict(row) if row else None

        cur.execute(
            """
            SELECT
                file_unique_id, chat_id, message_id, file_id,
                file_name, mime_type, file_size, duration,
                width, height, caption, message_date,
                media_group_id, supports_streaming, thumbs
            FROM tg_media
            WHERE message_id = ?
            """,
            (message_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        if not rows:
            return None
        if len(rows) == 1 or not secure_hash:
            return rows[0]

        import hashlib
        for r in rows:
            uid = r.get("file_unique_id", "")
            raw_uid = uid.split("@")[0]
            h1 = hashlib.sha256(uid.encode("utf-8")).hexdigest()[:hash_len]
            h2 = hashlib.sha256(raw_uid.encode("utf-8")).hexdigest()[:hash_len]
            if secure_hash in (h1, h2):
                return r
        return rows[0]


def get_tg_media_records_by_media_group(media_group_id: str, chat_id: int | None = None) -> list[dict]:
    """根据 Telegram 媒体组 ID 获取对应 tg_media 记录。支持按 chat_id 过滤。"""
    conditions = ["media_group_id = ?"]
    params = [media_group_id]
    if chat_id is not None:
        conditions.append("chat_id = ?")
        params.append(int(chat_id))

    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT
                file_unique_id, chat_id, message_id, file_id,
                file_name, mime_type, file_size, duration,
                width, height, caption, message_date,
                media_group_id, supports_streaming, thumbs
            FROM tg_media
            WHERE {' AND '.join(conditions)}
            ORDER BY message_id ASC
            """,
            tuple(params),
        )
        return [dict(row) for row in cur.fetchall()]


def list_all_tg_media_records(chat_id: int | None = None) -> list[dict]:
    """列出全部 tg_media 记录，用于批量清理 tg 网盘及缩略图预热。支持按 chat_id 过滤。"""
    conditions = ["message_id > 0"]
    params = []
    if chat_id is not None:
        conditions.append("chat_id = ?")
        params.append(int(chat_id))
    where_sql = f"WHERE {' AND '.join(conditions)}"

    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT
                file_unique_id, chat_id, message_id, file_name,
                mime_type, file_size, file_id, media_group_id, message_date
            FROM tg_media
            {where_sql}
            ORDER BY message_id ASC
            """,
            tuple(params),
        )
        return [dict(row) for row in cur.fetchall()]


def delete_tg_media_records(file_unique_ids: list[str], chat_id: int | None = None) -> dict:
    """
    删除指定 tg_media 记录及其关联的 downloads/uploads 记录。
    支持按 chat_id 进行安全所有权校验（防止跨租户误删）。

    注意：
    - 这里只清理数据库记录，不删除本地文件。
    - uploads/downloads 不一定开启了外键级联，因此显式删除。
    """
    ids = [file_unique_id for file_unique_id in dict.fromkeys(file_unique_ids) if file_unique_id]
    if not ids:
        return {
            'deleted_media': 0,
            'deleted_downloads': 0,
            'deleted_uploads': 0,
        }

    placeholders = ','.join('?' for _ in ids)

    with db_conn() as conn:
        cur = conn.cursor()

        if chat_id is not None:
            cur.execute(
                f"SELECT file_unique_id FROM tg_media WHERE file_unique_id IN ({placeholders}) AND chat_id = ?",
                tuple(ids + [int(chat_id)]),
            )
            filtered_ids = [r[0] for r in cur.fetchall()]
            if not filtered_ids:
                return {'deleted_media': 0, 'deleted_downloads': 0, 'deleted_uploads': 0}
            ids = filtered_ids
            placeholders = ','.join('?' for _ in ids)

        cur.execute(
            f"SELECT COUNT(*) FROM tg_media WHERE file_unique_id IN ({placeholders})",
            tuple(ids),
        )
        media_count = cur.fetchone()[0]

        cur.execute(
            f"SELECT id FROM downloads WHERE file_unique_id IN ({placeholders})",
            tuple(ids),
        )
        download_ids = [row[0] for row in cur.fetchall()]
        download_count = len(download_ids)

        upload_count = 0
        if download_ids:
            upload_placeholders = ','.join('?' for _ in download_ids)
            cur.execute(
                f"SELECT COUNT(*) FROM uploads WHERE download_id IN ({upload_placeholders})",
                tuple(download_ids),
            )
            upload_count = cur.fetchone()[0]
            cur.execute(
                f"DELETE FROM uploads WHERE download_id IN ({upload_placeholders})",
                tuple(download_ids),
            )

        cur.execute(
            f"SELECT message_id, file_name, chat_id FROM tg_media WHERE file_unique_id IN ({placeholders})",
            tuple(ids),
        )
        records_to_clean = cur.fetchall()
        if records_to_clean:
            try:
                from thumbnail_generator import remove_cached_telegram_thumbnail
                for rec_row in records_to_clean:
                    remove_cached_telegram_thumbnail(rec_row[0], rec_row[1], rec_row[2])
            except Exception:
                pass

        cur.execute(
            f"DELETE FROM downloads WHERE file_unique_id IN ({placeholders})",
            tuple(ids),
        )
        cur.execute(
            f"DELETE FROM tg_media WHERE file_unique_id IN ({placeholders})",
            tuple(ids),
        )

    return {
        'deleted_media': media_count,
        'deleted_downloads': download_count,
        'deleted_uploads': upload_count,
    }


def parse_extra_channels(val: Any) -> list[int]:
    """安全解析用户的 extra_channels 字段为整数列表"""
    if not val:
        return []
    if isinstance(val, (list, tuple, set)):
        res = []
        for x in val:
            try:
                res.append(int(x))
            except (ValueError, TypeError):
                pass
        return sorted(list(set(res)))
    if isinstance(val, str):
        val = val.strip()
        if not val or val in ("[]", "null", "None"):
            return []
        try:
            data = json.loads(val)
            if isinstance(data, list):
                return parse_extra_channels(data)
        except Exception:
            parts = [p.strip() for p in val.split(",") if p.strip()]
            return parse_extra_channels(parts)
    return []


def get_user_all_channel_ids(user: dict | int | None) -> list[int]:
    """获取用户关联的全部有效存储频道 ID 列表（当前主频道 bin_channel_id + 历史 extra_channels）"""
    if user is None:
        return []
    if isinstance(user, int):
        user = get_user_by_id(user)
        if not user:
            return []
    res = []
    main_cid = user.get("bin_channel_id")
    if main_cid is not None:
        try:
            res.append(int(main_cid))
        except (ValueError, TypeError):
            pass
    extras = parse_extra_channels(user.get("extra_channels"))
    for cid in extras:
        if cid not in res:
            res.append(cid)
    return res


def append_user_extra_channel(user_id: int, channel_id: int | str) -> list[int]:
    """向指定用户的 extra_channels 追加一个历史频道 ID（幂等去重）"""
    try:
        cid = int(channel_id)
    except (ValueError, TypeError):
        return []

    user = get_user_by_id(user_id)
    if not user:
        return []

    current_extras = parse_extra_channels(user.get("extra_channels"))
    if cid not in current_extras:
        current_extras.append(cid)
        update_user_record(user_id, extra_channels=json.dumps(current_extras))

    return current_extras


def remove_user_extra_channel(user_id: int, channel_id: int | str) -> list[int]:
    """从指定用户的 extra_channels 移除一个历史频道 ID"""
    try:
        cid = int(channel_id)
    except (ValueError, TypeError):
        return []

    user = get_user_by_id(user_id)
    if not user:
        return []

    current_extras = parse_extra_channels(user.get("extra_channels"))
    if cid in current_extras:
        current_extras.remove(cid)
        update_user_record(user_id, extra_channels=json.dumps(current_extras))

    return current_extras


def get_user_by_username(username: str) -> dict | None:
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        if not row:
            return None
        res = dict(row)
        if "extra_channels" in res:
            res["extra_channels"] = parse_extra_channels(res["extra_channels"])
        return res


def get_user_by_id(user_id: int) -> dict | None:
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, username, role, tg_user_id, tg_username, tg_first_name,
                   dc_id, bin_channel_id, bin_channel_username, creator_account_id,
                   extra_channels,
                   created_at, updated_at
            FROM users WHERE id = ?
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        res = dict(row)
        res["extra_channels"] = parse_extra_channels(res.get("extra_channels"))
        return res


def get_channel_username_by_chat_id(chat_id: int | str) -> str | None:
    """根据 chat_id 查询专属存储频道的公开 username"""
    if not chat_id:
        return None
    try:
        cid = int(chat_id)
    except (ValueError, TypeError):
        return None
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT bin_channel_username FROM users WHERE bin_channel_id = ?",
            (cid,),
        )
        row = cur.fetchone()
        if row and row["bin_channel_username"]:
            return row["bin_channel_username"]
        return None


def create_tg_register_code(
    code: str,
    tg_user_id: int,
    tg_username: str | None,
    tg_first_name: str | None,
    detected_dc_id: int,
    expires_minutes: int = 10,
) -> dict:
    """创建或更新 Telegram 用户的 6 位注册验证码"""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=expires_minutes)
    created_at = _now_iso()
    expires_at = expires.isoformat(timespec="seconds").replace("+00:00", "Z")

    with db_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO tg_register_codes (
                code, tg_user_id, tg_username, tg_first_name,
                detected_dc_id, created_at, expires_at, used
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (str(code).strip(), int(tg_user_id), tg_username, tg_first_name, int(detected_dc_id), created_at, expires_at),
        )
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM tg_register_codes WHERE code = ?", (str(code).strip(),)
        ).fetchone()
        return dict(row)


def get_tg_register_code(code: str) -> dict | None:
    """查询指定注册验证码信息"""
    if not code:
        return None
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM tg_register_codes WHERE code = ?", (str(code).strip(),)
        ).fetchone()
        return dict(row) if row else None


def verify_and_consume_tg_register_code(code: str) -> dict | None:
    """核销注册验证码。如果有效且未过期未被使用，标记为已用并返回记录"""
    if not code:
        return None
    now = _now_iso()
    code_str = str(code).strip()
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT * FROM tg_register_codes
             WHERE code = ?
               AND used = 0
               AND expires_at > ?
            """,
            (code_str, now),
        ).fetchone()
        if not row:
            return None
        rec = dict(row)
        conn.execute(
            "UPDATE tg_register_codes SET used = 1 WHERE code = ?",
            (code_str,),
        )
        return rec


def create_tenant_user(
    username: str,
    password_hash: str,
    tg_user_id: int | None = None,
    tg_username: str | None = None,
    tg_first_name: str | None = None,
    dc_id: int | None = None,
    bin_channel_id: int | None = None,
    bin_channel_username: str | None = None,
    creator_account_id: int | None = None,
    role: str = "user",
) -> dict:
    """创建绑专属频道的租户用户"""
    now = _now_iso()
    tg_uid_val = int(tg_user_id) if tg_user_id is not None else None
    dc_id_val = int(dc_id) if dc_id is not None else None
    bin_cid_val = int(bin_channel_id) if bin_channel_id is not None else None
    creator_id_val = int(creator_account_id) if creator_account_id is not None else None

    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO users (
                username, password_hash, role, tg_user_id, tg_username, tg_first_name,
                dc_id, bin_channel_id, bin_channel_username, creator_account_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username, password_hash, role, tg_uid_val, tg_username, tg_first_name,
                dc_id_val, bin_cid_val, bin_channel_username, creator_id_val,
                now, now,
            ),
        )
        user_id = cur.lastrowid
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row)


def get_user_by_tg_id(tg_user_id: int) -> dict | None:
    """根据 Telegram User ID 查询绑定的系统用户"""
    if not tg_user_id:
        return None
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM users WHERE tg_user_id = ?", (int(tg_user_id),)
        ).fetchone()
        return dict(row) if row else None


def list_users() -> list[dict]:
    """列出系统中所有用户及其租户绑定信息、存储频道容量统计（密码哈希已脱敏）"""
    now = _now_iso()
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT u.id, u.username, u.role, u.tg_user_id, u.tg_username, u.tg_first_name,
                   u.dc_id, u.bin_channel_id, u.bin_channel_username, u.creator_account_id,
                   u.extra_channels,
                   u.created_at, u.updated_at,
                   p.phone AS creator_phone,
                   p.status AS creator_account_status
            FROM users u
            LEFT JOIN tg_protocol_accounts p ON p.id = u.creator_account_id
            ORDER BY u.id ASC
            """
        ).fetchall()

        # Global BIN_CHANNEL fallback for admin without dedicated channel
        global_bin = None
        try:
            cfg_row = conn.execute("SELECT value FROM config_settings WHERE key = 'BIN_CHANNEL'").fetchone()
            if cfg_row and cfg_row["value"]:
                global_bin = int(cfg_row["value"])
        except Exception:
            pass

        # Pre-aggregate tg_media stats by chat_id
        media_stats_rows = conn.execute(
            """
            SELECT chat_id,
                   COUNT(*) AS media_count,
                   COALESCE(SUM(file_size), 0) AS total_size,
                   SUM(CASE WHEN mime_type LIKE 'video/%' THEN 1 ELSE 0 END) AS video_count,
                   SUM(CASE WHEN mime_type LIKE 'image/%' THEN 1 ELSE 0 END) AS image_count
            FROM tg_media
            GROUP BY chat_id
            """
        ).fetchall()
        media_by_chat = {}
        for mr in media_stats_rows:
            cid = mr["chat_id"]
            if cid is not None:
                try:
                    media_by_chat[int(cid)] = dict(mr)
                except (ValueError, TypeError):
                    media_by_chat[str(cid)] = dict(mr)

        # Pre-aggregate downloads by user_id
        dl_rows = conn.execute(
            "SELECT user_id, COUNT(*) AS dl_count FROM downloads WHERE user_id IS NOT NULL GROUP BY user_id"
        ).fetchall()
        dl_by_user = {int(r["user_id"]): int(r["dl_count"]) for r in dl_rows if r["user_id"] is not None}

        # Pre-aggregate active sessions by user_id
        sess_rows = conn.execute(
            "SELECT user_id, COUNT(*) AS sess_count FROM auth_sessions WHERE revoked_at IS NULL AND expires_at > ? GROUP BY user_id",
            (now,),
        ).fetchall()
        sess_by_user = {int(r["user_id"]): int(r["sess_count"]) for r in sess_rows if r["user_id"] is not None}

        result = []
        for r in rows:
            item = dict(r)
            uid = item["id"]
            target_chats = []
            if item.get("bin_channel_id"):
                try:
                    target_chats.append(int(item["bin_channel_id"]))
                except (ValueError, TypeError):
                    pass
            elif item.get("role") == "admin" and global_bin:
                target_chats.append(int(global_bin))
            for ex in parse_extra_channels(item.get("extra_channels")):
                if ex not in target_chats:
                    target_chats.append(ex)

            m_count = 0
            t_size = 0
            v_count = 0
            i_count = 0
            for cid in target_chats:
                mstat = media_by_chat.get(cid)
                if mstat:
                    m_count += int(mstat["media_count"] or 0)
                    t_size += int(mstat["total_size"] or 0)
                    v_count += int(mstat["video_count"] or 0)
                    i_count += int(mstat["image_count"] or 0)

            item["media_count"] = m_count
            item["total_size"] = t_size
            item["video_count"] = v_count
            item["image_count"] = i_count
            item["extra_channels"] = parse_extra_channels(item.get("extra_channels"))
            item["download_count"] = dl_by_user.get(uid, 0)
            item["active_sessions"] = sess_by_user.get(uid, 0)
            if not item.get("bin_channel_id"):
                item["creator_status"] = "none"
            elif not item.get("creator_account_id"):
                item["creator_status"] = "untracked"
            else:
                acc_status = str(item.get("creator_account_status") or "").lower()
                if acc_status in ("active", "ready", "ok", "limit_reached", "cooling_down"):
                    item["creator_status"] = "healthy"
                else:
                    item["creator_status"] = "warning"
            result.append(item)
        return result


def update_user_record(user_id: int, **fields) -> dict | None:
    """更新用户字段（支持修改角色、绑定频道、TG 信息、历史 extra_channels 等）"""
    allowed_keys = {
        "username", "role", "tg_user_id", "tg_username", "tg_first_name",
        "dc_id", "bin_channel_id", "bin_channel_username", "creator_account_id",
        "extra_channels",
    }
    updates = {}
    for k, v in fields.items():
        if k in allowed_keys:
            if k == "extra_channels":
                if isinstance(v, (list, tuple, set)):
                    updates[k] = json.dumps(sorted(list(set(int(x) for x in v if x is not None))))
                else:
                    updates[k] = str(v)
            else:
                updates[k] = v
    if not updates:
        return get_user_by_id(user_id)
    updates["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    params = list(updates.values()) + [int(user_id)]
    with db_conn() as conn:
        conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", tuple(params))
    return get_user_by_id(user_id)


def delete_user_record(user_id: int, delete_media_records: bool = False) -> dict:
    """删除指定用户，并可选清理其专属频道下的数据库记录与离线下载记录"""
    target = get_user_by_id(user_id)
    if not target:
        raise ValueError("用户不存在")

    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        if target.get("role") == "admin":
            admin_cnt = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]
            if admin_cnt <= 1:
                raise ValueError("不能删除系统中唯一的管理员账号")

        now = _now_iso()
        conn.execute(
            "UPDATE auth_sessions SET revoked_at = ?, revoked_reason = 'user_deleted' WHERE user_id = ? AND revoked_at IS NULL",
            (now, int(user_id)),
        )
        conn.execute("DELETE FROM auth_sessions WHERE user_id = ?", (int(user_id),))

        # 级联清理该租户名下的所有边缘节点与绑定的安装 Token
        conn.execute("DELETE FROM edge_node_tokens WHERE tenant_id = ?", (int(user_id),))
        conn.execute("DELETE FROM edge_nodes WHERE tenant_id = ?", (int(user_id),))

        deleted_media = 0
        deleted_downloads = 0
        if delete_media_records:
            cur_d_ids = conn.execute("SELECT id FROM downloads WHERE user_id = ?", (int(user_id),)).fetchall()
            if cur_d_ids:
                dids = [r[0] for r in cur_d_ids]
                ph = ",".join("?" for _ in dids)
                conn.execute(f"DELETE FROM uploads WHERE download_id IN ({ph})", tuple(dids))

            cur_d = conn.execute("DELETE FROM downloads WHERE user_id = ?", (int(user_id),))
            deleted_downloads = cur_d.rowcount
            if target.get("bin_channel_id"):
                cid = int(target["bin_channel_id"])
                cur_m_rows = conn.execute("SELECT file_unique_id, message_id, file_name, chat_id FROM tg_media WHERE chat_id = ?", (cid,)).fetchall()
                if cur_m_rows:
                    try:
                        from thumbnail_generator import remove_cached_telegram_thumbnail
                        for mr in cur_m_rows:
                            remove_cached_telegram_thumbnail(mr["message_id"], mr["file_name"], mr["chat_id"])
                    except Exception:
                        pass
                    fuids = [r["file_unique_id"] for r in cur_m_rows]
                    ph = ",".join("?" for _ in fuids)
                    conn.execute(f"DELETE FROM downloads WHERE file_unique_id IN ({ph})", tuple(fuids))

                try:
                    conn.execute("DELETE FROM tg_channel_files WHERE storage_channel_id = ?", (cid,))
                except Exception:
                    pass

                cur_m = conn.execute("DELETE FROM tg_media WHERE chat_id = ?", (cid,))
                deleted_media = cur_m.rowcount
        else:
            conn.execute("UPDATE downloads SET user_id = NULL WHERE user_id = ?", (int(user_id),))

        conn.execute("DELETE FROM users WHERE id = ?", (int(user_id),))
        return {
            "deleted_user_id": int(user_id),
            "deleted_username": target.get("username"),
            "deleted_media": deleted_media,
            "deleted_downloads": deleted_downloads,
        }


def fetch_channel_media_records(chat_id: int) -> list[dict]:
    """查询指定频道下的全部有效媒体记录，按 message_id 升序排列供无损平移使用"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM tg_media
            WHERE chat_id = ? AND message_id > 0
            ORDER BY message_id ASC
            """,
            (int(chat_id),),
        ).fetchall()
        return [dict(r) for r in rows]


def remap_single_media_pointer(
    old_chat_id: int,
    old_msg_id: int,
    new_chat_id: int,
    new_msg_id: int,
    new_file_id: str | None = None,
) -> bool:
    """原子更新单条媒体的 (chat_id, message_id) 指针"""
    with db_conn() as conn:
        updates = ["chat_id = ?", "message_id = ?"]
        params: list = [int(new_chat_id), int(new_msg_id)]
        if new_file_id:
            updates.append("file_id = ?")
            params.append(str(new_file_id))
        params.extend([int(old_chat_id), int(old_msg_id)])
        cur = conn.execute(
            f"UPDATE tg_media SET {', '.join(updates)} WHERE chat_id = ? AND message_id = ?",
            tuple(params),
        )
        try:
            conn.execute(
                "UPDATE tg_channel_files SET chat_id = ?, message_id = ? WHERE chat_id = ? AND message_id = ?",
                (int(new_chat_id), int(new_msg_id), int(old_chat_id), int(old_msg_id)),
            )
        except Exception:
            pass
        return cur.rowcount > 0


def finalize_channel_migration(
    user_id: int,
    old_chat_id: int,
    new_chat_id: int,
    new_username: str | None = None,
    new_dc_id: int | None = None,
    new_creator_id: int | None = None,
) -> dict | None:
    """完成租户专属频道迁移，原子更新用户专属频道绑定及关联下载任务的目标频道"""
    now = _now_iso()
    with db_conn() as conn:
        fields = [
            "bin_channel_id = ?",
            "updated_at = ?",
        ]
        params: list = [int(new_chat_id), now]
        if new_username is not None:
            fields.append("bin_channel_username = ?")
            params.append(str(new_username))
        if new_dc_id is not None:
            fields.append("dc_id = ?")
            params.append(int(new_dc_id))
        if new_creator_id is not None:
            fields.append("creator_account_id = ?")
            params.append(int(new_creator_id))
        params.append(int(user_id))
        conn.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE id = ?",
            tuple(params),
        )
        conn.execute(
            "UPDATE downloads SET target_channel_id = ? WHERE user_id = ? AND target_channel_id = ?",
            (int(new_chat_id), int(user_id), int(old_chat_id)),
        )
    return get_user_by_id(user_id)


def list_tg_register_codes(limit: int = 20) -> list[dict]:
    """查询最近生成的 Telegram 注册验证码记录"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM tg_register_codes ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]


def update_user_password(user_id: int, new_password_hash: str):
    with db_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (new_password_hash, _now_iso(), user_id),
        )


def create_auth_session(
    user_id: int,
    token_hash: str,
    expires_at: str,
    device_id: str | None = None,
    session_name: str | None = None,
) -> dict:
    """创建桌面客户端 refresh token 会话，数据库只保存 token hash。"""
    now = _now_iso()
    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO auth_sessions (
                user_id, token_hash, device_id, session_name,
                expires_at, created_at, last_used_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, token_hash, device_id, session_name, expires_at, now, now),
        )
        session_id = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM auth_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return dict(row)


def get_auth_session(
    token_hash: str,
    *,
    include_revoked: bool = False,
    touch: bool = True,
) -> dict | None:
    """按 token hash 查询有效会话；默认不返回已撤销或已过期会话。"""
    now = _now_iso()
    conditions = ["token_hash = ?"]
    params: list = [token_hash]
    if not include_revoked:
        conditions.append("revoked_at IS NULL")
        conditions.append("expires_at > ?")
        params.append(now)

    with db_conn() as conn:
        cur = conn.execute(
            f"SELECT * FROM auth_sessions WHERE {' AND '.join(conditions)}",
            tuple(params),
        )
        row = cur.fetchone()
        if not row:
            return None
        session = dict(row)
        if touch and not session.get("revoked_at") and session.get("expires_at", "") > now:
            conn.execute(
                "UPDATE auth_sessions SET last_used_at = ? WHERE id = ?",
                (now, session["id"]),
            )
            session["last_used_at"] = now
        return session


def revoke_auth_session(
    token_hash: str | None = None,
    *,
    session_id: int | None = None,
    reason: str = "revoked",
    replaced_by: int | None = None,
) -> bool:
    """撤销单个会话。可按 token hash 或 session id 定位。"""
    if token_hash is None and session_id is None:
        raise ValueError("token_hash or session_id is required")

    now = _now_iso()
    where_sql = "id = ?" if session_id is not None else "token_hash = ?"
    where_value = session_id if session_id is not None else token_hash
    with db_conn() as conn:
        cur = conn.execute(
            f"""
            UPDATE auth_sessions
               SET revoked_at = COALESCE(revoked_at, ?),
                   revoked_reason = COALESCE(revoked_reason, ?),
                   replaced_by = COALESCE(replaced_by, ?)
             WHERE {where_sql}
               AND revoked_at IS NULL
            """,
            (now, reason, replaced_by, where_value),
        )
        return cur.rowcount > 0


def rotate_auth_session(
    old_token_hash: str,
    new_token_hash: str,
    expires_at: str,
    *,
    device_id: str | None = None,
    session_name: str | None = None,
) -> dict | None:
    """
    轮换 refresh token 会话。

    只有未撤销且未过期的旧 token 可以轮换；成功后旧 token 立即失效。
    """
    now = _now_iso()
    with db_conn() as conn:
        old_row = conn.execute(
            """
            SELECT * FROM auth_sessions
             WHERE token_hash = ?
               AND revoked_at IS NULL
               AND expires_at > ?
            """,
            (old_token_hash, now),
        ).fetchone()
        if not old_row:
            return None

        old_session = dict(old_row)
        cur = conn.execute(
            """
            INSERT INTO auth_sessions (
                user_id, token_hash, device_id, session_name,
                expires_at, created_at, last_used_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                old_session["user_id"],
                new_token_hash,
                device_id if device_id is not None else old_session.get("device_id"),
                session_name if session_name is not None else old_session.get("session_name"),
                expires_at,
                now,
                now,
            ),
        )
        new_session_id = cur.lastrowid
        conn.execute(
            """
            UPDATE auth_sessions
               SET revoked_at = ?,
                   revoked_reason = ?,
                   replaced_by = ?
             WHERE id = ?
               AND revoked_at IS NULL
            """,
            (now, "rotated", new_session_id, old_session["id"]),
        )
        row = conn.execute(
            "SELECT * FROM auth_sessions WHERE id = ?",
            (new_session_id,),
        ).fetchone()
        return dict(row)


def revoke_user_sessions(
    user_id: int,
    *,
    reason: str = "user_revoked",
    exclude_session_id: int | None = None,
) -> int:
    """撤销指定用户的所有有效会话。"""
    now = _now_iso()
    params: list = [now, reason, user_id]
    exclude_sql = ""
    if exclude_session_id is not None:
        exclude_sql = " AND id != ?"
        params.append(exclude_session_id)

    with db_conn() as conn:
        cur = conn.execute(
            f"""
            UPDATE auth_sessions
               SET revoked_at = ?,
                   revoked_reason = ?
             WHERE user_id = ?
               AND revoked_at IS NULL
               {exclude_sql}
            """,
            tuple(params),
        )
        return cur.rowcount


def cleanup_expired_auth_sessions(now: str | None = None) -> int:
    """删除已过期的桌面客户端会话记录。"""
    cutoff = now or _now_iso()
    with db_conn() as conn:
        cur = conn.execute(
            "DELETE FROM auth_sessions WHERE expires_at <= ?",
            (cutoff,),
        )
        return cur.rowcount


def cleanup_expired_edge_node_tokens(now: str | None = None) -> int:
    """清理已过期且未使用的边缘节点安装 Token"""
    cutoff = now or _now_iso()
    with db_conn() as conn:
        cur = conn.execute(
            "DELETE FROM edge_node_tokens WHERE expires_at <= ? AND (used = 0 OR used IS NULL)",
            (cutoff,),
        )
        return cur.rowcount


def cleanup_expired_tg_register_codes(now: str | None = None, days_for_used: int = 7) -> int:
    """清理过期或已核销超过指定天数的注册验证码"""
    cutoff = now or _now_iso()
    used_cutoff = (datetime.now(timezone.utc) - timedelta(days=days_for_used)).isoformat()
    with db_conn() as conn:
        cur = conn.execute(
            """
            DELETE FROM tg_register_codes
             WHERE (expires_at <= ? AND (used = 0 OR used IS NULL))
                OR (used = 1 AND created_at <= ?)
            """,
            (cutoff, used_cutoff),
        )
        return cur.rowcount





# ==================== 协议号资产池 CRUD ====================

def upsert_protocol_account(
    phone: str,
    session_data: str,
    session_type: str = "pyrogram_string",
    code_url: str | None = None,
    bot_count: int | None = None,
    status: str | None = None,
    remark: str | None = None,
    api_id: int | None = None,
    api_hash: str | None = None,
    two_fa_password: str | None = None,
    two_fa_hint: str | None = None,
    has_two_fa: int | None = None,
    local_otp_token: str | None = None,
) -> dict:
    """创建或更新协议号资产记录"""
    import secrets
    now = _now_iso()
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT * FROM tg_protocol_accounts WHERE phone = ?", (phone,)
        ).fetchone()

        if existing:
            account_id = existing["id"]
            new_bot_count = bot_count if bot_count is not None else existing["bot_count"]
            new_status = status if status is not None else existing["status"]
            new_remark = remark if remark is not None else existing["remark"]
            new_code_url = code_url if code_url is not None else existing["code_url"]
            new_api_id = api_id if api_id is not None else existing["api_id"]
            new_api_hash = api_hash if api_hash is not None else existing["api_hash"]
            new_two_fa_password = two_fa_password if two_fa_password is not None else existing["two_fa_password"]
            new_two_fa_hint = two_fa_hint if two_fa_hint is not None else existing["two_fa_hint"]
            new_has_two_fa = has_two_fa if has_two_fa is not None else existing["has_two_fa"]
            new_otp_token = local_otp_token if local_otp_token is not None else (existing["local_otp_token"] or secrets.token_hex(16))

            conn.execute(
                """
                UPDATE tg_protocol_accounts
                   SET session_data = ?,
                       session_type = ?,
                       code_url = ?,
                       bot_count = ?,
                       status = ?,
                       remark = ?,
                       api_id = ?,
                       api_hash = ?,
                       two_fa_password = ?,
                       two_fa_hint = ?,
                       has_two_fa = ?,
                       local_otp_token = ?,
                       last_used_at = ?
                 WHERE id = ?
                """,
                (
                    session_data, session_type, new_code_url, new_bot_count, new_status, new_remark,
                    new_api_id, new_api_hash, new_two_fa_password, new_two_fa_hint, new_has_two_fa, new_otp_token, now, account_id
                ),
            )
        else:
            final_otp_token = local_otp_token or secrets.token_hex(16)
            final_has_2fa = has_two_fa if has_two_fa is not None else (1 if two_fa_password else 0)
            cur = conn.execute(
                """
                INSERT INTO tg_protocol_accounts (
                    phone, session_type, session_data, code_url, bot_count, status, remark,
                    api_id, api_hash, two_fa_password, two_fa_hint, has_two_fa, local_otp_token, created_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    phone,
                    session_type,
                    session_data,
                    code_url,
                    bot_count if bot_count is not None else 0,
                    status or "active",
                    remark,
                    api_id,
                    api_hash,
                    two_fa_password,
                    two_fa_hint,
                    final_has_2fa,
                    final_otp_token,
                    now,
                    now,
                ),
            )
            account_id = cur.lastrowid

        row = conn.execute(
            "SELECT * FROM tg_protocol_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        return dict(row)


def list_protocol_accounts() -> list:
    """列出所有纳管的协议号资产"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM tg_protocol_accounts ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_protocol_account_by_id(account_id: int) -> dict | None:
    """根据 ID 查询协议号资产"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM tg_protocol_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        return dict(row) if row else None


def get_protocol_account_by_phone(phone: str) -> dict | None:
    """根据手机号查询协议号资产"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM tg_protocol_accounts WHERE phone = ?", (phone,)
        ).fetchone()
        return dict(row) if row else None


def update_protocol_account(account_id: int, **kwargs) -> bool:
    """更新指定协议号的属性"""
    allowed_keys = {
        "session_data", "session_type", "code_url", "bot_count", "status", "remark", "last_used_at",
        "dc_id", "tg_user_id", "username", "first_name", "last_keepalive_at", "keepalive_ping_ms", "last_error", "api_id", "api_hash",
        "two_fa_password", "two_fa_hint", "has_two_fa", "local_otp_token",
        "is_taken_over", "taken_over_at", "phone", "bot_usernames"
    }
    updates = []
    params = []
    for k, v in kwargs.items():
        if k in allowed_keys:
            updates.append(f"{k} = ?")
            params.append(v)
    if not updates:
        return False
    params.append(account_id)
    with db_conn() as conn:
        cur = conn.execute(
            f"UPDATE tg_protocol_accounts SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
        return cur.rowcount > 0


def get_protocol_account_by_otp_token(token: str) -> dict | None:
    """根据自主接码专属 Token 查询协议号资产"""
    if not token or not str(token).strip():
        return None
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM tg_protocol_accounts WHERE local_otp_token = ?", (str(token).strip(),)
        ).fetchone()
        return dict(row) if row else None


def get_protocol_account_tenant_aggregates() -> dict[int, dict]:
    """返回所有协议号创建的租户专属存储频道统计及关联租户用户名列表 {creator_account_id: {"channel_count": int, "tenant_usernames": list[str]}}"""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT creator_account_id, username, bin_channel_id
            FROM users
            WHERE creator_account_id IS NOT NULL AND bin_channel_id IS NOT NULL
            """
        ).fetchall()
        result: dict[int, dict] = {}
        for r in rows:
            cid = int(r["creator_account_id"])
            if cid not in result:
                result[cid] = {"channel_count": 0, "tenant_usernames": []}
            result[cid]["channel_count"] += 1
            uname = r["username"]
            if uname and uname not in result[cid]["tenant_usernames"]:
                result[cid]["tenant_usernames"].append(uname)
        return result


def delete_protocol_account(account_id: int) -> bool:
    """删除指定协议号资产，并将引用该协议号的租户创建者字段置空"""
    with db_conn() as conn:
        conn.execute("UPDATE users SET creator_account_id = NULL WHERE creator_account_id = ?", (int(account_id),))
        cur = conn.execute(
            "DELETE FROM tg_protocol_accounts WHERE id = ?", (int(account_id),)
        )
        return cur.rowcount > 0



# ----------------------------------------------------------------------
# 多租户边缘推流分流节点 (Edge Streaming Worker) 与加密管理
# ----------------------------------------------------------------------


def get_user_by_bin_channel_id(bin_channel_id: int | str) -> dict | None:
    """根据专属存储频道 ID 查询所属租户信息（支持主频道与历史 extra_channels）"""
    if not bin_channel_id:
        return None
    try:
        cid = int(bin_channel_id)
    except (ValueError, TypeError):
        return None
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, username, role, tg_user_id, tg_username, tg_first_name,
                   dc_id, bin_channel_id, bin_channel_username, creator_account_id,
                   extra_channels, created_at, updated_at
            FROM users WHERE bin_channel_id = ?
            """,
            (cid,),
        )
        row = cur.fetchone()
        if row:
            res = dict(row)
            res["extra_channels"] = parse_extra_channels(res.get("extra_channels"))
            return res

        # 回退：检查 extra_channels 包含该 cid 的租户
        cur.execute("SELECT id, username, role, tg_user_id, tg_username, tg_first_name, dc_id, bin_channel_id, bin_channel_username, creator_account_id, extra_channels, created_at, updated_at FROM users WHERE extra_channels IS NOT NULL AND extra_channels != '[]'")
        for u_row in cur.fetchall():
            extras = parse_extra_channels(u_row["extra_channels"])
            if cid in extras:
                res = dict(u_row)
                res["extra_channels"] = extras
                return res
        return None


def _get_edge_encryption_key() -> bytes:
    secret_env = os.environ.get("MISTRELAY_JWT_SECRET") or os.environ.get("MISTRELAY_SECRET_KEY")
    if secret_env:
        return hashlib.sha256(secret_env.encode("utf-8")).digest()
    db_dir = os.path.dirname(DB_PATH)
    key_file = os.path.join(db_dir, "jwt_signing.key")
    try:
        if os.path.exists(key_file):
            with open(key_file, "r", encoding="utf-8") as f:
                s = f.read().strip()
                if s:
                    return hashlib.sha256(s.encode("utf-8")).digest()
    except Exception:
        pass
    return hashlib.sha256(b"mistrelay_default_edge_secret_v1").digest()


def encrypt_ssh_password(password: str) -> str:
    """对 SSH 密码进行防篡改对称加密 (HMAC-SHA256 CTR 流密码 + MAC 认证标签)"""
    if not password:
        return ""
    key = _get_edge_encryption_key()
    nonce = secrets.token_bytes(16)
    data = password.encode("utf-8")
    keystream = bytearray()
    counter = 0
    while len(keystream) < len(data):
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        keystream.extend(block)
        counter += 1
    ciphertext = bytes(b ^ k for b, k in zip(data, keystream[:len(data)]))
    mac = hmac.new(key, b"mac:" + nonce + ciphertext, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(nonce + mac + ciphertext).decode("ascii")


def decrypt_ssh_password(encrypted_str: str) -> str:
    """解密已加密的 SSH 密码"""
    if not encrypted_str:
        return ""
    try:
        raw_bytes = base64.urlsafe_b64decode(encrypted_str.encode("ascii"))
        if len(raw_bytes) < 32:
            return ""
        key = _get_edge_encryption_key()
        nonce = raw_bytes[:16]
        mac = raw_bytes[16:32]
        ciphertext = raw_bytes[32:]
        expected_mac = hmac.new(key, b"mac:" + nonce + ciphertext, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(mac, expected_mac):
            logger.warning("SSH 密码解密失败：MAC 校验不匹配")
            return ""
        keystream = bytearray()
        counter = 0
        while len(keystream) < len(ciphertext):
            block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
            keystream.extend(block)
            counter += 1
        plaintext = bytes(b ^ k for b, k in zip(ciphertext, keystream[:len(ciphertext)]))
        return plaintext.decode("utf-8")
    except Exception as e:
        logger.warning(f"SSH 密码解密异常: {e}")
        return ""


def _format_edge_node_row(row: sqlite3.Row | dict, include_secrets: bool = False) -> dict:
    d = dict(row)
    raw_metrics = d.get("metrics")
    default_metrics = {
        "cpu": 0.0,
        "mem": 0.0,
        "active_streams": 0,
        "net_rx": 0,
        "net_tx": 0,
        "total_bytes_served": 0,
    }
    if isinstance(raw_metrics, str) and raw_metrics.strip():
        try:
            parsed = json.loads(raw_metrics)
            if isinstance(parsed, dict):
                default_metrics.update(parsed)
        except Exception:
            pass
    elif isinstance(raw_metrics, dict):
        default_metrics.update(raw_metrics)
    d["metrics"] = default_metrics

    raw_bench = d.get("benchmark_data")
    default_bench = {}
    if isinstance(raw_bench, str) and raw_bench.strip():
        try:
            parsed_bench = json.loads(raw_bench)
            if isinstance(parsed_bench, dict):
                default_bench.update(parsed_bench)
        except Exception:
            pass
    elif isinstance(raw_bench, dict):
        default_bench.update(raw_bench)
    d["benchmark_data"] = default_bench

    d["use_ssl"] = bool(d.get("use_ssl"))
    d["allow_shared_pool"] = bool(d.get("allow_shared_pool"))
    d["allow_bot_pool"] = bool(d.get("allow_bot_pool", 1))
    d["target_bot_count"] = d.get("target_bot_count")
    d["target_dc_id"] = d.get("target_dc_id")
    d["assigned_bot_token"] = d.get("assigned_bot_token") or ""
    d["assigned_bot_username"] = d.get("assigned_bot_username") or ""
    d["has_ssh_password"] = bool(d.get("ssh_password_enc"))
    if include_secrets:
        if d.get("ssh_password_enc"):
            d["ssh_password"] = decrypt_ssh_password(d["ssh_password_enc"])
        else:
            d["ssh_password"] = ""
    else:
        d.pop("ssh_password_enc", None)
        secret_val = d.get("auth_secret") or ""
        d["auth_secret_masked"] = (secret_val[:6] + "****" + secret_val[-4:]) if len(secret_val) > 10 else "****"
        d.pop("auth_secret", None)
    return d


def create_edge_node(
    tenant_id: int,
    node_name: str,
    ip: str = "",
    port: int = 8090,
    ssh_host: str = "",
    ssh_port: int = 22,
    ssh_user: str = "root",
    ssh_password: str = "",
    domain: str = "",
    use_ssl: bool = False,
    allow_shared_pool: bool = False,
    status: str = "offline",
    auth_secret: str | None = None,
    include_secrets: bool = False,
    target_dc_id: int | None = None,
    assigned_bot_token: str = "",
    assigned_bot_username: str = "",
    allow_bot_pool: bool = True,
) -> dict:
    now = _now_iso()
    secret_val = auth_secret or secrets.token_hex(24)
    enc_pwd = encrypt_ssh_password(ssh_password) if ssh_password else ""
    actual_ip = (ip or ssh_host or "").strip()
    actual_ssh_host = (ssh_host or ip or "").strip()
    actual_domain = str(domain or "").strip()
    actual_use_ssl = bool(use_ssl)
    if not actual_domain and actual_ip:
        actual_domain = get_default_edge_domain(actual_ip)
        if actual_domain:
            actual_use_ssl = True
    elif actual_domain and not actual_use_ssl:
        actual_use_ssl = True

    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO edge_nodes (
                tenant_id, node_name, ip, port, ssh_host, ssh_port, ssh_user,
                ssh_password_enc, domain, use_ssl, auth_secret, status,
                deploy_log, allow_shared_pool, metrics, last_seen_at,
                target_dc_id, assigned_bot_token, assigned_bot_username, allow_bot_pool,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(tenant_id),
                str(node_name or "Edge Node").strip(),
                actual_ip,
                int(port or 8090),
                actual_ssh_host,
                int(ssh_port or 22),
                str(ssh_user or "root").strip(),
                enc_pwd,
                actual_domain,
                1 if actual_use_ssl else 0,
                secret_val,
                str(status or "offline"),
                "",
                1 if allow_shared_pool else 0,
                json.dumps({"cpu": 0.0, "mem": 0.0, "active_streams": 0, "net_rx": 0, "net_tx": 0, "total_bytes_served": 0}),
                now if status == "online" else None,
                int(target_dc_id) if target_dc_id is not None else None,
                str(assigned_bot_token or "").strip(),
                str(assigned_bot_username or "").strip(),
                1 if allow_bot_pool else 0,
                now,
                now,
            ),
        )
        node_id = cur.lastrowid
    return get_edge_node_by_id(node_id, include_secrets=include_secrets)


def get_edge_node_by_id(node_id: int, include_secrets: bool = False) -> dict | None:
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT e.*, u.username AS tenant_username
            FROM edge_nodes AS e
            LEFT JOIN users AS u ON e.tenant_id = u.id
            WHERE e.id = ?
            """,
            (int(node_id),),
        ).fetchone()
        return _format_edge_node_row(row, include_secrets=include_secrets) if row else None


def get_edge_node_by_secret(auth_secret: str, include_secrets: bool = False) -> dict | None:
    if not auth_secret or not str(auth_secret).strip():
        return None
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT e.*, u.username AS tenant_username
            FROM edge_nodes AS e
            LEFT JOIN users AS u ON e.tenant_id = u.id
            WHERE e.auth_secret = ?
            """,
            (str(auth_secret).strip(),),
        ).fetchone()
        return _format_edge_node_row(row, include_secrets=include_secrets) if row else None


def list_edge_nodes(tenant_id: int | None = None, include_secrets: bool = False) -> list[dict]:
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        if tenant_id is not None:
            rows = conn.execute(
                """
                SELECT e.*, u.username AS tenant_username
                FROM edge_nodes AS e
                LEFT JOIN users AS u ON e.tenant_id = u.id
                WHERE e.tenant_id = ?
                ORDER BY e.id DESC
                """,
                (int(tenant_id),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT e.*, u.username AS tenant_username
                FROM edge_nodes AS e
                LEFT JOIN users AS u ON e.tenant_id = u.id
                ORDER BY e.id DESC
                """
            ).fetchall()
        return [_format_edge_node_row(r, include_secrets=include_secrets) for r in rows]


def update_edge_node(node_id: int, include_secrets: bool = False, **kwargs) -> dict | None:
    allowed_fields = {
        "node_name", "ip", "port", "ssh_host", "ssh_port", "ssh_user",
        "ssh_password_enc", "domain", "use_ssl", "auth_secret", "status",
        "deploy_log", "allow_shared_pool", "metrics", "benchmark_data", "last_seen_at",
        "target_dc_id", "assigned_bot_token", "assigned_bot_username", "allow_bot_pool", "target_bot_count",
    }
    if "ssh_password" in kwargs:
        pwd = kwargs.pop("ssh_password")
        if pwd is not None:
            kwargs["ssh_password_enc"] = encrypt_ssh_password(str(pwd)) if pwd else ""

    updates = []
    params = []
    for k, v in kwargs.items():
        if k not in allowed_fields:
            continue
        if k in ("use_ssl", "allow_shared_pool", "allow_bot_pool"):
            v = 1 if v else 0
        elif k in ("target_dc_id", "target_bot_count") and v not in (None, ""):
            v = int(v)
        elif k in ("metrics", "benchmark_data") and isinstance(v, dict):
            v = json.dumps(v, ensure_ascii=False)
        updates.append(f"{k} = ?")
        params.append(v)

    if not updates:
        return get_edge_node_by_id(node_id, include_secrets=include_secrets)

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(int(node_id))

    with db_conn() as conn:
        conn.execute(
            f"UPDATE edge_nodes SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
    return get_edge_node_by_id(node_id, include_secrets=include_secrets)


def append_edge_node_deploy_log(node_id: int, line: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    formatted = f"[{ts}] {line.rstrip()}\n"
    now = _now_iso()
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE edge_nodes
               SET deploy_log = COALESCE(deploy_log, '') || ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (formatted, now, int(node_id)),
        )


def clear_edge_node_ssh_password(node_id: int) -> bool:
    with db_conn() as conn:
        cur = conn.execute(
            "UPDATE edge_nodes SET ssh_password_enc = '', updated_at = ? WHERE id = ?",
            (_now_iso(), int(node_id)),
        )
        return cur.rowcount > 0


def delete_edge_node(node_id: int) -> bool:
    with db_conn() as conn:
        conn.execute("DELETE FROM edge_node_tokens WHERE node_id = ?", (int(node_id),))
        cur = conn.execute("DELETE FROM edge_nodes WHERE id = ?", (int(node_id),))
        return cur.rowcount > 0


def _is_edge_node_fresh(node: dict, max_stale_seconds: int = 120) -> bool:
    if node.get("status") != "online":
        return False
    if not (node.get("ip") or node.get("domain")):
        return False
    if max_stale_seconds <= 0:
        return True
    last_seen = node.get("last_seen_at")
    if not last_seen:
        return True
    try:
        dt = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age <= max_stale_seconds
    except Exception:
        return True


def get_healthy_edge_node_for_tenant(
    tenant_id: int | None = None,
    max_stale_seconds: int = 120,
    include_secrets: bool = True,
) -> dict | None:
    """
    智能边缘节点优选策略：
    1. 若指定了 tenant_id，优先从该租户名下状态为 online 的专属节点中选择负载最低的节点；
    2. 若该租户无可用专属节点，则从开启了 allow_shared_pool = 1 的公共共享池中选择负载最低的健康节点；
    3. 若均无可用节点，返回 None（由 Master 回源兜底直出）。
    """
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        if tenant_id is not None:
            rows = conn.execute(
                """
                SELECT e.*, u.username AS tenant_username
                FROM edge_nodes AS e
                LEFT JOIN users AS u ON e.tenant_id = u.id
                WHERE e.tenant_id = ? AND e.status = 'online'
                ORDER BY e.id ASC
                """,
                (int(tenant_id),),
            ).fetchall()
            candidates = [
                _format_edge_node_row(r, include_secrets=include_secrets)
                for r in rows
            ]
            healthy_dedicated = [
                c for c in candidates if _is_edge_node_fresh(c, max_stale_seconds)
            ]
            if healthy_dedicated:
                healthy_dedicated.sort(
                    key=lambda x: (
                        int((x.get("metrics") or {}).get("active_streams", 0)),
                        int(x.get("id", 0)),
                    )
                )
                return healthy_dedicated[0]

        # 回退查找开启了公共池共享的在线节点
        shared_rows = conn.execute(
            """
            SELECT e.*, u.username AS tenant_username
            FROM edge_nodes AS e
            LEFT JOIN users AS u ON e.tenant_id = u.id
            WHERE e.allow_shared_pool = 1 AND e.status = 'online'
            ORDER BY e.id ASC
            """
        ).fetchall()
        shared_candidates = [
            _format_edge_node_row(r, include_secrets=include_secrets)
            for r in shared_rows
        ]
        healthy_shared = [
            c for c in shared_candidates if _is_edge_node_fresh(c, max_stale_seconds)
        ]
        if healthy_shared:
            healthy_shared.sort(
                key=lambda x: (
                    int((x.get("metrics") or {}).get("active_streams", 0)),
                    int(x.get("id", 0)),
                )
            )
            return healthy_shared[0]
    return None


def get_candidate_edge_nodes_for_tenant(
    tenant_id: int | None = None,
    max_stale_seconds: int = 120,
    include_secrets: bool = True,
) -> list[dict]:
    """
    获取满足多租户隔离约束的候选边缘节点列表（专属池优先，共享池兜底）：
    1. 若 tenant_id 非空且存在健康的专属在线节点，返回专属在线节点列表；
    2. 若租户无健康专属节点（或 tenant_id 为 None），返回公共共享池中健康的在线节点列表。
    """
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        if tenant_id is not None:
            rows = conn.execute(
                """
                SELECT e.*, u.username AS tenant_username
                FROM edge_nodes AS e
                LEFT JOIN users AS u ON e.tenant_id = u.id
                WHERE e.tenant_id = ? AND e.status = 'online'
                ORDER BY e.id ASC
                """,
                (int(tenant_id),),
            ).fetchall()
            candidates = [
                _format_edge_node_row(r, include_secrets=include_secrets)
                for r in rows
            ]
            healthy_dedicated = [
                c for c in candidates if _is_edge_node_fresh(c, max_stale_seconds)
            ]
            if healthy_dedicated:
                return healthy_dedicated

        # 回退查找开启了公共池共享的在线节点
        shared_rows = conn.execute(
            """
            SELECT e.*, u.username AS tenant_username
            FROM edge_nodes AS e
            LEFT JOIN users AS u ON e.tenant_id = u.id
            WHERE e.allow_shared_pool = 1 AND e.status = 'online'
            ORDER BY e.id ASC
            """
        ).fetchall()
        shared_candidates = [
            _format_edge_node_row(r, include_secrets=include_secrets)
            for r in shared_rows
        ]
        return [
            c for c in shared_candidates if _is_edge_node_fresh(c, max_stale_seconds)
        ]


def get_available_edge_nodes_for_user(
    tenant_id: int | None = None,
    is_admin: bool = False,
    include_secrets: bool = False,
) -> list[dict]:
    """
    获取用户在前端网盘可见/可选的全部可用边缘节点：
    - 管理员：返回全部在线节点；
    - 租户：返回该租户的专属在线节点 + 全部开启了公共共享池的在线节点（去重）。
    """
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        if is_admin:
            rows = conn.execute(
                """
                SELECT e.*, u.username AS tenant_username
                FROM edge_nodes AS e
                LEFT JOIN users AS u ON e.tenant_id = u.id
                WHERE e.status = 'online'
                ORDER BY e.id ASC
                """
            ).fetchall()
        else:
            tid = int(tenant_id or 0)
            rows = conn.execute(
                """
                SELECT e.*, u.username AS tenant_username
                FROM edge_nodes AS e
                LEFT JOIN users AS u ON e.tenant_id = u.id
                WHERE (e.tenant_id = ? OR e.allow_shared_pool = 1) AND e.status = 'online'
                ORDER BY e.id ASC
                """,
                (tid,),
            ).fetchall()

        seen_ids = set()
        result = []
        for r in rows:
            formatted = _format_edge_node_row(r, include_secrets=include_secrets)
            if formatted["id"] not in seen_ids:
                seen_ids.add(formatted["id"])
                result.append(formatted)
        return result


def create_edge_node_token(
    tenant_id: int,
    node_name: str,
    domain: str = "",
    port: int = 8090,
    use_ssl: bool = False,
    allow_shared_pool: bool = False,
    expires_minutes: int = 60,
) -> dict:
    token = secrets.token_urlsafe(24)
    now_dt = datetime.now(timezone.utc)
    exp_dt = now_dt + timedelta(minutes=max(5, int(expires_minutes)))
    now_str = now_dt.isoformat()
    exp_str = exp_dt.isoformat()
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO edge_node_tokens (
                token, tenant_id, node_name, domain, port,
                use_ssl, allow_shared_pool, node_id, expires_at, used, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 0, ?)
            """,
            (
                token,
                int(tenant_id),
                str(node_name or "Edge Worker").strip(),
                str(domain or "").strip(),
                int(port or 8090),
                1 if use_ssl else 0,
                1 if allow_shared_pool else 0,
                exp_str,
                now_str,
            ),
        )
    return {
        "token": token,
        "tenant_id": int(tenant_id),
        "node_name": str(node_name or "Edge Worker").strip(),
        "domain": str(domain or "").strip(),
        "port": int(port or 8090),
        "use_ssl": bool(use_ssl),
        "allow_shared_pool": bool(allow_shared_pool),
        "expires_at": exp_str,
        "used": False,
        "created_at": now_str,
    }


def get_edge_node_token(token: str) -> dict | None:
    if not token or not str(token).strip():
        return None
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM edge_node_tokens WHERE token = ?",
            (str(token).strip(),),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["use_ssl"] = bool(d.get("use_ssl"))
        d["allow_shared_pool"] = bool(d.get("allow_shared_pool"))
        d["used"] = bool(d.get("used"))
        try:
            exp_dt = datetime.fromisoformat(str(d["expires_at"]).replace("Z", "+00:00"))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            d["expired"] = datetime.now(timezone.utc) > exp_dt
        except Exception:
            d["expired"] = False
        return d


def verify_and_consume_edge_node_token(
    token: str,
    ip: str = "",
    port: int | None = None,
) -> dict | None:
    """验证并核销一键安装脚本 Token，创建或激活对应的 Edge 节点"""
    tok_info = get_edge_node_token(token)
    if not tok_info:
        return None
    if tok_info.get("expired"):
        return None
    if tok_info.get("used") and tok_info.get("node_id"):
        return None

    actual_port = int(port) if port else int(tok_info.get("port") or 8090)
    actual_ip = str(ip or "").strip()
    tok_domain = str(tok_info.get("domain") or "").strip()
    if not tok_domain and actual_ip:
        tok_domain = get_default_edge_domain(actual_ip)
    tok_ssl = True if tok_domain else bool(tok_info.get("use_ssl"))

    node = create_edge_node(
        tenant_id=int(tok_info["tenant_id"]),
        node_name=tok_info["node_name"],
        ip=actual_ip,
        port=actual_port,
        domain=tok_domain,
        use_ssl=tok_ssl,
        allow_shared_pool=bool(tok_info.get("allow_shared_pool")),
        status="online",
        include_secrets=True,
    )
    with db_conn() as conn:
        conn.execute(
            "UPDATE edge_node_tokens SET used = 1, node_id = ? WHERE token = ?",
            (int(node["id"]), str(token).strip()),
        )
    return node

def update_edge_node_benchmark(node_id: int, benchmark_data: dict) -> dict | None:
    """更新边缘节点的测速与体检数据"""
    return update_edge_node(node_id, benchmark_data=benchmark_data)


def heal_orphaned_tenant_media(channel_user_map: dict | None = None) -> dict:
    """
    扫描并自愈孤儿媒体数据。
    自动检测 tg_media 中存在媒体但未被任何用户当前 bin_channel_id 引用的 channel_id，
    根据历史基线归档记录及已知映射，将其追加至所属租户的 extra_channels 中。
    """
    default_mappings = {
        -1004327294673: "xiaopeng",
        -1003729299086: "linxiao",
        -1004056710317: "yangyangya",
        -1004339423265: "zxc",
    }
    if channel_user_map:
        default_mappings.update(channel_user_map)

    # 尝试从只读基线归档中补充历史用户与频道映射
    try:
        import tarfile, tempfile
        baseline_path = "/root/MistRelay-dev/db/backups/.immutable_baseline/backup_mistrelay_20260928_125911.tar.gz"
        if os.path.exists(baseline_path):
            with tarfile.open(baseline_path, "r:gz") as tar:
                if "downloads.db" in tar.getnames():
                    f = tar.extractfile("downloads.db")
                    if f:
                        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
                            tmp.write(f.read())
                            tmp.flush()
                            b_conn = sqlite3.connect(tmp.name)
                            for row in b_conn.execute("SELECT username, bin_channel_id FROM users WHERE bin_channel_id IS NOT NULL"):
                                if row[1] and int(row[1]) not in default_mappings:
                                    default_mappings[int(row[1])] = str(row[0])
                            b_conn.close()
    except Exception as e:
        logger.warning(f"从只读基线提取历史映射异常 (已忽略): {e}")

    global_bin = None
    try:
        with db_conn() as conn:
            cfg_row = conn.execute("SELECT value FROM config_settings WHERE key = 'BIN_CHANNEL'").fetchone()
            if cfg_row and cfg_row[0]:
                global_bin = int(cfg_row[0])
    except Exception:
        pass

    healed_list = []
    total_files_restored = 0

    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        all_users = conn.execute("SELECT id, username, bin_channel_id, extra_channels FROM users").fetchall()
        user_by_name = {u["username"]: dict(u) for u in all_users}
        user_by_id = {u["id"]: dict(u) for u in all_users}

        active_channels = set()
        for u in all_users:
            if u["bin_channel_id"]:
                active_channels.add(int(u["bin_channel_id"]))
            for ec in parse_extra_channels(u["extra_channels"]):
                active_channels.add(int(ec))
        if global_bin:
            active_channels.add(int(global_bin))

        orphan_rows = conn.execute(
            "SELECT chat_id, COUNT(*) as cnt, COALESCE(SUM(file_size), 0) as total_size FROM tg_media WHERE chat_id IS NOT NULL GROUP BY chat_id"
        ).fetchall()

        for orow in orphan_rows:
            cid = int(orow["chat_id"])
            if cid in active_channels:
                continue

            target_user = None
            if cid in default_mappings:
                identifier = default_mappings[cid]
                if isinstance(identifier, int) and identifier in user_by_id:
                    target_user = user_by_id[identifier]
                elif str(identifier) in user_by_name:
                    target_user = user_by_name[str(identifier)]

            if target_user:
                append_user_extra_channel(target_user["id"], cid)
                healed_list.append({
                    "user_id": target_user["id"],
                    "username": target_user["username"],
                    "channel_id": cid,
                    "files_count": int(orow["cnt"]),
                    "total_size": int(orow["total_size"]),
                })
                total_files_restored += int(orow["cnt"])
                logger.info(f"成功自愈孤儿媒体：为租户 {target_user['username']} 恢复历史频道 {cid} (共 {orow['cnt']} 个文件)")

    return {
        "success": True,
        "healed": healed_list,
        "total_files_restored": total_files_restored,
    }
