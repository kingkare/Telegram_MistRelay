import math
import asyncio
import logging
from WebStreamer import Var
from typing import Dict, Union, Optional, Tuple, List
from WebStreamer.bot import (
    work_loads,
    multi_clients,
    channel_accessible_clients,
    select_stream_bot,
    acquire_bot_slot,
    release_bot_slot,
    mark_bot_success,
    mark_bot_failure,
    record_bot_bytes,
    mark_bot_warm_dc,
)
from pyrogram import Client, utils, raw
from .file_properties import get_file_ids
from pyrogram.session import Session, Auth
from pyrogram.errors import AuthBytesInvalid
from WebStreamer.server.exceptions import FIleNotFound
from pyrogram.file_id import FileId, FileType, ThumbnailSource

logger = logging.getLogger("streamer")

# 按 (id(client), dc_id, slot_idx) 加锁，使多个 Bot 及同一 Bot 的多个独立连接可并行握手
export_auth_locks: Dict[Tuple[int, int, int], asyncio.Lock] = {}

# 全局缓存每个 Client 对应的 ByteStreamer 实例，供服务端单流多 Bot 条带化并发拉取复用
streamer_registry: Dict[Client, "ByteStreamer"] = {}

# 每个 Bot 在每个媒体 DC 上建立的独立 Session 数量（每个 Session 拥有独立的 Auth().create() 密钥）
MEDIA_SESSIONS_PER_BOT = 1

# 每个 Bot 在流播拉取时并发预取的 1MB 分片深度
PER_BOT_PREFETCH_DEPTH = 2

# 全局条带化轮转游标，使并发发起的各个流在集群中循环选择不同的 Worker 条带
_stripe_global_cursor: int = 0


def get_next_available_client(
    current_index: int,
    exclude_indices: Optional[set] = None,
    target_dc: Optional[int] = None,
) -> Optional[int]:
    if exclude_indices is None:
        exclude_indices = set()
    exclude_indices.add(current_index)
    return select_stream_bot(exclude_indices=exclude_indices, prefer_channel=True, target_dc=target_dc)


def get_available_bot_indices(
    primary_index: int,
    exclude_indices: Optional[set] = None,
    target_dc: Optional[int] = None,
) -> List[int]:
    excluded = set(exclude_indices or ())
    if channel_accessible_clients:
        candidates = [idx for idx in sorted(channel_accessible_clients) if idx in multi_clients and idx not in excluded]
    else:
        candidates = [idx for idx in sorted(multi_clients.keys()) if idx not in excluded]

    if not candidates and primary_index in multi_clients:
        return [primary_index]

    if target_dc is not None:
        from WebStreamer.bot import bot_runtime, work_loads

        def dc_affinity_key(idx: int):
            st = bot_runtime.get(idx, {})
            h_dc = st.get("home_dc")
            w_dcs = st.get("warm_dcs", ())
            if h_dc == target_dc:
                dc_tier = 0
            elif target_dc in w_dcs:
                dc_tier = 1
            else:
                dc_tier = 2
            is_primary = 0 if idx == primary_index else 1
            load = work_loads.get(idx, 0)
            rotated_pos = (candidates.index(idx) - candidates.index(primary_index)) % len(candidates) if primary_index in candidates else idx
            return (dc_tier, is_primary, load, rotated_pos, idx)

        candidates.sort(key=dc_affinity_key)
    elif primary_index in candidates:
        pos = candidates.index(primary_index)
        candidates = candidates[pos:] + candidates[:pos]

    return candidates


def _is_session_usable(media_session: Optional[Session]) -> bool:
    if media_session is None:
        return False
    try:
        if getattr(media_session, "is_started", None) and media_session.is_started.is_set():
            return True
        if (
            hasattr(media_session, "connection") and media_session.connection and
            hasattr(media_session.connection, "protocol") and media_session.connection.protocol and
            hasattr(media_session.connection.protocol, "encrypt") and
            media_session.connection.protocol.encrypt is not None
        ):
            return True
    except Exception:
        pass
    return False


