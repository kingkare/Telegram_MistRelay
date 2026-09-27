# This file is a part of MistRelay
# Globally accelerated multi-session MTProto parallel file uploader for Pyrogram

import asyncio
import contextvars
import functools
import inspect
import io
import logging
import math
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import md5
from pathlib import PurePath
from typing import Any, BinaryIO, Callable, Dict, List, Optional, Set, Tuple, Union

import pyrogram
from pyrogram import raw
from pyrogram.errors import FloodWait

try:
    from pyrogram import StopTransmission
except Exception:
    class StopTransmission(Exception):
        pass

try:
    from pyrogram.methods.advanced.save_file import SaveFile
except Exception:
    class SaveFile:
        save_file = None

try:
    from pyrogram.session import Session
except Exception:
    Session = None

logger = logging.getLogger("fast_uploader")

# Telegram MTProto 协议单分片最大尺寸: 512 KB
UPLOAD_PART_SIZE = 512 * 1024
# 大文件判定阈值: 10 MB (遵循 Telegram 官方 >10MB 使用 SaveBigFilePart 规范)
BIG_FILE_THRESHOLD = 10 * 1024 * 1024
# 超大文件判定阈值: 100 MB (启用 10 通道极限并发)
HUGE_FILE_THRESHOLD = 100 * 1024 * 1024
# 超大文件 (>100MB) 并发上传通道数: 10 (Telegram 官方 12 通道触发 FloodWait 1s 前的最佳峰值点)
MAX_HUGE_FILE_SESSIONS = 10
# 大文件 (10MB~100MB) 并发上传通道数: 8
MAX_BIG_FILE_SESSIONS = 8
# 小文件 (<=10MB) 并发上传通道数: 2
MAX_SMALL_FILE_SESSIONS = 2
# 套接字发送/接收缓冲区大小: 2 MB
UPLOAD_SOCKET_BUFFER_SIZE = 2 * 1024 * 1024
# 会话池空闲自动回收时间 (秒)
SESSION_POOL_IDLE_TIMEOUT = 60.0

# Context-local 上传进度钩子: (current_bytes, total_bytes, concurrency) -> None
_upload_progress_hook: contextvars.ContextVar[Optional[Callable[[int, int, int], Any]]] = (
    contextvars.ContextVar("mistrelay_upload_progress_hook", default=None)
)

# 相册/多文件并发预上传缓存: {abspath: (monotonic_ts, InputFile | InputFileBig)}
_preuploaded_cache: Dict[str, Tuple[float, Any]] = {}

_original_save_file = getattr(SaveFile, "save_file", None)
_is_patched = False


def set_upload_progress_hook(
    hook: Optional[Callable[[int, int, int], Any]]
) -> contextvars.Token:
    """在当前异步上下文中注册上传进度监控钩子（适用于 send_media_group 等未直接暴露 progress 参数的调用）"""
    return _upload_progress_hook.set(hook)


def reset_upload_progress_hook(token: contextvars.Token) -> None:
    """重置当前异步上下文的上传进度监控钩子"""
    try:
        _upload_progress_hook.reset(token)
    except Exception:
        pass


def register_preuploaded_file(path: Union[str, PurePath], input_file: Any) -> None:
    """注册已提前完成多通道流式上传的文件句柄 (InputFile / InputFileBig)，供 send_media_group 秒级消费"""
    if not path or input_file is None:
        return
    norm = os.path.abspath(str(path))
    _preuploaded_cache[norm] = (time.monotonic(), input_file)


def get_preuploaded_file(path: Union[str, PurePath]) -> Optional[Any]:
    """提取并消费预上传的文件句柄（10分钟内有效）"""
    if not path:
        return None
    norm = os.path.abspath(str(path))
    item = _preuploaded_cache.pop(norm, None)
    if item:
        ts, inf = item
        if time.monotonic() - ts < 600.0:
            return inf
    return None


def clear_preuploaded_files(paths: Optional[List[Union[str, PurePath]]] = None) -> None:
    """清理预上传文件句柄缓存"""
    if paths is None:
        _preuploaded_cache.clear()
    else:
        for p in paths:
            norm = os.path.abspath(str(p))
            _preuploaded_cache.pop(norm, None)


