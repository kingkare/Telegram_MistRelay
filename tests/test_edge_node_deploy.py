import os
import time
import tempfile
import unittest
from datetime import datetime, timezone

import db
import vps_deployer


class TestEdgeNodeDeploy(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_db_path = db.DB_PATH
        self.db_path = os.path.join(self.temp_dir.name, "test_edge.db")
        db.DB_PATH = self.db_path
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()

    def test_default_edge_domain_helper(self):
        self.assertEqual(db.get_default_edge_domain("16.162.23.244"), "edge.16-162-23-244.sslip.io")
        self.assertEqual(db.get_default_edge_domain("203.0.113.88"), "edge.203-0-113-88.sslip.io")
        self.assertEqual(db.get_default_edge_domain("custom.example.com"), "custom.example.com")
        self.assertEqual(db.get_default_edge_domain("127.0.0.1"), "")
        self.assertEqual(db.get_default_edge_domain("localhost"), "")
        self.assertEqual(db.get_default_edge_domain(""), "")

    def test_auto_domain_and_ssl_on_create_and_token(self):
        # 1. 创建节点留空 domain -> 自动绑定 edge.<ip>.sslip.io 并启用 SSL
        node = db.create_edge_node(
            tenant_id=201,
            node_name="AutoDomainNode",
            ip="198.51.100.55",
            port=8090,
        )
        self.assertEqual(node["domain"], "edge.198-51-100-55.sslip.io")
        self.assertTrue(node["use_ssl"])

        # 2. 一键脚本 Token 兑现留空 domain -> 自动生成
        tok_data = db.create_edge_node_token(
            tenant_id=201,
            node_name="AutoTokenNode",
            port=8090,
        )
        consumed = db.verify_and_consume_edge_node_token(
            token=tok_data["token"],
            ip="203.0.113.99",
            port=8090,
        )
        self.assertIsNotNone(consumed)
        self.assertEqual(consumed["domain"], "edge.203-0-113-99.sslip.io")
        self.assertTrue(consumed["use_ssl"])

    def test_init_db_migration_for_legacy_nodes(self):
        # 手动向数据库插入缺失域名的旧版本节点
        with db.db_conn() as conn:
            conn.execute(
                """
                INSERT INTO edge_nodes (
                    tenant_id, node_name, ip, port, domain, use_ssl, auth_secret, status,
                    allow_shared_pool, created_at, updated_at
                ) VALUES (202, 'LegacyNode', '192.0.2.77', 8090, '', 0, 'sec_leg', 'online', 0, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
                """
            )
        # 触发数据库初始化自愈迁移
        db.init_db()
        nodes = db.list_edge_nodes(tenant_id=202)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["domain"], "edge.192-0-2-77.sslip.io")
        self.assertTrue(nodes[0]["use_ssl"])

    def test_ssh_password_encryption_roundtrip(self):
        raw_pwd = "P@ssw0rd!#$12345678_very_secret"
        encrypted = db.encrypt_ssh_password(raw_pwd)
        self.assertNotEqual(encrypted, raw_pwd)
        self.assertTrue(len(encrypted) > 20)

        decrypted = db.decrypt_ssh_password(encrypted)
        self.assertEqual(decrypted, raw_pwd)

        # 篡改密文测试
        tampered = encrypted[:-4] + "ABCD"
        self.assertEqual(db.decrypt_ssh_password(tampered), "")

    def test_edge_node_crud_and_secret_masking(self):
        node = db.create_edge_node(
            tenant_id=101,
            node_name="SG VPS Edge 1",
            ip="203.0.113.10",
            port=8090,
            ssh_host="203.0.113.10",
            ssh_port=22,
            ssh_user="root",
            ssh_password="SuperSecretPassword!",
            domain="edge1.example.com",
            use_ssl=True,
            allow_shared_pool=True,
            status="offline",
        )
        self.assertIsNotNone(node)
        self.assertEqual(node["node_name"], "SG VPS Edge 1")
        self.assertEqual(node["tenant_id"], 101)
        self.assertTrue(node["use_ssl"])
        self.assertTrue(node["allow_shared_pool"])
        self.assertTrue(node["has_ssh_password"])
        # 默认屏蔽密码和敏感明文
        self.assertNotIn("ssh_password_enc", node)
        self.assertNotIn("auth_secret", node)
        self.assertIn("auth_secret_masked", node)

        # 读取明文版
        node_with_sec = db.get_edge_node_by_id(node["id"], include_secrets=True)
        self.assertIsNotNone(node_with_sec["auth_secret"])
        dec_pwd = db.decrypt_ssh_password(node_with_sec["ssh_password_enc"])
        self.assertEqual(dec_pwd, "SuperSecretPassword!")

        # 更新节点
        updated = db.update_edge_node(
            node["id"],
            node_name="SG VPS Edge 1 (Renamed)",
            status="online",
            metrics={"active_streams": 3, "net_tx": 1048576},
        )
        self.assertEqual(updated["node_name"], "SG VPS Edge 1 (Renamed)")
        self.assertEqual(updated["status"], "online")
        self.assertEqual(updated["metrics"]["active_streams"], 3)

        # 列表查询
        tenant_nodes = db.list_edge_nodes(tenant_id=101)
        self.assertEqual(len(tenant_nodes), 1)
        other_nodes = db.list_edge_nodes(tenant_id=999)
        self.assertEqual(len(other_nodes), 0)

        # 擦除密码
        self.assertTrue(db.clear_edge_node_ssh_password(node["id"]))
        cleared = db.get_edge_node_by_id(node["id"], include_secrets=True)
        self.assertFalse(cleared["has_ssh_password"])
        self.assertEqual(cleared["ssh_password_enc"], "")

        # 删除节点
        self.assertTrue(db.delete_edge_node(node["id"]))
        self.assertIsNone(db.get_edge_node_by_id(node["id"]))

    def test_token_creation_and_consumption(self):
        tok_data = db.create_edge_node_token(
            tenant_id=102,
            node_name="SelfInstallNode",
            port=8095,
            domain="self.example.com",
            allow_shared_pool=True,
            expires_minutes=30,
        )
        token = tok_data["token"]
        self.assertTrue(token)

        info = db.get_edge_node_token(token)
        self.assertIsNotNone(info)
        self.assertEqual(info["node_name"], "SelfInstallNode")
        self.assertFalse(info["used"])
        self.assertFalse(info["expired"])

        # 核销 Token
        consumed_node = db.verify_and_consume_edge_node_token(
            token=token,
            ip="198.51.100.22",
            port=8095,
        )
        self.assertIsNotNone(consumed_node)
        self.assertEqual(consumed_node["tenant_id"], 102)
        self.assertEqual(consumed_node["ip"], "198.51.100.22")
        self.assertEqual(consumed_node["port"], 8095)
        self.assertEqual(consumed_node["status"], "online")

        # 再次核销应当被拒绝
        re_consumed = db.verify_and_consume_edge_node_token(token=token)
        self.assertIsNone(re_consumed)

    def test_remote_deploy_script_builder(self):
        script = vps_deployer.build_remote_deploy_script(
            port=8090,
            auth_secret="sec_test_123456",
            master_url="http://master.example.com:8080",
            domain="edge.example.com",
            use_ssl=True,
        )
        self.assertIn("PORT=8090", script)
        self.assertIn("sec_test_123456", script)
        self.assertIn("http://master.example.com:8080", script)
        self.assertIn("worker_server.py", script)
        self.assertIn("mistrelay-edge.service", script)
        self.assertIn("certbot", script)
        self.assertIn("80/tcp", script)
        self.assertIn("/etc/cron.d/certbot-mistrelay-edge", script)

        # 留空 domain 且传入 ip 时自动绑定 sslip.io 域名并开启 SSL
        script_auto = vps_deployer.build_remote_deploy_script(
            port=8090,
            auth_secret="sec_test_123456",
            master_url="http://master.example.com:8080",
            ip="16.162.23.244",
        )
        self.assertIn("edge.16-162-23-244.sslip.io", script_auto)
        self.assertIn("--ssl", script_auto)

    def test_render_install_sh(self):
        sh = vps_deployer.render_install_sh(
            master_url="http://master.example.com:8080",
            token="TOK_ABC_123",
            port=8090,
        )
        self.assertIn("http://master.example.com:8080", sh)
        self.assertIn("TOK_ABC_123", sh)
        self.assertIn("8090", sh)

    async def test_deploy_node_via_ssh_success_mock(self):
        node = db.create_edge_node(
            tenant_id=103,
            node_name="DeployTestNode",
            ip="203.0.113.88",
            port=8090,
            ssh_host="203.0.113.88",
            ssh_port=22,
            ssh_user="root",
            ssh_password="TestPassword123",
            status="offline",
        )

        async def mock_runner(host, port, user, pwd, script, log_cb, timeout_sec=180):
            log_cb(">>> [Step 1/5] 探测系统环境: Linux x86_64")
            log_cb(">>> [Step 2/5] 写入 worker_server.py")
            log_cb(">>> [Step 3/5] 安装 Python 依赖")
            log_cb(">>> [Step 4/5] 放行端口 8090")
            log_cb(">>> [Step 5/5] 启动 systemd 服务")
            return 0

        ok = await vps_deployer.deploy_node_via_ssh(
            node_id=node["id"],
            master_url="http://master.example.com",
            clear_password_on_success=True,
            ssh_runner=mock_runner,
        )
        self.assertTrue(ok)

        fresh_node = db.get_edge_node_by_id(node["id"], include_secrets=True)
        self.assertEqual(fresh_node["status"], "online")
        self.assertIn("节点部署成功并已上线", fresh_node["deploy_log"])
        # 密码已根据 clear_password_on_success 自动擦除
        self.assertFalse(fresh_node["has_ssh_password"])
        self.assertEqual(fresh_node["ssh_password_enc"], "")

    async def test_deploy_node_via_ssh_failure_mock(self):
        node = db.create_edge_node(
            tenant_id=103,
            node_name="FailNode",
            ip="203.0.113.99",
            port=8090,
            ssh_host="203.0.113.99",
            ssh_port=22,
            ssh_user="root",
            ssh_password="WrongPassword",
            status="offline",
        )

        async def mock_fail_runner(host, port, user, pwd, script, log_cb, timeout_sec=180):
            log_cb("Permission denied, please try again.")
            return 255

        ok = await vps_deployer.deploy_node_via_ssh(
            node_id=node["id"],
            master_url="http://master.example.com",
            ssh_runner=mock_fail_runner,
        )
        self.assertFalse(ok)

        fresh_node = db.get_edge_node_by_id(node["id"])
        self.assertEqual(fresh_node["status"], "error")
        self.assertIn("SSH 部署异常退出", fresh_node["deploy_log"])


if __name__ == "__main__":
    unittest.main()
