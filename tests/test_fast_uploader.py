import asyncio
import hashlib
import io
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pyrogram
from pyrogram import raw
from pyrogram.methods.advanced.save_file import SaveFile

from WebStreamer.utils.fast_uploader import (
    MAX_BIG_FILE_SESSIONS,
    MAX_SMALL_FILE_SESSIONS,
    UPLOAD_PART_SIZE,
    UploadSessionPool,
    close_upload_sessions,
    fast_save_file,
    patch_pyrogram_uploader,
    reset_upload_progress_hook,
    set_upload_progress_hook,
)


class DummySession:
    def __init__(self, idx: int):
        self.idx = idx
        self.invoked_rpcs = []
        self.is_started = asyncio.Event()
        self.is_started.set()
        self.connection = MagicMock()
        self.connection.protocol = MagicMock(closed=False)
        self.stopped = False

    async def start(self):
        self.is_started.set()

    async def stop(self):
        self.stopped = True
        self.is_started.clear()

    async def invoke(self, rpc):
        await asyncio.sleep(0.002)
        self.invoked_rpcs.append(rpc)
        return True


class TestFastUploader(unittest.TestCase):
    def test_fast_save_file_none_path(self):
        """验证传入 None 时直接返回 None（兼容 send_video thumb=None）"""
        async def _run():
            client = MagicMock()
            res = await fast_save_file(client, None)
            self.assertIsNone(res)

        asyncio.run(_run())

    def test_fast_save_file_small_file_md5_and_parts(self):
        """验证小文件 (<= 10MB) 采用 2 通道并发、SaveFilePart 及准确的 MD5 校验和"""
        async def _run():
            data = os.urandom(UPLOAD_PART_SIZE * 2 + 12345)  # 3 parts
            expected_md5 = hashlib.md5(data).hexdigest()

            created_sessions = []

            async def _fake_create_single(cls_or_client):
                s = DummySession(len(created_sessions))
                created_sessions.append(s)
                return s

            client = MagicMock()
            client.rnd_id.return_value = 987654321
            client.me = MagicMock(is_premium=False)

            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
                tf.write(data)
                temp_path = tf.name

            try:
                with patch.object(
                    UploadSessionPool,
                    "_create_single_session",
                    side_effect=_fake_create_single,
                ):
                    res = await fast_save_file(client, temp_path)

                self.assertIsInstance(res, raw.types.InputFile)
                self.assertEqual(res.id, 987654321)
                self.assertEqual(res.parts, 3)
                self.assertEqual(res.md5_checksum, expected_md5)
                self.assertEqual(len(created_sessions), MAX_SMALL_FILE_SESSIONS)

                all_rpcs = [rpc for s in created_sessions for rpc in s.invoked_rpcs]
                self.assertEqual(len(all_rpcs), 3)
                for rpc in all_rpcs:
                    self.assertIsInstance(rpc, raw.functions.upload.SaveFilePart)

                reconstructed = b"".join(
                    rpc.bytes for rpc in sorted(all_rpcs, key=lambda r: r.file_part)
                )
                self.assertEqual(reconstructed, data)
            finally:
                await close_upload_sessions(client)
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

        asyncio.run(_run())

    def test_fast_save_file_big_file_8_channels(self):
        """验证大文件 (> 10MB) 自动启用 8 通道并发、SaveBigFilePart 并返回 InputFileBig"""
        async def _run():
            # 11 MB -> 22 个 512KB 分片
            total_size = 11 * 1024 * 1024
            data = b"A" * total_size
            bio = io.BytesIO(data)
            bio.name = "/tmp/big_movie.mp4"

            created_sessions = []

            async def _fake_create_single(cls_or_client):
                s = DummySession(len(created_sessions))
                created_sessions.append(s)
                return s

            client = MagicMock()
            client.rnd_id.return_value = 1122334455
            client.me = MagicMock(is_premium=False)

            try:
                with patch.object(
                    UploadSessionPool,
                    "_create_single_session",
                    side_effect=_fake_create_single,
                ):
                    res = await fast_save_file(client, bio)

                self.assertIsInstance(res, raw.types.InputFileBig)
                self.assertEqual(res.id, 1122334455)
                self.assertEqual(res.parts, 22)
                self.assertEqual(res.name, "big_movie.mp4")
                self.assertEqual(len(created_sessions), MAX_BIG_FILE_SESSIONS)

                all_rpcs = [rpc for s in created_sessions for rpc in s.invoked_rpcs]
                self.assertEqual(len(all_rpcs), 22)
                parts_seen = sorted(rpc.file_part for rpc in all_rpcs)
                self.assertEqual(parts_seen, list(range(22)))
                for rpc in all_rpcs:
                    self.assertIsInstance(rpc, raw.functions.upload.SaveBigFilePart)
                    self.assertEqual(rpc.file_total_parts, 22)
            finally:
                await close_upload_sessions(client)

        asyncio.run(_run())

    def test_fast_save_file_retry_on_transient_failure(self):
        """验证单个分片传输遇到临时网络错误时自动替换会话并重试成功"""
        async def _run():
            data = b"X" * (UPLOAD_PART_SIZE * 2)
            bio = io.BytesIO(data)
            bio.name = "retry_test.bin"

            fail_once = {"triggered": False}
            created_sessions = []

            class FlakySession(DummySession):
                async def invoke(self, rpc):
                    if rpc.file_part == 1 and not fail_once["triggered"]:
                        fail_once["triggered"] = True
                        raise ConnectionError("Simulated socket drop")
                    return await super().invoke(rpc)

            async def _fake_create_single(cls_or_client):
                s = FlakySession(len(created_sessions))
                created_sessions.append(s)
                return s

            client = MagicMock()
            client.rnd_id.return_value = 55667788
            client.me = MagicMock(is_premium=False)

            try:
                with patch.object(
                    UploadSessionPool,
                    "_create_single_session",
                    side_effect=_fake_create_single,
                ):
                    res = await fast_save_file(client, bio)

                self.assertTrue(fail_once["triggered"])
                self.assertIsInstance(res, raw.types.InputFile)
                self.assertEqual(res.parts, 2)
                # 初始 2 个会话 + 替换 1 个会话 = 3 个
                self.assertGreaterEqual(len(created_sessions), 3)
            finally:
                await close_upload_sessions(client)

        asyncio.run(_run())

    def test_progress_callback_and_context_hook(self):
        """验证显式 progress 回调与 ContextVar 进度钩子均能准确接收进度通知"""
        async def _run():
            data = b"P" * (UPLOAD_PART_SIZE * 3)
            bio = io.BytesIO(data)
            bio.name = "prog.mp4"

            client = MagicMock()
            client.rnd_id.return_value = 999888
            client.me = MagicMock(is_premium=False)
            client.invoke = AsyncMock(return_value=True)

            explicit_calls = []
            hook_calls = []

            async def _prog_cb(cur, tot):
                explicit_calls.append((cur, tot))

            def _ctx_hook(cur, tot, conc):
                hook_calls.append((cur, tot, conc))

            token = set_upload_progress_hook(_ctx_hook)
            try:
                res = await fast_save_file(client, bio, progress=_prog_cb)
                self.assertEqual(res.parts, 3)
                self.assertTrue(len(explicit_calls) >= 1)
                self.assertEqual(explicit_calls[-1], (len(data), len(data)))
                self.assertTrue(len(hook_calls) >= 1)
                self.assertEqual(hook_calls[-1][0], len(data))
                self.assertEqual(hook_calls[-1][1], len(data))
            finally:
                reset_upload_progress_hook(token)
                await close_upload_sessions(client)

        asyncio.run(_run())

    def test_patch_pyrogram_uploader(self):
        """验证 patch_pyrogram_uploader 将 fast_save_file 挂载至 Pyrogram Client"""
        patch_pyrogram_uploader()
        self.assertIs(pyrogram.Client.save_file, fast_save_file)
        self.assertIs(SaveFile.save_file, fast_save_file)



    def test_upgrade_pyrogram_crypto_executor(self):
        """验证 crypto_executor 成功被升级为多核并发线程池 (>=8 线程)"""
        from WebStreamer.utils.fast_uploader import upgrade_pyrogram_crypto_executor
        workers = upgrade_pyrogram_crypto_executor()
        self.assertGreaterEqual(workers, 8)
        self.assertGreaterEqual(pyrogram.crypto_executor._max_workers, 8)

    def test_tune_mtproto_session_socket(self):
        """验证 tune_mtproto_session_socket 为媒体套接字开启 TCP_NODELAY 与 2MB 缓冲区"""
        import socket
        from WebStreamer.utils.fast_uploader import tune_mtproto_session_socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            mock_session = MagicMock()
            mock_session.connection.protocol.socket = sock
            tuned = tune_mtproto_session_socket(mock_session)
            self.assertTrue(tuned)
            self.assertEqual(sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY), 1)
            self.assertGreaterEqual(sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF), 2000000)
        finally:
            sock.close()

    def test_fast_save_file_huge_file_10_channels(self):
        """验证超大文件 (>100MB) 自动升级为 10 通道极速并发"""
        import math
        from WebStreamer.utils.fast_uploader import MAX_HUGE_FILE_SESSIONS, HUGE_FILE_THRESHOLD
        async def _run():
            total_size = 102 * 1024 * 1024
            total_parts = math.ceil(total_size / UPLOAD_PART_SIZE)
            
            created_sessions = []
            async def _fake_create(cls_or_client):
                s = DummySession(len(created_sessions))
                created_sessions.append(s)
                return s

            client = MagicMock()
            client.rnd_id.return_value = 1234567890
            client.me = MagicMock(is_premium=False)

            bio = MagicMock()
            bio.tell.return_value = total_size
            bio.name = "huge_video.mp4"
            bio.read.side_effect = [b"H" * UPLOAD_PART_SIZE for _ in range(total_parts)] + [b""]

            try:
                with patch.object(UploadSessionPool, "_create_single_session", side_effect=_fake_create):
                    res = await fast_save_file(client, bio)

                self.assertIsInstance(res, raw.types.InputFileBig)
                self.assertEqual(res.parts, total_parts)
                self.assertEqual(len(created_sessions), MAX_HUGE_FILE_SESSIONS)
                self.assertEqual(MAX_HUGE_FILE_SESSIONS, 10)
            finally:
                await close_upload_sessions(client)

        asyncio.run(_run())

    def test_preuploaded_cache_instant_hit(self):
        """验证预上传缓存注册后，fast_save_file 零等待秒级返回"""
        from WebStreamer.utils.fast_uploader import register_preuploaded_file, get_preuploaded_file
        dummy_input = raw.types.InputFileBig(id=778899, parts=10, name="cached.mp4")
        test_path = "/tmp/fake_preupload_test.mp4"

        register_preuploaded_file(test_path, dummy_input)

        async def _run():
            client = MagicMock()
            res = await fast_save_file(client, test_path)
            self.assertIs(res, dummy_input)

        asyncio.run(_run())

    def test_upload_session_pool_exclusive_checkout(self):
        """验证多文件/相册并发上传时，UploadSessionPool 为不同任务独占借出互不干扰的 Session"""
        async def _run():
            client = MagicMock()
            created = []
            async def _fake_create(c):
                s = DummySession(len(created))
                created.append(s)
                return s

            with patch.object(UploadSessionPool, "_create_single_session", side_effect=_fake_create):
                s1 = await UploadSessionPool.acquire_sessions(client, 8)
                self.assertEqual(len(s1), 8)
                s2 = await UploadSessionPool.acquire_sessions(client, 2)
                self.assertEqual(len(s2), 2)
                self.assertEqual(len(set(s1) & set(s2)), 0)
                self.assertEqual(len(created), 10)

                UploadSessionPool.release_sessions(client, s2)
                s3 = await UploadSessionPool.acquire_sessions(client, 2)
                self.assertEqual(set(s3), set(s2))
                self.assertEqual(len(created), 10)

                UploadSessionPool.release_sessions(client, s1)
                UploadSessionPool.release_sessions(client, s3)
            await close_upload_sessions(client)

        asyncio.run(_run())

if __name__ == "__main__":
    unittest.main()
