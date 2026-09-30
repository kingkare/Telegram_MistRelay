import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import db
import backup_manager


class BackupAndRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_db_path = db.DB_PATH
        self.orig_sess_env = os.environ.get("MISTRELAY_SESSION_DIR")

        self.db_dir = Path(self.temp_dir.name) / "db"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir = self.db_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        # Create dummy session file and jwt key
        (self.sessions_dir / "acc_12345.session").write_bytes(b"SQLite format 3\x00dummy_session_data")
        (self.db_dir / "jwt_signing.key").write_text("dummy_jwt_secret_key", encoding="utf-8")

        db.DB_PATH = str(self.db_dir / "downloads.db")
        os.environ["MISTRELAY_SESSION_DIR"] = str(self.sessions_dir)
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        if self.orig_sess_env is None:
            os.environ.pop("MISTRELAY_SESSION_DIR", None)
        else:
            os.environ["MISTRELAY_SESSION_DIR"] = self.orig_sess_env
        self.temp_dir.cleanup()

    def test_create_list_and_restore_full_backup(self):
        # 1. Insert initial tenant & media record
        db.create_tenant_user(
            username="tenant_alpha",
            password_hash="hash_alpha",
            role="user",
            tg_user_id=880001,
            dc_id=5,
            bin_channel_id=-1005550001,
            bin_channel_username="mr_alpha_chan",
        )
        msg = SimpleNamespace(
            id=101,
            chat=SimpleNamespace(id=-1005550001),
            video=SimpleNamespace(
                file_unique_id="uniq_backup_1",
                file_id="fid_backup_1",
                file_name="alpha_video.mp4",
                mime_type="video/mp4",
                file_size=10485760,
            ),
            date="2026-09-28T00:00:00",
        )
        db.save_tg_media(msg)

        # 2. Create online backup
        res = backup_manager.create_backup(remark="before_mutation")
        self.assertTrue(res["filename"].endswith(".tar.gz"))
        self.assertGreater(res["size"], 0)
        self.assertEqual(res["manifest"]["remark"], "before_mutation")
        self.assertEqual(res["manifest"]["sessions_count"], 1)
        self.assertGreaterEqual(res["manifest"]["db_tables"]["tg_media"], 1)

        backups = backup_manager.list_backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0]["filename"], res["filename"])

        # 3. Mutate database & sessions after backup
        db.create_tenant_user(username="temp_intruder", password_hash="hash_2", role="user")
        (self.sessions_dir / "acc_12345.session").unlink()
        self.assertIsNotNone(db.get_user_by_username("temp_intruder"))
        self.assertFalse((self.sessions_dir / "acc_12345.session").exists())

        # 4. Restore from backup with overwrite mode
        restore_res = backup_manager.restore_backup(res["filename"], mode="overwrite")
        self.assertTrue(restore_res["safety_snapshot"].startswith("safety_pre_restore_"))

        # Verify database and session file are restored to snapshot point
        self.assertIsNone(db.get_user_by_username("temp_intruder"))
        restored_u1 = db.get_user_by_username("tenant_alpha")
        self.assertIsNotNone(restored_u1)
        self.assertEqual(restored_u1["bin_channel_id"], -1005550001)
        self.assertTrue((self.sessions_dir / "acc_12345.session").exists())

        # Verify safety snapshot was added to backup list
        backups_after = backup_manager.list_backups()
        self.assertEqual(len(backups_after), 2)
        self.assertTrue(any(b["is_safety_snapshot"] for b in backups_after))

    def test_schedule_and_delete_backup(self):
        sched = backup_manager.set_backup_schedule(enabled=True, interval_hours=12, max_keep=10)
        self.assertTrue(sched["enabled"])
        self.assertEqual(sched["interval_hours"], 12)
        self.assertEqual(sched["max_keep"], 10)

        res = backup_manager.create_backup(remark="to_be_deleted")
        fpath = backup_manager.get_backup_filepath(res["filename"])
        self.assertIsNotNone(fpath)

        deleted = backup_manager.delete_backup(res["filename"])
        self.assertTrue(deleted)
        self.assertIsNone(backup_manager.get_backup_filepath(res["filename"]))



    def test_protected_backup_deletion_is_blocked(self):
        """验证受保护的灾难恢复基线与安全快照绝对禁止删除"""
        self.assertTrue(backup_manager.is_protected_backup("backup_mistrelay_20260928_125911.tar.gz"))
        self.assertTrue(backup_manager.is_protected_backup("safety_pre_restore_20260929_120000.tar.gz"))
        self.assertTrue(backup_manager.is_protected_backup("safety_before_media_restore_1790695668.db"))
        self.assertTrue(backup_manager.is_protected_backup("golden_baseline_archive.tar.gz"))

        with self.assertRaises(PermissionError):
            backup_manager.delete_backup("backup_mistrelay_20260928_125911.tar.gz")



    def test_union_restore_safety_and_channel_merging(self):
        """验证非破坏性并集还原 (mode=union)：新租户与新媒体100%保留，旧频道安全并入"""
        u1 = db.create_tenant_user(
            username="tenant_first",
            password_hash="pw1",
            role="user",
            bin_channel_id=-1001111,
        )
        msg1 = SimpleNamespace(
            id=201,
            chat=SimpleNamespace(id=-1001111),
            video=SimpleNamespace(
                file_unique_id="fuid_first_1",
                file_id="fid_1",
                file_name="first_video.mp4",
                mime_type="video/mp4",
                file_size=50000,
            ),
            date="2026-09-28T00:00:00",
        )
        db.save_tg_media(msg1)
        bak_res = backup_manager.create_backup(remark="union_test_baseline")

        u2 = db.create_tenant_user(
            username="tenant_second",
            password_hash="pw2",
            role="user",
            bin_channel_id=-1002222,
        )
        msg2 = SimpleNamespace(
            id=202,
            chat=SimpleNamespace(id=-1002222),
            video=SimpleNamespace(
                file_unique_id="fuid_second_2",
                file_id="fid_2",
                file_name="second_video.mp4",
                mime_type="video/mp4",
                file_size=60000,
            ),
            date="2026-09-29T00:00:00",
        )
        db.save_tg_media(msg2)

        db.update_user_record(u1["id"], bin_channel_id=-1003333)

        union_res = backup_manager.restore_backup(bak_res["filename"], mode="union")
        self.assertTrue(union_res["success"])
        self.assertEqual(union_res["mode"], "union")

        self.assertIsNotNone(db.get_user_by_username("tenant_second"))
        browse_u2 = db.browse_tg_media(chat_id=-1002222)
        self.assertEqual(browse_u2["total"], 1)

        u1_updated = db.get_user_by_id(u1["id"])
        self.assertEqual(u1_updated["bin_channel_id"], -1003333)
        self.assertIn(-1001111, u1_updated["extra_channels"])

        browse_u1 = db.browse_tg_media(chat_ids=db.get_user_all_channel_ids(u1_updated))
        self.assertEqual(browse_u1["total"], 1)
        self.assertEqual(browse_u1["items"][0]["file_name"], "first_video.mp4")

    def test_tenant_data_export(self):
        """验证租户专属数据独立导出功能：数据完整且不泄露敏感凭据"""
        u = db.create_tenant_user(
            username="export_user",
            password_hash="secret_hash_value",
            role="user",
            bin_channel_id=-1008888,
        )
        msg = SimpleNamespace(
            id=301,
            chat=SimpleNamespace(id=-1008888),
            video=SimpleNamespace(
                file_unique_id="fuid_export_301",
                file_id="fid_301",
                file_name="my_export_vid.mp4",
                mime_type="video/mp4",
                file_size=123456,
            ),
            date="2026-09-30T00:00:00",
        )
        db.save_tg_media(msg)

        data = backup_manager.export_tenant_data(u["id"])
        self.assertEqual(data["tenant"]["username"], "export_user")
        self.assertNotIn("password_hash", data["tenant"])
        self.assertEqual(data["stats"]["media_count"], 1)
        self.assertEqual(data["media"][0]["file_name"], "my_export_vid.mp4")

if __name__ == "__main__":
    unittest.main()
