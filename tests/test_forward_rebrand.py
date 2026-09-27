import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import tests  # noqa: F401
from WebStreamer.utils.rebrand_cleaner import (
    clean_and_rebrand_caption,
    clean_drive_filename,
    get_effective_target_channel,
    normalize_channel_identity,
    parse_custom_replace_rules,
)


class TestRebrandCleaner(unittest.TestCase):
    def test_normalize_channel_identity(self):
        self.assertEqual(
            normalize_channel_identity("@jiuyue1314520"),
            ("@jiuyue1314520", "jiuyue1314520", "https://t.me/jiuyue1314520"),
        )
        self.assertEqual(
            normalize_channel_identity("https://t.me/my_test_channel"),
            ("@my_test_channel", "my_test_channel", "https://t.me/my_test_channel"),
        )
        self.assertEqual(
            normalize_channel_identity("bare_chan"),
            ("@bare_chan", "bare_chan", "https://t.me/bare_chan"),
        )
        self.assertEqual(normalize_channel_identity(""), ("", "", ""))
        self.assertEqual(normalize_channel_identity(None), ("", "", ""))

    def test_parse_custom_replace_rules(self):
        rules_text = """
        # 这是注释行
        老广告词=>新宣传词
        剔除这个广告
        原链接->新链接
        """
        rules = parse_custom_replace_rules(rules_text)
        self.assertEqual(
            rules,
            [
                ("老广告词", "新宣传词"),
                ("剔除这个广告", ""),
                ("原链接", "新链接"),
            ],
        )

    def test_caption_rebranding(self):
        raw_cap = (
            "精彩热门视频 电报TG@yijiqwq 欢迎订阅 @other_bot "
            "访问 https://t.me/other_channel 获取更多！"
        )
        cleaned = clean_and_rebrand_caption(
            raw_cap,
            target_channel="@jiuyue1314520",
            signature="📢 关注官方频道: {channel}",
        )
        # 验证第三方来源被彻底抹除或替换
        self.assertNotIn("yijiqwq", cleaned)
        self.assertNotIn("other_bot", cleaned)
        self.assertNotIn("other_channel", cleaned)
        # 验证本频道归属与签名
        self.assertIn("@jiuyue1314520", cleaned)
        self.assertIn("https://t.me/jiuyue1314520", cleaned)
        self.assertIn("📢 关注官方频道: @jiuyue1314520", cleaned)

    def test_caption_custom_rules_and_length_limit(self):
        custom_rules = "不良广告=>优质内容\n无用尾巴"
        raw_cap = "这里包含不良广告和无用尾巴。"
        cleaned = clean_and_rebrand_caption(
            raw_cap,
            target_channel="@jiuyue1314520",
            signature="📢 频道: {channel}",
            custom_rules=custom_rules,
        )
        self.assertIn("优质内容", cleaned)
        self.assertNotIn("不良广告", cleaned)
        self.assertNotIn("无用尾巴", cleaned)

        # 超长文本截断测试 (Telegram 1024 限制)
        long_cap = "A" * 1500
        cleaned_long = clean_and_rebrand_caption(
            long_cap,
            target_channel="@jiuyue1314520",
            signature="📢 频道: {channel}",
            max_length=1024,
        )
        self.assertLessEqual(len(cleaned_long), 1024)
        self.assertTrue(cleaned_long.endswith("📢 频道: @jiuyue1314520"))

    def test_filename_cleaning(self):
        # 验证保护扩展名与序号 (1), 01, E01
        self.assertEqual(
            clean_drive_filename("电报TG@yijiqwq 棒棒糖 (1).mp4"),
            "棒棒糖 (1).mp4",
        )
        self.assertEqual(
            clean_drive_filename("【tg搜@abc_channel】动作大片-01-@other_bot.mkv"),
            "动作大片-01.mkv",
        )
        self.assertEqual(
            clean_drive_filename("番剧_E01_电报TG@xyz.ts"),
            "番剧_E01.ts",
        )
        # 广告作为全部主干时的安全兜底
        self.assertEqual(
            clean_drive_filename("@only_ad.mp4"),
            "only_ad.mp4",
        )
        # clean_enabled=False 时不作修改
        self.assertEqual(
            clean_drive_filename("电报TG@yijiqwq 棒棒糖.mp4", clean_enabled=False),
            "电报TG@yijiqwq 棒棒糖.mp4",
        )


