import unittest
import os
import tempfile
import sqlite3
import json
import asyncio
from unittest.mock import patch, MagicMock

import db
import auth
from WebStreamer import Var
import edge_node_manager
from edge_worker.worker_server import EdgeStreamingWorker
from WebStreamer.server.stream_routes import (
    edge_node_config_handler,
    edge_nodes_reassign_bot_handler,
    edge_bots_pool_handler,
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


class TestEdgeDcBotAllocation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.test_dir.name, "test_edge_bots.db")
        self.sessions_dir = os.path.join(self.test_dir.name, "sessions")
        os.makedirs(self.sessions_dir, exist_ok=True)

        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self.db_path
        db.init_db()

        # Admin user
        self.admin_user = db.create_tenant_user(
            username="admin_tester",
            password_hash=auth.hash_password("Pass123"),
            role="admin",
        )

        # Mock Bot tokens: 3 in DC1, 2 in DC5
        self.dc1_tokens = [
            "1001:token_dc1_a",
            "1002:token_dc1_b",
            "1003:token_dc1_c",
        ]
        self.dc5_tokens = [
            "5001:token_dc5_a",
            "5002:token_dc5_b",
        ]
        self.all_mock_tokens = self.dc1_tokens + self.dc5_tokens

        # Create session files for each mock token
        for tok in self.dc1_tokens:
            pfx = tok.split(":", 1)[0]
            sf = os.path.join(self.sessions_dir, f"pyrogram_bot_{pfx}.session")
            with sqlite3.connect(sf) as sconn:
                sconn.execute("CREATE TABLE sessions (dc_id INTEGER, api_id INTEGER, test_mode INTEGER, auth_key BLOB, date INTEGER, user_id INTEGER, is_bot INTEGER)")
                sconn.execute("INSERT INTO sessions VALUES (1, 12345, 0, x'010203', 1700000000, ?, 1)", (int(pfx),))

        for tok in self.dc5_tokens:
            pfx = tok.split(":", 1)[0]
            sf = os.path.join(self.sessions_dir, f"pyrogram_bot_{pfx}.session")
            with sqlite3.connect(sf) as sconn:
                sconn.execute("CREATE TABLE sessions (dc_id INTEGER, api_id INTEGER, test_mode INTEGER, auth_key BLOB, date INTEGER, user_id INTEGER, is_bot INTEGER)")
                sconn.execute("INSERT INTO sessions VALUES (5, 12345, 0, x'050505', 1700000000, ?, 1)", (int(pfx),))

        # Save tokens to config_settings
        db.set_config("BOT_TOKEN", self.dc5_tokens[0], value_type="string", category="main")
        db.set_config("MULTI_BOT_TOKENS", self.dc1_tokens + [self.dc5_tokens[1]], value_type="list", category="main")

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        self.test_dir.cleanup()

    @patch("edge_node_manager._resolve_sessions_dir")
    def test_get_dc_bot_pool_partitioning(self, mock_sess_dir):
        mock_sess_dir.return_value = self.sessions_dir
        pool = edge_node_manager.get_dc_bot_pool(force_refresh=True)

        self.assertIn(1, pool)
        self.assertIn(5, pool)
        self.assertEqual(len(pool[1]), 3)
        self.assertEqual(len(pool[5]), 2)

        prefixes_dc1 = {b["prefix"] for b in pool[1]}
        self.assertEqual(prefixes_dc1, {"1001", "1002", "1003"})

        prefixes_dc5 = {b["prefix"] for b in pool[5]}
        self.assertEqual(prefixes_dc5, {"5001", "5002"})

    def test_infer_node_target_dc(self):
        # 1. Explicit target_dc_id
        node1 = {"id": 1, "target_dc_id": 1}
        self.assertEqual(edge_node_manager.infer_node_target_dc(node1), 1)

        # 2. Fastest DC from benchmark
        node2 = {
            "id": 2,
            "target_dc_id": None,
            "benchmark_data": {"fastest_dc": {"id": 3, "name": "DC3 美东 (Miami)"}}
        }
        # DC3 maps to DC1 in Miami
        self.assertEqual(edge_node_manager.infer_node_target_dc(node2), 1)

        node3 = {
            "id": 3,
            "target_dc_id": None,
            "benchmark_data": {"fastest_dc": {"id": 5, "name": "DC5 亚太 (Singapore)"}}
        }
        self.assertEqual(edge_node_manager.infer_node_target_dc(node3), 5)

        # 3. IP / Region Heuristics
        node4 = {"id": 4, "target_dc_id": None, "node_name": "RackNerd 美区洛杉矶大带宽", "ip": "23.94.214.191"}
        self.assertEqual(edge_node_manager.infer_node_target_dc(node4), 1)

        node5 = {"id": 5, "target_dc_id": None, "node_name": "ap-east-1 香港沙田", "ip": "16.162.23.244"}
        self.assertEqual(edge_node_manager.infer_node_target_dc(node5), 5)

    @patch("edge_node_manager._resolve_sessions_dir")
    def test_allocate_bots_for_edge_node_us_and_hk(self, mock_sess_dir):
        mock_sess_dir.return_value = self.sessions_dir
        edge_node_manager.get_dc_bot_pool(force_refresh=True)

        # Node in US (target DC 1)
        us_node = db.create_edge_node(
            tenant_id=1,
            node_name="美区 VPS",
            ip="23.94.214.191",
            target_dc_id=1,
            allow_bot_pool=True,
        )
        alloc_us = edge_node_manager.allocate_bots_for_edge_node(us_node)

        self.assertEqual(alloc_us["target_dc"], 1)
        # Primary bot must be from DC1
        self.assertIn(alloc_us["primary_bot_token"], self.dc1_tokens)
        # Bot tokens pool must have DC1 tokens
        self.assertTrue(all(t in self.dc1_tokens for t in alloc_us["bot_tokens"]))
        self.assertEqual(len(alloc_us["bot_tokens"]), 3)
        # Cross-DC map must have DC1 and DC5
        self.assertIn("1", alloc_us["dc_bot_map"])
        self.assertIn("5", alloc_us["dc_bot_map"])
        self.assertIn(alloc_us["dc_bot_map"]["1"], self.dc1_tokens)
        self.assertIn(alloc_us["dc_bot_map"]["5"], self.dc5_tokens)

        # Node in HK (target DC 5)
        hk_node = db.create_edge_node(
            tenant_id=1,
            node_name="香港 VPS",
            ip="16.162.23.244",
            target_dc_id=5,
            allow_bot_pool=True,
        )
        alloc_hk = edge_node_manager.allocate_bots_for_edge_node(hk_node)

        self.assertEqual(alloc_hk["target_dc"], 5)
        # Primary bot must be from DC5
        self.assertIn(alloc_hk["primary_bot_token"], self.dc5_tokens)
        self.assertTrue(all(t in self.dc5_tokens for t in alloc_hk["bot_tokens"]))

    @patch("edge_node_manager._resolve_sessions_dir")
    def test_allocate_bots_with_dedicated_token(self, mock_sess_dir):
        mock_sess_dir.return_value = self.sessions_dir
        edge_node_manager.get_dc_bot_pool(force_refresh=True)

        dedicated_token = "1002:token_dc1_b"
        node = db.create_edge_node(
            tenant_id=1,
            node_name="专属 Bot 节点",
            ip="1.2.3.4",
            target_dc_id=1,
            assigned_bot_token=dedicated_token,
            assigned_bot_username="my_custom_bot",
            allow_bot_pool=False,
        )
        alloc = edge_node_manager.allocate_bots_for_edge_node(node)

        self.assertEqual(alloc["primary_bot_token"], dedicated_token)
        self.assertEqual(alloc["primary_bot_username"], "my_custom_bot")
        # Pool disabled: should only contain primary token
        self.assertEqual(alloc["bot_tokens"], [dedicated_token])
        self.assertFalse(alloc["allow_bot_pool"])

    async def test_worker_server_diagnostics_dc_affinity(self):
        worker = EdgeStreamingWorker(
            port=8099,
            master_url="http://127.0.0.1:8080",
            node_secret="test_secret_abc",
            mock_stream=True,
        )
        worker.target_dc = 1
        worker.home_dc = 1
        worker.bot_username = "qianlong520f001_bot"

        req = MockRequest()
        resp = await worker.handle_diagnostics(req)
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.text)
        tg = data.get("telegram") or {}
        self.assertEqual(tg.get("home_dc"), 1)
        self.assertEqual(tg.get("assigned_dc"), 1)
        self.assertTrue(tg.get("dc_affinity_matched"))
        self.assertIn("bot_pool_size", tg)
        self.assertIn("active_worker_bots", tg)

    @patch("edge_node_manager._resolve_sessions_dir")
    async def test_edge_config_api_handler(self, mock_sess_dir):
        mock_sess_dir.return_value = self.sessions_dir
        edge_node_manager.get_dc_bot_pool(force_refresh=True)

        node = db.create_edge_node(
            tenant_id=1,
            node_name="美区测试",
            ip="23.94.214.191",
            target_dc_id=1,
            auth_secret="sec_test_config_123",
        )
        req = MockRequest(headers={"X-Node-Secret": "sec_test_config_123"})
        resp = await edge_node_config_handler(req)
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.text)
        self.assertTrue(data.get("success"))
        cfg = data.get("config") or {}
        self.assertEqual(cfg.get("target_dc"), 1)
        self.assertIn(cfg.get("bot_token"), self.dc1_tokens)
        self.assertIn("1", cfg.get("dc_bot_map", {}))
        self.assertIn("5", cfg.get("dc_bot_map", {}))

    @patch("edge_node_manager._resolve_sessions_dir")
    async def test_edge_nodes_reassign_bot_api_handler(self, mock_sess_dir):
        mock_sess_dir.return_value = self.sessions_dir
        edge_node_manager.get_dc_bot_pool(force_refresh=True)

        node = db.create_edge_node(
            tenant_id=1,
            node_name="待纠偏节点",
            ip="1.2.3.4",
            target_dc_id=5,
        )
        req = MockRequest(
            match_info={"node_id": str(node["id"])},
            json_data={"target_dc_id": 1, "trigger_ota": False},
            user={"sub": "admin_tester", "uid": self.admin_user["id"], "role": "admin"},
        )
        resp = await edge_nodes_reassign_bot_handler(req)
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.text)
        self.assertTrue(data.get("success"))
        alloc = data.get("allocation") or {}
        self.assertEqual(alloc.get("target_dc"), 1)
        self.assertIn(alloc.get("primary_bot_token"), self.dc1_tokens)

        # Verify DB updated
        reloaded = db.get_edge_node_by_id(node["id"])
        self.assertEqual(reloaded["target_dc_id"], 1)



    @patch("edge_node_manager._resolve_sessions_dir")
    async def test_edge_bots_pool_api_handler(self, mock_sess_dir):
        mock_sess_dir.return_value = self.sessions_dir
        edge_node_manager.get_dc_bot_pool(force_refresh=True)

        # 1. Query all
        req_all = MockRequest(user={"sub": "admin_tester", "uid": self.admin_user["id"], "role": "admin"})
        resp_all = await edge_bots_pool_handler(req_all)
        self.assertEqual(resp_all.status, 200)
        data_all = json.loads(resp_all.text)
        self.assertTrue(data_all.get("success"))
        self.assertEqual(data_all.get("total"), 5)

        # 2. Filter by DC1
        req_dc1 = MockRequest(
            query={"dc_id": "1"},
            user={"sub": "admin_tester", "uid": self.admin_user["id"], "role": "admin"}
        )
        resp_dc1 = await edge_bots_pool_handler(req_dc1)
        self.assertEqual(resp_dc1.status, 200)
        data_dc1 = json.loads(resp_dc1.text)
        self.assertEqual(len(data_dc1.get("bots", [])), 3)
        self.assertTrue(all(b["dc_id"] == 1 for b in data_dc1["bots"]))

        # 3. Search query
        req_search = MockRequest(
            query={"search": "1002"},
            user={"sub": "admin_tester", "uid": self.admin_user["id"], "role": "admin"}
        )
        resp_search = await edge_bots_pool_handler(req_search)
        data_search = json.loads(resp_search.text)
        self.assertEqual(len(data_search.get("bots", [])), 1)
        self.assertEqual(data_search["bots"][0]["prefix"], "1002")

    @patch("edge_node_manager._resolve_sessions_dir")
    async def test_manual_and_auto_reassign_bot_api(self, mock_sess_dir):
        mock_sess_dir.return_value = self.sessions_dir
        edge_node_manager.get_dc_bot_pool(force_refresh=True)

        node = db.create_edge_node(
            tenant_id=1,
            node_name="指定 Bot 节点",
            ip="5.6.7.8",
            target_dc_id=5,
        )

        # 1. 手动指定模式
        req_manual = MockRequest(
            match_info={"node_id": str(node["id"])},
            json_data={
                "mode": "manual",
                "assigned_bot_token": "1003:token_dc1_c",
                "trigger_ota": False,
            },
            user={"sub": "admin_tester", "uid": self.admin_user["id"], "role": "admin"},
        )
        resp_manual = await edge_nodes_reassign_bot_handler(req_manual)
        self.assertEqual(resp_manual.status, 200)
        data_m = json.loads(resp_manual.text)
        self.assertTrue(data_m.get("success"))
        self.assertEqual(data_m["allocation"]["primary_bot_token"], "1003:token_dc1_c")
        self.assertEqual(data_m["allocation"]["target_dc"], 1)

        db_node = db.get_edge_node_by_id(node["id"])
        self.assertEqual(db_node["assigned_bot_token"], "1003:token_dc1_c")
        self.assertEqual(db_node["target_dc_id"], 1)

        # 2. 切换回智能自动模式
        req_auto = MockRequest(
            match_info={"node_id": str(node["id"])},
            json_data={
                "mode": "auto",
                "target_dc_id": 5,
                "trigger_ota": False,
            },
            user={"sub": "admin_tester", "uid": self.admin_user["id"], "role": "admin"},
        )
        resp_auto = await edge_nodes_reassign_bot_handler(req_auto)
        self.assertEqual(resp_auto.status, 200)
        data_a = json.loads(resp_auto.text)
        self.assertTrue(data_a.get("success"))
        self.assertIn(data_a["allocation"]["primary_bot_token"], self.dc5_tokens)

        db_node_auto = db.get_edge_node_by_id(node["id"])
        self.assertEqual(db_node_auto["assigned_bot_token"], "")
        self.assertEqual(db_node_auto["target_dc_id"], 5)


if __name__ == "__main__":
    unittest.main()
