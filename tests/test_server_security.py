import tests  # noqa: F401
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

def load_server_module():
    root = Path(__file__).resolve().parents[1]

    aiohttp_module = types.ModuleType("aiohttp")
    web = types.ModuleType("aiohttp.web")

    class StreamResponse:
        def __init__(self, *, status=200, body=None, text=None, headers=None):
            self.status = status
            self.body = body
            self.text = text
            self.headers = headers or {}

    class Response(StreamResponse):
        pass

    class FileResponse(StreamResponse):
        content_type = None

    class WebSocketResponse(StreamResponse):
        pass

    class HTTPException(Exception):
        pass

    class RouteTableDef(list):
        def get(self, *_args, **_kwargs):
            return lambda func: func
        def post(self, *_args, **_kwargs):
            return lambda func: func
        def put(self, *_args, **_kwargs):
            return lambda func: func
        def delete(self, *_args, **_kwargs):
            return lambda func: func

    web.StreamResponse = StreamResponse
    web.Response = Response
    web.FileResponse = FileResponse
    web.WebSocketResponse = WebSocketResponse
    web.HTTPException = HTTPException
    web.Request = object
    web.Application = object
    web.RouteTableDef = RouteTableDef
    web.middleware = lambda function: function
    def _mock_json_resp(body, status=200):
        import json
        text_val = json.dumps(body, ensure_ascii=False) if isinstance(body, (dict, list)) else (str(body) if body is not None else None)
        return Response(status=status, body=body, text=text_val)

    web.json_response = _mock_json_resp
    aiohttp_module.web = web
    http_exceptions = types.ModuleType("aiohttp.http_exceptions")
    http_exceptions.BadStatusLine = HTTPException
    http_exceptions.BadHttpMessage = HTTPException
    sys.modules["aiohttp"] = aiohttp_module
    sys.modules["aiohttp.web"] = web
    sys.modules["aiohttp.http_exceptions"] = http_exceptions

    package = types.ModuleType("security_test_webstreamer")
    package.__path__ = [str(root / "WebStreamer")]
    routes_module = types.ModuleType("security_test_webstreamer.server.stream_routes")
    routes_module.routes = web.RouteTableDef()
    sys.modules[package.__name__] = package
    sys.modules[routes_module.__name__] = routes_module
    module_name = "security_test_webstreamer.server"
    spec = importlib.util.spec_from_file_location(
        module_name,
        root / "WebStreamer" / "server" / "__init__.py",
        submodule_search_locations=[str(root / "WebStreamer" / "server")],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


server = load_server_module()
web = sys.modules["aiohttp.web"]


class ServerSecurityTests(unittest.IsolatedAsyncioTestCase):
    def test_same_origin_and_dev_origins_only(self):
        request = SimpleNamespace(host="files.example.com")
        self.assertTrue(server._is_allowed_origin(request, "https://files.example.com"))
        self.assertTrue(server._is_allowed_origin(request, "http://localhost:5173"))
        self.assertFalse(server._is_allowed_origin(request, "https://attacker.example"))

    def test_websocket_bearer_is_scoped_to_subprotocol(self):
        request = SimpleNamespace(headers={
            "Upgrade": "websocket",
            "Sec-WebSocket-Protocol": "mistrelay.v1, mistrelay.jwt.test-token",
        })
        self.assertEqual(
            server._websocket_token(request),
            ("test-token", "mistrelay.jwt.test-token"),
        )

    async def test_websocket_response_headers_are_not_mutated_after_prepare(self):
        websocket = web.WebSocketResponse()

        async def handler(_request):
            return websocket

        request = SimpleNamespace(method="GET", path="/api/ws", headers={}, host="localhost")
        self.assertIs(
            await server.security_headers_middleware(request, handler),
            websocket,
        )
        self.assertIs(await server.cors_middleware(request, handler), websocket)

    async def test_cross_origin_request_is_rejected_before_handler(self):
        handler_called = False

        async def handler(_request):
            nonlocal handler_called
            handler_called = True
            return web.Response()

        request = SimpleNamespace(
            method="GET",
            path="/api/status",
            host="files.example.com",
            headers={"Origin": "https://attacker.example"},
        )
        response = await server.cors_middleware(request, handler)
        self.assertEqual(response.status, 403)
        self.assertFalse(handler_called)


if __name__ == "__main__":
    unittest.main()
