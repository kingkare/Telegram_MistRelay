import tests  # noqa: F401
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


class DatabaseIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "downloads.db"
        self.db_path_patch = patch.object(db, "DB_PATH", str(self.database))
        self.db_path_patch.start()
        db.init_db()

    def tearDown(self):
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_application_connections_enforce_foreign_keys(self):
        with db.get_connection() as connection:
            enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        self.assertEqual(enabled, 1)

    def test_initialization_repairs_legacy_channel_file_orphans(self):
        with sqlite3.connect(self.database) as connection:
            connection.executescript(
                """
                CREATE TABLE tg_channel_files (
                    id INTEGER PRIMARY KEY,
                    file_unique_id TEXT,
                    FOREIGN KEY (file_unique_id)
                        REFERENCES tg_media(file_unique_id) ON DELETE SET NULL
                );
                INSERT INTO tg_channel_files (id, file_unique_id)
                VALUES (1, 'missing-parent');
                """
            )
            self.assertEqual(len(connection.execute("PRAGMA foreign_key_check").fetchall()), 1)

        db.init_db()

        with sqlite3.connect(self.database) as connection:
            file_unique_id = connection.execute(
                "SELECT file_unique_id FROM tg_channel_files WHERE id = 1"
            ).fetchone()[0]
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        self.assertIsNone(file_unique_id)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
