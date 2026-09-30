import sys
import types
from types import SimpleNamespace

if "aiohttp" not in sys.modules:
    aiohttp_module = types.ModuleType("aiohttp")
    web_module = types.ModuleType("aiohttp.web")

    class Response:
        def __init__(self, *, status=200, body=None, text=None, headers=None, content_type=None, **kwargs):
            self.content_type = content_type or "text/plain" 
            self.status = status
            self.text = text if text is not None else (body if isinstance(body, str) else None)
            self.body = body if body is not None else text
            self.headers = headers or {}

        async def prepare(self, request):
            return self

        async def write(self, data):
            pass

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
    def _mock_json_response(data, status=200, headers=None, **kwargs):
        import json
        text_val = json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data)
        return Response(status=status, body=data, text=text_val, headers=headers)
    web_module.json_response = _mock_json_response
    web_module.middleware = lambda func: func
    aiohttp_module.web = web_module
    aiohttp_module.ClientSession = SimpleNamespace
    aiohttp_module.ClientTimeout = lambda **kwargs: SimpleNamespace(**kwargs)
    aiohttp_module.TCPConnector = lambda **kwargs: SimpleNamespace(**kwargs)
    aiohttp_module.CookieJar = lambda **kwargs: SimpleNamespace(**kwargs)
    sys.modules["aiohttp"] = aiohttp_module
    sys.modules["aiohttp.web"] = web_module

    http_exceptions = types.ModuleType("aiohttp.http_exceptions")
    http_exceptions.BadStatusLine = HTTPException
    http_exceptions.BadHttpMessage = HTTPException
    sys.modules["aiohttp.http_exceptions"] = http_exceptions

if "pyrogram" not in sys.modules:
    pyrogram_module = types.ModuleType("pyrogram")
    pyrogram_module.__path__ = []

    class DummyDispatcher:
        def __init__(self):
            self.groups = {}
        def add_handler(self, handler, group=0):
            if group not in self.groups:
                self.groups[group] = []
            self.groups[group].append(handler)

    class DummyClient:
        def __init__(self, *args, **kwargs):
            self.dispatcher = DummyDispatcher()
            self.is_connected = False
            self.me = None
        def add_handler(self, handler, group=0):
            self.dispatcher.add_handler(handler, group)
        @classmethod
        def on_message(cls, *args, **kwargs):
            group = kwargs.get('group', 0)
            def decorator(func):
                if not hasattr(func, 'handlers'):
                    func.handlers = []
                func.handlers.append((SimpleNamespace(callback=func), group))
                return func
            return decorator
        def on_callback_query(self, *args, **kwargs):
            return lambda func: func
        async def copy_message(self, *args, **kwargs):
            pass
        async def copy_media_group(self, *args, **kwargs):
            pass

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

    class StopTransmission(Exception):
        pass

    class DummySaveFile:
        save_file = None

    pyrogram_module.Client = DummyClient
    pyrogram_module.filters = DummyFilter()
    pyrogram_module.StopTransmission = StopTransmission

    pyrogram_methods = types.ModuleType("pyrogram.methods")
    pyrogram_methods_adv = types.ModuleType("pyrogram.methods.advanced")
    pyrogram_save_file_mod = types.ModuleType("pyrogram.methods.advanced.save_file")
    pyrogram_save_file_mod.SaveFile = DummySaveFile
    sys.modules["pyrogram.methods"] = pyrogram_methods
    sys.modules["pyrogram.methods.advanced"] = pyrogram_methods_adv
    sys.modules["pyrogram.methods.advanced.save_file"] = pyrogram_save_file_mod

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
    class DummyUser(SimpleNamespace):
        @staticmethod
        def _parse(cli, u):
            return u
    pyrogram_types.User = DummyUser
    class DummyInlineKeyboardButton:
        def __init__(self, text="", url=None, callback_data=None, **kwargs):
            self.text = text
            self.url = url
            self.callback_data = callback_data
            for k, v in kwargs.items():
                setattr(self, k, v)

    class DummyInlineKeyboardMarkup:
        def __init__(self, inline_keyboard=None, **kwargs):
            if inline_keyboard is None:
                self.inline_keyboard = kwargs.get("inline_keyboard", [])
            else:
                self.inline_keyboard = inline_keyboard
            for k, v in kwargs.items():
                setattr(self, k, v)

    pyrogram_types.InlineKeyboardMarkup = DummyInlineKeyboardMarkup
    pyrogram_types.InlineKeyboardButton = DummyInlineKeyboardButton
    pyrogram_types.ReplyKeyboardRemove = SimpleNamespace
    pyrogram_types.BotCommand = SimpleNamespace

    class DummyInputMedia:
        def __init__(self, media=None, **kwargs):
            self.media = media
            for k, v in kwargs.items():
                setattr(self, k, v)

    pyrogram_types.InputMediaPhoto = DummyInputMedia
    pyrogram_types.InputMediaVideo = DummyInputMedia
    pyrogram_types.InputMediaAudio = DummyInputMedia
    pyrogram_types.InputMediaDocument = DummyInputMedia
    pyrogram_module.types = pyrogram_types
    
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
    class GetUsers:
        def __init__(self, *args, **kwargs): pass
    pyrogram_raw.functions = SimpleNamespace(
        users=SimpleNamespace(GetUsers=GetUsers),
        upload=SimpleNamespace(GetFile=SimpleNamespace, SaveFilePart=SimpleNamespace, SaveBigFilePart=SimpleNamespace),
        auth=SimpleNamespace(
            ExportAuthorization=SimpleNamespace,
            ImportAuthorization=SimpleNamespace,
            ResetAuthorizations=type("ResetAuthorizations", (SimpleNamespace,), {}),
        ),
        account=SimpleNamespace(
            GetPassword=type("GetPassword", (SimpleNamespace,), {}),
            DeclinePasswordReset=type("DeclinePasswordReset", (SimpleNamespace,), {}),
            GetAuthorizations=type("GetAuthorizations", (SimpleNamespace,), {}),
            ResetAuthorization=type("ResetAuthorization", (SimpleNamespace,), {}),
        ),
    )
    
    pyrogram_raw_types = types.ModuleType("pyrogram.raw.types")
    pyrogram_raw_types.__path__ = []
    pyrogram_raw_types.InputDocumentFileLocation = SimpleNamespace
    pyrogram_raw_types.InputPhotoFileLocation = SimpleNamespace
    pyrogram_raw_types.InputPeerPhotoFileLocation = SimpleNamespace
    pyrogram_raw_types.InputStickerSetThumb = SimpleNamespace
    pyrogram_raw_types.InputFile = SimpleNamespace
    pyrogram_raw_types.InputFileBig = SimpleNamespace
    pyrogram_raw_types.InputUserSelf = SimpleNamespace
    upload_file_cls = type("UploadFile", (), {})
    pyrogram_raw_types.upload = SimpleNamespace(File=upload_file_cls)
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
