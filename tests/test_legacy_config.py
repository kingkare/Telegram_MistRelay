import tests  # noqa: F401
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import db
from legacy_config import (
    LEGACY_BOOTSTRAP_ENV,
    LegacyConfigError,
    load_legacy_config,
    retire_legacy_config,
)


class LegacyConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database = self.root / "downloads.db"
        self.config = self.root / "config.yml"
        self.config.write_text(
            yaml.safe_dump(
                {
                    "API_ID": 12345678,
                    "API_HASH": "0123456789abcdef0123456789abcdef",
                    "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
                    "RPC_SECRET": "0123456789abcdefABCDEFGHIJKLMNOPQRSTUVWXYZ_-ghijklmnop",
                }
            ),
            encoding="utf-8",
        )
        self.config.chmod(0o600)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_loading_requires_exact_explicit_opt_in(self):
        for value in ("", "0", "true", "yes", "2"):
            with self.subTest(value=value), patch.dict(
                os.environ, {LEGACY_BOOTSTRAP_ENV: value}, clear=False
            ):
                with self.assertRaisesRegex(LegacyConfigError, "explicitly enabled"):
                    load_legacy_config(self.config)

        with patch.dict(os.environ, {LEGACY_BOOTSTRAP_ENV: "1"}, clear=False):
            self.assertEqual(load_legacy_config(self.config)["API_ID"], 12345678)

    def test_group_readable_bootstrap_file_is_rejected(self):
        self.config.chmod(0o640)
        with patch.dict(os.environ, {LEGACY_BOOTSTRAP_ENV: "1"}, clear=False):
            with self.assertRaisesRegex(LegacyConfigError, "0600"):
                load_legacy_config(self.config)

    def test_database_initialization_does_not_fallback_by_default(self):
        with patch.object(db, "DB_PATH", str(self.database)), patch.dict(
            os.environ, {LEGACY_BOOTSTRAP_ENV: "0"}, clear=False
        ):
            db.init_db()
        with sqlite3.connect(self.database) as connection:
            count = connection.execute("SELECT COUNT(*) FROM config_settings").fetchone()[0]
        self.assertEqual(count, 0)
        self.assertIn("BOT_TOKEN", self.config.read_text(encoding="utf-8"))

    def test_explicit_database_bootstrap_imports_and_retires_yaml(self):
        with patch.object(db, "DB_PATH", str(self.database)), patch.dict(
            os.environ, {LEGACY_BOOTSTRAP_ENV: "1"}, clear=False
        ):
            db.init_db()
        with sqlite3.connect(self.database) as connection:
            token = connection.execute(
                "SELECT value FROM config_settings WHERE key = 'BOT_TOKEN'"
            ).fetchone()[0]
        self.assertTrue(token.startswith("123456789:"))
        self.assertEqual(yaml.safe_load(self.config.read_text(encoding="utf-8")), {})
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_retirement_failure_leaves_verified_import_for_cleanup_retry(self):
        with patch.object(db, "DB_PATH", str(self.database)), patch.dict(
            os.environ, {LEGACY_BOOTSTRAP_ENV: "1"}, clear=False
        ), patch.object(db, "retire_legacy_config", side_effect=LegacyConfigError("denied")):
            with self.assertRaisesRegex(RuntimeError, "安全退休失败"):
                db.init_db()

        with sqlite3.connect(self.database) as connection:
            count = connection.execute("SELECT COUNT(*) FROM config_settings").fetchone()[0]
        self.assertGreater(count, 0)
        self.assertIn("BOT_TOKEN", self.config.read_text(encoding="utf-8"))

        with patch.object(db, "DB_PATH", str(self.database)), patch.dict(
            os.environ, {LEGACY_BOOTSTRAP_ENV: "1"}, clear=False
        ):
            db.init_db()
        with sqlite3.connect(self.database) as connection:
            count = connection.execute("SELECT COUNT(*) FROM config_settings").fetchone()[0]
        self.assertGreater(count, 0)
        self.assertEqual(yaml.safe_load(self.config.read_text(encoding="utf-8")), {})

    def test_retirement_refuses_symbolic_links(self):
        target = self.root / "target.yml"
        target.write_text("BOT_TOKEN: still-present\n", encoding="utf-8")
        link = self.root / "linked-config.yml"
        link.symlink_to(target)
        with self.assertRaisesRegex(LegacyConfigError, "non-regular"):
            retire_legacy_config(link)
        self.assertIn("still-present", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
