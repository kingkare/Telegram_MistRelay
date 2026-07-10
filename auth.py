"""
认证模块：JWT 令牌生成/验证 + 密码哈希
全部使用 Python 内置库，无额外依赖。
"""

import hashlib
import hmac
import json
import base64
import time
import secrets
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# JWT 密钥：首次启动时随机生成，重启后旧 token 自动失效
_JWT_SECRET: str = secrets.token_hex(32)

# Token 有效期（秒）：默认 24 小时
TOKEN_EXPIRE_SECONDS = 24 * 3600

# Refresh token 有效期（秒）：桌面客户端长期登录 30 天
REFRESH_TOKEN_EXPIRE_SECONDS = 30 * 24 * 3600


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += '=' * padding
    return base64.urlsafe_b64decode(s)


def hash_password(password: str) -> str:
    """使用 PBKDF2-SHA256 对密码进行哈希"""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """验证密码是否匹配"""
    try:
        salt, dk_hex = hashed.split('$', 1)
        dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def create_token(user_id: int, username: str) -> str:
    """生成 JWT token"""
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())

    payload_data = {
        "uid": user_id,
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + TOKEN_EXPIRE_SECONDS,
    }
    payload = _b64url_encode(json.dumps(payload_data).encode())

    signing_input = f"{header}.{payload}"
    signature = hmac.new(_JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)

    return f"{header}.{payload}.{sig_b64}"


def create_refresh_token() -> str:
    """生成只返回给客户端一次的高熵 refresh token 明文。"""
    return secrets.token_urlsafe(48)


def hash_refresh_token(refresh_token: str) -> str:
    """对 refresh token 做不可逆哈希，数据库只保存该值。"""
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


def get_refresh_token_expires_at() -> str:
    """返回 refresh token 过期时间，使用 UTC ISO8601 字符串。"""
    return (
        datetime.utcnow() + timedelta(seconds=REFRESH_TOKEN_EXPIRE_SECONDS)
    ).isoformat(timespec="seconds") + "Z"


def verify_token(token: str) -> dict | None:
    """
    验证 JWT token。
    成功返回 payload dict，失败返回 None。
    """
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(_JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()

        actual_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload = json.loads(_b64url_decode(payload_b64))
        if payload.get('exp', 0) < time.time():
            return None

        return payload
    except Exception:
        return None
