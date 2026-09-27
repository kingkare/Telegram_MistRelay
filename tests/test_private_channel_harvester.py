import os
import shutil
import tempfile
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


class DummyPhoto:
    def __init__(self, file_name="photo.jpg", width=1280, height=720, file_size=24000):
        self.file_name = file_name
        self.width = width
        self.height = height
        self.file_size = file_size
        self.mime_type = "image/jpeg"
        self.file_id = "dummy_photo_file_id"
        self.file_unique_id = "dummy_photo_unique_id"

class DummyMessage:
    def __init__(
        self,
        msg_id=101,
        chat_id=-1001998444696,
        caption="资源分享 关注 @other_channel https://t.me/other_channel",
        has_protected_content=False,
        video=None,
        photo=None,
        grouped_id=None,
    ):
        self.id = msg_id
        self.chat = DummyChat(chat_id=chat_id, has_protected_content=has_protected_content)
        self.caption = caption
        self.has_protected_content = has_protected_content
        self.grouped_id = grouped_id
        self.media_group_id = grouped_id
        if photo is not None:
            self.photo = photo
            self.video = None
            self.media = DummyMediaType("photo")
        else:
            self.photo = None
            self.video = video if video is not None else DummyVideo()
            self.media = DummyMediaType("video") if self.video else None
        self.document = None
        self.audio = None
        self.animation = None
        self.voice = None
        self.video_note = None
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

    @patch("private_channel_harvester.db.save_tg_media", return_value="uid_pub_bot_101")
    @patch("private_channel_harvester.get_hash", return_value="ab12cd")
    @patch("private_channel_harvester.get_name", return_value="公开受限视频.mp4")
    async def test_harvest_single_message_public_channel_prefers_bot_download(
        self, mock_name, mock_hash, mock_save
    ):
        # 模拟公开受限频道消息（有 username，且开启 has_protected_content）
        src_msg = DummyMessage(msg_id=303, has_protected_content=True)
        src_msg.chat.username = "COSAVMY"
        uploaded_msg = DummyMessage(msg_id=1001, has_protected_content=False)

        user_client = MagicMock()
        user_client.download_media = AsyncMock()

        bot_client = MagicMock()
        bot_client.me = MagicMock()
        bot_client.me.username = "worker_bot_1"
        bot_client.is_connected = True

        async def fake_bot_download(msg, file_name, progress=None):
            with open(file_name, "wb") as f:
                f.write(b"bot_downloaded_binary")
            return file_name

        bot_client.download_media = AsyncMock(side_effect=fake_bot_download)
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
        self.assertEqual(res["msg_id"], 1001)
        # 核心断言：公开受限频道强制由 Bot 执行底层流式下载，协议号零调用
        bot_client.download_media.assert_awaited_once()
        user_client.download_media.assert_not_called()
        bot_client.send_video.assert_awaited_once()
        mock_save.assert_called_once()

    @patch("private_channel_harvester.select_active_protocol_account")
    @patch("private_channel_harvester.get_write_bot_client")
    @patch("private_channel_harvester.get_worker_bot_client")
    @patch("private_channel_harvester.fetch_and_expand_post")
    @patch("private_channel_harvester.harvest_single_message")
    async def test_run_pipeline_public_channel_routes_to_worker_bot(
        self, mock_harvest, mock_expand, mock_worker_bot, mock_write_bot, mock_select_acc
    ):
        manager = HarvesterTaskManager()
        from private_channel_harvester import HarvestTarget
        target = HarvestTarget(
            chat_id="COSAVMY",
            raw_chat_id="COSAVMY",
            is_private=False,
            msg_ids=[11164],
        )

        mock_bot = MagicMock()
        mock_bot.me = MagicMock()
        mock_bot.me.username = "worker_test_bot"
        mock_bot.is_connected = True
        mock_bot.get_chat = AsyncMock(return_value=DummyChat())
        mock_worker_bot.return_value = (1, mock_bot)
        mock_write_bot.return_value = mock_bot

        dummy_msg = DummyMessage(msg_id=11164)
        mock_expand.return_value = ([dummy_msg], None, "test caption")
        mock_harvest.return_value = {
            "status": "success",
            "mode": "restricted_relay",
            "msg_id": 777,
            "name": "test.mp4",
        }

        await manager._run_pipeline(
            targets=[target],
            invite_links=[],
            account_id=None,
            rebrand_enabled=True,
        )

        status = manager.get_status()
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["success_count"], 1)
        mock_select_acc.assert_not_called()
        mock_expand.assert_awaited_once()
        self.assertEqual(mock_expand.call_args.kwargs["reader_client"], mock_bot)
        mock_harvest.assert_awaited_once()
        self.assertEqual(mock_harvest.call_args.kwargs["dl_client"], mock_bot)

    @patch("private_channel_harvester.get_worker_bot_client")
    @patch("private_channel_harvester._fetch_single_msg")
    async def test_resolve_least_loaded_bot_for_large_file(
        self, mock_fetch, mock_worker_bot
    ):
        from private_channel_harvester import _resolve_least_loaded_bot_for_msg
        bot1 = MagicMock()
        bot2 = MagicMock()
        mock_worker_bot.return_value = (2, bot2)
        refreshed_msg = DummyMessage(msg_id=999)
        mock_fetch.return_value = refreshed_msg

        with patch("WebStreamer.bot.work_loads", {1: 5, 2: 0}):
            idx, chosen_bot, chosen_msg = await _resolve_least_loaded_bot_for_msg(
                current_bot_idx=1,
                current_bot=bot1,
                chat_target="COSAVMY",
                msg=DummyMessage(msg_id=999),
                file_size=60 * 1024 * 1024,  # > 50MB
            )

        self.assertEqual(idx, 2)
        self.assertEqual(chosen_bot, bot2)
        self.assertEqual(chosen_msg, refreshed_msg)

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


