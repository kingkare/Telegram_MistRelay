import json
import tests  # noqa: F401
import asyncio
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

if "pyrogram" not in sys.modules:
    try:
        import pyrogram  # noqa: F401
    except ImportError:
        pyrogram_mod = types.ModuleType("pyrogram")

        class DummyClient:
            def __init__(self, *args, **kwargs):
                self.is_connected = False

            async def start(self):
                self.is_connected = True

            async def stop(self):
                self.is_connected = False

            async def get_me(self):
                m = MagicMock()
                m.id = 10001
                m.first_name = "TestAccount"
                m.username = "test_acc"
                m.phone_number = "16813086196"
                return m

        pyrogram_mod.__path__ = []
        pyrogram_mod.Client = DummyClient
        errors_mod = types.ModuleType("pyrogram.errors")
        errors_mod.FloodWait = type("FloodWait", (Exception,), {})
        errors_mod.RPCError = type("RPCError", (Exception,), {})
        pyrogram_mod.errors = errors_mod
        pyrogram_types = types.ModuleType("pyrogram.types")
        pyrogram_types.Message = SimpleNamespace
        pyrogram_types.Chat = SimpleNamespace
        pyrogram_types.User = SimpleNamespace
        pyrogram_mod.types = pyrogram_types
        sys.modules["pyrogram"] = pyrogram_mod
        sys.modules["pyrogram.types"] = pyrogram_types
        sys.modules["pyrogram.errors"] = errors_mod

import db
import botfather_creator
from session_adapter import pack_pyrogram_session


