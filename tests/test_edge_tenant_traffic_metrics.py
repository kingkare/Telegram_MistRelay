import unittest
import asyncio
import time
from unittest.mock import patch, MagicMock

import db
from edge_node_manager import (
    mask_username,
    enrich_node_tenants,
    merge_node_tenants_metrics,
    sanitize_node_tenants_for_user,
    compute_edge_summary,
)
from edge_worker.worker_server import EdgeStreamingWorker


class TestEdgeTenantTrafficMetrics(unittest.IsolatedAsyncioTestCase):
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

    def test_mask_username(self):
        """测试多租户隐私脱敏函数"""
        self.assertEqual(mask_username("jiuyue"), "@jiu***")
        self.assertEqual(mask_username("@jiuyue"), "@jiu***")
        self.assertEqual(mask_username("admin"), "@adm***")
        self.assertEqual(mask_username("user"), "@use***")
        self.assertEqual(mask_username("bob"), "@bo***")
        self.assertEqual(mask_username("a"), "@a***")
        # 特殊或已知系统标识不打码
        self.assertEqual(mask_username("公共/访客"), "公共/访客")
        self.assertEqual(mask_username("租户#22"), "租户#22")

    def test_enrich_and_merge_node_tenants(self):
        """测试 Master 端租户指标富化与防回退合并"""
        # 1. 模拟上报数据
        raw_tenants = {
            "22": {
                "active_streams": 1,
                "net_tx": 2048000,
                "total_bytes": 50000000,
                "last_active": 1700000000.0,
            },
            "0": {
                "active_streams": 0,
                "net_tx": 0,
                "total_bytes": 10000000,
                "last_active": 1699999000.0,
            },
        }

        # 模拟 db.get_user_by_id
        with patch("db.get_user_by_id") as mock_get_user:
            def side_effect(uid):
                if uid == 22:
                    return {"id": 22, "username": "jiuyue", "role": "user"}
                return None
            mock_get_user.side_effect = side_effect

            enriched = enrich_node_tenants(raw_tenants, node_owner_id=22)
            self.assertEqual(len(enriched), 2)
            # 活跃的排在前面
            self.assertEqual(enriched[0]["tenant_id"], 22)
            self.assertEqual(enriched[0]["username"], "jiuyue")
            self.assertTrue(enriched[0]["is_owner"])
            self.assertEqual(enriched[0]["active_streams"], 1)
            self.assertEqual(enriched[0]["net_tx"], 2048000)

            # 公共访客
            self.assertEqual(enriched[1]["tenant_id"], 0)
            self.assertEqual(enriched[1]["username"], "公共/访客")
            self.assertFalse(enriched[1]["is_owner"])

            # 2. 模拟防回退合并（例如 Worker 重启，上报的 total_bytes 暂时变小）
            rebooted_raw = {
                "22": {
                    "active_streams": 2,
                    "net_tx": 4096000,
                    "total_bytes": 2000000,  # 小于历史 50000000
                    "last_active": 1700000100.0,
                }
            }
            merged = merge_node_tenants_metrics(enriched, rebooted_raw, node_owner_id=22)
            # tid 22 的 total_bytes 应该保持单调递增，取历史 50000000
            t22 = next(t for t in merged if t["tenant_id"] == 22)
            self.assertEqual(t22["total_bytes"], 50000000)
            self.assertEqual(t22["active_streams"], 2)
            self.assertEqual(t22["net_tx"], 4096000)
            # tid 0 虽未在本次心跳中出现，但也应保留历史流量，实时速率归零
            t0 = next(t for t in merged if t["tenant_id"] == 0)
            self.assertEqual(t0["total_bytes"], 10000000)
            self.assertEqual(t0["active_streams"], 0)
            self.assertEqual(t0["net_tx"], 0)

    def test_sanitize_node_tenants_for_user(self):
        """测试多租户隐私脱敏与权限隔离"""
        node = {
            "id": 1,
            "tenant_id": 22,
            "metrics": {
                "tenants": [
                    {
                        "tenant_id": 22,
                        "username": "jiuyue",
                        "active_streams": 1,
                        "net_tx": 1000,
                        "total_bytes": 5000,
                    },
                    {
                        "tenant_id": 5,
                        "username": "xiaoming",
                        "active_streams": 1,
                        "net_tx": 2000,
                        "total_bytes": 8000,
                    },
                    {
                        "tenant_id": 0,
                        "username": "公共/访客",
                        "active_streams": 0,
                        "net_tx": 0,
                        "total_bytes": 1000,
                    },
                ]
            }
        }

        # 1. 管理员视角：全部真实明文
        admin_view = sanitize_node_tenants_for_user(node, user_id=1, is_admin=True)
        t_list_admin = admin_view["metrics"]["tenants"]
        self.assertEqual(t_list_admin[0]["username"], "jiuyue")
        self.assertEqual(t_list_admin[1]["username"], "xiaoming")
        self.assertEqual(t_list_admin[2]["username"], "公共/访客")

        # 2. 租户 22 视角：本人 (22) 与 公共/访客 明文，其他借用者 (5) 脱敏为 @xia***
        user_view = sanitize_node_tenants_for_user(node, user_id=22, is_admin=False)
        t_list_user = user_view["metrics"]["tenants"]
        self.assertEqual(t_list_user[0]["username"], "jiuyue")
        self.assertEqual(t_list_user[1]["username"], "@xia***")
        self.assertTrue(t_list_user[1].get("masked"))
        self.assertEqual(t_list_user[2]["username"], "公共/访客")

    def test_worker_tenant_metrics_accounting(self):
        """测试 EdgeStreamingWorker 内部多租户流量记账与速率平滑统计"""
        worker = EdgeStreamingWorker(mock_stream=True)
        worker.start_time = time.time() - 10.0
        worker.last_mark_time = time.time() - 2.0

        # 模拟租户 22 与 租户 5 的会话与分片
        session_a = ("1.2.3.4", -1001, 100, 22, 1001)
        session_b = ("5.6.7.8", -1001, 101, 5, 1002)

        worker._record_stream_activity(session_a, tenant_id=22)
        worker._record_stream_activity(session_b, tenant_id=5)

        # 模拟产生流量
        worker._tenant_bytes[22] = 10 * 1024 * 1024  # 10MB
        worker._tenant_bytes[5] = 2 * 1024 * 1024   # 2MB
        worker.total_bytes_served = 12 * 1024 * 1024

        metrics = worker.get_system_metrics()
        self.assertIn("tenants", metrics)
        tenants = metrics["tenants"]
        self.assertIn("22", tenants)
        self.assertIn("5", tenants)

        # 检查租户 22 流量与活跃度
        self.assertEqual(tenants["22"]["tenant_id"], 22)
        self.assertEqual(tenants["22"]["total_bytes"], 10 * 1024 * 1024)
        self.assertGreaterEqual(tenants["22"]["active_streams"], 1)
        self.assertGreater(tenants["22"]["net_tx"], 0)

        # 检查租户 5 流量
        self.assertEqual(tenants["5"]["tenant_id"], 5)
        self.assertEqual(tenants["5"]["total_bytes"], 2 * 1024 * 1024)
        self.assertGreaterEqual(tenants["5"]["active_streams"], 1)

    def test_compute_edge_summary_aggregate_tenants(self):
        """测试 compute_edge_summary 聚合全集群租户总榜"""
        nodes = [
            {
                "id": 1,
                "status": "online",
                "allow_shared_pool": True,
                "metrics": {
                    "active_streams": 1,
                    "net_tx": 2000,
                    "total_bytes_served": 50000,
                    "tenants": [
                        {"tenant_id": 22, "username": "jiuyue", "active_streams": 1, "net_tx": 2000, "total_bytes": 50000},
                    ]
                }
            },
            {
                "id": 2,
                "status": "online",
                "allow_shared_pool": True,
                "metrics": {
                    "active_streams": 2,
                    "net_tx": 3000,
                    "total_bytes_served": 70000,
                    "tenants": [
                        {"tenant_id": 22, "username": "jiuyue", "active_streams": 1, "net_tx": 1000, "total_bytes": 30000},
                        {"tenant_id": 5, "username": "xiaoming", "active_streams": 1, "net_tx": 2000, "total_bytes": 40000},
                    ]
                }
            }
        ]

        summary = compute_edge_summary(nodes)
        self.assertEqual(summary["total_nodes"], 2)
        self.assertEqual(summary["active_streams"], 3)
        self.assertEqual(summary["total_tx_speed"], 5000)

        tenants_summary = summary.get("tenants", [])
        self.assertEqual(len(tenants_summary), 2)
        # 租户 22 聚合：2 节点，active 2，tx 3000，total 80000
        t22 = next(t for t in tenants_summary if t["tenant_id"] == 22)
        self.assertEqual(t22["active_streams"], 2)
        self.assertEqual(t22["net_tx"], 3000)
        self.assertEqual(t22["total_bytes"], 80000)
        self.assertEqual(t22["node_count"], 2)


if __name__ == "__main__":
    unittest.main()
