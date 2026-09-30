import edge_node_manager
import tests  # noqa: F401
import os
import json
import tempfile
import unittest
import sqlite3
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import db
import auth
from WebStreamer import Var
from edge_node_manager import (
    generate_edge_stream_ticket,
    verify_edge_stream_ticket,
    resolve_edge_redirect_url,
    edge_latency_router,
    extract_routing_client_ip,
    get_ip_subnet_key,
)
from edge_worker.worker_server import EdgeStreamingWorker, verify_ticket
from WebStreamer.server.stream_routes import (
    edge_nodes_list_handler,
    edge_nodes_create_handler,
    edge_nodes_update_handler,
    edge_nodes_delete_handler,
    edge_nodes_generate_token_handler,
    edge_serve_install_sh_handler,
    edge_serve_worker_script_handler,
    edge_node_config_handler,
    edge_register_with_token_handler,
    edge_node_heartbeat_handler,
    edge_nodes_test_handler,
    edge_nodes_deploy_logs_handler,
    edge_nodes_clear_password_handler,
    edge_available_nodes_handler,
    edge_client_latency_report_handler,
    resolve_edge_stream_url_handler,
)


class MockRequest(dict):
    def __init__(self, json_data=None, match_info=None, query=None, headers=None, user=None, remote="127.0.0.1"):
        super().__init__()
        self._json_data = json_data or {}
        self.match_info = match_info or {}
        self.query = query or {}
        self.headers = headers or {}
        self.remote = remote
        self.method = "GET"
        self.scheme = "http"
        self.host = "127.0.0.1:8080"
        if user:
            self["user"] = user

    async def json(self):
        return self._json_data


