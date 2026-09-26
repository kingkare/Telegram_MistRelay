import tests  # noqa: F401
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from WebStreamer.bot.plugins.stream_modules import media_processor
from WebStreamer.bot.plugins.stream_modules import queue_manager


def message(user_id=123, username="allowed"):
    return SimpleNamespace(from_user=SimpleNamespace(id=user_id, username=username))


class MediaAllowlistTests(unittest.TestCase):
    def test_empty_allowlist_fails_closed(self):
        with patch.object(media_processor.Var, "ALLOWED_USERS", []):
            self.assertFalse(media_processor.is_allowed_user(message()))


class MediaIngressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        media_processor.media_group_cache.clear()
        for task in media_processor.media_group_tasks.values():
            task.cancel()
        media_processor.media_group_tasks.clear()

    async def test_unauthorized_media_never_reaches_cache_or_queue(self):
        inbound = SimpleNamespace(
            from_user=SimpleNamespace(id=999, username="outsider"),
            media_group_id="album",
            chat=SimpleNamespace(id=123),
        )
        with (
            patch.object(media_processor.Var, "ENABLE_STREAM", True),
            patch.object(media_processor.Var, "ALLOWED_USERS", ["123"]),
            patch.object(queue_manager, "enqueue_message_task") as enqueue,
        ):
            await media_processor.media_receive_handler(None, inbound)

        enqueue.assert_not_called()
        self.assertEqual(dict(media_processor.media_group_cache), {})
        self.assertEqual(media_processor.media_group_tasks, {})

    async def test_authorized_single_media_is_admitted_once(self):
        inbound = SimpleNamespace(
            from_user=SimpleNamespace(id=123, username="trusted"),
            media_group_id=None,
            reply=Mock(),
        )
        with (
            patch.object(media_processor.Var, "ENABLE_STREAM", True),
            patch.object(media_processor.Var, "ALLOWED_USERS", ["123"]),
            patch.object(queue_manager, "enqueue_message_task", return_value=True) as enqueue,
        ):
            await media_processor.media_receive_handler(None, inbound)

        enqueue.assert_called_once_with(media_processor.process_single_media, inbound)

    def test_missing_sender_fails_closed(self):
        with patch.object(media_processor.Var, "ALLOWED_USERS", ["123"]):
            self.assertFalse(media_processor.is_allowed_user(SimpleNamespace(from_user=None)))

    def test_allows_explicit_user_id(self):
        with patch.object(media_processor.Var, "ALLOWED_USERS", ["123"]):
            self.assertTrue(media_processor.is_allowed_user(message()))

    def test_rejects_mutable_username(self):
        with patch.object(media_processor.Var, "ALLOWED_USERS", ["allowed"]):
            self.assertFalse(media_processor.is_allowed_user(message()))


if __name__ == "__main__":
    unittest.main()