def _is_session_active(session: Optional[Any]) -> bool:
    if session is None:
        return False
    if isinstance(session, _FallbackSession):
        return True
    is_started = getattr(session, "is_started", None)
    if is_started is not None and hasattr(is_started, "is_set") and not is_started.is_set():
        return False
    conn = getattr(session, "connection", None)
    if conn is None:
        return False
    protocol = getattr(conn, "protocol", None)
    if protocol is not None and getattr(protocol, "closed", False):
        return False
    return True


def tune_mtproto_session_socket(session: Any) -> bool:
    """
    调优 MTProto 媒体连接底层 TCP 套接字：
    1. 开启 TCP_NODELAY=1 禁用 Nagle 算法，消除 40ms ACK 等待延迟；
    2. 将 SO_SNDBUF 与 SO_RCVBUF 提升至 2MB，确保 512KB 分片零阻塞推入内核缓冲区。
    """
    if session is None or isinstance(session, _FallbackSession):
        return False
    try:
        conn = getattr(session, "connection", None)
        if conn is None:
            return False
        proto = getattr(conn, "protocol", None)
        sock = getattr(proto, "socket", None) or getattr(conn, "socket", None)
        if sock is None:
            writer = getattr(proto, "writer", None)
            if writer is not None and hasattr(writer, "get_extra_info"):
                sock = writer.get_extra_info("socket")
        if sock is not None and hasattr(sock, "setsockopt"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, UPLOAD_SOCKET_BUFFER_SIZE)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, UPLOAD_SOCKET_BUFFER_SIZE)
            return True
    except Exception as e:
        logger.debug(f"调优 MTProto 上传套接字选项跳过: {e}")
    return False


class _FallbackSession:
    """在 Mock 或轻量测试环境中当无法建立独立网络 Session 时，平滑回退代理至 client.invoke"""

    def __init__(self, client: Any):
        self.client = client
        self.is_started = asyncio.Event()
        self.is_started.set()

    async def start(self):
        pass

    async def stop(self):
        pass

    async def invoke(self, rpc: Any, *args, **kwargs):
        if hasattr(self.client, "invoke"):
            res = self.client.invoke(rpc)
            if asyncio.iscoroutine(res):
                return await res
            return res
        return True


