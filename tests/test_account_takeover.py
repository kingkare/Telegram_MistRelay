import tests  # noqa: F401
import os
import unittest
import tempfile
import datetime
from unittest.mock import patch, MagicMock, AsyncMock

import db
import botfather_creator
from session_adapter import pack_pyrogram_session


class TestAccountTakeover(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tmp_dir.name, "test_takeover.db")
        db.init_db()
        self.fake_session = pack_pyrogram_session(
            dc_id=2,
            auth_key=b"k" * 256,
            api_id=2040,
            user_id=888899,
        )

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        self.tmp_dir.cleanup()

    def test_db_columns_and_token_lookup(self):
        """测试 2FA 密码、hint 以及 local_otp_token 的持久化与查询"""
        acc = db.upsert_protocol_account(
            phone="+12025550199",
            session_data=self.fake_session,
            two_fa_password="MyStrongPassword123!",
            two_fa_hint="MyHint",
            has_two_fa=1,
            local_otp_token="test_token_abcdef123456",
        )
        self.assertEqual(acc["two_fa_password"], "MyStrongPassword123!")
        self.assertEqual(acc["two_fa_hint"], "MyHint")
        self.assertEqual(acc["has_two_fa"], 1)
        self.assertEqual(acc["local_otp_token"], "test_token_abcdef123456")

        found = db.get_protocol_account_by_otp_token("test_token_abcdef123456")
        self.assertIsNotNone(found)
        self.assertEqual(found["phone"], "+12025550199")

        # 测试 sanitize_account_record 脱敏
        sanitized = botfather_creator.sanitize_account_record(found)
        self.assertTrue(sanitized["has_two_fa"])
        self.assertEqual(sanitized["two_fa_hint"], "MyHint")
        self.assertEqual(sanitized["masked_two_fa"], "My****3!")
        self.assertEqual(sanitized["local_otp_token"], "test_token_abcdef123456")

    async def test_fetch_account_login_code(self):
        """测试从 777000 会话中截获 5 位纯数字登录代码及设备信息"""
        acc = db.upsert_protocol_account(
            phone="+12025550122",
            session_data=self.fake_session,
            two_fa_password="CloudPassword888",
        )

        fake_msg1 = MagicMock()
        fake_msg1.id = 101
        fake_msg1.text = (
            "Login code: 49281. Do not give this code to anyone, even if they say they're from Telegram!\n\n"
            "This code can be used to log in to your Telegram account.\n\n"
            "Device: Telegram Desktop\nIP: 198.51.100.88\nLocation: Singapore"
        )
        fake_msg1.date = datetime.datetime.now()

        fake_msg2 = MagicMock()
        fake_msg2.id = 100
        fake_msg2.text = "旧通知: 登录代码：12345"
        fake_msg2.date = datetime.datetime.now() - datetime.timedelta(hours=2)

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.is_connected = False
            async def start(self):
                self.is_connected = True
            async def stop(self):
                self.is_connected = False
            async def get_chat_history(self, chat_id, limit=10):
                yield fake_msg1
                yield fake_msg2

        with patch("botfather_creator.Client", FakeClient):
            res = await botfather_creator.fetch_account_login_code(acc["id"])
            self.assertEqual(res["latest_code"], "49281")
            self.assertTrue(res["is_recent"])
            self.assertEqual(res["device"], "Telegram Desktop")
            self.assertEqual(res["ip"], "198.51.100.88")
            self.assertEqual(res["location"], "Singapore")
            self.assertEqual(res["pass2fa"], "CloudPassword888")
            self.assertEqual(len(res["messages"]), 2)

    async def test_get_account_2fa_status(self):
        """测试查询 Telegram 官方 2FA 真实状态"""
        acc = db.upsert_protocol_account(
            phone="+12025550133",
            session_data=self.fake_session,
        )

        class FakePasswordResponse:
            has_password = True
            hint = "test hint from server"
            has_recovery = True
            login_email_pattern = "u***@gmail.com"
            pending_reset_date = 0

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass
            async def start(self):
                pass
            async def stop(self):
                pass
            async def invoke(self, query):
                return FakePasswordResponse()

        with patch("botfather_creator.Client", FakeClient):
            status = await botfather_creator.get_account_2fa_status(acc["id"])
            self.assertTrue(status["has_password"])
            self.assertEqual(status["hint"], "test hint from server")
            self.assertTrue(status["has_recovery"])
            self.assertEqual(status["login_email_pattern"], "u***@gmail.com")

            # 验证数据库自动同步 has_two_fa=1
            refreshed = db.get_protocol_account_by_id(acc["id"])
            self.assertEqual(refreshed["has_two_fa"], 1)
            self.assertEqual(refreshed["two_fa_hint"], "test hint from server")

    async def test_update_account_2fa_password_enable_and_change(self):
        """测试 2FA 密码未设置时开启、已设置时修改两条分支"""
        acc = db.upsert_protocol_account(
            phone="+12025550144",
            session_data=self.fake_session,
        )

        mock_enable = AsyncMock()
        mock_change = AsyncMock()

        # 分支 1: 未开启 2FA
        class FakeClientNoPass:
            def __init__(self, *args, **kwargs):
                self.enable_cloud_password = mock_enable
                self.change_cloud_password = mock_change
            async def start(self):
                pass
            async def stop(self):
                pass
            async def invoke(self, query):
                class Resp:
                    has_password = False
                return Resp()

        with patch("botfather_creator.Client", FakeClientNoPass):
            res1 = await botfather_creator.update_account_2fa_password(
                acc["id"],
                new_password="BrandNewPassword123!",
                hint="MyBrandNewHint",
            )
            self.assertTrue(res1["success"])
            self.assertEqual(res1["action"], "created")
            mock_enable.assert_awaited_once_with(password="BrandNewPassword123!", hint="MyBrandNewHint")

            acc_row = db.get_protocol_account_by_id(acc["id"])
            self.assertEqual(acc_row["two_fa_password"], "BrandNewPassword123!")
            self.assertEqual(acc_row["has_two_fa"], 1)

        # 分支 2: 已开启 2FA，修改密码
        class FakeClientHasPass:
            def __init__(self, *args, **kwargs):
                self.enable_cloud_password = mock_enable
                self.change_cloud_password = mock_change
            async def start(self):
                pass
            async def stop(self):
                pass
            async def invoke(self, query):
                class Resp:
                    has_password = True
                return Resp()

        with patch("botfather_creator.Client", FakeClientHasPass):
            res2 = await botfather_creator.update_account_2fa_password(
                acc["id"],
                new_password="SuperUpdatedPassword456!",
                current_password="BrandNewPassword123!",
                hint="UpdatedHint",
            )
            self.assertTrue(res2["success"])
            self.assertEqual(res2["action"], "updated")
            mock_change.assert_awaited_once_with(
                current_password="BrandNewPassword123!",
                new_password="SuperUpdatedPassword456!",
                new_hint="UpdatedHint",
            )

            acc_row2 = db.get_protocol_account_by_id(acc["id"])
            self.assertEqual(acc_row2["two_fa_password"], "SuperUpdatedPassword456!")
            self.assertEqual(acc_row2["two_fa_hint"], "UpdatedHint")

    async def test_terminate_account_other_sessions(self):
        """测试一键注销号商其他外部会话 (Terminate All Other Sessions)"""
        acc = db.upsert_protocol_account(
            phone="+12025550155",
            session_data=self.fake_session,
        )

        call_count = 0

        class FakeClientAuths:
            def __init__(self, *args, **kwargs):
                pass
            async def start(self):
                pass
            async def stop(self):
                pass
            async def invoke(self, query):
                nonlocal call_count
                call_count += 1
                q_name = query.__class__.__name__
                if q_name == "GetAuthorizations":
                    class RespAuths:
                        if call_count <= 1:
                            authorizations = [MagicMock(), MagicMock(), MagicMock()]
                        else:
                            authorizations = [MagicMock()]
                    return RespAuths()
                elif q_name == "ResetAuthorizations":
                    return True
                return MagicMock()

        with patch("botfather_creator.Client", FakeClientAuths):
            res = await botfather_creator.terminate_account_other_sessions(acc["id"])
            self.assertTrue(res["success"])
            self.assertEqual(res["terminated_count"], 2)
            self.assertEqual(res["remaining_sessions"], 1)

    async def test_cancel_password_reset(self):
        """测试一键撤销密码重置申请"""
        acc = db.upsert_protocol_account(
            phone="+12025550166",
            session_data=self.fake_session,
        )

        mock_decline = AsyncMock()

        class FakeClientDecline:
            def __init__(self, *args, **kwargs):
                pass
            async def start(self):
                pass
            async def stop(self):
                pass
            async def invoke(self, query):
                await mock_decline(query)
                return True

        with patch("botfather_creator.Client", FakeClientDecline):
            res = await botfather_creator.cancel_account_password_reset(acc["id"])
            self.assertTrue(res["success"])
            mock_decline.assert_awaited_once()

    def test_bind_local_otp_url(self):
        """测试生成自主接码链接并替换 code_url"""
        acc = db.upsert_protocol_account(
            phone="+12025550177",
            session_data=self.fake_session,
            code_url="https://seller.example.com/GetHTML",
        )
        res = botfather_creator.bind_local_otp_url(acc["id"], replace_code_url=True)
        self.assertIn("/api/telegram/botfather/otp/", res["otp_path"])
        self.assertEqual(res["code_url"], res["otp_path"])

        acc_updated = db.get_protocol_account_by_id(acc["id"])
        self.assertEqual(acc_updated["code_url"], res["otp_path"])
        self.assertTrue(bool(acc_updated["local_otp_token"]))

    async def test_otp_page_handler_json_and_html(self):
        """测试自主接码公开端点 (/api/telegram/botfather/otp/{token}) 的 JSON 与 HTML 渲染"""
        import WebStreamer.server.stream_routes as sr
        acc = db.upsert_protocol_account(
            phone="+12025550999",
            session_data=self.fake_session,
            two_fa_password="HtmlSecretPassword777",
            local_otp_token="my_special_token_999",
        )

        class DummyRequest:
            def __init__(self, token, is_json=False):
                self.match_info = {"token": token}
                self.headers = {"Accept": "application/json" if is_json else "text/html"}
                self.query = {"format": "json" if is_json else ""}

        fake_otp = {
            "account_id": acc["id"],
            "phone": "+12025550999",
            "latest_code": "88123",
            "code_time": "2026-09-27 18:00:00",
            "relative_time": "刚刚收到",
            "age_seconds": 12,
            "is_recent": True,
            "device": "Telegram Desktop",
            "ip": "1.2.3.4",
            "location": "Hong Kong",
            "raw_text": "Login code: 88123",
            "pass2fa": "HtmlSecretPassword777",
            "has_two_fa": True,
            "messages": [],
        }

        with patch("botfather_creator.fetch_account_login_code", AsyncMock(return_value=fake_otp)):
            # 1. 测试 JSON 格式返回
            req_json = DummyRequest("my_special_token_999", is_json=True)
            resp_json = await sr.telegram_botfather_otp_page_handler(req_json)
            self.assertEqual(resp_json.status, 200)
            self.assertIn("88123", resp_json.text)
            self.assertIn("HtmlSecretPassword777", resp_json.text)

            # 2. 测试 HTML 格式返回 (包含兼容号商接码页的隐藏输入框与玻璃质感卡片)
            req_html = DummyRequest("my_special_token_999", is_json=False)
            resp_html = await sr.telegram_botfather_otp_page_handler(req_html)
            self.assertEqual(resp_html.status, 200)
            self.assertIn('id="code" value="88123"', resp_html.text)
            self.assertIn('id="pass2fa" value="HtmlSecretPassword777"', resp_html.text)
            self.assertIn("88123", resp_html.text)
            self.assertIn("+12025550999", resp_html.text)


    async def test_auto_password_generation_and_candidate_fallback(self):
        """测试自动生成强密码与未提供 current_password 时自动匹配候选密码池"""
        pwd = botfather_creator.generate_strong_2fa_password()
        self.assertTrue(pwd.startswith("Mr-"))
        self.assertEqual(len(pwd), 15)

        acc = db.upsert_protocol_account(
            phone="+19413185447",
            session_data=self.fake_session,
        )

        class FakePasswordResp:
            has_password = True
            hint = ""

        class FakeClientFallback:
            def __init__(self, *args, **kwargs):
                pass
            async def start(self):
                pass
            async def stop(self):
                pass
            async def invoke(self, query):
                return FakePasswordResp()
            async def change_cloud_password(self, current_password, new_password, new_hint=""):
                if current_password != "z4422404":
                    raise Exception("400 PASSWORD_HASH_INVALID")
                return True

        with patch("botfather_creator.Client", FakeClientFallback):
            res = await botfather_creator.update_account_2fa_password(
                acc["id"],
                new_password="auto",
                current_password="wrong_manual_password",
                hint="AutoHint",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["matched_old_password"], "z4422404")
            self.assertTrue(res["new_password"].startswith("Mr-"))

            updated_acc = db.get_protocol_account_by_id(acc["id"])
            self.assertEqual(updated_acc["two_fa_password"], res["new_password"])

    async def test_takeover_protocol_account_full_pipeline(self):
        """测试单号一键全自动安全接管全链路 (改密 + 换绑本机接码 + 踢除外部设备)"""
        acc = db.upsert_protocol_account(
            phone="+19413185999",
            session_data=self.fake_session,
            code_url="https://miha.uk/tgapi/old-seller-link/GetHTML",
            two_fa_password="z4422404",
        )

        class FakeClientTakeover:
            def __init__(self, *args, **kwargs):
                self.auth_calls = 0
            async def start(self):
                pass
            async def stop(self):
                pass
            async def invoke(self, query):
                q_name = query.__class__.__name__
                if q_name == "GetPassword":
                    class R:
                        has_password = True
                    return R()
                if q_name == "GetAuthorizations":
                    self.auth_calls += 1
                    class RA:
                        authorizations = [MagicMock(), MagicMock()] if self.auth_calls == 1 else [MagicMock()]
                    return RA()
                if q_name == "ResetAuthorizations":
                    return True
                return MagicMock()
            async def change_cloud_password(self, current_password, new_password, new_hint=""):
                return True

        with patch("botfather_creator.Client", FakeClientTakeover):
            res = await botfather_creator.takeover_protocol_account(acc["id"], new_password="auto")
            self.assertTrue(res["success"])
            self.assertTrue(res["new_password"].startswith("Mr-"))
            self.assertIn("/api/telegram/botfather/otp/", res["code_url"])
            self.assertEqual(res["terminated_count"], 1)

            final_acc = db.get_protocol_account_by_id(acc["id"])
            self.assertEqual(final_acc["two_fa_password"], res["new_password"])
            self.assertEqual(final_acc["code_url"], res["code_url"])

    async def test_batch_takeover_skips_already_secured_accounts(self):
        """测试批量接管时精确识别并自动跳过已接管账号，仅统计和接管未接管账号"""
        # 1. 已接管账号：本机接码 + Mr- 高强 2FA
        acc_secured = db.upsert_protocol_account(
            phone="+19410001111",
            session_data=self.fake_session,
            code_url="/api/telegram/botfather/otp/token_secured_12345",
            two_fa_password="Mr-AlreadySecured",
            two_fa_hint="MistRelay",
            has_two_fa=1,
        )
        # 2. 待接管账号：号商外部接码 + 号商初始弱密码 8899
        acc_pending = db.upsert_protocol_account(
            phone="+9590002222",
            session_data=self.fake_session,
            code_url="https://miha.uk/tgapi/some-merchant/GetHTML",
            two_fa_password="8899",
            has_two_fa=1,
        )

        san_secured = botfather_creator.sanitize_account_record(acc_secured)
        san_pending = botfather_creator.sanitize_account_record(acc_pending)
        self.assertTrue(san_secured["is_taken_over"])
        self.assertTrue(san_secured["is_local_otp"])
        self.assertFalse(san_pending["is_taken_over"])
        self.assertFalse(san_pending["is_local_otp"])

        # 3. 运行全池一键接管 (only_unsecured=True)
        with patch("botfather_creator.takeover_protocol_account", AsyncMock(return_value={
            "success": True,
            "new_password": "Mr-NewPass123456",
            "terminated_count": 1,
            "restricted": False,
            "message": "ok",
        })) as mock_takeover:
            res = await botfather_creator.takeover_all_protocol_accounts(only_unsecured=True)
            self.assertTrue(res["success"])
            self.assertEqual(res["pool_total"], 2)
            self.assertEqual(res["total"], 1)
            self.assertEqual(res["skipped_count"], 1)
            self.assertEqual(res["success_count"], 1)
            mock_takeover.assert_awaited_once_with(acc_pending["id"])


if __name__ == "__main__":
    unittest.main()

