"""
Pyrogram 64-bit Telegram Channel ID, Peer Resolution & Constructor Monkey Patch
================================================================================
1. Resolves Telegram 64-bit channel IDs (where channel_id > 2147483647,
   e.g. chat_id = -1004056710317), which crash standard Pyrogram 2.0.x with
   ValueError: Peer id invalid: -1004...
2. Fixes Telegram API new layer UserFull constructor (0x93eadb53) crashing
   Client.get_me() with KeyError: 2481642323 / ValueError: The server sent an unknown constructor.
3. Provides lightweight, high-performance Client.get_me() via GetUsers(InputUserSelf())
   which avoids GetFullUser FloodWait and eliminates unknown constructor issues.
4. Protects Session.handle_packet against unhandled packet exceptions causing task crashes.
"""

import sys
import logging

logger = logging.getLogger("pyrogram_patch")


def apply_pyrogram_patches():
    """Apply monkey patches to pyrogram to support 64-bit channel IDs, chats, and modern Telegram API constructors."""
    try:
        import pyrogram.utils as utils

        # 1. Expand MIN_CHANNEL_ID and MIN_CHAT_ID to support full 64-bit Telegram channel and chat IDs
        utils.MIN_CHANNEL_ID = -100999999999999
        utils.MIN_CHAT_ID = -999999999999
        if not hasattr(utils, "MAX_CHANNEL_ID"):
            utils.MAX_CHANNEL_ID = -1000000000000
        if not hasattr(utils, "MAX_USER_ID"):
            utils.MAX_USER_ID = 999999999999

        _orig_get_peer_type = getattr(utils, "get_peer_type", None)

        def patched_get_peer_type(peer_id: int) -> str:
            if not isinstance(peer_id, int):
                try:
                    peer_id = int(peer_id)
                except Exception:
                    raise ValueError(f"Peer id invalid: {peer_id}")

            max_channel_id = getattr(utils, "MAX_CHANNEL_ID", -1000000000000)
            max_user_id = getattr(utils, "MAX_USER_ID", 999999999999)

            if peer_id < 0:
                # Any negative peer_id less than MAX_CHANNEL_ID (-1000000000000) is a channel / supergroup
                if peer_id < max_channel_id:
                    return "channel"
                # Negative peer_id >= MAX_CHANNEL_ID is a basic group chat
                return "chat"
            elif 0 < peer_id <= max_user_id:
                return "user"

            raise ValueError(f"Peer id invalid: {peer_id}")

        def patched_get_channel_id(peer_id: int) -> int:
            return getattr(utils, "MAX_CHANNEL_ID", -1000000000000) - peer_id

        utils.get_channel_id = patched_get_channel_id
        utils.get_peer_type = patched_get_peer_type

        # Ensure any existing references to get_peer_type / get_channel_id in imported modules get updated
        for mod_name, mod in list(sys.modules.items()):
            if mod and "pyrogram" in mod_name:
                if hasattr(mod, "MIN_CHANNEL_ID"):
                    setattr(mod, "MIN_CHANNEL_ID", utils.MIN_CHANNEL_ID)
                if hasattr(mod, "MIN_CHAT_ID"):
                    setattr(mod, "MIN_CHAT_ID", utils.MIN_CHAT_ID)
                if hasattr(mod, "get_peer_type"):
                    setattr(mod, "get_peer_type", patched_get_peer_type)
                if hasattr(mod, "get_channel_id"):
                    setattr(mod, "get_channel_id", patched_get_channel_id)

        logger.debug("已成功加载 Pyrogram 64 位 Channel ID 与 Peer 解析兼容补丁")
    except Exception as e:
        logger.warning(f"应用 Pyrogram 64 位 Channel ID 补丁失败: {e}")

    # 2. Register unknown constructor 0x93eadb53 (UserFull in Layer 160+)
    try:
        import pyrogram
        import pyrogram.raw.all as all_raw
        from pyrogram.raw.types.user_full import UserFull as OrigUserFull

        if hasattr(all_raw, 'objects') and isinstance(all_raw.objects, dict):
            if 0x93eadb53 not in all_raw.objects:
                all_raw.objects[0x93eadb53] = OrigUserFull
                all_raw.objects[2481642323] = OrigUserFull
    except Exception as e:
        logger.debug(f"注册 0x93eadb53 构造器跳过（测试或未定义 mock 环境）: {e}")

    # 3. Patch Client.get_me to use lightweight GetUsers(InputUserSelf())
    try:
        from pyrogram import Client, raw, types

        _orig_get_me = getattr(Client, "get_me", None)

        async def patched_get_me(self: Client) -> types.User:
            if not getattr(self, "is_connected", False):
                if _orig_get_me:
                    return await _orig_get_me(self)
                raise ConnectionError("Can't invoke API methods while disconnected")
            try:
                r = await self.invoke(
                    raw.functions.users.GetUsers(
                        id=[raw.types.InputUserSelf()]
                    )
                )
                if r and len(r) > 0:
                    parsed = types.User._parse(self, r[0])
                    self.me = parsed
                    return parsed
            except Exception as e:
                logger.debug(f"patched_get_me via GetUsers error: {e}, falling back to original")

            if _orig_get_me:
                return await _orig_get_me(self)
            raise ValueError("Failed to retrieve current user info via get_me")

        Client.get_me = patched_get_me
        logger.debug("已成功加载 Pyrogram Client.get_me 极速防崩溃补丁")
    except Exception as e:
        logger.warning(f"应用 Pyrogram Client.get_me 补丁失败: {e}")

    # 4. Patch Session.handle_packet to gracefully catch packet unpack exceptions
    try:
        from pyrogram.session import Session as PyrogramSession

        _orig_handle_packet = getattr(PyrogramSession, "handle_packet", None)
        if _orig_handle_packet and callable(_orig_handle_packet):
            async def patched_handle_packet(self, packet):
                try:
                    return await _orig_handle_packet(self, packet)
                except Exception as e:
                    import logging
                    logging.getLogger("pyrogram.session").warning("Session.handle_packet: 忽略无法解析的异常数据包: %s", e)
                    return None

            PyrogramSession.handle_packet = patched_handle_packet
            logger.debug("已成功加载 Pyrogram Session.handle_packet 异常安全捕获补丁")
    except Exception as e:
        logger.debug(f"应用 Pyrogram Session.handle_packet 补丁跳过: {e}")


# Auto-apply on import
apply_pyrogram_patches()
