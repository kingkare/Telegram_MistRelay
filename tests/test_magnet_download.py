import asyncio
import os
import re
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import db
from aria2_client import AsyncAria2Client
from aria2_client.download_handler import DownloadHandler
from aria2_client.upload_handler import UploadHandler


class TestMagnetDownloadEngine(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # 1. 严格使用独立临时数据库沙箱，防止触碰生产库
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()

        # 临时工作目录
        self._test_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        # 恢复数据库现场并清理临时文件
        db.DB_PATH = self.orig_db_path
        if hasattr(self, "_tmp") and os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except OSError:
                pass
        if hasattr(self, "_test_dir"):
            self._test_dir.cleanup()

    def test_magnet_regex_and_parsing(self):
        """测试磁力链接正则解析：Hex-40、Base32-32、大小写、附加参数与混排文本"""
        magnet_pattern = re.compile(
            r"magnet:\?xt=urn:btih:(?:[0-9a-fA-F]{40,64}|[2-7a-zA-Z]{32})(?:&[^\s<>\"'`]+)?",
            re.IGNORECASE,
        )

        test_cases = [
            # 标准 40 位 Hex 磁链
            (
                "magnet:?xt=urn:btih:36b104b47939b8b389ad2ddd5420afe599b0ac42&dn=Sample.mp4",
                ["magnet:?xt=urn:btih:36b104b47939b8b389ad2ddd5420afe599b0ac42&dn=Sample.mp4"]
            ),
            # 32 位 Base32 磁链
            (
                "magnet:?xt=urn:btih:N4QWY3DPO5XXE3DENB2W45DFOIZT2MBM&dn=Base32Video",
                ["magnet:?xt=urn:btih:N4QWY3DPO5XXE3DENB2W45DFOIZT2MBM&dn=Base32Video"]
            ),
            # 全大写与无参数磁链
            (
                "MAGNET:?XT=URN:BTIH:6822A64F5F803A4A1EC2C557654B7397712CCB32",
                ["MAGNET:?XT=URN:BTIH:6822A64F5F803A4A1EC2C557654B7397712CCB32"]
            ),
            # 混排文本与多行输入提取并去重
            (
                "请下载以下资源：\n"
                "1. magnet:?xt=urn:btih:e761bcb315d20301fbd491e0b08ffc09957365eb&dn=file1.mp4 速度很快\n"
                "2. 别忘了还有 magnet:?xt=urn:btih:e761bcb315d20301fbd491e0b08ffc09957365eb&dn=file1.mp4 重复项\n"
                "3. magnet:?xt=urn:btih:2B3C4D5E6F7A8B9C0D1E2F3A4B5C6D7E8F9A0B1C&tr=udp://tracker.opentrackr.org:1337\n"
                "谢谢机器人！",
                [
                    "magnet:?xt=urn:btih:e761bcb315d20301fbd491e0b08ffc09957365eb&dn=file1.mp4",
                    "magnet:?xt=urn:btih:2B3C4D5E6F7A8B9C0D1E2F3A4B5C6D7E8F9A0B1C&tr=udp://tracker.opentrackr.org:1337",
                ]
            )
        ]

        for text, expected in test_cases:
            matches = list(dict.fromkeys(magnet_pattern.findall(text)))
            self.assertEqual(matches, expected)

    async def test_metadata_task_followed_by_inheritance_and_cleanup(self):
        """测试元数据任务 [METADATA] 完成时：followedBy 租户属性自动继承、元数据文件清理与父任务完成归档"""
        mock_upload_handler = MagicMock(spec=UploadHandler)
        mock_upload_handler.upload_to_telegram_with_load_balance = AsyncMock()

        handler = DownloadHandler(
            bot=MagicMock(),
            download_messages={},
            completed_gids=set(),
            upload_handler=mock_upload_handler,
        )

        parent_gid = "gid_parent_magnet_meta"
        child_gid = "gid_child_data_payload"
        user_id = 99
        target_channel_id = -10088997766

        # 1. 模拟用户通过机器人提交磁力链接，在数据库生成父任务
        db.create_download(
            file_unique_id=f"aria2_{parent_gid}",
            gid=parent_gid,
            source_url="magnet:?xt=urn:btih:36b104b47939b8b389ad2ddd5420afe599b0ac42",
            user_id=user_id,
            target_channel_id=target_channel_id,
        )

        # 2. 创建临时 [METADATA] 文件
        meta_file_path = os.path.join(self._test_dir.name, "[METADATA]36b104b47939b8b389ad2ddd5420afe599b0ac42.torrent")
        with open(meta_file_path, "wb") as f:
            f.write(b"dummy torrent metadata bytes")
        self.assertTrue(os.path.exists(meta_file_path))

        # 3. 构造 Aria2 元数据完成时的 tellStatus 返回结构
        async def mock_tell_status(gid):
            if gid == parent_gid:
                return {
                    "gid": parent_gid,
                    "status": "complete",
                    "totalLength": "1024",
                    "completedLength": "1024",
                    "followedBy": [child_gid],
                    "files": [{"path": meta_file_path}],
                }
            return {}

        # 4. 执行 on_download_complete 事件
        event = {"params": [{"gid": parent_gid}]}
        await handler.on_download_complete(event, tell_status_func=mock_tell_status)

        # 5. 验证子任务已在数据库自动生成，且正确继承了租户 user_id 与 target_channel_id
        child_did = db.get_download_id_by_gid(child_gid)
        self.assertIsNotNone(child_did)
        child_rec = db.get_download_by_id(child_did)
        self.assertEqual(child_rec["user_id"], user_id)
        self.assertEqual(child_rec["target_channel_id"], target_channel_id)

        # 6. 验证 [METADATA] 文件已从磁盘物理清理
        self.assertFalse(os.path.exists(meta_file_path))

        # 7. 验证父任务在数据库中已正确标记完成，不残留为未结束任务
        parent_did = db.get_download_id_by_gid(parent_gid)
        parent_rec = db.get_download_by_id(parent_did)
        self.assertEqual(parent_rec["status"], "completed")

        # 8. 验证元数据文件绝不会触发上传到 Telegram
        mock_upload_handler.upload_to_telegram_with_load_balance.assert_not_called()

    async def test_child_task_following_inheritance(self):
        """测试子任务启动阶段通过 following 属性反向继承父元数据任务的租户信息"""
        mock_upload_handler = MagicMock(spec=UploadHandler)
        handler = DownloadHandler(
            bot=None,
            download_messages={},
            completed_gids=set(),
            upload_handler=mock_upload_handler,
        )

        parent_gid = "gid_parent_following_test"
        child_gid = "gid_child_following_test"
        user_id = 77
        target_channel_id = -10077889900

        # 父任务记录预置
        db.create_download(
            file_unique_id=f"aria2_{parent_gid}",
            gid=parent_gid,
            source_url="magnet:?xt=urn:btih:e761bcb315d20301fbd491e0b08ffc09957365eb",
            user_id=user_id,
            target_channel_id=target_channel_id,
        )

        async def mock_tell_status(gid):
            if gid == child_gid:
                return {
                    "gid": child_gid,
                    "following": parent_gid,
                    "status": "active",
                    "totalLength": "104857600",
                    "completedLength": "0",
                    "files": [{"path": "/data/downloads/movie.mp4"}],
                }
            return {}

        # 触发子任务开始
        event = {"params": [{"gid": child_gid}]}
        await handler.on_download_start(event, tell_status_func=mock_tell_status)

        # 验证子任务已创建并继承租户
        child_did = db.get_download_id_by_gid(child_gid)
        self.assertIsNotNone(child_did)
        child_rec = db.get_download_by_id(child_did)
        self.assertEqual(child_rec["user_id"], user_id)
        self.assertEqual(child_rec["target_channel_id"], target_channel_id)

    async def test_on_bt_download_complete_dispatch(self):
        """测试 WebSocket 消息循环成功分发 aria2.onBtDownloadComplete 事件"""
        client = AsyncAria2Client("secret", "ws://localhost:6800", bot=None)
        client.download_handler = MagicMock()
        client.download_handler.on_download_complete = AsyncMock()

        # 模拟接收到 aria2.onBtDownloadComplete 消息
        message = '{"jsonrpc": "2.0", "method": "aria2.onBtDownloadComplete", "params": [{"gid": "gid_bt_done"}]}'

        class MockWs:
            def __aiter__(self):
                return self
            async def __anext__(self):
                if hasattr(self, "_sent"):
                    raise StopAsyncIteration()
                self._sent = True
                return message

        client.websocket = MockWs()
        client.tell_status = AsyncMock()

        try:
            await asyncio.wait_for(client.listen(), timeout=0.5)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

        client.download_handler.on_download_complete.assert_awaited_once()
        call_args = client.download_handler.on_download_complete.await_args[0]
        self.assertEqual(call_args[0]["method"], "aria2.onBtDownloadComplete")
        self.assertEqual(call_args[0]["params"][0]["gid"], "gid_bt_done")

    async def test_polling_seeder_detection(self):
        """测试轮询同步在检测到 BT 做种中 (seeder==true 且已下载完成) 时触发完成事件"""
        client = AsyncAria2Client("secret", "ws://localhost:6800", bot=None)
        client.download_handler = MagicMock()
        client.download_handler.on_download_complete = AsyncMock()
        client.tell_status = AsyncMock()

        gid = "gid_bt_seeding_test"
        aria2_status = {
            "gid": gid,
            "status": "active",
            "bittorrent": {"info": {"name": "video.mkv"}},
            "seeder": "true",
            "completedLength": "52428800",
            "totalLength": "52428800",
        }

        # 预先在 DB 创建对应下载任务
        db.create_download(f"aria2_{gid}", gid, "magnet:?xt=urn:btih:...")

        await client.sync_download_status(gid, aria2_status)

        client.download_handler.on_download_complete.assert_awaited_once()
        call_event = client.download_handler.on_download_complete.await_args[0][0]
        self.assertEqual(call_event["method"], "aria2.onBtDownloadComplete")
        self.assertEqual(call_event["params"][0]["gid"], gid)

    async def test_multi_file_torrent_handling(self):
        """测试多文件种子任务：多文件独立校验、多条上传记录创建与异步排队上传"""
        mock_upload_handler = MagicMock(spec=UploadHandler)
        mock_upload_handler.upload_to_telegram_with_load_balance = AsyncMock()

        handler = DownloadHandler(
            bot=MagicMock(),
            download_messages={},
            completed_gids=set(),
            upload_handler=mock_upload_handler,
        )

        gid = "gid_multifile_torrent"
        db.create_download(f"aria2_{gid}", gid, "magnet:?xt=urn:btih:multi")

        file1 = os.path.join(self._test_dir.name, "movie.mp4")
        file2 = os.path.join(self._test_dir.name, "subs.srt")
        with open(file1, "wb") as f:
            f.write(b"video data" * 100)
        with open(file2, "wb") as f:
            f.write(b"subtitle text" * 10)

        async def mock_tell_status(g):
            return {
                "gid": gid,
                "status": "complete",
                "totalLength": str(os.path.getsize(file1) + os.path.getsize(file2)),
                "completedLength": str(os.path.getsize(file1) + os.path.getsize(file2)),
                "files": [
                    {"path": file1},
                    {"path": file2},
                ],
            }

        with patch("configer.get_config_value", return_value=True):
            await handler.on_download_complete({"params": [{"gid": gid}]}, tell_status_func=mock_tell_status)

        # 稍微让出执行权，等待异步上传任务启动
        await asyncio.sleep(0.05)

        # 验证数据库中为两个文件分别创建了 upload 记录
        did = db.get_download_id_by_gid(gid)
        uploads = db.get_uploads_by_download(did)
        self.assertEqual(len(uploads), 2)

        # 验证两个文件均已提交给 upload_handler
        self.assertEqual(mock_upload_handler.upload_to_telegram_with_load_balance.call_count, 2)
        uploaded_paths = [
            call.args[0]
            for call in mock_upload_handler.upload_to_telegram_with_load_balance.call_args_list
        ]
        self.assertIn(file1, uploaded_paths)
        self.assertIn(file2, uploaded_paths)



    async def test_app_private_message_magnet_handling(self):
        """测试 Telegram 私聊接收 Base32 磁力链接全流程：租户绑定、Aria2 投递与入库"""
        from types import SimpleNamespace
        import app

        # 1. 创建具备专属存储频道的租户
        tg_id = 88776655
        chan_id = -10044556677
        tenant = db.create_tenant_user(
            username="test_magnet_tenant",
            password_hash="dummy_hash",
            role="user",
            tg_user_id=tg_id,
            bin_channel_id=chan_id,
        )

        # 2. 构造包含 Base32 磁力链接的 Telegram 私聊消息
        base32_magnet = "magnet:?xt=urn:btih:N4QWY3DPO5XXE3DENB2W45DFOIZT2MBM&dn=base32_movie.mp4"
        raw_msg = f"帮我离线下载: {base32_magnet} 多谢！"
        event = SimpleNamespace(
            sender_id=tg_id,
            raw_text=raw_msg,
            media=None,
            reply=AsyncMock(),
        )

        mock_client = MagicMock()
        mock_client.add_uri = AsyncMock(return_value={"result": "gid_app_base32_123"})

        with patch.object(app, "client", mock_client), \
             patch.object(app, "ADMIN_ID", 11111111), \
             patch("app._is_authorized_tg_user", return_value=True):
            await app.handle_private_message(event)

        # 3. 验证调用了 Aria2 add_uri，入参为提取并清洗后的磁力链接
        mock_client.add_uri.assert_awaited_once_with(uris=[base32_magnet])

        # 4. 验证数据库中下载任务正确生成，并绑定了租户 ID 和专属存储频道
        did = db.get_download_id_by_gid("gid_app_base32_123")
        self.assertIsNotNone(did)
        rec = db.get_download_by_id(did)
        self.assertEqual(rec["user_id"], tenant["id"])
        self.assertEqual(rec["target_channel_id"], chan_id)
        self.assertEqual(rec["source_url"], base32_magnet)


if __name__ == "__main__":
    unittest.main()