class UploadSessionPool:
    """
    管理每个 Pyrogram Client 的多通道 MTProto 媒体上传会话池。
    支持独立独占借出（防止并发多文件上传时争用同一 Session 触发 FloodWait）、
    在相册或连续上传期间温热复用连接，并在空闲后自动回收。
    """

    _pools: Dict[int, List[Any]] = {}
    _busy_pools: Dict[int, Set[Any]] = {}
    _client_refs: Dict[int, Any] = {}
    _locks: Dict[int, asyncio.Lock] = {}
    _active_counts: Dict[int, int] = {}
    _last_used: Dict[int, float] = {}
    _cleanup_tasks: Dict[int, asyncio.Task] = {}

    @classmethod
    def _get_lock(cls, client_id: int) -> asyncio.Lock:
        lock = cls._locks.get(client_id)
        if lock is None:
            lock = asyncio.Lock()
            cls._locks[client_id] = lock
        return lock

    @classmethod
    async def _create_single_session(cls, client: "pyrogram.Client") -> Any:
        try:
            storage = getattr(client, "storage", None)
            if storage is None or not hasattr(storage, "dc_id"):
                return _FallbackSession(client)

            dc_id = await storage.dc_id()
            auth_key = await storage.auth_key()
            test_mode = await storage.test_mode()

            if not isinstance(auth_key, (bytes, bytearray)) or len(auth_key) != 256:
                return _FallbackSession(client)

            session = Session(
                client,
                dc_id,
                auth_key,
                test_mode,
                is_media=True,
            )
            await session.start()
            tune_mtproto_session_socket(session)
            return session
        except Exception as e:
            logger.debug(f"创建 MTProto 独立媒体 Session 失败，使用 FallbackSession: {e}")
            return _FallbackSession(client)

    @classmethod
    async def acquire_sessions(
        cls, client: "pyrogram.Client", count: int
    ) -> List[Any]:
        client_id = id(client)
        lock = cls._get_lock(client_id)
        async with lock:
            cls._client_refs[client_id] = client
            cls._active_counts[client_id] = cls._active_counts.get(client_id, 0) + 1
            cls._last_used[client_id] = time.monotonic()

            idle_pool = cls._pools.get(client_id, [])
            busy_set = cls._busy_pools.setdefault(client_id, set())

            usable_idle: List[Any] = []
            stale: List[Any] = []
            for s in idle_pool:
                if s in busy_set:
                    continue
                if _is_session_active(s):
                    usable_idle.append(s)
                else:
                    stale.append(s)

            for s in stale:
                try:
                    await s.stop()
                except Exception:
                    pass

            acquired = usable_idle[:count]
            remaining_idle = usable_idle[count:]

            needed = max(0, count - len(acquired))
            if needed > 0:
                new_sessions = await asyncio.gather(
                    *(cls._create_single_session(client) for _ in range(needed)),
                    return_exceptions=True,
                )
                for res in new_sessions:
                    if res is not None and not isinstance(res, Exception):
                        tune_mtproto_session_socket(res)
                        acquired.append(res)
                    elif isinstance(res, Exception):
                        logger.warning(f"创建并发上传媒体会话异常: {res}")

            if not acquired:
                fallback_session = await cls._create_single_session(client)
                tune_mtproto_session_socket(fallback_session)
                acquired.append(fallback_session)

            for s in acquired:
                busy_set.add(s)

            cls._pools[client_id] = remaining_idle
            return list(acquired[:count])

    @classmethod
    async def replace_session(
        cls, client: "pyrogram.Client", broken_session: Any
    ) -> Any:
        client_id = id(client)
        lock = cls._get_lock(client_id)
        async with lock:
            idle_pool = cls._pools.get(client_id, [])
            busy_set = cls._busy_pools.setdefault(client_id, set())
            if broken_session in idle_pool:
                idle_pool.remove(broken_session)
            busy_set.discard(broken_session)
            try:
                await broken_session.stop()
            except Exception:
                pass
            new_session = await cls._create_single_session(client)
            tune_mtproto_session_socket(new_session)
            busy_set.add(new_session)
            cls._pools[client_id] = idle_pool
            return new_session

    @classmethod
    def release_sessions(
        cls, client: "pyrogram.Client", sessions: Optional[List[Any]] = None
    ) -> None:
        client_id = id(client)
        cur = cls._active_counts.get(client_id, 0)
        cls._active_counts[client_id] = max(0, cur - 1)
        cls._last_used[client_id] = time.monotonic()

        idle_pool = cls._pools.setdefault(client_id, [])
        busy_set = cls._busy_pools.setdefault(client_id, set())

        to_release = sessions if sessions is not None else list(busy_set)
        for s in to_release:
            busy_set.discard(s)
            if _is_session_active(s) and s not in idle_pool:
                idle_pool.append(s)

        if cls._active_counts.get(client_id, 0) == 0 and len(busy_set) == 0:
            existing_task = cls._cleanup_tasks.get(client_id)
            if existing_task is None or existing_task.done():
                try:
                    loop = asyncio.get_running_loop()
                    cls._cleanup_tasks[client_id] = loop.create_task(
                        cls._idle_watcher(client_id)
                    )
                except RuntimeError:
                    pass

    @classmethod
    async def _idle_watcher(cls, client_id: int) -> None:
        try:
            await asyncio.sleep(SESSION_POOL_IDLE_TIMEOUT)
            lock = cls._locks.get(client_id)
            if lock is None:
                return
            async with lock:
                if cls._active_counts.get(client_id, 0) > 0:
                    return
                busy_set = cls._busy_pools.get(client_id, set())
                if len(busy_set) > 0:
                    return
                idle_for = time.monotonic() - cls._last_used.get(client_id, 0.0)
                if idle_for < SESSION_POOL_IDLE_TIMEOUT * 0.9:
                    return
                pool = cls._pools.pop(client_id, [])
                cls._busy_pools.pop(client_id, None)
                cls._client_refs.pop(client_id, None)
                for s in pool:
                    try:
                        await s.stop()
                    except Exception:
                        pass
                if pool:
                    logger.debug(f"已自动回收空闲上传会话池 ({len(pool)} 个连接)")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"回收空闲上传会话池异常: {e}")

    @classmethod
    async def close_client_sessions(cls, client: Any) -> None:
        """显式关闭并清理指定客户端的所有并发上传媒体会话"""
        if client is None:
            return
        client_id = id(client)
        task = cls._cleanup_tasks.pop(client_id, None)
        if task is not None and not task.done():
            task.cancel()

        lock = cls._locks.get(client_id)
        if lock is not None:
            async with lock:
                idle_pool = cls._pools.pop(client_id, [])
                busy_set = cls._busy_pools.pop(client_id, set())
                cls._active_counts.pop(client_id, None)
                cls._last_used.pop(client_id, None)
                cls._client_refs.pop(client_id, None)
                all_sessions = list(idle_pool) + [s for s in busy_set if s not in idle_pool]
                for s in all_sessions:
                    try:
                        await s.stop()
                    except Exception:
                        pass


