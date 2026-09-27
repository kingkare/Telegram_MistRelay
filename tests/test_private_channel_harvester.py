import os
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from private_channel_harvester import (
    parse_telegram_post_links,
    harvest_single_message,
    HarvesterTaskManager,
)


class DummyMediaType:
    def __init__(self, value="video"):
        self.value = value


class DummyVideo:
    def __init__(self, file_name="raw_video_电报TG@other.mp4", duration=120, width=1920, height=1080):
        self.file_name = file_name
        self.duration = duration
        self.width = width
        self.height = height
        self.file_size = 1024000
        self.mime_type = "video/mp4"
        self.file_id = "dummy_file_id"
        self.file_unique_id = "dummy_unique_id"


class DummyChat:
    def __init__(self, chat_id=-1001998444696, has_protected_content=False):
        self.id = chat_id
        self.has_protected_content = has_protected_content


class DummyMessage:
    def __init__(
        self,
        msg_id=101,
        chat_id=-1001998444696,
        caption="资源分享 关注 @other_channel https://t.me/other_channel",
        has_protected_content=False,
        video=None,
    ):
        self.id = msg_id
        self.chat = DummyChat(chat_id=chat_id, has_protected_content=has_protected_content)
        self.caption = caption
        self.has_protected_content = has_protected_content
        self.video = video if video is not None else DummyVideo()
        self.document = None
        self.photo = None
        self.audio = None
        self.animation = None
        self.voice = None
        self.video_note = None
        self.media = DummyMediaType("video") if self.video else None
        self.empty = False


class TestPrivateChannelHarvester(unittest.IsolatedAsyncioTestCase):
    def test_parse_links_private_public_and_invites(self):
        raw_text = """
        https://t.me/+InviteHashAbc123
        https://t.me/c/1998444696/100-104
        https://t.me/c/1998444696/108
        https://t.me/public_demo_chan/50-52
        https://telegram.me/joinchat/LegacyJoinHash99
        """
        targets, invites = parse_telegram_post_links(raw_text, default_invite="+DefaultHash00")
        self.assertEqual(
            invites,
            [
                "https://t.me/+DefaultHash00",
                "https://t.me/+InviteHashAbc123",
                "https://t.me/+LegacyJoinHash99",
            ],
        )
        self.assertEqual(len(targets), 2)

        priv_target = targets[0]
        self.assertTrue(priv_target.is_private)
        self.assertEqual(priv_target.chat_id, -1001998444696)
        self.assertEqual(priv_target.msg_ids, [100, 101, 102, 103, 104, 108])

        pub_target = targets[1]
        self.assertFalse(pub_target.is_private)
        self.assertEqual(pub_target.chat_id, "public_demo_chan")
        self.assertEqual(pub_target.msg_ids, [50, 51, 52])

    def test_parse_links_range_cap(self):
        targets, _ = parse_telegram_post_links("https://t.me/c/12345678/1-500", max_range_span=200)
        self.assertEqual(len(targets), 1)
        self.assertEqual(len(targets[0].msg_ids), 200)
        self.assertEqual(targets[0].msg_ids[0], 1)
        self.assertEqual(targets[0].msg_ids[-1], 200)

    @patch("private_channel_harvester.db.save_tg_media", return_value="uid_fast_101")
    @patch("private_channel_harvester.get_hash", return_value="ab12cd")
    @patch("private_channel_harvester.get_name", return_value="电影01_电报TG@other.mp4")
    async def test_harvest_single_message_fast_copy(self, mock_name, mock_hash, mock_save):
        src_msg = DummyMessage(msg_id=101, has_protected_content=False)
        copied_msg = DummyMessage(msg_id=888, has_protected_content=False)

        bot_client = MagicMock()
        bot_client.copy_message = AsyncMock(return_value=copied_msg)

        with patch("private_channel_harvester.get_config_value") as mock_cfg:
            cfg_map = {
                "FORWARD_REBRAND_ENABLED": True,
                "FORWARD_CLEAN_FILENAMES": True,
                "FORWARD_TARGET_CHANNEL": "@my_own_channel",
                "FORWARD_CHANNEL_SIGNATURE": "📢 归属: {channel}",
                "FORWARD_CUSTOM_REPLACE_RULES": "",
            }
            mock_cfg.side_effect = lambda k, default=None: cfg_map.get(k, default)

            res = await harvest_single_message(
                msg=src_msg,
                user_client=None,
                bot_client=bot_client,
                bin_channel=-100999999,
                rebrand_enabled=True,
            )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["mode"], "fast_copy")
        self.assertEqual(res["msg_id"], 888)
        self.assertEqual(res["name"], "电影01.mp4")
        bot_client.copy_message.assert_awaited_once()
        call_kwargs = bot_client.copy_message.call_args.kwargs
        self.assertIn("@my_own_channel", call_kwargs["caption"])
        self.assertNotIn("@other_channel", call_kwargs["caption"])
        mock_save.assert_called_once()

    @patch("private_channel_harvester.db.save_tg_media", return_value="uid_relay_202")
    @patch("private_channel_harvester.get_hash", return_value="ef34gh")
    @patch("private_channel_harvester.get_name", return_value="受限视频_tg搜@ad_bot.mp4")
    async def test_harvest_single_message_restricted_relay_and_cleanup(
        self, mock_name, mock_hash, mock_save
    ):
        # 模拟开启了禁止复制转发的私密频道消息
        src_msg = DummyMessage(msg_id=202, has_protected_content=True)
        uploaded_msg = DummyMessage(msg_id=999, has_protected_content=False)

        user_client = MagicMock()
        created_temp_files = []

        async def fake_download_media(msg, file_name, progress=None):
            with open(file_name, "wb") as f:
                f.write(b"fake_video_binary_payload")
            created_temp_files.append(file_name)
            return file_name

        user_client.download_media = AsyncMock(side_effect=fake_download_media)

        bot_client = MagicMock()
        bot_client.send_video = AsyncMock(return_value=uploaded_msg)

        with patch("private_channel_harvester.get_config_value") as mock_cfg:
            cfg_map = {
                "SAVE_PATH": "/tmp",
                "FORWARD_REBRAND_ENABLED": True,
                "FORWARD_CLEAN_FILENAMES": True,
                "FORWARD_TARGET_CHANNEL": "@mist_official",
                "FORWARD_CHANNEL_SIGNATURE": "",
                "FORWARD_CUSTOM_REPLACE_RULES": "",
            }
            mock_cfg.side_effect = lambda k, default=None: cfg_map.get(k, default)

            res = await harvest_single_message(
                msg=src_msg,
                user_client=user_client,
                bot_client=bot_client,
                bin_channel=-100999999,
                rebrand_enabled=True,
            )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["mode"], "restricted_relay")
        self.assertEqual(res["msg_id"], 999)
        self.assertEqual(res["name"], "受限视频.mp4")
        user_client.download_media.assert_awaited_once()
        bot_client.send_video.assert_awaited_once()

        # 验证上传完成后本地临时文件已被彻底删除
        self.assertEqual(len(created_temp_files), 1)
        self.assertFalse(os.path.exists(created_temp_files[0]))
        mock_save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
