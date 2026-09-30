"""
认证模块：JWT 令牌生成/验证 + 密码哈希
全部使用 Python 内置库，无额外依赖。
"""

import os
import hashlib
import hmac
import json
import base64
import time
import secrets
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# JWT 密钥：优先从持久化文件/环境变量读取，保证容器重启后现有登录 Token 持续有效
def _load_or_create_jwt_secret() -> str:
    secret_env = os.environ.get("MISTRELAY_JWT_SECRET")
    if secret_env:
        return secret_env
    import db
    db_dir = os.path.dirname(getattr(db, "DB_PATH", None) or os.environ.get("MISTRELAY_DB_PATH", "/app/db/downloads.db"))
    key_file = os.path.join(db_dir, "jwt_signing.key")
    try:
        if os.path.exists(key_file):
            with open(key_file, "r", encoding="utf-8") as f:
                s = f.read().strip()
                if len(s) >= 32:
                    return s
        new_secret = secrets.token_hex(32)
        os.makedirs(os.path.dirname(os.path.abspath(key_file)), exist_ok=True)
        with open(key_file, "w", encoding="utf-8") as f:
            f.write(new_secret)
        return new_secret
    except Exception:
        return secrets.token_hex(32)

_JWT_SECRET: str = _load_or_create_jwt_secret()

# Access tokens are deliberately short lived; refresh tokens are rotated server-side.
TOKEN_EXPIRE_SECONDS = 15 * 60

# Refresh token 有效期（秒）：桌面客户端长期登录 30 天
REFRESH_TOKEN_EXPIRE_SECONDS = 30 * 24 * 3600
RESOURCE_TICKET_EXPIRE_SECONDS = 5 * 60
PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 600_000


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
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), PASSWORD_HASH_ITERATIONS
    )
    return f"{PASSWORD_HASH_SCHEME}${PASSWORD_HASH_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """验证密码是否匹配"""
    try:
        parts = hashed.split("$")
        if len(parts) == 4 and parts[0] == PASSWORD_HASH_SCHEME:
            iterations = int(parts[1])
            salt, dk_hex = parts[2], parts[3]
            if iterations < 100_000 or iterations > 2_000_000:
                return False
        elif len(parts) == 2:
            # Backward compatibility for hashes created before the incident fix.
            iterations = 100_000
            salt, dk_hex = parts
        else:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), iterations
        )
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def password_needs_rehash(hashed: str) -> bool:
    """Return true for legacy hashes or hashes below the current work factor."""
    try:
        scheme, iterations, _salt, _digest = hashed.split("$", 3)
        return scheme != PASSWORD_HASH_SCHEME or int(iterations) != PASSWORD_HASH_ITERATIONS
    except (AttributeError, TypeError, ValueError):
        return True


def create_token(user_id: int, username: str, role: str = "admin") -> str:
    """生成 JWT token，包含用户角色以供权限校验"""
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())

    payload_data = {
        "uid": user_id,
        "sub": username,
        "role": role,
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


def create_resource_ticket(path: str, lifetime_seconds: int = RESOURCE_TICKET_EXPIRE_SECONDS) -> str:
    """Create a short-lived ticket that grants access to one exact API path."""
    if not isinstance(path, str) or not path.startswith("/") or "\n" in path or "\r" in path:
        raise ValueError("resource ticket path must be an absolute URL path")
    lifetime = max(1, min(int(lifetime_seconds), RESOURCE_TICKET_EXPIRE_SECONDS))
    payload = _b64url_encode(json.dumps({
        "path": path,
        "exp": int(time.time()) + lifetime,
    }, separators=(",", ":")).encode())
    signature = hmac.new(
        _JWT_SECRET.encode(),
        f"resource.{payload}".encode(),
        hashlib.sha256,
    ).digest()
    return f"{payload}.{_b64url_encode(signature)}"


def verify_resource_ticket(ticket: str, path: str) -> bool:
    """Verify that a resource ticket is valid for the requested exact path."""
    try:
        payload_b64, signature_b64 = ticket.split(".", 1)
        expected_signature = hmac.new(
            _JWT_SECRET.encode(),
            f"resource.{payload_b64}".encode(),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected_signature, _b64url_decode(signature_b64)):
            return False
        payload = json.loads(_b64url_decode(payload_b64))
        return payload.get("path") == path and payload.get("exp", 0) >= time.time()
    except Exception:
        return False


def rotate_signing_secret() -> None:
    """Invalidate every outstanding access token after a security event."""
    global _JWT_SECRET
    _JWT_SECRET = secrets.token_hex(32)
    import db
    db_dir = os.path.dirname(getattr(db, "DB_PATH", None) or os.environ.get("MISTRELAY_DB_PATH", "/app/db/downloads.db"))
    key_file = os.path.join(db_dir, "jwt_signing.key")
    try:
        with open(key_file, "w", encoding="utf-8") as f:
            f.write(_JWT_SECRET)
    except Exception:
        pass


def verify_telegram_webapp_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = 86400,
) -> dict | None:
    """
    验证 Telegram WebApp / Mini App 的 initData 签名。
    符合 Telegram 官方 Mini App 签名算法：
    1. 解析 query string 参数并提取 hash；
    2. 其余参数按 key 字典序升序排序，用 \n 拼接为 "k=v" 字符串；
    3. secret_key = HMAC_SHA256(b"WebAppData", bot_token)；
    4. expected_hash = HMAC_SHA256(secret_key, data_check_string).hexdigest()；
    5. 常量时间比较 hash 与 expected_hash；
    6. 校验 auth_date 未过期且未超出未来时间窗口；
    校验通过则返回包含 user 字典、auth_date、query_id 及原始参数的 dict，失败返回 None。
    """
    import urllib.parse

    if not isinstance(init_data, str) or not init_data.strip():
        return None
    if not isinstance(bot_token, str) or not bot_token.strip():
        return None

    try:
        parsed = urllib.parse.parse_qsl(init_data.strip(), keep_blank_values=True)
        if not parsed:
            return None
        params = dict(parsed)
        received_hash = params.pop("hash", None)
        if not received_hash:
            return None

        auth_date_raw = params.get("auth_date")
        if not auth_date_raw:
            return None

        try:
            auth_date = int(auth_date_raw)
        except (ValueError, TypeError):
            return None

        now = int(time.time())
        if auth_date > now + 300 or (now - auth_date) > max_age_seconds:
            logger.warning(
                "TMA initData expired or invalid clock skew: auth_date=%s now=%s",
                auth_date,
                now,
            )
            return None

        sorted_items = sorted(params.items(), key=lambda x: x[0])
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_items)

        secret_key = hmac.new(
            b"WebAppData",
            bot_token.strip().encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expected_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_hash.lower(), received_hash.lower()):
            logger.warning("TMA initData hash mismatch")
            return None

        user_info = None
        user_str = params.get("user")
        if user_str:
            try:
                user_info = json.loads(user_str)
            except Exception:
                user_info = None

        return {
            "user": user_info,
            "auth_date": auth_date,
            "query_id": params.get("query_id"),
            "params": params,
        }
    except Exception as e:
        logger.warning("Failed to verify telegram webapp init_data: %s", e)
        return None
