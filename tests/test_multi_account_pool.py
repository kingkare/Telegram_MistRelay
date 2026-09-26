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
        botfather_creator._PHONE_SESSION_CACHE.clear()
        botfather_creator._CACHE_FILES = [os.path.join(self.tmp_dir.name, "sessions.json")]

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


if __name__ == "__main__":
    unittest.main()
