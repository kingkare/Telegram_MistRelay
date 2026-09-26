"""
Telegram 协议号与会话适配器 (Session Adapter)
==============================================
支持将多种主流 Telegram 协议号格式（Pyrogram Session String、Telethon StringSession、
Pyrogram SQLite .session 文件、Telethon SQLite .session 文件）无缝解析并转换为
Pyrogram 兼容的纯内存会话，确保全生态协议号兼容。
"""

import os
import re
import struct
import base64
import sqlite3
import tempfile
import logging
from typing import Tuple, Optional

logger = logging.getLogger("session_adapter")

# Pyrogram 2.x Session String 结构：
# dc_id: uint8 (1 byte)
# api_id: uint32 (4 bytes)
# test_mode: bool (1 byte)
# auth_key: 256 bytes
# user_id: uint64 (8 bytes)
# is_bot: bool (1 byte)
PYROGRAM_SESSION_FORMAT = ">BI?256sQ?"
PYROGRAM_SESSION_SIZE = struct.calcsize(PYROGRAM_SESSION_FORMAT)  # 271 字节

# Pyrogram 旧版 6 字段格式 (无 api_id)
PYROGRAM_OLD_SESSION_FORMAT = ">B?256sQ?"
PYROGRAM_OLD_SESSION_SIZE = struct.calcsize(PYROGRAM_OLD_SESSION_FORMAT)  # 267 字节


def pack_pyrogram_session(
    dc_id: int,
    auth_key: bytes,
    api_id: int = 0,
    test_mode: bool = False,
    user_id: int = 0,
    is_bot: bool = False,
) -> str:
    """将会话参数打包为 Pyrogram 标准 Session String"""
    if len(auth_key) != 256:
        raise ValueError(f"auth_key 长度必须为 256 字节，当前为 {len(auth_key)} 字节")
    packed = struct.pack(
        PYROGRAM_SESSION_FORMAT,
        int(dc_id),
        int(api_id or 0),
        bool(test_mode),
        auth_key,
        int(user_id or 1),
        bool(is_bot),
    )
    return base64.urlsafe_b64encode(packed).decode("utf-8").rstrip("=")


def extract_dc_and_auth_key_from_telethon_string(telethon_str: str) -> Tuple[int, bytes]:
    """从 Telethon StringSession (1 开头) 中提取 dc_id 与 auth_key"""
    stripped = telethon_str.strip()
    if not stripped.startswith("1"):
        raise ValueError("Telethon StringSession 必须以 '1' 开头")

    raw = stripped[1:]
    padding = "=" * (-len(raw) % 4)
    data = base64.urlsafe_b64decode(raw + padding)

    if len(data) < 257:
        raise ValueError(f"Telethon StringSession 长度异常: {len(data)} 字节")

    dc_id = data[0]
    auth_key = data[-256:]
    return dc_id, auth_key


def extract_from_pyrogram_string(pyro_str: str) -> Tuple[int, bytes, int, bool, int, bool]:
    """从 Pyrogram Session String 中提取各字段"""
    stripped = pyro_str.strip()
    padding = "=" * (-len(stripped) % 4)
    data = base64.urlsafe_b64decode(stripped + padding)

    if len(data) == PYROGRAM_SESSION_SIZE:
        dc_id, api_id, test_mode, auth_key, user_id, is_bot = struct.unpack(
            PYROGRAM_SESSION_FORMAT, data
        )
        return dc_id, auth_key, api_id, test_mode, user_id, is_bot
    elif len(data) == PYROGRAM_OLD_SESSION_SIZE:
        dc_id, test_mode, auth_key, user_id, is_bot = struct.unpack(
            PYROGRAM_OLD_SESSION_FORMAT, data
        )
        return dc_id, auth_key, 0, test_mode, user_id, is_bot
    else:
        raise ValueError(f"未知或不受支持的 Pyrogram Session String 长度: {len(data)} 字节")


