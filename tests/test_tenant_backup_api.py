import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import db
import backup_manager
from WebStreamer.server.stream_routes import (
    admin_export_tenant_data_handler,
    admin_heal_orphans_handler,
    admin_provision_user_channel_handler,
    restore_system_backup_handler,
    tenant_backup_export_handler,
)


def _parse_resp(resp):
    if hasattr(resp, "body"):
        b = resp.body
        if isinstance(b, dict):
            return b
        if isinstance(b, (bytes, bytearray)):
            return json.loads(b.decode("utf-8"))
    if hasattr(resp, "text") and resp.text:
        return json.loads(resp.text)
    return {}


class TenantBackupApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        self.orig_env = os.environ.get("MISTRELAY_DB_PATH")
        os.environ["MISTRELAY_DB_PATH"] = self._tmp.name
        db.DB_PATH = self._tmp.name
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        if self.orig_env is None:
            os.environ.pop("MISTRELAY_DB_PATH", None)
        else:
            os.environ["MISTRELAY_DB_PATH"] = self.orig_env
        if os.path.exists(self._tmp.name):
            try:
                os.unlink(self._tmp.name)
            except OSError:
                pass

    async def test_admin_provision_channel_guardrail_saves_extra_channel(self):
        """验证为用户重新开通频道时，旧频道自动追加至 extra_channels 防孤儿"""
        u = db.create_tenant_user(
            username="user_guardrail",
            password_hash="pw",
            role="user",
            bin_channel_id=-1009999881,
            bin_channel_username="mr_old_chan",
        )

        req = MagicMock()
        req.match_info = {"id": str(u["id"])}
        req.can_read_body = True
        req.json = AsyncMock(return_value={"target_dc_id": 5})

        mock_chan_meta = {
            "dc_id": 5,
            "bin_channel_id": -1009999882,
            "bin_channel_username": "mr_new_chan",
            "creator_account_id": 1,
        }

        with patch("WebStreamer.server.stream_routes._require_admin_user", return_value=True), \
             patch("botfather_creator.provision_user_storage_channel", AsyncMock(return_value=mock_chan_meta)):
            resp = await admin_provision_user_channel_handler(req)
            data = _parse_resp(resp)
            self.assertTrue(data["success"])

        # 检查数据库：当前主频道变更新频道，旧频道自动加入 extra_channels
        updated_u = db.get_user_by_id(u["id"])
        self.assertEqual(updated_u["bin_channel_id"], -1009999882)
        self.assertIn(-1009999881, updated_u["extra_channels"])

    async def test_tenant_export_api_tenant_and_admin(self):
        """验证租户自主导出与管理员导出接口"""
        u = db.create_tenant_user(
            username="export_api_user",
            password_hash="pw",
            role="user",
            bin_channel_id=-1009991,
        )
        msg = SimpleNamespace(
            id=12,
            chat=SimpleNamespace(id=-1009991),
            video=SimpleNamespace(
                file_unique_id="fuid_exp_api_1",
                file_id="fid_exp_api_1",
                file_name="exp_api.mp4",
                mime_type="video/mp4",
                file_size=1234,
            ),
            date="2026-09-30T00:00:00",
        )
        db.save_tg_media(msg)

        # 租户自主导出
        req_tenant = MagicMock()
        req_tenant.get.return_value = {"uid": u["id"], "role": "user", "sub": "export_api_user"}
        resp_tenant = await tenant_backup_export_handler(req_tenant)
        self.assertEqual(resp_tenant.status, 200)
        tenant_json = _parse_resp(resp_tenant)
        self.assertEqual(tenant_json["tenant"]["username"], "export_api_user")
        self.assertEqual(tenant_json["stats"]["media_count"], 1)

        # 管理员导出
        req_admin = MagicMock()
        req_admin.match_info = {"id": str(u["id"])}
        with patch("WebStreamer.server.stream_routes._require_admin_user", return_value=True):
            resp_admin = await admin_export_tenant_data_handler(req_admin)
            self.assertEqual(resp_admin.status, 200)
            admin_json = _parse_resp(resp_admin)
            self.assertEqual(admin_json["tenant"]["username"], "export_api_user")

    async def test_admin_heal_orphans_api(self):
        """验证管理员一键自愈孤儿资产 API"""
        req_admin = MagicMock()
        with patch("WebStreamer.server.stream_routes._require_admin_user", return_value=True), \
             patch("db.heal_orphaned_tenant_media", return_value={"success": True, "total_files_restored": 5}):
            resp = await admin_heal_orphans_handler(req_admin)
            data = _parse_resp(resp)
            self.assertTrue(data["success"])
            self.assertEqual(data["data"]["total_files_restored"], 5)


if __name__ == "__main__":
    unittest.main()
