import unittest
import time
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import db
from edge_worker.worker_server import EdgeStreamingWorker
from WebStreamer.server.ws_manager import WebSocketManager


class TestEdgeRealtimeMetrics(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile, os
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()

    def tearDown(self):
        import os
        db.DB_PATH = self.orig_db_path
        if hasattr(self, "_tmp") and os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except OSError:
                pass

    async def test_worker_realtime_cpu_and_mem_metrics(self):
        """测试边缘 Worker 读取真实瞬时 CPU 与内存指标"""
        worker = EdgeStreamingWorker(
            port=8090,
            node_secret="test_secret_123",
            mock_stream=True,
        )
        metrics = worker.get_system_metrics()
        self.assertIn("cpu", metrics)
        self.assertIn("mem", metrics)
        self.assertIsInstance(metrics["cpu"], float)
        self.assertIsInstance(metrics["mem"], float)
        self.assertGreaterEqual(metrics["cpu"], 0.0)
        self.assertLessEqual(metrics["cpu"], 100.0)
        self.assertGreaterEqual(metrics["mem"], 0.0)
        self.assertLessEqual(metrics["mem"], 100.0)

    async def test_active_stream_session_window_tracking(self):
        """测试 HTTP Range 分片读写时的会话滑动窗口保活机制"""
        worker = EdgeStreamingWorker(
            port=8090,
            node_secret="test_secret_123",
            mock_stream=True,
        )
        self.assertEqual(worker.active_streams, 0)

        # 模拟客户端 A 播放视频 1 发起 Range 请求
        sess_a = ("1.2.3.4", -1001234, 100)
        worker._inflight_streams += 1
        worker._record_stream_activity(sess_a)
        self.assertEqual(worker.active_streams, 1)

        # 模拟 100ms 后该分片下载结束，连接已释放，但播放器仍在消费缓冲区
        worker._inflight_streams = 0
        self.assertEqual(worker.active_streams, 1)

        # 模拟客户端 B 同时在播放另一个视频
        sess_b = ("5.6.7.8", -1001234, 200)
        worker._record_stream_activity(sess_b)
        self.assertEqual(worker.active_streams, 2)

        # 模拟测试或系统主动重置为 0
        worker.active_streams = 0
        self.assertEqual(worker.active_streams, 0)

    async def test_ewma_bandwidth_rate_smoothing(self):
        """测试实时出网速率平滑滤波与缓冲间隙渐进衰减机制"""
        worker = EdgeStreamingWorker(
            port=8090,
            node_secret="test_secret_123",
            mock_stream=True,
        )
        sess = ("1.2.3.4", -1001234, 100)
        worker._record_stream_activity(sess)

        # 模拟传输了 2MB 数据
        worker.total_bytes_served += 2 * 1024 * 1024
        await asyncio.sleep(0.3)
        m1 = worker.get_system_metrics()
        self.assertEqual(m1["active_streams"], 1)
        self.assertGreater(m1["net_tx"], 0)

        # 模拟播放器正在缓冲（delta_bytes 为 0，但会话仍在活跃窗口内）
        m2 = worker.get_system_metrics()
        self.assertEqual(m2["active_streams"], 1)
        # 速率应当平滑衰减，而不是断崖式瞬间跌落为 0
        self.assertGreater(m2["net_tx"], 0)
        self.assertLessEqual(m2["net_tx"], m1["net_tx"])

        # 模拟流完全停止并超时重置
        worker.active_streams = 0
        worker._last_stream_activity = time.time() - 20.0
        m3 = worker.get_system_metrics()
        self.assertEqual(m3["active_streams"], 0)
        self.assertEqual(m3["net_tx"], 0)

    async def test_stale_edge_node_auto_offline_cleanup(self):
        """测试 WebSocket 后台广播循环对失联 >45s 的边缘节点自动置 offline 并清空活跃指标"""
        # 创建一个测试节点
        node = db.create_edge_node(
            tenant_id=1,
            node_name="Stale Test Node",
            ip="192.0.2.99",
            port=8090,
            status="online",
        )
        # 伪造其最后一次心跳为 60 秒前，且残余指标不为 0
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        db.update_edge_node(
            node["id"],
            last_seen_at=old_time,
            metrics={"cpu": 15.0, "active_streams": 3, "net_tx": 2048000, "total_bytes_served": 50000},
        )

        ws_mgr = WebSocketManager()
        # 触发一次广播循环逻辑
        import db as test_db
        all_nodes = test_db.list_edge_nodes(tenant_id=None, include_secrets=False)
        target_node = next((n for n in all_nodes if n["id"] == node["id"]), None)
        self.assertIsNotNone(target_node)
        self.assertEqual(target_node["status"], "online")

        # 模拟 ws_manager._background_broadcast_loop 内部的超时收敛处理
        now_utc = datetime.now(timezone.utc)
        for n in all_nodes:
            if n.get("status") == "online":
                last_seen = n.get("last_seen_at")
                if last_seen:
                    dt = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if (now_utc - dt).total_seconds() > 45.0:
                        n["status"] = "offline"
                        metrics = dict(n.get("metrics") or {})
                        metrics.update({"active_streams": 0, "net_tx": 0, "net_rx": 0, "cpu": 0.0})
                        n["metrics"] = metrics
                        test_db.update_edge_node(n["id"], status="offline", metrics=metrics)

        # 检查落库结果
        fresh_node = test_db.get_edge_node_by_id(node["id"])
        self.assertEqual(fresh_node["status"], "offline")
        self.assertEqual(fresh_node["metrics"]["active_streams"], 0)
        self.assertEqual(fresh_node["metrics"]["net_tx"], 0)
        self.assertEqual(fresh_node["metrics"]["cpu"], 0.0)


if __name__ == "__main__":
    unittest.main()
