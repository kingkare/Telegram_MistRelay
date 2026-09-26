import tests  # noqa: F401
import asyncio
import sys
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
        pyrogram_mod.Client = DummyClient

        errors_mod = types.ModuleType("pyrogram.errors")
        errors_mod.FloodWait = type("FloodWait", (Exception,), {})
        errors_mod.RPCError = type("RPCError", (Exception,), {})
        pyrogram_mod.errors = errors_mod


        sys.modules["pyrogram"] = pyrogram_mod
        sys.modules["pyrogram.errors"] = errors_mod

from botfather_creator import (
    wait_for_botfather_reply,
    fetch_existing_bot_tokens,
    create_single_bot,
    TOKEN_REGEX,
)


class TestBotFatherCreator(unittest.IsolatedAsyncioTestCase):
    async def test_token_regex(self):
        sample = (
            "Done! Congratulations on your new bot. You will find it at t.me/my_test_bot.\n\n"
            "Use this token to access the HTTP API:\n"
            "1234567890:AAH_XYZ1234567890abcdefghijklmnopqrstuv\n\n"
            "Keep your token secure and store it safely."
        )
        match = TOKEN_REGEX.search(sample)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "1234567890:AAH_XYZ1234567890abcdefghijklmnopqrstuv")

    async def test_wait_for_botfather_reply(self):
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.id = 105
        mock_msg.from_user.is_self = False

        async def mock_history(*args, **kwargs):
            yield mock_msg

        mock_client.get_chat_history = mock_history
        res = await wait_for_botfather_reply(mock_client, after_id=100, timeout=1.0)
        self.assertEqual(res.id, 105)

    async def test_create_single_bot_success_with_retry(self):
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(side_effect=[
            MagicMock(id=1),  # /cancel
            MagicMock(id=2),  # /newbot
            MagicMock(id=3),  # name
            MagicMock(id=4),  # uname collision
            MagicMock(id=5),  # uname success
        ])

        replies = [
            MagicMock(id=10, text="Alright, a new bot. How are we going to call it?", from_user=MagicMock(is_self=False)),
            MagicMock(id=11, text="Good. Now let's choose a username for your bot.", from_user=MagicMock(is_self=False)),
            MagicMock(id=12, text="Sorry, this username is already taken. Please try something different.", from_user=MagicMock(is_self=False)),
            MagicMock(id=13, text="Done! Use this token: 1234567890:AAH_XYZ1234567890abcdefghijklmnopqrstuv", from_user=MagicMock(is_self=False)),
        ]
        reply_iter = iter(replies)

        async def mock_wait(*args, **kwargs):
            return next(reply_iter)

        with patch("botfather_creator.wait_for_botfather_reply", side_effect=mock_wait):
            uname, tok = await create_single_bot(mock_client, display_name="Test Node", username_prefix="test_node")
            self.assertTrue(uname.endswith("_bot"))
            self.assertEqual(tok, "1234567890:AAH_XYZ1234567890abcdefghijklmnopqrstuv")

    async def test_create_single_bot_limit_reached(self):
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(return_value=MagicMock(id=2))

        limit_reply = MagicMock(
            id=10,
            text="Sorry, you can't add more than 20 bots to your account. Please delete some bots before creating new ones.",
            from_user=MagicMock(is_self=False),
        )

        with patch("botfather_creator.wait_for_botfather_reply", AsyncMock(return_value=limit_reply)):
            with self.assertRaises(ValueError) as ctx:
                await create_single_bot(mock_client, display_name="Test Node", username_prefix="test_node")
            self.assertIn("20 个机器人的最大上限", str(ctx.exception))

    async def test_fetch_existing_bot_tokens(self):
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(return_value=MagicMock(id=2))

        btn = MagicMock()
        btn.text = "@existing_bot"
        btn.callback_data = b"cb_data"

        markup_msg = MagicMock(id=10)
        markup_msg.reply_markup.inline_keyboard = [[btn]]
        markup_msg.click = AsyncMock(return_value=MagicMock(
            text="Here is the token for @existing_bot:\n9876543210:BBH_XYZ1234567890abcdefghijklmnopqrstuv"
        ))

        with patch("botfather_creator.wait_for_botfather_reply", AsyncMock(return_value=markup_msg)):
            tokens = await fetch_existing_bot_tokens(mock_client, max_limit=5)
            self.assertEqual(len(tokens), 1)
            self.assertEqual(tokens[0]["username"], "existing_bot")
            self.assertEqual(tokens[0]["token"], "9876543210:BBH_XYZ1234567890abcdefghijklmnopqrstuv")


    async def test_create_single_bot_spambot_restricted(self):
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(return_value=MagicMock(id=2))

        spambot_reply = MagicMock(
            id=10,
            text="Unfortunately, you cannot create new bots at this time.\n\nFor more information on why this happened and what your appeal options are, kindly contact @SpamBot.",
            from_user=MagicMock(is_self=False),
        )

        with patch("botfather_creator.wait_for_botfather_reply", AsyncMock(return_value=spambot_reply)):
            with self.assertRaises(ValueError) as ctx:
                await create_single_bot(mock_client, display_name="Test Node", username_prefix="test_node")
            self.assertIn("SpamBot", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