async def close_upload_sessions(client: Any) -> None:
    """对外暴露的客户端上传会话池安全清理接口"""
    await UploadSessionPool.close_client_sessions(client)


async def fast_save_file(
    self: "pyrogram.Client",
    path: Union[str, BinaryIO, PurePath, Any],
    file_id: int = None,
    file_part: int = 0,
    progress: Callable = None,
    progress_args: tuple = (),
):
    """
    多通道并行流式分片上传实现（完全兼容 Pyrogram Client.save_file 签名与返回契约）。
    - 支持命中相册并发预上传缓存 (InputFile / InputFileBig)，零等待直通；
    - <= 10 MB 小文件：2 通道并发 + SaveFilePart + 流式 MD5 校验，返回 InputFile；
    - 10 MB ~ 100 MB 大文件：8 通道并发 + SaveBigFilePart + 滑动预读队列，返回 InputFileBig；
    - > 100 MB 超大文件：10 通道并发 + SaveBigFilePart + 滑动预读队列，返回 InputFileBig。
    """
    if path is None:
        return None

    # 1. 若传入对象本身已是预生成的 InputFile / InputFileBig，直接返回
    if isinstance(path, (raw.types.InputFile, raw.types.InputFileBig)):
        return path

    # 2. 检查是否命中相册并发预上传缓存
    if isinstance(path, (str, PurePath)) and file_id is None and file_part == 0:
        cached_input = get_preuploaded_file(path)
        if cached_input is not None:
            logger.debug(f"⚡ 命中相册预上传缓存句柄: {os.path.basename(str(path))}")
            return cached_input

    part_size = UPLOAD_PART_SIZE
    should_close_fp = False

    if isinstance(path, (str, PurePath)):
        fp = open(path, "rb")
        should_close_fp = True
        file_name = os.path.basename(str(path)) or "file.jpg"
    elif isinstance(path, io.IOBase) or (hasattr(path, "read") and hasattr(path, "seek")):
        fp = path
        raw_name = getattr(fp, "name", "file.jpg") or "file.jpg"
        file_name = os.path.basename(str(raw_name)) if isinstance(raw_name, (str, PurePath)) else "file.jpg"
    else:
        raise ValueError(
            "Invalid file. Expected a file path as string or a binary (not text) file pointer"
        )

    try:
        fp.seek(0, os.SEEK_END)
        file_size = fp.tell()
        fp.seek(0)

        if file_size == 0:
            raise ValueError("File size equals to 0 B")

        is_premium = bool(getattr(getattr(self, "me", None), "is_premium", False))
        file_size_limit_mib = 4000 if is_premium else 2000
        if file_size > file_size_limit_mib * 1024 * 1024:
            raise ValueError(f"Can't upload files bigger than {file_size_limit_mib} MiB")

        file_total_parts = int(math.ceil(file_size / part_size))
        is_big = file_size > BIG_FILE_THRESHOLD
        is_huge = file_size > HUGE_FILE_THRESHOLD
        is_missing_part = file_id is not None
        file_id = file_id or (self.rnd_id() if hasattr(self, "rnd_id") else int(time.time() * 1000))

        if is_missing_part:
            target_workers = 1
        elif is_huge:
            target_workers = min(MAX_HUGE_FILE_SESSIONS, max(1, file_total_parts))
        elif is_big:
            target_workers = min(MAX_BIG_FILE_SESSIONS, max(1, file_total_parts))
        else:
            target_workers = min(MAX_SMALL_FILE_SESSIONS, max(1, file_total_parts))

        sessions = await UploadSessionPool.acquire_sessions(self, target_workers)
        actual_workers = len(sessions)

        try:
            # 单分片补传模式 (FilePartMissing 重试)
            if is_missing_part:
                fp.seek(part_size * file_part)
                chunk = fp.read(part_size)
                if not chunk:
                    return None
                if is_big:
                    rpc = raw.functions.upload.SaveBigFilePart(
                        file_id=file_id,
                        file_part=file_part,
                        file_total_parts=file_total_parts,
                        bytes=chunk,
                    )
                else:
                    rpc = raw.functions.upload.SaveFilePart(
                        file_id=file_id,
                        file_part=file_part,
                        bytes=chunk,
                    )
                await sessions[0].invoke(rpc)
                return None

            md5_sum = md5() if not is_big else None
            md5_hex = ""
            queue_maxsize = max(2, actual_workers * 2)
            part_queue: asyncio.Queue[Optional[Tuple[int, bytes]]] = asyncio.Queue(
                maxsize=queue_maxsize
            )

            uploaded_bytes = 0
            last_progress_ts = 0.0
            progress_lock = asyncio.Lock()
            ctx_hook = _upload_progress_hook.get()
            worker_errors: List[BaseException] = []
            stop_event = asyncio.Event()

            async def _notify_progress(chunk_len: int) -> None:
                nonlocal uploaded_bytes, last_progress_ts
                async with progress_lock:
                    uploaded_bytes = min(file_size, uploaded_bytes + chunk_len)
                    cur_bytes = uploaded_bytes
                    now = time.monotonic()
                    is_final = cur_bytes >= file_size
                    should_fire = is_final or (now - last_progress_ts >= 0.08)
                    if should_fire:
                        last_progress_ts = now

                if not should_fire:
                    return

                if ctx_hook is not None:
                    try:
                        res = ctx_hook(cur_bytes, file_size, actual_workers)
                        if inspect.iscoroutine(res):
                            await res
                    except StopTransmission:
                        stop_event.set()
                        raise
                    except Exception:
                        pass

                if progress is not None:
                    func = functools.partial(
                        progress,
                        cur_bytes,
                        file_size,
                        *progress_args,
                    )
                    if inspect.iscoroutinefunction(progress):
                        await func()
                    else:
                        loop = getattr(self, "loop", None) or asyncio.get_running_loop()
                        executor = getattr(self, "executor", None)
                        await loop.run_in_executor(executor, func)

            async def _worker(worker_idx: int, session: Any) -> None:
                cur_session = session
                while not stop_event.is_set():
                    item = await part_queue.get()
                    if item is None:
                        part_queue.task_done()
                        return

                    part_idx, chunk = item
                    try:
                        if is_big:
                            rpc = raw.functions.upload.SaveBigFilePart(
                                file_id=file_id,
                                file_part=part_idx,
                                file_total_parts=file_total_parts,
                                bytes=chunk,
                            )
                        else:
                            rpc = raw.functions.upload.SaveFilePart(
                                file_id=file_id,
                                file_part=part_idx,
                                bytes=chunk,
                            )

                        for attempt in range(4):
                            if stop_event.is_set():
                                break
                            try:
                                await cur_session.invoke(rpc)
                                break
                            except FloodWait as fw:
                                wait_s = int(getattr(fw, "value", 1) or 1)
                                logger.warning(
                                    f"上传分片 #{part_idx} 触发 FloodWait({wait_s}s)，自动等待重试"
                                )
                                await asyncio.sleep(min(wait_s, 15))
                            except Exception as e:
                                if attempt == 3:
                                    raise
                                logger.debug(
                                    f"Worker {worker_idx} 上传分片 #{part_idx} 异常 (重试 {attempt + 1}/3): {e}"
                                )
                                await asyncio.sleep(0.3 * (attempt + 1))
                                try:
                                    cur_session = await UploadSessionPool.replace_session(
                                        self, cur_session
                                    )
                                except Exception:
                                    pass

                        if not stop_event.is_set():
                            await _notify_progress(len(chunk))
                    except BaseException as exc:
                        worker_errors.append(exc)
                        stop_event.set()
                        return
                    finally:
                        part_queue.task_done()

            workers = [
                asyncio.create_task(_worker(idx, s))
                for idx, s in enumerate(sessions)
            ]

            try:
                fp.seek(part_size * file_part)
                cur_part = file_part
                while not stop_event.is_set():
                    chunk = fp.read(part_size)
                    if not chunk:
                        if md5_sum is not None:
                            md5_hex = "".join(
                                [hex(i)[2:].zfill(2) for i in md5_sum.digest()]
                            )
                        break

                    if md5_sum is not None:
                        md5_sum.update(chunk)

                    while not stop_event.is_set():
                        try:
                            await asyncio.wait_for(
                                part_queue.put((cur_part, chunk)), timeout=0.5
                            )
                            break
                        except asyncio.TimeoutError:
                            if worker_errors:
                                break
                            continue

                    cur_part += 1
            finally:
                if stop_event.is_set():
                    while not part_queue.empty():
                        try:
                            _ = part_queue.get_nowait()
                            part_queue.task_done()
                        except Exception:
                            break
                    for _ in workers:
                        try:
                            part_queue.put_nowait(None)
                        except Exception:
                            pass
                else:
                    for _ in workers:
                        await part_queue.put(None)

                await asyncio.gather(*workers, return_exceptions=True)

            if worker_errors:
                first_err = worker_errors[0]
                if isinstance(first_err, StopTransmission):
                    raise first_err
                raise first_err

            if is_big:
                return raw.types.InputFileBig(
                    id=file_id,
                    parts=file_total_parts,
                    name=file_name,
                )
            else:
                return raw.types.InputFile(
                    id=file_id,
                    parts=file_total_parts,
                    name=file_name,
                    md5_checksum=md5_hex,
                )
        finally:
            UploadSessionPool.release_sessions(self, sessions)
    except StopTransmission:
        raise
    except Exception as e:
        logger.exception(f"fast_save_file 上传异常 ({file_name}): {e}")
        raise
    finally:
        if should_close_fp:
            try:
                fp.close()
            except Exception:
                pass