class TestEdgeStreamDispatch(unittest.IsolatedAsyncioTestCase):
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

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        if os.path.exists(self._tmp.name):
            os.unlink(self._tmp.name)
        edge_node_manager._bot_pool_cache = None

    def test_ticket_generation_and_tamper_verification(self):
        secret = "super_node_secret_key_12345"
        ticket = generate_edge_stream_ticket(
            tenant_id=self.alice_user["uid"],
            chat_id=-100111111111,
            message_id=505,
            file_unique_id="fuid_test_video",
            node_secret=secret,
            file_name="video.mp4",
            file_size=10485760,
            mime_type="video/mp4",
            dc_id=5,
            expire_seconds=3600,
        )
        self.assertTrue("." in ticket)

        # 正常验证
        ok, payload, reason = verify_edge_stream_ticket(ticket, secret, expected_message_id=505)
        self.assertTrue(ok)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["mid"], 505)
        self.assertEqual(payload["cid"], -100111111111)
        self.assertEqual(payload["fs"], 10485760)

        # 错误 secret 验证 -> 签名失败
        ok2, _, reason2 = verify_edge_stream_ticket(ticket, "wrong_secret", expected_message_id=505)
        self.assertFalse(ok2)
        self.assertIn("签名不匹配", reason2)

        # 消息 ID 不匹配
        ok3, _, reason3 = verify_edge_stream_ticket(ticket, secret, expected_message_id=999)
        self.assertFalse(ok3)
        self.assertIn("不一致", reason3)

        # 过期 ticket
        expired_ticket = generate_edge_stream_ticket(
            tenant_id=self.alice_user["uid"],
            chat_id=-100111111111,
            message_id=505,
            file_unique_id="fuid_test",
            node_secret=secret,
            expire_seconds=-10,
        )
        ok4, _, reason4 = verify_edge_stream_ticket(expired_ticket, secret, expected_message_id=505)
        self.assertFalse(ok4)
        self.assertIn("过期", reason4)

        # Edge Worker 本地校验函数对齐一致性测试
        w_ok, w_payload, w_reason = verify_ticket(ticket, secret, expected_mid=505)
        self.assertTrue(w_ok)
        self.assertEqual(w_payload["mid"], 505)

    def test_resolve_edge_redirect_url_logic(self):
        # 1. 租户 Alice 创建专属节点
        alice_node = db.create_edge_node(
            tenant_id=self.alice_user["uid"],
            node_name="Alice SG Node",
            ip="203.0.113.88",
            port=8090,
            status="online",
            include_secrets=True,
        )

        class DummyRequest:
            def __init__(self, query=None, user=None):
                self.query = query or {}
                self._user = user
                self.scheme = "http"
                self.host = "master.example.com"
            def get(self, key, default=None):
                if key == "user":
                    return self._user
                return default

        source_record = {
            "chat_id": -100111111111,
            "file_unique_id": "fuid_sample_1",
            "file_name": "movie.mp4",
            "file_size": 52428800,
            "mime_type": "video/mp4",
            "dc_id": 5,
        }

        # 正常分流：应该返回指向 Alice 节点的 302 URL
        req1 = DummyRequest()
        redir_url = resolve_edge_redirect_url(
            request=req1,
            message_id=777,
            secure_hash="abc123",
            source_record=source_record,
            record_chat_id=-100111111111,
        )
        self.assertIsNotNone(redir_url)
        self.assertTrue(redir_url.startswith("https://edge.203-0-113-88.sslip.io:8090/stream/abc123777?ticket="))
        self.assertIn("ticket=", redir_url)

        # 携带 direct=1 参数强制直连 -> 应跳过边缘分流返回 None
        req_direct = DummyRequest(query={"direct": "1"})
        redir_url_direct = resolve_edge_redirect_url(
            request=req_direct,
            message_id=777,
            secure_hash="abc123",
            source_record=source_record,
            record_chat_id=-100111111111,
        )
        self.assertIsNone(redir_url_direct)

        # 租户 Bob 请求自己频道的媒体，但 Bob 无专属节点且公共池无节点 -> 返回 None 回源 Master
        bob_record = {
            "chat_id": -100222222222,
            "file_unique_id": "fuid_sample_2",
            "file_name": "bob.mp4",
            "file_size": 1024,
            "mime_type": "video/mp4",
        }
        redir_bob_none = resolve_edge_redirect_url(
            request=req1,
            message_id=888,
            secure_hash="def456",
            source_record=bob_record,
            record_chat_id=-100222222222,
        )
        self.assertIsNone(redir_bob_none)

        # 现在将 Alice 的节点开启 allow_shared_pool=1 -> Bob 可以共享分流
        db.update_edge_node(alice_node["id"], allow_shared_pool=True)
        redir_bob_shared = resolve_edge_redirect_url(
            request=req1,
            message_id=888,
            secure_hash="def456",
            source_record=bob_record,
            record_chat_id=-100222222222,
        )
        self.assertIsNotNone(redir_bob_shared)
        self.assertTrue(redir_bob_shared.startswith("https://edge.203-0-113-88.sslip.io:8090/stream/def456888?ticket="))

        # 管理员在全局 BIN_CHANNEL 创建专用节点 (非共享)
        admin_node = db.create_edge_node(
            tenant_id=self.admin_user["uid"],
            node_name="Admin Edge Dedicated",
            ip="16.162.23.244",
            port=8090,
            status="online",
            allow_shared_pool=False,
            include_secrets=True,
        )
        global_rec = {
            "chat_id": -1001998444696,
            "file_unique_id": "fuid_global_video",
            "file_name": "sample.mp4",
            "file_size": 2048000,
            "mime_type": "video/mp4",
        }

        # 模拟 HTML5 <video> 标签请求 (无 request["user"], 但携带 preferred_node)
        req_video_tag = DummyRequest(query={"preferred_node": str(admin_node["id"])})
        redir_video = resolve_edge_redirect_url(
            request=req_video_tag,
            message_id=999,
            secure_hash="xyz789",
            source_record=global_rec,
            record_chat_id=-1001998444696,
        )
        self.assertIsNotNone(redir_video)
        self.assertTrue(redir_video.startswith("https://edge.16-162-23-244.sslip.io:8090/stream/xyz789999?ticket="))

        # 模拟 FFmpeg / Lavf 本地抽帧请求 -> 必须回源 Master (返回 None)
        class DummyFfmpegRequest(DummyRequest):
            def __init__(self, query=None):
                super().__init__(query=query)
                self.headers = {"User-Agent": "Lavf/59.27.100"}
        req_lavf = DummyFfmpegRequest(query={"preferred_node": str(admin_node["id"])})
        redir_lavf = resolve_edge_redirect_url(
            request=req_lavf,
            message_id=999,
            secure_hash="xyz789",
            source_record=global_rec,
            record_chat_id=-1001998444696,
        )
        self.assertIsNone(redir_lavf)

        # 模拟 HTML5 <video> 携带 uid 参数识别管理员身份
        req_uid = DummyRequest(query={"uid": str(self.admin_user["uid"])})
        redir_uid = resolve_edge_redirect_url(
            request=req_uid,
            message_id=999,
            secure_hash="xyz789",
            source_record=global_rec,
            record_chat_id=-1001998444696,
        )
        self.assertIsNotNone(redir_uid)
        self.assertTrue("https://edge.16-162-23-244.sslip.io:8090/stream/" in redir_uid or "https://edge.203-0-113-88.sslip.io:8090/stream/" in redir_uid)

    async def test_api_edge_nodes_tenant_rbac_isolation(self):
        # 1. Alice 创建自己的节点
        req_create = MockRequest(
            json_data={
                "node_name": "Alice Node 1",
                "ip": "203.0.113.11",
                "port": 8090,
                "ssh_host": "203.0.113.11",
                "ssh_user": "root",
                "ssh_password": "AliceSecretPassword",
                "allow_shared_pool": False,
            },
            user=self.alice_user,
        )
        resp_create = await edge_nodes_create_handler(req_create)
        self.assertEqual(resp_create.status, 200)
        alice_data = resp_create.body
        self.assertTrue(alice_data["success"])
        alice_node_id = alice_data["node"]["id"]
        self.assertEqual(alice_data["node"]["tenant_id"], self.alice_user["uid"])

        # 2. Bob 查询节点列表：只能看到 0 个（看不见 Alice 的节点）
        req_bob_list = MockRequest(user=self.bob_user)
        resp_bob_list = await edge_nodes_list_handler(req_bob_list)
        self.assertEqual(resp_bob_list.status, 200)
        self.assertEqual(len(resp_bob_list.body["nodes"]), 0)

        # 3. Bob 尝试越权修改 Alice 的节点 -> 403 Forbidden
        req_bob_edit = MockRequest(
            match_info={"node_id": str(alice_node_id)},
            json_data={"node_name": "Hacked by Bob"},
            user=self.bob_user,
        )
        resp_bob_edit = await edge_nodes_update_handler(req_bob_edit)
        self.assertEqual(resp_bob_edit.status, 403)

        # 4. Bob 尝试越权删除 Alice 的节点 -> 403 Forbidden
        req_bob_del = MockRequest(
            match_info={"node_id": str(alice_node_id)},
            user=self.bob_user,
        )
        resp_bob_del = await edge_nodes_delete_handler(req_bob_del)
        self.assertEqual(resp_bob_del.status, 403)

        # 5. 管理员查询列表：可见全局所有节点
        req_admin_list = MockRequest(user=self.admin_user)
        resp_admin_list = await edge_nodes_list_handler(req_admin_list)
        self.assertEqual(resp_admin_list.status, 200)
        self.assertEqual(len(resp_admin_list.body["nodes"]), 1)
        self.assertEqual(resp_admin_list.body["nodes"][0]["id"], alice_node_id)

    async def test_api_token_pairing_and_heartbeat(self):
        # 1. 生成配对 Token
        req_gen = MockRequest(
            json_data={
                "node_name": "AutoPairNode",
                "port": 8092,
                "allow_shared_pool": True,
            },
            user=self.alice_user,
        )
        resp_gen = await edge_nodes_generate_token_handler(req_gen)
        self.assertEqual(resp_gen.status, 200)
        token = resp_gen.body["token"]
        self.assertIn("install.sh?token=", resp_gen.body["command"])

        # 2. 公网拉取 install.sh
        req_sh = MockRequest(query={"token": token})
        resp_sh = await edge_serve_install_sh_handler(req_sh)
        self.assertEqual(resp_sh.status, 200)
        self.assertIn("MistRelay", resp_sh.body)

        # 3. 边缘脚本上报配对注册
        req_reg = MockRequest(
            json_data={
                "token": token,
                "ip": "198.51.100.99",
                "port": 8092,
            },
        )
        resp_reg = await edge_register_with_token_handler(req_reg)
        self.assertEqual(resp_reg.status, 200)
        self.assertTrue(resp_reg.body["success"])
        node_id = resp_reg.body["node_id"]
        auth_secret = resp_reg.body["auth_secret"]

        # 4. 边缘节点通过 secret 拉取 MTProto 配置
        req_cfg = MockRequest(headers={"X-Node-Secret": auth_secret})
        resp_cfg = await edge_node_config_handler(req_cfg)
        self.assertEqual(resp_cfg.status, 200)
        self.assertTrue(resp_cfg.body["success"])
        self.assertEqual(resp_cfg.body["config"]["node_id"], node_id)

        # 5. 边缘节点上报心跳
        req_hb = MockRequest(
            json_data={
                "secret": auth_secret,
                "port": 8092,
                "metrics": {
                    "cpu": 12.5,
                    "mem": 34.2,
                    "active_streams": 2,
                    "net_tx": 2097152,
                    "total_bytes_served": 104857600,
                },
            },
        )
        resp_hb = await edge_node_heartbeat_handler(req_hb)
        self.assertEqual(resp_hb.status, 200)
        self.assertTrue(resp_hb.body["success"])

        # 6. 验证数据库中该节点更新为 online 且 metrics 正常
        updated_node = db.get_edge_node_by_id(node_id)
        self.assertEqual(updated_node["status"], "online")
        self.assertEqual(updated_node["metrics"]["active_streams"], 2)
        self.assertEqual(updated_node["metrics"]["net_tx"], 2097152)

    async def test_edge_worker_health_and_streaming_handler(self):
        worker = EdgeStreamingWorker(
            port=8090,
            node_secret="mock_worker_secret_999",
            mock_stream=True,
        )

        # 1. 测试 handle_health
        req_h = MockRequest()
        resp_h = await worker.handle_health(req_h)
        self.assertEqual(resp_h.status, 200)
        self.assertEqual(resp_h.body["status"], "online")

        # 2. 伪造错误 ticket 请求 handle_stream
        class StreamReq:
            def __init__(self, path, ticket="", range_hdr=""):
                self.match_info = {"path": path}
                self.query = {"ticket": ticket}
                self.headers = {"Range": range_hdr} if range_hdr else {}
                self.method = "GET"

        bad_req = StreamReq("abc123100", ticket="invalid_ticket")
        bad_resp = await worker.handle_stream(bad_req)
        self.assertEqual(bad_resp.status, 403)

        # 3. 正常签发 ticket 请求 handle_stream
        valid_ticket = generate_edge_stream_ticket(
            tenant_id=1,
            chat_id=-100111111111,
            message_id=100,
            file_unique_id="fuid_worker_100",
            node_secret="mock_worker_secret_999",
            file_size=65536,
            mime_type="video/mp4",
        )
        good_req = StreamReq("abc123100", ticket=valid_ticket)
        good_resp = await worker.handle_stream(good_req)
        self.assertEqual(good_resp.status, 200)
        self.assertEqual(good_resp.headers["Content-Length"], "65536")
        self.assertEqual(good_resp.headers["Content-Type"], "video/mp4")

        # 4. 带 Range 头的请求 -> 206 Partial Content
        range_req = StreamReq("abc123100", ticket=valid_ticket, range_hdr="bytes=0-1023")
        range_resp = await worker.handle_stream(range_req)
        self.assertEqual(range_resp.status, 206)
        self.assertEqual(range_resp.headers["Content-Range"], "bytes 0-1023/65536")
        self.assertEqual(range_resp.headers["Content-Length"], "1024")

        # 5. 测试 32位十六进制哈希前缀的 stream 路径及 OPTIONS 预检请求
        hex32_ticket = generate_edge_stream_ticket(
            tenant_id=1,
            chat_id=-1001998444696,
            message_id=6097,
            file_unique_id="fuid_6097",
            node_secret="mock_worker_secret_999",
            file_size=340260237,
            mime_type="video/mp4",
        )
        hex32_req = StreamReq("019fe70f5517ca206d1f20e59d19f4726097", ticket=hex32_ticket)
        hex32_resp = await worker.handle_stream(hex32_req)
        self.assertEqual(hex32_resp.status, 200)
        self.assertEqual(hex32_resp.headers["Content-Length"], "340260237")

        opt_req = StreamReq("019fe70f5517ca206d1f20e59d19f4726097")
        opt_req.method = "OPTIONS"
        opt_resp = await worker.handle_stream(opt_req)
        self.assertEqual(opt_resp.status, 204)
        self.assertEqual(opt_resp.headers["Access-Control-Allow-Origin"], "*")


    async def test_low_latency_auto_routing_and_subnet_caching(self):
        hk_node = db.create_edge_node(
            tenant_id=self.alice_user["uid"],
            node_name="HongKong Node",
            domain="hk.stream.example.com",
            port=443,
            use_ssl=True,
            auth_secret="sec_hk_123",
        )
        db.update_edge_node(
            hk_node["id"],
            status="online",
            benchmark_data={
                "fastest_dc": {"id": 5, "name": "DC5 亚太 (Singapore)", "avg_rtt_ms": 30.0},
                "dcs": [{"dc_id": 5, "avg_rtt_ms": 30.0}, {"dc_id": 1, "avg_rtt_ms": 220.0}],
            },
        )

        us_node = db.create_edge_node(
            tenant_id=self.alice_user["uid"],
            node_name="US West Node",
            domain="us.stream.example.com",
            port=443,
            use_ssl=True,
            auth_secret="sec_us_456",
        )
        db.update_edge_node(
            us_node["id"],
            status="online",
            benchmark_data={
                "fastest_dc": {"id": 1, "name": "DC1 美西 (Miami)", "avg_rtt_ms": 35.0},
                "dcs": [{"dc_id": 1, "avg_rtt_ms": 35.0}, {"dc_id": 5, "avg_rtt_ms": 200.0}],
            },
        )

        # 模拟前端测速上报：亚洲客户端到香港 18ms，到美西 195ms
        edge_latency_router.record_client_latency("203.0.113.55", hk_node["id"], 18.0, source="browser")
        edge_latency_router.record_client_latency("203.0.113.55", us_node["id"], 195.0, source="browser")

        req_alice_hk = MockRequest(
            headers={"CF-Connecting-IP": "203.0.113.55"},
            user=self.alice_user,
        )
        redir_hk = resolve_edge_redirect_url(
            request=req_alice_hk,
            message_id=901,
            secure_hash="hash901",
            source_record={"dc_id": 5, "file_unique_id": "vid_dc5"},
            record_chat_id=-100111111111,
        )
        self.assertIsNotNone(redir_hk)
        self.assertTrue(redir_hk.startswith("https://hk.stream.example.com/stream/hash901901?ticket="))

        # 同一 /24 网段的新 IP (203.0.113.88) 自动复用缓存选优
        req_alice_subnet = MockRequest(
            headers={"X-Real-IP": "203.0.113.88"},
            user=self.alice_user,
        )
        redir_subnet = resolve_edge_redirect_url(
            request=req_alice_subnet,
            message_id=902,
            secure_hash="hash902",
            source_record={"dc_id": 5, "file_unique_id": "vid_dc5_2"},
            record_chat_id=-100111111111,
        )
        self.assertTrue(redir_subnet.startswith("https://hk.stream.example.com/stream/hash902902?ticket="))

        # 美洲客户端 (198.51.100.22) 上报到美西 25ms，到香港 215ms，播放 DC1 媒体
        edge_latency_router.record_client_latency("198.51.100.22", us_node["id"], 25.0, source="browser")
        edge_latency_router.record_client_latency("198.51.100.22", hk_node["id"], 215.0, source="browser")

        req_alice_us = MockRequest(
            headers={"X-Forwarded-For": "198.51.100.22, 10.0.0.1"},
            user=self.alice_user,
        )
        redir_us = resolve_edge_redirect_url(
            request=req_alice_us,
            message_id=903,
            secure_hash="hash903",
            source_record={"dc_id": 1, "file_unique_id": "vid_dc1"},
            record_chat_id=-100111111111,
        )
        self.assertTrue(redir_us.startswith("https://us.stream.example.com/stream/hash903903?ticket="))

    async def test_preferred_node_override_and_direct_fallback(self):
        alice_node = db.create_edge_node(
            tenant_id=self.alice_user["uid"],
            node_name="Alice Node",
            ip="203.0.113.11",
            port=8090,
            auth_secret="sec_alice_1",
            allow_shared_pool=False,
        )
        db.update_edge_node(alice_node["id"], status="online")

        shared_node = db.create_edge_node(
            tenant_id=self.admin_user["uid"],
            node_name="Global Shared Node",
            ip="198.51.100.88",
            port=8090,
            auth_secret="sec_shared_1",
            allow_shared_pool=True,
        )
        db.update_edge_node(shared_node["id"], status="online")

        # 默认专属池优先命中自己的专属节点
        req_norm = MockRequest(user=self.alice_user)
        redir_norm = resolve_edge_redirect_url(
            request=req_norm,
            message_id=910,
            secure_hash="h910",
            source_record={},
            record_chat_id=-100111111111,
        )
        self.assertTrue(redir_norm.startswith("https://edge.203-0-113-11.sslip.io:8090/stream/h910910"))

        # Alice 显式指定 preferred_node 切换至共享节点
        req_pref = MockRequest(
            query={"preferred_node": str(shared_node["id"])},
            user=self.alice_user,
        )
        redir_pref = resolve_edge_redirect_url(
            request=req_pref,
            message_id=910,
            secure_hash="h910",
            source_record={},
            record_chat_id=-100111111111,
        )
        self.assertTrue(redir_pref.startswith("https://edge.198-51-100-88.sslip.io:8090/stream/h910910"))

        # Bob 尝试指定 Alice 的私有非共享节点 -> 安全拦截，回退到共享节点
        req_bob_hack = MockRequest(
            query={"preferred_node": str(alice_node["id"])},
            user=self.bob_user,
        )
        redir_bob = resolve_edge_redirect_url(
            request=req_bob_hack,
            message_id=910,
            secure_hash="h910",
            source_record={},
            record_chat_id=-100222222222,
        )
        self.assertTrue(redir_bob.startswith("https://edge.198-51-100-88.sslip.io:8090/stream/h910910"))

        # direct=1 回源主控直出
        req_direct = MockRequest(
            query={"direct": "1"},
            user=self.alice_user,
        )
        redir_direct = resolve_edge_redirect_url(
            request=req_direct,
            message_id=910,
            secure_hash="h910",
            source_record={},
            record_chat_id=-100111111111,
        )
        self.assertIsNone(redir_direct)

    async def test_edge_available_nodes_and_latency_reporting_api(self):
        alice_node = db.create_edge_node(
            tenant_id=self.alice_user["uid"],
            node_name="Alice Node",
            ip="203.0.113.11",
            port=8090,
            auth_secret="sec_alice_1",
            allow_shared_pool=False,
        )
        db.update_edge_node(alice_node["id"], status="online")

        shared_node = db.create_edge_node(
            tenant_id=self.admin_user["uid"],
            node_name="Shared Public Node",
            ip="198.51.100.88",
            port=8090,
            auth_secret="sec_shared_1",
            allow_shared_pool=True,
        )
        db.update_edge_node(shared_node["id"], status="online")

        req_avail = MockRequest(user=self.alice_user)
        resp_avail = await edge_available_nodes_handler(req_avail)
        self.assertEqual(resp_avail.status, 200)
        nodes = resp_avail.body["nodes"]
        self.assertEqual(len(nodes), 2)
        node_map = {n["id"]: n for n in nodes}
        self.assertTrue(node_map[alice_node["id"]]["is_dedicated"])
        self.assertFalse(node_map[shared_node["id"]]["is_dedicated"])
        self.assertEqual(node_map[alice_node["id"]]["ping_url"], "https://edge.203-0-113-11.sslip.io:8090/ping")

        req_report = MockRequest(
            json_data={
                "latencies": [
                    {"node_id": alice_node["id"], "rtt_ms": 22.4},
                    {"node_id": shared_node["id"], "rtt_ms": 88.5},
                ]
            },
            headers={"CF-Connecting-IP": "116.25.120.40"},
            user=self.alice_user,
        )
        resp_report = await edge_client_latency_report_handler(req_report)
        self.assertEqual(resp_report.status, 200)
        self.assertEqual(resp_report.body["recorded"], 2)

        entry = edge_latency_router.get_cached_entry("116.25.120.40", alice_node["id"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry["rtt_ms"], 22.4)
        self.assertEqual(entry["source"], "browser")

    async def test_worker_ping_and_probe_client(self):
        worker = EdgeStreamingWorker(
            port=8090,
            node_secret="probe_secret_123",
            mock_stream=True,
        )

        req_ping = MockRequest()
        resp_ping = await worker.handle_ping(req_ping)
        self.assertEqual(resp_ping.status, 200)
        self.assertTrue(resp_ping.body["pong"])
        self.assertIn("Access-Control-Allow-Origin", resp_ping.headers)
        self.assertEqual(resp_ping.headers["Access-Control-Allow-Origin"], "*")

        req_opt = MockRequest()
        req_opt.method = "OPTIONS"
        resp_opt = await worker.handle_ping(req_opt)
        self.assertEqual(resp_opt.status, 204)
        self.assertEqual(resp_opt.headers["Access-Control-Allow-Methods"], "GET, HEAD, OPTIONS")

        req_unauth = MockRequest(query={"ip": "8.8.8.8"})
        resp_unauth = await worker.handle_probe_client(req_unauth)
        self.assertEqual(resp_unauth.status, 401)

        req_priv = MockRequest(
            query={"ip": "192.168.1.1", "secret": "probe_secret_123"},
        )
        resp_priv = await worker.handle_probe_client(req_priv)
        self.assertEqual(resp_priv.status, 200)
        self.assertFalse(resp_priv.body["reachable"])
        self.assertEqual(resp_priv.body["reason"], "private_or_reserved_ip")


    async def test_api_resolve_stream_url(self):
        # 创建测试节点与测试媒体
        node = db.create_edge_node(
            tenant_id=self.alice_user["uid"],
            node_name="Alice Test Edge",
            ip="203.0.113.88",
            port=8090,
            auth_secret="sec_alice_test",
            status="online",
        )
        with sqlite3.connect(db.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tg_media (file_unique_id, chat_id, message_id, file_id, file_name, file_size, mime_type, message_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                ("fuid_resolve_5555", -100111111111, 5555, "fid_resolve_5555", "test_video.mp4", 10485760, "video/mp4"),
            )

        # 1. 成功解析边缘直链 (指定 preferred_node)
        req_resolve = MockRequest(
            json_data={
                "message_id": 5555,
                "preferred_node": str(node["id"]),
            },
            user=self.alice_user,
        )
        resp_resolve = await resolve_edge_stream_url_handler(req_resolve)
        self.assertEqual(resp_resolve.status, 200)
        self.assertTrue(resp_resolve.body["success"])
        self.assertTrue(resp_resolve.body["is_edge"])
        self.assertEqual(resp_resolve.body["node_id"], node["id"])
        self.assertIn("https://edge.203-0-113-88.sslip.io:8090/stream/", resp_resolve.body["url"])
        self.assertIn("ticket=", resp_resolve.body["url"])

        # 2. 解析带 download=true 的下载直链
        req_dl = MockRequest(
            json_data={
                "message_id": 5555,
                "preferred_node": str(node["id"]),
                "download": True,
            },
            user=self.alice_user,
        )
        resp_dl = await resolve_edge_stream_url_handler(req_dl)
        self.assertEqual(resp_dl.status, 200)
        self.assertIn("download=1", resp_dl.body["url"])

        # 3. 指定 preferred_node="direct" -> 回退主控直出
        req_direct = MockRequest(
            json_data={
                "message_id": 5555,
                "preferred_node": "direct",
            },
            user=self.alice_user,
        )
        resp_direct = await resolve_edge_stream_url_handler(req_direct)
        self.assertEqual(resp_direct.status, 200)
        self.assertTrue(resp_direct.body["success"])
        self.assertFalse(resp_direct.body["is_edge"])
        self.assertIn("direct=1", resp_direct.body["url"])

        # 4. 缺少 message_id -> 400
        req_bad = MockRequest(json_data={}, user=self.alice_user)
        resp_bad = await resolve_edge_stream_url_handler(req_bad)
        self.assertEqual(resp_bad.status, 400)


if __name__ == "__main__":
    unittest.main()
