"""
边缘推流节点 VPS 物理宽带优先测速与动态 Bot 阵列容量匹配测试
============================================================
验证：
1. 宽带换算与 Bot 弹性容量分配算法 (calculate_recommended_bots)；
2. 依据实测宽带动态组建 2~24 个 Bot 阵列及 DC 亲和分配；
3. Edge Worker 的 handle_benchmark_vps_bandwidth 与 handle_reconfigure 端点；
4. vps_deployer 的四阶段自适应闭环测速 (物理宽带 ➔ 算力匹配 ➔ 拉流实测 ➔ 达标率校验)；
5. 数据库 target_bot_count 字段与持久化。
"""

import tests  # noqa: F401
import os
import sys
import unittest
import asyncio
import tempfile
import json
from unittest.mock import patch, MagicMock, AsyncMock

import db
import edge_node_manager
import vps_deployer
from edge_worker.worker_server import EdgeStreamingWorker


class MockRequest:
    def __init__(self, json_data=None, query=None, headers=None, method="GET", read_data=b""):
        self._json_data = json_data or {}
        self.query = query or {}
        self.headers = headers or {}
        self.method = method
        self._read_data = read_data

    async def json(self):
        return self._json_data

    async def read(self):
        return self._read_data


class TestEdgeBandwidthMatching(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()
        edge_node_manager._bot_pool_cache = None

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        if hasattr(self, "_tmp") and os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except OSError:
                pass

    def test_calculate_recommended_bots_formula(self):
        """测试按 2.0 MB/s/Bot 额定拉流吞吐换算推荐 Bot 数量"""
        calc = edge_node_manager.calculate_recommended_bots

        # 兜底与异常
        self.assertEqual(calc(None), 4)
        self.assertEqual(calc(0.0), 4)
        self.assertEqual(calc(-5.0), 4)

        # 极限低速（保底 2 个 Bot）
        self.assertEqual(calc(1.0), 2)
        self.assertEqual(calc(2.0), 2)
        self.assertEqual(calc(3.5), 2)
        self.assertEqual(calc(4.0), 2)

        # 常规中高速
        self.assertEqual(calc(6.0), 3)
        self.assertEqual(calc(8.0), 4)
        self.assertEqual(calc(10.0), 5)
        self.assertEqual(calc(15.0), 8)
        self.assertEqual(calc(20.0), 10)
        self.assertEqual(calc(30.0), 15)
        self.assertEqual(calc(48.0), 24)

        # 超高千兆带宽（上限 24 个 Bot）
        self.assertEqual(calc(50.0), 24)
        self.assertEqual(calc(100.0), 24)
        self.assertEqual(calc(200.0), 24)

        # 自定义上限
        self.assertEqual(calc(50.0, max_cap=8), 8)
        self.assertEqual(calc(50.0, max_cap=16), 16)

        # RTT 延迟感知动态折算
        self.assertEqual(calc(24.0, rtt_ms=35.0), 12)   # RTT <= 50ms: 2.0 MB/s/Bot -> 12
        self.assertEqual(calc(24.0, rtt_ms=78.5), 20)   # 50ms < RTT <= 110ms: 1.2 MB/s/Bot -> 20
        self.assertEqual(calc(24.0, rtt_ms=130.0), 24)  # RTT > 110ms: 0.8 MB/s/Bot -> 24 (封顶)
        # 木桶短板有效带宽：min(down, up)
        # 下行 100 MB/s, 上行 10 MB/s -> 有效 10 MB/s -> 按 2.0 MB/s/Bot 匹配 5 个 Bot
        self.assertEqual(calc(down_speed_mb_s=100.0, up_speed_mb_s=10.0, rtt_ms=30.0), 5)
        # 下行 20 MB/s, 上行 100 MB/s -> 有效 20 MB/s -> 匹配 10 个 Bot
        self.assertEqual(calc(down_speed_mb_s=20.0, up_speed_mb_s=100.0, rtt_ms=30.0), 10)
        # 直接使用 effective_bw_mb_s
        self.assertEqual(calc(effective_bw_mb_s=16.0, rtt_ms=30.0), 8)

    def test_allocate_bots_with_measured_bandwidth(self):
        """测试依据实测物理宽带动态从 DC 资产池中分配对应数量的 Bot 阵列"""
        # 1. 模拟 DC1 节点（实测 20 MB/s 宽带 -> 匹配 10 个 Bot）
        node_dc1 = {
            "id": 991,
            "target_dc_id": 1,
            "allow_bot_pool": 1,
            "benchmark_data": {
                "bandwidth": {
                    "down_speed_mb_s": 20.0,
                    "down_speed_mbps": 160.0,
                }
            }
        }
        res_dc1 = edge_node_manager.allocate_bots_for_edge_node(node_dc1)
        self.assertEqual(res_dc1["target_dc"], 1)
        self.assertEqual(res_dc1["target_bot_count"], 10)
        self.assertEqual(len(res_dc1["bot_tokens"]), 10)
        self.assertEqual(len(res_dc1["bot_session_strings"]), 10)

        # 2. 模拟 DC5 节点（实测 12 MB/s 宽带 -> 匹配 6 个 Bot）
        node_dc5 = {
            "id": 992,
            "target_dc_id": 5,
            "allow_bot_pool": 1,
            "benchmark_data": {
                "bandwidth": {
                    "down_speed_mb_s": 12.0,
                    "down_speed_mbps": 96.0,
                }
            }
        }
        res_dc5 = edge_node_manager.allocate_bots_for_edge_node(node_dc5)
        self.assertEqual(res_dc5["target_dc"], 5)
        self.assertEqual(res_dc5["target_bot_count"], 6)
        self.assertEqual(len(res_dc5["bot_tokens"]), 6)

        # 3. 显式传入 requested_bot_count 优先覆盖
        res_override = edge_node_manager.allocate_bots_for_edge_node(node_dc1, requested_bot_count=16)
        self.assertEqual(res_override["target_bot_count"], 16)
        self.assertEqual(len(res_override["bot_tokens"]), 16)

    def test_db_target_bot_count_persistence(self):
        """测试数据库 edge_nodes 表中 target_bot_count 的持久化与读取"""
        test_node_name = "test_bw_node_persistence"
        node = db.create_edge_node(
            tenant_id=1,
            node_name=test_node_name,
            ip="198.51.100.22",
            port=8090,
            auth_secret="sec_test_bw_123",
        )
        self.assertIsNotNone(node)
        node_id = node["id"]

        # 更新 target_bot_count
        updated = db.update_edge_node(node_id, target_bot_count=12)
        self.assertEqual(updated["target_bot_count"], 12)

        # 重新查库验证
        fetched = db.get_edge_node_by_id(node_id)
        self.assertEqual(fetched["target_bot_count"], 12)

        # 清理
        db.delete_edge_node(node_id)

    def test_worker_vps_bandwidth_handler(self):
        """测试 Edge Worker 的 handle_benchmark_vps_bandwidth 返回合法宽带测速结构"""
        worker = EdgeStreamingWorker(
            master_url="http://127.0.0.1:8080",
            node_secret="test_secret_key",
            mock_stream=True,
        )

        req = MockRequest()
        resp = asyncio.run(worker.handle_benchmark_vps_bandwidth(req))
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.text)
        self.assertTrue(data.get("success"))
        self.assertIn("down_speed_mb_s", data)
        self.assertIn("down_speed_mbps", data)
        self.assertIn("recommended_bots", data)
        self.assertIn("rated_capacity_mb_s", data)
        self.assertGreaterEqual(data["recommended_bots"], 2)
        self.assertLessEqual(data["recommended_bots"], 24)

    def test_worker_reconfigure_handler(self):
        """测试 Edge Worker 的 handle_reconfigure 端点鉴权与响应"""
        worker = EdgeStreamingWorker(
            master_url="http://127.0.0.1:8080",
            node_secret="test_secret_key",
            mock_stream=True,
        )

        # 1. 模拟未带密钥或错误密钥
        req_bad = MockRequest(headers={"X-Node-Secret": "wrong_secret"})
        resp_bad = asyncio.run(worker.handle_reconfigure(req_bad))
        self.assertEqual(resp_bad.status, 403)

        # 2. 模拟正确密钥热重载
        with patch.object(worker, "fetch_config_from_master", new_callable=AsyncMock) as m_fetch, \
             patch.object(worker, "reconcile_worker_clients", new_callable=AsyncMock) as m_rec:
            req_good = MockRequest(headers={"X-Node-Secret": "test_secret_key"})
            resp_good = asyncio.run(worker.handle_reconfigure(req_good))
            self.assertEqual(resp_good.status, 200)
            data = json.loads(resp_good.text)
            self.assertTrue(data.get("success"))
            self.assertTrue(data.get("reconfigured"))
            self.assertTrue(m_fetch.called)
            self.assertTrue(m_rec.called)


