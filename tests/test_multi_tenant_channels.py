import tests  # noqa: F401
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import db
import botfather_creator
from session_adapter import pack_pyrogram_session
from auth import create_token, hash_password


class TestMultiTenantChannels(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        if os.path.exists(self._tmp.name):
            os.unlink(self._tmp.name)

    def test_tg_register_code_lifecycle(self):
        rec = db.create_tg_register_code(
            code="886699",
            tg_user_id=55667788,
            tg_username="alice_tg",
            tg_first_name="Alice",
            detected_dc_id=5,
            expires_minutes=10,
        )
        self.assertEqual(rec["code"], "886699")
        self.assertEqual(rec["detected_dc_id"], 5)
        self.assertEqual(rec["used"], 0)

        # 第一次核销应成功
        consumed = db.verify_and_consume_tg_register_code("886699")
        self.assertIsNotNone(consumed)
        self.assertEqual(consumed["tg_user_id"], 55667788)

        # 第二次重复核销应返回 None
        consumed_again = db.verify_and_consume_tg_register_code("886699")
        self.assertIsNone(consumed_again)

        # 过期验证码核销应失败
        db.create_tg_register_code(
            code="112233",
            tg_user_id=99887766,
            tg_username="bob_tg",
            tg_first_name="Bob",
            detected_dc_id=1,
            expires_minutes=-5,
        )
        self.assertIsNone(db.verify_and_consume_tg_register_code("112233"))

    def test_detect_user_dc_id(self):
        # 优先使用用户对象的 dc_id
        u1 = SimpleNamespace(dc_id=1, language_code="zh-hans", photo=None)
        self.assertEqual(botfather_creator.detect_user_dc_id(u1), 1)

        # 无头像时根据 language_code 识别
        u_zh = SimpleNamespace(dc_id=None, language_code="zh-hans", photo=None)
        self.assertEqual(botfather_creator.detect_user_dc_id(u_zh), 5)

        u_en = SimpleNamespace(dc_id=None, language_code="en-US", photo=None)
        self.assertEqual(botfather_creator.detect_user_dc_id(u_en), 1)

        u_ru = SimpleNamespace(dc_id=None, language_code="ru", photo=None)
        self.assertEqual(botfather_creator.detect_user_dc_id(u_ru), 2)

    async def test_provision_user_storage_channel_same_dc_selection(self):
        # 构造 DC1 与 DC5 两个协议号
        sess_dc1 = pack_pyrogram_session(
            dc_id=1,
            api_id=2040,
            test_mode=False,
            auth_key=b"\x11" * 256,
            user_id=100001,
            is_bot=False,
        )
        sess_dc5 = pack_pyrogram_session(
            dc_id=5,
            api_id=2040,
            test_mode=False,
            auth_key=b"\x55" * 256,
            user_id=500005,
            is_bot=False,
        )
        acc1 = db.upsert_protocol_account(
            phone="+16810000001",
            session_data=sess_dc1,
            session_type="pyrogram_string",
            status="active",
        )
        acc5 = db.upsert_protocol_account(
            phone="+95970000005",
            session_data=sess_dc5,
            session_type="pyrogram_string",
            status="active",
        )

        mock_client = MagicMock()
        mock_client.start = AsyncMock()
        mock_client.stop = AsyncMock()
        mock_client.create_channel = AsyncMock(return_value=SimpleNamespace(id=-100888999000))
        mock_client.set_chat_username = AsyncMock(return_value=True)
        mock_client.promote_chat_member = AsyncMock(return_value=True)

        with patch.object(botfather_creator, "Client", return_value=mock_client):
            # 请求 target_dc_id=5，应自动命中 acc5 (DC5)
            res5 = await botfather_creator.provision_user_storage_channel(
                username="alice_dc5",
                target_dc_id=5,
                tg_user_id=778899,
            )
            self.assertEqual(res5["dc_id"], 5)
            self.assertEqual(res5["creator_account_id"], acc5["id"])
            self.assertEqual(res5["bin_channel_id"], -100888999000)
            self.assertTrue(res5["bin_channel_username"].startswith("mr_u"))
            mock_client.create_channel.assert_awaited()
            mock_client.set_chat_username.assert_awaited()

            # 请求 target_dc_id=1，应自动命中 acc1 (DC1)
            res1 = await botfather_creator.provision_user_storage_channel(
                username="bob_dc1",
                target_dc_id=1,
                tg_user_id=112233,
            )
            self.assertEqual(res1["dc_id"], 1)
            self.assertEqual(res1["creator_account_id"], acc1["id"])

    def test_multi_tenant_media_and_download_isolation(self):
        # 创建两个租户用户
        u_a = db.create_tenant_user(
            username="tenant_a",
            password_hash=hash_password("PasswordA_123456"),
            tg_user_id=1001,
            tg_username="t_a",
            tg_first_name="Tenant A",
            dc_id=5,
            bin_channel_id=-100111111,
            bin_channel_username="mr_u1001_aaaa",
        )
        u_b = db.create_tenant_user(
            username="tenant_b",
            password_hash=hash_password("PasswordB_123456"),
            tg_user_id=1002,
            tg_username="t_b",
            tg_first_name="Tenant B",
            dc_id=1,
            bin_channel_id=-100222222,
            bin_channel_username="mr_u1002_bbbb",
        )

        self.assertEqual(db.get_channel_username_by_chat_id(-100111111), "mr_u1001_aaaa")
        self.assertEqual(db.get_channel_username_by_chat_id(-100222222), "mr_u1002_bbbb")

        # 两个租户在各自专属频道保存同一个 Telegram 文件 (相同的 raw file_unique_id)
        msg_a = SimpleNamespace(
            id=10,
            chat=SimpleNamespace(id=-100111111),
            from_user=SimpleNamespace(id=1001),
            sender_chat=None,
            date="2026-09-28T10:00:00Z",
            caption="Tenant A video",
            caption_entities=[],
            media_group_id=None,
            has_media_spoiler=False,
        )
        media_a = SimpleNamespace(
            file_unique_id="AgAD_SHARED_UNIQUE_ID",
            file_id="BAAD_FILE_A",
            file_name="movie_a.mp4",
            mime_type="video/mp4",
            file_size=1024 * 1024 * 50,
            duration=120,
            width=1920,
            height=1080,
            supports_streaming=True,
        )

        msg_b = SimpleNamespace(
            id=10,  # 甚至 message_id 也相同！
            chat=SimpleNamespace(id=-100222222),
            from_user=SimpleNamespace(id=1002),
            sender_chat=None,
            date="2026-09-28T10:05:00Z",
            caption="Tenant B video",
            caption_entities=[],
            media_group_id=None,
            has_media_spoiler=False,
        )
        media_b = SimpleNamespace(
            file_unique_id="AgAD_SHARED_UNIQUE_ID",
            file_id="BAAD_FILE_B",
            file_name="movie_b.mp4",
            mime_type="video/mp4",
            file_size=1024 * 1024 * 80,
            duration=240,
            width=1920,
            height=1080,
            supports_streaming=True,
        )

        uid_a = db.save_tg_media(msg_a, media_a)
        uid_b = db.save_tg_media(msg_b, media_b)
        self.assertNotEqual(uid_a, uid_b)

        # 验证各自网盘浏览完全隔离
        browse_a = db.browse_tg_media(chat_id=-100111111)
        self.assertEqual(browse_a["total"], 1)
        self.assertEqual(browse_a["items"][0]["file_name"], "movie_a.mp4")

        browse_b = db.browse_tg_media(chat_id=-100222222)
        self.assertEqual(browse_b["total"], 1)
        self.assertEqual(browse_b["items"][0]["file_name"], "movie_b.mp4")

        # 验证容量统计完全隔离
        stats_a = db.get_tg_media_stats(chat_id=-100111111)
        self.assertEqual(stats_a["total_count"], 1)
        self.assertEqual(stats_a["total_size"], 1024 * 1024 * 50)

        stats_b = db.get_tg_media_stats(chat_id=-100222222)
        self.assertEqual(stats_b["total_count"], 1)
        self.assertEqual(stats_b["total_size"], 1024 * 1024 * 80)

        # 验证租户 A 尝试跨频道删除租户 B 的文件会被拦截
        del_cross = db.delete_tg_media_records([uid_b], chat_id=-100111111)
        self.assertEqual(del_cross["deleted_media"], 0)
        self.assertEqual(db.browse_tg_media(chat_id=-100222222)["total"], 1)

        # 验证下载任务按 user_id 隔离
        db.create_download(uid_a, "gid_a_1", "http://example.com/a", user_id=u_a["id"], target_channel_id=-100111111)
        db.create_download(uid_b, "gid_b_1", "http://example.com/b", user_id=u_b["id"], target_channel_id=-100222222)

        dls_a = db.fetch_recent_downloads(100, user_id=u_a["id"])
        self.assertEqual(len(dls_a), 1)
        self.assertEqual(dls_a[0]["gid"], "gid_a_1")

        dls_b = db.fetch_recent_downloads(100, user_id=u_b["id"])
        self.assertEqual(len(dls_b), 1)
        self.assertEqual(dls_b[0]["gid"], "gid_b_1")

    async def test_rbac_middleware_blocks_non_admin_from_admin_routes(self):
        from WebStreamer.server import auth_middleware
        from aiohttp import web

        u = db.create_tenant_user(
            username="normal_user",
            password_hash=hash_password("NormalPass_123456"),
            tg_user_id=3003,
            tg_username="norm_u",
            tg_first_name="Normal",
            dc_id=5,
            bin_channel_id=-100333333,
            bin_channel_username="mr_u3003_cccc",
            role="user",
        )
        user_token = create_token(u["id"], u["username"], role="user")

        async def dummy_handler(req):
            return web.json_response({"success": True, "uid": req.get("user", {}).get("uid")})

        class FakeReq(dict):
            def __init__(self, path, headers=None, query=None):
                super().__init__()
                self.path = path
                self.headers = headers or {}
                self.query = query or {}

        # 普通用户访问 /api/telegram/browse 应放行 (200)
        req_allowed = FakeReq(
            "/api/telegram/browse",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp_allowed = await auth_middleware(req_allowed, dummy_handler)
        self.assertEqual(resp_allowed.status, 200)

        # 普通用户访问 /api/telegram/botfather/accounts 应拦截 (403)
        for blocked_path in [
            "/api/telegram/botfather/accounts",
            "/api/telegram/bots/status",
            "/api/settings",
            "/api/cache/status",
            "/api/users",
            "/api/system/resources",
            "/api/monitor/trend",
            "/api/files/list",
            "/api/aria2/test",
            "/api/telegram/rebrand/preview",
            "/api/telegram/benchmark/stream-and-download",
            "/api/telegram/thumbnails/warmup",
        ]:
            req_blocked = FakeReq(
                blocked_path,
                headers={"Authorization": f"Bearer {user_token}"},
            )
            resp_blocked = await auth_middleware(req_blocked, dummy_handler)
            self.assertEqual(resp_blocked.status, 403, f"Path {blocked_path} should be 403 for role=user")


    def test_user_management_crud_and_aggregates(self):
        admin_u = db.create_tenant_user(
            username="admin_test",
            password_hash=hash_password("AdminPass123"),
            tg_user_id=10001,
            role="admin",
        )
        tenant_u = db.create_tenant_user(
            username="tenant_bob",
            password_hash=hash_password("BobPass123"),
            tg_user_id=20002,
            dc_id=1,
            bin_channel_id=-100998877,
            bin_channel_username="mr_u20002_bob",
            role="user",
        )

        msg_bob = SimpleNamespace(
            id=501,
            chat=SimpleNamespace(id=-100998877),
            from_user=SimpleNamespace(id=20002),
            sender_chat=None,
            date="2026-09-28T00:00:00Z",
            caption="Bob video",
            caption_entities=[],
            media_group_id=None,
            has_media_spoiler=False,
        )
        media_bob = SimpleNamespace(
            file_unique_id="bob_file_1",
            file_id="fid_bob_1",
            file_name="bob_video.mp4",
            file_size=1048576,
            mime_type="video/mp4",
            duration=60,
            width=1280,
            height=720,
            supports_streaming=True,
        )
        uid_bob = db.save_tg_media(msg_bob, media_bob)
        db.create_download(
            file_unique_id=uid_bob,
            gid="dl_bob_1",
            source_url="https://example.com/bob_dl.zip",
            user_id=tenant_u["id"],
            target_channel_id=-100998877,
        )

        all_users = db.list_users()
        self.assertEqual(len(all_users), 2)
        bob_item = next(u for u in all_users if u["id"] == tenant_u["id"])
        self.assertEqual(bob_item["media_count"], 1)
        self.assertEqual(bob_item["total_size"], 1048576)
        self.assertEqual(bob_item["video_count"], 1)
        self.assertEqual(bob_item["download_count"], 1)

        # 测试更新
        updated = db.update_user_record(tenant_u["id"], tg_username="bob_tg", dc_id=2)
        self.assertEqual(updated["tg_username"], "bob_tg")
        self.assertEqual(updated["dc_id"], 2)

        # 测试注册码查询
        db.create_tg_register_code("123456", 20002, "bob_tg", "Bob", 2, 10)
        codes = db.list_tg_register_codes(limit=10)
        self.assertTrue(any(c["code"] == "123456" for c in codes))

        # 测试删除唯一管理员防护
        with self.assertRaises(ValueError):
            db.delete_user_record(admin_u["id"])

        # 测试正常删除租户
        del_res = db.delete_user_record(tenant_u["id"], delete_media_records=True)
        self.assertEqual(del_res["deleted_user_id"], tenant_u["id"])
        self.assertEqual(del_res["deleted_media"], 1)
        self.assertIsNone(db.get_user_by_id(tenant_u["id"]))

    async def test_admin_users_api_endpoints(self):
        from WebStreamer.server.stream_routes import (
            list_users_handler,
            admin_create_user_handler,
            admin_reset_user_password_handler,
            admin_update_user_handler,
            admin_delete_user_handler,
        )

        admin_u = db.create_tenant_user(
            username="super_admin",
            password_hash=hash_password("SuperSecret123"),
            role="admin",
        )

        class MockRequest(dict):
            def __init__(self, json_data=None, match_info=None, query=None, user=None):
                super().__init__()
                self._json_data = json_data or {}
                self.match_info = match_info or {}
                self.query = query or {}
                self.can_read_body = bool(json_data)
                self["user"] = user or {"uid": admin_u["id"], "username": admin_u["username"], "role": "admin"}

            async def json(self):
                return self._json_data

        # 1. 模拟管理员手动创建租户 (自动建频)
        mock_chan_meta = {
            "bin_channel_id": -100445566,
            "bin_channel_username": "mr_u7788_test",
            "dc_id": 5,
            "creator_account_id": 1,
        }
        with patch("botfather_creator.provision_user_storage_channel", AsyncMock(return_value=mock_chan_meta)):
            req_create = MockRequest(json_data={
                "username": "charlie_tenant",
                "password": "auto",
                "role": "user",
                "target_dc_id": 5,
                "auto_provision_channel": True,
            })
            resp = await admin_create_user_handler(req_create)
            self.assertEqual(resp.status, 200)
            created_u = resp.body["user"]
            self.assertEqual(created_u["username"], "charlie_tenant")
            self.assertEqual(created_u["bin_channel_id"], -100445566)
            self.assertIsNotNone(resp.body["generated_password"])

        # 2. 查询用户列表
        req_list = MockRequest()
        resp_list = await list_users_handler(req_list)
        self.assertEqual(resp_list.status, 200)
        self.assertEqual(resp_list.body["summary"]["total_users"], 2)
        self.assertEqual(resp_list.body["summary"]["dedicated_tenants"], 1)

        # 3. 重置密码
        req_reset = MockRequest(
            json_data={"new_password": "NewSecretPass123"},
            match_info={"id": str(created_u["id"])},
        )
        resp_reset = await admin_reset_user_password_handler(req_reset)
        self.assertEqual(resp_reset.status, 200)
        self.assertEqual(resp_reset.body["new_password"], "NewSecretPass123")

        # 4. 更新用户信息
        req_update = MockRequest(
            json_data={"tg_username": "charlie_tg", "dc_id": 1},
            match_info={"id": str(created_u["id"])},
        )
        resp_update = await admin_update_user_handler(req_update)
        self.assertEqual(resp_update.status, 200)
        self.assertEqual(resp_update.body["user"]["tg_username"], "charlie_tg")

        # 5. 删除管理员自身保护测试
        req_del_self = MockRequest(match_info={"id": str(admin_u["id"])})
        resp_del_self = await admin_delete_user_handler(req_del_self)
        self.assertEqual(resp_del_self.status, 400)

        # 6. 删除普通租户
        req_del_charlie = MockRequest(match_info={"id": str(created_u["id"])})
        resp_del_charlie = await admin_delete_user_handler(req_del_charlie)
        self.assertEqual(resp_del_charlie.status, 200)


    async def test_bot_modern_command_handlers(self):
        """验证主控 Bot 的 /start, /register, /help 现代化指令及 ReplyKeyboardRemove 自动清理"""
        from pyrogram.types import ReplyKeyboardRemove
        from WebStreamer.bot.plugins.stream_modules.media_processor import (
            user_register_command_handler,
            start_command_handler,
            help_command_handler,
        )

        # 1. 验证 app.py 已移除旧版 get_menu 及 /menu, /info 指令
        with open("/root/MistRelay-dev/app.py", "r", encoding="utf-8") as f:
            app_src = f.read()
        self.assertNotIn("def get_menu()", app_src)
        self.assertNotIn('BotCommand(command="menu"', app_src)
        self.assertNotIn('BotCommand(command="info"', app_src)
        self.assertIn('BotCommand(command="start"', app_src)
        self.assertIn('BotCommand(command="register"', app_src)
        self.assertIn('BotCommand(command="help"', app_src)

        # 2. 未注册用户触发 /start 与 /register
        mock_user = MagicMock()
        mock_user.id = 999888777
        mock_user.username = "new_visitor"
        mock_user.first_name = "Visitor"
        mock_user.dc_id = 5

        msg_start = MagicMock()
        msg_start.text = "/start"
        msg_start.from_user = mock_user
        msg_start.reply_text = AsyncMock()

        await start_command_handler(None, msg_start)
        msg_start.reply_text.assert_awaited_once()
        args, kwargs = msg_start.reply_text.call_args
        self.assertIn("/register", args[0])
        self.assertIsNotNone(kwargs.get("reply_markup"))

        msg_reg = MagicMock()
        msg_reg.text = "/register"
        msg_reg.from_user = mock_user
        msg_reg.reply_text = AsyncMock()

        await user_register_command_handler(None, msg_reg)
        msg_reg.reply_text.assert_awaited_once()
        r_args, r_kwargs = msg_reg.reply_text.call_args
        self.assertIn("您的 6 位验证码", r_args[0])
        self.assertIn("DC5", r_args[0])
        self.assertIsNotNone(r_kwargs.get("reply_markup"))

        # 3. 已注册租户触发 /start 与 /help
        db.create_tenant_user(
            username="tenant_vip",
            password_hash="hash",
            role="user",
            tg_user_id=999888777,
            dc_id=5,
            bin_channel_id=-100888999,
            bin_channel_username="mr_u_vip_chan",
        )
        msg_start_reg = MagicMock()
        msg_start_reg.text = "/start"
        msg_start_reg.from_user = mock_user
        msg_start_reg.reply_text = AsyncMock()

        await start_command_handler(None, msg_start_reg)
        msg_start_reg.reply_text.assert_awaited_once()
        s_args, s_kwargs = msg_start_reg.reply_text.call_args
        self.assertIn("MistRelay 云盘服务已就绪", s_args[0])
        self.assertIn("@mr_u_vip_chan", s_args[0])
        self.assertIsNotNone(s_kwargs.get("reply_markup"))

        msg_help = MagicMock()
        msg_help.text = "/help"
        msg_help.from_user = mock_user
        msg_help.reply_text = AsyncMock()

        await help_command_handler(None, msg_help)
        msg_help.reply_text.assert_awaited_once()
        h_args, h_kwargs = msg_help.reply_text.call_args
        self.assertIn("MistRelay 极速云盘使用指南", h_args[0])
        self.assertIn("受限/私密频道资源破除采集", h_args[0])
        self.assertIsNotNone(h_kwargs.get("reply_markup"))



    async def test_system_settings_upgrade_and_registration_switch(self):
        """验证系统设置升级：在线修改核心配置、needs_restart 标记、自助注册开关拦截与自定义频道前缀"""
        from WebStreamer.server.stream_routes import (
            get_config_handler,
            update_config_handler,
            auth_register_handler,
        )
        from WebStreamer.bot.plugins.stream_modules.media_processor import (
            user_register_command_handler,
        )

        class MockReq(dict):
            def __init__(self, json_data=None, query=None):
                super().__init__()
                self._json = json_data or {}
                self.query = query or {}
                self.headers = {"User-Agent": "TestAgent"}
                self.remote = "127.0.0.1"
                self["user"] = {"uid": 1, "sub": "admin", "role": "admin"}

            async def json(self):
                return self._json

        # 1. GET /api/config 返回 offline_only_keys 为空列表且包含新增默认项
        get_resp = await get_config_handler(MockReq(query={"category": "telegram"}))
        self.assertEqual(get_resp.status, 200)
        self.assertEqual(get_resp.body["offline_only_keys"], [])
        self.assertTrue(get_resp.body["data"]["ALLOW_USER_REGISTRATION"])
        self.assertEqual(get_resp.body["data"]["DEFAULT_TENANT_DC_ID"], 5)
        self.assertEqual(get_resp.body["data"]["TENANT_CHANNEL_PREFIX"], "mr_u")

        # 2. 在线更新热生效配置 (不触发 needs_restart)
        upd_hot = await update_config_handler(MockReq(json_data={
            "ALLOW_USER_REGISTRATION": False,
            "DEFAULT_TENANT_DC_ID": 1,
            "TENANT_CHANNEL_PREFIX": "vip_drive_",
            "PROTOCOL_KEEPALIVE_INTERVAL_HOURS": 6,
        }))
        self.assertEqual(upd_hot.status, 200)
        self.assertFalse(upd_hot.body["needs_restart"])
        self.assertFalse(db.get_config("ALLOW_USER_REGISTRATION", True))
        self.assertEqual(db.get_config("DEFAULT_TENANT_DC_ID", 5), 1)
        self.assertEqual(db.get_config("TENANT_CHANNEL_PREFIX", "mr_u"), "vip_drive_")

        # 3. 在线更新原受限核心配置 (触发 needs_restart=True 且成功落库)
        upd_core = await update_config_handler(MockReq(json_data={
            "PROXY_IP": "127.0.0.1",
            "PROXY_PORT": "7890",
            "BIN_CHANNEL": "-10099887766",
        }))
        self.assertEqual(upd_core.status, 200)
        self.assertTrue(upd_core.body["needs_restart"])
        self.assertEqual(db.get_config("PROXY_IP"), "127.0.0.1")
        self.assertEqual(db.get_config("BIN_CHANNEL"), "-10099887766")

        # 4. 当 ALLOW_USER_REGISTRATION=False 时，未注册用户私聊 /register 与调用注册 API 被拦截
        mock_visitor = MagicMock()
        mock_visitor.id = 555444333
        mock_visitor.username = "blocked_user"
        mock_visitor.first_name = "Blocked"
        msg_v = MagicMock()
        msg_v.text = "/register"
        msg_v.from_user = mock_visitor
        msg_v.reply_text = AsyncMock()

        await user_register_command_handler(None, msg_v)
        msg_v.reply_text.assert_awaited_once()
        v_args, _ = msg_v.reply_text.call_args
        self.assertIn("已关闭自助注册", v_args[0])

        reg_api_resp = await auth_register_handler(MockReq(json_data={
            "username": "blocked_user",
            "password": "Password123456",
            "code": "123456",
        }))
        self.assertEqual(reg_api_resp.status, 403)

        # 5. 已注册租户在关闭自助注册时仍可通过 /register 查看自身专属频道
        db.create_tenant_user(
            username="existing_member",
            password_hash="hash",
            role="user",
            tg_user_id=555444333,
            dc_id=1,
            bin_channel_id=-100777666,
            bin_channel_username="vip_drive_777666",
        )
        msg_member = MagicMock()
        msg_member.text = "/register"
        msg_member.from_user = mock_visitor
        msg_member.reply_text = AsyncMock()
        await user_register_command_handler(None, msg_member)
        m_args, _ = msg_member.reply_text.call_args
        self.assertIn("@vip_drive_777666", m_args[0])


    async def test_tenant_dashboard_and_task_api_isolation(self):
        """验证租户仪表板状态脱敏、趋势接口拦截、上传统计/列表隔离、跨租户任务控制拦截及按租户清空历史"""
        from WebStreamer.server.stream_routes import (
            api_status_handler,
            monitor_trend_handler,
            uploads_statistics_handler,
            uploads_api_handler,
            delete_all_downloads_handler,
            retry_download_handler,
            delete_download_handler,
            delete_download_record_handler,
            retry_upload_handler,
            delete_upload_handler,
        )

        u_a = db.create_tenant_user(
            username="dash_tenant_a",
            password_hash="hash_a",
            role="user",
            tg_user_id=7001,
            dc_id=5,
            bin_channel_id=-1007001,
            bin_channel_username="mr_u7001_aaaa",
        )
        u_b = db.create_tenant_user(
            username="dash_tenant_b",
            password_hash="hash_b",
            role="user",
            tg_user_id=7002,
            dc_id=1,
            bin_channel_id=-1007002,
            bin_channel_username="mr_u7002_bbbb",
        )

        msg_a = SimpleNamespace(
            id=101,
            chat=SimpleNamespace(id=-1007001),
            from_user=SimpleNamespace(id=7001),
            sender_chat=None,
            date="2026-09-28T10:00:00Z",
            caption="A",
            caption_entities=[],
            media_group_id=None,
            has_media_spoiler=False,
        )
        media_a = SimpleNamespace(
            file_unique_id="fuid_dash_a",
            file_id="fid_dash_a",
            file_name="video_a.mp4",
            mime_type="video/mp4",
            file_size=1024 * 1024 * 10,
            duration=60,
            width=1280,
            height=720,
            supports_streaming=True,
        )
        msg_b = SimpleNamespace(
            id=102,
            chat=SimpleNamespace(id=-1007002),
            from_user=SimpleNamespace(id=7002),
            sender_chat=None,
            date="2026-09-28T10:01:00Z",
            caption="B",
            caption_entities=[],
            media_group_id=None,
            has_media_spoiler=False,
        )
        media_b = SimpleNamespace(
            file_unique_id="fuid_dash_b",
            file_id="fid_dash_b",
            file_name="video_b.mp4",
            mime_type="video/mp4",
            file_size=1024 * 1024 * 20,
            duration=120,
            width=1280,
            height=720,
            supports_streaming=True,
        )

        fuid_a = db.save_tg_media(msg_a, media_a)
        fuid_b = db.save_tg_media(msg_b, media_b)

        dl_a_id = db.create_download(fuid_a, "gid_dash_a", "https://example.com/a.mp4", user_id=u_a["id"], target_channel_id=-1007001)
        dl_b_id = db.create_download(fuid_b, "gid_dash_b", "https://example.com/b.mp4", user_id=u_b["id"], target_channel_id=-1007002)

        up_a_id = db.create_upload(dl_a_id, "telegram")
        up_b_id = db.create_upload(dl_b_id, "telegram")
        db.mark_upload_completed(up_a_id, remote_path="tg://a")
        db.mark_upload_cleaned(up_a_id)
        db.mark_upload_failed(up_b_id, "network_error", "timeout", "TIMEOUT")

        class MockReq(dict):
            def __init__(self, user, query=None, match_info=None):
                super().__init__()
                self["user"] = user
                self.query = query or {}
                self.match_info = match_info or {}

        req_a = MockReq({"uid": u_a["id"], "sub": u_a["username"], "role": "user"})
        req_b = MockReq({"uid": u_b["id"], "sub": u_b["username"], "role": "user"})
        req_admin = MockReq({"uid": 1, "sub": "admin", "role": "admin"})

        # 1. 上传统计与上传列表隔离
        up_stats_a = await uploads_statistics_handler(req_a)
        self.assertEqual(up_stats_a.status, 200)
        self.assertEqual(up_stats_a.body["data"]["total"], 1)
        self.assertEqual(up_stats_a.body["data"]["cleaned"], 1)
        self.assertEqual(up_stats_a.body["data"]["failed"], 0)

        up_stats_b = await uploads_statistics_handler(req_b)
        self.assertEqual(up_stats_b.status, 200)
        self.assertEqual(up_stats_b.body["data"]["total"], 1)
        self.assertEqual(up_stats_b.body["data"]["cleaned"], 0)
        self.assertEqual(up_stats_b.body["data"]["failed"], 1)

        up_list_a = await uploads_api_handler(req_a)
        self.assertEqual(up_list_a.body["count"], 1)
        self.assertEqual(up_list_a.body["data"][0]["id"], up_a_id)

        # 2. 趋势接口对租户返回 403，对管理员返回 200
        trend_a = await monitor_trend_handler(req_a)
        self.assertEqual(trend_a.status, 403)
        trend_admin = await monitor_trend_handler(req_admin)
        self.assertEqual(trend_admin.status, 200)

        # 3. /api/status 对租户返回脱敏信息及自身专属频道，不包含集群内部字段
        status_a = await api_status_handler(req_a)
        self.assertEqual(status_a.status, 200)
        self.assertNotIn("bot_details", status_a.body)
        self.assertNotIn("loads", status_a.body)
        self.assertNotIn("bot_metrics", status_a.body)
        self.assertEqual(status_a.body["channel_info"]["channel_id"], -1007001)
        self.assertEqual(status_a.body["channel_info"]["public_handle"], "mr_u7001_aaaa")

        status_admin = await api_status_handler(req_admin)
        self.assertEqual(status_admin.status, 200)
        self.assertIn("bot_details", status_admin.body)
        self.assertIn("loads", status_admin.body)

        # 4. 租户 A 跨租户操作租户 B 的下载/上传任务应返回 403
        self.assertEqual(
            (await retry_download_handler(MockReq(req_a["user"], match_info={"gid": "gid_dash_b"}))).status,
            403,
        )
        self.assertEqual(
            (await delete_download_handler(MockReq(req_a["user"], match_info={"gid": "gid_dash_b"}))).status,
            403,
        )
        self.assertEqual(
            (await delete_download_record_handler(MockReq(req_a["user"], match_info={"download_id": str(dl_b_id)}))).status,
            403,
        )
        self.assertEqual(
            (await retry_upload_handler(MockReq(req_a["user"], match_info={"upload_id": str(up_b_id)}))).status,
            403,
        )
        self.assertEqual(
            (await delete_upload_handler(MockReq(req_a["user"], match_info={"upload_id": str(up_b_id)}))).status,
            403,
        )

        # 5. 租户 A 清空历史记录仅删除自身记录，不影响租户 B
        del_all_a = await delete_all_downloads_handler(req_a)
        self.assertEqual(del_all_a.status, 200)
        self.assertEqual(del_all_a.body["data"]["deleted_downloads"], 1)
        self.assertEqual(del_all_a.body["data"]["deleted_uploads"], 1)
        self.assertEqual(len(db.fetch_recent_downloads(10, user_id=u_a["id"])), 0)
        self.assertEqual(len(db.fetch_recent_downloads(10, user_id=u_b["id"])), 1)
        self.assertEqual(len(db.fetch_recent_uploads(10, user_id=u_b["id"])), 1)



    async def test_unbound_tenant_no_fallback_and_admin_only_endpoints(self):
        """验证未绑定专属频道的普通租户不会回退读写 Var.BIN_CHANNEL，且管理员专属接口拦截普通租户"""
        import json
        from WebStreamer.server.stream_routes import (
            get_request_bin_channel,
            telegram_browse_handler,
            telegram_usage_handler,
            telegram_delete_item_handler,
            telegram_delete_group_handler,
            telegram_batch_delete_handler,
            telegram_clear_all_handler,
            list_files_handler,
            download_file_handler,
            upload_file_handler,
            mkdir_handler,
            delete_file_handler,
            rebrand_preview_handler,
        )

        # 全局频道写入一条管理员媒体
        msg_global = SimpleNamespace(
            id=501,
            caption="Global Admin Video",
            media_group_id="grp_global",
            date=None,
            chat=SimpleNamespace(id=-100999999),
        )
        media_global = SimpleNamespace(
            file_unique_id="fuid_global_501",
            file_id="fid_global_501",
            file_name="global_secret.mp4",
            file_size=10485760,
            mime_type="video/mp4",
        )
        db.save_tg_media(msg_global, media_global)

        # 创建一个尚未绑定专属存储频道 (bin_channel_id=None) 的普通租户
        u_unbound = db.create_tenant_user(
            username="unbound_tenant",
            password_hash=hash_password("pass123456"),
            role="user",
            tg_user_id=880011,
            bin_channel_id=None,
        )

        class MockReq(dict):
            def __init__(self, user, query=None, match_info=None, json_body=None):
                super().__init__()
                self["user"] = user
                self.query = query or {}
                self.match_info = match_info or {}
                self._json_body = json_body or {}

            async def json(self):
                return self._json_body

        req_unbound = MockReq({"uid": u_unbound["id"], "sub": u_unbound["username"], "role": "user"})

        # 1. get_request_bin_channel 绝不能回退到 Var.BIN_CHANNEL
        self.assertIsNone(get_request_bin_channel(req_unbound))

        # 2. 浏览与用量统计返回空，不泄露全库/管理员频道媒体
        browse_res = await telegram_browse_handler(req_unbound)
        browse_body = json.loads(browse_res.body) if isinstance(browse_res.body, (bytes, bytearray)) else browse_res.body
        self.assertEqual(browse_res.status, 200)
        self.assertEqual(browse_body["items"], [])
        self.assertEqual(browse_body["total"], 0)

        usage_res = await telegram_usage_handler(req_unbound)
        usage_body = json.loads(usage_res.body) if isinstance(usage_res.body, (bytes, bytearray)) else usage_res.body
        self.assertEqual(usage_res.status, 200)
        self.assertEqual(usage_body["data"]["total_count"], 0)
        self.assertEqual(usage_body["data"]["total_size"], 0)

        # 3. 删除与清空接口对未绑定频道租户返回 403，严禁误删全库
        self.assertEqual(
            (await telegram_delete_item_handler(MockReq(req_unbound["user"], match_info={"message_id": "501"}))).status,
            403,
        )
        self.assertEqual(
            (await telegram_delete_group_handler(MockReq(req_unbound["user"], match_info={"media_group_id": "grp_global"}))).status,
            403,
        )
        self.assertEqual(
            (await telegram_batch_delete_handler(MockReq(req_unbound["user"], json_body={"message_ids": [501], "media_group_ids": []}))).status,
            403,
        )
        self.assertEqual(
            (await telegram_clear_all_handler(req_unbound)).status,
            403,
        )
        # 确认管理员全局媒体完好无损
        self.assertIsNotNone(db.get_tg_media_record_by_message_id(501))

        # 4. 本地文件管理 /api/files/* 与洗白预览对普通租户返回 403
        self.assertEqual((await list_files_handler(req_unbound)).status, 403)
        self.assertEqual((await download_file_handler(MockReq(req_unbound["user"], query={"path": "/a.txt"}))).status, 403)
        self.assertEqual((await upload_file_handler(req_unbound)).status, 403)
        self.assertEqual((await mkdir_handler(MockReq(req_unbound["user"], json_body={"path": "/test"}))).status, 403)
        self.assertEqual((await delete_file_handler(MockReq(req_unbound["user"], query={"path": "/a.txt"}))).status, 403)
        self.assertEqual((await rebrand_preview_handler(MockReq(req_unbound["user"], json_body={"caption": "hi"}))).status, 403)

    async def test_thumbnail_harvester_queue_and_ws_isolation(self):
        """验证缩略图跨频道隔离、采集器归属与脱敏、消息队列与 WebSocket 租户过滤"""
        import json
        from WebStreamer.server.stream_routes import (
            telegram_thumbnail_handler,
            telegram_thumbnails_status_handler,
            telegram_harvester_start_handler,
            telegram_harvester_status_handler,
            telegram_harvester_cancel_handler,
            queue_api_handler,
        )
        from private_channel_harvester import HarvesterTaskManager
        from WebStreamer.bot.plugins.stream_modules import queue_manager
        from WebStreamer.server.ws_manager import WebSocketManager

        u_a = db.create_tenant_user(
            username="sec_tenant_a",
            password_hash=hash_password("pass123456"),
            role="user",
            tg_user_id=910001,
            bin_channel_id=-1009101,
        )
        u_b = db.create_tenant_user(
            username="sec_tenant_b",
            password_hash=hash_password("pass123456"),
            role="user",
            tg_user_id=910002,
            bin_channel_id=-1009102,
        )

        # 存入租户 A 频道的消息 ID=777
        msg_a = SimpleNamespace(id=777, caption="A Photo", media_group_id=None, date=None, chat=SimpleNamespace(id=-1009101))
        med_a = SimpleNamespace(file_unique_id="fuid_sec_a_777", file_id="fid_sec_a_777", file_name="a.jpg", file_size=2048, mime_type="image/jpeg")
        db.save_tg_media(msg_a, med_a)

        class MockReq(dict):
            def __init__(self, user, query=None, match_info=None, json_body=None):
                super().__init__()
                self["user"] = user
                self.query = query or {}
                self.match_info = match_info or {}
                self._json_body = json_body or {}

            async def json(self):
                return self._json_body

        req_a = MockReq({"uid": u_a["id"], "sub": u_a["username"], "role": "user"})
        req_b = MockReq({"uid": u_b["id"], "sub": u_b["username"], "role": "user"})

        # 1. 租户 B 访问租户 A 的 message_id=777 缩略图应返回 404，指定 chat_id=-1009101 应返回 403
        thumb_b = await telegram_thumbnail_handler(MockReq(req_b["user"], match_info={"message_id": "777"}))
        self.assertEqual(thumb_b.status, 404)

        thumb_b_cross = await telegram_thumbnail_handler(
            MockReq(req_b["user"], match_info={"message_id": "777"}, query={"chat_id": "-1009101"})
        )
        self.assertEqual(thumb_b_cross.status, 403)

        # 缩略图状态接口对租户按各自信道统计并隐藏 current_message_id
        t_status_b = await telegram_thumbnails_status_handler(req_b)
        t_body_b = json.loads(t_status_b.body) if isinstance(t_status_b.body, (bytes, bytearray)) else t_status_b.body
        self.assertEqual(t_body_b["data"]["total"], 0)
        self.assertIsNone(t_body_b["data"]["current_message_id"])

        # 2. 采集器任务归属与手机号/日志隔离
        manager = HarvesterTaskManager.get_instance()
        manager._state = {
            "status": "running",
            "task_id": "harvest_test_a",
            "total_messages": 5,
            "current_index": 2,
            "success_count": 2,
            "failed_count": 0,
            "skipped_count": 0,
            "current_mode": "fast_copy",
            "current_file": "secret_a_video.mp4",
            "speed_text": "10 MB/s",
            "logs": ["[12:00:00] 正在采集租户A私密内容"],
            "results": [{"name": "secret_a_video.mp4", "full_link": "http://example/777"}],
            "account_phone": "+19998887777",
            "owner_uid": u_a["id"],
            "owner_role": "user",
            "error": None,
        }

        # 租户 A 查看自己的采集状态：能看到进度但看不到协议号手机号
        h_status_a = await telegram_harvester_status_handler(req_a)
        h_body_a = json.loads(h_status_a.body) if isinstance(h_status_a.body, (bytes, bytearray)) else h_status_a.body
        self.assertEqual(h_body_a["data"]["task_id"], "harvest_test_a")
        self.assertIsNone(h_body_a["data"]["account_phone"])

        # 租户 B 查看采集状态：被脱敏为空闲状态，看不到租户 A 的日志和结果直链
        h_status_b = await telegram_harvester_status_handler(req_b)
        h_body_b = json.loads(h_status_b.body) if isinstance(h_status_b.body, (bytes, bytearray)) else h_status_b.body
        self.assertEqual(h_body_b["data"]["status"], "idle")
        self.assertEqual(h_body_b["data"]["logs"], [])
        self.assertEqual(h_body_b["data"]["results"], [])

        # 租户 B 尝试取消租户 A 的任务：返回 403
        h_cancel_b = await telegram_harvester_cancel_handler(req_b)
        self.assertEqual(h_cancel_b.status, 403)

        # 恢复采集器状态为空闲
        manager._state["status"] = "idle"

        # 3. 队列状态 (/api/queue) 按租户过滤
        queue_manager._ensure_queue_initialized()
        queue_manager.queue_item_tracker.clear()
        queue_manager.queue_item_tracker[1] = {
            "message_id": 10,
            "chat_id": -1009101,
            "from_user_id": 910001,
            "title": "tenant_a_movie.mp4",
            "type": "single",
            "media_group_total": 0,
            "status": "waiting",
            "task_gids": [],
            "added_at": 1.0,
        }
        queue_manager.queue_item_tracker[2] = {
            "message_id": 20,
            "chat_id": -1009102,
            "from_user_id": 910002,
            "title": "tenant_b_private.mp4",
            "type": "single",
            "media_group_total": 0,
            "status": "waiting",
            "task_gids": [],
            "added_at": 2.0,
        }
        q_res_a = await queue_api_handler(req_a)
        q_body_a = json.loads(q_res_a.body) if isinstance(q_res_a.body, (bytes, bytearray)) else q_res_a.body
        self.assertEqual(q_body_a["waiting_count"], 1)
        self.assertEqual(q_body_a["waiting_items"][0]["title"], "tenant_a_movie.mp4")
        queue_manager.queue_item_tracker.clear()

        # 4. WebSocket 广播按租户连接过滤
        ws_mgr = WebSocketManager()
        sent_a, sent_b, sent_admin = [], [], []

        class FakeWS:
            def __init__(self, sink):
                self.closed = False
                self._sink = sink

            async def send_str(self, s):
                self._sink.append(json.loads(s))

        ws_a = FakeWS(sent_a)
        ws_b = FakeWS(sent_b)
        ws_adm = FakeWS(sent_admin)
        await ws_mgr.add_connection(ws_a, user_id=u_a["id"], role="user")
        await ws_mgr.add_connection(ws_b, user_id=u_b["id"], role="user")
        await ws_mgr.add_connection(ws_adm, user_id=1, role="admin")

        await ws_mgr.send_download_update({"gid": "g_a", "user_id": u_a["id"], "status": "downloading"})
        self.assertEqual(len(sent_a), 1)
        self.assertEqual(len(sent_b), 0)
        self.assertEqual(len(sent_admin), 1)

        # 全局无 user_id 任务更新仅推送给管理员
        await ws_mgr.send_download_update({"gid": "g_global", "user_id": None, "status": "completed"})
        self.assertEqual(len(sent_a), 1)
        self.assertEqual(len(sent_b), 0)
        self.assertEqual(len(sent_admin), 2)


    async def test_bin_channel_and_tenant_channel_isolation(self):
        """验证全局默认频道 (BIN_CHANNEL) 与租户专属频道在展示、上传与消息转存上的严格隔离"""
        import json
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        from WebStreamer.server.stream_routes import (
            telegram_browse_handler,
            telegram_usage_handler,
        )
        from WebStreamer.bot.plugins.stream_modules.media_processor import (
            get_target_bin_channel_for_message,
            ensure_peer_cached,
        )
        import sys
        for mod in ("websockets", "ffmpy3"):
            if mod not in sys.modules:
                from unittest.mock import MagicMock
                sys.modules[mod] = MagicMock()
        from aria2_client.upload_handler import UploadHandler
        from aria2_client.download_handler import DownloadHandler

        # 1. 准备全局默认频道媒体 vs 租户专属频道媒体
        chan_global = -100999000
        chan_tenant = -100111222

        u_admin = db.create_tenant_user(
            username="admin_sys",
            password_hash=hash_password("adminpass123"),
            role="admin",
            tg_user_id=10001,
            bin_channel_id=None,
        )
        u_tenant = db.create_tenant_user(
            username="tenant_bob",
            password_hash=hash_password("bobpass123"),
            role="user",
            tg_user_id=20002,
            bin_channel_id=chan_tenant,
            bin_channel_username="mr_u20002_test",
        )

        # 写入 2 条全局默认频道记录
        for mid in (101, 102):
            msg = SimpleNamespace(id=mid, caption="Global Video", media_group_id=None, date=None, chat=SimpleNamespace(id=chan_global))
            media = SimpleNamespace(file_unique_id=f"fuid_g_{mid}", file_id=f"fid_g_{mid}", file_name=f"global_{mid}.mp4", file_size=1000, mime_type="video/mp4")
            db.save_tg_media(msg, media)

        # 写入 3 条租户专属频道记录
        for mid in (201, 202, 203):
            msg = SimpleNamespace(id=mid, caption="Tenant Video", media_group_id=None, date=None, chat=SimpleNamespace(id=chan_tenant))
            media = SimpleNamespace(file_unique_id=f"fuid_t_{mid}", file_id=f"fid_t_{mid}", file_name=f"tenant_{mid}.mp4", file_size=2000, mime_type="video/mp4")
            db.save_tg_media(msg, media)

        class MockReq(dict):
            def __init__(self, user, query=None):
                super().__init__()
                self["user"] = user
                self.query = query or {}

        with patch("WebStreamer.vars.Var.BIN_CHANNEL", chan_global):
            # A. 管理员未带 chat_id 访问默认网盘：严格只返回全局默认频道的 2 条记录，绝不混入租户的 3 条记录
            req_admin_default = MockReq({"uid": u_admin["id"], "role": "admin"})
            res_browse = await telegram_browse_handler(req_admin_default)
            body_browse = json.loads(res_browse.body) if isinstance(res_browse.body, (bytes, bytearray)) else res_browse.body
            self.assertEqual(body_browse["total"], 2)
            ret_fnames = [it["file_name"] for it in body_browse["items"]]
            self.assertIn("global_101.mp4", ret_fnames)
            self.assertIn("global_102.mp4", ret_fnames)
            self.assertNotIn("tenant_201.mp4", ret_fnames)

            # 管理员默认网盘用量统计同样只统计全局频道 (2 * 1000 = 2000)
            res_usage = await telegram_usage_handler(req_admin_default)
            body_usage = json.loads(res_usage.body) if isinstance(res_usage.body, (bytes, bytearray)) else res_usage.body
            self.assertEqual(body_usage["data"]["total_count"], 2)
            self.assertEqual(body_usage["data"]["total_size"], 2000)

            # B. 管理员检视指定租户专属频道
            req_admin_inspect = MockReq({"uid": u_admin["id"], "role": "admin"}, query={"chat_id": str(chan_tenant)})
            res_inspect = await telegram_browse_handler(req_admin_inspect)
            body_inspect = json.loads(res_inspect.body) if isinstance(res_inspect.body, (bytes, bytearray)) else res_inspect.body
            self.assertEqual(body_inspect["total"], 3)
            ret_inspect_names = [it["file_name"] for it in body_inspect["items"]]
            self.assertIn("tenant_201.mp4", ret_inspect_names)
            self.assertNotIn("global_101.mp4", ret_inspect_names)

            # C. 管理员查看全库媒体总览 (chat_id=all)
            req_admin_all = MockReq({"uid": u_admin["id"], "role": "admin"}, query={"chat_id": "all"})
            res_all = await telegram_browse_handler(req_admin_all)
            body_all = json.loads(res_all.body) if isinstance(res_all.body, (bytes, bytearray)) else res_all.body
            self.assertEqual(body_all["total"], 5)

        # 2. Aria2 上传目标频道解析与防回退隔离
        u_handler = UploadHandler(bot=None, progress_cache={})
        # 租户任务上传目标必须是该租户专属频道
        dl_tenant_id = db.create_download("f_dl_t1", "gid_t1", "http://test.com/t.mp4", user_id=u_tenant["id"], target_channel_id=chan_tenant)
        self.assertEqual(u_handler._get_upload_chat_id(gid="gid_t1"), chan_tenant)

        # 未绑定专属频道的普通租户严禁上传至全局 BIN_CHANNEL
        u_unbound = db.create_tenant_user(username="unbound2", password_hash=hash_password("pw"), role="user", tg_user_id=30003, bin_channel_id=None)
        dl_unbound_id = db.create_download("f_dl_u1", "gid_u1", "http://test.com/u.mp4", user_id=u_unbound["id"], target_channel_id=None)
        with self.assertRaises(RuntimeError):
            u_handler._get_upload_chat_id(gid="gid_u1")

        # 3. Bot 私聊消息目标频道解析防回退
        msg_unbound = SimpleNamespace(from_user=SimpleNamespace(id=30003, first_name="UnboundUser"))
        self.assertIsNone(get_target_bin_channel_for_message(msg_unbound))

        msg_tenant = SimpleNamespace(from_user=SimpleNamespace(id=20002, first_name="TenantUser"))
        self.assertEqual(get_target_bin_channel_for_message(msg_tenant), chan_tenant)

        # 4. Pyrogram 专属频道 Peer 缓存预热
        mock_pyro_client = SimpleNamespace(
            resolve_peer=AsyncMock(side_effect=Exception("Peer id invalid")),
            get_chat=AsyncMock(return_value=SimpleNamespace(id=chan_tenant)),
        )
        await ensure_peer_cached(mock_pyro_client, chan_tenant)
        mock_pyro_client.get_chat.assert_awaited_with("@mr_u20002_test")

        # 5. Aria2 磁力派生任务 (followedBy / following) 租户属性自动继承
        dl_handler = DownloadHandler(bot=None, download_messages={}, completed_gids=set(), upload_handler=u_handler)
        parent_gid = "gid_parent_magnet"
        child_gid = "gid_child_data"
        db.create_download("f_parent", parent_gid, "magnet:?xt=urn:btih:...", user_id=u_tenant["id"], target_channel_id=chan_tenant)

        async def mock_tell_status(gid):
            if gid == child_gid:
                return {"gid": child_gid, "following": parent_gid, "files": []}
            return {}

        await dl_handler.on_download_start({"params": [{"gid": child_gid}]}, tell_status_func=mock_tell_status)
        child_did = db.get_download_id_by_gid(child_gid)
        self.assertIsNotNone(child_did)
        child_rec = db.get_download_by_id(child_did)
        self.assertIsNotNone(child_rec)
        self.assertEqual(child_rec["user_id"], u_tenant["id"])
        self.assertEqual(child_rec["target_channel_id"], chan_tenant)



    async def test_pyrogram_64bit_channel_id_patch_and_peer_resolution(self):
        import pyrogram_patch
        import pyrogram.utils as pyro_utils
        from WebStreamer.bot.plugins.stream_modules.media_processor import ensure_peer_cached

        # 验证 64 位 Telegram Channel ID 边界与解析
        chan_64bit = -1004056710317
        self.assertEqual(pyro_utils.get_peer_type(chan_64bit), "channel")
        self.assertEqual(pyro_utils.get_channel_id(chan_64bit), 4056710317)
        self.assertLess(chan_64bit, -1002147483647)

        # 验证对于 channel_ 开头的私密/未绑定 Handle 频道，ensure_peer_cached 直接通过 numeric chat_id 解析
        u_numeric = db.create_tenant_user(
            username="numeric_chan_user",
            password_hash=hash_password("pw123"),
            role="user",
            tg_user_id=8023262846,
            bin_channel_id=chan_64bit,
            bin_channel_username=f"channel_{abs(chan_64bit)}",
        )

        mock_pyro_client = SimpleNamespace(
            resolve_peer=AsyncMock(side_effect=Exception("Peer id invalid")),
            get_chat=AsyncMock(return_value=SimpleNamespace(id=chan_64bit)),
        )
        await ensure_peer_cached(mock_pyro_client, chan_64bit)
        # 应直接调用 numeric get_chat(chan_64bit)，绝不会去查不存在的 @channel_1004056710317
        mock_pyro_client.get_chat.assert_awaited_with(chan_64bit)

    async def test_provision_user_storage_channel_quota_failover(self):
        # 构造两个协议号，第一个已达上限，第二个正常
        sess1 = pack_pyrogram_session(
            dc_id=5,
            api_id=2040,
            test_mode=False,
            auth_key=b"\x11" * 256,
            user_id=500001,
            is_bot=False,
        )
        sess2 = pack_pyrogram_session(
            dc_id=5,
            api_id=2040,
            test_mode=False,
            auth_key=b"\x22" * 256,
            user_id=500002,
            is_bot=False,
        )
        acc1 = db.upsert_protocol_account(phone="+95911111111", session_data=sess1, session_type="pyrogram_string", status="active")
        acc2 = db.upsert_protocol_account(phone="+95922222222", session_data=sess2, session_type="pyrogram_string", status="active")

        # 模拟 acc1 抛出 CHANNELS_ADMIN_PUBLIC_TOO_MUCH，acc2 成功
        client_instances = []
        def mock_client_factory(*args, **kwargs):
            m_cli = MagicMock()
            m_cli.start = AsyncMock()
            m_cli.stop = AsyncMock()
            m_cli.create_channel = AsyncMock(return_value=SimpleNamespace(id=-1004099990001 if len(client_instances) == 0 else -1004099990002))
            m_cli.delete_channel = AsyncMock()
            m_cli.promote_chat_member = AsyncMock()
            if len(client_instances) == 0:
                m_cli.set_chat_username = AsyncMock(side_effect=Exception("Telegram says: [400 CHANNELS_ADMIN_PUBLIC_TOO_MUCH]"))
            else:
                m_cli.set_chat_username = AsyncMock(return_value=True)
            client_instances.append(m_cli)
            return m_cli

        with patch.object(botfather_creator, "Client", side_effect=mock_client_factory):
            res = await botfather_creator.provision_user_storage_channel(
                username="failover_user",
                target_dc_id=5,
                tg_user_id=999888,
            )
            # 验证自动切换到 acc2
            self.assertEqual(res["creator_account_id"], acc2["id"])
            self.assertEqual(res["bin_channel_id"], -1004099990002)
            self.assertTrue(res["bin_channel_username"].startswith("mr_u"))
            # 验证 acc1 上的空频道已被安全删除清理
            client_instances[0].delete_channel.assert_awaited()

if __name__ == "__main__":
    unittest.main()
