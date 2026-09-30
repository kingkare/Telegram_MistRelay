import tests  # noqa: F401
import os
import json
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import db
import auth
from WebStreamer import Var
from edge_worker.worker_server import EdgeStreamingWorker, _ping_single_dc, TELEGRAM_DCS
import vps_deployer
from WebStreamer.server.stream_routes import (
    edge_nodes_benchmark_dcs_handler,
    edge_nodes_benchmark_tg_speed_handler,
    edge_nodes_diagnostics_handler,
    edge_nodes_benchmark_full_handler,
    edge_nodes_upgrade_handler,
)


class MockRequest(dict):
    def __init__(self, json_data=None, match_info=None, query=None, headers=None, user=None, method="GET", read_data=b""):
        super().__init__()
        self._json_data = json_data or {}
        self.match_info = match_info or {}
        self.query = query or {}
        self.headers = headers or {}
        self.method = method
        self._read_data = read_data
        self.scheme = "http"
        self.host = "127.0.0.1:8080"
        if user:
            self["user"] = user

    async def json(self):
        return self._json_data

    async def read(self):
        return self._read_data


class TestEdgeBenchmarkAndDiagnostics(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()

        # 初始化测试租户
        admin_u = db.create_tenant_user(
            username="admin_user",
            password_hash=auth.hash_password("AdminPass123"),
            role="admin",
            bin_channel_id=-1001998444696,
        )
        alice_u = db.create_tenant_user(
            username="alice",
            password_hash=auth.hash_password("AlicePass123"),
            role="user",
            bin_channel_id=-100111111111,
        )
        bob_u = db.create_tenant_user(
            username="bob",
            password_hash=auth.hash_password("BobPass123"),
            role="user",
            bin_channel_id=-100222222222,
        )

        self.admin_user = {"uid": admin_u["id"], "username": "admin_user", "role": "admin"}
        self.alice_user = {"uid": alice_u["id"], "username": "alice", "role": "user"}
        self.bob_user = {"uid": bob_u["id"], "username": "bob", "role": "user"}

        # 初始化测试节点
        self.alice_node = db.create_edge_node(
            tenant_id=self.alice_user["uid"],
            node_name="Alice SG VPS",
            ip="203.0.113.10",
            port=8090,
            ssh_host="203.0.113.10",
            ssh_port=22,
            ssh_user="root",
            ssh_password="AlicePassword123",
            auth_secret="sec_alice_12345",
            status="online",
        )

        self.bob_node = db.create_edge_node(
            tenant_id=self.bob_user["uid"],
            node_name="Bob US VPS",
            ip="198.51.100.20",
            port=8090,
            auth_secret="sec_bob_67890",
            status="online",
        )

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        if os.path.exists(self._tmp.name):
            os.unlink(self._tmp.name)

    async def test_ping_single_dc_logic(self):
        dc_test = {"id": 1, "name": "DC1 美西", "region": "美西", "ip": "127.0.0.1", "port": 443}
        res = await _ping_single_dc(dc_test, rounds=1, timeout=0.1)
        self.assertEqual(res["dc_id"], 1)
        self.assertIn("rating", res)
        self.assertIn("packet_loss_pct", res)

    async def test_worker_benchmark_dcs_handler(self):
        worker = EdgeStreamingWorker(mock_stream=True, node_secret="test_sec")
        req = MockRequest()
        resp = await worker.handle_benchmark_dcs(req)
        self.assertEqual(resp.status, 200)
        body = resp.body
        self.assertTrue(body["success"])
        self.assertEqual(len(body["dcs"]), 5)
        self.assertIn("fastest_dc", body)

    async def test_worker_benchmark_tg_speed_handler(self):
        worker = EdgeStreamingWorker(mock_stream=True, node_secret="test_sec")
        req = MockRequest(json_data={"sample_size_mb": 1.0}, method="POST")
        resp = await worker.handle_benchmark_tg_speed(req)
        self.assertEqual(resp.status, 200)
        body = resp.body
        self.assertTrue(body["success"])
        self.assertGreater(body["speed_mb_s"], 0)
        self.assertGreater(body["speed_mbps"], 0)
        self.assertIn("ttfb_ms", body)
        self.assertIn("evaluation", body)
        self.assertIn("grade", body)

    async def test_worker_diagnostics_handler(self):
        worker = EdgeStreamingWorker(mock_stream=True, node_secret="test_sec")
        req = MockRequest()
        resp = await worker.handle_diagnostics(req)
        self.assertEqual(resp.status, 200)
        body = resp.body
        self.assertTrue(body["success"])
        self.assertGreaterEqual(body["health_score"], 0)
        self.assertLessEqual(body["health_score"], 100)
        self.assertIn(body["health_grade"], ["A+", "A", "B", "C"])
        self.assertIn("system", body)
        self.assertIn("telegram", body)
        self.assertTrue(body["telegram"]["connected"])

    async def test_worker_link_speed_handler(self):
        worker = EdgeStreamingWorker(mock_stream=True, node_secret="test_sec")
        # POST upload to worker
        req_post = MockRequest(method="POST", read_data=b"HELLO_WORLD_TEST_PAYLOAD")
        resp_post = await worker.handle_benchmark_link_speed(req_post)
        self.assertEqual(resp_post.status, 200)
        self.assertEqual(resp_post.body["direction"], "master_to_worker")
        self.assertEqual(resp_post.body["bytes_transferred"], 24)

    async def test_worker_update_unauthorized(self):
        worker = EdgeStreamingWorker(mock_stream=True, node_secret="correct_secret")
        req_bad = MockRequest(method="POST", headers={"X-Node-Secret": "wrong_secret"})
        resp_bad = await worker.handle_update(req_bad)
        self.assertEqual(resp_bad.status, 403)

    async def test_deployer_run_full_benchmark_mocked(self):
        # 模拟 Edge Worker 响应
        mock_dcs = {
            "success": True,
            "fastest_dc": {"id": 5, "name": "DC5 亚太 (Singapore)", "avg_rtt_ms": 28.4, "rating_label": "极速最优"},
            "dcs": [{"dc_id": 5, "name": "DC5 亚太", "avg_rtt_ms": 28.4, "rating": "optimal"}],
            "home_dc": 5,
        }
        mock_speed = {
            "success": True,
            "speed_mb_s": 38.5,
            "speed_mbps": 308.0,
            "ttfb_ms": 86.4,
            "buffer_ms": 112.5,
            "evaluation": "4K 60FPS 极清无损直推",
            "grade": "A+",
            "sample_size_mb": 10.0,
        }
        mock_link = {
            "success": True,
            "rtt_ms": 45.2,
            "down_speed_mb_s": 25.0,
            "down_speed_mbps": 200.0,
            "up_speed_mb_s": 20.0,
            "up_speed_mbps": 160.0,
        }
        mock_diag = {
            "success": True,
            "health_score": 98,
            "health_grade": "A+",
            "health_label": "健康极佳",
            "issues": [],
            "system": {"os": "Debian 12", "cpu_cores": 4, "nofile_limit": 65535},
            "telegram": {"connected": True, "bot_username": "test_bot", "home_dc": 5},
        }

        with patch("vps_deployer.run_edge_dcs_benchmark", AsyncMock(return_value=mock_dcs)),              patch("vps_deployer.run_edge_tg_speed_benchmark", AsyncMock(return_value=mock_speed)),              patch("vps_deployer.run_edge_link_benchmark", AsyncMock(return_value=mock_link)),              patch("vps_deployer.run_edge_diagnostics", AsyncMock(return_value=mock_diag)):

            res = await vps_deployer.run_edge_full_benchmark(self.alice_node["id"], sample_mb=10.0)
            self.assertTrue(res["success"])
            bench = res["benchmark_data"]
            self.assertEqual(bench["health_score"], 98)
            self.assertEqual(bench["fastest_dc"]["id"], 5)
            self.assertEqual(bench["speed"]["peak_speed_mb_s"], 38.5)

            # 验证数据库中已持久化
            fresh_node = db.get_edge_node_by_id(self.alice_node["id"])
            self.assertEqual(fresh_node["status"], "online")
            self.assertEqual(fresh_node["benchmark_data"]["health_score"], 98)
            self.assertEqual(fresh_node["benchmark_data"]["fastest_dc"]["id"], 5)
            self.assertIn("last_benchmark_at", fresh_node["benchmark_data"])

    async def test_stream_routes_permission_isolation(self):
        # 1. 租户 Alice 越权测试 Bob 的节点 -> 拦截 403
        req_unauth = MockRequest(
            match_info={"node_id": str(self.bob_node["id"])},
            user=self.alice_user,
        )
        resp_unauth = await edge_nodes_benchmark_dcs_handler(req_unauth)
        self.assertEqual(resp_unauth.status, 403)

        # 2. 租户 Alice 越权对 Bob 节点执行全量测速 -> 拦截 403
        resp_unauth_full = await edge_nodes_benchmark_full_handler(req_unauth)
        self.assertEqual(resp_unauth_full.status, 403)

        # 3. 租户 Alice 越权升级 Bob 节点 -> 拦截 403
        resp_unauth_upg = await edge_nodes_upgrade_handler(req_unauth)
        self.assertEqual(resp_unauth_upg.status, 403)

        # 4. 租户 Alice 测试自己的节点 -> 鉴权通过 (200)
        req_auth = MockRequest(
            match_info={"node_id": str(self.alice_node["id"])},
            user=self.alice_user,
        )
        with patch("vps_deployer.run_edge_dcs_benchmark", AsyncMock(return_value={"success": True, "dcs": []})):
            resp_auth = await edge_nodes_benchmark_dcs_handler(req_auth)
            self.assertEqual(resp_auth.status, 200)
            self.assertTrue(resp_auth.body["success"])

        # 5. 管理员测试任何租户的节点 -> 鉴权通过 (200)
        req_admin = MockRequest(
            match_info={"node_id": str(self.bob_node["id"])},
            user=self.admin_user,
        )
        with patch("vps_deployer.run_edge_full_benchmark", AsyncMock(return_value={"success": True, "benchmark_data": {}})):
            resp_admin = await edge_nodes_benchmark_full_handler(req_admin)
            self.assertEqual(resp_admin.status, 200)
            self.assertTrue(resp_admin.body["success"])


if __name__ == "__main__":
    unittest.main()
