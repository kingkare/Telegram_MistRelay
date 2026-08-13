#!/usr/bin/env python3
"""Read-only activation gate for an incident-recovered MistRelay deployment."""

import argparse
import hashlib
import io
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from security_validation import (
    BOT_TOKEN_PATTERN,
    are_valid_telegram_credentials,
    contains_preserved_compromised_credentials,
    is_valid_rpc_secret,
    parse_allowed_user_ids,
)


CHANNEL_ID_PATTERN = re.compile(r"-100[0-9]{6,16}")
PASSWORD_HASH_PATTERN = re.compile(
    r"pbkdf2_sha256\$600000\$[0-9a-f]{32}\$[0-9a-f]{64}"
)
REQUIRED_TABLES = frozenset({
    "auth_sessions",
    "config_settings",
    "downloads",
    "tg_media",
    "uploads",
    "users",
})
ALLOWED_EXTRA_TABLES = frozenset({"tg_channel_files"})
REQUIRED_MOUNTS = frozenset({"/app/db", "/data/downloads", "/app/cache/thumbnails"})
EXPECTED_HEALTHCHECK = [
    "CMD",
    "python3",
    "-c",
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=5).read()",
]
CRITICAL_IMAGE_FILES = (
    "activation_preflight.py",
    "app.py",
    "auth.py",
    "configer.py",
    "db.py",
    "legacy_config.py",
    "request_security.py",
    "rotate_credentials.py",
    "security_validation.py",
    "service_runtime.py",
    "start.sh",
    "WebStreamer/bot/__init__.py",
    "WebStreamer/server/__init__.py",
    "WebStreamer/server/stream_routes.py",
)
CANONICAL_CONFIG_TYPES = {
    "ADMIN_ID": "int",
    "API_HASH": "string",
    "API_ID": "int",
    "BIN_CHANNEL": "string",
    "BOT_TOKEN": "string",
    "DOWNLOAD_CLEANUP_ENABLED": "bool",
    "ENABLE_STREAM": "bool",
    "MULTI_BOT_TOKENS": "list",
    "PROXY_IP": "string",
    "PROXY_PORT": "string",
    "RPC_SECRET": "string",
    "RPC_URL": "string",
    "SAVE_PATH": "string",
    "SECURITY_BASELINE_VERSION": "int",
    "SEND_STREAM_LINK": "bool",
    "STREAM_ALLOWED_USERS": "string",
    "STREAM_AUTO_DOWNLOAD": "bool",
    "STREAM_BIND_ADDRESS": "string",
    "STREAM_FQDN": "string",
    "STREAM_HASH_LENGTH": "int",
    "STREAM_HAS_SSL": "bool",
    "STREAM_NO_PORT": "bool",
    "STREAM_PORT": "int",
    "STREAM_USE_SESSION_FILE": "bool",
    "UP_TELEGRAM": "bool",
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


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _check(name: str, ok: bool, success: str, failure: str) -> Check:
    return Check(name=name, ok=bool(ok), detail=success if ok else failure)


def _file_stat(path: Path):
    try:
        return path.stat(follow_symlinks=False)
    except OSError:
        return None


def _owner_only_file(path: Path, uid: int, gid: int) -> bool:
    file_stat = _file_stat(path)
    mode = stat.S_IMODE(file_stat.st_mode) if file_stat else 0
    return bool(
        file_stat
        and stat.S_ISREG(file_stat.st_mode)
        and file_stat.st_nlink == 1
        and file_stat.st_uid == uid
        and file_stat.st_gid == gid
        and mode & 0o600 == 0o600
        and mode & 0o177 == 0
    )


def _private_directory(path: Path, uid: int, gid: int) -> bool:
    directory_stat = _file_stat(path)
    mode = stat.S_IMODE(directory_stat.st_mode) if directory_stat else 0
    return bool(
        directory_stat
        and stat.S_ISDIR(directory_stat.st_mode)
        and directory_stat.st_uid == uid
        and directory_stat.st_gid == gid
        and mode & 0o700 == 0o700
        and mode & 0o007 == 0
    )


def _session_material_count(database_dir: Path) -> int:
    count = 0
    try:
        for root, directories, files in os.walk(database_dir, followlinks=False):
            for name in directories:
                path = Path(root, name)
                if path.is_symlink() or name == "sessions":
                    count += 1
            for name in files:
                lowered = name.lower()
                if ".session" in lowered:
                    count += 1
    except OSError:
        return -1
    return count


def evaluate_filesystem(
    database_path: Path,
    download_root: Path,
    cache_root: Path,
    runtime_uid: int,
    runtime_gid: int,
    rotation_input_path: Path | None = None,
) -> list[Check]:
    database_dir = database_path.parent
    checks = [
        _check(
            "database_file_permissions",
            _owner_only_file(database_path, runtime_uid, runtime_gid),
            "database is a runtime-owned owner-only regular file",
            "database must be a runtime-owned regular file with mode 0600 or stricter",
        ),
        _check(
            "database_directory_permissions",
            _private_directory(database_dir, runtime_uid, runtime_gid),
            "database directory excludes other users",
            "database directory must be runtime-owned and inaccessible to other users",
        ),
        _check(
            "download_directory_permissions",
            _private_directory(download_root, runtime_uid, runtime_gid),
            "download directory excludes other users",
            "download directory must be runtime-owned and inaccessible to other users",
        ),
        _check(
            "cache_directory_permissions",
            _private_directory(cache_root, runtime_uid, runtime_gid),
            "thumbnail cache excludes other users",
            "thumbnail cache must be runtime-owned and inaccessible to other users",
        ),
    ]

    sidecars = [
        path for path in (
            Path(f"{database_path}-wal"),
            Path(f"{database_path}-shm"),
        )
        if os.path.lexists(path)
    ]
    checks.append(_check(
        "database_sidecar_permissions",
        all(_owner_only_file(path, runtime_uid, runtime_gid) for path in sidecars),
        "existing SQLite sidecars are runtime-owned owner-only regular files",
        "a SQLite sidecar has unsafe ownership, mode, type, or link count",
    ))

    legacy_config = database_dir / "config.yml"
    legacy_ok = not os.path.lexists(legacy_config)
    if not legacy_ok and _owner_only_file(legacy_config, runtime_uid, runtime_gid):
        try:
            legacy_ok = (yaml.safe_load(legacy_config.read_text(encoding="utf-8")) or {}) == {}
        except (OSError, UnicodeError, yaml.YAMLError):
            legacy_ok = False
    checks.append(_check(
        "legacy_yaml_retired",
        legacy_ok,
        "legacy YAML is absent or an empty owner-only retirement marker",
        "legacy YAML still contains data, is unsafe, or is unreadable",
    ))

    admin_password = database_dir / "admin-password"
    checks.append(_check(
        "initial_password_removed",
        not os.path.lexists(admin_password),
        "initial plaintext password file is absent",
        "remove the initial plaintext password file before activation",
    ))

    session_count = _session_material_count(database_dir)
    checks.append(_check(
        "session_material_absent",
        session_count == 0,
        "no filesystem Telegram session material is mounted",
        "filesystem Telegram session material or an unreadable session path remains",
    ))
    if rotation_input_path is not None:
        checks.append(_check(
            "rotation_input_removed",
            not os.path.lexists(rotation_input_path),
            "owner-only credential rotation input has been removed",
            "credential rotation input still exists at the declared path",
        ))
    return checks


def _decode_config(value: str | None, value_type: str):
    if value_type in {"list", "json"}:
        try:
            return json.loads(value) if value else ([] if value_type == "list" else {})
        except (json.JSONDecodeError, TypeError):
            return None
    if value_type == "bool":
        return str(value or "").lower() in {"true", "1", "yes", "on"}
    if value_type == "int":
        try:
            return int(value) if value else None
        except (TypeError, ValueError):
            return None
    return value or ""


def _canonical_config_value(raw_value: str | None, value_type: str) -> bool:
    value = "" if raw_value is None else str(raw_value)
    if value_type == "bool":
        return value in {"true", "false"}
    if value_type == "int":
        try:
            return str(int(value)) == value
        except (TypeError, ValueError):
            return False
    if value_type == "list":
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return False
        return isinstance(decoded, list) and json.dumps(
            decoded,
            ensure_ascii=True,
            separators=(",", ":"),
        ) == value
    return value_type == "string"


def _origin_matches(config: dict, expected_origin: str | None) -> bool:
    send_links = config.get("SEND_STREAM_LINK") is True
    fqdn = str(config.get("STREAM_FQDN") or "").strip().lower()
    secure_link_config = (
        config.get("STREAM_HAS_SSL") is True
        and config.get("STREAM_NO_PORT") is True
        and fqdn not in {"", "127.0.0.1", "localhost"}
    )
    if send_links and not secure_link_config:
        return False
    if expected_origin is None:
        return True
    try:
        parsed = urlsplit(expected_origin.strip().rstrip("/"))
        port = parsed.port
    except (AttributeError, TypeError, ValueError):
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
        and secure_link_config
        and fqdn == parsed.hostname.lower()
    )