class ByteStreamer:
    def __init__(self, client: Client):
        self.clean_timer = 30 * 60
        self.client: Client = client
        self.cached_file_ids: Dict[int, FileId] = {}
        self._cache_lock = asyncio.Lock()
        self._inflight_sem = asyncio.Semaphore(PER_BOT_PREFETCH_DEPTH)
        self._rr_counter = 0
        streamer_registry[client] = self
        asyncio.create_task(self.clean_cache())

    @classmethod
    def for_client(cls, client: Client) -> "ByteStreamer":
        inst = streamer_registry.get(client)
        if inst is None:
            inst = cls(client)
        return inst

    async def get_file_properties(self, message_id: int, force_refresh: bool = False) -> FileId:
        if force_refresh:
            async with self._cache_lock:
                self.cached_file_ids.pop(message_id, None)
                await self.generate_file_properties(message_id)
                return self.cached_file_ids[message_id]

        if message_id not in self.cached_file_ids:
            async with self._cache_lock:
                if message_id not in self.cached_file_ids:
                    await self.generate_file_properties(message_id)
                    logger.debug(f"Cached file properties for message with ID {message_id}")
        return self.cached_file_ids[message_id]

    async def generate_file_properties(self, message_id: int) -> FileId:
        file_id = await get_file_ids(self.client, Var.BIN_CHANNEL, message_id)
        logger.debug(f"Generated file ID and Unique ID for message with ID {message_id}")
        if not file_id:
            logger.debug(f"Message with ID {message_id} not found")
            raise FIleNotFound
        self.cached_file_ids[message_id] = file_id
        logger.debug(f"Cached media message with ID {message_id}")
        return self.cached_file_ids[message_id]

    async def generate_media_session(
        self,
        client: Client,
        file_id: FileId,
        slot_idx: Optional[int] = None,
        force_recreate: bool = False,
    ) -> Session:
        dc_id = file_id.dc_id
        if not hasattr(client, "_media_session_pool"):
            client._media_session_pool = {}
        pool: Dict[int, Session] = client._media_session_pool.setdefault(dc_id, {})

        if slot_idx is None:
            # 优先挑已就绪的槽位轮询；同时异步预热未创建的槽位
            self._rr_counter += 1
            target_slot = self._rr_counter % MEDIA_SESSIONS_PER_BOT
            if _is_session_usable(pool.get(target_slot)):
                return pool[target_slot]
            # 若 target_slot 尚未建立，但 slot 0 已就绪，则后台异步建 target_slot，本次先用已就绪连接或直接建立
            slot_idx = target_slot

        if not force_recreate and _is_session_usable(pool.get(slot_idx)):
            return pool[slot_idx]

        lock_key = (id(client), dc_id, slot_idx)
        if lock_key not in export_auth_locks:
            export_auth_locks[lock_key] = asyncio.Lock()
        lock = export_auth_locks[lock_key]

        async with lock:
            if not force_recreate and _is_session_usable(pool.get(slot_idx)):
                return pool[slot_idx]

            old_session = pool.pop(slot_idx, None)
            if old_session is not None:
                try:
                    await old_session.stop()
                except Exception:
                    pass

            home_dc = await client.storage.dc_id()
            test_mode = await client.storage.test_mode()

            # 注意：MTProto 要求每个并发 TCP Session 必须拥有独立的 auth_key！
            # 只有当 dc_id == home_dc 且 slot_idx == 0 时才可复用 storage.auth_key()；
            # 其余任何跨 DC 会话或第 2 条并发连接（slot_idx >= 1）都必须创建独立 Auth().create() 并导入授权。
            if dc_id != home_dc:
                media_session = Session(
                    client,
                    dc_id,
                    await Auth(client, dc_id, test_mode).create(),
                    test_mode,
                    is_media=True,
                )
                await media_session.start()

                auth_imported = False
                for attempt in range(6):
                    try:
                        exported_auth = await client.invoke(
                            raw.functions.auth.ExportAuthorization(dc_id=dc_id)
                        )
                        await media_session.invoke(
                            raw.functions.auth.ImportAuthorization(
                                id=exported_auth.id, bytes=exported_auth.bytes
                            )
                        )
                        auth_imported = True
                        logger.debug(
                            f"Successfully imported authorization for DC {dc_id} slot={slot_idx} (attempt {attempt + 1})"
                        )
                        break
                    except AuthBytesInvalid as e:
                        logger.warning(f"Invalid authorization bytes for DC {dc_id} slot={slot_idx} (attempt {attempt + 1}/6): {e}")
                        if attempt < 5:
                            await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    except Exception as e:
                        logger.error(f"Unexpected error during auth import for DC {dc_id} slot={slot_idx}: {e}", exc_info=True)
                        if attempt < 5:
                            await asyncio.sleep(0.5 * (attempt + 1))
                        continue

                if not auth_imported:
                    try:
                        await media_session.stop()
                    except Exception:
                        pass
                    raise AuthBytesInvalid(f"Failed to import authorization for DC {dc_id} slot={slot_idx} after 6 attempts")
            else:
                media_session = Session(
                    client,
                    dc_id,
                    await client.storage.auth_key(),
                    test_mode,
                    is_media=True,
                )
                await media_session.start()

            pool[slot_idx] = media_session
            client.media_sessions[dc_id] = media_session
            try:
                for k, v in multi_clients.items():
                    if v == client:
                        mark_bot_warm_dc(k, dc_id)
                        break
            except Exception:
                pass
            return media_session

    @staticmethod
    async def get_location(file_id: FileId) -> Union[
        raw.types.InputPhotoFileLocation,
        raw.types.InputDocumentFileLocation,
        raw.types.InputPeerPhotoFileLocation,
    ]:
        file_type = file_id.file_type

        if file_type == FileType.CHAT_PHOTO:
            if file_id.chat_id > 0:
                peer = raw.types.InputPeerUser(
                    user_id=file_id.chat_id, access_hash=file_id.chat_access_hash
                )
            else:
                if file_id.chat_access_hash == 0:
                    peer = raw.types.InputPeerChat(chat_id=-file_id.chat_id)
                else:
                    peer = raw.types.InputPeerChannel(
                        channel_id=utils.get_channel_id(file_id.chat_id),
                        access_hash=file_id.chat_access_hash,
                    )

            location = raw.types.InputPeerPhotoFileLocation(
                peer=peer,
                volume_id=file_id.volume_id,
                local_id=file_id.local_id,
                big=file_id.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG,
            )
        elif file_type == FileType.PHOTO:
            location = raw.types.InputPhotoFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size,
            )
        else:
            location = raw.types.InputDocumentFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size,
            )
        return location

    async def _try_get_file_chunk(
        self,
        client: Client,
        client_index: int,
        file_id: FileId,
        location,
        offset: int,
        chunk_size: int,
        max_retries: int = 2,
        slot_idx: Optional[int] = None,
        timeout: float = 8.0,
        message_id: Optional[int] = None,
    ):
        if slot_idx is None:
            self._rr_counter += 1
            slot_idx = self._rr_counter % MEDIA_SESSIONS_PER_BOT

        for retry_attempt in range(max_retries):
            cur_slot = (slot_idx + retry_attempt) % MEDIA_SESSIONS_PER_BOT
            try:
                media_session = await self.generate_media_session(client, file_id, slot_idx=cur_slot)
                async with self._inflight_sem:
                    r = await asyncio.wait_for(
                        media_session.invoke(
                            raw.functions.upload.GetFile(
                                location=location, offset=offset, limit=chunk_size
                            ),
                        ),
                        timeout=timeout,
                    )
                mark_bot_success(client_index)
                return True, r, client, None

            except (asyncio.TimeoutError, TimeoutError) as e:
                logger.warning(f"客户端 {client_index} 拉取分片超时 (offset={offset})")
                if retry_attempt < max_retries - 1:
                    await asyncio.sleep(0.2 * (retry_attempt + 1))
                else:
                    mark_bot_failure(client_index, e)
                    return False, None, client, None

            except (OSError, ConnectionError, AuthBytesInvalid, TypeError, AttributeError, Exception) as e:
                error_msg = str(e)
                logger.warning(f"客户端 {client_index} 拉取分片失败 (offset={offset}): {type(e).__name__}: {error_msg}")
                is_encryption_error = (
                    isinstance(e, AuthBytesInvalid) or
                    "AUTH_KEY_UNREGISTERED" in error_msg or
                    ("encrypt" in error_msg.lower() and isinstance(e, (TypeError, ValueError))) or
                    "Value after * must be an iterable" in error_msg
                )
                is_file_ref_expired = "FILE_REFERENCE" in error_msg

                if retry_attempt < max_retries - 1:
                    if is_encryption_error:
                        try:
                            await self.generate_media_session(client, file_id, slot_idx=cur_slot, force_recreate=True)
                        except Exception:
                            pass
                    elif is_file_ref_expired and message_id is not None:
                        try:
                            refreshed_file_id = await self.get_file_properties(message_id, force_refresh=True)
                            location = await self.get_location(refreshed_file_id)
                            file_id = refreshed_file_id
                        except Exception:
                            pass
                    await asyncio.sleep(0.2 * (retry_attempt + 1))
                else:
                    mark_bot_failure(client_index, e)
                    return False, None, client, None

        return False, None, client, None

    async def _prepare_bot_context(self, bot_idx: int, message_id: Optional[int], default_file_id: FileId, default_location):
        bot_client = multi_clients[bot_idx]
        bot_streamer = ByteStreamer.for_client(bot_client)
        if bot_idx == self._find_own_index() or message_id is None:
            return bot_client, bot_streamer, default_file_id, default_location
        # 每个从机器人必须通过自己的会话获取专属 file_reference，否则 Telegram 会拒绝并抛出 FILE_REFERENCE_EXPIRED
        bot_file_id = await bot_streamer.get_file_properties(message_id, force_refresh=False)
        bot_location = await bot_streamer.get_location(bot_file_id)
        return bot_client, bot_streamer, bot_file_id, bot_location

    def _find_own_index(self) -> int:
        for k, v in multi_clients.items():
            if v == self.client:
                return k
        return 0

    async def yield_file(
        self,
        file_id: FileId,
        index: int,
        offset: int,
        first_part_cut: int,
        last_part_cut: int,
        part_count: int,
        chunk_size: int,
        slot_preacquired: bool = False,
        message_id: Optional[int] = None,
    ) -> Union[str, None]:
        current_index = index
        failed_indices = set()
        slot_acquired = slot_preacquired

        def acquire_current_slot():
            nonlocal slot_acquired
            if not slot_acquired:
                acquire_bot_slot(current_index)
                slot_acquired = True

        def release_current_slot():
            nonlocal slot_acquired
            if slot_acquired:
                release_bot_slot(current_index)
                slot_acquired = False

        from WebStreamer.bot import (
            bot_runtime,
            acquire_stream_slot,
            release_stream_slot,
            get_active_stream_count,
        )

        stream_id = None
        is_probe = (part_count <= 2)
        if not is_probe:
            stream_id = acquire_stream_slot()

        acquire_current_slot()
        default_location = await self.get_location(file_id)
        target_dc = getattr(file_id, "dc_id", None)

        all_bots = get_available_bot_indices(current_index, set(), target_dc=target_dc) if (part_count > 1 and message_id is not None) else [current_index]

        acquired_stripe_slots = set()

        if is_probe or len(all_bots) <= 1 or message_id is None:
            # 探针请求（读取 MP4 文件头/元数据）或单 Bot 模式：直接走主 Bot 单分片极速通道
            stripe_bots = [current_index]
            prefetch_window = min(part_count, 2)
        else:
            # 真实客户端流播/满速下载：服务端 1-to-N 全量多 Bot 聚合切片
            active_streams = max(1, get_active_stream_count())
            total_bots = len(all_bots)
            quota = max(1, total_bots // active_streams)

            if active_streams <= 1:
                # 单连接接入（Web/第三方播放器/单流下载）：直接调动集群全部可用 Bot 全量并行拉取！
                stripe_bots = list(all_bots)
            else:
                # 多流并发（多个用户或播放器发起多个连接）：按活跃流数动态均分 Bot 池，零锁竞争
                start_offset = (((stream_id or 1) - 1) * quota) % total_bots
                stripe_bots = [all_bots[(start_offset + i) % total_bots] for i in range(quota)]
                if current_index not in stripe_bots and len(stripe_bots) < total_bots:
                    stripe_bots[0] = current_index

            # 单流预取滑动窗口大小：每个 Bot 承担 1 个在途分片（最小 2，上限等于所选 Bot 数）
            prefetch_window = min(part_count, max(2, len(stripe_bots)))

            for b in stripe_bots:
                if b != current_index:
                    acquire_bot_slot(b)
                    acquired_stripe_slots.add(b)

        bot_ctx_cache: Dict[int, Tuple[Client, "ByteStreamer", FileId, object]] = {
            current_index: (self.client, self, file_id, default_location)
        }
        bot_ctx_locks: Dict[int, asyncio.Lock] = {b: asyncio.Lock() for b in multi_clients.keys()}

        async def _get_ctx(bot_idx: int):
            if bot_idx in bot_ctx_cache:
                return bot_ctx_cache[bot_idx]
            lock = bot_ctx_locks.setdefault(bot_idx, asyncio.Lock())
            async with lock:
                if bot_idx in bot_ctx_cache:
                    return bot_ctx_cache[bot_idx]
                try:
                    ctx = await self._prepare_bot_context(bot_idx, message_id, file_id, default_location)
                    bot_ctx_cache[bot_idx] = ctx
                    return ctx
                except Exception as e:
                    logger.warning(f"从机 {bot_idx} 初始化分片上下文失败: {e}")
                    return None

        # 并行预热当前条带所有节点的上下文与 FileId 缓存，消除逐个初始化延迟
        if len(stripe_bots) > 1 and message_id is not None:
            try:
                await asyncio.gather(*[_get_ctx(b) for b in stripe_bots], return_exceptions=True)
            except Exception:
                pass

        async def _fetch_part(part_idx: int):
            part_offset = offset + (part_idx - 1) * chunk_size
            active_bots = stripe_bots or [current_index]
            assigned_bot = active_bots[(part_idx - 1) % len(active_bots)]
            slot_idx = ((part_idx - 1) // len(active_bots)) % MEDIA_SESSIONS_PER_BOT

            try:
                ctx = await _get_ctx(assigned_bot)
                if ctx is None:
                    ctx = bot_ctx_cache[current_index]
                b_client, b_streamer, b_file_id, b_location = ctx
                success, r, _, _ = await b_streamer._try_get_file_chunk(
                    b_client, assigned_bot, b_file_id, b_location, part_offset, chunk_size, max_retries=2, slot_idx=slot_idx, timeout=8.0, message_id=message_id
                )
                if success and isinstance(r, raw.types.upload.File):
                    return True, r, assigned_bot, part_offset
            except Exception as e:
                logger.warning(f"条带 Bot {assigned_bot} 获取分片异常 (offset={part_offset}): {e}")

            part_failed = {assigned_bot}

            for fallback_attempt in range(2):
                next_bot = get_next_available_client(assigned_bot, part_failed, target_dc=target_dc)
                if next_bot is None:
                    break
                try:
                    ctx = await _get_ctx(next_bot)
                    if ctx is None:
                        ctx = bot_ctx_cache[current_index]
                    b_client, b_streamer, b_file_id, b_location = ctx
                    success, r, _, _ = await b_streamer._try_get_file_chunk(
                        b_client, next_bot, b_file_id, b_location, part_offset, chunk_size, max_retries=1, timeout=6.0, message_id=message_id
                    )
                    if success and isinstance(r, raw.types.upload.File):
                        return True, r, next_bot, part_offset
                except Exception as e:
                    logger.warning(f"备用 Bot {next_bot} 获取分片失败 (offset={part_offset}): {e}")
                part_failed.add(next_bot)

            return False, None, assigned_bot, part_offset

        prefetch_tasks: Dict[int, asyncio.Task] = {}

        try:
            initial_window = min(part_count, prefetch_window)
            for p in range(1, initial_window + 1):
                prefetch_tasks[p] = asyncio.create_task(_fetch_part(p))

            for current_part in range(1, part_count + 1):
                task = prefetch_tasks.pop(current_part, None)
                if task is None:
                    task = asyncio.create_task(_fetch_part(current_part))

                active_bots = stripe_bots or [current_index]
                assigned_bot = active_bots[(current_part - 1) % len(active_bots)]

                try:
                    success, r, used_bot, part_offset = await asyncio.wait_for(task, timeout=12.0)
                except Exception as e:
                    logger.warning(f"分片 {current_part} (Bot {assigned_bot}) 预取等待超时或异常 ({e})，执行兜底重试...")
                    success, r, used_bot, part_offset = False, None, assigned_bot, offset + (current_part - 1) * chunk_size

                if not success or not isinstance(r, raw.types.upload.File):
                    logger.warning(f"分片 {current_part} 首轮获取未命中，执行备用重试...")
                    success, r, used_bot, part_offset = await _fetch_part(current_part)
                    if not success or not isinstance(r, raw.types.upload.File):
                        logger.error(f"所有客户端都无法获取文件块，停止文件流传输 (offset: {part_offset})")
                        break

                for next_p in range(current_part + 1, min(part_count, current_part + prefetch_window) + 1):
                    if next_p not in prefetch_tasks:
                        prefetch_tasks[next_p] = asyncio.create_task(_fetch_part(next_p))

                chunk = r.bytes
                if not chunk:
                    break
                elif part_count == 1:
                    output_chunk = chunk[first_part_cut:last_part_cut]
                elif current_part == 1:
                    output_chunk = chunk[first_part_cut:]
                elif current_part == part_count:
                    output_chunk = chunk[:last_part_cut]
                else:
                    output_chunk = chunk

                if output_chunk:
                    record_bot_bytes(used_bot, len(output_chunk))
                    yield output_chunk

        except (GeneratorExit, asyncio.CancelledError):
            raise
        except Exception as e:
            error_msg = str(e)
            if "Connection lost" in error_msg or "Connection closed" in error_msg:
                logger.error(f"连接丢失错误 in yield_file: {e}")
            else:
                logger.error(f"Unexpected error in yield_file: {e}", exc_info=True)
        finally:
            for t in prefetch_tasks.values():
                if not t.done():
                    t.cancel()
            if prefetch_tasks:
                await asyncio.gather(*prefetch_tasks.values(), return_exceptions=True)
            release_current_slot()
            for b in acquired_stripe_slots:
                release_bot_slot(b)
            if stream_id is not None:
                release_stream_slot(stream_id)

    async def clean_cache(self) -> None:
        while True:
            await asyncio.sleep(self.clean_timer)
            async with self._cache_lock:
                self.cached_file_ids.clear()
            logger.debug("Cleaned the cache")
