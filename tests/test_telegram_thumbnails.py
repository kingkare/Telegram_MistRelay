import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

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
    pyrogram_file_id = types.ModuleType("pyrogram.file_id")
    pyrogram_file_id.FileId = SimpleNamespace(decode=lambda _value: SimpleNamespace(file_type=None))
    sys.modules["pyrogram"] = pyrogram_module
    sys.modules["pyrogram.file_id"] = pyrogram_file_id

    webstreamer = types.ModuleType("WebStreamer")
    webstreamer.Var = SimpleNamespace(HASH_LENGTH=6, BIN_CHANNEL=-100, MULTI_CLIENT=False, URL="")
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


class TelegramThumbnailTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.routes = load_stream_routes()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mistrelay_thumb_cache_", dir="/tmp")

        import thumbnail_generator

        thumbnail_generator._thumbnail_generator = thumbnail_generator.ThumbnailGenerator(
            cache_dir=str(Path(self.temp_dir.name) / "cache"),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_build_thumbnail_url_for_media_and_album(self):
        build_url = self.routes.build_telegram_thumbnail_url

        self.assertEqual(
            build_url({"entry_type": "file", "message_id": 10, "mime_type": "image/png"}),
            "/api/telegram/thumbnail/10",
        )
        self.assertEqual(
            build_url({"entry_type": "file", "message_id": 11, "mime_type": "video/mp4"}),
            "/api/telegram/thumbnail/11",
        )
        self.assertEqual(
            build_url({
                "entry_type": "folder",
                "message_id": 12,
                "group_mime_types": ["application/pdf", "image/jpeg"],
            }),
            "/api/telegram/thumbnail/12",
        )
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


if __name__ == "__main__":
    unittest.main()