def evaluate_database(
    database_path: Path,
    expected_origin: str | None,
    expected_admin_id: str | None = None,
    expected_channel_id: str | None = None,
    expected_allowed_users: list[str] | None = None,
) -> list[Check]:
    checks: list[Check] = []
    try:
        connection = sqlite3.connect(
            f"file:{database_path}?mode=ro",
            uri=True,
            timeout=10,
        )
    except sqlite3.Error:
        return [Check("database_open", False, "database cannot be opened read-only")]

    try:
        connection.execute("PRAGMA query_only=ON")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        checks.append(_check(
            "sqlite_integrity",
            bool(integrity and integrity[0] == "ok"),
            "SQLite integrity check is clean",
            "SQLite integrity check failed",
        ))
        foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        checks.append(_check(
            "sqlite_foreign_keys",
            not foreign_key_violations,
            "SQLite foreign-key check is clean",
            "SQLite contains foreign-key violations",
        ))

        schema_rows = connection.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE type IN ('table', 'view', 'trigger')"
        ).fetchall()
        tables = {name for object_type, name in schema_rows if object_type == "table"}
        unexpected_tables = {
            name for name in tables
            if not name.startswith("sqlite_")
            and name not in REQUIRED_TABLES
            and name not in ALLOWED_EXTRA_TABLES
        }
        executable_schema_objects = [
            name for object_type, name in schema_rows if object_type in {"view", "trigger"}
        ]
        checks.append(_check(
            "database_schema",
            REQUIRED_TABLES.issubset(tables) and not unexpected_tables,
            "required tables exist and no unexpected application tables are present",
            "required tables are missing or unexpected application tables are present",
        ))
        checks.append(_check(
            "database_executable_schema",
            not executable_schema_objects,
            "no views or triggers are installed",
            "unexpected views or triggers are installed",
        ))

        table_columns = {
            table: {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            for table in ("auth_sessions", "config_settings", "users")
            if table in tables
        }
        auth_foreign_keys = (
            connection.execute("PRAGMA foreign_key_list(auth_sessions)").fetchall()
            if "auth_sessions" in tables else []
        )
        auth_indexes = (
            connection.execute("PRAGMA index_list(auth_sessions)").fetchall()
            if "auth_sessions" in tables else []
        )
        security_schema_ok = all((
            {
                "id", "user_id", "token_hash", "expires_at", "revoked_at",
                "revoked_reason", "replaced_by", "created_at", "last_used_at",
            }.issubset(table_columns.get("auth_sessions", set())),
            {"key", "value", "value_type", "category", "updated_at"}.issubset(
                table_columns.get("config_settings", set())
            ),
            {"id", "username", "password_hash", "role", "created_at", "updated_at"}.issubset(
                table_columns.get("users", set())
            ),
            any(row[2] == "users" and row[3] == "user_id" and row[4] == "id"
                for row in auth_foreign_keys),
            any(row[2] == "auth_sessions" and row[3] == "replaced_by" and row[4] == "id"
                for row in auth_foreign_keys),
            any(row[1] == "idx_auth_sessions_token_hash" and bool(row[2])
                for row in auth_indexes),
        ))
        checks.append(_check(
            "database_security_schema",
            security_schema_ok,
            "authentication and configuration schema constraints are present",
            "authentication or configuration schema constraints are incomplete",
        ))

        config_rows = connection.execute(
            "SELECT key, value, value_type FROM config_settings"
        ).fetchall()
        raw_config = {
            key: (value, value_type)
            for key, value, value_type in config_rows
        }
        config = {
            key: _decode_config(value, value_type)
            for key, value, value_type in config_rows
        }
        canonical_config = all(
            key in raw_config
            and raw_config[key][1] == expected_type
            and _canonical_config_value(raw_config[key][0], raw_config[key][1])
            for key, expected_type in CANONICAL_CONFIG_TYPES.items()
        )
        checks.append(_check(
            "canonical_config_storage",
            canonical_config,
            "security-sensitive settings use canonical types and serialization",
            "security-sensitive settings are missing or use non-canonical storage",
        ))
        allowed_users = parse_allowed_user_ids(config.get("STREAM_ALLOWED_USERS"))
        telegram_ready = are_valid_telegram_credentials(
            config.get("API_ID"),
            config.get("API_HASH"),
            config.get("BOT_TOKEN"),
            allowed_users,
        )
        admin_id = str(config.get("ADMIN_ID") or "").strip()
        channel_id = str(config.get("BIN_CHANNEL") or "").strip()
        checks.append(_check(
            "telegram_credentials",
            telegram_ready
            and admin_id in allowed_users
            and CHANNEL_ID_PATTERN.fullmatch(channel_id) is not None,
            "Telegram credentials, administrator, channel and allowlist pass validation",
            "Telegram credentials, administrator, channel or numeric allowlist are invalid",
        ))
        exact_identity_scope = True
        if expected_admin_id is not None:
            exact_identity_scope = exact_identity_scope and admin_id == str(expected_admin_id)
        if expected_channel_id is not None:
            exact_identity_scope = exact_identity_scope and channel_id == str(expected_channel_id)
        if expected_allowed_users is not None:
            exact_identity_scope = exact_identity_scope and set(allowed_users) == set(
                expected_allowed_users
            ) and len(allowed_users) == len(expected_allowed_users)
        checks.append(_check(
            "telegram_identity_scope",
            exact_identity_scope,
            "Telegram administrator, channel and complete allowlist match expectations",
            "Telegram administrator, channel or allowlist contains an unexpected identity",
        ))

        primary_token = str(config.get("BOT_TOKEN") or "").strip()
        multi_tokens = config.get("MULTI_BOT_TOKENS")
        multi_ready = isinstance(multi_tokens, list) and all(
            isinstance(token, str) and BOT_TOKEN_PATTERN.fullmatch(token.strip())
            for token in multi_tokens
        )
        normalized_multi = [token.strip() for token in multi_tokens] if multi_ready else []
        checks.append(_check(
            "telegram_multi_bot_tokens",
            multi_ready
            and len(normalized_multi) == len(set(normalized_multi))
            and primary_token not in normalized_multi,
            "additional Bot tokens are well formed and unique",
            "additional Bot tokens are malformed, duplicated, or reuse the primary token",
        ))
        preserved_credentials_absent = not contains_preserved_compromised_credentials(
            api_id=config.get("API_ID"),
            api_hash=config.get("API_HASH"),
            bot_tokens=[primary_token, *normalized_multi],
            rpc_secret=config.get("RPC_SECRET"),
        )
        checks.append(_check(
            "preserved_compromised_credentials_absent",
            preserved_credentials_absent,
            "no credential matches the incident evidence fingerprints",
            "a credential matches an incident evidence fingerprint and must be revoked",
        ))

        runtime_config_ok = all((
            is_valid_rpc_secret(config.get("RPC_SECRET")),
            config.get("RPC_URL") == "localhost:6800/jsonrpc",
            config.get("PROXY_IP") == "",
            config.get("PROXY_PORT") == "",
            config.get("SAVE_PATH") == "/data/downloads",
            config.get("STREAM_BIND_ADDRESS") == "0.0.0.0",
            config.get("STREAM_PORT") == 8080,
            isinstance(config.get("STREAM_HASH_LENGTH"), int),
            (config.get("STREAM_HASH_LENGTH") or 0) >= 32,
            config.get("STREAM_USE_SESSION_FILE") is False,
            config.get("STREAM_AUTO_DOWNLOAD") is False,
            config.get("ENABLE_STREAM") is True,
            config.get("UP_TELEGRAM") is True,
            not RETIRED_LEGACY_CONFIG_KEYS.intersection(config),
        ))
        checks.append(_check(
            "security_runtime_config",
            runtime_config_ok,
            "RPC, proxy, file root, listener, stream and legacy settings match the baseline",
            "one or more security-sensitive runtime settings differ from the baseline",
        ))
        checks.append(_check(
            "public_origin",
            _origin_matches(config, expected_origin),
            "public stream-link settings are internally consistent",
            "public stream-link settings do not match the required HTTPS origin",
        ))
        checks.append(_check(
            "security_baseline",
            config.get("SECURITY_BASELINE_VERSION") == 2,
            "security baseline version 2 is recorded",
            "security baseline version 2 is missing",
        ))

        users = connection.execute(
            "SELECT username, role, password_hash FROM users ORDER BY id"
        ).fetchall()
        admin_ready = bool(
            len(users) == 1
            and users[0][0] == "admin"
            and users[0][1] == "admin"
            and PASSWORD_HASH_PATTERN.fullmatch(str(users[0][2] or ""))
        )
        checks.append(_check(
            "administrator_account",
            admin_ready,
            "exactly one administrator exists with the current password hash scheme",
            "administrator count, role or password hash scheme is unsafe",
        ))

        active_sessions = connection.execute(
            "SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL"
        ).fetchone()[0]
        checks.append(_check(
            "web_sessions_revoked",
            active_sessions == 0,
            "no pre-activation Web refresh sessions remain active",
            "active Web refresh sessions remain",
        ))
    except sqlite3.Error:
        checks.append(Check(
            "database_queries",
            False,
            "one or more required database queries failed",
        ))
    finally:
        connection.close()
    return checks


def _docker_inspect(name: str) -> dict | None:
    try:
        result = subprocess.run(
            ["docker", "inspect", name],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        documents = json.loads(result.stdout)
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    return documents[0] if isinstance(documents, list) and len(documents) == 1 else None


def _docker_image_id(reference: str) -> str | None:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", reference, "--format", "{{.Id}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _docker_network_inspect(name: str) -> dict | None:
    try:
        result = subprocess.run(
            ["docker", "network", "inspect", name],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        documents = json.loads(result.stdout)
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    return documents[0] if isinstance(documents, list) and len(documents) == 1 else None


def _container_source_matches(container_name: str, source_root: Path) -> bool:
    host_hashes = {}
    for relative_path in CRITICAL_IMAGE_FILES:
        source_path = source_root / relative_path
        try:
            host_hashes[f"/app/{relative_path}"] = hashlib.sha256(
                source_path.read_bytes()
            ).hexdigest()
        except OSError:
            return False
    try:
        result = subprocess.run(
            ["docker", "cp", f"{container_name}:/app", "-"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        archive = tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:*")
    except (FileNotFoundError, subprocess.SubprocessError, tarfile.TarError):
        return False
    image_hashes = {}
    try:
        members = {
            member.name.removeprefix("./"): member
            for member in archive.getmembers()
        }
        for image_path in host_hashes:
            relative_path = image_path.removeprefix("/app/")
            member = members.get(f"app/{relative_path}") or members.get(relative_path)
            if member is None:
                return False
            handle = archive.extractfile(member)
            if handle is None:
                return False
            image_hashes[image_path] = hashlib.sha256(handle.read()).hexdigest()
    finally:
        archive.close()
    return image_hashes == host_hashes


def evaluate_container(
    container_name: str,
    image_reference: str,
    source_root: Path | None = None,
    expected_mount_sources: dict[str, str] | None = None,
    network_name: str = "mistrelay-dev_default",
) -> list[Check]:
    document = _docker_inspect(container_name)
    if document is None:
        return [Check("container_inspect", False, "Docker container inspection failed")]

    config = document.get("Config") or {}
    host = document.get("HostConfig") or {}
    state = document.get("State") or {}
    mounts = document.get("Mounts") or []
    environment = {
        item.split("=", 1)[0]: item.split("=", 1)[1] if "=" in item else ""
        for item in config.get("Env") or []
    }
    port_bindings = host.get("PortBindings") or {}
    web_bindings = port_bindings.get("8080/tcp") or []
    mount_destinations = {mount.get("Destination") for mount in mounts}
    health_test = ((config.get("Healthcheck") or {}).get("Test") or [])
    local_image_id = _docker_image_id(image_reference)
    source_matches = bool(
        source_root is not None and _container_source_matches(container_name, source_root)
    )
    network_document = _docker_network_inspect(network_name)
    network_ipam = ((network_document or {}).get("IPAM") or {}).get("Config") or []
    network_settings = ((document.get("NetworkSettings") or {}).get("Networks") or {})
    exact_mounts = mount_destinations == REQUIRED_MOUNTS and all(
        mount.get("Type") == "bind" and mount.get("RW") is True
        for mount in mounts
    )
    if expected_mount_sources is not None:
        exact_mounts = exact_mounts and all(
            expected_mount_sources.get(mount.get("Destination")) == mount.get("Source")
            for mount in mounts
        )
    unsafe_mount = any(
        "docker.sock" in str(mount.get(field) or "")
        or str(mount.get(field) or "").startswith("/var/run/")
        for mount in mounts
        for field in ("Source", "Destination")
    )

    return [
        _check(
            "container_stopped",
            state.get("Status") in {"created", "exited"} and not state.get("Running"),
            "container is staged but stopped",
            "container must be stopped during offline activation checks",
        ),
        _check(
            "container_image_current",
            bool(
                local_image_id
                and document.get("Image") == local_image_id
                and source_matches
            ),
            "staged container uses the current image and critical source hashes match",
            "container image/tag or critical runtime files differ from the worktree",
        ),
        _check(
            "container_identity",
            config.get("User") == "10001:10001",
            "container runs as UID/GID 10001",
            "container runtime user is not UID/GID 10001",
        ),
        _check(
            "container_privileges",
            host.get("ReadonlyRootfs") is True
            and host.get("Privileged") is False
            and "ALL" in (host.get("CapDrop") or [])
            and not (host.get("CapAdd") or [])
            and "no-new-privileges:true" in (host.get("SecurityOpt") or [])
            and host.get("Init") is True
            and host.get("PidMode") != "host"
            and host.get("IpcMode") != "host"
            and not (host.get("Devices") or [])
            and not (host.get("DeviceRequests") or []),
            "read-only rootfs, init, dropped capabilities and no-new-privileges are active",
            "one or more container privilege controls are missing",
        ),
        _check(
            "container_network",
            host.get("NetworkMode") == network_name
            and len(web_bindings) == 1
            and web_bindings[0].get("HostIp") == "127.0.0.1"
            and not any("6800" in key for key in port_bindings)
            and network_name in network_settings
            and network_document is not None
            and network_document.get("Internal") is False
            and any(
                item.get("Subnet") == "172.25.0.0/16"
                and item.get("Gateway") == "172.25.0.1"
                for item in network_ipam
            ),
            "fixed bridge, loopback-only Web and unpublished aria2 RPC are active",
            "bridge IPAM, network mode, Web bind, or aria2 RPC publishing is unsafe",
        ),
        _check(
            "container_mounts",
            exact_mounts and not unsafe_mount,
            "exact required bind mounts are writable and no runtime socket is mounted",
            "mount set/source/type differs from baseline or exposes a runtime socket",
        ),
        _check(
            "container_resources",
            0 < int(host.get("Memory") or 0) <= 2 * 1024**3
            and 0 < int(host.get("NanoCpus") or 0) <= 2_000_000_000
            and 0 < int(host.get("PidsLimit") or 0) <= 512,
            "memory, CPU and PID limits are active",
            "memory, CPU or PID limits are missing or exceed the recovery baseline",
        ),
        _check(
            "container_recovery_policy",
            (host.get("RestartPolicy") or {}).get("Name") == "no",
            "restart automation remains disabled during recovery",
            "restart automation must remain disabled until live HTTPS tests pass",
        ),
        _check(
            "container_healthcheck",
            health_test == EXPECTED_HEALTHCHECK,
            "container healthcheck uses the minimal readiness endpoint",
            "container healthcheck does not use /api/health",
        ),
        _check(
            "container_security_environment",
            environment.get("MISTRELAY_TRUSTED_PROXY_CIDRS") == "172.25.0.1/32"
            and environment.get("MISTRELAY_ALLOW_LEGACY_YAML_BOOTSTRAP", "0") != "1"
            and environment.get("MISTRELAY_ENABLE_DOCKER_CONTROL", "0") not in {
                "1", "true", "yes", "on"
            },
            "trusted proxy is exact and legacy bootstrap/Docker control are disabled",
            "trusted proxy, legacy bootstrap or Docker-control environment is unsafe",
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only activation gate for an incident-recovered MistRelay deployment."
    )
    parser.add_argument("--database", type=Path, default=Path("db/downloads.db"))
    parser.add_argument("--download-root", type=Path, default=Path("downloads"))
    parser.add_argument("--cache-root", type=Path, default=Path("cache/thumbnails"))
    parser.add_argument("--runtime-uid", type=int, default=10001)
    parser.add_argument("--runtime-gid", type=int, default=10001)
    parser.add_argument("--rotation-input-path", type=Path)
    parser.add_argument("--expected-public-origin")
    parser.add_argument("--expected-admin-id")
    parser.add_argument("--expected-channel-id")
    parser.add_argument(
        "--expected-allowed-user",
        action="append",
        default=[],
        help="repeat for every authorized numeric Telegram user ID",
    )
    parser.add_argument(
        "--staged-only",
        action="store_true",
        help="check structure without claiming public activation readiness",
    )
    parser.add_argument("--container", default="mistrelay")
    parser.add_argument("--image", default="mistrelay-dev-mistrelay:latest")
    parser.add_argument("--network", default="mistrelay-dev_default")
    parser.add_argument("--skip-container", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    arguments = parser.parse_args()

    if not arguments.staged_only:
        missing_expectations = [
            name for name, value in (
                ("--expected-public-origin", arguments.expected_public_origin),
                ("--expected-admin-id", arguments.expected_admin_id),
                ("--expected-channel-id", arguments.expected_channel_id),
                ("--expected-allowed-user", arguments.expected_allowed_user),
                ("--rotation-input-path", arguments.rotation_input_path),
            )
            if not value
        ]
        if missing_expectations:
            parser.error(
                "public activation requires exact expectations: "
                + ", ".join(missing_expectations)
            )
        if arguments.skip_container:
            parser.error("public activation cannot skip container inspection")

    checks = evaluate_filesystem(
        arguments.database,
        arguments.download_root,
        arguments.cache_root,
        arguments.runtime_uid,
        arguments.runtime_gid,
        arguments.rotation_input_path,
    )
    checks.extend(evaluate_database(
        arguments.database,
        arguments.expected_public_origin,
        arguments.expected_admin_id,
        arguments.expected_channel_id,
        arguments.expected_allowed_user or None,
    ))
    if not arguments.skip_container:
        checks.extend(evaluate_container(
            arguments.container,
            arguments.image,
            source_root=Path(__file__).resolve().parent,
            expected_mount_sources={
                "/app/db": str(arguments.database.parent.resolve()),
                "/data/downloads": str(arguments.download_root.resolve()),
                "/app/cache/thumbnails": str(arguments.cache_root.resolve()),
            },
            network_name=arguments.network,
        ))

    ready = bool(checks) and all(item.ok for item in checks)
    if arguments.json_output:
        print(json.dumps(
            {
                "mode": "staged" if arguments.staged_only else "public_activation",
                "ready": ready,
                "checks": [asdict(item) for item in checks],
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ))
    else:
        for item in checks:
            print(f"[{'PASS' if item.ok else 'FAIL'}] {item.name}: {item.detail}")
        label = "staged_ready" if arguments.staged_only else "activation_ready"
        print(f"{label}={str(ready).lower()}")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