def extract_from_sqlite_session(session_bytes_or_path) -> Tuple[int, bytes, int, int]:
    """
    从 SQLite .session 文件中提取 (dc_id, auth_key, api_id, user_id)
    兼容 Pyrogram 与 Telethon 两种库生成的 SQLite .session 结构
    """
    temp_file = None
    if isinstance(session_bytes_or_path, (bytes, bytearray)):
        fd, temp_path = tempfile.mkstemp(suffix=".session")
        with os.fdopen(fd, "wb") as f:
            f.write(session_bytes_or_path)
        db_path = temp_path
        temp_file = temp_path
    elif isinstance(session_bytes_or_path, str) and os.path.isfile(session_bytes_or_path):
        db_path = session_bytes_or_path
    else:
        raise ValueError("提供的 SQLite 会话数据既不是有效文件路径也不是二进制字节流")

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 检查 sessions 表结构
        cur.execute("PRAGMA table_info(sessions)")
        columns = [row["name"] for row in cur.fetchall()]
        if not columns:
            raise ValueError(".session 数据库中缺少 sessions 表")

        cur.execute("SELECT * FROM sessions LIMIT 1")
        row = cur.fetchone()
        if not row:
            raise ValueError("sessions 表为空，无有效授权记录")

        dc_id = int(row["dc_id"])
        auth_key = row["auth_key"]
        if not isinstance(auth_key, bytes) or len(auth_key) != 256:
            raise ValueError(f"auth_key 无效或长度不为 256 字节 (len={len(auth_key) if isinstance(auth_key, bytes) else 'N/A'})")

        api_id = int(row["api_id"]) if "api_id" in columns and row["api_id"] is not None else 0
        user_id = int(row["user_id"]) if "user_id" in columns and row["user_id"] is not None else 0

        conn.close()
        return dc_id, auth_key, api_id, user_id
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except Exception:
                pass


def parse_session_to_pyrogram_string(
    source: str | bytes | bytearray,
    default_api_id: int = 0,
) -> str:
    """
    将任何形式的 Telegram 会话（字符串或文件二进制）统一转换为 Pyrogram Session String。
    """
    if isinstance(source, (bytes, bytearray)):
        # 检查是否为 SQLite 数据库文件魔数
        if source.startswith(b"SQLite format 3\x00"):
            dc_id, auth_key, api_id, user_id = extract_from_sqlite_session(source)
            return pack_pyrogram_session(
                dc_id=dc_id,
                auth_key=auth_key,
                api_id=api_id or default_api_id,
                user_id=user_id,
            )
        else:
            # 尝试作为文本解码
            try:
                source = source.decode("utf-8").strip()
            except Exception:
                raise ValueError("提供的文件内容既不是 SQLite .session 文件，也不是可解析的文本字符串")

    if not isinstance(source, str):
        raise ValueError(f"不支持的输入类型: {type(source)}")

    source = source.strip()

    # 1. 检查是否为 Telethon StringSession (以 1 开头且长度通常 > 300)
    if source.startswith("1") and len(source) > 280:
        try:
            dc_id, auth_key = extract_dc_and_auth_key_from_telethon_string(source)
            return pack_pyrogram_session(
                dc_id=dc_id,
                auth_key=auth_key,
                api_id=default_api_id,
            )
        except Exception as e:
            logger.debug(f"尝试按 Telethon StringSession 解析失败: {e}")

    # 2. 检查是否为 Pyrogram Session String
    try:
        dc_id, auth_key, api_id, test_mode, user_id, is_bot = extract_from_pyrogram_string(source)
        # 如果原 session 中缺少 api_id，补充 default_api_id 后重新 pack
        return pack_pyrogram_session(
            dc_id=dc_id,
            auth_key=auth_key,
            api_id=api_id or default_api_id,
            test_mode=test_mode,
            user_id=user_id,
            is_bot=is_bot,
        )
    except Exception as e:
        logger.debug(f"尝试按 Pyrogram Session String 解析失败: {e}")

    raise ValueError("未能识别或解析该 Telegram 会话，请确保提供的是有效的 Pyrogram / Telethon Session 文本或 .session 文件")
