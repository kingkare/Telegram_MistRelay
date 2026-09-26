import tests  # noqa: F401
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault(
    "MISTRELAY_DB_PATH",
    tempfile.mktemp(prefix="mistrelay_hotplug_tests_", suffix=".db", dir="/tmp"),
)
os.environ.setdefault(
    "MISTRELAY_SESSION_DIR",
    tempfile.mkdtemp(prefix="mistrelay_hotplug_sessions_", dir="/tmp"),
)

if "pyrogram" not in sys.modules:
    try:
        import pyrogram  # noqa: F401
    except ImportError:
        pyrogram_mod = types.ModuleType("pyrogram")

        class DummyClient:
            def __init__(self, *args, **kwargs):
                self.is_connected = False
                self.username = "dummy_bot"

        pyrogram_mod.Client = DummyClient
        sys.modules["pyrogram"] = pyrogram_mod

import WebStreamer.bot as bot_mod
from WebStreamer.bot.clients import hot_add_bot_client, hot_remove_bot_client
from WebStreamer.vars import Var


class TestBotHotPlug(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot_mod.multi_clients.clear()
        bot_mod.work_loads.clear()
        bot_mod.channel_accessible_clients.clear()
        bot_mod.channel_write_clients.clear()
        bot_mod.bot_channel_modes.clear()
        bot_mod.bot_runtime.clear()
        Var.MULTI_BOT_TOKENS = []
        Var.MULTI_CLIENT = False
        Var.BOT_TOKEN = "111111111:AAAPrimaryBotToken1234567890abcdef"
        Var.BIN_CHANNEL = -1001998444696

        # Register mock client 0
        primary_mock = MagicMock()
        primary_mock.username = "primary_bot"
        primary_mock.is_connected = True
        bot_mod.multi_clients[0] = primary_mock
        bot_mod.work_loads[0] = 0
        bot_mod.channel_accessible_clients.add(0)
        bot_mod.channel_write_clients.add(0)

    def tearDown(self):
        bot_mod.multi_clients.clear()
        bot_mod.work_loads.clear()
        bot_mod.channel_accessible_clients.clear()
        bot_mod.channel_write_clients.clear()
        bot_mod.bot_channel_modes.clear()
        bot_mod.bot_runtime.clear()

    async def test_hot_add_invalid_token_rejected(self):
        with self.assertRaises(ValueError):
            await hot_add_bot_client("invalid-token", persist=False)

    async def test_hot_add_primary_token_rejected(self):
        with self.assertRaises(ValueError):
            await hot_add_bot_client(Var.BOT_TOKEN, persist=False)

    async def test_hot_add_and_remove_worker_lifecycle(self):
        token_1 = "222222222:BBBWorkerBotToken1234567890abcdef"

        mock_client = MagicMock()
        mock_client.start = AsyncMock()
        mock_client.stop = AsyncMock()
        mock_client.get_me = AsyncMock(return_value=MagicMock(username="worker_2_bot"))
        mock_client.is_connected = True

        with patch("WebStreamer.bot.clients.Client", return_value=mock_client), \
             patch("WebStreamer.bot.clients.probe_worker_channel_access", AsyncMock(return_value={
                 "mode": "no_join_resolved",
                 "can_read": True,
                 "can_write": False,
                 "username": "worker_2_bot",
                 "last_error": "",
             })), \
             patch("WebStreamer.bot.clients.client_health_check", AsyncMock()):

            # 1. Hot Add
            res = await hot_add_bot_client(token_1, persist=False)
            self.assertEqual(res["index"], 1)
            self.assertEqual(res["username"], "worker_2_bot")
            self.assertEqual(res["mode"], "no_join_resolved")
            self.assertTrue(res["can_read"])
            self.assertFalse(res["can_write"])
            self.assertFalse(res["already_exists"])

            # Verify registered into bot_mod structures
            self.assertIn(1, bot_mod.multi_clients)
            self.assertIn(1, bot_mod.channel_accessible_clients)
            self.assertEqual(bot_mod.work_loads[1], 0)
            self.assertTrue(Var.MULTI_CLIENT)
            self.assertIn(token_1, Var.MULTI_BOT_TOKENS)

            # Scheduler can select the new worker
            selected = bot_mod.select_stream_bot()
            self.assertIn(selected, [0, 1])

            # 2. Add same token again -> should return already_exists=True
            res_repeat = await hot_add_bot_client(token_1, persist=False)
            self.assertTrue(res_repeat["already_exists"])
            self.assertEqual(res_repeat["index"], 1)

            # 3. Cannot remove client 0
            with self.assertRaises(ValueError):
                await hot_remove_bot_client(0, persist=False)

            # 4. Hot remove worker 1
            rem_res = await hot_remove_bot_client(1, persist=False)
            self.assertEqual(rem_res["removed_index"], 1)
            self.assertEqual(rem_res["username"], "worker_2_bot")

            # Verify unregistered
            self.assertNotIn(1, bot_mod.multi_clients)
            self.assertNotIn(1, bot_mod.channel_accessible_clients)
            self.assertNotIn(1, bot_mod.work_loads)
            self.assertNotIn(token_1, Var.MULTI_BOT_TOKENS)
            self.assertFalse(Var.MULTI_CLIENT)
            mock_client.stop.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
