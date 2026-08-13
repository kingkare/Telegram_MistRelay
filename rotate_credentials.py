#!/usr/bin/env python3
"""Replace compromised credentials from one protected YAML file."""

import argparse
import json
import os
import re
import sqlite3
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from auth import hash_password, verify_password
from legacy_config import (
    LegacyConfigError,
    legacy_config_path,
    retire_legacy_config,
)
from security_validation import (
    BOT_TOKEN_PATTERN,
    are_valid_telegram_credentials,
    credential_matches_preserved_fingerprint,
    is_valid_rpc_secret,
    parse_allowed_user_ids,
)


MAX_INPUT_BYTES = 64 * 1024
CHANNEL_ID_PATTERN = re.compile(r"-100[0-9]{6,16}")
REQUIRED_KEYS = frozenset({
    "API_ID",
    "API_HASH",
    "BOT_TOKEN",
    "ADMIN_ID",
    "BIN_CHANNEL",
    "STREAM_ALLOWED_USERS",
    "RPC_SECRET",
    "MULTI_BOT_TOKENS",
    "ADMIN_PASSWORD",
    "PUBLIC_BASE_URL",
    "SEND_STREAM_LINK",
})

CONFIG_DEFINITIONS = {
    "API_ID": ("int", "telegram", "Telegram API ID"),
    "API_HASH": ("string", "telegram", "Telegram API Hash"),
    "BOT_TOKEN": ("string", "telegram", "Telegram Bot Token"),
    "ADMIN_ID": ("int", "telegram", "Telegram administrator ID"),
    "BIN_CHANNEL": ("string", "stream", "Telegram storage channel ID"),
    "STREAM_ALLOWED_USERS": ("string", "stream", "Allowed numeric Telegram user IDs"),
    "RPC_SECRET": ("string", "aria2", "Aria2 RPC secret"),
    "MULTI_BOT_TOKENS": ("list", "stream", "Additional Telegram bot tokens"),
    "STREAM_USE_SESSION_FILE": ("bool", "stream", "Persist Pyrogram sessions"),
    "RPC_URL": ("string", "aria2", "Aria2 RPC URL"),
    "PROXY_IP": ("string", "download", "Telegram proxy host"),
    "PROXY_PORT": ("string", "download", "Telegram proxy port"),
    "SAVE_PATH": ("string", "download", "Download root"),
    "STREAM_BIND_ADDRESS": ("string", "stream", "Web bind address"),
    "STREAM_PORT": ("int", "stream", "Web listen port"),
    "STREAM_FQDN": ("string", "stream", "Public stream host"),
    "STREAM_HASH_LENGTH": ("int", "stream", "Stream capability hash length"),
    "STREAM_HAS_SSL": ("bool", "stream", "Generate HTTPS stream links"),
    "STREAM_NO_PORT": ("bool", "stream", "Omit port from stream links"),
    "ENABLE_STREAM": ("bool", "stream", "Enable the Web and stream service"),
    "UP_TELEGRAM": ("bool", "telegram", "Upload completed downloads to Telegram"),
    "SEND_STREAM_LINK": ("bool", "stream", "Send stream links to Telegram users"),
    "STREAM_AUTO_DOWNLOAD": ("bool", "stream", "Legacy Telegram auto-download switch"),
    "DOWNLOAD_CLEANUP_ENABLED": ("bool", "download", "Automatic download cleanup"),
    "SECURITY_BASELINE_VERSION": ("int", "security", "Applied security baseline version"),
}

RETIRED_LEGACY_CONFIG_KEYS = frozenset({
    "FORWARD_ID",
    "GOOGLE_DRIVE_PATH",
    "GOOGLE_DRIVE_REMOTE",
    "MEDIA_ARCHIVE_TARGET",
    "RCLONE_PATH",
    "RCLONE_REMOTE",
    "UP_GOOGLE_DRIVE",
    "UP_ONEDRIVE",
})


class RotationError(ValueError):
    pass


