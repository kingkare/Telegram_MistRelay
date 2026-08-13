import os
import sqlite3
import tempfile
import unittest

os.environ["MISTRELAY_DB_PATH"] = tempfile.mktemp(
    prefix="mistrelay_auth_tests_import_",
    suffix=".db",
    dir="/tmp",
)

import auth
import db


class AuthSessionTests(unittest.TestCase):
    def setUp(self):
        self.db_path = tempfile.mktemp(
            prefix="mistrelay_auth_tests_",
            suffix=".db",
            dir="/tmp",
        )
        db.DB_PATH = self.db_path
        db.init_db()
        with db.db_conn() as connection:
            connection.executemany(
                """
                INSERT INTO users
                    (id, username, password_hash, role, created_at, updated_at)
                VALUES (?, ?, ?, 'admin', 'test', 'test')
                """,
                [
                    (1, "test-user-1", "unused-test-hash"),
                    (2, "test-user-2", "unused-test-hash"),
                ],
            )

    def test_schema_is_idempotent_and_indexed(self):
        db.init_db()

        with sqlite3.connect(self.db_path) as conn:
            columns = [
                row[1]
                for row in conn.execute("PRAGMA table_info(auth_sessions)").fetchall()
            ]
            indexes = {
                row[1]: bool(row[2])
                for row in conn.execute("PRAGMA index_list(auth_sessions)").fetchall()
            }

        self.assertEqual(
            columns,
            [
                "id",
                "user_id",
                "token_hash",
                "device_id",
                "session_name",
                "expires_at",
                "revoked_at",
                "revoked_reason",
                "replaced_by",
                "created_at",
                "last_used_at",
            ],
        )
        self.assertTrue(indexes["idx_auth_sessions_token_hash"])
        self.assertFalse(indexes["idx_auth_sessions_user_id"])

    def test_login_session_stores_only_refresh_token_hash(self):
        refresh_token = auth.create_refresh_token()
        token_hash = auth.hash_refresh_token(refresh_token)

        session = db.create_auth_session(
            1,
            token_hash,
            auth.get_refresh_token_expires_at(),
            device_id="pc-1",
            session_name="Desktop",
        )

        self.assertNotEqual(refresh_token, token_hash)
        self.assertEqual(len(token_hash), 64)
        self.assertEqual(session["token_hash"], token_hash)
        self.assertIsNone(db.get_auth_session(refresh_token))
        self.assertEqual(db.get_auth_session(token_hash)["device_id"], "pc-1")

    def test_refresh_rotation_blocks_replay(self):
        old_hash = auth.hash_refresh_token("old-refresh")
        new_hash = auth.hash_refresh_token("new-refresh")
        db.create_auth_session(1, old_hash, "2999-01-01T00:00:00Z")

        new_session = db.rotate_auth_session(
            old_hash,
            new_hash,
            "2999-01-01T00:00:00Z",
        )

        self.assertIsNotNone(new_session)
        self.assertEqual(db.get_auth_session(new_hash)["id"], new_session["id"])
        self.assertIsNone(db.get_auth_session(old_hash))
        old_session = db.get_auth_session(old_hash, include_revoked=True, touch=False)
        self.assertEqual(old_session["revoked_reason"], "rotated")
        self.assertEqual(old_session["replaced_by"], new_session["id"])
        self.assertIsNone(
            db.rotate_auth_session(
                old_hash,
                auth.hash_refresh_token("replay-refresh"),
                "2999-01-01T00:00:00Z",
            )
        )

    def test_logout_revokes_refresh_session(self):
        token_hash = auth.hash_refresh_token("logout-refresh")
        db.create_auth_session(1, token_hash, "2999-01-01T00:00:00Z")

        self.assertTrue(db.revoke_auth_session(token_hash, reason="logout"))

        self.assertIsNone(db.get_auth_session(token_hash))
        revoked = db.get_auth_session(token_hash, include_revoked=True, touch=False)
        self.assertEqual(revoked["revoked_reason"], "logout")
        self.assertIsNone(
            db.rotate_auth_session(
                token_hash,
                auth.hash_refresh_token("after-logout"),
                "2999-01-01T00:00:00Z",
            )
        )

    def test_password_change_revokes_user_sessions(self):
        db.create_auth_session(1, "user-1-a", "2999-01-01T00:00:00Z")
        db.create_auth_session(1, "user-1-b", "2999-01-01T00:00:00Z")
        db.create_auth_session(2, "user-2-a", "2999-01-01T00:00:00Z")

        revoked_count = db.revoke_user_sessions(1, reason="password_changed")

        self.assertEqual(revoked_count, 2)
        self.assertIsNone(db.get_auth_session("user-1-a"))
        self.assertIsNone(db.get_auth_session("user-1-b"))
        self.assertIsNotNone(db.get_auth_session("user-2-a"))
        revoked = db.get_auth_session("user-1-a", include_revoked=True, touch=False)
        self.assertEqual(revoked["revoked_reason"], "password_changed")

    def test_cleanup_expired_auth_sessions(self):
        db.create_auth_session(1, "expired", "2000-01-01T00:00:00Z")
        db.create_auth_session(1, "active", "2999-01-01T00:00:00Z")

        deleted_count = db.cleanup_expired_auth_sessions()

        self.assertEqual(deleted_count, 1)
        self.assertIsNone(db.get_auth_session("expired", include_revoked=True))
        self.assertIsNotNone(db.get_auth_session("active"))


if __name__ == "__main__":
    unittest.main()
