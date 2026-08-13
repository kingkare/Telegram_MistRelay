#!/bin/sh
set -eu

CONFIG_DIR="/app/aria2"
CONFIG_FILE="$CONFIG_DIR/aria2.conf"
mkdir -p "$CONFIG_DIR"
umask 077

case "${MISTRELAY_ALLOW_LEGACY_YAML_BOOTSTRAP:-0}" in
    0|1) ;;
    *)
        echo "拒绝启动: MISTRELAY_ALLOW_LEGACY_YAML_BOOTSTRAP 只能显式设为 0 或 1" >&2
        exit 1
        ;;
esac

RPC_SECRET=$(python3 - <<'PY'
import sqlite3
from pathlib import Path

from legacy_config import (
    legacy_config_path,
    legacy_yaml_bootstrap_enabled,
    load_legacy_config,
)

value = ""
db_path = Path("/app/db/downloads.db")
if db_path.is_file():
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT value FROM config_settings WHERE key = 'RPC_SECRET'"
            ).fetchone()
            if row:
                value = str(row[0] or "")
    except Exception:
        pass

if not value and legacy_yaml_bootstrap_enabled():
    try:
        config = load_legacy_config(legacy_config_path(db_path))
        value = str(config.get("RPC_SECRET") or "")
    except Exception:
        value = ""

print(value)
PY
)

RPC_SECRET_STATE=$(RPC_SECRET_VALUE="$RPC_SECRET" python3 - <<'PY'
import os

from security_validation import (
    credential_matches_preserved_fingerprint,
    is_valid_rpc_secret,
)

secret = os.environ.get("RPC_SECRET_VALUE")
valid = (
    is_valid_rpc_secret(secret)
    and not credential_matches_preserved_fingerprint(secret, "RPC_SECRET")
)
print("ready" if valid else "blocked")
PY
)

if [ "$RPC_SECRET_STATE" != "ready" ]; then
    echo "拒绝启动: RPC_SECRET 必须是 32-256 位高熵 URL-safe 随机字符串" >&2
    exit 1
fi

CREDENTIAL_STATE=$(python3 - <<'PY'
import json
import sqlite3
from pathlib import Path

from security_validation import (
    BOT_TOKEN_PATTERN,
    are_valid_telegram_credentials,
    contains_preserved_compromised_credentials,
)
from legacy_config import (
    legacy_config_path,
    legacy_yaml_bootstrap_enabled,
    load_legacy_config,
)

required_keys = (
    "API_ID", "API_HASH", "BOT_TOKEN", "STREAM_ALLOWED_USERS", "MULTI_BOT_TOKENS"
)
values = {}
db_path = Path("/app/db/downloads.db")
if db_path.is_file():
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT key, value FROM config_settings WHERE key IN (?, ?, ?, ?, ?)",
                required_keys,
            ).fetchall()
            values = {key: str(value or "").strip() for key, value in rows}
    except Exception:
        values = {}

if not values and legacy_yaml_bootstrap_enabled():
    try:
        config = load_legacy_config(legacy_config_path(db_path))
        values = {key: config.get(key) for key in required_keys}
    except Exception:
        values = {}

try:
    multi_tokens = json.loads(values.get("MULTI_BOT_TOKENS", "[]"))
except (json.JSONDecodeError, TypeError):
    multi_tokens = None
primary_token = str(values.get("BOT_TOKEN") or "").strip()
multi_valid = (
    isinstance(multi_tokens, list)
    and all(
        isinstance(token, str) and BOT_TOKEN_PATTERN.fullmatch(token.strip())
        for token in multi_tokens
    )
)
normalized_multi = [token.strip() for token in multi_tokens] if multi_valid else []
multi_valid = (
    multi_valid
    and len(normalized_multi) == len(set(normalized_multi))
    and primary_token not in normalized_multi
)
valid = multi_valid and are_valid_telegram_credentials(
    values.get("API_ID"),
    values.get("API_HASH"),
    primary_token,
    values.get("STREAM_ALLOWED_USERS"),
)
valid = valid and not contains_preserved_compromised_credentials(
    api_id=values.get("API_ID"),
    api_hash=values.get("API_HASH"),
    bot_tokens=[primary_token, *normalized_multi],
)
print("ready" if valid else "blocked")
PY
)