def _protected_file(path: Path) -> bytes:
    try:
        file_stat = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise RotationError(f"cannot read protected input file: {exc}") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise RotationError("credential input must be a regular file, not a link or device")
    if file_stat.st_uid != os.geteuid():
        raise RotationError("credential input must be owned by the current user")
    if stat.S_IMODE(file_stat.st_mode) & 0o077:
        raise RotationError("credential input permissions must be 0600 or stricter")
    if file_stat.st_size <= 0 or file_stat.st_size > MAX_INPUT_BYTES:
        raise RotationError("credential input size is invalid")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RotationError(f"cannot read protected input file: {exc}") from exc


def _reject_preserved_compromised_values(values: dict) -> None:
    for key in ("API_HASH", "RPC_SECRET"):
        if credential_matches_preserved_fingerprint(values[key], key):
            raise RotationError(f"{key} matches a preserved compromised fingerprint")
    bot_tokens = [values["BOT_TOKEN"], *values["MULTI_BOT_TOKENS"]]
    if any(
        credential_matches_preserved_fingerprint(token, "BOT_TOKENS")
        for token in bot_tokens
    ):
        raise RotationError("a Bot token matches a preserved compromised fingerprint")


def load_and_validate(path: Path) -> dict:
    try:
        data = yaml.safe_load(_protected_file(path))
    except yaml.YAMLError as exc:
        raise RotationError("credential input is not valid YAML") from exc
    if not isinstance(data, dict):
        raise RotationError("credential input must contain a YAML mapping")

    supplied_keys = set(data)
    missing = sorted(REQUIRED_KEYS - supplied_keys)
    unknown = sorted(supplied_keys - REQUIRED_KEYS)
    if missing:
        raise RotationError(f"credential input is missing keys: {', '.join(missing)}")
    if unknown:
        raise RotationError(f"credential input contains unknown keys: {', '.join(unknown)}")

    allowed_users = parse_allowed_user_ids(data["STREAM_ALLOWED_USERS"])
    admin_id = str(data["ADMIN_ID"] or "").strip()
    if not are_valid_telegram_credentials(
        data["API_ID"], data["API_HASH"], data["BOT_TOKEN"], allowed_users
    ):
        raise RotationError("Telegram API credentials or numeric allowlist are invalid")
    if admin_id not in allowed_users:
        raise RotationError("ADMIN_ID must be present in STREAM_ALLOWED_USERS")

    channel_id = str(data["BIN_CHANNEL"] or "").strip()
    if CHANNEL_ID_PATTERN.fullmatch(channel_id) is None:
        raise RotationError("BIN_CHANNEL must be a numeric Telegram channel ID beginning with -100")
    if not is_valid_rpc_secret(data["RPC_SECRET"]):
        raise RotationError("RPC_SECRET must be a new high-entropy URL-safe value")

    multi_tokens = data["MULTI_BOT_TOKENS"]
    if not isinstance(multi_tokens, list) or not all(
        isinstance(token, str) and BOT_TOKEN_PATTERN.fullmatch(token.strip())
        for token in multi_tokens
    ):
        raise RotationError("MULTI_BOT_TOKENS must be a list of valid, newly issued tokens")
    normalized_multi_tokens = [token.strip() for token in multi_tokens]
    if len(set(normalized_multi_tokens)) != len(normalized_multi_tokens):
        raise RotationError("MULTI_BOT_TOKENS contains duplicate tokens")
    if str(data["BOT_TOKEN"]).strip() in normalized_multi_tokens:
        raise RotationError("BOT_TOKEN must not also appear in MULTI_BOT_TOKENS")

    admin_password = data["ADMIN_PASSWORD"]
    if not isinstance(admin_password, str) or not 16 <= len(admin_password) <= 512:
        raise RotationError("ADMIN_PASSWORD must contain 16-512 characters")
    if admin_password.casefold() in {"admin123", "password", "changeme", "change-me"}:
        raise RotationError("ADMIN_PASSWORD is a known unsafe value")

    public_base_url = data["PUBLIC_BASE_URL"]
    send_stream_link = data["SEND_STREAM_LINK"]
    if not isinstance(public_base_url, str) or not isinstance(send_stream_link, bool):
        raise RotationError("PUBLIC_BASE_URL must be a string and SEND_STREAM_LINK a boolean")
    public_base_url = public_base_url.strip().rstrip("/")
    if public_base_url:
        try:
            parsed_url = urlsplit(public_base_url)
            port = parsed_url.port
        except ValueError as exc:
            raise RotationError("PUBLIC_BASE_URL is invalid") from exc
        hostname = parsed_url.hostname or ""
        valid_hostname = (
            hostname.isascii()
            and re.fullmatch(r"[A-Za-z0-9.-]{1,253}", hostname) is not None
            and not hostname.startswith((".", "-"))
            and not hostname.endswith((".", "-"))
            and ".." not in hostname
        )
        if (
            parsed_url.scheme != "https"
            or not valid_hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or port not in (None, 443)
            or parsed_url.path not in ("", "/")
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise RotationError("PUBLIC_BASE_URL must be a standard HTTPS origin without a path")
        stream_fqdn = hostname
        stream_has_ssl = True
        stream_no_port = True
    else:
        if send_stream_link:
            raise RotationError("SEND_STREAM_LINK requires a non-empty PUBLIC_BASE_URL")
        stream_fqdn = "127.0.0.1"
        stream_has_ssl = False
        stream_no_port = False

    normalized_values = {
        "API_ID": int(str(data["API_ID"]).strip()),
        "API_HASH": str(data["API_HASH"]).strip(),
        "BOT_TOKEN": str(data["BOT_TOKEN"]).strip(),
        "ADMIN_ID": int(admin_id),
        "BIN_CHANNEL": channel_id,
        "STREAM_ALLOWED_USERS": ",".join(allowed_users),
        "RPC_SECRET": str(data["RPC_SECRET"]).strip(),
        "MULTI_BOT_TOKENS": normalized_multi_tokens,
        "ADMIN_PASSWORD": admin_password,
        "STREAM_FQDN": stream_fqdn,
        "STREAM_HAS_SSL": stream_has_ssl,
        "STREAM_NO_PORT": stream_no_port,
        "SEND_STREAM_LINK": send_stream_link,
    }
    _reject_preserved_compromised_values(normalized_values)
    return normalized_values


def _serialize_config(value: object, value_type: str) -> str:
    if value_type in {"list", "json"}:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    if value_type == "bool":
        return "true" if bool(value) else "false"
    return str(value)


def _stored_bot_tokens(raw_value: object) -> set[str]:
    if not raw_value:
        return set()
    if isinstance(raw_value, list):
        values = raw_value
    else:
        text = str(raw_value).strip()
        try:
            decoded = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            decoded = None
        values = decoded if isinstance(decoded, list) else text.split(",")
    return {
        str(value).strip()
        for value in values
        if isinstance(value, str) and value.strip()
    }


def _ensure_recovery_schema(connection: sqlite3.Connection) -> None:
    """Upgrade the legacy auth schema inside the same recovery transaction."""
    existing_tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if not {"config_settings", "users"}.issubset(existing_tables):
        raise RotationError("database lacks the legacy configuration or user tables")

    connection.execute(
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
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(auth_sessions)")
    }
    required_columns = {
        "id", "user_id", "token_hash", "device_id", "session_name", "expires_at",
        "revoked_at", "revoked_reason", "replaced_by", "created_at", "last_used_at",
    }
    if not required_columns.issubset(columns):
        raise RotationError("existing auth_sessions schema is incompatible")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_sessions_token_hash "
        "ON auth_sessions (token_hash)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id "
        "ON auth_sessions (user_id)"
    )