class TestMediaProcessorRebranding(unittest.IsolatedAsyncioTestCase):
    async def test_process_single_media_copy_message(self):
        from WebStreamer.bot.plugins.stream_modules import media_processor
        from WebStreamer.vars import Var

        # 模拟消息对象
        mock_user = SimpleNamespace(id=123456, first_name="Tester")
        mock_chat = SimpleNamespace(id=987654)
        mock_media = SimpleNamespace(
            file_unique_id="unique_123",
            file_id="file_id_123",
            file_name="电报TG@yijiqwq 演示视频 (1).mp4",
            file_size=1048576,
            mime_type="video/mp4",
            duration=60,
            width=1920,
            height=1080,
        )
        mock_msg = SimpleNamespace(
            id=101,
            chat=mock_chat,
            from_user=mock_user,
            media_group_id=None,
            caption="精彩短片 电报TG@yijiqwq 关注 @other_bot",
            document=None,
            video=mock_media,
            audio=None,
            photo=None,
            animation=None,
            voice=None,
            video_note=None,
            sticker=None,
            reply=AsyncMock(),
            reply_text=AsyncMock(),
            forward=AsyncMock(),
        )

        mock_copied_msg = SimpleNamespace(
            id=202,
            chat=SimpleNamespace(id=-1001998444696),
            media=SimpleNamespace(value="video"),
            video=mock_media,
            caption="洗白后的配文",
        )

        with patch.object(Var, "BIN_CHANNEL", -1001998444696), \
             patch.object(Var, "ALLOWED_USERS", ["123456"]), \
             patch.object(Var, "ENABLE_STREAM", True), \
             patch.object(Var, "SEND_STREAM_LINK", False), \
             patch("configer.get_config_value", side_effect=lambda key, default=None: {
                 "FORWARD_REBRAND_ENABLED": True,
                 "FORWARD_TARGET_CHANNEL": "@jiuyue1314520",
                 "FORWARD_CHANNEL_SIGNATURE": "📢 关注: {channel}",
                 "FORWARD_CLEAN_FILENAMES": True,
                 "FORWARD_CUSTOM_REPLACE_RULES": "",
             }.get(key, default)), \
             patch.object(media_processor.StreamBot, "copy_message", new_callable=AsyncMock) as mock_copy, \
             patch("WebStreamer.bot.plugins.stream_modules.media_processor.save_tg_media") as mock_save:

            mock_copy.return_value = mock_copied_msg
            mock_save.return_value = "unique_123"

            await media_processor.process_single_media(mock_msg)

            # 验证调用了 copy_message
            self.assertTrue(mock_copy.called)
            copy_call_kwargs = mock_copy.call_args.kwargs
            self.assertEqual(copy_call_kwargs["chat_id"], -1001998444696)
            self.assertEqual(copy_call_kwargs["from_chat_id"], 987654)
            self.assertEqual(copy_call_kwargs["message_id"], 101)
            # 验证配文被洗白
            self.assertIn("@jiuyue1314520", copy_call_kwargs["caption"])
            self.assertNotIn("yijiqwq", copy_call_kwargs["caption"])

            # 验证写入数据库时传入了净化后的文件名和配文
            self.assertTrue(mock_save.called)
            save_kwargs = mock_save.call_args.kwargs
            self.assertEqual(save_kwargs["custom_file_name"], "演示视频 (1).mp4")
            self.assertIn("@jiuyue1314520", save_kwargs["custom_caption"])

    async def test_process_single_media_fallback_to_forward(self):
        from WebStreamer.bot.plugins.stream_modules import media_processor
        from WebStreamer.vars import Var

        mock_user = SimpleNamespace(id=123456, first_name="Tester")
        mock_chat = SimpleNamespace(id=987654)
        mock_media = SimpleNamespace(
            file_unique_id="unique_fallback",
            file_id="file_id_fallback",
            file_name="test.mp4",
            file_size=1024,
            mime_type="video/mp4",
        )
        mock_msg = SimpleNamespace(
            id=102,
            chat=mock_chat,
            from_user=mock_user,
            media_group_id=None,
            caption="test caption",
            document=None,
            video=mock_media,
            audio=None,
            photo=None,
            animation=None,
            voice=None,
            video_note=None,
            sticker=None,
            reply=AsyncMock(),
            reply_text=AsyncMock(),
            forward=AsyncMock(),
        )

        mock_fwd_msg = SimpleNamespace(
            id=303,
            chat=SimpleNamespace(id=-1001998444696),
            media=SimpleNamespace(value="video"),
            video=mock_media,
            caption="test caption",
        )
        mock_msg.forward.return_value = mock_fwd_msg

        with patch.object(Var, "BIN_CHANNEL", -1001998444696), \
             patch.object(Var, "ALLOWED_USERS", ["123456"]), \
             patch.object(Var, "ENABLE_STREAM", True), \
             patch.object(Var, "SEND_STREAM_LINK", False), \
             patch("configer.get_config_value", return_value=True), \
             patch.object(media_processor.StreamBot, "copy_message", side_effect=Exception("copy error")), \
             patch("WebStreamer.bot.plugins.stream_modules.media_processor.save_tg_media") as mock_save:

            mock_save.return_value = "unique_fallback"
            await media_processor.process_single_media(mock_msg)

            # 当 copy_message 异常时安全回退到 forward
            self.assertTrue(mock_msg.forward.called)
            self.assertTrue(mock_save.called)


