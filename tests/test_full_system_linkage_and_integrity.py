import tests  # noqa: F401
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import db
import cache_manager
from thumbnail_generator import get_thumbnail_generator, remove_cached_telegram_thumbnail
from telegram_user_uploader import UserUploadManager
from auth import hash_password


def _make_mock_media(chat_id: int, message_id: int, file_name: str, file_unique_id: str, file_size: int = 1024, mime_type: str = "video/mp4"):
    msg = SimpleNamespace(
        id=message_id,
        caption="",
        media_group_id=None,
        date=None,
        chat=SimpleNamespace(id=chat_id)
    )
    media = SimpleNamespace(
        file_unique_id=file_unique_id,
        file_id=f"fid_{file_unique_id}",
        file_name=file_name,
        file_size=file_size,
        mime_type=mime_type
    )
    return msg, media


class TestFullSystemLinkageAndIntegrity(unittest.TestCase):
    def setUp(self):
        # 1. 独立临时 SQLite 沙箱
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()

        # 2. 独立临时缓存与上传目录沙箱
        self._thumb_dir = tempfile.mkdtemp(prefix="test_thumb_linkage_")
        self._upload_dir = tempfile.mkdtemp(prefix="test_upload_linkage_")
        
        # 模拟缩略图生成器指向临时目录
        self.tg = get_thumbnail_generator()
        self.orig_cache_dir = self.tg.cache_dir
        self.tg.cache_dir = Path(self._thumb_dir)

    def tearDown(self):
        # 还原数据库现场
        db.DB_PATH = self.orig_db_path
        if os.path.exists(self._tmp.name):
            try:
                os.unlink(self._tmp.name)
            except OSError:
                pass

        # 还原缩略图与清理临时目录
        self.tg.cache_dir = self.orig_cache_dir
        shutil.rmtree(self._thumb_dir, ignore_errors=True)
        shutil.rmtree(self._upload_dir, ignore_errors=True)

    def test_tenant_lifecycle_and_zero_orphans(self):
        """用例 1: 租户完整生命周期与 0 孤儿验证 (分别测试 delete_media=False 与 True)"""
        # 阶段 A: 创建租户 Bob，添加边缘节点与 Token，添加下载记录
        bob = db.create_tenant_user(
            username="bob_tenant",
            password_hash=hash_password("BobPass123!"),
            bin_channel_id=-1001111111,
        )
        bob_id = bob["id"]
        token_info = db.create_edge_node_token(tenant_id=bob_id, node_name="BobNode")
        node = db.verify_and_consume_edge_node_token(token_info["token"], ip="1.2.3.4")
        self.assertIsNotNone(node)

        # 插入模拟媒体与关联下载记录
        msg_b, med_b = _make_mock_media(
            chat_id=-1001111111,
            message_id=5001,
            file_name="bob_doc.pdf",
            file_unique_id="fuid_bob_media",
        )
        db.save_tg_media(msg_b, med_b)

        dl_id = db.create_download(
            file_unique_id="fuid_bob_media",
            gid="gid_bob_dl",
            source_url="http://127.0.0.1/bob_doc.pdf",
            user_id=bob_id,
        )

        # 模式 1: delete_media_records=False 销户
        res = db.delete_user_record(bob_id, delete_media_records=False)
        self.assertEqual(res["deleted_user_id"], bob_id)

        # 校验：边缘节点与 Token 均已被清理
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM edge_nodes WHERE tenant_id = ?", (bob_id,)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM edge_node_tokens WHERE tenant_id = ?", (bob_id,)).fetchone()[0], 0)
            # 下载记录保留，但 user_id 安全置空，消除断链孤儿
            dl_row = conn.execute("SELECT user_id, file_unique_id FROM downloads WHERE id = ?", (dl_id,)).fetchone()
            self.assertIsNone(dl_row["user_id"])
            # 媒体记录仍然保留
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tg_media WHERE file_unique_id = 'fuid_bob_media'").fetchone()[0], 1)
            # 外键校验无任何违规
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(len(violations), 0)

        # 阶段 B: 创建租户 Alice (delete_media_records=True 模式)
        alice = db.create_tenant_user(
            username="alice_tenant",
            password_hash=hash_password("AlicePass123!"),
            bin_channel_id=-1002222222,
        )
        alice_id = alice["id"]
        msg_a, med_a = _make_mock_media(
            chat_id=-1002222222,
            message_id=6001,
            file_name="alice_video.mp4",
            file_unique_id="fuid_alice_media",
            file_size=2048,
        )
        db.save_tg_media(msg_a, med_a)

        dl_alice = db.create_download(
            file_unique_id="fuid_alice_media",
            gid="gid_alice_dl",
            source_url="http://127.0.0.1/alice_video.mp4",
            user_id=alice_id,
        )
        upload_id = db.create_upload(
            download_id=dl_alice,
            upload_target="telegram",
            remote_path="/alice_video.mp4",
        )

        # 模式 2: delete_media_records=True 销户
        res_alice = db.delete_user_record(alice_id, delete_media_records=True)
        self.assertEqual(res_alice["deleted_user_id"], alice_id)
        self.assertEqual(res_alice["deleted_media"], 1)

        with db.get_connection() as conn:
            # Alice 的媒体、下载和上传记录均被彻底清理
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tg_media WHERE chat_id = -1002222222").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM downloads WHERE id = ?", (dl_alice,)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM uploads WHERE id = ?", (upload_id,)).fetchone()[0], 0)
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(len(violations), 0)

    def test_edge_node_and_token_cascade(self):
        """用例 2: 边缘节点删除与 Token 级联核销"""
        user = db.create_tenant_user(username="node_owner", password_hash="hash")
        tok = db.create_edge_node_token(tenant_id=user["id"], node_name="Worker1")
        node = db.verify_and_consume_edge_node_token(tok["token"], ip="192.168.1.100")
        node_id = node["id"]

        with db.get_connection() as conn:
            tok_row = conn.execute("SELECT used, node_id FROM edge_node_tokens WHERE token = ?", (tok["token"],)).fetchone()
            self.assertEqual(tok_row["used"], 1)
            self.assertEqual(tok_row["node_id"], node_id)

        # 删除边缘节点
        deleted = db.delete_edge_node(node_id)
        self.assertTrue(deleted)

        with db.get_connection() as conn:
            # 确认节点记录已删
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM edge_nodes WHERE id = ?", (node_id,)).fetchone()[0], 0)
            # 确认关联的 token 也已被安全移除，不留悬空外键
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM edge_node_tokens WHERE node_id = ?", (node_id,)).fetchone()[0], 0)
            self.assertEqual(len(conn.execute("PRAGMA foreign_key_check").fetchall()), 0)

    def test_protocol_account_deletion_unlinking(self):
        """用例 3: 协议号注销与租户创建者字段安全置空"""
        proto = db.upsert_protocol_account(phone="+1234567890", session_data="test_session")
        proto_id = proto["id"]

        # 创建引用该协议号的租户
        tenant = db.create_tenant_user(
            username="chan_tenant",
            password_hash="hash",
            creator_account_id=proto_id,
            bin_channel_id=-100888888,
        )
        self.assertEqual(tenant["creator_account_id"], proto_id)

        # 删除协议号
        ok = db.delete_protocol_account(proto_id)
        self.assertTrue(ok)

        # 校验：租户仍正常存在，但 creator_account_id 置空
        updated_tenant = db.get_user_by_id(tenant["id"])
        self.assertIsNotNone(updated_tenant)
        self.assertIsNone(updated_tenant["creator_account_id"])
        with db.get_connection() as conn:
            self.assertEqual(len(conn.execute("PRAGMA foreign_key_check").fetchall()), 0)

    def test_media_deletion_and_thumbnail_file_linkage(self):
        """用例 4: 媒体删除与缩略图物理文件联动清理"""
        cid = -100333333
        mid = 7777
        fname = "sample.mp4"
        fuid = "fuid_sample_7777"

        msg, med = _make_mock_media(
            chat_id=cid,
            message_id=mid,
            file_name=fname,
            file_unique_id=fuid,
        )
        db.save_tg_media(msg, med)

        # 在沙箱缓存目录写入该媒体的模拟缩略图
        cache_key = f"{cid}_{mid}_{fname}"
        thumb_path = self.tg._get_cache_path("telegram", cache_key)
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        thumb_path.write_bytes(b"fake_webp_bytes")
        self.assertTrue(thumb_path.exists())

        # 调用 delete_tg_media_records
        res = db.delete_tg_media_records([fuid], chat_id=cid)
        self.assertEqual(res["deleted_media"], 1)

        # 验证数据库被删除且磁盘上的 .webp 缩略图已被联动移除
        self.assertFalse(thumb_path.exists())

    def test_clean_orphaned_telegram_thumbnails_audit(self):
        """用例 5: 孤儿缩略图全量审计核销验证"""
        # 1. 数据库中保留一个有效记录
        msg, med = _make_mock_media(
            chat_id=-10055555,
            message_id=8888,
            file_name="active.mp4",
            file_unique_id="fuid_active",
        )
        db.save_tg_media(msg, med)

        active_key = "-10055555_8888_active.mp4"
        active_thumb = self.tg._get_cache_path("telegram", active_key)
        active_thumb.parent.mkdir(parents=True, exist_ok=True)
        active_thumb.write_bytes(b"active_webp")

        # 2. 注入一个未在数据库中的孤儿缩略图
        orphan_thumb = self.tg.cache_dir / "telegram" / "deadbeef000011112222333344445555.webp"
        orphan_thumb.write_bytes(b"orphan_webp")

        # 3. 注入系统保留 fallback
        fallback_file = self.tg.cache_dir / "telegram" / "fallback-video.webp"
        fallback_file.write_bytes(b"fallback_webp")

        self.assertTrue(active_thumb.exists())
        self.assertTrue(orphan_thumb.exists())
        self.assertTrue(fallback_file.exists())

        # 4. 执行孤儿缩略图核销
        audit_res = cache_manager.clean_orphaned_telegram_thumbnails(dry_run=False)
        self.assertEqual(audit_res["deleted_files"], 1)

        # 5. 校验：孤儿文件被删除，活跃媒体缩略图和 fallback 保留
        self.assertFalse(orphan_thumb.exists())
        self.assertTrue(active_thumb.exists())
        self.assertTrue(fallback_file.exists())

    def test_stale_chunk_upload_garbage_collection(self):
        """用例 6: 分片上传异常中断暂存垃圾回收"""
        manager = UserUploadManager()
        # 覆写其暂存根目录为沙箱目录
        staging_root = Path(self._upload_dir) / "temp_uploads"
        staging_root.mkdir(parents=True, exist_ok=True)

        with mock.patch("telegram_user_uploader.get_temp_upload_dir", return_value=staging_root):
            init_res = manager.init_upload(
                user_id=1,
                chat_id=-1001111111,
                filename="test_movie.mkv",
                file_size=10 * 1024 * 1024,
                chunk_size=5 * 1024 * 1024,
            )
            upload_id = init_res["upload_id"]
            staging_path = staging_root / upload_id
            self.assertTrue(staging_path.exists())

            # 模拟写入 1 个分片
            manager.save_chunk(upload_id, user_id=1, chunk_index=0, chunk_data=b"fake_chunk_0")
            self.assertTrue((staging_path / "chunk_0").exists())

            # 模拟时间流逝（篡改 mtime 为 3 小时前）
            old_time = time.time() - 3600 * 3
            os.utime(staging_path, (old_time, old_time))
            manager._tasks[upload_id]["updated_at"] = old_time

            # 执行过期清理 (TTL=7200s, 2小时)
            clean_res = manager.cleanup_stale_uploads(max_age_seconds=7200)
            self.assertEqual(clean_res["cleaned_dirs"], 1)
            self.assertFalse(staging_path.exists())
            self.assertNotIn(upload_id, manager._tasks)

    def test_expired_sessions_tokens_codes_cleanup(self):
        """用例 7: 过期凭证、令牌与注册码清理"""
        # 1. 注册码：插入过期与未过期
        db.create_tg_register_code(code="PAST01", tg_user_id=101, tg_username="u1", tg_first_name="f1", detected_dc_id=1, expires_minutes=-10)
        db.create_tg_register_code(code="FUTURE01", tg_user_id=102, tg_username="u2", tg_first_name="f2", detected_dc_id=1, expires_minutes=10)

        # 2. 边缘 Token：插入过期与未过期
        exp_past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        tok_past = db.create_edge_node_token(tenant_id=1, node_name="PastNode", expires_minutes=5)
        with db.get_connection() as conn:
            conn.execute("UPDATE edge_node_tokens SET expires_at = ? WHERE token = ?", (exp_past, tok_past["token"]))
        tok_future = db.create_edge_node_token(tenant_id=1, node_name="FutureNode", expires_minutes=10)

        # 3. 运行清理函数
        del_tokens = db.cleanup_expired_edge_node_tokens()
        del_codes = db.cleanup_expired_tg_register_codes()

        self.assertGreaterEqual(del_tokens, 1)
        self.assertGreaterEqual(del_codes, 1)

        # 校验：过期的消失，未来的保留
        self.assertIsNone(db.get_tg_register_code("PAST01"))
        self.assertIsNotNone(db.get_tg_register_code("FUTURE01"))
        self.assertIsNone(db.get_edge_node_token(tok_past["token"]))
        self.assertIsNotNone(db.get_edge_node_token(tok_future["token"]))


if __name__ == "__main__":
    unittest.main()