if [ "$CREDENTIAL_STATE" != "ready" ]; then
    echo "拒绝启动: Telegram API_ID/API_HASH/Bot Token 或数字 STREAM_ALLOWED_USERS 尚未安全配置" >&2
    exit 1
fi

ADMIN_STATE=$(python3 - <<'PY'
import os
import sqlite3
import stat
from pathlib import Path

from legacy_config import legacy_yaml_bootstrap_enabled

db_path = Path("/app/db/downloads.db")
has_admin = False
if db_path.is_file():
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            has_admin = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
    except Exception:
        has_admin = False

if has_admin:
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT value FROM config_settings WHERE key = 'SECURITY_BASELINE_VERSION'"
            ).fetchone()
        print("ready" if row and str(row[0]) == "2" else "blocked")
    except Exception:
        print("blocked")
    raise SystemExit

if not legacy_yaml_bootstrap_enabled():
    print("blocked")
    raise SystemExit

password_path = Path(
    os.environ.get("MISTRELAY_ADMIN_PASSWORD_FILE", "/app/db/admin-password")
)
try:
    password_stat = password_path.stat(follow_symlinks=False)
except OSError:
    print("blocked")
    raise SystemExit

valid = (
    stat.S_ISREG(password_stat.st_mode)
    and password_stat.st_uid == os.geteuid()
    and stat.S_IMODE(password_stat.st_mode) & 0o077 == 0
)
if valid:
    try:
        password = password_path.read_text(encoding="utf-8").strip()
        valid = 16 <= len(password) <= 512
    except (OSError, UnicodeError):
        valid = False
print("ready" if valid else "blocked")
PY
)

if [ "$ADMIN_STATE" != "ready" ]; then
    echo "拒绝启动: 管理员安全基线未完成，或首次管理员密码文件不安全" >&2
    exit 1
fi

tmp_config="$CONFIG_FILE.tmp"
cat > "$tmp_config" <<EOF
# Basic settings
dir=/data/downloads
disable-ipv6=false
enable-rpc=true
rpc-allow-origin-all=false
rpc-listen-all=false
rpc-listen-port=6800

# Connection settings
max-concurrent-downloads=5
continue=true
max-connection-per-server=10
min-split-size=10M
split=10
max-overall-download-limit=0
max-download-limit=0
max-overall-upload-limit=0
max-upload-limit=0
lowest-speed-limit=0
timeout=60
max-tries=5
retry-wait=0

# RPC settings
rpc-max-request-size=10M
rpc-secret=${RPC_SECRET}
EOF
chmod 0600 "$tmp_config"
mv -f "$tmp_config" "$CONFIG_FILE"

aria2c --conf-path="$CONFIG_FILE" &
aria2_pid=$!
python3 -u app.py &
app_pid=$!

terminate() {
    kill -TERM "$app_pid" "$aria2_pid" 2>/dev/null || true
    wait "$app_pid" 2>/dev/null || true
    wait "$aria2_pid" 2>/dev/null || true
}

trap terminate INT TERM EXIT
status=0
while :; do
    if ! kill -0 "$aria2_pid" 2>/dev/null; then
        echo "aria2 exited unexpectedly; stopping MistRelay" >&2
        status=1
        break
    fi
    if ! kill -0 "$app_pid" 2>/dev/null; then
        if wait "$app_pid"; then
            status=0
        else
            status=$?
        fi
        break
    fi
    sleep 1
done
trap - INT TERM EXIT
terminate
exit "$status"