class TestRebrandApiHandlers(unittest.IsolatedAsyncioTestCase):
    async def test_rebrand_preview_handler(self):
        from WebStreamer.server import stream_routes

        class FakeRequest:
            async def json(self):
                return {
                    "caption": "热门视频 电报TG@yijiqwq 关注 @other_bot https://t.me/other",
                    "filename": "电报TG@yijiqwq 棒棒糖 (1).mp4",
                    "target_channel": "@jiuyue1314520",
                    "signature": "📢 关注官方: {channel}",
                    "clean_filenames": True,
                    "custom_rules": "",
                }

        resp = await stream_routes.rebrand_preview_handler(FakeRequest())
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.text)
        self.assertTrue(data["success"])
        self.assertNotIn("yijiqwq", data["data"]["cleaned_caption"])
        self.assertIn("@jiuyue1314520", data["data"]["cleaned_caption"])
        self.assertEqual(data["data"]["cleaned_filename"], "棒棒糖 (1).mp4")


if __name__ == "__main__":
    unittest.main()


class TestMediaGroupAndConfigRebrand(unittest.IsolatedAsyncioTestCase):
    async def test_process_media_group_copy_and_fallback(self):
        from WebStreamer.bot.plugins.stream_modules import media_processor
        from WebStreamer.vars import Var

        mock_user = SimpleNamespace(id=123456, first_name="Tester")
        mock_chat = SimpleNamespace(id=987654)
        media_1 = SimpleNamespace(
            file_unique_id="grp_u1",
            file_id="grp_f1",
            file_name="电报TG@yijiqwq 剧集 (1).mp4",
            file_size=1024,
            mime_type="video/mp4",
        )
        media_2 = SimpleNamespace(
            file_unique_id="grp_u2",
            file_id="grp_f2",
            file_name="电报TG@yijiqwq 剧集 (2).mp4",
            file_size=1024,
            mime_type="video/mp4",
        )
        msg_1 = SimpleNamespace(
            id=501,
            chat=mock_chat,
            from_user=mock_user,
            media_group_id="mg_1",
            caption="合集第一集 @other_bot https://t.me/other",
            document=None,
            video=media_1,
            audio=None,
            photo=None,
            animation=None,
            voice=None,
            video_note=None,
            sticker=None,
            reply=AsyncMock(),
            reply_text=AsyncMock(),
            forward=AsyncMock(),
        )
        msg_2 = SimpleNamespace(
            id=502,
            chat=mock_chat,
            from_user=mock_user,
            media_group_id="mg_1",
            caption="",
            document=None,
            video=media_2,
            audio=None,
            photo=None,
            animation=None,
            voice=None,
            video_note=None,
            sticker=None,
            reply=AsyncMock(),
            reply_text=AsyncMock(),
            forward=AsyncMock(),
        )

        copied_1 = SimpleNamespace(
            id=601,
            chat=SimpleNamespace(id=-1001998444696),
            media=SimpleNamespace(value="video"),
            video=media_1,
            caption="合集第一集 @jiuyue1314520",
        )
        copied_2 = SimpleNamespace(
            id=602,
            chat=SimpleNamespace(id=-1001998444696),
            media=SimpleNamespace(value="video"),
            video=media_2,
            caption="",
        )

        with patch.object(Var, "BIN_CHANNEL", -1001998444696), \
             patch.object(Var, "ALLOWED_USERS", ["123456"]), \
             patch.object(Var, "ENABLE_STREAM", True), \
             patch.object(Var, "SEND_STREAM_LINK", False), \
             patch("configer.get_config_value", side_effect=lambda key, default=None: {
                 "FORWARD_REBRAND_ENABLED": True,
                 "FORWARD_TARGET_CHANNEL": "@jiuyue1314520",
                 "FORWARD_CHANNEL_SIGNATURE": "📢 频道: {channel}",
                 "FORWARD_CLEAN_FILENAMES": True,
                 "FORWARD_CUSTOM_REPLACE_RULES": "",
             }.get(key, default)), \
             patch.object(media_processor.StreamBot, "copy_media_group", new_callable=AsyncMock) as mock_copy_grp, \
             patch("WebStreamer.bot.plugins.stream_modules.media_processor.save_tg_media") as mock_save:

            mock_copy_grp.return_value = [copied_1, copied_2]
            mock_save.side_effect = ["grp_u1", "grp_u2"]

            await media_processor.process_media_group([msg_1, msg_2])

            self.assertTrue(mock_copy_grp.called)
            self.assertEqual(mock_save.call_count, 2)
            first_save_kwargs = mock_save.call_args_list[0].kwargs
            second_save_kwargs = mock_save.call_args_list[1].kwargs
            self.assertEqual(first_save_kwargs["custom_file_name"], "剧集 (1).mp4")
            self.assertEqual(second_save_kwargs["custom_file_name"], "剧集 (2).mp4")
            self.assertIn("@jiuyue1314520", first_save_kwargs["custom_caption"])

    async def test_config_api_read_and_write_rebrand_fields(self):
        from WebStreamer.server import stream_routes

        class PostRequest:
            async def json(self):
                return {
                    "FORWARD_REBRAND_ENABLED": True,
                    "FORWARD_TARGET_CHANNEL": "@jiuyue1314520",
                    "FORWARD_CHANNEL_SIGNATURE": "📢 官方频道: {channel}",
                    "FORWARD_CLEAN_FILENAMES": True,
                    "FORWARD_CUSTOM_REPLACE_RULES": "广告A=>福利A\n垃圾词",
                }

        with patch("WebStreamer.server.stream_routes.set_configs") as mock_set_configs:
            post_resp = await stream_routes.update_config_handler(PostRequest())
            self.assertEqual(post_resp.status, 200)
            body = json.loads(post_resp.text)
            self.assertTrue(body["success"])
            self.assertEqual(body["updated_count"], 5)
            self.assertFalse(body["needs_restart"])
            self.assertTrue(mock_set_configs.called)
