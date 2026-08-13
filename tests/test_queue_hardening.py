import asyncio
import unittest
from unittest.mock import patch

from WebStreamer.bot.plugins.stream_modules import queue_manager


class QueueHardeningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        queue_manager.message_processing_queue = None
        queue_manager.queue_processing_lock = None
        queue_manager.queue_tracker_lock = asyncio.Lock()
        queue_manager.message_concurrent_semaphore = None
        queue_manager.queue_processor_task = None
        queue_manager.queue_item_tracker.clear()
        queue_manager.current_processing_queue_id = None

    async def asyncTearDown(self):
        task = queue_manager.queue_processor_task
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_queue_is_bounded_and_rejects_when_full(self):
        def config_value(key, default=None):
            return 2 if key == "MAX_MESSAGE_QUEUE_SIZE" else default

        with patch("configer.get_config_value", side_effect=config_value):
            queue_manager._ensure_queue_initialized()

        self.assertEqual(queue_manager.message_processing_queue.maxsize, 2)
        queue_manager.message_processing_queue.put_nowait((None, (), {}, None, None))
        queue_manager.message_processing_queue.put_nowait((None, (), {}, None, None))

        async def task(queue_reply_msg=None):
            return []

        self.assertFalse(queue_manager.enqueue_message_task(task))
        self.assertEqual(queue_manager.message_processing_queue.qsize(), 2)

    async def test_configured_queue_limit_is_clamped(self):
        with patch("configer.get_config_value", return_value=100_000):
            queue_manager._ensure_queue_initialized()
        self.assertEqual(
            queue_manager.message_processing_queue.maxsize,
            queue_manager.HARD_MAX_QUEUE_SIZE,
        )

    async def test_completed_tracker_entry_is_evicted(self):
        queue_manager.message_processing_queue = asyncio.Queue(maxsize=2)
        queue_manager.queue_item_tracker[7] = {
            "status": "waiting",
            "task_gids": [],
        }

        async def task(queue_reply_msg=None):
            return []

        await queue_manager._process_message_item((task, (), {}, None, 7), None)
        self.assertNotIn(7, queue_manager.queue_item_tracker)


if __name__ == "__main__":
    unittest.main()
