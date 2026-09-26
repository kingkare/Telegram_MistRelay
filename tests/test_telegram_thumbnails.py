import tests  # noqa: F401
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image

os.environ["MISTRELAY_DB_PATH"] = tempfile.mktemp(
    prefix="mistrelay_thumb_tests_",
    suffix=".db",
    dir="/tmp",
)


def load_stream_routes():
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

    pyrogram_module = types.ModuleType("pyrogram")
    pyrogram_module.__path__ = []
    pyrogram_file_id = types.ModuleType("pyrogram.file_id")
    pyrogram_file_id.FileId = SimpleNamespace(decode=lambda _value: SimpleNamespace(file_type=None))
    pyrogram_types = types.ModuleType("pyrogram.types")
    pyrogram_types.Message = SimpleNamespace
    pyrogram_types.Chat = SimpleNamespace
    pyrogram_types.User = SimpleNamespace
    pyrogram_enums = types.ModuleType("pyrogram.enums")
    pyrogram_enums.ChatType = SimpleNamespace(CHANNEL="channel", SUPERGROUP="supergroup", GROUP="group")
    pyrogram_enums.ParseMode = SimpleNamespace(HTML="html", MARKDOWN="markdown")
    sys.modules["pyrogram"] = pyrogram_module
    sys.modules["pyrogram.file_id"] = pyrogram_file_id
    sys.modules["pyrogram.types"] = pyrogram_types
    sys.modules["pyrogram.enums"] = pyrogram_enums
    sys.modules["pyrogram.enums.parse_mode"] = SimpleNamespace(ParseMode=pyrogram_enums.ParseMode)

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

    bot_module = types.ModuleType("WebStreamer.bot")
    bot_module.multi_clients = {}
    bot_module.work_loads = {}
    bot_module.channel_accessible_clients = set()
    bot_module.channel_write_clients = set()
    bot_module.bot_channel_modes = {}
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

    clients_module = types.ModuleType("WebStreamer.bot.clients")
    clients_module.StreamBot = None
    sys.modules["WebStreamer.bot.clients"] = clients_module

    sys.modules["configer"] = types.ModuleType("configer")

    module_name = "test_stream_routes"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        root / "WebStreamer" / "server" / "stream_routes.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class FakeRequest(dict):
    def __init__(self, message_id: int, method: str = "GET"):
        super().__init__()
        self.match_info = {"message_id": str(message_id)}
        self.method = method


class FakeJsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class TelegramThumbnailTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved_modules = dict(sys.modules)
        cls.routes = load_stream_routes()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_saved_modules"):
            for k in list(sys.modules.keys()):
                if k not in cls._saved_modules:
                    sys.modules.pop(k, None)
            sys.modules.update(cls._saved_modules)

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mistrelay_thumb_cache_", dir="/tmp")
        from db import init_db
        init_db()

        import thumbnail_generator

        thumbnail_generator._thumbnail_generator = thumbnail_generator.ThumbnailGenerator(
            cache_dir=str(Path(self.temp_dir.name) / "cache"),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_build_thumbnail_url_for_media_and_album(self):
        build_url = self.routes.build_telegram_thumbnail_url

        items = [
            ({"entry_type": "file", "message_id": 10, "mime_type": "image/png"}, 10),
            ({"entry_type": "file", "message_id": 11, "mime_type": "video/mp4"}, 11),
            ({
                "entry_type": "folder",
                "message_id": 12,
                "group_mime_types": ["application/pdf", "image/jpeg"],
            }, 12),
        ]
        from auth import verify_resource_ticket

        for item, message_id in items:
            parsed = urlsplit(build_url(item))
            expected_path = f"/api/telegram/thumbnail/{message_id}"
            self.assertEqual(parsed.path, expected_path)
            ticket = parse_qs(parsed.query)["ticket"][0]
            self.assertTrue(verify_resource_ticket(ticket, expected_path))

        self.assertIsNone(
            build_url({"entry_type": "file", "message_id": 13, "mime_type": "application/pdf"})
        )

    async def test_thumbnail_handler_returns_cache_hit(self):
        import thumbnail_generator

        message_id = 42
        file_name = "cached.png"
        cache_key = f"{message_id}_{file_name}"
        generator = thumbnail_generator.get_thumbnail_generator()
        source_path = Path(self.temp_dir.name) / file_name
        Image.new("RGB", (32, 32), "#2f9e8f").save(source_path)
        cached_path = generator.generate_thumbnail("telegram", cache_key, source_path)
        self.assertIsNotNone(cached_path)

        self.routes.get_tg_media_record_by_message_id = lambda _message_id: {
            "message_id": message_id,
            "file_name": file_name,
            "mime_type": "image/png",
            "file_size": source_path.stat().st_size,
        }

        async def fail_if_called(*_args, **_kwargs):
            raise AssertionError("download should not run for cache hit")

        self.routes.download_telegram_media_sample = fail_if_called

        response = await self.routes.telegram_thumbnail_handler(FakeRequest(message_id))

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get("X-MistRelay-Thumbnail-Cache"), "hit")

    async def test_thumbnail_generation_failure_returns_fallback(self):
        message_id = 43
        self.routes.get_tg_media_record_by_message_id = lambda _message_id: {
            "message_id": message_id,
            "file_name": "broken.png",
            "mime_type": "image/png",
            "file_size": 128,
        }

        async def fail_download(*_args, **_kwargs):
            raise RuntimeError("download failed")

        self.routes.download_telegram_media_sample = fail_download

        response = await self.routes.telegram_thumbnail_handler(FakeRequest(message_id))

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get("Content-Type"), "image/webp")

    async def test_invalid_stream_capability_does_not_call_telegram(self):
        message_id = 44
        self.routes.get_tg_media_record_by_message_id = lambda _message_id: {
            "message_id": message_id,
            "file_unique_id": "telegram-file-unique-id",
        }

        async def fail_if_called(*_args, **_kwargs):
            raise AssertionError("invalid capabilities must be rejected before Telegram")

        self.routes.get_main_bot_file_properties = fail_if_called
        request = FakeRequest(message_id)
        request.headers = {}

        with self.assertRaises(self.routes.InvalidHash):
            await self.routes.media_streamer(request, message_id, "0" * 32)

    async def test_health_requires_completed_startup_and_connected_bot(self):
        from service_runtime import set_service_ready

        set_service_ready(True)
        self.routes.StreamBot = SimpleNamespace(is_connected=False)
        response = await self.routes.api_health_handler(None)
        self.assertEqual(response.status, 503)

        self.routes.StreamBot = SimpleNamespace(is_connected=True)
        response = await self.routes.api_health_handler(None)
        self.assertEqual(response.status, 200)
        set_service_ready(False)

    async def test_docker_logs_fall_back_to_application_log(self):
        request = SimpleNamespace(query={"lines": "2"})
        with patch.object(self.routes, "DOCKER_CONTROL_ENABLED", False), patch.object(
            self.routes,
            "read_log_lines",
            return_value=["first", "second"],
        ):
            response = await self.routes.docker_logs_handler(request)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["source"], "application")
        self.assertEqual(response.body["logs"], "first\nsecond")
        self.assertEqual(response.body["lines"], 2)

    async def test_docker_status_uses_application_self_check_without_socket(self):
        with patch.object(self.routes, "DOCKER_CONTROL_ENABLED", False), patch.object(
            self.routes.os.path,
            "exists",
            return_value=True,
        ), patch.dict(
            self.routes.os.environ,
            {"MISTRELAY_CONTAINER_NAME": "mistrelay-test"},
        ):
            response = await self.routes.docker_status_handler(None)

        self.assertEqual(response.status, 200)
        self.assertTrue(response.body["success"])
        self.assertTrue(response.body["in_docker"])
        self.assertEqual(response.body["container_name"], "mistrelay-test")
        self.assertEqual(response.body["status"], "running")
        self.assertEqual(response.body["status_source"], "application")
        self.assertFalse(response.body["control_enabled"])
        self.assertIn("应用自检", response.body["control_message"])
        self.assertEqual(response.body["application_version"], "vtest")
        self.assertNotIn("error", response.body)

    async def test_config_handler_appends_redacted_multi_bot_tokens(self):
        existing = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        addition = "234567:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        primary = "345678:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"

        class ConfigRequest:
            async def json(self):
                return {"MULTI_BOT_TOKENS": [addition]}

        stored_updates = []

        def fake_get_config(key, default=None):
            return {
                "MULTI_BOT_TOKENS": [existing],
                "BOT_TOKEN": primary,
            }.get(key, default)

        with patch.object(self.routes, "get_config", side_effect=fake_get_config), patch.object(
            self.routes,
            "set_configs",
            side_effect=lambda updates: stored_updates.extend(updates),
        ):
            response = await self.routes.update_config_handler(ConfigRequest())

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["updated_count"], 1)
        self.assertEqual(stored_updates[0][0], "MULTI_BOT_TOKENS")
        self.assertEqual(stored_updates[0][1], [existing, addition])

    async def test_config_handler_reports_secret_count_without_values(self):
        tokens = [
            "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
            "234567:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
        ]
        request = SimpleNamespace(query={"category": "stream"})
        with patch.object(
            self.routes,
            "get_all_configs",
            return_value={"MULTI_BOT_TOKENS": tokens, "ENABLE_STREAM": True},
        ):
            response = await self.routes.get_config_handler(request)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["data"]["MULTI_BOT_TOKENS"], [])
        self.assertEqual(response.body["secret_counts"]["MULTI_BOT_TOKENS"], 2)
        self.assertNotIn("MULTI_BOT_TOKENS", response.body["offline_only_keys"])

    async def test_batch_delete_expands_groups_and_deduplicates_records(self):
        deleted_message_ids = []
        deleted_file_ids = []

        async def fake_delete_messages(message_ids):
            deleted_message_ids.extend(message_ids)
            return {
                "deleted_message_count": len(message_ids),
                "cleanup_only": False,
                "client_index": 0,
            }

        def fake_get_record(message_id):
            if message_id == 101:
                return {"file_unique_id": "file-a", "message_id": 101}
            return None

        def fake_get_group(group_id):
            if group_id != "group-a":
                return []
            return [
                {"file_unique_id": "file-a", "message_id": 101},
                {"file_unique_id": "file-b", "message_id": 102},
            ]

        def fake_cleanup(file_ids):
            deleted_file_ids.extend(file_ids)
            return {
                "deleted_media": len(file_ids),
                "deleted_downloads": 0,
                "deleted_uploads": 0,
            }

        request = FakeJsonRequest({
            "message_ids": [101, 101, 999],
            "media_group_ids": ["group-a", "group-a", "missing-group"],
        })
        with patch.object(
            self.routes,
            "get_tg_media_record_by_message_id",
            side_effect=fake_get_record,
        ), patch.object(
            self.routes,
            "get_tg_media_records_by_media_group",
            side_effect=fake_get_group,
        ), patch.object(
            self.routes,
            "delete_bin_channel_messages",
            side_effect=fake_delete_messages,
        ), patch.object(
            self.routes,
            "delete_tg_media_records",
            side_effect=fake_cleanup,
        ):
            response = await self.routes.telegram_batch_delete_handler(request)

        self.assertEqual(response.status, 200)
        self.assertEqual(deleted_message_ids, [101, 102])
        self.assertEqual(deleted_file_ids, ["file-a", "file-b"])
        self.assertEqual(response.body["data"]["matched_file_count"], 2)
        self.assertEqual(response.body["data"]["missing_message_ids"], [999])
        self.assertEqual(
            response.body["data"]["missing_media_group_ids"],
            ["missing-group"],
        )

    async def test_batch_delete_rejects_empty_or_oversized_selections(self):
        empty_response = await self.routes.telegram_batch_delete_handler(
            FakeJsonRequest({"message_ids": [], "media_group_ids": []})
        )
        self.assertEqual(empty_response.status, 400)

        oversized_response = await self.routes.telegram_batch_delete_handler(
            FakeJsonRequest({
                "message_ids": list(range(1, 202)),
                "media_group_ids": [],
            })
        )
        self.assertEqual(oversized_response.status, 400)
        self.assertIn("200", oversized_response.body["error"])


    async def test_ensure_telegram_thumbnail_cache_flow(self):
        import thumbnail_generator
        message_id = 88
        file_name = "test_flow.jpg"
        source_path = Path(self.temp_dir.name) / file_name
        Image.new("RGB", (32, 32), "#38bdf8").save(source_path)

        self.routes.get_tg_media_record_by_message_id = lambda _mid: {
            "message_id": message_id,
            "file_name": file_name,
            "mime_type": "image/jpeg",
            "file_size": source_path.stat().st_size,
        }

        async def fake_download(_mid, out_path, _max_bytes):
            out_path.write_bytes(source_path.read_bytes())

        self.routes.download_telegram_media_sample = fake_download

        # First call: cache miss
        path1, hit1 = await self.routes.ensure_telegram_thumbnail(message_id)
        self.assertIsNotNone(path1)
        self.assertFalse(hit1)
        self.assertTrue(path1.exists())

        # Second call: cache hit
        path2, hit2 = await self.routes.ensure_telegram_thumbnail(message_id)
        self.assertEqual(path1, path2)
        self.assertTrue(hit2)

    async def test_thumbnail_worker_and_api_endpoints(self):
        import asyncio
        from thumbnail_worker import TelegramThumbnailWorker
        worker = TelegramThumbnailWorker()
        processed = []

        async def mock_ensure(mid):
            processed.append(mid)
            return (Path(self.temp_dir.name) / f"{mid}.webp", False)

        worker.set_ensure_func(mock_ensure)
        worker.enqueue(901)
        worker.enqueue(902)
        # Duplicate enqueue should be skipped
        worker.enqueue(901)

        status = worker.get_status()
        self.assertIn("running", status)
        self.assertIn("total", status)
        self.assertIn("cached", status)
        self.assertIn("pending", status)
        self.assertIn("percent", status)

        await asyncio.sleep(1.2)
        await worker.stop()
        self.assertIn(901, processed)

        # Test GET /api/telegram/thumbnails/status
        status_req = SimpleNamespace()
        status_resp = await self.routes.telegram_thumbnails_status_handler(status_req)
        self.assertEqual(status_resp.status, 200)
        self.assertTrue(status_resp.body["success"])
        self.assertIn("cached", status_resp.body["data"])

        # Test POST /api/telegram/thumbnails/warmup (admin permitted)
        warmup_req = SimpleNamespace(get=lambda k, d=None: {"role": "admin"} if k == "user" else d)
        warmup_resp = await self.routes.telegram_thumbnails_warmup_handler(warmup_req)
        self.assertEqual(warmup_resp.status, 200)
        self.assertTrue(warmup_resp.body["success"])

        # Test POST /api/telegram/thumbnails/warmup (non-admin rejected)
        non_admin_req = SimpleNamespace(get=lambda k, d=None: {"role": "guest"} if k == "user" else d)
        forbidden_resp = await self.routes.telegram_thumbnails_warmup_handler(non_admin_req)
        self.assertEqual(forbidden_resp.status, 403)


if __name__ == "__main__":
    unittest.main()
