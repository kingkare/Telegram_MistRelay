import sys
import types
from types import SimpleNamespace

if "aiohttp" not in sys.modules:
    aiohttp_module = types.ModuleType("aiohttp")
    web_module = types.ModuleType("aiohttp.web")

    class Response:
        def __init__(self, *, status=200, body=None, text=None, headers=None):
            self.status = status
            self.body = body
            self.text = text
            self.headers = headers or {}

    class FileResponse(Response):
        def __init__(self, path, headers=None):
            super().__init__(status=200, body=path, headers=headers)
            self.path = path

    class RouteTableDef(list):
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
    web_module.Application = object
    web_module.HTTPException = HTTPException
    web_module.HTTPNotFound = HTTPException
    web_module.HTTPForbidden = HTTPException
    web_module.HTTPInternalServerError = HTTPException
    web_module.json_response = lambda data, status=200: Response(status=status, body=data)
    web_module.middleware = lambda func: func
    aiohttp_module.web = web_module
    aiohttp_module.ClientSession = SimpleNamespace
    sys.modules["aiohttp"] = aiohttp_module
    sys.modules["aiohttp.web"] = web_module

    http_exceptions = types.ModuleType("aiohttp.http_exceptions")
    http_exceptions.BadStatusLine = HTTPException
    http_exceptions.BadHttpMessage = HTTPException
    sys.modules["aiohttp.http_exceptions"] = http_exceptions

if "pyrogram" not in sys.modules:
    pyrogram_module = types.ModuleType("pyrogram")
    pyrogram_module.__path__ = []

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass
        def on_message(self, *args, **kwargs):
            return lambda func: func
        def on_callback_query(self, *args, **kwargs):
            return lambda func: func

    class DummyFilter:
        def __or__(self, other):
            return self
        def __and__(self, other):
            return self
        def __invert__(self):
            return self
        def __call__(self, *args, **kwargs):
            return self
        def __getattr__(self, name):
            return self

    pyrogram_module.Client = DummyClient
    pyrogram_module.filters = DummyFilter()

    pyrogram_file_id = types.ModuleType("pyrogram.file_id")
    def _mock_decode_file_id(val):
        dc = 5
        s = str(val).lower()
        if "dc1" in s: dc = 1
        elif "dc2" in s: dc = 2
        elif "dc3" in s: dc = 3
        elif "dc4" in s: dc = 4
        elif "dc5" in s: dc = 5
        return SimpleNamespace(file_type=None, dc_id=dc)
    pyrogram_file_id.FileId = SimpleNamespace(decode=_mock_decode_file_id)
    pyrogram_file_id.FileType = SimpleNamespace(PHOTO="photo", VIDEO="video", DOCUMENT="document", AUDIO="audio")
    pyrogram_file_id.ThumbnailSource = SimpleNamespace
    pyrogram_file_id.PHOTO_TYPES = {"photo"}
    
    pyrogram_types = types.ModuleType("pyrogram.types")
    pyrogram_types.Message = SimpleNamespace
    pyrogram_types.Chat = SimpleNamespace
    pyrogram_types.User = SimpleNamespace
    pyrogram_types.InlineKeyboardMarkup = SimpleNamespace
    pyrogram_types.InlineKeyboardButton = SimpleNamespace
    
    pyrogram_enums = types.ModuleType("pyrogram.enums")
    pyrogram_enums.ChatType = SimpleNamespace(CHANNEL="channel", SUPERGROUP="supergroup", GROUP="group")
    pyrogram_enums.ParseMode = SimpleNamespace(HTML="html", MARKDOWN="markdown")
    
    pyrogram_errors = types.ModuleType("pyrogram.errors")
    class RPCError(Exception): pass
    pyrogram_errors.RPCError = RPCError
    pyrogram_errors.FloodWait = type("FloodWait", (RPCError,), {"value": 5})
    pyrogram_errors.ChannelInvalid = type("ChannelInvalid", (RPCError,), {})
    pyrogram_errors.PeerIdInvalid = type("PeerIdInvalid", (RPCError,), {})
    pyrogram_errors.AuthBytesInvalid = type("AuthBytesInvalid", (RPCError,), {})
    pyrogram_errors.FileReferenceExpired = type("FileReferenceExpired", (RPCError,), {})
    
    pyrogram_raw = types.ModuleType("pyrogram.raw")
    pyrogram_raw.__path__ = []
    pyrogram_raw.functions = SimpleNamespace(upload=SimpleNamespace(GetFile=SimpleNamespace), auth=SimpleNamespace(ExportAuthorization=SimpleNamespace, ImportAuthorization=SimpleNamespace))
    
    pyrogram_raw_types = types.ModuleType("pyrogram.raw.types")
    pyrogram_raw_types.__path__ = []
    pyrogram_raw_types.InputDocumentFileLocation = SimpleNamespace
    pyrogram_raw_types.InputPhotoFileLocation = SimpleNamespace
    pyrogram_raw_types.InputPeerPhotoFileLocation = SimpleNamespace
    pyrogram_raw_types.InputStickerSetThumb = SimpleNamespace
    pyrogram_raw.types = pyrogram_raw_types
    
    pyrogram_raw_types_messages = types.ModuleType("pyrogram.raw.types.messages")
    pyrogram_raw_types_messages.Messages = SimpleNamespace
    
    pyrogram_session = types.ModuleType("pyrogram.session")
    pyrogram_session.Session = SimpleNamespace
    pyrogram_session.Auth = SimpleNamespace
    pyrogram_internals = types.ModuleType("pyrogram.session.internals")
    pyrogram_internals.DataCenter = SimpleNamespace

    pyrogram_utils = types.ModuleType("pyrogram.utils")
    pyrogram_utils.get_channel_id = lambda peer: peer
    pyrogram_utils.get_peer_type = lambda peer: "channel"

    pyrogram_module.raw = pyrogram_raw
    pyrogram_module.utils = pyrogram_utils

    sys.modules["pyrogram"] = pyrogram_module
    sys.modules["pyrogram.file_id"] = pyrogram_file_id
    sys.modules["pyrogram.types"] = pyrogram_types
    sys.modules["pyrogram.enums"] = pyrogram_enums
    sys.modules["pyrogram.enums.parse_mode"] = SimpleNamespace(ParseMode=pyrogram_enums.ParseMode)
    sys.modules["pyrogram.errors"] = pyrogram_errors
    sys.modules["pyrogram.raw"] = pyrogram_raw
    sys.modules["pyrogram.raw.types"] = pyrogram_raw_types
    sys.modules["pyrogram.raw.types.messages"] = pyrogram_raw_types_messages
    sys.modules["pyrogram.raw.functions"] = pyrogram_raw.functions
    sys.modules["pyrogram.session"] = pyrogram_session
    sys.modules["pyrogram.session.internals"] = pyrogram_internals
    sys.modules["pyrogram.utils"] = pyrogram_utils