def upgrade_pyrogram_crypto_executor() -> int:
    """
    将 Pyrogram 默认的单线程 crypto_executor (ThreadPoolExecutor(1))
    升级为全核并发线程池，彻底消除多通道上传时的 AES-CTR-256 加密排队瓶颈。
    """
    target_workers = min(32, max(8, (os.cpu_count() or 4) * 2))
    try:
        cur_exec = getattr(pyrogram, "crypto_executor", None)
        cur_max = getattr(cur_exec, "_max_workers", 1) if cur_exec is not None else 1
        if cur_max < target_workers:
            pyrogram.crypto_executor = ThreadPoolExecutor(
                max_workers=target_workers,
                thread_name_prefix="CryptoWorker",
            )
            logger.info(
                f"⚡ 已解锁 Pyrogram 全核并行加密引擎: crypto_executor 线程数 {cur_max} -> {target_workers}"
            )
        return getattr(pyrogram.crypto_executor, "_max_workers", target_workers)
    except Exception as e:
        logger.debug(f"升级 crypto_executor 忽略异常: {e}")
        return 1


def patch_pyrogram_uploader() -> None:
    """
    将全核并行加密池与全局多通道并发上传引擎注入 Pyrogram 的 SaveFile 与 Client 类。
    幂等操作，重复调用安全。
    """
    global _is_patched
    try:
        import pyrogram
        from pyrogram.methods.advanced.save_file import SaveFile

        upgrade_pyrogram_crypto_executor()

        SaveFile.save_file = fast_save_file
        pyrogram.Client.save_file = fast_save_file
        if not _is_patched:
            _is_patched = True
            logger.info(
                f"🚀 已启用全局多通道 MTProto 并发上传加速引擎 (超大文件 {MAX_HUGE_FILE_SESSIONS} 通道 / 大文件 {MAX_BIG_FILE_SESSIONS} 通道 / 小文件 {MAX_SMALL_FILE_SESSIONS} 通道)"
            )
    except Exception as e:
        logger.debug(f"注入 fast_uploader 忽略异常: {e}")
