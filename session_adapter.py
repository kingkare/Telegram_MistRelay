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


# Telethon DC IPv4 地址映射
TELETHON_DC_IPV4 = {
    1: "149.154.175.53",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.91",
    5: "91.108.56.165",
}


def pack_telethon_session(
    dc_id: int,
    auth_key: bytes,
    port: int = 443,
) -> str:
    """将会话参数打包为 Telethon 1.x 标准 StringSession (以 "1" 开头)"""
    if len(auth_key) != 256:
        raise ValueError(f"auth_key 长度必须为 256 字节，当前为 {len(auth_key)} 字节")
    import ipaddress
    ip_str = TELETHON_DC_IPV4.get(int(dc_id), "149.154.175.53")
    ip_bytes = ipaddress.IPv4Address(ip_str).packed
    raw = struct.pack(">B4sH256s", int(dc_id), ip_bytes, int(port), auth_key)
    return "1" + base64.urlsafe_b64encode(raw).decode("ascii")


def parse_session_to_telethon_string(
    source: str | bytes | bytearray,
) -> str:
    """
    将任何形式的 Telegram 会话（Pyrogram Session String、Telethon StringSession 或 SQLite .session 文件）
    统一转换为 Telethon 兼容的标准 StringSession。
    """
    if isinstance(source, (bytes, bytearray)):
        if source.startswith(b"SQLite format 3\x00"):
            dc_id, auth_key, _, _ = extract_from_sqlite_session(source)
            return pack_telethon_session(dc_id=dc_id, auth_key=auth_key)
        else:
            try:
                source = source.decode("utf-8").strip()
            except Exception:
                raise ValueError("提供的文件内容既不是 SQLite .session 文件，也不是可解析的文本字符串")

    if not isinstance(source, str):
        raise ValueError(f"不支持的输入类型: {type(source)}")

    source = source.strip()

    # 1. 检查是否为 Telethon StringSession (以 1 开头且长度通常 > 280)
    if source.startswith("1") and len(source) > 280:
        try:
            dc_id, auth_key = extract_dc_and_auth_key_from_telethon_string(source)
            return pack_telethon_session(dc_id=dc_id, auth_key=auth_key)
        except Exception as e:
            logger.debug(f"校验 Telethon StringSession 失败: {e}")

    # 2. 检查是否为 Pyrogram Session String
    try:
        dc_id, auth_key, api_id, test_mode, user_id, is_bot = extract_from_pyrogram_string(source)
        return pack_telethon_session(dc_id=dc_id, auth_key=auth_key)
    except Exception as e:
        logger.debug(f"尝试按 Pyrogram Session String 解析并转换为 Telethon 失败: {e}")

    raise ValueError("未能识别或解析该 Telegram 会话，请确保提供的是有效的 Pyrogram / Telethon Session 文本或 .session 文件")


TELETHON_DC_INFO = {
    1: {"name": "DC1 美西 (Miami/Plano)", "region": "美西", "ip": "149.154.175.53", "port": 443},
    2: {"name": "DC2 欧洲 (Amsterdam)", "region": "欧洲", "ip": "149.154.167.51", "port": 443},
    3: {"name": "DC3 美东 (Miami)", "region": "美东", "ip": "149.154.175.100", "port": 443},
    4: {"name": "DC4 欧洲 (Amsterdam/Netherlands)", "region": "欧洲", "ip": "149.154.167.91", "port": 443},
    5: {"name": "DC5 亚太 (Singapore)", "region": "亚太/新加坡", "ip": "91.108.56.165", "port": 443},
}


def inspect_session_metadata(
    source: str | bytes | bytearray,
    default_api_id: int = 0,
) -> dict:
    """
    深度无阻塞解析 Telegram 协议号会话底层参数并生成双端 Session String：
    兼容 Pyrogram Session String、Telethon StringSession 与 SQLite .session 数据库。
    返回包含 dc_id, dc_name, dc_ip, dc_port, user_id, api_id, test_mode, is_bot,
    auth_key_len, auth_key_fingerprint, telethon_session_string, pyrogram_session_string 等元数据。
    """
    import hashlib

    if isinstance(source, (bytes, bytearray)):
        if source.startswith(b"SQLite format 3\x00"):
            dc_id, auth_key, api_id, user_id = extract_from_sqlite_session(source)
            test_mode = False
            is_bot = False
        else:
            try:
                source = source.decode("utf-8").strip()
            except Exception:
                raise ValueError("提供的文件内容既不是 SQLite .session 文件，也不是可解析的文本字符串")

    if not isinstance(source, str):
        raise ValueError(f"不支持的输入类型: {type(source)}")

    source = source.strip()
    dc_id = 1
    auth_key = b""
    api_id = default_api_id
    test_mode = False
    user_id = 0
    is_bot = False

    parsed = False
    # 1. 尝试按 Telethon StringSession (以 1 开头)
    if source.startswith("1") and len(source) > 280:
        try:
            dc_id, auth_key = extract_dc_and_auth_key_from_telethon_string(source)
            parsed = True
        except Exception:
            pass

    # 2. 尝试按 Pyrogram Session String 解析
    if not parsed:
        try:
            dc_id, auth_key, api_id_parsed, test_mode, user_id, is_bot = extract_from_pyrogram_string(source)
            api_id = api_id_parsed or default_api_id
            parsed = True
        except Exception:
            pass

    if not parsed:
        raise ValueError("未能识别或解析该 Telegram 会话，请确保提供的是有效的 Pyrogram / Telethon Session 文本或 .session 文件")

    auth_fingerprint = hashlib.sha256(auth_key).hexdigest()[:16]
    dc_info = TELETHON_DC_INFO.get(
        int(dc_id),
        {
            "name": f"DC{dc_id}",
            "region": "未知",
            "ip": TELETHON_DC_IPV4.get(int(dc_id), "149.154.175.53"),
            "port": 443,
        }
    )

    tele_str = pack_telethon_session(dc_id=dc_id, auth_key=auth_key, port=dc_info.get("port", 443))
    pyro_str = pack_pyrogram_session(
        dc_id=dc_id,
        auth_key=auth_key,
        api_id=api_id or default_api_id,
        test_mode=test_mode,
        user_id=user_id or 1,
        is_bot=is_bot,
    )

    return {
        "dc_id": int(dc_id),
        "dc_name": dc_info["name"],
        "dc_region": dc_info["region"],
        "dc_ip": dc_info["ip"],
        "dc_port": dc_info.get("port", 443),
        "user_id": int(user_id or 0),
        "api_id": int(api_id or 0),
        "test_mode": bool(test_mode),
        "is_bot": bool(is_bot),
        "auth_key_len": len(auth_key),
        "auth_key_fingerprint": auth_fingerprint,
        "telethon_session_string": tele_str,
        "pyrogram_session_string": pyro_str,
    }
