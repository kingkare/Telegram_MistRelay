# Taken from megadlbot_oss <https://github.com/eyaadh/megadlbot_oss/blob/master/mega/webserver/__init__.py>
# Thanks to Eyaadh <https://github.com/eyaadh>
# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

import logging
import os
from urllib.parse import urlsplit
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine, BadHttpMessage
from .stream_routes import routes

logger = logging.getLogger("server")


class _SuppressConnectAccessFilter(logging.Filter):
    """
    屏蔽常见扫描器/代理探测产生的 CONNECT access log。

    说明：aiohttp.access 的 record 内容依赖 aiohttp 版本与 formatter，
    这里用 getMessage() 做最稳妥的字符串匹配。
    """

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover
        try:
            msg = record.getMessage()
        except Exception:
            return True
        # 例：`"CONNECT  HTTP/1.0" 404 ...`
        if '"CONNECT ' in msg:
            return False
        return True


@web.middleware
async def error_handler_middleware(request, handler):
    """处理协议级别的错误，如 TLS 握手请求等"""
    try:
        # 常见扫描/代理探测：CONNECT 方法不属于本服务用途，直接静默返回
        if request.method == "CONNECT":
            return web.Response(status=404, text="Not Found")
        return await handler(request)
    except (BadStatusLine, BadHttpMessage, ConnectionResetError, OSError) as e:
        # 检查是否是 TLS 握手请求（常见的安全扫描）
        error_str = str(e)
        if "Invalid method" in error_str or "BadStatusLine" in error_str:
            # 静默处理 TLS 握手请求和无效的 HTTP 请求
            # 这些通常是扫描或恶意请求，不需要记录为错误
            logger.debug(f"收到无效请求（可能是 TLS/HTTPS 扫描）: {request.remote}")
            return web.Response(status=400, text="Bad Request")
        # 其他连接错误也静默处理
        logger.debug(f"连接错误: {request.remote} - {error_str}")
        return web.Response(status=400, text="Bad Request")
    except web.HTTPException:
        # 诸如 404/405 等属于正常 HTTP 流程，不应记录为 ERROR/堆栈
        raise
    except Exception as e:
        # 其他未预期的错误正常记录
        logger.error(f"处理请求时出错: {e}", exc_info=True)
        raise


@web.middleware
async def compression_middleware(request, handler):
    """添加 gzip 压缩支持"""
    response = await handler(request)

    # 只压缩文本类型的响应
    if isinstance(response, web.FileResponse):
        content_type = response.content_type
        if content_type and any(t in content_type for t in ['text/', 'application/javascript', 'application/json']):
            # 检查客户端是否支持 gzip
            accept_encoding = request.headers.get('Accept-Encoding', '')
            if 'gzip' in accept_encoding.lower():
                response.enable_compression()

    return response


_AUTH_WHITELIST = frozenset({
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/refresh",
    "/api/health",
})

_AUTH_WHITELIST_PREFIXES = ()

_RESOURCE_TICKET_PREFIXES = (
    "/api/telegram/thumbnail/",
)

_DEFAULT_CORS_ORIGINS = frozenset({
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
})

_WEBSOCKET_PROTOCOL_PREFIX = "mistrelay.jwt."


def _configured_cors_origins() -> frozenset[str]:
    configured = {
        origin.strip().rstrip("/")
        for origin in os.environ.get("MISTRELAY_CORS_ORIGINS", "").split(",")
        if origin.strip()
    }
    return _DEFAULT_CORS_ORIGINS | configured


def _is_allowed_origin(request: web.Request, origin: str | None) -> bool:
    if not origin:
        return True
    normalized_origin = origin.rstrip("/")
    if normalized_origin in _configured_cors_origins():
        return True
    try:
        parsed = urlsplit(normalized_origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc == request.host
    except (TypeError, ValueError):
        return False


def _websocket_token(request: web.Request) -> tuple[str | None, str | None]:
    if request.headers.get("Upgrade", "").lower() != "websocket":
        return None, None
    protocols = request.headers.get("Sec-WebSocket-Protocol", "")
    if len(protocols) > 4096:
        return None, None
    for protocol in (value.strip() for value in protocols.split(",")):
        if protocol.startswith(_WEBSOCKET_PROTOCOL_PREFIX):
            return protocol[len(_WEBSOCKET_PROTOCOL_PREFIX):], protocol
    return None, None


def _apply_security_headers(request: web.Request, response: web.StreamResponse) -> web.StreamResponse:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; object-src 'none'; "
        "script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; media-src 'self' blob:; "
        "font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:"
    )
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.path.startswith("/api/auth/") or request.path.startswith("/api/config"):
        response.headers["Cache-Control"] = "no-store"
    return response


@web.middleware
async def security_headers_middleware(request, handler):
    response = await handler(request)
    if isinstance(response, web.WebSocketResponse):
        return response
    return _apply_security_headers(request, response)


def _apply_cors_headers(request: web.Request, response: web.StreamResponse) -> web.StreamResponse:
    origin = request.headers.get("Origin")
    if origin and _is_allowed_origin(request, origin):
        response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept, Origin, X-Requested-With, Range"
    response.headers["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Length, Content-Range, Accept-Ranges, X-MistRelay-Min-Threads"
    response.headers["Access-Control-Max-Age"] = "86400"
    response.headers["Vary"] = "Origin"
    return response


@web.middleware
async def cors_middleware(request, handler):
    """为独立 Web 前端提供跨域访问支持。"""
    origin = request.headers.get("Origin")
    if origin and not _is_allowed_origin(request, origin):
        return web.json_response({"success": False, "error": "Origin 不被允许"}, status=403)
    if request.method == "OPTIONS":
        return _apply_cors_headers(request, web.Response(status=204))

    response = await handler(request)
    if isinstance(response, web.WebSocketResponse):
        return response
    return _apply_cors_headers(request, response)


@web.middleware
async def auth_middleware(request, handler):
    """JWT 认证中间件。保护所有 /api/ 路径（白名单除外）。"""
    path = request.path
    if not path.startswith("/api/") or path in _AUTH_WHITELIST or any(path.startswith(p) for p in _AUTH_WHITELIST_PREFIXES):
        return await handler(request)

    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    if not token:
        token, websocket_protocol = _websocket_token(request)
        if websocket_protocol:
            request["websocket_protocol"] = websocket_protocol

    if not token and any(path.startswith(prefix) for prefix in _RESOURCE_TICKET_PREFIXES):
        from auth import verify_resource_ticket
        ticket = request.query.get("ticket", "")
        if ticket and verify_resource_ticket(ticket, path):
            request["resource_ticket"] = True
            return await handler(request)

    if not token:
        return web.json_response({"success": False, "error": "未登录"}, status=401)

    from auth import verify_token
    payload = verify_token(token)
    if payload is None:
        return web.json_response({"success": False, "error": "登录已过期，请重新登录"}, status=401)

    request["user"] = payload
    return await handler(request)


def web_server():
    logger.info("Initializing..")
    # 屏蔽 CONNECT 探测带来的 access log 噪音(不影响其它请求日志)
    logging.getLogger("aiohttp.access").addFilter(_SuppressConnectAccessFilter())
    web_app = web.Application(client_max_size=30000000)

    # 添加中间件(顺序很重要：先 CORS，再压缩、认证、错误处理)
    web_app.middlewares.append(security_headers_middleware)
    web_app.middlewares.append(cors_middleware)
    web_app.middlewares.append(compression_middleware)
    web_app.middlewares.append(auth_middleware)
    web_app.middlewares.append(error_handler_middleware)

    web_app.add_routes(routes)
    logger.info("Added routes")
    return web_app
