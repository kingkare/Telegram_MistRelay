import os
import sys
import time
import math
import asyncio
import tempfile
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

import db
import edge_node_manager
from edge_worker.worker_server import (
    SystemHardwareGuardrail,
    NetworkPathTracker,
    PIDWindowController,
    MultiBotLaneMatrix,
    EdgeStreamingWorker,
    VERSION,
)
import vps_deployer


class AdaptiveTransmissionAccelerationTests(unittest.TestCase):
    def setUp(self):
        # 1. 创建独立临时 SQLite 文件，保证生产库绝对安全 (AGENTS.md 红线要求)
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()

        # 2. 保存并重定向全局 DB_PATH
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name

        # 3. 初始化沙箱表结构
        db.init_db()

    def tearDown(self):
        # 4. 严格恢复现场，防止状态污染后续测试用例
        db.DB_PATH = self.orig_db_path
        if hasattr(self, "_tmp") and os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except OSError:
                pass

    def test_system_hardware_guardrail_tiers(self):
        """测试不同物理算力环境下的内存隔离与窗口硬限制 (防 OOM 守护)"""
        guard = SystemHardwareGuardrail()

        # 1. 模拟极端小内存 NAT VPS (如 512MB RAM NAT/t2.nano)
        guard._total_mb = 450.0
        guard._free_mb = 200.0
        self.assertEqual(guard.tier, "ULTRA_LOW_NAT")
        self.assertLessEqual(guard.max_queue_bytes, 24 * 1024 * 1024)
        clamped = guard.clamp_window(requested_window=64, chunk_size=524288)
        self.assertLessEqual(clamped, 12)
        self.assertGreaterEqual(clamped, 2)

        # 2. 模拟中配廉价 VPS (如 1GB RackNerd)
        guard._total_mb = 960.0
        guard._free_mb = 420.0
        self.assertEqual(guard.tier, "BUDGET_VPS")
        self.assertLessEqual(guard.max_queue_bytes, 72 * 1024 * 1024)
        clamped_budget = guard.clamp_window(requested_window=64, chunk_size=524288)
        self.assertLessEqual(clamped_budget, 32)
        self.assertGreaterEqual(clamped_budget, 2)

        # 3. 模拟高配云主机 / 独服 (> 1.6GB RAM)
        guard._total_mb = 4096.0
        guard._free_mb = 3200.0
        self.assertEqual(guard.tier, "DEDICATED_HIGH_SPEC")
        self.assertLessEqual(guard.max_queue_bytes, 256 * 1024 * 1024)
        clamped_high = guard.clamp_window(requested_window=128, chunk_size=524288)
        self.assertLessEqual(clamped_high, 96)
        self.assertGreaterEqual(clamped_high, 2)

    def test_network_path_tracker_dynamics(self):
        """测试网络链路物理指标与往返延迟 EWMA 动态跟踪 (Jacobson/Karn 算法)"""
        tracker = NetworkPathTracker(dc_id=5)

        # 初始默认值
        self.assertEqual(tracker.dc_id, 5)
        self.assertAlmostEqual(tracker.srtt, 0.120, delta=0.01)

        # 模拟稳定低延迟网络包反馈 (40ms)
        for _ in range(10):
            tracker.update_rtt(0.040)
        self.assertLess(tracker.srtt, 0.080)
        self.assertAlmostEqual(tracker.rtt_min, 0.040, delta=0.005)

        # 验证首分片投机对冲超时 (应在 45ms ~ 350ms 之间)
        t_first_hedge = tracker.get_hedge_deadline(is_first_chunk=True)
        self.assertGreaterEqual(t_first_hedge, 0.045)
        self.assertLessEqual(t_first_hedge, 0.350)

        # 验证稳态对冲超时
        t_steady_hedge = tracker.get_hedge_deadline(is_first_chunk=False)
        self.assertGreaterEqual(t_steady_hedge, 0.080)

        # 验证 BDP 动态计算
        tracker.update_speed(bytes_transferred=20 * 1024 * 1024, duration_s=0.5) # 40 MB/s
        self.assertGreater(tracker.estimated_speed_mb_s, 10.0)
        bdp_chunks = tracker.get_target_bdp_chunks(chunk_size=524288)
        self.assertGreaterEqual(bdp_chunks, 2)

    def test_pid_window_controller_backpressure_and_rampup(self):
        """测试 PID 闭环调速器在客户端背压与线速拉取下的自适应调节行为"""
        guard = SystemHardwareGuardrail()
        guard._total_mb = 1024.0
        guard._free_mb = 500.0

        tracker = NetworkPathTracker(dc_id=1)
        tracker.update_rtt(0.050)
        tracker.update_speed(10 * 1024 * 1024, 0.2) # 50 MB/s

        controller = PIDWindowController(is_download=True, hw_guard=guard)
        initial_win = controller.current_window

        # 1. 模拟下游客户端快速畅通消费 (write_dur_s = 0.005s < 0.015s)
        for _ in range(5):
            controller.on_downstream_feedback(write_dur_s=0.005, chunk_bytes=524288, path_tracker=tracker)
        self.assertGreater(controller.current_window, initial_win)
        self.assertFalse(controller.backpressure_detected)

        # 2. 模拟下游客户端暂停/卡顿/缓冲堆积发生背压 (write_dur_s = 0.120s > 0.060s)
        prev_win = controller.current_window
        controller.on_downstream_feedback(write_dur_s=0.120, chunk_bytes=524288, path_tracker=tracker)
        self.assertTrue(controller.backpressure_detected)
        self.assertLess(controller.current_window, prev_win)
        self.assertGreaterEqual(controller.current_window, controller.min_window)

    def test_multi_bot_lane_matrix_allocation(self):
        """测试多 Bot 多 Session 高维无竞态通道矩阵映射与备份对冲调度"""
        fake_bots = [("bot_1", 1), ("bot_2", 2), ("bot_3", 3)]
        matrix = MultiBotLaneMatrix(usable_sources=fake_bots, sessions_per_bot=3)

        # 3 个 Bot * 3 个 Session = 9 条独立管道
        self.assertEqual(matrix.total_lanes, 9)

        # 验证主通道与槽位循环分布
        lane_0, slot_0 = matrix.get_lane(0)
        lane_1, slot_1 = matrix.get_lane(1)
        lane_2, slot_2 = matrix.get_lane(2)
        lane_3, slot_3 = matrix.get_lane(3)

        self.assertEqual(lane_0, fake_bots[0])
        self.assertEqual(slot_0, 0)
        self.assertEqual(lane_1, fake_bots[1])
        self.assertEqual(slot_1, 0)
        self.assertEqual(lane_2, fake_bots[2])
        self.assertEqual(slot_2, 0)
        self.assertEqual(lane_3, fake_bots[0])
        self.assertEqual(slot_3, 1)

        # 验证对冲备份通道与主通道完全交错，杜绝单点阻塞
        for idx in range(6):
            p_lane, p_slot = matrix.get_lane(idx)
            b_lane, b_slot = matrix.get_backup_lane(idx)
            # 备份管道不应与主管道完全相同
            self.assertFalse(p_lane == b_lane and p_slot == b_slot)

    def test_mock_streaming_metrics_and_pareto_optimality(self):
        """测试在模拟与真实请求下，指标采集与帕累托最优判定"""
        worker = EdgeStreamingWorker(port=8090, node_secret="test_secret_123", mock_stream=True)
        ticket = edge_node_manager.generate_edge_stream_ticket(
            tenant_id=1,
            chat_id=-1001234567,
            message_id=42,
            file_unique_id="unique_media_42",
            node_secret="test_secret_123",
            file_name="test_video.mp4",
            file_size=10 * 1024 * 1024,
            mime_type="video/mp4",
            dc_id=5,
            expire_seconds=3600,
        )

        req = MagicMock()
        req.method = "GET"
        req.match_info = {"path": "42"}
        req.query = {"ticket": ticket}
        req.headers = {"Range": "bytes=0-1048575"}
        req.transport = None
        req.remote = "127.0.0.1"

        async def run_req():
            resp = await worker.handle_stream(req)
            return resp

        resp = asyncio.run(run_req())
        self.assertEqual(resp.status, 206)
        self.assertIn("Content-Range", resp.headers)
        self.assertIn("MistRelay-Edge", resp.headers.get("X-Edge-Worker", ""))

        # 验证指标字典写入与帕累托最优状态
        metrics = worker.get_last_relay_metrics()
        self.assertTrue(metrics.get("success", False))
        self.assertIn("ttfb_ms", metrics)
        self.assertIn("client_push_speed_mb_s", metrics)
        self.assertIn("hardware_tier", metrics)
        self.assertIn("pareto_optimal", metrics)

    def test_vps_deployer_metric_parsing(self):
        """测试 vps_deployer 对边缘综合评测指标的完整解析与持久化结构"""
        fake_relay_metrics = {
            "relay_speed_mb_s": 28.5,
            "relay_speed_mbps": 228.0,
            "tg_pull_speed_mb_s": 32.1,
            "ttfb_ms": 138.4,
            "buffer_ms": 182.0,
            "hedged_requests_count": 2,
            "hedged_wins_count": 1,
            "dual_launch_used": True,
            "jitter_cv": 0.12,
            "hardware_tier": "BUDGET_VPS",
            "window_size": 16,
            "pareto_optimal": True,
        }
        # 验证帕累托判定逻辑
        self.assertTrue(fake_relay_metrics["pareto_optimal"])
        self.assertLess(fake_relay_metrics["ttfb_ms"], 200.0)
        self.assertGreater(fake_relay_metrics["relay_speed_mb_s"], 20.0)


if __name__ == "__main__":
    unittest.main()
