import tests  # noqa: F401
import asyncio
import importlib.util
import os
import shutil
import sys
import tempfile
import time
import types
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import cache_manager


def get_stream_routes_module():
    root = Path(__file__).resolve().parents[1]

    aiohttp_module = types.ModuleType("aiohttp")
    web_module = types.ModuleType("aiohttp.web")

    class Response:
        def __init__(self, *, status=200, body=None, text=None, headers=None):
            self.status = status
            self.body = body
            self.text = text
            self.headers = headers or {}

    class FileResponse(Response):
        def __init__(self, path, *, headers=None):
            super().__init__(status=200, headers=headers)
            self.path = Path(path)

    class RouteTableDef:
        def get(self, *_args, **_kwargs):
            return lambda func: func

        def post(self, *_args, **_kwargs):
            return lambda func: func

        def put(self, *_args, **_kwargs):
            return lambda func: func

        def delete(self, *_args, **_kwargs):
            return lambda func: func

    class HTTPException(Exception):
        pass

    web_module.RouteTableDef = RouteTableDef
    web_module.Response = Response
    web_module.FileResponse = FileResponse
    web_module.WebSocketResponse = Response
    web_module.StreamResponse = Response
    web_module.Request = object
    web_module.HTTPException = HTTPException
    web_module.HTTPNotFound = HTTPException
    web_module.HTTPForbidden = HTTPException
    web_module.HTTPInternalServerError = HTTPException
    web_module.json_response = lambda data, status=200: Response(status=status, body=data)
    web_module.middleware = lambda func: func
    aiohttp_module.web = web_module
    sys.modules["aiohttp"] = aiohttp_module
    sys.modules["aiohttp.web"] = web_module

    http_exceptions = types.ModuleType("aiohttp.http_exceptions")
    http_exceptions.BadStatusLine = HTTPException
    sys.modules["aiohttp.http_exceptions"] = http_exceptions

    if "pyrogram" not in sys.modules:
        pyrogram_module = types.ModuleType("pyrogram")
        pyrogram_module.__path__ = []
        pyrogram_module.Client = object
        pyrogram_file_id = types.ModuleType("pyrogram.file_id")
        pyrogram_file_id.FileId = SimpleNamespace(decode=lambda _value: SimpleNamespace(file_type=None))
        pyrogram_types = types.ModuleType("pyrogram.types")
        pyrogram_types.Message = SimpleNamespace
        pyrogram_types.Chat = SimpleNamespace
        pyrogram_types.User = SimpleNamespace
        pyrogram_module.types = pyrogram_types
        sys.modules["pyrogram"] = pyrogram_module
        sys.modules["pyrogram.file_id"] = pyrogram_file_id
        sys.modules["pyrogram.types"] = pyrogram_types

    webstreamer = types.ModuleType("WebStreamer")
    webstreamer.Var = SimpleNamespace(HASH_LENGTH=32, BIN_CHANNEL=-100, MULTI_CLIENT=False, URL="")
    webstreamer.utils = SimpleNamespace(
        get_hash=lambda value, length: str(value)[:length].ljust(length, "0"),
        ByteStreamer=lambda client: client,
        get_readable_time=lambda _seconds: "0s",
    )
    webstreamer.StartTime = 0
    webstreamer.__version__ = "test"
    webstreamer.StreamBot = None
    sys.modules["WebStreamer"] = webstreamer

    if "WebStreamer.bot" not in sys.modules:
        bot_module = types.ModuleType("WebStreamer.bot")
        bot_module.multi_clients = {}
        bot_module.work_loads = {}
        bot_module.channel_accessible_clients = set()
        bot_module.channel_write_clients = set()
        bot_module.bot_channel_modes = {}
        bot_module.channel_public_handle = None
        bot_module.select_stream_bot = lambda **_kwargs: None
        bot_module.get_available_channel_bot_count = lambda: 1
        bot_module.get_bot_runtime_snapshot = lambda: {}
        bot_module.mark_bot_failure = lambda *_args, **_kwargs: None
        bot_module.mark_bot_success = lambda *_args, **_kwargs: None
        sys.modules["WebStreamer.bot"] = bot_module

    server_module = types.ModuleType("WebStreamer.server")
    sys.modules["WebStreamer.server"] = server_module

    exceptions_module = types.ModuleType("WebStreamer.server.exceptions")

    class FIleNotFound(Exception):
        message = "not found"

    class InvalidHash(Exception):
        message = "invalid hash"

    exceptions_module.FIleNotFound = FIleNotFound
    exceptions_module.InvalidHash = InvalidHash
    sys.modules["WebStreamer.server.exceptions"] = exceptions_module

    ws_module = types.ModuleType("WebStreamer.server.ws_manager")
    ws_module.ws_manager = SimpleNamespace()
    sys.modules["WebStreamer.server.ws_manager"] = ws_module

    if "WebStreamer.bot.clients" not in sys.modules:
        clients_module = types.ModuleType("WebStreamer.bot.clients")
        clients_module.StreamBot = None
        sys.modules["WebStreamer.bot.clients"] = clients_module

    module_name = "test_cache_stream_routes"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(
        module_name,
        root / "WebStreamer" / "server" / "stream_routes.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class TestCacheManager(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="mistrelay_cache_test_")
        self.test_path = Path(self.test_dir)
        self.thumb_dir = self.test_path / "cache" / "thumbnails"
        self.thumb_dir.mkdir(parents=True)
        self.down_dir = self.test_path / "downloads"
        self.down_dir.mkdir(parents=True)
        self.rclone_dir = self.test_path / "cache" / "rclone"
        self.rclone_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_disk_stats(self):
        stats = cache_manager.get_disk_stats()
        self.assertIn("total_bytes", stats)
        self.assertIn("free_bytes", stats)
        self.assertIn("percent", stats)
        self.assertGreaterEqual(stats["total_bytes"], 0)

    def test_thumbnail_stats_and_cleaning(self):
        # Create sub sources in thumbnails
        tg_sub = self.thumb_dir / "telegram"
        tg_sub.mkdir()
        od_sub = self.thumb_dir / "onedrive"
        od_sub.mkdir()

        # Create recent file in telegram
        recent_file = tg_sub / "recent.webp"
        recent_file.write_bytes(b"x" * 1024)

        # Create expired file in onedrive
        expired_file = od_sub / "old.webp"
        expired_file.write_bytes(b"y" * 2048)
        old_time = (datetime.now() - timedelta(days=10)).timestamp()
        os.utime(expired_file, (old_time, old_time))

        mock_tg = MagicMock()
        mock_tg.cache_dir = self.thumb_dir
        mock_tg._get_cached_path = MagicMock()

        with patch("cache_manager.get_thumbnail_generator", return_value=mock_tg):
            # Test stats
            stats = cache_manager.get_thumbnail_stats()
            self.assertEqual(stats["total_files"], 2)
            self.assertEqual(stats["total_bytes"], 3072)
            self.assertEqual(stats["expired_files"], 1)
            self.assertIn("telegram", stats["sub_sources"])
            self.assertIn("onedrive", stats["sub_sources"])

            # Test dry_run clean of expired
            dry_res = cache_manager.clean_thumbnails(retention_days=7, dry_run=True)
            self.assertEqual(dry_res["deleted_files"], 1)
            self.assertEqual(dry_res["deleted_bytes"], 2048)
            self.assertTrue(expired_file.exists())
            self.assertTrue(recent_file.exists())

            # Test actual clean of expired
            clean_res = cache_manager.clean_thumbnails(retention_days=7, dry_run=False)
            self.assertEqual(clean_res["deleted_files"], 1)
            self.assertFalse(expired_file.exists())
            self.assertTrue(recent_file.exists())

            # Test purge_all
            purge_res = cache_manager.clean_thumbnails(purge_all=True, dry_run=False)
            self.assertEqual(purge_res["deleted_files"], 1)
            self.assertFalse(recent_file.exists())

    def test_thumbnail_sub_source_path_security(self):
        mock_tg = MagicMock()
        mock_tg.cache_dir = self.thumb_dir

        with patch("cache_manager.get_thumbnail_generator", return_value=mock_tg):
            with self.assertRaises(ValueError):
                cache_manager.clean_thumbnails(sub_source="../outside")
            with self.assertRaises(ValueError):
                cache_manager.clean_thumbnails(sub_source="foo/bar")

    async def test_downloads_stats_and_cleaning(self):
        # Create files in downloads
        active_file = self.down_dir / "active.mp4"
        active_file.write_bytes(b"a" * 1000)

        expired_file = self.down_dir / "old_temp.bin"
        expired_file.write_bytes(b"b" * 2000)

        # Mock age function so active_file is recent and expired_file is old
        def mock_age(path, now):
            if path.name == "old_temp.bin":
                return 48 * 3600  # 48 hours old (> 24 hours)
            return 1 * 3600       # 1 hour old

        with patch("cache_manager.resolve_downloads_dir", return_value=self.down_dir), \
             patch("download_cleanup._resolve_download_dir", return_value=self.down_dir), \
             patch("cache_manager._path_age_seconds", side_effect=mock_age), \
             patch("download_cleanup._path_age_seconds", side_effect=mock_age), \
             patch("cache_manager._collect_database_protected_paths", return_value={active_file.resolve()}), \
             patch("download_cleanup._collect_database_protected_paths", return_value={active_file.resolve()}):

            stats = await cache_manager.get_downloads_stats(aria2_client=None)
            self.assertEqual(stats["total_files"], 2)
            self.assertEqual(stats["protected_files"], 1)
            self.assertEqual(stats["cleanable_files"], 1)
            self.assertEqual(stats["cleanable_bytes"], 2000)

            # Clean downloads with dry_run
            dry_res = await cache_manager.clean_downloads(
                aria2_client=None,
                retention_hours=24,
                dry_run=True,
            )
            self.assertEqual(dry_res["deleted_files"], 1)
            self.assertTrue(expired_file.exists())
            self.assertTrue(active_file.exists())

            # Clean downloads actual
            clean_res = await cache_manager.clean_downloads(
                aria2_client=None,
                retention_hours=24,
                dry_run=False,
            )
            self.assertEqual(clean_res["deleted_files"], 1)
            self.assertFalse(expired_file.exists())
            self.assertTrue(active_file.exists())

    def test_rclone_cleaning(self):
        cache_file = self.rclone_dir / "chunk.bin"
        cache_file.write_bytes(b"r" * 500)

        with patch("cache_manager.resolve_rclone_dir", return_value=self.rclone_dir):
            stats = cache_manager.get_rclone_stats()
            self.assertEqual(stats["total_files"], 1)
            self.assertEqual(stats["total_bytes"], 500)

            dry_res = cache_manager.clean_rclone(dry_run=True)
            self.assertEqual(dry_res["deleted_files"], 1)
            self.assertTrue(cache_file.exists())

            clean_res = cache_manager.clean_rclone(dry_run=False)
            self.assertEqual(clean_res["deleted_files"], 1)
            self.assertFalse(cache_file.exists())

    def test_clean_memory(self):
        mock_tg = MagicMock()
        mock_tg._get_cached_path = MagicMock()
        with patch("cache_manager.get_thumbnail_generator", return_value=mock_tg):
            res = cache_manager.clean_memory()
            self.assertEqual(res["status"], "cleared")
            mock_tg._get_cached_path.cache_clear.assert_called_once()

    async def test_clean_cache_category_all(self):
        with patch("cache_manager.clean_thumbnails", return_value={"deleted_files": 2, "deleted_bytes": 100}), \
             patch("cache_manager.clean_downloads", new_callable=AsyncMock) as mock_down, \
             patch("cache_manager.clean_rclone", return_value={"deleted_files": 1, "deleted_bytes": 50}), \
             patch("cache_manager.clean_memory", return_value={"status": "cleared"}):

            mock_down.return_value = {"deleted_files": 3, "deleted_bytes": 200}

            res = await cache_manager.clean_cache_category("all", dry_run=False)
            self.assertEqual(res["deleted_files"], 6)
            self.assertEqual(res["deleted_bytes"], 350)
            self.assertIn("thumbnails", res["details"])
            self.assertIn("downloads", res["details"])

    def test_policy_read_write(self):
        with patch("db.set_configs") as mock_set, patch("configer.reload_config"):
            updated = cache_manager.update_cache_policy({
                "DOWNLOAD_CLEANUP_ENABLED": True,
                "DOWNLOAD_RETENTION_HOURS": 48,
                "DOWNLOAD_CLEANUP_INTERVAL_SECONDS": 7200,
                "THUMBNAIL_CACHE_MAX_AGE_DAYS": 14,
            })
            self.assertTrue(mock_set.called)
            self.assertIn("DOWNLOAD_CLEANUP_ENABLED", updated)


class MockRequest:
    def __init__(self, user=None, json_data=None):
        self._user = user
        self._json_data = json_data or {}

    def get(self, key, default=None):
        if key == "user":
            return self._user
        return default

    async def json(self):
        return self._json_data


class TestCacheApiHandlers(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved_modules = dict(sys.modules)
        cls.stream_routes = get_stream_routes_module()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_saved_modules"):
            for k in list(sys.modules.keys()):
                if k not in cls._saved_modules:
                    sys.modules.pop(k, None)
            sys.modules.update(cls._saved_modules)

    async def test_handlers_require_admin(self):
        non_admin_req = MockRequest(user={"role": "user"})

        res = await self.stream_routes.cache_stats_handler(non_admin_req)
        self.assertEqual(res.status, 403)

        res = await self.stream_routes.cache_clean_handler(non_admin_req)
        self.assertEqual(res.status, 403)

        res = await self.stream_routes.cache_policy_get_handler(non_admin_req)
        self.assertEqual(res.status, 403)

        res = await self.stream_routes.cache_policy_update_handler(non_admin_req)
        self.assertEqual(res.status, 403)

    async def test_admin_access_allowed(self):
        admin_req = MockRequest(user={"role": "admin"}, json_data={"category": "memory"})

        with patch("cache_manager.get_all_cache_stats", new_callable=AsyncMock) as mock_stats:
            mock_stats.return_value = {"total_cache_bytes": 0}
            res = await self.stream_routes.cache_stats_handler(admin_req)
            self.assertEqual(res.status, 200)

        with patch("cache_manager.clean_cache_category", new_callable=AsyncMock) as mock_clean:
            mock_clean.return_value = {"status": "cleared"}
            res = await self.stream_routes.cache_clean_handler(admin_req)
            self.assertEqual(res.status, 200)

        with patch("cache_manager.get_cache_policy", return_value={"retention": 24}):
            res = await self.stream_routes.cache_policy_get_handler(admin_req)
            self.assertEqual(res.status, 200)

        with patch("cache_manager.update_cache_policy", return_value={"retention": 48}):
            admin_update_req = MockRequest(user={"role": "admin"}, json_data={"DOWNLOAD_RETENTION_HOURS": 48})
            res = await self.stream_routes.cache_policy_update_handler(admin_update_req)
            self.assertEqual(res.status, 200)


if __name__ == "__main__":
    unittest.main()