class TestFullBenchmarkClosedLoop(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()
        edge_node_manager._bot_pool_cache = None
        self.node = db.create_edge_node(
            tenant_id=1,
            node_name="test_closed_loop_node",
            ip="198.51.100.88",
            port=8090,
            auth_secret="sec_closed_loop_88",
        )

    def tearDown(self):
        if self.node:
            db.delete_edge_node(self.node["id"])
        db.DB_PATH = self.orig_db_path
        if hasattr(self, "_tmp") and os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except OSError:
                pass

    def test_run_edge_full_benchmark_four_phases(self):
        """测试 vps_deployer.run_edge_full_benchmark 四阶段闭环调度与饱和达标率计算"""
        node_id = self.node["id"]

        mock_bw = {
            "success": True,
            "down_speed_mb_s": 24.0,
            "down_speed_mbps": 192.0,
            "up_speed_mb_s": 24.0,
            "up_speed_mbps": 192.0,
            "effective_bw_mb_s": 24.0,
            "cdn_speed_mb_s": 24.0,
            "master_speed_mb_s": 18.0,
            "source": "anycast_cdn",
            "recommended_bots": 20,
        }
        mock_dcs = {
            "success": True,
            "fastest_dc": {"id": 1, "name": "DC1 美西 (Miami)", "avg_rtt_ms": 78.5},
            "dcs": [{"dc_id": 1, "avg_rtt_ms": 78.5}],
        }
        mock_tg_speed = {
            "success": True,
            "speed_mb_s": 22.8,
            "speed_mbps": 182.4,
            "ttfb_ms": 210.0,
            "buffer_ms": 420.0,
            "evaluation": "4K 60FPS 极清秒开",
            "grade": "A+",
            "sample_size_mb": 10.0,
        }
        mock_link = {
            "success": True,
            "rtt_ms": 45.0,
            "down_speed_mb_s": 20.0,
        }
        mock_diag = {
            "success": True,
            "health_score": 98,
            "health_grade": "A+",
            "health_label": "健康极佳",
        }

        mock_relay = {
            "success": True,
            "relay_speed_mb_s": 22.8,
            "relay_speed_mbps": 182.4,
            "tg_pull_speed_mb_s": 24.0,
            "tg_pull_speed_mbps": 192.0,
            "ttfb_ms": 180.0,
            "buffer_ms": 360.0,
            "bottleneck_diagnosis": "🟢 全链路无损满速中继",
            "grade": "A+",
            "evaluation": "4K 60FPS 极清秒开",
        }

        with patch("vps_deployer.run_edge_bandwidth_benchmark", new_callable=AsyncMock) as m_bw, \
             patch("vps_deployer.run_edge_dcs_benchmark", new_callable=AsyncMock) as m_dcs, \
             patch("vps_deployer.run_edge_diagnostics", new_callable=AsyncMock) as m_diag, \
             patch("vps_deployer.run_edge_link_benchmark", new_callable=AsyncMock) as m_link, \
             patch("vps_deployer.reconfigure_edge_worker", new_callable=AsyncMock) as m_reconfig, \
             patch("vps_deployer.run_edge_relay_stream_benchmark", new_callable=AsyncMock) as m_relay, \
             patch("vps_deployer.run_edge_tg_speed_benchmark", new_callable=AsyncMock) as m_tg:

            m_bw.return_value = mock_bw
            m_dcs.return_value = mock_dcs
            m_diag.return_value = mock_diag
            m_link.return_value = mock_link
            m_reconfig.return_value = {"success": True, "reconfigured": True}
            m_relay.return_value = mock_relay
            m_tg.return_value = mock_tg_speed

            res = asyncio.run(vps_deployer.run_edge_full_benchmark(node_id, sample_mb=10.0))

            self.assertTrue(res["success"])
            bm = res["benchmark_data"]
            self.assertIn("bandwidth", bm)
            bw_data = bm["bandwidth"]

            # 验证 Phase 1 宽带实测入库
            self.assertEqual(bw_data["down_speed_mb_s"], 24.0)
            self.assertEqual(bw_data["down_speed_mbps"], 192.0)

            # 验证 Phase 2 动态匹配 Bot 数量 (24 MB/s + RTT 78.5ms -> 按 1.2MB/s/Bot 动态匹配 20 个 Bot)
            self.assertEqual(bw_data["matched_bots"], 20)
            self.assertEqual(bw_data["rated_capacity_mb_s"], 24.0)
            self.assertTrue(m_reconfig.called)

            # 验证 Phase 3 拉流实测与宽带饱和达标率 (22.8 / 24.0 * 100% = 95.0%)
            self.assertEqual(bm["speed"]["peak_speed_mb_s"], 22.8)
            self.assertEqual(bw_data["saturation_percent"], 95.0)

            # 验证 Phase 4 数据库持久化
            fresh = db.get_edge_node_by_id(node_id)
            self.assertEqual(fresh["target_bot_count"], 20)
            self.assertEqual(fresh["target_dc_id"], 1)
            self.assertIsNotNone(fresh["benchmark_data"])
            self.assertEqual(fresh["benchmark_data"]["bandwidth"]["saturation_percent"], 95.0)



    def test_run_edge_relay_stream_benchmark_direct(self):
        """测试 vps_deployer.run_edge_relay_stream_benchmark 端到端中继压测"""
        node_id = self.node["id"]
        mock_sess = MagicMock()
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=None)

        with patch("vps_deployer.ClientSession", return_value=mock_sess), \
             patch("vps_deployer.find_best_benchmark_media", return_value={"chat_id": -1001234567, "message_id": 999, "channel_username": "test_chan", "file_size": 52428800, "dc_id": 1}), \
             patch("vps_deployer._safe_edge_request") as m_req:

            # Mock stream response
            mock_resp = AsyncMock()
            mock_resp.status = 206
            mock_resp.content.read = AsyncMock(side_effect=[b"X" * 1048576, b"Y" * 1048576, b""])

            # Mock last-relay metric response
            mock_metric_resp = AsyncMock()
            mock_metric_resp.status = 200
            mock_metric_resp.json = AsyncMock(return_value={
                "chat_id": -1001234567,
                "message_id": 999,
                "client_push_speed_mb_s": 25.0,
                "tg_pull_speed_mb_s": 26.5,
                "usable_sources_count": 4,
                "backpressure_detected": False,
            })

            from contextlib import asynccontextmanager
            @asynccontextmanager
            async def fake_safe_edge_request(session, base_url, path, method="GET", **kwargs):
                if "/benchmark/last-relay" in path:
                    yield mock_metric_resp
                else:
                    yield mock_resp

            m_req.side_effect = fake_safe_edge_request

            res = asyncio.run(vps_deployer.run_edge_relay_stream_benchmark(node_id, sample_mb=2.0))
            self.assertTrue(res["success"])
            self.assertIn("relay_speed_mb_s", res)
            self.assertIn("tg_pull_speed_mb_s", res)
            self.assertIn("bottleneck_diagnosis", res)

if __name__ == "__main__":
    unittest.main()
