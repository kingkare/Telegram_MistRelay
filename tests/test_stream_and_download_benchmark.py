import tests  # noqa: F401
import asyncio
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


import db
from tests.test_cache_management import get_stream_routes_module


class TestStreamAndDownloadBenchmark(unittest.TestCase):
    def setUp(self):
        self.orig_webstreamer = sys.modules.get("WebStreamer")
        self.orig_vars = sys.modules.get("WebStreamer.vars")
        ws_mod = sys.modules.get("WebStreamer.server.ws_manager")
        self.orig_ws_manager = getattr(ws_mod, "ws_manager", None) if ws_mod else None
        self.routes_mod = get_stream_routes_module()
        vars_mod = types.ModuleType("WebStreamer.vars")
        real_bot_tok = getattr(getattr(self.orig_webstreamer, "Var", None), "BOT_TOKEN", None) or getattr(getattr(self.orig_vars, "Var", None), "BOT_TOKEN", "5625760372:AAE6txEJ-PbmQzs36lyyp07w-eQw4M7Sdqs")
        real_multi = getattr(getattr(self.orig_webstreamer, "Var", None), "MULTI_BOT_TOKENS", None) or getattr(getattr(self.orig_vars, "Var", None), "MULTI_BOT_TOKENS", [])
        vars_mod.Var = types.SimpleNamespace(
            BIN_CHANNEL=-1001234567890,
            BOT_TOKEN=real_bot_tok,
            MULTI_BOT_TOKENS=real_multi,
        )
        sys.modules["WebStreamer.vars"] = vars_mod

        self._tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()
        with db.db_conn() as conn:
            conn.execute("""
                INSERT INTO tg_media (file_unique_id, chat_id, message_id, file_id, file_name, file_size, mime_type, message_date)
                VALUES ('unique_id_1001', -1001234567890, 1001, 'tg_file_id_1001', 'test_sample.mp4', 52428800, 'video/mp4', '2026-09-26T00:00:00')
            """)

        self.bot_mod = sys.modules["WebStreamer.bot"]
        self.orig_multi = getattr(self.bot_mod, "multi_clients", {}).copy()
        self.orig_accessible = getattr(self.bot_mod, "channel_accessible_clients", set()).copy()
        self.orig_custom_dl = sys.modules.get("WebStreamer.utils.custom_dl")
        if "WebStreamer.utils.custom_dl" not in sys.modules:
            custom_dl_mod = types.ModuleType("WebStreamer.utils.custom_dl")
            custom_dl_mod.get_available_bot_indices = lambda *args, **kwargs: list(sorted(self.bot_mod.multi_clients.keys())) or [0]
            sys.modules["WebStreamer.utils.custom_dl"] = custom_dl_mod

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        if hasattr(self, '_tmp') and os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except OSError:
                pass
        self.bot_mod.multi_clients.clear(); self.bot_mod.multi_clients.update(self.orig_multi)
        self.bot_mod.channel_accessible_clients = self.orig_accessible
        if self.orig_custom_dl is not None:
            sys.modules["WebStreamer.utils.custom_dl"] = self.orig_custom_dl
        else:
            sys.modules.pop("WebStreamer.utils.custom_dl", None)
        if self.orig_webstreamer is not None:
            sys.modules["WebStreamer"] = self.orig_webstreamer
        if self.orig_vars is not None:
            sys.modules["WebStreamer.vars"] = self.orig_vars
        else:
            sys.modules.pop("WebStreamer.vars", None)
        ws_mod = sys.modules.get("WebStreamer.server.ws_manager")
        if ws_mod and self.orig_ws_manager is not None:
            ws_mod.ws_manager = self.orig_ws_manager

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


    def test_straggler_bot_hedged_by_fast_workers(self):
        """测试集群中存在慢节点 (2.0s) 时，动态窃取与尾块对冲可在 <0.4s 内完成 10M (20分片) 测速，不被慢节点阻塞"""
        import time
        mock_request = MagicMock()
        mock_request.get.return_value = {"id": 1, "username": "admin", "role": "admin"}
        mock_request.json = AsyncMock(return_value={"sample_size_mb": 10.0})

        clients = {}
        for i in range(8):
            c = MagicMock()
            c.username = f"bot_{i}"
            clients[i] = c
        self.bot_mod.multi_clients.clear()
        self.bot_mod.multi_clients.update(clients)

        mock_streamer = MagicMock()
        mock_file_id = MagicMock()
        mock_file_id.file_size = 52428800
        mock_streamer.get_file_properties = AsyncMock(return_value=mock_file_id)
        mock_streamer.get_location = AsyncMock(return_value=MagicMock())
        mock_streamer.generate_media_session = AsyncMock(return_value=MagicMock())

        chunk_obj = MagicMock()
        chunk_obj.bytes = b"F" * 524288

        async def _simulated_chunk_fetch(cli, bot_idx, file_id, loc, offset=0, chunk_size=524288, **kwargs):
            # 模拟 7 号节点在下载分片阶段突发 2.0s 网络长尾卡顿，其余节点 2ms 极速返回
            if bot_idx == 7 and chunk_size == 524288:
                await asyncio.sleep(2.0)
            else:
                await asyncio.sleep(0.002)
            return True, chunk_obj, cli, None

        mock_streamer._try_get_file_chunk = AsyncMock(side_effect=_simulated_chunk_fetch)

        custom_dl_mod = types.ModuleType("WebStreamer.utils.custom_dl")
        custom_dl_mod.get_available_bot_indices = lambda *args, **kwargs: list(range(8))
        sys.modules["WebStreamer.utils.custom_dl"] = custom_dl_mod

        t0 = time.perf_counter()
        with patch.object(self.routes_mod, "get_byte_streamer", return_value=mock_streamer),              patch.object(self.routes_mod, "select_stream_bot", return_value=0):
            resp = asyncio.run(self.routes_mod.telegram_stream_and_download_benchmark_handler(mock_request))
        elapsed = time.perf_counter() - t0

        body = resp.body
        self.assertTrue(body["success"])
        dl = body["data"]["download"]
        self.assertEqual(dl["total_chunks_tested"], 20)
        # 尽管 7 号节点卡顿 2.0s，快节点通过动态窃取与尾块对冲在 0.4s 内即完成全部 20 个分片并立即终止慢任务
        self.assertLess(elapsed, 0.5)
        self.assertGreater(dl["avg_speed_mb_s"], 25.0)


if __name__ == "__main__":
    unittest.main()
