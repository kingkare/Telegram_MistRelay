import unittest
import json
import asyncio
from unittest.mock import patch, MagicMock

import db
import auth
from WebStreamer.server.ws_manager import WebSocketManager
from edge_node_manager import (
    compute_edge_summary,
    broadcast_edge_node_update,
    broadcast_edge_node_deleted,
    broadcast_edge_deploy_log,
)


class FakeWebSocket:
    def __init__(self, sink: list):
        self.closed = False
        self._sink = sink

    async def send_str(self, s: str):
        self._sink.append(json.loads(s))

    async def send_json(self, data: dict):
        self._sink.append(data)


class TestEdgeRealtimeWebSocket(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile, os
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()

    async def asyncTearDown(self):
        import os
        db.DB_PATH = self.orig_db_path
        if hasattr(self, "_tmp") and os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except OSError:
                pass

    async def test_ws_manager_edge_node_broadcast_isolation(self):
        """测试 WebSocket 管理器在边缘节点事件推送时的租户隔离机制"""
        mgr = WebSocketManager()
        sent_admin, sent_tenant_a, sent_tenant_b = [], [], []

        ws_admin = FakeWebSocket(sent_admin)
        ws_a = FakeWebSocket(sent_tenant_a)
        ws_b = FakeWebSocket(sent_tenant_b)

        await mgr.add_connection(ws_admin, user_id=1, role="admin")
        await mgr.add_connection(ws_a, user_id=101, role="user")
        await mgr.add_connection(ws_b, user_id=102, role="user")

        # 1. 租户 101 的边缘节点指标/心跳更新
        node_101 = {
            "id": 1,
            "tenant_id": 101,
            "node_name": "Tenant A Edge",
            "status": "online",
            "metrics": {"active_streams": 3, "net_tx": 5242880},
        }
        await mgr.send_edge_node_update(node_101, summary={"active_streams": 3})

        # 管理员和租户 A 应该收到更新，租户 B 绝不应该收到
        self.assertEqual(len(sent_admin), 1)
        self.assertEqual(len(sent_tenant_a), 1)
        self.assertEqual(len(sent_tenant_b), 0)
        self.assertEqual(sent_admin[0]["type"], "edge_node_update")
        self.assertEqual(sent_admin[0]["data"]["node"]["id"], 1)
        self.assertEqual(sent_tenant_a[0]["data"]["node"]["id"], 1)

        # 2. 租户 101 节点的 SSH 实时部署日志流
        await mgr.send_edge_deploy_log(
            node_id=1,
            line="[12:00:01] Docker 容器拉取中...",
            status="deploying",
            target_user_id=101,
        )
        self.assertEqual(len(sent_admin), 2)
        self.assertEqual(len(sent_tenant_a), 2)
        self.assertEqual(len(sent_tenant_b), 0)
        self.assertEqual(sent_admin[1]["type"], "edge_deploy_log")
        self.assertEqual(sent_admin[1]["data"]["line"], "[12:00:01] Docker 容器拉取中...")

        # 3. 租户 102 的一键脚本配对成功事件
        node_102 = {
            "id": 2,
            "tenant_id": 102,
            "node_name": "Tenant B Edge",
            "status": "online",
        }
        await mgr.send_edge_token_used(token="tok_102_xyz", node_data=node_102)
        # 管理员和租户 B 收到，租户 A 绝不应该收到
        self.assertEqual(len(sent_admin), 3)
        self.assertEqual(len(sent_tenant_a), 2)
        self.assertEqual(len(sent_tenant_b), 1)
        self.assertEqual(sent_tenant_b[0]["type"], "edge_token_used")
        self.assertEqual(sent_tenant_b[0]["data"]["token"], "tok_102_xyz")

        # 4. 节点删除事件推送
        await mgr.send_edge_node_deleted(node_id=1, target_user_id=101)
        self.assertEqual(len(sent_admin), 4)
        self.assertEqual(len(sent_tenant_a), 3)
        self.assertEqual(len(sent_tenant_b), 1)
        self.assertEqual(sent_tenant_a[2]["type"], "edge_node_deleted")
        self.assertEqual(sent_tenant_a[2]["data"]["node_id"], 1)

    def test_compute_edge_summary(self):
        """测试边缘节点 KPI 汇总指标计算"""
        mock_nodes = [
            {
                "id": 1,
                "status": "online",
                "allow_shared_pool": 1,
                "metrics": {"active_streams": 2, "net_tx": 2048, "total_bytes_served": 50000},
            },
            {
                "id": 2,
                "status": "online",
                "allow_shared_pool": 0,
                "metrics": {"active_streams": 1, "net_tx": 1024, "total_bytes_served": 30000},
            },
            {
                "id": 3,
                "status": "deploying",
                "allow_shared_pool": 0,
                "metrics": {},
            },
            {
                "id": 4,
                "status": "offline",
                "allow_shared_pool": 1,
                "metrics": {},
            },
        ]
        s = compute_edge_summary(mock_nodes)
        self.assertEqual(s["total_nodes"], 4)
        self.assertEqual(s["online_nodes"], 2)
        self.assertEqual(s["deploying_nodes"], 1)
        self.assertEqual(s["shared_pool_nodes"], 1)
        self.assertEqual(s["active_streams"], 3)
        self.assertEqual(s["total_tx_speed"], 3072)
        self.assertEqual(s["total_bytes_served"], 80000)

    @patch("WebStreamer.server.ws_manager.ws_manager")
    async def test_broadcast_edge_node_update_dual_view(self, mock_ws_mgr):
        """测试 broadcast_edge_node_update 向管理员和所属租户发送各自独立的 summary"""
        mock_ws_mgr.send_edge_node_update = MagicMock(return_value=asyncio.sleep(0))

        test_node = {
            "id": 99,
            "tenant_id": 55,
            "node_name": "Node Dual View",
            "status": "online",
            "metrics": {},
        }

        with patch("db.get_edge_node_by_id", return_value=test_node), \
             patch("db.list_edge_nodes") as mock_list:
            mock_list.side_effect = [
                # First call: for admin (tenant_id=None)
                [test_node, {"id": 100, "status": "online", "metrics": {}}],
                # Second call: for tenant 55
                [test_node],
            ]

            await broadcast_edge_node_update(99)

            self.assertEqual(mock_ws_mgr.send_edge_node_update.call_count, 2)
            # Call 1: for admin
            call_admin = mock_ws_mgr.send_edge_node_update.call_args_list[0]
            self.assertIsNone(call_admin.kwargs["target_user_id"])
            self.assertEqual(call_admin.kwargs["summary"]["total_nodes"], 2)

            # Call 2: for tenant 55
            call_tenant = mock_ws_mgr.send_edge_node_update.call_args_list[1]
            self.assertEqual(call_tenant.kwargs["target_user_id"], 55)
            self.assertEqual(call_tenant.kwargs["summary"]["total_nodes"], 1)


    async def test_edge_nodes_update_admin_and_tenant_isolation(self):
        """测试全量/租户节点列表推送时，租户子列表绝不推送给管理员以防止节点被刷没"""
        mgr = WebSocketManager()
        sent_admin, sent_tenant_a, sent_tenant_b = [], [], []

        ws_admin = FakeWebSocket(sent_admin)
        ws_a = FakeWebSocket(sent_tenant_a)
        ws_b = FakeWebSocket(sent_tenant_b)

        await mgr.add_connection(ws_admin, user_id=1, role="admin")
        await mgr.add_connection(ws_a, user_id=101, role="user")
        await mgr.add_connection(ws_b, user_id=102, role="user")

        all_nodes = [
            {"id": 1, "tenant_id": 101, "node_name": "Node A"},
            {"id": 2, "tenant_id": 102, "node_name": "Node B"},
            {"id": 3, "tenant_id": None, "node_name": "Node Admin"},
        ]
        admin_summary = {"total_nodes": 3}
        tenant_a_nodes = [{"id": 1, "tenant_id": 101, "node_name": "Node A"}]
        tenant_a_summary = {"total_nodes": 1}

        # 1. 向管理员广播全集群全量节点
        await mgr.send_edge_nodes_update(all_nodes, summary=admin_summary, target_user_id=None)
        self.assertEqual(len(sent_admin), 1)
        self.assertEqual(len(sent_tenant_a), 0)
        self.assertEqual(len(sent_tenant_b), 0)
        self.assertEqual(sent_admin[0]["data"]["nodes"], all_nodes)
        self.assertEqual(sent_admin[0]["data"]["summary"]["total_nodes"], 3)

        # 2. 向租户 A 推送专属单节点列表
        await mgr.send_edge_nodes_update(tenant_a_nodes, summary=tenant_a_summary, target_user_id=101)
        # 核心断言：租户 A 收到，管理员绝不收到租户子集（否则管理员视图中的 Node B / Node Admin 会被前端刷没过滤掉）
        self.assertEqual(len(sent_admin), 1)  # 保持 1，未被污染
        self.assertEqual(len(sent_tenant_a), 1)
        self.assertEqual(len(sent_tenant_b), 0)
        self.assertEqual(sent_tenant_a[0]["data"]["nodes"], tenant_a_nodes)
        self.assertEqual(sent_tenant_a[0]["data"]["summary"]["total_nodes"], 1)

    async def test_broadcast_edge_node_update_real_ws_isolation(self):
        """真实 WebSocket 连接测试：broadcast_edge_node_update 确保管理员与租户互不污染 summary"""
        from WebStreamer.server.ws_manager import ws_manager
        sent_admin, sent_tenant = [], []
        ws_admin = FakeWebSocket(sent_admin)
        ws_tenant = FakeWebSocket(sent_tenant)

        await ws_manager.add_connection(ws_admin, user_id=1, role="admin")
        await ws_manager.add_connection(ws_tenant, user_id=88, role="user")

        test_node = {
            "id": 888,
            "tenant_id": 88,
            "node_name": "Realtime Edge Node",
            "status": "online",
            "metrics": {},
        }

        try:
            with patch("db.get_edge_node_by_id", return_value=test_node), \
                 patch("db.list_edge_nodes") as mock_list:
                mock_list.side_effect = [
                    # 第一次 list_edge_nodes (admin): 返回 5 个全网节点
                    [test_node, {"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}],
                    # 第二次 list_edge_nodes (tenant 88): 返回 1 个所属节点
                    [test_node],
                ]

                await broadcast_edge_node_update(888)

                # 管理员仅收到 1 次针对管理员的广播（包含 5 个节点的全网 summary）
                self.assertEqual(len(sent_admin), 1)
                self.assertEqual(sent_admin[0]["data"]["summary"]["total_nodes"], 5)

                # 租户 88 仅收到 1 次针对该租户的定向广播（包含 1 个节点的个人 summary）
                self.assertEqual(len(sent_tenant), 1)
                self.assertEqual(sent_tenant[0]["data"]["summary"]["total_nodes"], 1)
        finally:
            await ws_manager.remove_connection(ws_admin)
            await ws_manager.remove_connection(ws_tenant)

if __name__ == "__main__":

    unittest.main()
