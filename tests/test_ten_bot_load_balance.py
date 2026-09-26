import tests  # noqa: F401
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault(
    "MISTRELAY_DB_PATH",
    tempfile.mktemp(prefix="mistrelay_tenbot_tests_", suffix=".db", dir="/tmp"),
)
os.environ.setdefault(
    "MISTRELAY_SESSION_DIR",
    tempfile.mkdtemp(prefix="mistrelay_tenbot_sessions_", dir="/tmp"),
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

        err_mod = types.ModuleType("pyrogram.errors")
        class ChannelInvalid(Exception):
            pass
        err_mod.ChannelInvalid = ChannelInvalid
        err_mod.PeerIdInvalid = Exception
        sys.modules["pyrogram.errors"] = err_mod

import WebStreamer.bot as bot_mod
from WebStreamer.bot.clients import (
    hot_add_bot_client,
    hot_remove_bot_client,
)
from WebStreamer.vars import Var


class TestTenBotLoadBalancing(unittest.IsolatedAsyncioTestCase):
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

    async def test_ten_bots_hot_mount_and_load_dispatch(self):
        """测试动态挂载 10 个机器人，并验证免加频道 Peer 解析与 10 节点请求分流负载均衡"""
        tokens = [f"2222222{i:02d}:BBBWorkerBotToken1234567890abcdef{i:02d}" for i in range(1, 11)]

        for idx, token in enumerate(tokens, start=1):
            mock_client = MagicMock()
            mock_client.start = AsyncMock()
            mock_client.stop = AsyncMock()
            mock_client.get_me = AsyncMock(return_value=MagicMock(username=f"worker_{idx}_bot"))
            mock_client.is_connected = True

            with patch("WebStreamer.bot.clients.Client", return_value=mock_client), \
                 patch("WebStreamer.bot.clients.probe_worker_channel_access", AsyncMock(return_value={
                     "mode": "no_join_resolved",
                     "can_read": True,
                     "can_write": False,
                     "username": f"worker_{idx}_bot",
                     "last_error": "",
                 })), \
                 patch("WebStreamer.bot.clients.client_health_check", AsyncMock()):

                res = await hot_add_bot_client(token, persist=False)
                self.assertEqual(res["index"], idx)
                self.assertEqual(res["mode"], "no_join_resolved")
                self.assertTrue(res["can_read"])
                self.assertFalse(res["can_write"])

        # 验证目前集群包含 1 个主控 + 10 个 Worker = 11 个客户端
        self.assertEqual(len(bot_mod.multi_clients), 11)
        self.assertEqual(len(bot_mod.channel_accessible_clients), 11)

        # 模拟高并发 110 次分流请求调度
        dispatched = {i: 0 for i in range(11)}
        for req_id in range(110):
            selected = bot_mod.select_stream_bot()
            self.assertIsNotNone(selected)
            self.assertIn(selected, range(11))
            dispatched[selected] += 1
            # 记录活跃负载
            bot_mod.acquire_bot_slot(selected)
            bot_mod.release_bot_slot(selected)
            bot_mod.record_bot_bytes(selected, 1024*1024)

        print(f"\n[10节点负载均衡测试] 110次分流请求在11个节点的分流统计: {dispatched}")
        # 验证所有节点均参与了分流且负载高度均匀（每个节点均分流了正好 10 次请求）
        for i in range(11):
            self.assertEqual(dispatched[i], 10, f"节点 {i} 分流请求数不均匀: {dispatched[i]}")

        # 逐一下线释放
        for idx in range(1, 11):
            rem_res = await hot_remove_bot_client(idx, persist=False)
            self.assertEqual(rem_res["removed_index"], idx)

        self.assertEqual(len(bot_mod.multi_clients), 1)
        self.assertEqual(len(bot_mod.channel_accessible_clients), 1)



    async def test_twenty_bots_hot_mount_and_load_dispatch(self):
        """测试动态挂载 20 个机器人，并验证免加频道 Peer 解析与 20 节点请求分流负载均衡"""
        tokens = [f"3333333{i:02d}:CCCWorkerBotToken1234567890abcdef{i:02d}" for i in range(1, 21)]

        for idx, token in enumerate(tokens, start=1):
            mock_client = MagicMock()
            mock_client.start = AsyncMock()
            mock_client.stop = AsyncMock()
            mock_client.get_me = AsyncMock(return_value=MagicMock(username=f"worker20_{idx}_bot"))
            mock_client.is_connected = True

            with patch("WebStreamer.bot.clients.Client", return_value=mock_client), \
                 patch("WebStreamer.bot.clients.probe_worker_channel_access", AsyncMock(return_value={
                     "mode": "no_join_resolved",
                     "can_read": True,
                     "can_write": False,
                     "username": f"worker20_{idx}_bot",
                     "last_error": "",
                 })), \
                 patch("WebStreamer.bot.clients.client_health_check", AsyncMock()):

                res = await hot_add_bot_client(token, persist=False)
                self.assertEqual(res["index"], idx)
                self.assertEqual(res["mode"], "no_join_resolved")
                self.assertTrue(res["can_read"])
                self.assertFalse(res["can_write"])

        # 验证目前集群包含 1 个主控 + 20 个 Worker = 21 个客户端
        self.assertEqual(len(bot_mod.multi_clients), 21)
        self.assertEqual(len(bot_mod.channel_accessible_clients), 21)

        # 模拟高并发 210 次分流请求调度
        dispatched = {i: 0 for i in range(21)}
        for req_id in range(210):
            selected = bot_mod.select_stream_bot()
            self.assertIsNotNone(selected)
            self.assertIn(selected, range(21))
            dispatched[selected] += 1
            bot_mod.acquire_bot_slot(selected)
            bot_mod.release_bot_slot(selected)
            bot_mod.record_bot_bytes(selected, 1024 * 1024)

        print(f"\n[20节点负载均衡测试] 210次分流请求在21个节点的分流统计: {dispatched}")
        for i in range(21):
            self.assertEqual(dispatched[i], 10, f"节点 {i} 分流请求数不均匀: {dispatched[i]}")

        for idx in range(1, 21):
            rem_res = await hot_remove_bot_client(idx, persist=False)
            self.assertEqual(rem_res["removed_index"], idx)

        self.assertEqual(len(bot_mod.multi_clients), 1)


if __name__ == "__main__":
    unittest.main()
