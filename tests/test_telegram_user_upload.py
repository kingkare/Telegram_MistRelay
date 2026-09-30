import json
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# Ensure paths
root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import db
from telegram_user_uploader import UserUploadManager, DEFAULT_CHUNK_SIZE
from path_security import UnsafePathError
from WebStreamer.server.stream_routes import (
    telegram_upload_init_handler,
    telegram_upload_chunk_handler,
    telegram_upload_finish_handler,
    telegram_upload_status_handler,
    telegram_upload_cancel_handler
)
from WebStreamer.vars import Var


class MockRequest(dict):
    def __init__(self, user=None, query=None, match_info=None, json_body=None, headers=None, content_type="application/json", body_bytes=b""):
        super().__init__()
        self["user"] = user
        self.query = query or {}
        self.match_info = match_info or {}
        self._json_body = json_body or {}
        self.headers = headers or {}
        self.content_type = content_type
        self._body_bytes = body_bytes

    async def json(self):
        return self._json_body

    async def read(self):
        return self._body_bytes


class TestTelegramUserUpload(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # 1. 独立临时 SQLite 沙箱
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()

        # 2. 独立临时上传目录
        self._tmp_upload_dir = tempfile.TemporaryDirectory()
        self.orig_temp_env = os.environ.get("MISTRELAY_TEMP_UPLOAD_DIR")
        os.environ["MISTRELAY_TEMP_UPLOAD_DIR"] = self._tmp_upload_dir.name

        self.manager = UserUploadManager()

    def tearDown(self):
        # 恢复现场
        db.DB_PATH = self.orig_db_path
        if hasattr(self, "_tmp") and os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except OSError:
                pass

        if self.orig_temp_env is not None:
            os.environ["MISTRELAY_TEMP_UPLOAD_DIR"] = self.orig_temp_env
        else:
            os.environ.pop("MISTRELAY_TEMP_UPLOAD_DIR", None)

        try:
            self._tmp_upload_dir.cleanup()
        except Exception:
            pass

    def test_init_upload_validation(self):
        """测试上传初始化时的参数校验与安全过滤"""
        # 正常初始化
        res = self.manager.init_upload(
            user_id=1,
            chat_id=-1001234567,
            filename="my_test_video.mp4",
            file_size=12 * 1024 * 1024,  # 12MB
            chunk_size=5 * 1024 * 1024
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["total_chunks"], 3)
        self.assertEqual(res["filename"], "my_test_video.mp4")
        self.assertEqual(res["target_channel_id"], -1001234567)

        # 路径穿越文件名必须被拦截
        with self.assertRaises(UnsafePathError):
            self.manager.init_upload(
                user_id=1,
                chat_id=-1001234567,
                filename="../../etc/passwd",
                file_size=1024
            )

        # 非法文件大小必须被拦截
        with self.assertRaises(ValueError):
            self.manager.init_upload(
                user_id=1,
                chat_id=-1001234567,
                filename="zero.txt",
                file_size=0
            )

        with self.assertRaises(ValueError):
            self.manager.init_upload(
                user_id=1,
                chat_id=-1001234567,
                filename="huge.bin",
                file_size=3 * 1024 * 1024 * 1024  # 3GB > 2GB
            )

    async def test_chunk_upload_and_assembly(self):
        """测试分片写入、缺片检查与流式拼接"""
        file_content = b"MistRelay-Telegram-User-Upload-Test-Chunk-Content" * 100
        chunk_size = 1000
        total_size = len(file_content)

        init_res = self.manager.init_upload(
            user_id=1,
            chat_id=-100999,
            filename="sample_doc.pdf",
            file_size=total_size,
            chunk_size=chunk_size
        )
        upload_id = init_res["upload_id"]
        total_chunks = init_res["total_chunks"]

        # 上传第 0 个分片
        c0 = file_content[:chunk_size]
        res0 = self.manager.save_chunk(upload_id, user_id=1, chunk_index=0, chunk_data=c0)
        self.assertTrue(res0["success"])
        self.assertEqual(res0["received_count"], 1)

        # 在缺少分片时调用 finish 必须抛出异常
        if total_chunks > 1:
            with self.assertRaises(ValueError):
                await self.manager.finish_upload(upload_id, user_id=1, wait_seconds=0)

        # 上传剩余分片
        for i in range(1, total_chunks):
            ci = file_content[i * chunk_size : (i + 1) * chunk_size]
            self.manager.save_chunk(upload_id, user_id=1, chunk_index=i, chunk_data=ci)

        # Mock Telegram 上传客户端，验证发送与入库
        mock_msg = MagicMock()
        mock_msg.id = 8888
        mock_msg.message_id = 8888
        mock_msg.chat = MagicMock(id=-100999)
        mock_msg.from_user = None
        mock_msg.sender_chat = None
        mock_msg.caption_entities = []
        mock_msg.date = "2026-09-30T00:00:00"
        mock_msg.media_group_id = None
        mock_msg.has_media_spoiler = 0
        mock_msg.supports_streaming = 1
        mock_msg.caption = None
        mock_msg.file = None

        mock_doc = MagicMock()
        mock_doc.file_unique_id = "test_unique_doc_8888"
        mock_doc.file_id = "test_fid_doc_8888"
        mock_doc.file_name = "sample_doc.pdf"
        mock_doc.mime_type = "application/pdf"
        mock_doc.file_size = total_size
        mock_doc.width = None
        mock_doc.height = None
        mock_doc.duration = None
        mock_doc.thumbs = None

        mock_msg.document = mock_doc
        mock_msg.media = MagicMock(value="document")
        mock_msg.photo = None
        mock_msg.video = None
        mock_msg.audio = None
        mock_msg.voice = None
        mock_msg.video_note = None
        mock_msg.animation = None
        mock_msg.sticker = None

        mock_client = MagicMock()
        mock_client.send_document = AsyncMock(return_value=mock_msg)
        mock_client.resolve_peer = AsyncMock()

        with patch.object(self.manager, "_resolve_client", return_value=mock_client):
            finish_res = await self.manager.finish_upload(upload_id, user_id=1, wait_seconds=1.0)
            self.assertTrue(finish_res["success"])

            # 等待后台任务完成
            task = self.manager._tasks[upload_id]
            if task["async_task"]:
                await task["async_task"]

            status_res = self.manager.get_status(upload_id, user_id=1)
            self.assertEqual(status_res["status"], "completed")
            self.assertEqual(status_res["tg_progress"], 1.0)

            # 校验 tg_media 数据库记录已生成
            rec = db.get_tg_media_record_by_message_id(8888, chat_id=-100999)
            self.assertIsNotNone(rec)
            self.assertEqual(rec["file_name"], "sample_doc.pdf")
            self.assertEqual(rec["mime_type"], "application/pdf")

    async def test_video_upload_flow(self):
        """测试视频文件上传流与 send_video 路由"""
        file_content = b"\x00\x00\x00\x20ftypisom" * 50
        init_res = self.manager.init_upload(
            user_id=2,
            chat_id=-100777,
            filename="nature.mp4",
            file_size=len(file_content),
            chunk_size=1000
        )
        upload_id = init_res["upload_id"]
        for idx in range(init_res["total_chunks"]):
            self.manager.save_chunk(
                upload_id,
                user_id=2,
                chunk_index=idx,
                chunk_data=file_content[idx * 1000 : (idx + 1) * 1000]
            )

        mock_msg = MagicMock()
        mock_msg.id = 9999
        mock_msg.message_id = 9999
        mock_msg.chat = MagicMock(id=-100777)
        mock_msg.from_user = None
        mock_msg.sender_chat = None
        mock_msg.caption_entities = []
        mock_msg.date = "2026-09-30T00:00:00"
        mock_msg.media_group_id = None
        mock_msg.has_media_spoiler = 0
        mock_msg.supports_streaming = 1
        mock_msg.caption = None
        mock_msg.file = None

        mock_video = MagicMock()
        mock_video.file_unique_id = "test_vid_9999"
        mock_video.file_id = "test_fid_vid_9999"
        mock_video.file_name = "nature.mp4"
        mock_video.mime_type = "video/mp4"
        mock_video.file_size = len(file_content)
        mock_video.width = 1920
        mock_video.height = 1080
        mock_video.duration = 120
        mock_video.thumbs = None

        mock_msg.video = mock_video
        mock_msg.media = MagicMock(value="video")
        mock_msg.document = None
        mock_msg.photo = None
        mock_msg.audio = None
        mock_msg.voice = None
        mock_msg.video_note = None
        mock_msg.animation = None
        mock_msg.sticker = None

        mock_client = MagicMock()
        mock_client.send_video = AsyncMock(return_value=mock_msg)
        mock_client.resolve_peer = AsyncMock()

        with patch.object(self.manager, "_resolve_client", return_value=mock_client):
            finish_res = await self.manager.finish_upload(upload_id, user_id=2, wait_seconds=1.0)
            self.assertTrue(finish_res["success"])

            task = self.manager._tasks[upload_id]
            if task["async_task"]:
                await task["async_task"]

            self.assertTrue(mock_client.send_video.called)
            rec = db.get_tg_media_record_by_message_id(9999, chat_id=-100777)
            self.assertIsNotNone(rec)
            self.assertEqual(rec["file_name"], "nature.mp4")
            self.assertEqual(rec["mime_type"], "video/mp4")

    async def test_image_upload_flow(self):
        """测试图片文件 (如 640.jpeg) 上传流与 send_photo 路由与媒体元数据落库"""
        file_content = b"fake-jpeg-header-640-jpeg" + b"0" * 2000
        init_res = self.manager.init_upload(
            user_id=2,
            chat_id=-100777,
            filename="640.jpeg",
            file_size=len(file_content),
            chunk_size=1000
        )
        upload_id = init_res["upload_id"]
        for idx in range(init_res["total_chunks"]):
            self.manager.save_chunk(
                upload_id,
                user_id=2,
                chunk_index=idx,
                chunk_data=file_content[idx * 1000 : (idx + 1) * 1000]
            )

        mock_msg = MagicMock()
        mock_msg.id = 7777
        mock_msg.message_id = 7777
        mock_msg.chat = MagicMock(id=-100777)
        mock_msg.from_user = None
        mock_msg.sender_chat = None
        mock_msg.caption_entities = []
        mock_msg.date = "2026-09-30T00:00:00"
        mock_msg.media_group_id = None
        mock_msg.has_media_spoiler = 0
        mock_msg.supports_streaming = 0
        mock_msg.caption = None
        mock_msg.file = None

        mock_photo = MagicMock()
        mock_photo.file_unique_id = "test_photo_7777"
        mock_photo.file_id = "test_fid_photo_7777"
        mock_photo.file_name = "640.jpeg"
        mock_photo.mime_type = "image/jpeg"
        mock_photo.file_size = len(file_content)
        mock_photo.width = 640
        mock_photo.height = 480
        mock_photo.duration = None
        mock_photo.thumbs = None

        mock_msg.photo = mock_photo
        mock_msg.media = MagicMock(value="photo")
        mock_msg.document = None
        mock_msg.video = None
        mock_msg.audio = None
        mock_msg.voice = None
        mock_msg.video_note = None
        mock_msg.animation = None
        mock_msg.sticker = None

        mock_client = MagicMock()
        mock_client.send_photo = AsyncMock(return_value=mock_msg)
        mock_client.resolve_peer = AsyncMock()

        with patch.object(self.manager, "_resolve_client", return_value=mock_client):
            finish_res = await self.manager.finish_upload(upload_id, user_id=2, wait_seconds=1.0)
            self.assertTrue(finish_res["success"])

            task = self.manager._tasks[upload_id]
            if task["async_task"]:
                await task["async_task"]

            self.assertTrue(mock_client.send_photo.called)
            rec = db.get_tg_media_record_by_message_id(7777, chat_id=-100777)
            self.assertIsNotNone(rec)
            self.assertEqual(rec["file_name"], "640.jpeg")
            self.assertEqual(rec["mime_type"], "image/jpeg")

    async def test_cancel_upload(self):
        """测试取消上传与暂存清理"""
        init_res = self.manager.init_upload(
            user_id=1,
            chat_id=-100123,
            filename="to_be_cancelled.bin",
            file_size=5000,
            chunk_size=1000
        )
        upload_id = init_res["upload_id"]
        staging_dir = self.manager._tasks[upload_id]["staging_dir"]
        self.assertTrue(os.path.exists(staging_dir))

        cancel_res = await self.manager.cancel_upload(upload_id, user_id=1)
        self.assertTrue(cancel_res["success"])
        self.assertFalse(os.path.exists(staging_dir))
        self.assertNotIn(upload_id, self.manager._tasks)

    async def test_api_handlers_permissions(self):
        """测试上传 API 路由层的身份认证与租户频道权限隔离"""
        # 1. 未登录请求各接口 -> 401
        req_unauth = MockRequest(user=None, json_body={"filename": "test.txt", "file_size": 100})
        resp_unauth = await telegram_upload_init_handler(req_unauth)
        self.assertEqual(resp_unauth.status, 401)

        req_chunk_unauth = MockRequest(user=None, headers={"X-Upload-ID": "u1", "X-Chunk-Index": "0"})
        self.assertEqual((await telegram_upload_chunk_handler(req_chunk_unauth)).status, 401)

        req_finish_unauth = MockRequest(user=None, json_body={"upload_id": "u1"})
        self.assertEqual((await telegram_upload_finish_handler(req_finish_unauth)).status, 401)

        req_status_unauth = MockRequest(user=None, match_info={"upload_id": "u1"})
        self.assertEqual((await telegram_upload_status_handler(req_status_unauth)).status, 401)

        req_cancel_unauth = MockRequest(user=None, json_body={"upload_id": "u1"})
        self.assertEqual((await telegram_upload_cancel_handler(req_cancel_unauth)).status, 401)

        # 2. 未分配专属频道的普通租户请求 -> 403
        tenant_no_channel = {"uid": 101, "role": "user", "username": "unbound_user"}
        req_no_chan = MockRequest(user=tenant_no_channel, json_body={"filename": "test.txt", "file_size": 100})
        resp_no_chan = await telegram_upload_init_handler(req_no_chan)
        self.assertEqual(resp_no_chan.status, 403)
        body_no_chan = json.loads(resp_no_chan.text)
        self.assertIn("专属存储频道", body_no_chan["error"])

        # 3. 已绑定专属频道的普通租户请求 -> 200 并锁定其专属频道
        u_bound = db.create_tenant_user("bound_user", "pass123", bin_channel_id=-10088888, role="user")
        tenant_bound = {"uid": u_bound["id"], "role": "user", "username": "bound_user"}
        req_bound = MockRequest(user=tenant_bound, json_body={"filename": "doc.pdf", "file_size": 1024})
        resp_bound = await telegram_upload_init_handler(req_bound)
        self.assertEqual(resp_bound.status, 200)
        body_bound = json.loads(resp_bound.text)
        self.assertTrue(body_bound["success"])
        self.assertEqual(body_bound["target_channel_id"], -10088888)

        # 4. 管理员上传请求 -> 200 (默认或指定频道)
        admin_user = {"uid": 1, "role": "admin", "username": "admin"}
        req_admin = MockRequest(user=admin_user, json_body={"filename": "admin_file.zip", "file_size": 2048, "chat_id": -10055555})
        resp_admin = await telegram_upload_init_handler(req_admin)
        self.assertEqual(resp_admin.status, 200)
        body_admin = json.loads(resp_admin.text)
        self.assertEqual(body_admin["target_channel_id"], -10055555)

        # 5. 上传分片并查询状态与取消
        upload_id = body_admin["upload_id"]
        req_chunk = MockRequest(
            user=admin_user,
            headers={"X-Upload-ID": upload_id, "X-Chunk-Index": "0"},
            content_type="application/octet-stream",
            body_bytes=b"admin_test_chunk_data"
        )
        resp_chunk = await telegram_upload_chunk_handler(req_chunk)
        self.assertEqual(resp_chunk.status, 200)

        # 查询状态
        req_status = MockRequest(user=admin_user, match_info={"upload_id": upload_id})
        resp_status = await telegram_upload_status_handler(req_status)
        self.assertEqual(resp_status.status, 200)
        body_status = json.loads(resp_status.text)
        self.assertEqual(body_status["received_chunks"], 1)

        # 取消上传
        req_cancel = MockRequest(user=admin_user, json_body={"upload_id": upload_id})
        resp_cancel = await telegram_upload_cancel_handler(req_cancel)
        self.assertEqual(resp_cancel.status, 200)


if __name__ == "__main__":
    unittest.main()