class TestMultiAccountPoolAndRelay(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tmp_dir.name, "test_pool.db")
        db.init_db()
        db.set_config("TELEGRAM_API_PROXY_URL", "https://proxy.example.com/api?region=US&num=1&time=10&format=1&type=txt")
        botfather_creator._PHONE_SESSION_CACHE.clear()
        botfather_creator._CACHE_FILES = [os.path.join(self.tmp_dir.name, "sessions.json")]
        botfather_creator._CREDENTIALS_CACHE_FILES = [os.path.join(self.tmp_dir.name, "credentials.json")]

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        self.tmp_dir.cleanup()

    def _make_fake_session(self, uid: int = 1001) -> str:
        return pack_pyrogram_session(
            dc_id=2,
            auth_key=os.urandom(256),
            api_id=2040,
            user_id=uid,
        )

    async def test_protocol_account_crud_and_sanitize(self):
        s1 = self._make_fake_session(1001)
        rec = db.upsert_protocol_account(
            phone="+16813086196",
            session_data=s1,
            session_type="telethon_string",
            code_url="https://miha.uk/tgapi/xxx/GetHTML",
            bot_count=5,
            status="active",
            remark="号商A",
        )
        self.assertEqual(rec["phone"], "+16813086196")
        self.assertEqual(rec["bot_count"], 5)

        sanitized = botfather_creator.sanitize_account_record(rec)
        self.assertNotIn("session_data", sanitized)
        self.assertEqual(sanitized["remaining_quota"], 15)
        self.assertTrue(sanitized["has_code_url"])
        self.assertIn("https://miha.uk/***", sanitized["masked_code_url"])

        # 更新持有机数到 20
        db.update_protocol_account(rec["id"], bot_count=20, status="limit_reached")
        updated = db.get_protocol_account_by_id(rec["id"])
        san2 = botfather_creator.sanitize_account_record(updated)
        self.assertEqual(san2["remaining_quota"], 0)
        self.assertEqual(san2["status"], "limit_reached")

        # 删除
        self.assertTrue(db.delete_protocol_account(rec["id"]))
        self.assertIsNone(db.get_protocol_account_by_id(rec["id"]))

    async def test_remove_protocol_account_thoroughly_cleans_cache_and_db(self):
        """验证移除协议号后彻底清理 DB、内存会话与磁盘 JSON 缓存，杜绝误复活"""
        s = self._make_fake_session(1804)
        phone = "+18048484620"
        rec = botfather_creator._save_cached_session(phone=phone, session_str=s, remark="待删除")
        self.assertIsNotNone(rec)
        self.assertIn(phone, botfather_creator._PHONE_SESSION_CACHE)

        # 验证移除协议号
        self.assertTrue(botfather_creator.remove_protocol_account(rec["id"]))
        self.assertIsNone(db.get_protocol_account_by_id(rec["id"]))
        self.assertNotIn(phone, botfather_creator._PHONE_SESSION_CACHE)

        # 检查磁盘 JSON 缓存文件
        for cpath in botfather_creator._CACHE_FILES:
            if os.path.exists(cpath):
                with open(cpath, "r", encoding="utf-8") as f:
                    import json
                    d = json.load(f)
                    self.assertNotIn(phone, d)

        # 调用 sync_cached_sessions_to_db 验证绝不会复活已删除的账号
        pool = botfather_creator.sync_cached_sessions_to_db()
        pool_phones = [a["phone"] for a in pool]
        self.assertNotIn(phone, pool_phones)
        self.assertIsNone(db.get_protocol_account_by_phone(phone))

    async def test_batch_import_protocol_accounts(self):
        s1 = self._make_fake_session(2001)
        s2 = self._make_fake_session(2002)

        with patch(
            "botfather_creator.login_via_phone_and_code_url",
            AsyncMock(return_value=s1),
        ):
            res = await botfather_creator.batch_import_protocol_accounts(
                lines=[
                    "+16813086196|https://miha.uk/tgapi/111/GetHTML",
                    s2,
                    "invalid_short_line",
                ],
                remark="批次测试",
            )

        self.assertEqual(res["imported_count"], 2)
        self.assertEqual(res["failed_count"], 1)
        accounts = db.list_protocol_accounts()
        self.assertEqual(len(accounts), 2)
        phones = [a["phone"] for a in accounts]
        self.assertIn("+16813086196", phones)
        self.assertIn("+uid_2002", phones)

    async def test_batch_import_concurrent_resilience(self):
        """测试多账号受控并发导入：多个账号同时解析接码，单账号异常不阻断其他有效账号入库"""
        s1 = self._make_fake_session(5001)
        s2 = self._make_fake_session(5002)

        async def fake_login(raw_str):
            if "fail" in raw_str:
                raise TimeoutError("等待接码平台验证码超时")
            await asyncio.sleep(0.05)
            return s1 if "5001" in raw_str else s2

        with patch("botfather_creator.login_via_phone_and_code_url", side_effect=fake_login):
            res = await botfather_creator.batch_import_protocol_accounts(
                lines=[
                    "+16813085001|https://miha.uk/tgapi/5001/GetHTML",
                    "+16813085002|https://miha.uk/tgapi/5002/GetHTML",
                    "+16813085003|https://miha.uk/tgapi/fail/GetHTML",
                ],
                remark="并发测试",
            )

        self.assertEqual(res["imported_count"], 2)
        self.assertEqual(res["failed_count"], 1)
        self.assertTrue(any("等待接码平台验证码超时" in e for e in res["errors"]))

    async def test_async_import_task_lifecycle(self):
        """测试后台异步协议号导入任务的生命周期：创建、轮询状态、进度上报与完成（彻底避免 Cloudflare 524 代理超时）"""
        s1 = self._make_fake_session(6001)

        async def fake_login(raw_str, on_progress=None):
            if on_progress:
                on_progress("Telegram 已向该号码签发验证码", "+16813086001", 0)
                on_progress("接码平台频率保护，冷却 5 秒", "+16813086001", 5)
            await asyncio.sleep(0.05)
            return s1

        with patch("botfather_creator.login_via_phone_and_code_url", side_effect=fake_login):
            task_id = botfather_creator.create_import_task(
                lines=["+16813086001|https://miha.uk/tgapi/6001/GetHTML"],
                remark="异步测试",
            )
            self.assertTrue(task_id.startswith("import_"))

            status1 = botfather_creator.get_import_task_status(task_id)
            self.assertIsNotNone(status1)
            self.assertIn(status1["status"], ("running", "completed"))

            # 等待异步任务执行完成
            for _ in range(30):
                await asyncio.sleep(0.05)
                cur = botfather_creator.get_import_task_status(task_id)
                if cur and cur["status"] == "completed":
                    break

            final_status = botfather_creator.get_import_task_status(task_id)
            self.assertEqual(final_status["status"], "completed")
            self.assertEqual(final_status["imported_count"], 1)
            self.assertEqual(final_status["failed_count"], 0)
            self.assertTrue(len(final_status["logs"]) >= 1)
            self.assertEqual(final_status["current_phone"], "+16813086001")

            # 验证数据库中账号已建立
            acc = db.get_protocol_account_by_phone("+16813086001")
            self.assertIsNotNone(acc)
            self.assertEqual(acc["phone"], "+16813086001")

    async def test_multi_account_relay_mode_auto_switch_on_20_limit(self):
        """测试多号接力模式：当账号 1 达到 20 上限时，自动无缝切换至账号 2 继续铸造，突破单号 20 限制"""
        s1 = self._make_fake_session(3001)
        s2 = self._make_fake_session(3002)
        acc1 = db.upsert_protocol_account(phone="+10000000001", session_data=s1, bot_count=19, status="active")
        acc2 = db.upsert_protocol_account(phone="+10000000002", session_data=s2, bot_count=0, status="active")

        manager = botfather_creator.BackgroundMintManager()

        class FakePyroClient:
            def __init__(self, *args, **kwargs):
                self.is_connected = False

            async def start(self):
                self.is_connected = True

            async def stop(self):
                self.is_connected = False

            async def get_me(self):
                m = MagicMock()
                m.id = 3001
                m.first_name = "RelayUser"
                return m

        # 模拟：都不复用存量，每次调用 create_single_bot：
        # 第 1 次成功（账号1的第20个），第 2 次抛出 20 bots 上限异常（触发切号），第 3、4 次在账号2上成功！
        call_seq = {"idx": 0}

        async def fake_create_single_bot(*args, **kwargs):
            call_seq["idx"] += 1
            c = call_seq["idx"]
            if c == 1:
                return ("relay_bot_1", "100001:AAH_TOKEN_1111111111111111111111111")
            if c == 2:
                raise ValueError("该 Telegram 账号在 @BotFather 创建的机器人数量已达上限（最多 20 个）")
            if c == 3:
                return ("relay_bot_2", "100002:AAH_TOKEN_2222222222222222222222222")
            return ("relay_bot_3", "100003:AAH_TOKEN_3333333333333333333333333")

        async def fake_hot_add(tok, persist=True):
            idx = int(tok.split(":")[0]) - 100000
            return {
                "index": idx,
                "username": f"relay_bot_{idx}",
                "mode": "no_join_resolved",
                "can_read": True,
                "can_write": False,
            }

        with patch("botfather_creator.Client", FakePyroClient), \
             patch("botfather_creator.create_single_bot", AsyncMock(return_value=("single_new_bot", "200003:BBH_TOKEN_CCCCCCCCCCCCCCCCCCCCCCCCC"))), \
             patch("botfather_creator.fetch_existing_bot_tokens", AsyncMock(return_value=[])), \
             patch("botfather_creator.create_single_bot", side_effect=fake_create_single_bot), \
             patch("WebStreamer.bot.clients.hot_add_bot_client", side_effect=fake_hot_add), \
             patch("asyncio.sleep", AsyncMock()):

            state = manager.start_task(
                mode="relay",
                account_ids=[acc1["id"], acc2["id"]],
                count=3,
                name_prefix="RelayTest",
                reuse_existing=False,
            )
            self.assertEqual(state["mode"], "relay")
            self.assertEqual(state["total_accounts"], 2)

            if manager._task:
                await manager._task

        final_status = manager.get_status()
        self.assertEqual(final_status["status"], "completed")
        self.assertEqual(final_status["created_count"], 3)
        self.assertEqual(len(final_status["account_history"]), 2)

        # 验证账号 1 在数据库中已被自动标记为 limit_reached
        updated_acc1 = db.get_protocol_account_by_id(acc1["id"])
        self.assertEqual(updated_acc1["status"], "limit_reached")
        self.assertEqual(updated_acc1["bot_count"], 20)

        # 验证日志中包含跨号接力事件
        relay_logs = [l["msg"] for l in final_status["logs"] if "跨号接力" in l["msg"]]
        self.assertTrue(len(relay_logs) >= 1)

    async def test_single_account_dedicated_mode(self):
        """测试单号精准独立铸造模式：仅使用指定单号且数量受控在 20 以内"""
        s1 = self._make_fake_session(4001)
        s2 = self._make_fake_session(4002)
        acc1 = db.upsert_protocol_account(phone="+10000000011", session_data=s1)
        acc2 = db.upsert_protocol_account(phone="+10000000022", session_data=s2)

        manager = botfather_creator.BackgroundMintManager()

        class FakePyroClient:
            def __init__(self, *args, **kwargs):
                self.is_connected = False

            async def start(self):
                self.is_connected = True

            async def stop(self):
                self.is_connected = False

            async def get_me(self):
                m = MagicMock()
                m.id = 4002
                m.first_name = "SingleAcc2"
                return m

        async def fake_fetch_existing(*args, **kwargs):
            return [
                {"username": "single_bot_a", "token": "200001:BBH_TOKEN_AAAAAAAAAAAAAAAAAAAAAAAAA"},
                {"username": "single_bot_b", "token": "200002:BBH_TOKEN_BBBBBBBBBBBBBBBBBBBBBBBBB"},
            ]

        async def fake_hot_add(tok, persist=True):
            return {"index": 1, "username": "single_bot", "mode": "no_join_resolved", "can_read": True, "can_write": False}

        with patch("botfather_creator.Client", FakePyroClient), \
             patch("botfather_creator.create_single_bot", AsyncMock(return_value=("single_new_bot", "200003:BBH_TOKEN_CCCCCCCCCCCCCCCCCCCCCCCCC"))), \
             patch("botfather_creator.fetch_existing_bot_tokens", side_effect=fake_fetch_existing), \
             patch("WebStreamer.bot.clients.hot_add_bot_client", side_effect=fake_hot_add), \
             patch("asyncio.sleep", AsyncMock()):

            state = manager.start_task(
                mode="single",
                single_account_id=acc2["id"],
                count=50,  # 单号模式自动限制上限为 20
                reuse_existing=True,
            )
            self.assertEqual(state["mode"], "single")
            self.assertEqual(state["target_count"], 20)
            self.assertEqual(state["total_accounts"], 1)
            self.assertEqual(state["current_account_phone"], "+10000000022")

            # 令目标为 2 以便立即完成
            manager.target_count = 2
            if manager._task:
                await manager._task

        final_status = manager.get_status()
        self.assertEqual(final_status["reused_count"], 2)
        self.assertEqual(len(final_status["account_history"]), 1)
        self.assertEqual(final_status["account_history"][0]["phone"], "+10000000022")


    async def test_inspect_session_metadata_and_telethon_conversion(self):
        """测试底层会话参数无阻塞解析与 Telethon Session String 转换"""
        from session_adapter import inspect_session_metadata
        s = self._make_fake_session(5001)
        meta = inspect_session_metadata(s)
        self.assertEqual(meta["dc_id"], 2)
        self.assertIn("DC2", meta["dc_name"])
        self.assertTrue(len(meta["auth_key_fingerprint"]) >= 8)
        self.assertTrue(meta["telethon_session_string"].startswith("1"))
        self.assertTrue(len(meta["telethon_session_string"]) > 280)

        # 验证往返互转一致性
        meta_roundtrip = inspect_session_metadata(meta["telethon_session_string"])
        self.assertEqual(meta_roundtrip["dc_id"], 2)
        self.assertEqual(meta_roundtrip["auth_key_fingerprint"], meta["auth_key_fingerprint"])

    async def test_get_protocol_account_detail(self):
        """测试获取协议号详情透视接口（含双端 Session 凭证）"""
        s = self._make_fake_session(6001)
        rec = db.upsert_protocol_account(
            phone="+16813087777",
            session_data=s,
            code_url="https://miha.uk/tgapi/xxx",
            remark="测试号777",
        )
        detail = await botfather_creator.get_protocol_account_detail(rec["id"], refresh_online=False)
        self.assertEqual(detail["account"]["phone"], "+16813087777")
        self.assertEqual(detail["metadata"]["dc_id"], 2)
        self.assertEqual(detail["metadata"]["code_url"], "https://miha.uk/tgapi/xxx")
        self.assertTrue(detail["sessions"]["telethon_session_string"].startswith("1"))
        self.assertEqual(detail["sessions"]["pyrogram_session_string"], s)

    async def test_keepalive_protocol_account_and_all(self):
        """测试协议号主动保活握手与全池保活巡检"""
        s1 = self._make_fake_session(7001)
        s2 = self._make_fake_session(7002)
        acc1 = db.upsert_protocol_account(phone="+10000000088", session_data=s1)
        acc2 = db.upsert_protocol_account(phone="+10000000099", session_data=s2)

        class FakeKeepaliveClient:
            def __init__(self, *args, **kwargs):
                self.is_connected = False
                self.storage = MagicMock()
                self.storage.dc_id = AsyncMock(return_value=2)

            async def start(self):
                self.is_connected = True

            async def stop(self):
                self.is_connected = False

            async def get_me(self):
                m = MagicMock()
                m.id = 7001
                m.first_name = "KeepaliveTester"
                m.username = "keepalive_user"
                m.phone_number = "10000000088"
                return m

        with patch("botfather_creator.Client", FakeKeepaliveClient),              patch("asyncio.sleep", AsyncMock()):
            # 单号保活测试
            res = await botfather_creator.keepalive_protocol_account(acc1["id"], check_bots=False)
            self.assertTrue(res["success"])
            self.assertEqual(res["phone"], "+10000000088")
            self.assertTrue(res["ping_ms"] >= 0)

            # 验证数据库字段已更新
            up1 = db.get_protocol_account_by_id(acc1["id"])
            self.assertIsNotNone(up1["last_keepalive_at"])
            self.assertEqual(up1["first_name"], "KeepaliveTester")
            self.assertEqual(up1["username"], "keepalive_user")
            self.assertEqual(up1["tg_user_id"], 7001)
            self.assertEqual(up1["dc_id"], 2)

            # 全量保活巡检测试
            summary = await botfather_creator.keepalive_all_protocol_accounts(account_ids=[acc1["id"], acc2["id"]])
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["success_count"], 2)
            self.assertEqual(summary["failed_count"], 0)

    async def test_keepalive_worker_lifecycle_and_config(self):
        """测试保活守护 Worker 的生命周期与配置读写"""
        worker = botfather_creator.get_keepalive_worker()
        status = worker.get_status()
        self.assertIn("enabled", status)
        self.assertIn("interval_hours", status)

        # 修改配置
        db.set_config_value("PROTOCOL_KEEPALIVE_INTERVAL_HOURS", 6)
        db.set_config_value("PROTOCOL_KEEPALIVE_ENABLED", True)
        status2 = worker.get_status()
        self.assertEqual(status2["interval_hours"], 6)
        self.assertTrue(status2["enabled"])

    async def test_import_multi_format_api_id_and_hash(self):
        """测试多格式导入自动解析 api_id 与 api_hash (文本行与 .json 档案)"""
        s1 = self._make_fake_session(8001)
        s2 = self._make_fake_session(8002)
        s3 = self._make_fake_session(8003)

        import json
        json_bytes = json.dumps({
            "phone": "+16813088003",
            "app_id": 28880003,
            "app_hash": "aabbccddeeff00112233445566778899",
            "first_name": "JsonUser",
            "username": "json_u8003",
            "session_string": s3,
        }).encode("utf-8")

        with patch("botfather_creator.login_via_phone_and_code_url", AsyncMock(return_value=s1)):
            res = await botfather_creator.batch_import_protocol_accounts(
                lines=[
                    "+16813088001|28880001|11223344556677889900aabbccddeeff|https://miha.uk/tgapi/8001/GetHTML|测试备注A",
                    f"28880002:fedcba9876543210fedcba9876543210:{s2}",
                ],
                files=[
                    ("+16813088003.json", json_bytes),
                ],
            )

        self.assertEqual(res["imported_count"], 3)
        acc1 = db.get_protocol_account_by_phone("+16813088001")
        self.assertIsNotNone(acc1)
        self.assertEqual(acc1["api_id"], 28880001)
        self.assertEqual(acc1["api_hash"], "11223344556677889900aabbccddeeff")
        self.assertEqual(acc1["remark"], "测试备注A")

        acc2 = db.get_protocol_account_by_phone("+uid_8002")
        self.assertIsNotNone(acc2)
        self.assertEqual(acc2["api_id"], 28880002)
        self.assertEqual(acc2["api_hash"], "fedcba9876543210fedcba9876543210")

        acc3 = db.get_protocol_account_by_phone("+16813088003")
        self.assertIsNotNone(acc3)
        self.assertEqual(acc3["api_id"], 28880003)
        self.assertEqual(acc3["api_hash"], "aabbccddeeff00112233445566778899")
        self.assertEqual(acc3["first_name"], "JsonUser")

    def test_detect_region_from_phone(self):
        """测试国际电话号码 E.164 最长前缀归属地区代码识别"""
        cases = [
            ("+16813086196", "US"),
            ("+14165550199", "CA"),
            ("+959757485895", "MM"),
            ("+447700900077", "GB"),
            ("+85291234567", "HK"),
            ("+6581234567", "SG"),
            ("+60123456789", "MY"),
            ("+8613800000000", "CN"),
            ("+819012345678", "JP"),
            ("+79161234567", "RU"),
            ("+77011234567", "KZ"),
            ("unknown", "US"),
        ]
        for phone, expected in cases:
            self.assertEqual(botfather_creator.detect_region_from_phone(phone), expected, f"Phone: {phone}")

    def test_build_regional_proxy_api_url_and_parse(self):
        """测试家宽代理 URL 地区代码替换与响应文本解析"""
        url1 = botfather_creator.build_regional_proxy_api_url("MM")
        self.assertIn("region=MM", url1)
        self.assertNotIn("region=US", url1)

        url2 = botfather_creator.build_regional_proxy_api_url("GB", "https://proxy.example.com/get?region={region}&num=1")
        self.assertEqual(url2, "https://proxy.example.com/get?region=GB&num=1")

        self.assertEqual(botfather_creator.parse_proxy_line("198.51.100.10:7150\r\n"), "http://198.51.100.10:7150")
        self.assertEqual(botfather_creator.parse_proxy_line("10.0.0.1:8080:user:pass"), "http://user:pass@10.0.0.1:8080")
        self.assertEqual(botfather_creator.parse_proxy_line('{"code": 200, "data": ["192.168.1.1:8888"]}'), "http://192.168.1.1:8888")

    async def test_fetch_api_credentials_from_my_telegram(self):
        """测试通过 my.telegram.org 自动提取或自动创建 App api_id 与 api_hash (含家宽代理注入)"""
        s1 = self._make_fake_session(9001)
        acc = db.upsert_protocol_account(phone="+16813089001", session_data=s1)

        class FakeMyTgClient:
            def __init__(self, *args, **kwargs):
                self.is_connected = False

            async def start(self):
                self.is_connected = True

            async def stop(self):
                self.is_connected = False

            async def get_me(self):
                m = MagicMock()
                m.id = 9001
                m.phone_number = "16813089001"
                return m

            async def get_chat_history(self, chat_id, limit=3):
                msg = MagicMock()
                msg.text = "Web login code:\nAbCdEfGh1234\nDo not give this code to anyone."
                yield msg

        class FakeResp:
            def __init__(self, text_val):
                self._text = text_val

            async def text(self):
                return self._text

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                pass

        class FakeHttpSession:
            def __init__(self, *args, **kwargs):
                self.apps_get_calls = 0
                self.proxies_used = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                pass

            def post(self, url, data=None, headers=None, proxy=None, **kwargs):
                if proxy:
                    self.proxies_used.append(proxy)
                if "send_password" in url:
                    return FakeResp('{"random_hash": "rhash_998877"}')
                if "auth/login" in url:
                    return FakeResp("true")
                if "apps/create" in url:
                    return FakeResp("")
                return FakeResp("")

            def get(self, url, headers=None, proxy=None, **kwargs):
                if proxy:
                    self.proxies_used.append(proxy)
                if "proxy" in url or "region=" in url:
                    return FakeResp("198.51.100.10:7150\n")
                self.apps_get_calls += 1
                if self.apps_get_calls == 1:
                    return FakeResp('<form action="/apps/create"><input type="hidden" name="hash" value="form_hash_xyz"/></form>')
                return FakeResp(
                    '<label>App api_id:</label><span><strong>29998888</strong></span>'
                    '<label>App api_hash:</label><span>1234567890abcdef1234567890abcdef</span>'
                )

        import aiohttp
        with patch("botfather_creator.Client", FakeMyTgClient), \
             patch.object(aiohttp, "ClientSession", FakeHttpSession, create=True), \
             patch("asyncio.sleep", AsyncMock()):
            res = await botfather_creator.fetch_api_credentials_from_my_telegram(acc["id"])

        self.assertEqual(res["api_id"], 29998888)
        self.assertEqual(res["api_hash"], "1234567890abcdef1234567890abcdef")
        self.assertEqual(res["region"], "US")
        self.assertIn("198.51.100.10", res["proxy_used"])

        updated = db.get_protocol_account_by_id(acc["id"])
        self.assertEqual(updated["api_id"], 29998888)
        self.assertEqual(updated["api_hash"], "1234567890abcdef1234567890abcdef")

    async def test_fetch_api_credentials_myanmar_region_matching(self):
        """测试缅甸 (+95) 协议号自动调度 region=MM 家宽代理并提取凭证"""
        s_mm = self._make_fake_session(9095)
        acc_mm = db.upsert_protocol_account(phone="+959757485895", session_data=s_mm)

        requested_proxy_urls = []

        class FakeMyanmarClient:
            def __init__(self, *args, **kwargs):
                self.is_connected = False
            async def start(self): self.is_connected = True
            async def stop(self): self.is_connected = False
            async def get_me(self):
                m = MagicMock()
                m.id = 9095
                m.phone_number = "959757485895"
                return m
            async def get_chat_history(self, chat_id, limit=5):
                msg = MagicMock()
                msg.text = "Web login code: MmCode998877"
                yield msg

        class FakeResp:
            def __init__(self, text): self._t = text
            async def text(self): return self._t
            async def __aenter__(self): return self
            async def __aexit__(self, exc_type, exc, tb): pass

        class FakeMyanmarHttpSession:
            def __init__(self, *args, **kwargs):
                self.apps_get_calls = 0

            async def __aenter__(self): return self
            async def __aexit__(self, exc_type, exc, tb): pass

            def post(self, url, data=None, headers=None, proxy=None, **kwargs):
                if "send_password" in url:
                    return FakeResp('{"random_hash": "rhash_mm_123"}')
                if "auth/login" in url:
                    return FakeResp("true")
                return FakeResp("")

            def get(self, url, headers=None, proxy=None, **kwargs):
                if "proxy" in url or "region=" in url:
                    requested_proxy_urls.append(url)
                    return FakeResp("198.51.100.10:32043\n")
                return FakeResp(
                    '<label>App api_id:</label><span><strong>29999095</strong></span>'
                    '<label>App api_hash:</label><span>9595959595abcdef9595959595abcdef</span>'
                )

        import aiohttp
        with patch("botfather_creator.Client", FakeMyanmarClient), \
             patch.object(aiohttp, "ClientSession", FakeMyanmarHttpSession, create=True), \
             patch("asyncio.sleep", AsyncMock()):
            res = await botfather_creator.fetch_api_credentials_from_my_telegram(acc_mm["id"])

        self.assertEqual(res["region"], "MM")
        self.assertEqual(res["api_id"], 29999095)
        self.assertEqual(res["api_hash"], "9595959595abcdef9595959595abcdef")
        self.assertTrue(any("region=MM" in u for u in requested_proxy_urls), f"Requested URLs: {requested_proxy_urls}")

    async def test_fetch_api_credentials_retry_on_bad_proxy(self):
        """测试首个家宽代理节点异常时，引擎自动换拉第 2 个代理节点完成提取"""
        s_retry = self._make_fake_session(9099)
        acc_retry = db.upsert_protocol_account(phone="+16813089099", session_data=s_retry)

        proxy_call_count = 0

        class FakeClient:
            def __init__(self, *args, **kwargs): self.is_connected = False
            async def start(self): self.is_connected = True
            async def stop(self): self.is_connected = False
            async def get_me(self):
                m = MagicMock()
                m.id = 9099
                m.phone_number = "16813089099"
                return m
            async def get_chat_history(self, chat_id, limit=5):
                msg = MagicMock()
                msg.text = "Web login code: RetryCode123"
                yield msg

        class FakeResp:
            def __init__(self, text): self._t = text
            async def text(self): return self._t
            async def __aenter__(self): return self
            async def __aexit__(self, exc_type, exc, tb): pass

        class FakeRetryHttpSession:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, exc_type, exc, tb): pass

            def post(self, url, data=None, headers=None, proxy=None, **kwargs):
                if "7150" in str(proxy):
                    raise TimeoutError("家宽代理连接超时")
                if "send_password" in url:
                    return FakeResp('{"random_hash": "rhash_retry"}')
                if "auth/login" in url:
                    return FakeResp("true")
                return FakeResp("")

            def get(self, url, headers=None, proxy=None, **kwargs):
                nonlocal proxy_call_count
                if "proxy" in url or "region=" in url:
                    proxy_call_count += 1
                    if proxy_call_count == 1:
                        return FakeResp("198.51.100.10:7150\n")
                    return FakeResp("198.51.100.10:8888\n")
                return FakeResp(
                    '<label>App api_id:</label><span><strong>29999099</strong></span>'
                    '<label>App api_hash:</label><span>9999999999abcdef9999999999abcdef</span>'
                )

        import aiohttp
        with patch("botfather_creator.Client", FakeClient), \
             patch.object(aiohttp, "ClientSession", FakeRetryHttpSession, create=True), \
             patch("asyncio.sleep", AsyncMock()):
            res = await botfather_creator.fetch_api_credentials_from_my_telegram(acc_retry["id"])

        self.assertEqual(res["api_id"], 29999099)
        self.assertIn("8888", res["proxy_used"])
        self.assertGreaterEqual(proxy_call_count, 2)

    async def test_batch_fetch_api_credentials(self):
        """测试全池批量提取未配置专属凭证的协议号"""
        s_b1 = self._make_fake_session(9081)
        s_b2 = self._make_fake_session(9082)
        acc1 = db.upsert_protocol_account(phone="+16813089081", session_data=s_b1)
        acc2 = db.upsert_protocol_account(phone="+959757489082", session_data=s_b2)

        async def fake_fetch(acc_id, proxy_api_url=None):
            return {
                "api_id": 30000000 + acc_id,
                "api_hash": f"batchhash{acc_id:024d}",
                "region": "MM" if acc_id == acc2["id"] else "US",
                "proxy_used": "http://198.51.100.10:7150",
            }

        with patch("botfather_creator.fetch_api_credentials_from_my_telegram", side_effect=fake_fetch), \
             patch("asyncio.sleep", AsyncMock()):
            batch_res = await botfather_creator.batch_fetch_api_credentials(account_ids=[acc1["id"], acc2["id"]])

        self.assertEqual(batch_res["total"], 2)
        self.assertEqual(batch_res["succeeded"], 2)
        self.assertEqual(batch_res["failed"], 0)

    async def test_update_protocol_account_credentials_manual(self):
        """测试手动更新与校验协议号的 api_id 与 api_hash"""
        s1 = self._make_fake_session(9002)
        acc = db.upsert_protocol_account(phone="+16813089002", session_data=s1)

        detail = await botfather_creator.update_protocol_account_credentials(
            acc["id"],
            api_id=21112222,
            api_hash="ABCDEF1234567890ABCDEF1234567890",
            remark="手动录入凭证",
        )
        self.assertEqual(detail["metadata"]["api_id"], 21112222)
        self.assertEqual(detail["metadata"]["api_hash"], "abcdef1234567890abcdef1234567890")
        self.assertEqual(detail["account"]["remark"], "手动录入凭证")
        self.assertTrue(detail["account"]["has_api_hash"])

        with self.assertRaises(ValueError):
            await botfather_creator.update_protocol_account_credentials(
                acc["id"],
                api_id=21112222,
                api_hash="invalid_short_hash",
            )


    async def test_unconfigured_account_never_polluted_by_session_meta_api_id(self):
        """验证未配置专属凭证的协议号决不回退会话内置的 meta_api_id (如 2420373)，避免假数据污染与误解"""
        # 创建一个内置 api_id=2420373 的 Pyrogram 会话
        sess = pack_pyrogram_session(
            dc_id=1,
            auth_key=os.urandom(256),
            api_id=2420373,
            user_id=10086,
        )
        rec = db.upsert_protocol_account(phone="+16813087777", session_data=sess)
        self.assertIsNone(rec["api_id"])
        self.assertIsNone(rec["api_hash"])

        # 校验脱敏记录中 api_id 为 None，且 has_api_hash 为 False
        sanitized = botfather_creator.sanitize_account_record(rec)
        self.assertIsNone(sanitized["api_id"], "未提取账号脱敏 api_id 必须为 None")
        self.assertFalse(sanitized["has_api_hash"])
        self.assertEqual(sanitized["masked_api_hash"], "")

        # 校验详情中 metadata.api_id 为 None
        detail = await botfather_creator.get_protocol_account_detail(rec["id"])
        self.assertIsNone(detail["metadata"]["api_id"], "未提取账号详情 metadata.api_id 必须为 None")
        self.assertFalse(detail["metadata"]["has_api_hash"])

    async def test_credentials_dual_persistence_and_self_healing(self):
        """验证 SQLite 数据库与磁盘 JSON 凭证备份的双向持久化与自愈"""
        s1 = self._make_fake_session(9005)
        phone = "+16813089005"
        rec = db.upsert_protocol_account(phone=phone, session_data=s1)

        # 1. 更新凭证 -> 校验同时写入 DB 与磁盘 JSON
        detail = await botfather_creator.update_protocol_account_credentials(
            rec["id"],
            api_id=33078544,
            api_hash="65ef3f63d4f109c7290bea5e4f329be6",
            remark="双写测试",
        )
        self.assertEqual(detail["metadata"]["api_id"], 33078544)
        self.assertEqual(detail["metadata"]["api_hash"], "65ef3f63d4f109c7290bea5e4f329be6")

        # 验证磁盘缓存文件内容
        cached = botfather_creator._load_cached_credentials()
        self.assertIn(phone, cached)
        self.assertEqual(cached[phone]["api_id"], 33078544)
        self.assertEqual(cached[phone]["api_hash"], "65ef3f63d4f109c7290bea5e4f329be6")

        # 2. 模拟 SQLite 意外丢失 api_id 与 api_hash
        db.update_protocol_account(rec["id"], api_id=None, api_hash=None)
        wiped_row = db.get_protocol_account_by_id(rec["id"])
        self.assertIsNone(wiped_row["api_id"])
        self.assertIsNone(wiped_row["api_hash"])

        # 3. 执行 sync_cached_sessions_to_db -> 自动从磁盘凭证备份自愈回填 SQLite
        pool = botfather_creator.sync_cached_sessions_to_db()
        healed_item = next(p for p in pool if p["phone"] == phone)
        self.assertEqual(healed_item["api_id"], 33078544)
        self.assertTrue(healed_item["has_api_hash"])

        db_healed = db.get_protocol_account_by_id(rec["id"])
        self.assertEqual(db_healed["api_id"], 33078544)
        self.assertEqual(db_healed["api_hash"], "65ef3f63d4f109c7290bea5e4f329be6")

        # 4. 删除账号 -> 校验磁盘凭证备份中该账号被安全清理
        self.assertTrue(botfather_creator.remove_protocol_account(rec["id"]))
        cached_after = botfather_creator._load_cached_credentials()
        self.assertNotIn(phone, cached_after)

    async def test_fetch_api_retry_connector_freshness_and_proxy_rotation(self):
        """验证多轮重试时连接器独立创建（杜绝 Session is closed）与家宽代理节点自动轮换"""
        import aiohttp
        # 1. 验证 parse_proxy_lines 解析多行代理
        multi_text = "198.51.100.10:7150\n198.51.100.10:7151\n198.51.100.10:7152"
        lines = botfather_creator.parse_proxy_lines(multi_text)
        self.assertEqual(len(lines), 3)

        # 2. 模拟 fetch_residential_proxy_for_region 在重试时轮换节点
        with patch.object(aiohttp, "ClientSession", create=True) as mock_sess_cls:
            mock_sess = MagicMock()
            mock_resp = AsyncMock()
            mock_resp.text = AsyncMock(return_value=multi_text)
            mock_sess.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp), __aexit__=AsyncMock()))
            mock_sess_cls.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
            mock_sess_cls.return_value.__aexit__ = AsyncMock()

            test_proxy_url = "https://proxy.example.com/api?region=US&num=1"
            p0 = await botfather_creator.fetch_residential_proxy_for_region("US", proxy_api_url=test_proxy_url, attempt_index=0)
            p1 = await botfather_creator.fetch_residential_proxy_for_region("US", proxy_api_url=test_proxy_url, attempt_index=1)
            p2 = await botfather_creator.fetch_residential_proxy_for_region("US", proxy_api_url=test_proxy_url, attempt_index=2)
            self.assertIn("7150", p0)
            self.assertIn("7151", p1)
            self.assertIn("7152", p2)

    async def test_fetch_api_detects_too_many_tries_and_fails_fast(self):
        """验证当 my.telegram.org 返回 Sorry, too many tries 时立即识别为频控并快速报错，杜绝挂等 777000"""
        import aiohttp
        s = self._make_fake_session(9098)
        acc = db.upsert_protocol_account(phone="+16813089098", session_data=s)

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.is_connected = False
            async def start(self):
                self.is_connected = True
            async def stop(self):
                self.is_connected = False
            async def get_me(self):
                m = MagicMock()
                m.id = 9098
                m.phone_number = "16813089098"
                return m
            async def get_chat_history(self, chat_id, limit=5):
                if False:
                    yield None

        class FakeTooManySession:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                pass
            def post(self, url, data=None, headers=None, proxy=None, **kwargs):
                class Resp:
                    async def text(self):
                        return "Sorry, too many tries. Please try again later."
                    async def __aenter__(self):
                        return self
                    async def __aexit__(self, exc_type, exc, tb):
                        pass
                return Resp()
            def get(self, url, headers=None, proxy=None, **kwargs):
                class Resp:
                    async def text(self):
                        return "198.51.100.10:7150\n"
                    async def __aenter__(self):
                        return self
                    async def __aexit__(self, exc_type, exc, tb):
                        pass
                return Resp()

        with patch("botfather_creator.Client", FakeClient),              patch.object(aiohttp, "ClientSession", FakeTooManySession, create=True),              patch("asyncio.sleep", AsyncMock()):
            with self.assertRaises(RuntimeError) as cm:
                await botfather_creator.fetch_api_credentials_from_my_telegram(
                    acc["id"],
                    proxy_api_url="https://proxy.example.com/api?region=US&num=1",
                )
            self.assertIn("频控限制", str(cm.exception))
            self.assertIn("Sorry, too many tries", str(cm.exception))


    async def test_sanitize_account_record_with_tenant_and_cluster_aggregates(self):
        """验证 sanitize_account_record 正确聚合租户专属频道、租户用户名与集群在线节点数"""
        s1 = self._make_fake_session(1001)
        acc = db.upsert_protocol_account(
            phone="+16813089999",
            session_data=s1,
            bot_count=3,
            status="limit_reached",
        )
        db.update_protocol_account(acc["id"], bot_usernames='["my_node_1_bot", "my_node_2_bot"]')

        u1 = db.create_tenant_user(
            username="tenant_alice",
            password_hash="hash_alice",
            role="user",
            bin_channel_id=-1001122334455,
            creator_account_id=acc["id"],
        )

        class MockClient:
            def __init__(self, username):
                self.username = username

        import WebStreamer.bot as bot_mod
        orig_clients = getattr(bot_mod, "multi_clients", {})
        try:
            bot_mod.multi_clients = {
                1: MockClient("my_node_1_bot"),
                2: MockClient("other_bot"),
            }
            sanitized = botfather_creator.sanitize_account_record(db.get_protocol_account_by_id(acc["id"]))
            self.assertEqual(sanitized["created_channels_count"], 1)
            self.assertIn("tenant_alice", sanitized["tenant_usernames"])
            self.assertEqual(sanitized["max_channels"], 10)
            self.assertEqual(sanitized["cluster_active_bots_count"], 1)
            self.assertEqual(sanitized["bot_usernames"], ["my_node_1_bot", "my_node_2_bot"])
        finally:
            bot_mod.multi_clients = orig_clients

    def test_db_list_users_creator_status_limit_reached_healthy(self):
        """验证 db.list_users() 对 limit_reached 状态的建频母号判定为 healthy 而非误报 warning"""
        s1 = self._make_fake_session(1002)
        acc_full = db.upsert_protocol_account(
            phone="+16813089988",
            session_data=s1,
            bot_count=20,
            status="limit_reached",
        )
        acc_bad = db.upsert_protocol_account(
            phone="+16813089977",
            session_data=s1,
            bot_count=5,
            status="invalid",
        )

        u_healthy = db.create_tenant_user(
            username="tenant_bob",
            password_hash="hash_bob",
            role="user",
            bin_channel_id=-1009988776655,
            creator_account_id=acc_full["id"],
        )
        u_warn = db.create_tenant_user(
            username="tenant_carol",
            password_hash="hash_carol",
            role="user",
            bin_channel_id=-1009988776644,
            creator_account_id=acc_bad["id"],
        )

        users = db.list_users()
        user_map = {u["username"]: u for u in users}

        self.assertEqual(user_map["tenant_bob"]["creator_status"], "healthy")
        self.assertEqual(user_map["tenant_carol"]["creator_status"], "warning")


    async def test_telegram_botfather_accounts_sync_handler(self):
        """测试全池数据同步接口 POST /api/telegram/botfather/accounts/sync"""
        from aiohttp import web
        from WebStreamer.server.stream_routes import telegram_botfather_accounts_sync_handler

        s1 = self._make_fake_session(1003)
        acc = db.upsert_protocol_account(
            phone="+16813089966",
            session_data=s1,
            bot_count=1,
            status="active",
        )

        class FakeRequest:
            def __init__(self, data=None):
                self._data = data or {}
                self._dict = {"user": {"role": "admin"}}
            def get(self, k, default=None):
                return self._dict.get(k, default)
            async def json(self):
                return self._data

        with patch("botfather_creator.keepalive_all_protocol_accounts", AsyncMock(return_value={"total": 1, "success_count": 1, "failed_count": 0})) as mock_keep:
            resp = await telegram_botfather_accounts_sync_handler(FakeRequest({"check_bots": True}))
            self.assertEqual(resp.status, 200)
            data = resp.body if isinstance(resp.body, dict) else json.loads(resp.text or resp.body.decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertEqual(data["summary"]["success_count"], 1)
            self.assertTrue(len(data["data"]) >= 1)
            mock_keep.assert_called_once_with(account_ids=None, check_bots=True)

    async def test_get_protocol_account_detail_includes_tenant_channels(self):
        """测试获取协议号详情返回名下创建的全部租户专属频道明细"""
        from botfather_creator import get_protocol_account_detail

        s1 = self._make_fake_session(8881)
        acc = db.upsert_protocol_account(
            phone="+16813088881",
            session_data=s1,
            bot_count=3,
            status="active",
        )

        # 关联 2 个租户
        db.create_tenant_user(
            username="tenant_x1",
            password_hash="hash1",
            bin_channel_id=-100888111,
            bin_channel_username="mr_u8881_x1",
            creator_account_id=acc["id"],
            role="user",
        )
        db.create_tenant_user(
            username="tenant_x2",
            password_hash="hash2",
            bin_channel_id=-100888222,
            bin_channel_username="mr_u8881_x2",
            creator_account_id=acc["id"],
            role="user",
        )

        detail = await get_protocol_account_detail(acc["id"], refresh_online=False)
        self.assertIn("tenant_channels", detail)
        self.assertEqual(len(detail["tenant_channels"]), 2)
        unames = [tc["username"] for tc in detail["tenant_channels"]]
        self.assertIn("tenant_x1", unames)
        self.assertIn("tenant_x2", unames)
        self.assertEqual(detail["tenant_channels"][0]["bin_channel_id"], -100888111)
        self.assertEqual(detail["tenant_channels"][0]["bin_channel_username"], "mr_u8881_x1")
        self.assertEqual(detail["account"]["created_channels_count"], 2)

if __name__ == "__main__":
    unittest.main()
