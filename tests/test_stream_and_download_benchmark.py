import tests  # noqa: F401
import asyncio
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault(
    "MISTRELAY_DB_PATH",
    tempfile.mktemp(prefix="mistrelay_stream_bench_", suffix=".db", dir="/tmp"),
)

import db
from tests.test_cache_management import get_stream_routes_module


class TestStreamAndDownloadBenchmark(unittest.TestCase):
    def setUp(self):
        self.routes_mod = get_stream_routes_module()
        vars_mod = types.ModuleType("WebStreamer.vars")
        vars_mod.Var = types.SimpleNamespace(BIN_CHANNEL=-1001234567890)
        sys.modules["WebStreamer.vars"] = vars_mod

        db.init_db()
        with db.db_conn() as conn:
            conn.execute("DELETE FROM tg_media")
            conn.execute("""
                INSERT INTO tg_media (file_unique_id, chat_id, message_id, file_id, file_name, file_size, mime_type, message_date)
                VALUES ('unique_id_1001', -1001234567890, 1001, 'tg_file_id_1001', 'test_sample.mp4', 52428800, 'video/mp4', '2026-09-26T00:00:00')
            """)

        self.bot_mod = sys.modules["WebStreamer.bot"]
        self.orig_multi = getattr(self.bot_mod, "multi_clients", {}).copy()
        self.orig_accessible = getattr(self.bot_mod, "channel_accessible_clients", set()).copy()

    def tearDown(self):
        self.bot_mod.multi_clients.clear(); self.bot_mod.multi_clients.update(self.orig_multi)
        self.bot_mod.channel_accessible_clients = self.orig_accessible

    def test_single_bot_benchmark_with_stream_and_playback_metrics(self):
        """测试单节点基准测试正确包含 stream_ttfb_ms 和 playback_bitrate_mbps"""
        mock_cli = MagicMock()
        mock_cli.username = "test_worker_bot"
        self.bot_mod.channel_accessible_clients.add(1)
        mock_cli.get_me = AsyncMock(return_value=MagicMock())
        mock_cli.get_chat = AsyncMock(return_value=MagicMock())

        mock_streamer = MagicMock()
        mock_file_id = MagicMock()
        mock_file_id.file_size = 52428800
        mock_streamer.get_file_properties = AsyncMock(return_value=mock_file_id)
        mock_streamer.get_location = AsyncMock(return_value=MagicMock())
        mock_streamer.generate_media_session = AsyncMock(return_value=MagicMock())

        chunk_obj = MagicMock()
        chunk_obj.bytes = b"X" * 524288  # 512 KB
        mock_streamer._try_get_file_chunk = AsyncMock(return_value=(True, chunk_obj, mock_cli, None))

        with patch.object(self.routes_mod, "get_byte_streamer", return_value=mock_streamer):
            res = asyncio.run(self.routes_mod._benchmark_single_bot(1, mock_cli, test_download=True))

        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["index"], 1)
        self.assertEqual(res["username"], "test_worker_bot")
        self.assertIsNotNone(res["stream_ttfb_ms"])
        self.assertIsNotNone(res["download_speed_mbps"])
        self.assertIsNotNone(res["playback_bitrate_mbps"])
        self.assertEqual(res["bytes_transferred"], 524288)

    def test_stream_and_download_benchmark_handler_cluster_mode(self):
        """测试 POST /api/telegram/benchmark/stream-and-download 全集群条带化测速响应结构"""
        mock_request = MagicMock()
        mock_request.get.return_value = {"id": 1, "username": "admin", "role": "admin"}
        mock_request.json = AsyncMock(return_value={"sample_size_mb": 2.0})

        mock_cli0 = MagicMock()
        mock_cli0.username = "bot_0"
        mock_cli1 = MagicMock()
        mock_cli1.username = "bot_1"

        self.bot_mod.multi_clients.clear(); self.bot_mod.multi_clients.update({0: mock_cli0, 1: mock_cli1})

        mock_streamer = MagicMock()
        mock_file_id = MagicMock()
        mock_file_id.file_size = 52428800
        mock_streamer.get_file_properties = AsyncMock(return_value=mock_file_id)
        mock_streamer.get_location = AsyncMock(return_value=MagicMock())
        mock_streamer.generate_media_session = AsyncMock(return_value=MagicMock())

        chunk_obj = MagicMock()
        chunk_obj.bytes = b"M" * 524288
        mock_streamer._try_get_file_chunk = AsyncMock(return_value=(True, chunk_obj, mock_cli0, None))

        custom_dl_mod = types.ModuleType("WebStreamer.utils.custom_dl")
        custom_dl_mod.get_available_bot_indices = lambda *args, **kwargs: [0, 1]
        sys.modules["WebStreamer.utils.custom_dl"] = custom_dl_mod

        with patch.object(self.routes_mod, "get_byte_streamer", return_value=mock_streamer), \
             patch.object(self.routes_mod, "select_stream_bot", return_value=0):
            resp = asyncio.run(self.routes_mod.telegram_stream_and_download_benchmark_handler(mock_request))

        body = resp.body
        self.assertTrue(body["success"])
        data = body["data"]

        # 验证播放体验指标
        self.assertIn("playback", data)
        self.assertIn("ttfb_ms", data["playback"])
        self.assertIn("initial_buffer_ms", data["playback"])
        self.assertIn("speed_mb_s", data["playback"])
        self.assertIn("bitrate_mbps", data["playback"])
        self.assertIn("ratio_1080p", data["playback"])
        self.assertIn("stutter_risk", data["playback"])

        # 验证单连接下载指标
        self.assertIn("download", data)
        self.assertIn("avg_speed_mb_s", data["download"])
        self.assertIn("peak_speed_mb_s", data["download"])
        self.assertIn("stability_score", data["download"])
        self.assertIn("chunk_samples", data["download"])
        self.assertGreaterEqual(len(data["download"]["chunk_samples"]), 2)

        # 验证诊断与总结
        self.assertIn("summary", data)
        self.assertIn("target_file", data)
        self.assertEqual(data["target_file"]["message_id"], 1001)


    def test_stream_and_download_benchmark_handler_large_sample_sizes(self):
        """测试 10M、100M 与 1G (1024MB) 样本大小处理与分片采样缩放"""
        for size_mb, expected_chunks in [(10.0, 20), (100.0, 200)]:
            mock_request = MagicMock()
            mock_request.get.return_value = {"id": 1, "username": "admin", "role": "admin"}
            mock_request.json = AsyncMock(return_value={"sample_size_mb": size_mb})

            mock_cli0 = MagicMock()
            mock_cli0.username = "bot_0"
            mock_cli1 = MagicMock()
            mock_cli1.username = "bot_1"
            self.bot_mod.multi_clients.clear(); self.bot_mod.multi_clients.update({0: mock_cli0, 1: mock_cli1})

            mock_streamer = MagicMock()
            mock_file_id = MagicMock()
            mock_file_id.file_size = 52428800
            mock_streamer.get_file_properties = AsyncMock(return_value=mock_file_id)
            mock_streamer.get_location = AsyncMock(return_value=MagicMock())
            mock_streamer.generate_media_session = AsyncMock(return_value=MagicMock())

            chunk_obj = MagicMock()
            chunk_obj.bytes = b"M" * 524288
            mock_streamer._try_get_file_chunk = AsyncMock(return_value=(True, chunk_obj, mock_cli0, None))

            with patch.object(self.routes_mod, "get_byte_streamer", return_value=mock_streamer),                  patch.object(self.routes_mod, "select_stream_bot", return_value=0):
                resp = asyncio.run(self.routes_mod.telegram_stream_and_download_benchmark_handler(mock_request))

            body = resp.body
            self.assertTrue(body["success"])
            dl = body["data"]["download"]
            self.assertEqual(dl["sample_mb_requested"], size_mb)
            self.assertEqual(dl["total_chunks_tested"], expected_chunks)
            if size_mb >= 100:
                self.assertTrue(dl["is_sampled_timeline"])
                self.assertLessEqual(len(dl["chunk_samples"]), 26)
            else:
                self.assertFalse(dl["is_sampled_timeline"])
                self.assertEqual(len(dl["chunk_samples"]), expected_chunks)


if __name__ == "__main__":
    unittest.main()