def _rotation_config_values(values: dict) -> dict:
    config_values = {
        key: values[key]
        for key in (
            "API_ID", "API_HASH", "BOT_TOKEN", "ADMIN_ID", "BIN_CHANNEL",
            "STREAM_ALLOWED_USERS", "RPC_SECRET", "MULTI_BOT_TOKENS",
        )
    }
    config_values.update({
        "STREAM_USE_SESSION_FILE": False,
        "RPC_URL": "localhost:6800/jsonrpc",
        "PROXY_IP": "",
        "PROXY_PORT": "",
        "SAVE_PATH": "/data/downloads",
        "STREAM_BIND_ADDRESS": "0.0.0.0",
        "STREAM_PORT": 8080,
        "STREAM_FQDN": values["STREAM_FQDN"],
        "STREAM_HASH_LENGTH": 32,
        "STREAM_HAS_SSL": values["STREAM_HAS_SSL"],
        "STREAM_NO_PORT": values["STREAM_NO_PORT"],
        "ENABLE_STREAM": True,
        "UP_TELEGRAM": True,
        "SEND_STREAM_LINK": values["SEND_STREAM_LINK"],
        "STREAM_AUTO_DOWNLOAD": False,
        "DOWNLOAD_CLEANUP_ENABLED": False,
        "SECURITY_BASELINE_VERSION": 2,
    })
    return config_values


