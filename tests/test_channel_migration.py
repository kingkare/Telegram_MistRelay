import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import db
import channel_migrator


class ChannelMigrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        if os.path.exists(self._tmp.name):
            os.unlink(self._tmp.name)

    def test_creator_account_health_status_in_list_users(self):
        acc_ok = db.upsert_protocol_account(
            phone="12025550101",
            session_data="sess_ok",
            status="active",
        )
        acc_bad = db.upsert_protocol_account(
            phone="12025550199",
            session_data="sess_bad",
            status="invalid",
        )

        db.create_tenant_user(
            username="healthy_tenant",
            password_hash="h1",
            dc_id=5,
            bin_channel_id=-1001110001,
            bin_channel_username="mr_healthy",
            creator_account_id=acc_ok["id"],
        )
        db.create_tenant_user(
            username="warning_tenant",
            password_hash="h2",
            dc_id=5,
            bin_channel_id=-1001110002,
            bin_channel_username="mr_warning",
            creator_account_id=acc_bad["id"],
        )

        users_map = {u["username"]: u for u in db.list_users()}
        self.assertEqual(users_map["healthy_tenant"]["creator_status"], "healthy")
        self.assertEqual(users_map["warning_tenant"]["creator_status"], "warning")

    async def test_lossless_channel_migration_workflow(self):
        old_cid = -100111222333
        new_cid = -100999888777

        tenant = db.create_tenant_user(
            username="mig_user",
            password_hash="hash_mig",
            dc_id=5,
            bin_channel_id=old_cid,
            bin_channel_username="mr_old_chan",
        )
        dl_id = db.create_download(
            file_unique_id="aria2_mig_1",
            gid="gid_mig_1",
            source_url="https://example.com/v.mp4",
            user_id=tenant["id"],
            target_channel_id=old_cid,
        )

        # Insert 5 media records in old channel
        for idx in range(1, 6):
            msg = SimpleNamespace(
                id=100 + idx,
                chat=SimpleNamespace(id=old_cid),
                video=SimpleNamespace(
                    file_unique_id=f"uniq_mig_{idx}",
                    file_id=f"old_fid_{idx}",
                    file_name=f"episode_{idx}.mp4",
                    mime_type="video/mp4",
                    file_size=1024 * 1024 * idx,
                ),
                date="2026-09-28T01:00:00",
            )
            db.save_tg_media(msg)

        mock_bot = SimpleNamespace(
            is_connected=True,
            username="MistRelayMasterBot",
            get_chat=AsyncMock(return_value=SimpleNamespace(id=new_cid)),
            copy_message=AsyncMock(
                side_effect=lambda chat_id, from_chat_id, message_id: SimpleNamespace(
                    id=message_id + 1900,
                    video=SimpleNamespace(file_id=f"new_fid_{message_id + 1900}"),
                )
            ),
        )

        mock_provision = AsyncMock(
            return_value={
                "dc_id": 5,
                "bin_channel_id": new_cid,
                "bin_channel_username": "mr_new_chan",
                "creator_account_id": 42,
            }
        )

        mgr = channel_migrator.ChannelMigrationManager()
        with patch("botfather_creator.provision_user_storage_channel", mock_provision), patch(
            "WebStreamer.bot.StreamBot", mock_bot
        ):
            status_dict = await mgr.start_migration(user_id=tenant["id"], target_dc_id=5)
            self.assertIn(status_dict["status"], ("pending", "running", "completed"))

            # Wait for background task to complete
            async_task = mgr._running_async_tasks.get(tenant["id"])
            if async_task:
                await asyncio.wait_for(async_task, timeout=10.0)

        final_task = mgr.get_task(tenant["id"])
        self.assertIsNotNone(final_task)
        self.assertEqual(final_task.status, "completed")
        self.assertEqual(final_task.total_files, 5)
        self.assertEqual(final_task.migrated_files, 5)
        self.assertEqual(final_task.skipped_files, 0)
        self.assertEqual(final_task.progress_percent, 100.0)

        # Verify user's bin_channel_id and bin_channel_username are updated
        updated_user = db.get_user_by_id(tenant["id"])
        self.assertEqual(updated_user["bin_channel_id"], new_cid)
        self.assertEqual(updated_user["bin_channel_username"], "mr_new_chan")

        # Verify all 5 media records now point to new_cid and new message IDs (2001..2005)
        old_records = db.fetch_channel_media_records(old_cid)
        self.assertEqual(len(old_records), 0)

        new_records = db.fetch_channel_media_records(new_cid)
        self.assertEqual(len(new_records), 5)
        self.assertEqual([r["message_id"] for r in new_records], [2001, 2002, 2003, 2004, 2005])
        self.assertEqual(new_records[0]["file_id"], "new_fid_2001")

        # Verify download target_channel_id was updated
        dl = db.get_download_by_id(dl_id)
        self.assertEqual(dl["target_channel_id"], new_cid)


if __name__ == "__main__":
    unittest.main()
