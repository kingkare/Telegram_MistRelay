import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pyrogram_patch
from pyrogram import Client
from WebStreamer.bot.plugins.stream_modules import media_processor


class BotHandlersResilienceTests(unittest.IsolatedAsyncioTestCase):
    """验证主控机器人 Handlers 规范化、重连防丢失机制以及 Client.get_me 极速防崩溃补丁"""

    def test_all_five_handlers_have_handler_metadata(self):
        """验证所有 5 个核心消息处理器均挂载了 handlers 元数据（遵循 Pyrogram 插件规范）"""
        handlers_meta = [
            (media_processor.user_register_command_handler, 1),
            (media_processor.start_command_handler, 2),
            (media_processor.help_command_handler, 3),
            (media_processor.media_receive_handler, 4),
            (media_processor.channel_link_receive_handler, 5),
        ]
        for func, expected_group in handlers_meta:
            self.assertTrue(
                hasattr(func, "handlers"),
                f"{func.__name__} 缺失 handlers 属性，无法被 load_plugins 自动加载！"
            )
            handlers = getattr(func, "handlers")
            self.assertGreaterEqual(len(handlers), 1)
            handler_obj, group = handlers[0]
            self.assertEqual(
                group, expected_group,
                f"{func.__name__} group 不匹配: 期望 {expected_group}, 实际 {group}"
            )

    async def test_register_stream_handlers_is_idempotent(self):
        """验证 register_stream_handlers 具有幂等性，重复注册不会产生重复 Handler"""
        cli = Client("test_resilience_idempotent", in_memory=True)
        # 第一次手动注册
        media_processor.register_stream_handlers(cli)
        await asyncio.sleep(0.01)
        
        initial_counts = {g: len(h) for g, h in cli.dispatcher.groups.items()}
        for g in (1, 2, 3, 4, 5):
            self.assertIn(g, initial_counts)
            self.assertEqual(initial_counts[g], 1)

        # 第二次注册（模拟重复调用）
        media_processor.register_stream_handlers(cli)
        await asyncio.sleep(0.01)

        second_counts = {g: len(h) for g, h in cli.dispatcher.groups.items()}
        self.assertEqual(initial_counts, second_counts)

    async def test_handlers_recovery_after_dispatcher_clear(self):
        """模拟重连时 dispatcher.groups 被清空，验证 register_stream_handlers 能 100% 完整复活全部 Handlers"""
        cli = Client("test_resilience_reconnect", in_memory=True)
        media_processor.register_stream_handlers(cli)
        await asyncio.sleep(0.01)
        self.assertEqual(len(cli.dispatcher.groups), 5)

        # 模拟 dispatcher.stop() 执行 self.groups.clear()
        cli.dispatcher.groups.clear()
        self.assertEqual(len(cli.dispatcher.groups), 0)

        # 模拟重连恢复流程
        media_processor.register_stream_handlers(cli)
        await asyncio.sleep(0.01)
        self.assertEqual(len(cli.dispatcher.groups), 5)
        for g in (1, 2, 3, 4, 5):
            self.assertEqual(len(cli.dispatcher.groups[g]), 1)

    async def test_patched_get_me_uses_get_users(self):
        """验证 patched_get_me 优先使用 GetUsers(InputUserSelf()) 绕过 GetFullUser 及 0x93eadb53 报错"""
        cli = Client("test_resilience_get_me", in_memory=True)
        mock_raw_user = SimpleNamespace(
            id=123456,
            is_self=True,
            contact=False,
            mutual_contact=False,
            deleted=False,
            bot=True,
            verified=False,
            restricted=False,
            scam=False,
            fake=False,
            support=False,
            premium=False,
            first_name="TestBot",
            last_name=None,
            status=None,
            username="test_mistrelay_bot",
            lang_code="en",
            emoji_status=None,
            photo=None,
            restriction_reason=[],
        )

        with (
            patch.object(cli, "is_connected", True),
            patch.object(cli, "invoke", AsyncMock(return_value=[mock_raw_user]), create=True) as mock_invoke,
        ):
            me = await cli.get_me()
            mock_invoke.assert_awaited_once()
            # 验证 invoke 的函数是 GetUsers 而不是 GetFullUser
            invoked_fn = mock_invoke.call_args[0][0]
            self.assertEqual(invoked_fn.__class__.__name__, "GetUsers")
            self.assertEqual(me.id, 123456)
            self.assertEqual(me.username, "test_mistrelay_bot")
            self.assertEqual(cli.me.username, "test_mistrelay_bot")


if __name__ == "__main__":
    unittest.main()