def _rotation_state_matches(
    connection: sqlite3.Connection,
    config_values: dict,
    admin_password: str,
) -> bool:
    users = connection.execute(
        "SELECT username, password_hash FROM users ORDER BY id"
    ).fetchall()
    if (
        len(users) != 1
        or users[0][0] != "admin"
        or not verify_password(admin_password, users[0][1])
    ):
        return False

    expected = {
        key: (_serialize_config(value, CONFIG_DEFINITIONS[key][0]), CONFIG_DEFINITIONS[key][0])
        for key, value in config_values.items()
    }
    placeholders = ",".join("?" for _ in expected)
    actual = {
        row[0]: (row[1], row[2])
        for row in connection.execute(
            f"SELECT key, value, value_type FROM config_settings "
            f"WHERE key IN ({placeholders})",
            tuple(expected),
        )
    }
    if actual != expected:
        return False
    legacy_placeholders = ",".join("?" for _ in RETIRED_LEGACY_CONFIG_KEYS)
    if connection.execute(
        f"SELECT COUNT(*) FROM config_settings WHERE key IN ({legacy_placeholders})",
        tuple(sorted(RETIRED_LEGACY_CONFIG_KEYS)),
    ).fetchone()[0]:
        return False
    return connection.execute(
        "SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL"
    ).fetchone()[0] == 0


