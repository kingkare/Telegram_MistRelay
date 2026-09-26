import tests  # noqa: F401
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from auth import verify_password


class InitialAdminTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "downloads.db"
        self.db_path_patch = patch.object(db, "DB_PATH", str(self.db_path))
        self.db_path_patch.start()
        db.init_db()

    def tearDown(self):
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_missing_initial_password_fails_closed(self):
        missing = Path(self.temp_dir.name) / "missing-password"
        with patch.dict(
            os.environ,
            {"MISTRELAY_ADMIN_PASSWORD_FILE": str(missing)},
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                db.ensure_default_admin()

    def test_short_initial_password_is_rejected(self):
        password_file = Path(self.temp_dir.name) / "admin-password"
        password_file.write_text("too-short", encoding="utf-8")
        password_file.chmod(0o600)
        with patch.dict(
            os.environ,
            {"MISTRELAY_ADMIN_PASSWORD_FILE": str(password_file)},
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                db.ensure_default_admin()

    def test_group_readable_initial_password_is_rejected(self):
        password_file = Path(self.temp_dir.name) / "admin-password"
        password_file.write_text("test-only-strong-admin-password", encoding="utf-8")
        password_file.chmod(0o640)
        with patch.dict(
            os.environ,
            {"MISTRELAY_ADMIN_PASSWORD_FILE": str(password_file)},
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                db.ensure_default_admin()

    def test_strong_password_file_creates_hashed_admin(self):
        password = "test-only-strong-admin-password"
        password_file = Path(self.temp_dir.name) / "admin-password"
        password_file.write_text(password, encoding="utf-8")
        password_file.chmod(0o600)
        with patch.dict(
            os.environ,
            {"MISTRELAY_ADMIN_PASSWORD_FILE": str(password_file)},
            clear=False,
        ):
            db.ensure_default_admin()

        with sqlite3.connect(self.db_path) as conn:
            username, password_hash = conn.execute(
                "SELECT username, password_hash FROM users"
            ).fetchone()
            baseline = conn.execute(
                "SELECT value FROM config_settings WHERE key = 'SECURITY_BASELINE_VERSION'"
            ).fetchone()[0]
        self.assertEqual(username, "admin")
        self.assertNotEqual(password_hash, password)
        self.assertTrue(verify_password(password, password_hash))
        self.assertEqual(baseline, "2")


if __name__ == "__main__":
    unittest.main()
