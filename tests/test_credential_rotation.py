import tests  # noqa: F401
import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from auth import hash_password, verify_password
from legacy_config import LegacyConfigError
from rotate_credentials import RotationError, load_and_validate, rotate_database


class CredentialRotationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database = self.root / "downloads.db"
        with sqlite3.connect(self.database) as connection:
            connection.executescript(
                """
                CREATE TABLE config_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    value_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT INTO config_settings VALUES (?, ?, ?, ?, ?, ?)",
                ("API_ID", "87654321", "int", "telegram", "", "old"),
            )
            connection.execute(
                "INSERT INTO config_settings VALUES (?, ?, ?, ?, ?, ?)",
                ("API_HASH", "ffffffffffffffffffffffffffffffff", "string", "telegram", "", "old"),
            )
            connection.execute(
                "INSERT INTO config_settings VALUES (?, ?, ?, ?, ?, ?)",
                ("BOT_TOKEN", "111111:oldoldoldoldoldoldoldoldoldold", "string", "telegram", "", "old"),
            )
            connection.execute(
                "INSERT INTO config_settings VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "MULTI_BOT_TOKENS",
                    '["222222:oldoldoldoldoldoldoldoldoldold"]',
                    "list",
                    "stream",
                    "",
                    "old",
                ),
            )
            connection.execute(
                "INSERT INTO config_settings VALUES (?, ?, ?, ?, ?, ?)",
                ("RPC_SECRET", "old-secret", "string", "aria2", "", "old"),
            )
            connection.execute(
                "INSERT INTO config_settings VALUES (?, ?, ?, ?, ?, ?)",
                ("FORWARD_ID", "-1001998444696", "string", "telegram", "", "old"),
            )
            connection.execute(
                "INSERT INTO config_settings VALUES (?, ?, ?, ?, ?, ?)",
                ("RCLONE_REMOTE", "legacy:remote", "string", "rclone", "", "old"),
            )
            connection.execute(
                "INSERT INTO users (username, password_hash, role, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("admin", hash_password("old-test-password-123"), "admin", "old", "old"),
            )

        self.legacy_config = self.root / "config.yml"
        self.legacy_config.write_text(
            yaml.safe_dump(
                {
                    "API_HASH": "exposed-api-hash",
                    "BOT_TOKEN": "111111:oldoldoldoldoldoldoldoldoldold",
                    "RPC_SECRET": "old-secret",
                    "BIN_CHANNEL": "-1001998444696",
                    "FORWARD_ID": "-1001998444696",
                }
            ),
            encoding="utf-8",
        )
        self.legacy_config.chmod(0o600)

        self.values = {
            "API_ID": 12345678,
            "API_HASH": "0123456789abcdef0123456789abcdef",
            "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
            "ADMIN_ID": 123456789,
            "BIN_CHANNEL": "-1001234567890",
            "STREAM_ALLOWED_USERS": [123456789, 987654321],
            "RPC_SECRET": "0123456789abcdefABCDEFGHIJKLMNOPQRSTUVWXYZ_-ghijklmnop",
            "MULTI_BOT_TOKENS": [],
            "ADMIN_PASSWORD": "new-test-password-456",
            "PUBLIC_BASE_URL": "https://files.example.test",
            "SEND_STREAM_LINK": True,
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_input(self, mode=0o600) -> Path:
        path = self.root / "credentials.yml"
        path.write_text(yaml.safe_dump(self.values), encoding="utf-8")
        path.chmod(mode)
        return path

    def test_protected_input_is_normalized(self):
        values = load_and_validate(self._write_input())
        self.assertEqual(values["STREAM_ALLOWED_USERS"], "123456789,987654321")
        self.assertEqual(values["ADMIN_ID"], 123456789)
        self.assertEqual(values["STREAM_FQDN"], "files.example.test")
        self.assertTrue(values["STREAM_HAS_SSL"])

    def test_api_id_historical_fingerprint_is_allowed(self):
        fingerprint = hashlib.sha256(
            str(self.values["API_ID"]).encode("utf-8")
        ).hexdigest()
        with patch.dict(
            "security_validation.PRESERVED_COMPROMISED_VALUE_HASHES",
            {"API_ID": frozenset({fingerprint})},
        ):
            values = load_and_validate(self._write_input())
        self.assertEqual(values["API_ID"], self.values["API_ID"])

    def test_preserved_compromised_fingerprint_is_rejected(self):
        fingerprint = hashlib.sha256(
            self.values["API_HASH"].encode("utf-8")
        ).hexdigest()
        with patch.dict(
            "security_validation.PRESERVED_COMPROMISED_VALUE_HASHES",
            {"API_HASH": frozenset({fingerprint})},
        ):
            with self.assertRaisesRegex(RotationError, "preserved compromised fingerprint"):
                load_and_validate(self._write_input())

    def test_group_readable_input_is_rejected(self):
        with self.assertRaisesRegex(RotationError, "0600"):
            load_and_validate(self._write_input(mode=0o640))

    def test_admin_must_be_in_allowlist(self):
        self.values["STREAM_ALLOWED_USERS"] = [987654321]
        with self.assertRaisesRegex(RotationError, "ADMIN_ID"):
            load_and_validate(self._write_input())

    def test_public_url_must_be_a_standard_https_origin(self):
        self.values["PUBLIC_BASE_URL"] = "http://files.example.test/path"
        with self.assertRaisesRegex(RotationError, "HTTPS origin"):
            load_and_validate(self._write_input())

    def test_links_cannot_be_sent_without_a_public_origin(self):
        self.values["PUBLIC_BASE_URL"] = ""
        with self.assertRaisesRegex(RotationError, "SEND_STREAM_LINK"):
            load_and_validate(self._write_input())

    def test_rotation_is_atomic_and_revokes_sessions(self):
        values = load_and_validate(self._write_input())
        result = rotate_database(self.database, values, self.legacy_config)
        self.assertEqual(
            result,
            {
                "updated_settings": 25,
                "removed_legacy_settings": 2,
                "revoked_sessions": 0,
                "retired_legacy_config": 1,
                "already_applied": 0,
            },
        )

        with sqlite3.connect(self.database) as connection:
            config = dict(connection.execute("SELECT key, value FROM config_settings"))
            password_hash = connection.execute(
                "SELECT password_hash FROM users WHERE username = 'admin'"
            ).fetchone()[0]
            auth_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(auth_sessions)")
            }
        self.assertEqual(config["BOT_TOKEN"], values["BOT_TOKEN"])
        self.assertEqual(config["STREAM_USE_SESSION_FILE"], "false")
        self.assertTrue(verify_password(values["ADMIN_PASSWORD"], password_hash))
        self.assertIn("revoked_reason", auth_columns)
        self.assertEqual(config["SECURITY_BASELINE_VERSION"], "2")
        self.assertEqual(config["RPC_URL"], "localhost:6800/jsonrpc")
        self.assertEqual(config["PROXY_IP"], "")
        self.assertEqual(config["STREAM_HASH_LENGTH"], "32")
        self.assertEqual(config["STREAM_FQDN"], "files.example.test")
        self.assertEqual(config["STREAM_HAS_SSL"], "true")
        self.assertEqual(config["STREAM_NO_PORT"], "true")
        self.assertEqual(config["SEND_STREAM_LINK"], "true")
        self.assertNotIn("FORWARD_ID", config)
        self.assertNotIn("RCLONE_REMOTE", config)
        self.assertEqual(yaml.safe_load(self.legacy_config.read_text(encoding="utf-8")), {})

    def test_reused_exposed_secret_rolls_back_everything(self):
        values = load_and_validate(self._write_input())
        values["BOT_TOKEN"] = "111111:oldoldoldoldoldoldoldoldoldold"
        with self.assertRaisesRegex(RotationError, "BOT_TOKEN"):
            rotate_database(self.database, values, self.legacy_config)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT value FROM config_settings WHERE key = 'BOT_TOKEN'"
                ).fetchone()[0],
                values["BOT_TOKEN"],
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'auth_sessions'"
                ).fetchone()
            )
            self.assertEqual(
                connection.execute(
                    "SELECT value FROM config_settings WHERE key = 'FORWARD_ID'"
                ).fetchone()[0],
                "-1001998444696",
            )
        self.assertIn("FORWARD_ID", self.legacy_config.read_text(encoding="utf-8"))

    def test_all_exposed_telegram_credentials_must_change(self):
        cases = (
            ("API_ID", 87654321, "API_ID"),
            ("API_HASH", "ffffffffffffffffffffffffffffffff", "API_HASH"),
            (
                "MULTI_BOT_TOKENS",
                ["222222:oldoldoldoldoldoldoldoldoldold"],
                "MULTI_BOT_TOKENS",
            ),
        )
        for key, exposed_value, error in cases:
            with self.subTest(key=key):
                values = load_and_validate(self._write_input())
                values[key] = exposed_value
                with self.assertRaisesRegex(RotationError, error):
                    rotate_database(self.database, values, self.legacy_config)

        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT value FROM config_settings WHERE key = 'API_HASH'"
                ).fetchone()[0],
                "ffffffffffffffffffffffffffffffff",
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'auth_sessions'"
                ).fetchone()
            )

    def test_cleanup_failure_can_retry_without_rotating_again(self):
        values = load_and_validate(self._write_input())
        with patch(
            "rotate_credentials.retire_legacy_config",
            side_effect=LegacyConfigError("test cleanup denial"),
        ):
            with self.assertRaisesRegex(RotationError, "committed.*rerun"):
                rotate_database(self.database, values, self.legacy_config)

        with sqlite3.connect(self.database) as connection:
            config = dict(connection.execute("SELECT key, value FROM config_settings"))
            password_hash = connection.execute(
                "SELECT password_hash FROM users WHERE username = 'admin'"
            ).fetchone()[0]
        self.assertEqual(config["BOT_TOKEN"], values["BOT_TOKEN"])
        self.assertNotIn("FORWARD_ID", config)
        self.assertTrue(verify_password(values["ADMIN_PASSWORD"], password_hash))
        self.assertIn("FORWARD_ID", self.legacy_config.read_text(encoding="utf-8"))

        result = rotate_database(self.database, values, self.legacy_config)
        self.assertEqual(
            result,
            {
                "updated_settings": 0,
                "removed_legacy_settings": 0,
                "revoked_sessions": 0,
                "retired_legacy_config": 1,
                "already_applied": 1,
            },
        )
        self.assertEqual(yaml.safe_load(self.legacy_config.read_text(encoding="utf-8")), {})


if __name__ == "__main__":
    unittest.main()
