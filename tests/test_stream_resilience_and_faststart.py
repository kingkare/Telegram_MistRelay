import unittest
import asyncio
import os
import tempfile
from unittest.mock import MagicMock, AsyncMock, patch
from pyrogram import raw
import WebStreamer.bot as bot_mod
from WebStreamer.utils.custom_dl import (
    ByteStreamer,
    _global_bot_ctx_cache,
    clear_global_bot_ctx_cache,
)
from private_channel_harvester import optimize_video_for_streaming


def _make_upload_file(data: bytes):
    f_cls = getattr(getattr(raw.types, "upload", None), "File", None)
    if f_cls is not None:
        inst = f_cls.__new__(f_cls) if hasattr(f_cls, "__new__") else f_cls()
        inst.bytes = data
        return inst
    obj = MagicMock()
    obj.bytes = data
    return obj


class TestStreamResilienceAndFaststart(unittest.TestCase):
    def setUp(self):
        clear_global_bot_ctx_cache()
        bot_mod.active_user_streams = 0
        bot_mod._stream_id_counter = 0

    def tearDown(self):
        clear_global_bot_ctx_cache()

    def test_global_bot_ctx_cache_reuse_across_ranges(self):
        """测试跨 Range 请求时全局上下文缓存复用，避免重复 MTProto get_messages 往返"""
        async def _run():
            mock_client_0 = MagicMock()
            mock_client_1 = MagicMock()
            streamer_0 = ByteStreamer.for_client(mock_client_0)
            streamer_1 = ByteStreamer.for_client(mock_client_1)

            streamer_0.get_file_properties = AsyncMock(return_value=MagicMock(dc_id=5))
            streamer_0.get_location = AsyncMock(return_value="loc_0")
            streamer_1.get_file_properties = AsyncMock(return_value=MagicMock(dc_id=5))
            streamer_1.get_location = AsyncMock(return_value="loc_1")

            with patch("WebStreamer.utils.custom_dl.multi_clients", {0: mock_client_0, 1: mock_client_1}):
                # 第一次调用 _prepare_bot_context：应调用 get_file_properties 和 get_location
                ctx1 = await streamer_0._prepare_bot_context(1, message_id=888, default_file_id=MagicMock(), default_location="default")
                self.assertIsNotNone(ctx1)
                self.assertEqual(streamer_1.get_file_properties.call_count, 1)
                self.assertEqual(streamer_1.get_location.call_count, 1)

                # 第二次调用（模拟下一个 Range 请求到达）：直接命中全局缓存，不触发网络调用
                ctx2 = await streamer_0._prepare_bot_context(1, message_id=888, default_file_id=MagicMock(), default_location="default")
                self.assertEqual(ctx1, ctx2)
                self.assertEqual(streamer_1.get_file_properties.call_count, 1)
                self.assertEqual(streamer_1.get_location.call_count, 1)

                # clear_global_bot_ctx_cache(888) 后再次调用应刷新
                clear_global_bot_ctx_cache(888)
                ctx3 = await streamer_0._prepare_bot_context(1, message_id=888, default_file_id=MagicMock(), default_location="default")
                self.assertEqual(streamer_1.get_file_properties.call_count, 2)

        asyncio.run(_run())

    def test_try_get_file_chunk_shield_protection_on_cancel(self):
        """测试客户端 Seek / 突然断连导致任务被 cancel 时，asyncio.shield 保证底层 MTProto 请求在后台平稳收尾"""
        async def _run():
            mock_client = MagicMock()
            streamer = ByteStreamer.for_client(mock_client)

            mock_session = MagicMock()
            invoke_started = asyncio.Event()
            invoke_finished = asyncio.Event()

            async def mock_invoke(req):
                invoke_started.set()
                try:
                    await asyncio.sleep(0.08)
                    invoke_finished.set()
                    return _make_upload_file(b"chunk_data")
                except asyncio.CancelledError:
                    # 如果 shield 生效，底层的 invoke 不应该被 cancel
                    self.fail("底层 MTProto session.invoke 被上层 Task Cancellation 错误打断！")
                    raise

            mock_session.invoke = mock_invoke
            streamer.generate_media_session = AsyncMock(return_value=mock_session)

            async def _caller_task():
                return await streamer._try_get_file_chunk(
                    client=mock_client,
                    client_index=0,
                    file_id=MagicMock(dc_id=5),
                    location="loc",
                    offset=0,
                    chunk_size=1024,
                    timeout=5.0,
                )

            t = asyncio.create_task(_caller_task())
            await invoke_started.wait()

            # 模拟 HTTP 客户端 Seek，上层取消 task
            t.cancel()

            with self.assertRaises(asyncio.CancelledError):
                await t

            # 验证底层 invoke 依然在后台平稳完成，没有被撕裂中断
            await asyncio.wait_for(invoke_finished.wait(), timeout=1.0)
            self.assertTrue(invoke_finished.is_set())

        asyncio.run(_run())

    def test_optimize_video_for_streaming_faststart(self):
        """测试 optimize_video_for_streaming 执行 faststart 优化或小文件安全跳过"""
        async def _run():
            with tempfile.TemporaryDirectory() as td:
                # 1. 小文件 (< 4KB) 跳过
                small_path = os.path.join(td, "small.mp4")
                with open(small_path, "wb") as f:
                    f.write(b"tiny_fake_video_data")
                res = await optimize_video_for_streaming(small_path)
                self.assertEqual(res, small_path)
                with open(small_path, "rb") as f:
                    self.assertEqual(f.read(), b"tiny_fake_video_data")

                # 2. 生成真实测试 MP4 并验证 faststart 优化
                src_path = os.path.join(td, "real.mp4")
                cmd = [
                    "ffmpeg", "-y", "-v", "error",
                    "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=15",
                    "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
                    "-c:v", "libx264", "-c:a", "aac",
                    src_path
                ]
                p = await asyncio.create_subprocess_exec(*cmd)
                await p.communicate()
                self.assertEqual(p.returncode, 0)
                orig_size = os.path.getsize(src_path)
                self.assertGreater(orig_size, 4096)

                logs = []
                opt_res = await optimize_video_for_streaming(src_path, log_fn=logs.append)
                self.assertEqual(opt_res, src_path)
                self.assertTrue(os.path.exists(src_path))
                self.assertGreater(os.path.getsize(src_path), 4096)
                self.assertTrue(any("faststart" in l for l in logs))

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