class TestCopiedLinkDeepResolution(unittest.IsolatedAsyncioTestCase):
    def test_copied_post_link_variants(self):
        links = """
        https://t.me/COSAVMY/11164
        https://t.me/COSAVMY/11164?single
        https://t.me/s/COSAVMY/11164
        https://t.me/c/1998444696/11164?single
        https://t.me/c/1998444696/11164?comment=99
        """
        targets, _ = parse_telegram_post_links(links)
        self.assertEqual(len(targets), 2)

        pub = next(t for t in targets if not t.is_private)
        self.assertEqual(pub.chat_id, "COSAVMY")
        self.assertEqual(pub.msg_ids, [11164])

        priv = next(t for t in targets if t.is_private)
        self.assertEqual(priv.chat_id, -1001998444696)
        self.assertEqual(priv.msg_ids, [11164])

    def test_telethon_session_adapter(self):
        from session_adapter import (
            pack_pyrogram_session,
            parse_session_to_telethon_string,
        )
        from telethon.sessions import StringSession

        fake_key = b"A" * 256
        pyro_session = pack_pyrogram_session(dc_id=4, auth_key=fake_key, api_id=12345)
        telethon_session = parse_session_to_telethon_string(pyro_session)

        self.assertTrue(telethon_session.startswith("1"))
        ss = StringSession(telethon_session)
        self.assertEqual(ss.dc_id, 4)
        self.assertEqual(ss.auth_key.key, fake_key)

    async def test_fetch_and_expand_album(self):
        from private_channel_harvester import fetch_and_expand_post

        # 模拟一个包含 1 个带标题封面和 2 个无标题媒体的相册 (grouped_id = 999888)
        class MockAlbumMsg:
            def __init__(self, mid, gid, cap=""):
                self.id = mid
                self.grouped_id = gid
                self.message = cap
                self.caption = cap
                self.empty = False

        m1 = MockAlbumMsg(11164, 999888, "【相册主标题配文】这是精彩视频")
        m2 = MockAlbumMsg(11170, 999888, "")
        m3 = MockAlbumMsg(11189, 999888, "")
        other = MockAlbumMsg(11175, 123456, "其他帖")

        mock_client = MagicMock()
        mock_client.get_messages = AsyncMock()

        async def fake_get_messages(chat, ids=None):
            if isinstance(ids, int) or ids is None:
                return m1
            # 批量扫描
            return [m3, other, m1, m2]

        mock_client.get_messages.side_effect = fake_get_messages

        album_msgs, gid_str, primary_caption = await fetch_and_expand_post(
            reader_client=mock_client,
            chat_target="COSAVMY",
            msg_id=11164,
        )

        self.assertEqual(gid_str, "999888")
        self.assertEqual(primary_caption, "【相册主标题配文】这是精彩视频")
        self.assertEqual(len(album_msgs), 3)
        self.assertEqual([m.id for m in album_msgs], [11164, 11170, 11189])

    def test_extract_nested_post_links_from_text_and_buttons(self):
        from private_channel_harvester import extract_nested_post_links

        class MockButton:
            def __init__(self, url):
                self.url = url

        class MockRow:
            def __init__(self, buttons):
                self.buttons = buttons

        class MockMarkup:
            def __init__(self, rows):
                self.inline_keyboard = rows

        class MockEntity:
            def __init__(self, url):
                self.url = url

        class MockGuideMsg:
            def __init__(self):
                self.message = "最新合集发布：请前往正片 https://t.me/COSAVMY/11164"
                self.caption = None
                self.entities = [MockEntity("https://t.me/c/1998444696/200")]
                self.reply_markup = MockMarkup([
                    MockRow([MockButton("https://t.me/c/1998444696/300-305")]),
                ])

        targets, _ = extract_nested_post_links(MockGuideMsg())
        self.assertEqual(len(targets), 2)
        target_ids = {t.chat_id: t.msg_ids for t in targets}
        self.assertIn(11164, target_ids["COSAVMY"])
        self.assertIn(200, target_ids[-1001998444696])
        self.assertIn(300, target_ids[-1001998444696])
        self.assertIn(305, target_ids[-1001998444696])


    def test_split_media_group_batches(self):
        from private_channel_harvester import split_media_group_batches

        self.assertEqual(split_media_group_batches([]), [])
        self.assertEqual(split_media_group_batches([1]), [[1]])
        self.assertEqual(split_media_group_batches([1, 2, 3]), [[1, 2, 3]])
        self.assertEqual(len(split_media_group_batches(list(range(10)))), 1)
        
        # 11 个元素：切为 9 + 2（避免尾部仅 1 个元素违背 Telegram 协议）
        b11 = split_media_group_batches(list(range(11)))
        self.assertEqual(len(b11), 2)
        self.assertEqual(len(b11[0]), 9)
        self.assertEqual(len(b11[1]), 2)
        for b in b11:
            self.assertGreaterEqual(len(b), 2)
            self.assertLessEqual(len(b), 10)

        # 21 个元素：切为 10 + 9 + 2
        b21 = split_media_group_batches(list(range(21)))
        self.assertEqual(len(b21), 3)
        self.assertEqual([len(b) for b in b21], [10, 9, 2])

    @patch("private_channel_harvester.db.save_tg_media", return_value="uid_album_fast_1")
    @patch("private_channel_harvester.get_hash", return_value="hash_fast")
    async def test_harvest_media_group_fast_copy(self, mock_hash, mock_save):
        from private_channel_harvester import harvest_media_group

        p1 = DummyMessage(msg_id=10, photo=DummyPhoto(), has_protected_content=False)
        p2 = DummyMessage(msg_id=11, photo=DummyPhoto(), has_protected_content=False)
        album_msgs = [p1, p2]

        copied_1 = DummyMessage(msg_id=801, photo=DummyPhoto(), grouped_id="mg_copied_1")
        copied_2 = DummyMessage(msg_id=802, photo=DummyPhoto(), grouped_id="mg_copied_1")

        bot_client = MagicMock()
        bot_client.copy_media_group = AsyncMock(return_value=[copied_1, copied_2])

        with patch("private_channel_harvester.get_config_value") as mock_cfg:
            cfg_map = {
                "FORWARD_REBRAND_ENABLED": True,
                "FORWARD_CLEAN_FILENAMES": True,
                "FORWARD_TARGET_CHANNEL": "@my_target",
                "FORWARD_CHANNEL_SIGNATURE": "📢 官方频道: {channel}",
                "FORWARD_CUSTOM_REPLACE_RULES": "",
            }
            mock_cfg.side_effect = lambda k, default=None: cfg_map.get(k, default)

            results = await harvest_media_group(
                album_msgs=album_msgs,
                group_id_str="source_grp_100",
                primary_caption="相册首发：欢迎关注 @ad_bot",
                bot_client=bot_client,
                bin_channel=-100999888,
                rebrand_enabled=True,
            )

        self.assertEqual(len(results), 2)
        bot_client.copy_media_group.assert_awaited_once()
        self.assertEqual(results[0]["mode"], "fast_copy")
        self.assertEqual(results[0]["media_group_id"], "mg_copied_1")
        self.assertEqual(results[1]["media_group_id"], "mg_copied_1")
        self.assertEqual(mock_save.call_count, 2)

    @patch("private_channel_harvester.db.save_tg_media", return_value="uid_album_relay_1")
    @patch("private_channel_harvester.get_hash", return_value="hash_smg")
    async def test_harvest_media_group_restricted_aggregates_via_send_media_group(
        self, mock_hash, mock_save
    ):
        from private_channel_harvester import harvest_media_group

        # 模拟 5 张受限图片 + 1 个受限大视频（真实还原用户反馈场景）
        album_msgs = []
        for i in range(5):
            album_msgs.append(
                DummyMessage(
                    msg_id=11162 + i,
                    photo=DummyPhoto(file_name=f"preview_{i}.jpg"),
                    has_protected_content=True,
                    grouped_id="grp_143210174",
                )
            )
        video_msg = DummyMessage(
            msg_id=11183,
            video=DummyVideo(file_name="正片_tg搜@ad.mp4", duration=300),
            has_protected_content=True,
            grouped_id="grp_143210174",
        )
        album_msgs.append(video_msg)

        # 模拟下载
        created_files = []
        async def fake_download(msg, temp_file_path, **kwargs):
            os.makedirs(os.path.dirname(temp_file_path), exist_ok=True)
            with open(temp_file_path, "wb") as f:
                f.write(b"dummy_payload")
            created_files.append(temp_file_path)
            return temp_file_path

        sent_messages = [
            DummyMessage(msg_id=5968 + i, grouped_id="tg_native_mg_999")
            for i in range(6)
        ]

        bot_client = MagicMock()
        bot_client.download_media = AsyncMock(side_effect=fake_download)
        bot_client.send_media_group = AsyncMock(return_value=sent_messages)

        with patch("private_channel_harvester._download_media_unified", side_effect=fake_download),              patch("private_channel_harvester.get_config_value") as mock_cfg:
            cfg_map = {
                "FORWARD_REBRAND_ENABLED": True,
                "FORWARD_CLEAN_FILENAMES": True,
                "FORWARD_TARGET_CHANNEL": "@my_channel",
                "FORWARD_CHANNEL_SIGNATURE": "📢 来源: {channel}",
                "FORWARD_CUSTOM_REPLACE_RULES": "",
            }
            mock_cfg.side_effect = lambda k, default=None: cfg_map.get(k, default)

            results = await harvest_media_group(
                album_msgs=album_msgs,
                group_id_str="grp_143210174",
                primary_caption="【清纯学妹】性爱视频流出！关注 @ad_other",
                bot_client=bot_client,
                bin_channel=-100123456,
                rebrand_enabled=True,
            )

        self.assertEqual(len(results), 6)
        # 核心断言：必须且仅调用一次 send_media_group，不拆散发送
        bot_client.send_media_group.assert_awaited_once()
        call_kwargs = bot_client.send_media_group.call_args.kwargs
        media_input = call_kwargs["media"]
        self.assertEqual(len(media_input), 6)

        # 验证仅首个媒体项携带主配文，其余媒体项配文为空
        self.assertIn("@my_channel", media_input[0].caption)
        self.assertNotIn("@ad_other", media_input[0].caption)
        for sub_inp in media_input[1:]:
            self.assertEqual(sub_inp.caption, "")

        # 验证第 6 个成员为视频且开启 supports_streaming
        self.assertTrue(getattr(media_input[5], "supports_streaming", False))

        # 验证全部 6 个媒体入库时绑定统一的 media_group_id
        for res in results:
            self.assertEqual(res["media_group_id"], "tg_native_mg_999")
            self.assertEqual(res["mode"], "restricted_relay")

        self.assertEqual(mock_save.call_count, 6)

        # 验证所有本地临时文件与子目录在发送完成后被彻底清理
        for fpath in created_files:
            self.assertFalse(os.path.exists(fpath))

    async def test_download_media_concurrent_multibot_striping(self):
        from private_channel_harvester import download_media_concurrent_multibot
        from types import SimpleNamespace

        # 模拟 10MB 视频文件 (10 个 1MB 分片)
        file_size = 10 * 1024 * 1024
        msg = DummyMessage(
            msg_id=777,
            video=DummyVideo(file_name="large.mp4"),
        )
        msg.video.file_size = file_size
        msg.video.file_id = "dummy_fid_dc5"

        temp_dir = tempfile.mkdtemp()
        dest_path = os.path.join(temp_dir, "test_large.mp4")

        # 模拟 3 个 Worker Bot
        mock_bot1 = MagicMock()
        mock_bot2 = MagicMock()
        mock_bot3 = MagicMock()

        for b in (mock_bot1, mock_bot2, mock_bot3):
            b.is_connected = True
            b.get_messages = AsyncMock(return_value=msg)

        async def fake_try_chunk(client, idx, fid, loc, offset, chunk_size, **kwargs):
            # 返回带有固定模式的 1MB 分片
            part_no = offset // chunk_size
            chunk_bytes = bytes([part_no % 256]) * chunk_size
            return True, SimpleNamespace(bytes=chunk_bytes), client, None

        with patch("WebStreamer.bot.multi_clients", {1: mock_bot1, 2: mock_bot2, 3: mock_bot3}),              patch("WebStreamer.bot.work_loads", {1: 0, 2: 0, 3: 0}),              patch("WebStreamer.utils.custom_dl.ByteStreamer._try_get_file_chunk", side_effect=fake_try_chunk),              patch("WebStreamer.utils.custom_dl.ByteStreamer.get_location", return_value=SimpleNamespace()),              patch("private_channel_harvester._fetch_single_msg", return_value=msg):

            res = await download_media_concurrent_multibot(
                msg=msg,
                chat_target="COSAVMY",
                temp_file_path=dest_path,
                chunk_size=1024 * 1024,
            )

        self.assertEqual(res, dest_path)
        self.assertTrue(os.path.exists(dest_path))
        self.assertEqual(os.path.getsize(dest_path), file_size)

        # 验证文件分片内容按 offset 正确写入
        with open(dest_path, "rb") as f:
            for p in range(10):
                f.seek(p * 1024 * 1024)
                data = f.read(1024 * 1024)
                self.assertEqual(data[0], p % 256)
                self.assertEqual(data[-1], p % 256)

        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_clean_drive_filename_removes_site_watermarks(self):
        from WebStreamer.utils.rebrand_cleaner import clean_drive_filename

        raw = "全网最美学生妹泄密！云南交通职业技术学院_郑悦怡_身材苗条_胸挺大屁股_无毛一线天_性爱自拍全流出！_17黑料网.mp4"
        cleaned = clean_drive_filename(raw)
        self.assertNotIn("17黑料网", cleaned)
        self.assertTrue(cleaned.endswith(".mp4"))
        self.assertIn("郑悦怡", cleaned)

    def test_get_write_bot_client_prefers_dc1_over_dc5(self):
        """验证当多个机器人拥有写权限时，调度器自动优选 DC1 (低时延 67ms) 写节点"""
        from private_channel_harvester import get_write_bot_client

        bot_dc5 = MagicMock()
        bot_dc5.is_connected = True
        bot_dc1 = MagicMock()
        bot_dc1.is_connected = True

        multi = {0: bot_dc5, 1: bot_dc1}
        write_clients = {0, 1}
        workloads = {0: 0, 1: 0}
        runtime = {
            0: {"home_dc": 5},
            1: {"home_dc": 1},
        }

        with patch("WebStreamer.bot.multi_clients", multi), \
             patch("WebStreamer.bot.channel_write_clients", write_clients), \
             patch("WebStreamer.bot.work_loads", workloads), \
             patch("WebStreamer.bot.bot_runtime", runtime):
            chosen = get_write_bot_client()
            self.assertIs(chosen, bot_dc1)

    async def test_harvest_media_group_parallel_preupload(self):
        """验证相册媒体组在发布前，整组全部文件均被并发预上传至 Telegram 云端"""
        from private_channel_harvester import harvest_media_group

        album_msgs = [
            DummyMessage(msg_id=2001, photo=DummyPhoto(file_name="p1.jpg"), has_protected_content=True, grouped_id="g1"),
            DummyMessage(msg_id=2002, photo=DummyPhoto(file_name="p2.jpg"), has_protected_content=True, grouped_id="g1"),
            DummyMessage(msg_id=2003, video=DummyVideo(file_name="v1.mp4", duration=60), has_protected_content=True, grouped_id="g1"),
        ]

        async def fake_download(msg, temp_file_path, **kwargs):
            os.makedirs(os.path.dirname(temp_file_path), exist_ok=True)
            with open(temp_file_path, "wb") as f:
                f.write(b"data_" + str(msg.id).encode())
            return temp_file_path

        preuploaded_files = []
        async def fake_save_file(path, **kwargs):
            preuploaded_files.append(path)
            return raw.types.InputFileBig(id=9988, parts=2, name=os.path.basename(path))

        sent_msgs = [
            DummyMessage(msg_id=3001, grouped_id="tg_g1"),
            DummyMessage(msg_id=3002, grouped_id="tg_g1"),
            DummyMessage(msg_id=3003, grouped_id="tg_g1"),
        ]

        bot = MagicMock()
        bot.download_media = AsyncMock(side_effect=fake_download)
        bot.save_file = AsyncMock(side_effect=fake_save_file)
        bot.send_media_group = AsyncMock(return_value=sent_msgs)

        with patch("private_channel_harvester._download_media_unified", side_effect=fake_download), \
             patch("private_channel_harvester.db.save_tg_media", return_value="fuid_123"):
            results = await harvest_media_group(
                album_msgs=album_msgs,
                group_id_str="g1",
                bot_client=bot,
                bin_channel=-10099999,
            )

        self.assertEqual(len(results), 3)
        # 验证 3 个相册媒体文件均触发了并发预上传
        self.assertGreaterEqual(len(preuploaded_files), 3)
        bot.send_media_group.assert_awaited_once()


    async def test_download_media_concurrent_multibot_no_deadlock_on_all_failures(self):
        """验证当所有 Worker 分片拉取均失败时，多 Bot 并发下载绝不死锁挂起，而是快速抛出异常并清理临时文件"""
        from private_channel_harvester import download_media_concurrent_multibot

        bots = {i: MagicMock() for i in range(10)}
        for b in bots.values():
            b.is_connected = True
            b.get_messages = AsyncMock()

        streamer = MagicMock()
        # 模拟所有分片拉取失败
        streamer._try_get_file_chunk = AsyncMock(return_value=(False, None, bots[0], None))

        file_size = 10 * 1024 * 1024
        msg = DummyMessage(
            msg_id=7788,
            video=DummyVideo(file_name="fail_video.mp4"),
        )
        msg.video.file_size = file_size
        msg.video.file_id = "dummy_fid_fail"

        tmp_dir = tempfile.mkdtemp()
        tmp_path = os.path.join(tmp_dir, "fail_video.mp4")

        with patch("WebStreamer.bot.multi_clients", bots),              patch("WebStreamer.bot.work_loads", {i: 0 for i in range(10)}),              patch("private_channel_harvester.is_client_ready", return_value=True),              patch("private_channel_harvester.ByteStreamer.for_client", return_value=streamer),              patch("private_channel_harvester._fetch_single_msg", return_value=msg),              patch("private_channel_harvester.ByteStreamer.get_location", new_callable=AsyncMock) as mock_loc:
            mock_loc.return_value = MagicMock()

            with self.assertRaises(RuntimeError):
                await asyncio.wait_for(
                    download_media_concurrent_multibot(
                        msg=msg,
                        chat_target="COSAVMY",
                        temp_file_path=tmp_path,
                        chunk_size=1024 * 1024,
                    ),
                    timeout=5.0,  # 确保 5 秒内绝不死锁
                )

            # 验证失败后未完整下载的空洞临时文件已被清理
            self.assertFalse(os.path.exists(tmp_path))
            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def test_try_get_file_chunk_executes_even_if_max_retries_zero(self):
        """验证 _try_get_file_chunk 在传入 max_retries=0 时仍至少执行 1 次请求而非直接跳出"""
        from WebStreamer.utils.custom_dl import ByteStreamer
        client = MagicMock()
        streamer = ByteStreamer(client)

        invoke_count = 0
        async def mock_invoke(req):
            nonlocal invoke_count
            invoke_count += 1
            res = MagicMock()
            res.bytes = b'x' * 1024
            return res

        mock_session = MagicMock()
        mock_session.invoke = AsyncMock(side_effect=mock_invoke)
        streamer.generate_media_session = AsyncMock(return_value=mock_session)

        fid = MagicMock()
        fid.file_type = 1
        fid.dc_id = 4
        loc = MagicMock()

        ok, r, _, _ = await streamer._try_get_file_chunk(
            client=client,
            client_index=0,
            file_id=fid,
            location=loc,
            offset=0,
            chunk_size=1024,
            max_retries=0,  # 即使传入 0
            timeout=2.0,
        )

        self.assertTrue(ok)
        self.assertEqual(invoke_count, 1)
