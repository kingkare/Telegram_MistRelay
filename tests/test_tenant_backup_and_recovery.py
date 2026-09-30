import os
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import db
import backup_manager


class TenantBackupAndRecoveryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()

        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name

        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_sess_env = os.environ.get("MISTRELAY_SESSION_DIR")
        self.sessions_dir = Path(self.temp_dir.name) / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        os.environ["MISTRELAY_SESSION_DIR"] = str(self.sessions_dir)

        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        if self.orig_sess_env is None:
            os.environ.pop("MISTRELAY_SESSION_DIR", None)
        else:
            os.environ["MISTRELAY_SESSION_DIR"] = self.orig_sess_env
        self.temp_dir.cleanup()

        if hasattr(self, "_tmp") and os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except OSError:
                pass

    def test_orphan_media_recovery_and_browse(self):
        """验证孤儿媒体自愈与多频道联合挂载浏览"""
        # 1. 创建租户并绑定原频道
        u = db.create_tenant_user(
            username="xiaopeng_test",
            password_hash="pw123",
            role="user",
            bin_channel_id=-1004327294673,
            bin_channel_username="mr_chan_old",
        )
        msg1 = SimpleNamespace(
            id=10,
            chat=SimpleNamespace(id=-1004327294673),
            video=SimpleNamespace(
                file_unique_id="fuid_old_1",
                file_id="fid_old_1",
                file_name="old_video.mp4",
                mime_type="video/mp4",
                file_size=1000000,
            ),
            date="2026-09-28T00:00:00",
        )
        db.save_tg_media(msg1)

        # 2. 模拟管理员为其重开新频道，原频道媒体变为孤儿
        db.update_user_record(u["id"], bin_channel_id=-1004471687603)

        # 验证此时若仅按当前新频道查，结果为0（复现租户反馈“数据丢失”问题）
        browse_only_new = db.browse_tg_media(chat_id=-1004471687603)
        self.assertEqual(browse_only_new["total"], 0)

        # 3. 执行孤儿自愈函数
        heal_res = db.heal_orphaned_tenant_media({-1004327294673: "xiaopeng_test"})
        self.assertTrue(heal_res["success"])
        self.assertEqual(heal_res["total_files_restored"], 1)

        # 4. 验证用户 extra_channels 正确挂载了旧频道
        updated_u = db.get_user_by_id(u["id"])
        self.assertEqual(updated_u["bin_channel_id"], -1004471687603)
        self.assertIn(-1004327294673, updated_u["extra_channels"])

        # 5. 验证多频道联合浏览与统计
        all_cids = db.get_user_all_channel_ids(updated_u)
        self.assertEqual(len(all_cids), 2)
        browse_res = db.browse_tg_media(chat_ids=all_cids)
        self.assertEqual(browse_res["total"], 1)
        self.assertEqual(browse_res["items"][0]["file_name"], "old_video.mp4")

        stats_res = db.get_tg_media_stats(chat_ids=all_cids)
        self.assertEqual(stats_res["total_count"], 1)
        self.assertEqual(stats_res["total_size"], 1000000)

    def test_union_restore_safety_preserves_new_tenants(self):
        """验证无损增量还原 (Union Restore) 绝不冲掉新注册租户与最新上传文件"""
        # 1. 建立历史租户与文件
        u_old = db.create_tenant_user(username="historical_tenant", password_hash="pw", role="user", bin_channel_id=-100101)
        msg_old = SimpleNamespace(
            id=1,
            chat=SimpleNamespace(id=-100101),
            video=SimpleNamespace(
                file_unique_id="fuid_hist_1",
                file_id="fid_hist_1",
                file_name="hist_movie.mp4",
                mime_type="video/mp4",
                file_size=200000,
            ),
            date="2026-09-20T00:00:00",
        )
        db.save_tg_media(msg_old)
        bak = backup_manager.create_backup(remark="baseline_for_union")

        # 2. 模拟新注册租户与新媒体
        u_new = db.create_tenant_user(username="brand_new_tenant", password_hash="pw", role="user", bin_channel_id=-100202)
        msg_new = SimpleNamespace(
            id=2,
            chat=SimpleNamespace(id=-100202),
            video=SimpleNamespace(
                file_unique_id="fuid_brand_new_2",
                file_id="fid_brand_new_2",
                file_name="new_movie.mp4",
                mime_type="video/mp4",
                file_size=300000,
            ),
            date="2026-09-30T00:00:00",
        )
        db.save_tg_media(msg_new)

        # 3. 执行 union 还原
        res = backup_manager.restore_backup(bak["filename"], mode="union")
        self.assertTrue(res["success"])
        self.assertEqual(res["mode"], "union")

        # 4. 断言：新租户依然存在且文件正常
        self.assertIsNotNone(db.get_user_by_username("brand_new_tenant"))
        self.assertIsNotNone(db.get_user_by_username("historical_tenant"))
        self.assertEqual(db.browse_tg_media(chat_id=-100202)["total"], 1)
        self.assertEqual(db.browse_tg_media(chat_id=-100101)["total"], 1)

    def test_tenant_data_export_sanitization(self):
        """验证租户独立导出包含所有频道与媒体，且完全脱敏系统与他人凭据"""
        u = db.create_tenant_user(
            username="tenant_for_export",
            password_hash="my_super_secret_hash",
            role="user",
            bin_channel_id=-100777,
        )
        # 追加一个历史频道
        db.append_user_extra_channel(u["id"], -100666)

        msg_curr = SimpleNamespace(
            id=71,
            chat=SimpleNamespace(id=-100777),
            video=SimpleNamespace(
                file_unique_id="fuid_curr_71",
                file_id="fid_71",
                file_name="curr_file.mp4",
                mime_type="video/mp4",
                file_size=150000,
            ),
            date="2026-09-30T00:00:00",
        )
        msg_hist = SimpleNamespace(
            id=61,
            chat=SimpleNamespace(id=-100666),
            video=SimpleNamespace(
                file_unique_id="fuid_hist_61",
                file_id="fid_61",
                file_name="hist_file.mp4",
                mime_type="video/mp4",
                file_size=250000,
            ),
            date="2026-09-28T00:00:00",
        )
        db.save_tg_media(msg_curr)
        db.save_tg_media(msg_hist)

        data = backup_manager.export_tenant_data(u["id"])
        self.assertEqual(data["tenant"]["username"], "tenant_for_export")
        self.assertNotIn("password_hash", data["tenant"])
        self.assertIn(-100777, data["channel_ids"])
        self.assertIn(-100666, data["channel_ids"])
        self.assertEqual(data["stats"]["media_count"], 2)
        self.assertEqual(data["stats"]["media_total_bytes"], 400000)
        file_names = {m["file_name"] for m in data["media"]}
        self.assertEqual(file_names, {"curr_file.mp4", "hist_file.mp4"})


if __name__ == "__main__":
    unittest.main()