def rotate_database(
    database_path: Path,
    values: dict,
    legacy_config_file: Path | None = None,
) -> dict[str, int]:
    try:
        database_stat = database_path.stat(follow_symlinks=False)
    except OSError as exc:
        raise RotationError(f"cannot access database: {exc}") from exc
    if not stat.S_ISREG(database_stat.st_mode):
        raise RotationError("database must be an existing regular file")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    config_values = _rotation_config_values(values)
    already_applied = False
    removed_legacy_settings = 0
    revoked_sessions = 0
    connection = None
    try:
        connection = sqlite3.connect(str(database_path), timeout=15)
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")

        _ensure_recovery_schema(connection)

        if _rotation_state_matches(connection, config_values, values["ADMIN_PASSWORD"]):
            already_applied = True
            connection.commit()
        else:
            users = connection.execute(
                "SELECT username, password_hash FROM users ORDER BY id"
            ).fetchall()
            if len(users) != 1 or users[0][0] != "admin":
                raise RotationError("recovery requires exactly one existing administrator account")
            if verify_password(values["ADMIN_PASSWORD"], users[0][1]):
                raise RotationError(
                    "ADMIN_PASSWORD already matches but the prior rotation is incomplete; "
                    "use another new password"
                )

            existing_secrets = dict(connection.execute(
                "SELECT key, value FROM config_settings WHERE key IN "
                "('API_ID', 'API_HASH', 'BOT_TOKEN', 'MULTI_BOT_TOKENS', 'RPC_SECRET')"
            ).fetchall())
            for key in ("API_ID", "API_HASH", "BOT_TOKEN", "RPC_SECRET"):
                if (
                    str(existing_secrets.get(key) or "").strip()
                    and str(existing_secrets[key]).strip() == str(values[key]).strip()
                ):
                    raise RotationError(f"{key} must differ from the exposed value")

            exposed_bot_tokens = _stored_bot_tokens(
                existing_secrets.get("MULTI_BOT_TOKENS")
            )
            exposed_primary_token = str(existing_secrets.get("BOT_TOKEN") or "").strip()
            if exposed_primary_token:
                exposed_bot_tokens.add(exposed_primary_token)
            if values["BOT_TOKEN"] in exposed_bot_tokens:
                raise RotationError("BOT_TOKEN must not reuse any exposed bot token")
            if exposed_bot_tokens.intersection(values["MULTI_BOT_TOKENS"]):
                raise RotationError(
                    "MULTI_BOT_TOKENS must not reuse any exposed bot token"
                )

            for key, value in config_values.items():
                value_type, category, description = CONFIG_DEFINITIONS[key]
                connection.execute(
                    """
                    INSERT INTO config_settings
                        (key, value, value_type, category, description, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        value_type = excluded.value_type,
                        category = excluded.category,
                        description = excluded.description,
                        updated_at = excluded.updated_at
                    """,
                    (
                        key,
                        _serialize_config(value, value_type),
                        value_type,
                        category,
                        description,
                        now,
                    ),
                )

            legacy_placeholders = ",".join("?" for _ in RETIRED_LEGACY_CONFIG_KEYS)
            removed_legacy_settings = connection.execute(
                f"DELETE FROM config_settings WHERE key IN ({legacy_placeholders})",
                tuple(sorted(RETIRED_LEGACY_CONFIG_KEYS)),
            ).rowcount
            revoked_sessions = connection.execute(
                "UPDATE auth_sessions SET revoked_at = ?, revoked_reason = ? "
                "WHERE revoked_at IS NULL",
                (now, "incident credential rotation"),
            ).rowcount
            connection.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE username = 'admin'",
                (hash_password(values["ADMIN_PASSWORD"]), now),
            )
            connection.commit()
    except sqlite3.Error as exc:
        if connection is not None:
            connection.rollback()
        raise RotationError(f"database rotation failed: {exc}") from exc
    except Exception:
        if connection is not None:
            connection.rollback()
        raise
    finally:
        if connection is not None:
            connection.close()

    try:
        with sqlite3.connect(str(database_path), timeout=15) as verification:
            if not _rotation_state_matches(
                verification, config_values, values["ADMIN_PASSWORD"]
            ):
                raise RotationError(
                    "database rotation committed but post-commit verification failed"
                )
    except sqlite3.Error as exc:
        raise RotationError(
            f"database rotation committed but verification could not run: {exc}"
        ) from exc

    try:
        retired_legacy_config = retire_legacy_config(
            legacy_config_file or legacy_config_path(database_path)
        )
    except LegacyConfigError as exc:
        raise RotationError(
            "database rotation committed but legacy cleanup failed; "
            f"rerun the same command to retry cleanup: {exc}"
        ) from exc

    return {
        "updated_settings": 0 if already_applied else len(config_values),
        "removed_legacy_settings": removed_legacy_settings,
        "revoked_sessions": revoked_sessions,
        "retired_legacy_config": int(retired_legacy_config),
        "already_applied": int(already_applied),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replace MistRelay credentials while the service is stopped."
    )
    parser.add_argument("--input", required=True, type=Path, help="owner-only YAML file")
    parser.add_argument(
        "--database", type=Path, default=Path("db/downloads.db"), help="MistRelay SQLite database"
    )
    parser.add_argument(
        "--legacy-config",
        type=Path,
        help="legacy YAML path to retire (defaults to config.yml beside the database)",
    )
    arguments = parser.parse_args()
    try:
        values = load_and_validate(arguments.input)
        result = rotate_database(arguments.database, values, arguments.legacy_config)
    except RotationError as exc:
        print(f"credential rotation refused: {exc}", file=sys.stderr)
        return 1
    print(
        "credential rotation completed: "
        f"{result['updated_settings']} settings updated, "
        f"{result['removed_legacy_settings']} legacy settings removed, "
        f"{result['revoked_sessions']} sessions revoked, "
        f"{result['retired_legacy_config']} legacy files retired, "
        f"already applied={result['already_applied']}; remove the input file now"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
