import tests  # noqa: F401
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault(
    "MISTRELAY_DB_PATH",
    tempfile.mktemp(prefix="mistrelay_multibot_tests_", suffix=".db", dir="/tmp"),
)
os.environ.setdefault(
    "MISTRELAY_SESSION_DIR",
    tempfile.mkdtemp(prefix="mistrelay_sessions_tests_", dir="/tmp"),
)

# Provide lightweight pyrogram mock if running outside container where pyrogram is not installed
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

from WebStreamer.bot.clients import (
    extract_channel_public_handle,
    probe_worker_channel_access,
)
import WebStreamer.bot as bot_mod


class MockChat:
    def __init__(self, username=None, linked_chat=None):
        self.username = username
        self.linked_chat = linked_chat


class TestMultiBotNoChannelBalancing(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot_mod.multi_clients.clear()
        bot_mod.work_loads.clear()
        bot_mod.channel_accessible_clients.clear()
        bot_mod.channel_write_clients.clear()
        bot_mod.bot_channel_modes.clear()
        bot_mod.channel_public_handle = None

    def tearDown(self):
        bot_mod.multi_clients.clear()
        bot_mod.work_loads.clear()
        bot_mod.channel_accessible_clients.clear()
        bot_mod.channel_write_clients.clear()
        bot_mod.bot_channel_modes.clear()
        bot_mod.channel_public_handle = None

    def test_extract_channel_public_handle(self):
        # 1. 频道本身带有公开用户名
        chat_with_username = MockChat(username="my_public_channel")
        self.assertEqual(extract_channel_public_handle(chat_with_username), "my_public_channel")
        self.assertEqual(extract_channel_public_handle(MockChat(username="@with_at")), "with_at")

        # 2. 频道私密，但关联讨论组带有公开用户名
        linked = MockChat(username="my_discussion_group")
        chat_with_linked = MockChat(username=None, linked_chat=linked)
        self.assertEqual(extract_channel_public_handle(chat_with_linked), "my_discussion_group")

        # 3. 频道纯私密，无任何公开用户名
        private_chat = MockChat(username=None, linked_chat=MockChat(username=None))
        self.assertIsNone(extract_channel_public_handle(private_chat))
        self.assertIsNone(extract_channel_public_handle(None))

    async def test_probe_worker_direct_admin(self):
        # 模拟 Worker 机器人已被添加为频道管理员
        client = MagicMock()
        client.username = "admin_bot"
        client.get_chat = AsyncMock(return_value=MockChat(username="my_channel"))
        member_mock = MagicMock()
        member_mock.privileges.can_post_messages = True
        client.get_chat_member = AsyncMock(return_value=member_mock)

        result = await probe_worker_channel_access(1, client, -1001234567890)

        self.assertTrue(result["can_read"])
        self.assertTrue(result["can_write"])
        self.assertEqual(result["mode"], "direct_admin")
        self.assertIn(1, bot_mod.channel_accessible_clients)
        self.assertIn(1, bot_mod.channel_write_clients)

    async def test_probe_worker_no_join_via_public_handle(self):
        # 模拟 Worker 机器人未加频道，首次 get_chat(ID) 报 CHANNEL_INVALID，
        # 系统通过 public_handle 自动解析 Peer 成功接入
        client = MagicMock()
        client.username = "worker_bot"
        peer_resolved = False

        async def mock_get_chat(target):
            nonlocal peer_resolved
            if target == -1001234567890:
                if not peer_resolved:
                    raise Exception("CHANNEL_INVALID: channel not found in peer cache")
                return MockChat(username="my_channel")
            elif target == "my_channel":
                peer_resolved = True
                return MockChat(username="my_channel")
            raise Exception("unexpected target")

        client.get_chat = AsyncMock(side_effect=mock_get_chat)

        result = await probe_worker_channel_access(
            index=2,
            client=client,
            bin_channel=-1001234567890,
            public_handle="my_channel",
        )

        self.assertTrue(result["can_read"])
        self.assertFalse(result["can_write"])
        self.assertEqual(result["mode"], "no_join_resolved")
        self.assertIn(2, bot_mod.channel_accessible_clients)
        # 读写分离：未加频道的 Worker 不具备写权限
        self.assertNotIn(2, bot_mod.channel_write_clients)

    async def test_probe_worker_cached_session_non_participant(self):
        # 模拟 Worker 机器人的 SQLite 虽有 Peer 缓存，但 get_chat_member 证实并非成员
        client = MagicMock()
        client.username = "cached_worker_bot"
        client.get_chat = AsyncMock(return_value=MockChat(username="my_channel"))
        client.get_chat_member = AsyncMock(side_effect=Exception("USER_NOT_PARTICIPANT"))

        result = await probe_worker_channel_access(3, client, -1001234567890)

        self.assertTrue(result["can_read"])
        self.assertFalse(result["can_write"])
        self.assertEqual(result["mode"], "no_join_resolved")
        self.assertIn(3, bot_mod.channel_accessible_clients)
        self.assertNotIn(3, bot_mod.channel_write_clients)

    async def test_probe_worker_strictly_private_unreachable(self):
        # 模拟纯私密频道（无 public_handle），Worker 无法访问
        client = MagicMock()
        client.username = "stranded_bot"
        client.get_chat = AsyncMock(side_effect=Exception("CHANNEL_INVALID"))

        result = await probe_worker_channel_access(
            index=4,
            client=client,
            bin_channel=-1001234567890,
            public_handle=None,
        )

        self.assertFalse(result["can_read"])
        self.assertFalse(result["can_write"])
        self.assertEqual(result["mode"], "unreachable")
        self.assertNotIn(4, bot_mod.channel_accessible_clients)
        self.assertNotIn(4, bot_mod.channel_write_clients)

    def test_runtime_snapshot_includes_modes_and_read_write_separation(self):
        c0 = MagicMock()
        c0.username = "primary_bot"
        c1 = MagicMock()
        c1.username = "nojoin_worker"

        bot_mod.multi_clients[0] = c0
        bot_mod.multi_clients[1] = c1
        bot_mod.register_bot_client(0)
        bot_mod.register_bot_client(1)

        bot_mod.channel_accessible_clients.update({0, 1})
        bot_mod.channel_write_clients.update({0})
        bot_mod.bot_channel_modes[0] = {"mode": "primary_admin", "can_read": True, "can_write": True}
        bot_mod.bot_channel_modes[1] = {"mode": "no_join_resolved", "can_read": True, "can_write": False}

        snap = bot_mod.get_bot_runtime_snapshot()
        self.assertEqual(snap[0]["mode"], "primary_admin")
        self.assertTrue(snap[0]["can_read"])
        self.assertTrue(snap[0]["can_write"])

        self.assertEqual(snap[1]["mode"], "no_join_resolved")
        self.assertTrue(snap[1]["can_read"])
        self.assertFalse(snap[1]["can_write"])

        # 流播调度应能选出 0 和 1
        selected_first = bot_mod.select_stream_bot()
        selected_second = bot_mod.select_stream_bot()
        self.assertEqual({selected_first, selected_second}, {0, 1})


if __name__ == "__main__":
    unittest.main()
