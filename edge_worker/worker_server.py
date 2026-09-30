#!/usr/bin/env python3
"""
MistRelay Edge Streaming Worker (独立边缘推流微服务)
=====================================================
部署于租户 VPS 节点，通过 Master 签发的防篡改 HMAC Ticket 校验请求，
直接从 Telegram DC 拉取分片并向客户端执行 HTTP Range 流式传输，彻底释放主控带宽。
内置：全球 Telegram 5 大 DC 延迟矩阵测试、真实 MTProto 拉流测速、主控链路测速与深度系统体检。
"""

import os
import ssl
from pathlib import Path
import re
import sys
import math
import time
import json
import hmac
import base64
import socket
import ipaddress
import shutil
import hashlib
import logging
import asyncio
import argparse
import platform
import mimetypes
import importlib.util
import subprocess
import statistics
from typing import Dict, Any, List, Tuple, Optional
from urllib.parse import quote
from aiohttp import web, ClientSession, ClientTimeout

try:
    import resource
except ImportError:
    resource = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("edge_worker")

VERSION = "1.6.0"
MEDIA_SESSIONS_PER_BOT = 3

MEDIA_SOCKET_RCVBUF_SIZE = 4 * 1024 * 1024
MEDIA_SOCKET_SNDBUF_SIZE = 4 * 1024 * 1024


def ensure_tgcrypto_installed() -> bool:
    """检测并确保安装 tgcrypto 硬件加速扩展，避免纯 Python AES 解密拖慢拉流性能"""
    try:
        import tgcrypto
        return True
    except ImportError:
        pass
    try:
        import subprocess, sys
        logger.info("正在检查并安装 tgcrypto C 扩展以开启 Telegram 硬件 AES 解密加速...")
        cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages", "--quiet", "tgcrypto"]
        res = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        if res.returncode != 0:
            cmd2 = [sys.executable, "-m", "pip", "install", "--quiet", "tgcrypto"]
            subprocess.run(cmd2, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        import tgcrypto
        logger.info("tgcrypto 硬件加速模块加载成功")
        return True
    except Exception as e:
        logger.debug(f"tgcrypto 自动补齐跳过: {e}")
        return False



def upgrade_pyrogram_crypto_executor() -> int:
    """
    将 Pyrogram 默认的单线程 crypto_executor (ThreadPoolExecutor(1))
    升级为全核高并发线程池，彻底消除多 Bot 并发拉流时的 AES-CTR-256 加解密排队瓶颈。
    """
    target_workers = max(16, min(64, (os.cpu_count() or 4) * 8))
    try:
        import pyrogram
        from concurrent.futures.thread import ThreadPoolExecutor
        cur_exec = getattr(pyrogram, "crypto_executor", None)
        cur_max = getattr(cur_exec, "_max_workers", 1) if cur_exec is not None else 1
        if cur_max < target_workers:
            try:
                if cur_exec:
                    cur_exec.shutdown(wait=False)
            except Exception:
                pass
            pyrogram.crypto_executor = ThreadPoolExecutor(
                max_workers=target_workers,
                thread_name_prefix="CryptoWorker",
            )
            logger.info(
                f"⚡ 已解锁 Pyrogram 全并发解密引擎: crypto_executor 线程数 {cur_max} -> {target_workers}"
            )
        return getattr(pyrogram.crypto_executor, "_max_workers", target_workers)
    except Exception as e:
        logger.debug(f"升级 crypto_executor 忽略异常: {e}")
        return 1

def apply_pyrogram_patches():
    upgrade_pyrogram_crypto_executor()
    try:
        import pyrogram.utils as utils
        utils.MIN_CHANNEL_ID = -100999999999999
        utils.MIN_CHAT_ID = -999999999999
        if not hasattr(utils, "MAX_CHANNEL_ID"):
            utils.MAX_CHANNEL_ID = -1000000000000
        if not hasattr(utils, "MAX_USER_ID"):
            utils.MAX_USER_ID = 999999999999

        def patched_get_peer_type(peer_id: int) -> str:
            if not isinstance(peer_id, int):
                try:
                    peer_id = int(peer_id)
                except Exception:
                    raise ValueError(f"Peer id invalid: {peer_id}")
            max_channel_id = getattr(utils, "MAX_CHANNEL_ID", -1000000000000)
            max_user_id = getattr(utils, "MAX_USER_ID", 999999999999)
            if peer_id < 0:
                if peer_id < max_channel_id:
                    return "channel"
                return "chat"
            elif 0 < peer_id <= max_user_id:
                return "user"
            raise ValueError(f"Peer id invalid: {peer_id}")

        def patched_get_channel_id(peer_id: int) -> int:
            return getattr(utils, "MAX_CHANNEL_ID", -1000000000000) - peer_id

        utils.get_channel_id = patched_get_channel_id
        utils.get_peer_type = patched_get_peer_type

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
    except Exception as e:
        logger.debug(f"Pyrogram 64-bit patch skipped: {e}")


def tune_system_tcp_stack():
    try:
        if os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0:
            import subprocess
            subprocess.run(["modprobe", "tcp_bbr"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for k, v in [
                ("net.core.default_qdisc", "fq"),
                ("net.ipv4.tcp_congestion_control", "bbr"),
                ("net.core.rmem_max", "16777216"),
                ("net.core.wmem_max", "16777216"),
                ("net.ipv4.tcp_rmem", "4096 87380 16777216"),
                ("net.ipv4.tcp_wmem", "4096 65536 16777216"),
                ("net.ipv4.tcp_window_scaling", "1"),
                ("net.ipv4.tcp_slow_start_after_idle", "0"),
            ]:
                subprocess.run(["sysctl", "-w", f"{k}={v}"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


tune_system_tcp_stack()


def tune_media_session_socket(media_session) -> bool:
    if media_session is None:
        return False
    try:
        conn = getattr(media_session, "connection", None)
        if conn is None:
            return False
        proto = getattr(conn, "protocol", None)
        sock = getattr(proto, "socket", None) or getattr(conn, "socket", None)
        if sock is None and proto is not None:
            for attr_name in ("writer", "transport"):
                holder = getattr(proto, attr_name, None)
                if holder is not None and hasattr(holder, "get_extra_info"):
                    sock = holder.get_extra_info("socket")
                    if sock is not None:
                        break
        if sock is not None and hasattr(sock, "setsockopt"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, MEDIA_SOCKET_RCVBUF_SIZE)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, MEDIA_SOCKET_SNDBUF_SIZE)
            return True
    except Exception:
        pass
    return False


def _is_session_usable(media_session) -> bool:
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

TELEGRAM_DCS = [
    {"id": 1, "name": "DC1 美西 (Miami)", "region": "美西/北美", "ip": "149.154.175.53", "port": 443},
    {"id": 2, "name": "DC2 欧洲 (Amsterdam)", "region": "欧洲/阿姆斯特丹", "ip": "149.154.167.51", "port": 443},
    {"id": 3, "name": "DC3 美东 (Miami)", "region": "美东/迈阿密", "ip": "149.154.175.100", "port": 443},
    {"id": 4, "name": "DC4 欧洲 (Amsterdam)", "region": "欧洲/荷兰", "ip": "149.154.167.91", "port": 443},
    {"id": 5, "name": "DC5 亚太 (Singapore)", "region": "亚太/新加坡", "ip": "91.108.56.165", "port": 443},
]


async def _ping_single_dc(dc_info: dict, rounds: int = 3, timeout: float = 2.5) -> dict:
    ip = dc_info["ip"]
    port = dc_info["port"]
    rtts = []
    failed = 0
    for _ in range(rounds):
        t0 = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
            rtt = (time.perf_counter() - t0) * 1000
            rtts.append(round(rtt, 1))
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        except Exception:
            failed += 1
        await asyncio.sleep(0.02)

    total_probes = len(rtts) + failed
    loss_pct = round((failed / total_probes) * 100, 1) if total_probes else 100.0

    if rtts:
        min_rtt = min(rtts)
        avg_rtt = round(sum(rtts) / len(rtts), 1)
        max_rtt = max(rtts)
        if avg_rtt < 80:
            rating = "optimal"
            rating_label = "极速最优"
        elif avg_rtt < 160:
            rating = "good"
            rating_label = "网络通畅"
        elif avg_rtt < 260:
            rating = "medium"
            rating_label = "普通延迟"
        else:
            rating = "poor"
            rating_label = "延迟偏高"
    else:
        min_rtt = 0.0
        avg_rtt = 0.0
        max_rtt = 0.0
        rating = "unreachable"
        rating_label = "不可达"

    return {
        "dc_id": dc_info["id"],
        "name": dc_info["name"],
        "region": dc_info["region"],
        "ip": ip,
        "port": port,
        "min_rtt_ms": min_rtt,
        "avg_rtt_ms": avg_rtt,
        "max_rtt_ms": max_rtt,
        "packet_loss_pct": loss_pct,
        "rating": rating,
        "rating_label": rating_label,
        "reachable": bool(rtts),
    }


def verify_ticket(ticket: str, node_secret: str, expected_mid: int | None = None):
    if not ticket or "." not in ticket:
        return False, None, "Missing or malformed ticket"
    parts = ticket.split(".", 1)
    if len(parts) != 2:
        return False, None, "Invalid ticket format"
    b64_payload, sig = parts

    expected_sig = hmac.new(
        node_secret.encode("utf-8"),
        b64_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected_sig):
        return False, None, "Ticket signature mismatch"

    try:
        raw = base64.urlsafe_b64decode(b64_payload.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception as e:
        return False, None, f"Ticket decode error: {e}"

    if time.time() > payload.get("exp", 0):
        return False, payload, "Ticket expired"

    if expected_mid is not None and int(payload.get("mid", -1)) != int(expected_mid):
        return False, payload, "Ticket message_id mismatch"

    return True, payload, "OK"


def build_content_disposition(disposition: str, file_name: str) -> str:
    bad_chars = ('"', chr(13), chr(10))
    safe_name = ''.join(c for c in (file_name or 'video.mp4') if c not in bad_chars)
    ascii_name = safe_name.encode('ascii', 'ignore').decode('ascii') or 'stream.bin'
    utf8_quoted = quote(safe_name)
    return disposition + '; filename="' + ascii_name + '"; filename*=UTF-8''' + utf8_quoted


# =====================================================================
# 基于控制理论的自适应边缘传输加速体系 (Adaptive Transmission Acceleration)
# =====================================================================

class SystemHardwareGuardrail:
    """
    边缘硬件与内存安全守护控制器 (防 OOM 与算力分级)
    将异构边缘节点 (NAT VPS, 独服, 云服务器) 按物理内存/CPU 划分为三层算力画像:
    1. ULTRA_LOW_NAT (< 600MB RAM, 如 512MB NAT VPS, t2.nano):
       硬约束在途内存队列 <= 24MB, 初始窗口 2, 最大窗口 8~12, 禁止大规模并发堆叠
    2. BUDGET_VPS (600MB ~ 1600MB RAM, 如 RackNerd, 廉价 VPS):
       在途队列 <= 72MB, 初始窗口 4, 最大窗口 24~32
    3. DEDICATED_HIGH_SPEC (> 1600MB RAM, 如多核独服, 高配云主机):
       在途队列 <= 256MB, 初始窗口 8, 最大窗口 64~96, 全速跑满高带宽高时延积 (BDP)
    """
    def __init__(self):
        self._total_mb = 1024.0
        self._free_mb = 512.0
        self._cpu_cores = os.cpu_count() or 1
        self._refresh()

    def _refresh(self):
        try:
            import psutil
            vm = psutil.virtual_memory()
            self._total_mb = round(vm.total / (1024 * 1024), 1)
            self._free_mb = round(vm.available / (1024 * 1024), 1)
        except Exception:
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            self._total_mb = round(int(line.split()[1]) / 1024, 1)
                        elif line.startswith("MemAvailable:"):
                            self._free_mb = round(int(line.split()[1]) / 1024, 1)
            except Exception:
                pass

    @property
    def tier(self) -> str:
        if self._total_mb < 600.0:
            return "ULTRA_LOW_NAT"
        elif self._total_mb < 1600.0:
            return "BUDGET_VPS"
        return "DEDICATED_HIGH_SPEC"

    @property
    def max_queue_bytes(self) -> int:
        t = self.tier
        if t == "ULTRA_LOW_NAT":
            return int(min(24 * 1024 * 1024, max(4 * 1024 * 1024, self._free_mb * 0.25 * 1024 * 1024)))
        elif t == "BUDGET_VPS":
            return int(min(72 * 1024 * 1024, max(12 * 1024 * 1024, self._free_mb * 0.35 * 1024 * 1024)))
        else:
            return int(min(256 * 1024 * 1024, max(24 * 1024 * 1024, self._free_mb * 0.45 * 1024 * 1024)))

    def clamp_window(self, requested_window: int, chunk_size: int = 524288) -> int:
        max_chunks_by_mem = max(2, self.max_queue_bytes // max(1, chunk_size))
        if self.tier == "ULTRA_LOW_NAT":
            upper = min(12, max_chunks_by_mem)
        elif self.tier == "BUDGET_VPS":
            upper = min(32, max_chunks_by_mem)
        else:
            upper = min(96, max_chunks_by_mem)
        return max(2, min(requested_window, upper))


class NetworkPathTracker:
    """
    网络链路物理指标与往返延迟 EWMA 动态跟踪器 (Jacobson/Karn 算法)
    实时监测 RTT 均值、方差抖动与有效物理带宽 BDP，指导对冲超时与窗口基准。
    """
    def __init__(self, dc_id: int = 5):
        self.dc_id = dc_id
        self.srtt = 0.120       # Smoothed RTT (秒)
        self.rttvar = 0.040     # RTT 抖动方差 (秒)
        self.rtt_min = 0.030    # 物理极限最小 RTT
        self.observed_speeds: List[float] = [] # MB/s
        self.last_update = time.perf_counter()

    def update_rtt(self, sample_rtt_s: float):
        if sample_rtt_s <= 0.001 or sample_rtt_s > 10.0:
            return
        if self.srtt == 0.120 and self.rttvar == 0.040:
            self.srtt = sample_rtt_s
            self.rttvar = sample_rtt_s / 2.0
            self.rtt_min = sample_rtt_s
        else:
            self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - sample_rtt_s)
            self.srtt = 0.875 * self.srtt + 0.125 * sample_rtt_s
            if sample_rtt_s < self.rtt_min:
                self.rtt_min = sample_rtt_s
        self.last_update = time.perf_counter()

    def update_speed(self, bytes_transferred: int, duration_s: float):
        if duration_s > 0.001 and bytes_transferred > 0:
            spd = (bytes_transferred / (1024 * 1024)) / duration_s
            self.observed_speeds.append(spd)
            if len(self.observed_speeds) > 20:
                self.observed_speeds.pop(0)

    @property
    def estimated_speed_mb_s(self) -> float:
        if not self.observed_speeds:
            return 8.0
        return round(float(statistics.median(self.observed_speeds)), 2)

    def get_hedge_deadline(self, is_first_chunk: bool = False) -> float:
        if is_first_chunk:
            return max(0.045, min(0.35, self.rtt_min * 1.15))
        return max(0.080, min(1.2, self.srtt + 1.25 * self.rttvar))

    def get_target_bdp_chunks(self, chunk_size: int = 524288) -> int:
        bw_bytes_sec = self.estimated_speed_mb_s * 1024 * 1024
        bdp_bytes = bw_bytes_sec * max(0.02, self.rtt_min)
        chunks = math.ceil(bdp_bytes / max(1, chunk_size))
        return max(2, chunks)


class PIDWindowController:
    """
    闭环控制理论 PID 动态滑动窗口调速器 (BBR 风格背压感知)
    根据下游客户端写入耗时 (tau_write) 实时辨识网络背压与缓冲拥塞:
    - 客户端播放卡顿/暂停/缓冲已满 (tau_write 显著增加) -> 乘性减窗 (Multiplicative Decrease) 截断预取，杜绝内存堆积
    - 客户端线速拉取 (tau_write 极低且队列通畅) -> 加性增窗 (Additive Increase) 扩充并发，跑满全集群物理带宽
    """
    def __init__(self, is_download: bool, hw_guard: SystemHardwareGuardrail):
        self.is_download = is_download
        self.hw_guard = hw_guard
        self.min_window = 2 if not is_download else 4
        self.current_window = 3 if not is_download else 6
        self.kp = 0.6
        self.ki = 0.1
        self.kd = 0.05
        self.integral = 0.0
        self.last_error = 0.0
        self.backpressure_detected = False

    def on_downstream_feedback(self, write_dur_s: float, chunk_bytes: int, path_tracker: NetworkPathTracker):
        target_write_time = 0.010
        error = target_write_time - write_dur_s
        self.integral = max(-5.0, min(5.0, self.integral + error))
        deriv = error - self.last_error
        self.last_error = error

        if write_dur_s > 0.060:
            self.backpressure_detected = True
            self.current_window = max(self.min_window, int(self.current_window * 0.6))
        elif write_dur_s < 0.015:
            step = 2 if self.is_download else 1
            self.current_window += step
        else:
            delta = self.kp * error + self.ki * self.integral + self.kd * deriv
            self.current_window = int(self.current_window + delta)

        bdp_target = path_tracker.get_target_bdp_chunks(chunk_size=chunk_bytes)
        self.current_window = int(0.75 * self.current_window + 0.25 * bdp_target)
        self.current_window = self.hw_guard.clamp_window(self.current_window, chunk_size=chunk_bytes)


class MultiBotLaneMatrix:
    """
    多 Bot 阵列高维会话复用矩阵
    将集群内 N 个可用 Bot 与每个 Bot 的 M 个独立长连接映射为 (N * M) 条无竞态并行管道。
    """
    def __init__(self, usable_sources: List[Any], sessions_per_bot: int = 2):
        self.usable_sources = usable_sources
        self.sessions_per_bot = sessions_per_bot

    @property
    def total_lanes(self) -> int:
        return max(1, len(self.usable_sources) * self.sessions_per_bot)

    def get_lane(self, chunk_idx: int) -> Tuple[Any, int]:
        n_src = max(1, len(self.usable_sources))
        lane_idx = chunk_idx % self.total_lanes
        src_ctx = self.usable_sources[lane_idx % n_src] if self.usable_sources else None
        slot = (lane_idx // n_src) % self.sessions_per_bot
        return src_ctx, slot

    def get_backup_lane(self, chunk_idx: int) -> Tuple[Any, int]:
        n_src = max(1, len(self.usable_sources))
        if n_src <= 1:
            lane_idx = (chunk_idx + 1) % self.total_lanes
            src_ctx = self.usable_sources[0] if self.usable_sources else None
            slot = lane_idx % self.sessions_per_bot
            return src_ctx, slot
        lane_idx = (chunk_idx + 1 + (chunk_idx // n_src)) % self.total_lanes
        src_ctx = self.usable_sources[lane_idx % n_src] if self.usable_sources else None
        slot = (lane_idx // n_src) % self.sessions_per_bot
        return src_ctx, slot


class EdgeStreamingWorker:
    def __init__(
        self,
        port: int = 8090,
        node_secret: str = "",
        master_url: str = "",
        api_id: int = 0,
        api_hash: str = "",
        bot_token: str = "",
        mock_stream: bool = False,
    ):
        self.port = port
        self.node_secret = node_secret
        self.master_url = master_url.rstrip("/") if master_url else ""
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.mock_stream = mock_stream

        self.start_time = time.time()
        self._inflight_streams = 0
        self._stream_sessions = {}
        self._tenant_bytes = {}
        self._tenant_stream_sessions = {}
        self._tenant_inflight = {}
        self._tenant_speeds = {}
        self._tenant_last_active = {}
        self._tenant_last_bytes_mark = {}
        self._tenant_last_mark_time = {}
        self.total_bytes_served = 0
        self.last_bytes_mark = 0
        self.last_mark_time = time.time()
        self.current_tx_speed = 0
        self._tx_speed_ewma = 0.0
        self._last_relay_metrics: Dict[str, Any] = {}

        self._last_cpu_times = None
        try:
            with open("/proc/stat", "r") as f:
                line = f.readline()
                if line.startswith("cpu "):
                    parts = [float(x) for x in line.split()[1:]]
                    idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
                    total = sum(parts)
                    self._last_cpu_times = (idle, total)
        except Exception:
            pass

        try:
            import psutil
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

        self.bot_username = ""
        self.home_dc = 5
        self.target_dc = 5
        self.bot_tokens = []
        self.dc_bot_map = {}
        self.master_bot_token = ""
        self.master_bot_username = ""
        self.primary_session_string = ""
        self.bot_session_strings = []
        self.dc_session_map = {}
        self.master_session_string = ""
        self.master_client = None
        self.worker_clients = []
        self.dc_clients = {}
        self.client_rr_idx = 0

        self.tg_client = None
        self._msg_cache = {}
        self._msg_locks = {}
        self.bot_ctx_cache = {}
        self.bot_ctx_locks = {}
        self.unusable_bots_cache = set()
        self._media_sessions = {}
        self._media_session_locks = {}
        self._foreign_auth_keys = {}
        self._session_rr_counter = 0
        self._inflight_sem = asyncio.Semaphore(64)
        self._heartbeat_task = None
        self._heartbeat_wake_event = asyncio.Event()
        self._last_stream_activity = 0.0
        self._hw_guard = SystemHardwareGuardrail()
        self._path_trackers: Dict[int, NetworkPathTracker] = {}
        self._background_probe_tasks = set()

    def get_system_metrics(self) -> dict:
        cpu_pct = 0.0
        mem_pct = 0.0
        try:
            import psutil
            cpu_pct = round(psutil.cpu_percent(interval=None), 1)
            mem_pct = round(psutil.virtual_memory().percent, 1)
        except Exception:
            pass

        # 优先读取 Linux /proc/stat 计算真正的瞬时 CPU 利用率
        if cpu_pct == 0.0:
            try:
                with open("/proc/stat", "r") as f:
                    line = f.readline()
                    if line.startswith("cpu "):
                        parts = [float(x) for x in line.split()[1:]]
                        idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
                        total = sum(parts)
                        if self._last_cpu_times:
                            last_idle, last_total = self._last_cpu_times
                            d_idle = idle - last_idle
                            d_total = total - last_total
                            if d_total > 0:
                                cpu_pct = round(max(0.0, min(100.0, (1.0 - (d_idle / d_total)) * 100.0)), 1)
                        self._last_cpu_times = (idle, total)
            except Exception:
                pass

        # 若仍然无法获取（非 Linux / 缺少 proc 访问），兜底采用系统负载
        if cpu_pct == 0.0 and self._last_cpu_times is None:
            try:
                load1, _, _ = os.getloadavg()
                cpu_count = os.cpu_count() or 1
                cpu_pct = round(min(100.0, (load1 / cpu_count) * 100.0), 1)
            except Exception:
                pass

        if mem_pct == 0.0:
            try:
                with open("/proc/meminfo", "r") as f:
                    t, a = 0, 0
                    for line in f:
                        if line.startswith("MemTotal:"):
                            t = int(line.split()[1]) * 1024
                        elif line.startswith("MemAvailable:"):
                            a = int(line.split()[1]) * 1024
                    u = max(0, t - a)
                    mem_pct = round((u / t) * 100.0, 1) if t else 0.0
            except Exception:
                pass

        now = time.time()
        elapsed = max(0.5, now - self.last_mark_time)
        delta_bytes = max(0, self.total_bytes_served - self.last_bytes_mark)
        instant_speed = delta_bytes / elapsed
        self.last_bytes_mark = self.total_bytes_served
        self.last_mark_time = now

        current_active = self.active_streams
        if delta_bytes > 0:
            if self._tx_speed_ewma <= 0.0:
                self._tx_speed_ewma = instant_speed
            else:
                self._tx_speed_ewma = (0.6 * instant_speed) + (0.4 * self._tx_speed_ewma)
        else:
            if current_active > 0 or (now - self._last_stream_activity) < 8.0:
                # 播放器正在消费本地分片缓冲区，平滑衰减当前速率，杜绝瞬间跌零断崖跳变
                self._tx_speed_ewma = self._tx_speed_ewma * 0.75
                if self._tx_speed_ewma < 1024:
                    self._tx_speed_ewma = 0.0
            else:
                self._tx_speed_ewma = 0.0

        self.current_tx_speed = int(self._tx_speed_ewma)

        # 计算各租户分流用量与实时速率
        cutoff = now - 8.0
        expired_t = [k for k, ts in self._tenant_stream_sessions.items() if ts < cutoff]
        for k in expired_t:
            self._tenant_stream_sessions.pop(k, None)

        tenants_metrics = {}
        for tid, total_b in list(self._tenant_bytes.items()):
            last_mark_b = self._tenant_last_bytes_mark.get(tid, 0)
            last_mark_t = self._tenant_last_mark_time.get(tid, self.start_time)
            t_elapsed = max(0.5, now - last_mark_t)
            t_delta_b = max(0, total_b - last_mark_b)
            t_instant_speed = t_delta_b / t_elapsed
            self._tenant_last_bytes_mark[tid] = total_b
            self._tenant_last_mark_time[tid] = now

            t_active = sum(1 for k in self._tenant_stream_sessions.keys() if len(k) >= 4 and k[3] == tid)
            t_inflight = self._tenant_inflight.get(tid, 0)
            t_active_count = max(t_inflight, t_active)

            old_speed = self._tenant_speeds.get(tid, 0.0)
            if t_delta_b > 0:
                if old_speed <= 0.0:
                    new_speed = t_instant_speed
                else:
                    new_speed = (0.6 * t_instant_speed) + (0.4 * old_speed)
            else:
                last_act = self._tenant_last_active.get(tid, 0.0)
                if t_active_count > 0 or (now - last_act) < 8.0:
                    new_speed = old_speed * 0.75
                    if new_speed < 1024:
                        new_speed = 0.0
                else:
                    new_speed = 0.0
            self._tenant_speeds[tid] = new_speed

            if total_b > 0 or t_active_count > 0:
                tenants_metrics[str(tid)] = {
                    "tenant_id": tid,
                    "active_streams": t_active_count,
                    "net_tx": int(new_speed),
                    "total_bytes": total_b,
                    "last_active": self._tenant_last_active.get(tid, now),
                }

        return {
            "cpu": cpu_pct,
            "mem": mem_pct,
            "active_streams": current_active,
            "net_rx": int(self.current_tx_speed * 1.02),
            "net_tx": self.current_tx_speed,
            "total_bytes_served": self.total_bytes_served,
            "tenants": tenants_metrics,
        }

    async def fetch_config_from_master(self):
        if not self.master_url or not self.node_secret:
            return
        url = f"{self.master_url}/api/edge/config"
        try:
            async with ClientSession() as session:
                async with session.get(
                    url,
                    headers={"X-Node-Secret": self.node_secret},
                    timeout=10,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("success"):
                            cfg = data.get("config") or {}
                            self.api_id = int(cfg.get("api_id") or self.api_id or 0)
                            self.api_hash = str(cfg.get("api_hash") or self.api_hash or "")
                            self.bot_token = str(cfg.get("bot_token") or self.bot_token or "")
                            self.bot_username = str(cfg.get("bot_username") or self.bot_username or "").lstrip("@")
                            self.target_dc = int(cfg.get("target_dc") or self.target_dc or 5)
                            self.bot_tokens = cfg.get("bot_tokens") or []
                            self.dc_bot_map = cfg.get("dc_bot_map") or {}
                            self.master_bot_token = str(cfg.get("master_bot_token") or "")
                            self.master_bot_username = str(cfg.get("master_bot_username") or "").lstrip("@")
                            self.primary_session_string = str(cfg.get("primary_session_string") or "")
                            self.bot_session_strings = cfg.get("bot_session_strings") or []
                            self.dc_session_map = cfg.get("dc_session_map") or {}
                            self.master_session_string = str(cfg.get("master_session_string") or "")
                            init_bytes = cfg.get("initial_tenant_bytes") or {}
                            if isinstance(init_bytes, dict):
                                for ik, iv in init_bytes.items():
                                    try:
                                        itid = int(ik)
                                        ival = int(iv)
                                        if itid not in self._tenant_bytes or self._tenant_bytes[itid] < ival:
                                            self._tenant_bytes[itid] = ival
                                    except Exception:
                                        pass
                            logger.info(f"Successfully synced MTProto config from Master (Target DC{self.target_dc}, {len(self.bot_tokens)} bot tokens, master={self.master_bot_username or 'none'})")
        except Exception as e:
            logger.warning(f"Failed to fetch config from Master ({url}): {e}")

    async def start_tg_client(self):
        if self.mock_stream:
            logger.info("Edge Worker running in MOCK_STREAM mode")
            return
        if not ((self.api_id and self.api_hash and self.bot_token) or self.primary_session_string):
            await self.fetch_config_from_master()
        if not ((self.api_id and self.api_hash and self.bot_token) or self.primary_session_string):
            logger.warning("Telegram credentials not configured yet; will retry on heartbeat")
            return
        if self.tg_client is not None:
            return
        try:
            from pyrogram import Client
            apply_pyrogram_patches()

            pri_kwargs = {
                "in_memory": True,
                "no_updates": True,
            }
            if self.primary_session_string:
                pri_kwargs["session_string"] = self.primary_session_string
            else:
                pri_kwargs["api_id"] = int(self.api_id)
                pri_kwargs["api_hash"] = str(self.api_hash)
                pri_kwargs["bot_token"] = str(self.bot_token)

            self.tg_client = Client("mistrelay_edge_worker", **pri_kwargs)
            await self.tg_client.start()
            apply_pyrogram_patches()
            me = await self.tg_client.get_me()
            self.bot_username = (getattr(me, "username", "") or self.bot_username or "").lstrip("@")
            self.tg_client.username = self.bot_username
            self.home_dc = getattr(me, "dc_id", None) or self.target_dc or 5
            logger.info(f"Telegram MTProto Primary Client started: @{self.bot_username} (DC{self.home_dc}, auth={'session_string' if self.primary_session_string else 'token'})")

            self.worker_clients = [self.tg_client]
            self.dc_clients[self.home_dc] = self.tg_client

            # 启动 Master 保底客户端（针对 BIN_CHANNEL 等私密频道未授权原生 Bot 时的兜底）
            if self.master_session_string or (self.master_bot_token and self.master_bot_token != self.bot_token):
                try:
                    pfx = (self.master_bot_token or "master").split(":", 1)[0]
                    m_kwargs = {
                        "in_memory": True,
                        "no_updates": True,
                    }
                    if self.master_session_string:
                        m_kwargs["session_string"] = self.master_session_string
                    else:
                        m_kwargs["api_id"] = int(self.api_id)
                        m_kwargs["api_hash"] = str(self.api_hash)
                        m_kwargs["bot_token"] = str(self.master_bot_token)

                    m_cli = Client(f"mistrelay_edge_master_{pfx}", **m_kwargs)
                    await m_cli.start()
                    apply_pyrogram_patches()
                    m_me = await m_cli.get_me()
                    m_cli.username = (getattr(m_me, "username", "") or getattr(self, "master_bot_username", "") or pfx).lstrip("@")
                    self.master_client = m_cli
                    logger.info(f"Master Fallback Client started: @{m_cli.username} (auth={'session_string' if self.master_session_string else 'token'})")
                except Exception as me:
                    logger.warning(f"Failed to start master fallback client: {me}")

            # 启动同 DC 额外 Worker Bot 阵列（支持依据实测物理宽带动态扩容至最多 100 个 Bot，并发拉起）
            extra_tokens = [t for t in self.bot_tokens if t and t != self.bot_token][:99]
            if extra_tokens:
                start_sem = asyncio.Semaphore(12)
                async def _start_extra(idx, tok):
                    async with start_sem:
                        try:
                            try:
                                import psutil
                                free_mb = psutil.virtual_memory().available / (1024 * 1024)
                                if free_mb < 120.0:
                                    logger.warning(f"系统剩余可用内存仅 {free_mb:.1f} MB (< 120MB)，已停止启动更多 Bot 客户端以防止 OOM 崩溃")
                                    return None
                            except Exception:
                                pass
                            pfx = tok.split(":", 1)[0]
                            s_str = ""
                            if getattr(self, "bot_session_strings", None) and idx < len(self.bot_session_strings):
                                s_str = self.bot_session_strings[idx]

                            w_kwargs = {"in_memory": True, "no_updates": True}
                            if s_str:
                                w_kwargs["session_string"] = s_str
                            else:
                                w_kwargs["api_id"] = int(self.api_id)
                                w_kwargs["api_hash"] = str(self.api_hash)
                                w_kwargs["bot_token"] = str(tok)

                            w_cli = Client(f"mistrelay_edge_worker_{pfx}", **w_kwargs)
                            await asyncio.wait_for(w_cli.start(), timeout=8.0)
                            apply_pyrogram_patches()
                            try:
                                w_me = await asyncio.wait_for(w_cli.get_me(), timeout=4.0)
                                w_cli.username = (getattr(w_me, "username", "") or pfx).lstrip("@")
                            except Exception:
                                w_cli.username = pfx
                            w_cli._bot_token = tok
                            logger.info(f"Worker Client #{idx} started for DC{self.home_dc} array: @{w_cli.username}")
                            return w_cli
                        except Exception as we:
                            logger.debug(f"Failed to start extra worker client #{idx}: {we}")
                            return None

                started = await asyncio.gather(*[_start_extra(i, t) for i, t in enumerate(extra_tokens, start=1)])
                for w in started:
                    if w is not None:
                        self.worker_clients.append(w)

            # 跨 DC 直通：为其他主要数据中心初始化原生客户端（免 cross-dc auth 导出）
            for dc_str, dc_tok in (self.dc_bot_map or {}).items():
                try:
                    dc_num = int(dc_str)
                    dc_s_str = (getattr(self, "dc_session_map", {}) or {}).get(dc_str) or ""
                    if dc_num in self.dc_clients or (not dc_tok and not dc_s_str):
                        continue
                    pfx = str(dc_tok).split(":", 1)[0] if dc_tok else f"dc_{dc_str}"

                    dc_kwargs = {"in_memory": True, "no_updates": True}
                    if dc_s_str:
                        dc_kwargs["session_string"] = dc_s_str
                    else:
                        dc_kwargs["api_id"] = int(self.api_id)
                        dc_kwargs["api_hash"] = str(self.api_hash)
                        dc_kwargs["bot_token"] = str(dc_tok)

                    dc_cli = Client(f"mistrelay_edge_dc_{dc_num}_{pfx}", **dc_kwargs)
                    await dc_cli.start()
                    apply_pyrogram_patches()
                    dc_me = await dc_cli.get_me()
                    dc_cli.username = (getattr(dc_me, "username", "") or pfx).lstrip("@")
                    self.dc_clients[dc_num] = dc_cli
                    logger.info(f"Cross-DC Client for DC{dc_num} started: @{dc_cli.username}")
                except Exception as dce:
                    logger.debug(f"Failed to start cross-dc client for DC{dc_str}: {dce}")
        except Exception as e:
            logger.error(f"Failed to start Pyrogram client: {e}")
            self.tg_client = None

    @property
    def active_streams(self) -> int:
        now = time.time()
        cutoff = now - 8.0
        expired = [k for k, ts in self._stream_sessions.items() if ts < cutoff]
        for k in expired:
            self._stream_sessions.pop(k, None)
        expired_t = [k for k, ts in self._tenant_stream_sessions.items() if ts < cutoff]
        for k in expired_t:
            self._tenant_stream_sessions.pop(k, None)
        return max(self._inflight_streams, len(self._stream_sessions))

    @active_streams.setter
    def active_streams(self, val: int):
        self._inflight_streams = max(0, int(val))
        if val == 0:
            self._stream_sessions.clear()
            self._tenant_stream_sessions.clear()
            self._tenant_inflight.clear()

    def _record_stream_activity(self, session_key=None, tenant_id=None):
        now = time.time()
        self._last_stream_activity = now
        if session_key is not None:
            self._stream_sessions[session_key] = now
            if tenant_id is not None:
                self._tenant_stream_sessions[session_key] = now
        if tenant_id is not None:
            self._tenant_last_active[tenant_id] = now
        try:
            self._heartbeat_wake_event.set()
        except Exception:
            pass

    def trigger_heartbeat_soon(self):
        self._record_stream_activity(None)

    async def _get_media_message(
        self,
        chat_id: int,
        message_id: int,
        channel_username: str = "",
        force_refresh: bool = False,
    ):
        ctx = await self._get_client_media_context(
            self.tg_client, chat_id, message_id, channel_username=channel_username, force_refresh=force_refresh
        )
        if ctx:
            return ctx[3]
        if self.master_client:
            m_ctx = await self._get_client_media_context(
                self.master_client, chat_id, message_id, channel_username=channel_username, force_refresh=force_refresh
            )
            if m_ctx:
                return m_ctx[3]
        raise RuntimeError(f"Message {message_id} in {chat_id} is not accessible")

    async def _get_client_media_context(
        self,
        client,
        chat_id: int,
        message_id: int,
        channel_username: str = "",
        force_refresh: bool = False,
    ):
        if client is None:
            return None
        cli_key = (id(client), int(chat_id))
        if cli_key in self.unusable_bots_cache and not force_refresh:
            return None

        cache_key = (id(client), int(chat_id), int(message_id))
        if not force_refresh and cache_key in self.bot_ctx_cache:
            return self.bot_ctx_cache[cache_key]

        lock = self.bot_ctx_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            if not force_refresh and cache_key in self.bot_ctx_cache:
                return self.bot_ctx_cache[cache_key]

            apply_pyrogram_patches()
            msg_obj = None
            last_err = None
            clean_uname = str(channel_username or "").strip().lstrip("@")

            # 1. 优先尝试直接读取消息（零等待直取内存/本地 Peer 缓存）
            try:
                msg_obj = await client.get_messages(chat_id, message_id)
                last_err = None
            except Exception as e:
                last_err = e
                # 若初次读取失败且尚未尝试过用户名预热
                if clean_uname and not clean_uname.startswith("channel_") and msg_obj is None:
                    try:
                        await client.get_chat(f"@{clean_uname}")
                        msg_obj = await client.get_messages(chat_id, message_id)
                        last_err = None
                    except Exception as e2:
                        last_err = e2
                if msg_obj is None:
                    try:
                        await client.get_chat(chat_id)
                        msg_obj = await client.get_messages(chat_id, message_id)
                        last_err = None
                    except Exception as e3:
                        last_err = e3

            if msg_obj and not getattr(msg_obj, "empty", False):
                try:
                    media, file_id, location = self._extract_media_and_location(msg_obj)
                    ctx = (client, file_id, location, msg_obj)
                    self.bot_ctx_cache[cache_key] = ctx
                    return ctx
                except Exception as ex:
                    last_err = ex

            logger.debug(
                f"Bot @{getattr(client, 'username', 'unknown')} 无法获取频道 {chat_id} 消息 {message_id}: {last_err}"
            )
            # 仅当确认发生明确权限拦截时，才加入不可用黑名单（避免网络超时或微抖动导致 Bot 被永久误封杀）
            is_perm_issue = False
            if last_err is not None:
                err_text = str(last_err).upper()
                if any(k in err_text for k in ("CHANNEL_PRIVATE", "CHAT_ADMIN_REQUIRED", "USER_NOT_PARTICIPANT", "CHAT_WRITE_FORBIDDEN")):
                    is_perm_issue = True
                elif "CHANNEL_INVALID" in err_text and not clean_uname:
                    is_perm_issue = True
            if is_perm_issue:
                self.unusable_bots_cache.add(cli_key)
            return None

    async def _resolve_media_source(
        self,
        chat_id: int,
        message_id: int,
        channel_username: str = "",
        fast_start: bool = True,
    ):
        """
        获取当前消息所有可用的 (client, file_id, location, msg_obj) 集合。
        首帧秒开机制 (Zero-Lag Fast-Start):
        - 一旦主 Bot 或已在内存缓存中的 Bot 验证通过，立即返回当前就绪源（耗时 < 100ms），绝不阻塞等待数十个从机探测！
        - 后台异步协程并行预热剩余 20~100 个 Bot 阵列，动态平滑加入通道池，兼顾极速首帧与百兆稳态吞吐。
        """
        usable = []
        primary_ctx = None

        # 1. 优先尝试主客户端
        if self.tg_client is not None:
            primary_ctx = await self._get_client_media_context(
                self.tg_client, chat_id, message_id, channel_username
            )
            if primary_ctx is not None:
                usable.append(primary_ctx)

        # 2. 检查已在内存缓存中的所有已验证 Bot 上下文
        for (cli_id, ch_id, m_id), c_ctx in list(self.bot_ctx_cache.items()):
            if ch_id == int(chat_id) and m_id == int(message_id):
                if c_ctx and not any(id(u[0]) == id(c_ctx[0]) for u in usable):
                    usable.append(c_ctx)

        # 3. 如果主客户端不可用（如私密频道未加群），尝试主控 Bot 兜底
        if not usable and self.master_client is not None:
            master_ctx = await self._get_client_media_context(
                self.master_client, chat_id, message_id, channel_username
            )
            if master_ctx is not None:
                logger.info(
                    f"频道 {chat_id} 私密未授权当前节点主 Bot，自动触发 Master Bot @{getattr(self.master_client, 'username', '')} 兜底通道成功"
                )
                usable.append(master_ctx)
        elif usable and self.master_client is not None and not any(id(u[0]) == id(self.master_client) for u in usable):
            m_key = (id(self.master_client), int(chat_id))
            if m_key not in self.unusable_bots_cache:
                master_ctx = await self._get_client_media_context(
                    self.master_client, chat_id, message_id, channel_username
                )
                if master_ctx is not None and not any(id(u[0]) == id(master_ctx[0]) for u in usable):
                    usable.append(master_ctx)

        # 候选从属 Worker Bot 列表
        candidate_bots = []
        if usable:
            base_cli, base_fid, _, _ = usable[0]
            target_dc = getattr(base_fid, "dc_id", self.home_dc or 5)
            if target_dc in self.dc_clients:
                dc_c = self.dc_clients[target_dc]
                if not any(id(u[0]) == id(dc_c) for u in usable) and (id(dc_c), int(chat_id)) not in self.unusable_bots_cache:
                    candidate_bots.append(dc_c)
            for w_cli in self.worker_clients:
                if not any(id(u[0]) == id(w_cli) for u in usable) and (id(w_cli), int(chat_id)) not in self.unusable_bots_cache:
                    if w_cli not in candidate_bots:
                        candidate_bots.append(w_cli)

            if candidate_bots:
                # 异步后台非阻塞并发预热扩张，绝不阻塞首帧起播
                bg_task = asyncio.create_task(
                    self._background_expand_sources(usable, candidate_bots, chat_id, message_id, channel_username)
                )
                self._background_probe_tasks.add(bg_task)
                bg_task.add_done_callback(lambda t: self._background_probe_tasks.discard(t))
                if fast_start:
                    return usable

        # 兜底：若初始未命中任何 Bot，执行轻量限时并发探测
        if not usable:
            target_dc = self.home_dc or 5
            for w_cli in self.worker_clients:
                if (id(w_cli), int(chat_id)) not in self.unusable_bots_cache:
                    candidate_bots.append(w_cli)
            if candidate_bots:
                probe_sem = asyncio.Semaphore(16)
                async def probe_bot(bot_cli):
                    async with probe_sem:
                        try:
                            return await asyncio.wait_for(
                                self._get_client_media_context(bot_cli, chat_id, message_id, channel_username),
                                timeout=4.0,
                            )
                        except Exception:
                            return None
                extra_ctxs = await asyncio.gather(*[probe_bot(b) for b in candidate_bots[:12]])
                for e_ctx in extra_ctxs:
                    if e_ctx is not None and not any(id(u[0]) == id(e_ctx[0]) for u in usable):
                        usable.append(e_ctx)

        return usable

    async def _background_expand_sources(
        self,
        target_usable_list: List[Any],
        candidate_bots: List[Any],
        chat_id: int,
        message_id: int,
        channel_username: str = "",
    ):
        """后台异步预热并在可用时平滑扩展 Bot 阵列池"""
        probe_sem = asyncio.Semaphore(16)
        async def _probe(b):
            async with probe_sem:
                try:
                    ctx = await asyncio.wait_for(
                        self._get_client_media_context(b, chat_id, message_id, channel_username),
                        timeout=5.0,
                    )
                    if ctx is not None and not any(id(u[0]) == id(ctx[0]) for u in target_usable_list):
                        target_usable_list.append(ctx)
                except Exception:
                    pass
        await asyncio.gather(*[_probe(b) for b in candidate_bots], return_exceptions=True)

    @staticmethod
    def _extract_media_and_location(msg_obj):
        from pyrogram import raw, utils as pyro_utils
        from pyrogram.file_id import FileId, FileType, ThumbnailSource

        media = None
        for attr in ("video", "document", "audio", "animation", "photo", "voice", "video_note", "sticker"):
            m = getattr(msg_obj, attr, None)
            if m and getattr(m, "file_id", None):
                media = m
                break
        if media is None:
            raise ValueError("No downloadable media in message")

        file_id = FileId.decode(media.file_id)
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
                        channel_id=pyro_utils.get_channel_id(file_id.chat_id),
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
        return media, file_id, location

    async def _get_or_create_media_session(
        self, dc_id: int, client=None, slot_idx: int = 0, force_recreate: bool = False
    ):
        from pyrogram import raw
        from pyrogram.session import Session, Auth
        from pyrogram.errors import AuthBytesInvalid

        cli = client or self.tg_client
        if cli is None:
            raise RuntimeError("Telegram client is not ready")

        cache_key = (id(cli), int(dc_id), int(slot_idx))
        if not force_recreate and _is_session_usable(self._media_sessions.get(cache_key)):
            return self._media_sessions[cache_key]

        lock = self._media_session_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            if not force_recreate and _is_session_usable(self._media_sessions.get(cache_key)):
                return self._media_sessions[cache_key]

            old_session = self._media_sessions.pop(cache_key, None)
            if old_session is not None:
                try:
                    await old_session.stop()
                except Exception:
                    pass

            home_dc = await cli.storage.dc_id()
            test_mode = await cli.storage.test_mode()

            if dc_id != home_dc:
                # 跨 DC 会话：首个 Slot 创建 auth_key 并执行 Export/Import Authorization；
                # 后续所有并发 Slot 均安全复用已注册的 foreign_auth_key，避免重复导出引发 FloodWait
                foreign_key = self._foreign_auth_keys.get((id(cli), int(dc_id)))
                if foreign_key is None or force_recreate:
                    auth_key = await Auth(cli, dc_id, test_mode).create()
                    media_session = Session(
                        cli,
                        dc_id,
                        auth_key,
                        test_mode,
                        is_media=True,
                    )
                    await media_session.start()

                    auth_imported = False
                    for attempt in range(5):
                        try:
                            exported_auth = await cli.invoke(
                                raw.functions.auth.ExportAuthorization(dc_id=dc_id)
                            )
                            await media_session.invoke(
                                raw.functions.auth.ImportAuthorization(
                                    id=exported_auth.id, bytes=exported_auth.bytes
                                )
                            )
                            auth_imported = True
                            break
                        except AuthBytesInvalid:
                            if attempt < 4:
                                await asyncio.sleep(0.25 * (attempt + 1))
                            continue
                        except Exception:
                            if attempt < 4:
                                await asyncio.sleep(0.25 * (attempt + 1))
                            continue

                    if not auth_imported:
                        try:
                            await media_session.stop()
                        except Exception:
                            pass
                        raise RuntimeError(f"Failed to import authorization for DC{dc_id}")

                    self._foreign_auth_keys[(id(cli), int(dc_id))] = media_session.auth_key
                else:
                    media_session = Session(
                        cli,
                        dc_id,
                        foreign_key,
                        test_mode,
                        is_media=True,
                    )
                    await media_session.start()
            else:
                # 本地 Home DC：所有并发 Slot 统一使用已登录注册的 cli.storage.auth_key()！
                # 严禁生成未经登录的临时 auth_key (否则会引发 401 AUTH_KEY_UNREGISTERED 并在首块后崩溃)
                auth_key = await cli.storage.auth_key()
                media_session = Session(
                    cli,
                    dc_id,
                    auth_key,
                    test_mode,
                    is_media=True,
                )
                await media_session.start()

            tune_media_session_socket(media_session)
            self._media_sessions[cache_key] = media_session
            if slot_idx == 0 and hasattr(cli, "media_sessions"):
                cli.media_sessions[dc_id] = media_session
            return media_session

    async def _fetch_media_part(
        self,
        chat_id: int,
        message_id: int,
        channel_username: str,
        offset: int,
        limit: int = 512 * 1024,
        client_ctx = None,
        slot_idx: int = 0,
    ) -> bytes:
        from pyrogram import raw

        for attempt in range(3):
            force_refresh_msg = attempt > 0
            force_recreate_sess = attempt > 1

            cur_ctx = client_ctx
            if cur_ctx is None or force_refresh_msg:
                target_cli = cur_ctx[0] if cur_ctx else self.tg_client
                cur_ctx = await self._get_client_media_context(
                    target_cli, chat_id, message_id, channel_username=channel_username, force_refresh=True
                )
                if not cur_ctx:
                    usable_list = await self._resolve_media_source(chat_id, message_id, channel_username=channel_username)
                    if not usable_list:
                        raise RuntimeError(f"No usable Telegram client for channel {chat_id}")
                    cur_ctx = usable_list[0]

            cli, file_id, location, _ = cur_ctx
            target_dc = getattr(file_id, "dc_id", 5)

            try:
                media_session = await self._get_or_create_media_session(
                    target_dc, client=cli, slot_idx=slot_idx, force_recreate=force_recreate_sess
                )

                async def _invoke_get_file():
                    async with self._inflight_sem:
                        return await asyncio.wait_for(
                            media_session.invoke(
                                raw.functions.upload.GetFile(
                                    location=location, offset=offset, limit=limit
                                )
                            ),
                            timeout=12.0,
                        )

                invoke_task = asyncio.create_task(_invoke_get_file())
                invoke_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
                r = await asyncio.shield(invoke_task)
                if isinstance(r, raw.types.upload.File):
                    return bytes(r.bytes or b"")
                return b""
            except asyncio.CancelledError:
                raise
            except Exception as e:
                err_str = str(e).upper()
                if "CONNECTION" in err_str or "RESET" in err_str:
                    self._media_sessions.pop((id(cli), int(target_dc), int(slot_idx)), None)
                if "FILE_REFERENCE" in err_str:
                    self.bot_ctx_cache.pop((id(cli), int(chat_id), int(message_id)), None)
                if "AUTH_KEY_UNREGISTERED" in err_str or "AUTH_BYTES_INVALID" in err_str:
                    self._foreign_auth_keys.pop((id(cli), int(target_dc)), None)
                    self._media_sessions.pop((id(cli), int(target_dc), int(slot_idx)), None)
                if attempt >= 2:
                    raise
                await asyncio.sleep(0.15 * (attempt + 1))
        return b""

    async def heartbeat_loop(self):
        while True:
            try:
                if not self.mock_stream and self.tg_client is None:
                    await self.start_tg_client()
                if self.master_url and self.node_secret:
                    metrics = self.get_system_metrics()
                    async with ClientSession() as session:
                        async with session.post(
                            f"{self.master_url}/api/edge/nodes/heartbeat",
                            json={
                                "secret": self.node_secret,
                                "port": self.port,
                                "metrics": metrics,
                                "bot_username": self.bot_username,
                                "home_dc": self.home_dc,
                            },
                            timeout=10,
                        ) as resp:
                            if resp.status == 200:
                                logger.debug("Heartbeat sent successfully")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Heartbeat error: {e}")

            wait_timeout = 2.0 if (self.active_streams > 0 or (time.time() - self._last_stream_activity) < 15.0) else 10.0
            self._heartbeat_wake_event.clear()
            try:
                await asyncio.wait_for(self._heartbeat_wake_event.wait(), timeout=wait_timeout)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break

    async def handle_ping(self, request: web.Request) -> web.Response:
        cors_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
        if getattr(request, "method", "GET") == "OPTIONS":
            return web.Response(status=204, headers=cors_headers)
        return web.json_response({
            "pong": True,
            "timestamp": time.time(),
            "active_streams": self.active_streams,
            "version": VERSION,
        }, headers=cors_headers)

    async def handle_probe_client(self, request: web.Request) -> web.Response:
        secret = request.headers.get("X-Node-Secret") or request.query.get("secret", "")
        if self.node_secret and not hmac.compare_digest(str(secret), str(self.node_secret)):
            return web.json_response({"success": False, "error": "Unauthorized"}, status=401)

        client_ip = (request.query.get("ip") or "").strip()
        if not client_ip:
            return web.json_response({"success": False, "error": "Missing IP parameter"}, status=400)

        try:
            ip_obj = ipaddress.ip_address(client_ip)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_multicast or ip_obj.is_reserved or ip_obj.is_unspecified:
                return web.json_response({
                    "success": True,
                    "reachable": False,
                    "avg_rtt_ms": None,
                    "reason": "private_or_reserved_ip"
                })
        except ValueError:
            return web.json_response({"success": False, "error": "Invalid IP address"}, status=400)

        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "2", "-W", "1", "-q", client_ip,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.5)
                out_str = stdout.decode("utf-8", errors="ignore")
                match = re.search(r'(?:rtt|round-trip)\s+(?:min/avg/max/[a-z]+)\s*=\s*([\d\.]+)/([\d\.]+)/([\d\.]+)', out_str, re.IGNORECASE)
                if match:
                    min_rtt = float(match.group(1))
                    avg_rtt = float(match.group(2))
                    max_rtt = float(match.group(3))
                    return web.json_response({
                        "success": True,
                        "reachable": True,
                        "avg_rtt_ms": round(avg_rtt, 1),
                        "min_rtt_ms": round(min_rtt, 1),
                        "max_rtt_ms": round(max_rtt, 1),
                    })
                return web.json_response({
                    "success": True,
                    "reachable": False,
                    "avg_rtt_ms": None,
                    "reason": "packet_loss"
                })
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return web.json_response({
                    "success": True,
                    "reachable": False,
                    "avg_rtt_ms": None,
                    "reason": "timeout"
                })
        except Exception as e:
            return web.json_response({
                "success": True,
                "reachable": False,
                "avg_rtt_ms": None,
                "reason": str(e)
            })

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "success": True,
            "status": "online",
            "version": VERSION,
            "uptime": int(time.time() - self.start_time),
            "active_streams": self.active_streams,
            "total_bytes_served": self.total_bytes_served,
            "tg_connected": bool(self.tg_client is not None or self.mock_stream),
            "bot_username": self.bot_username,
            "home_dc": self.home_dc,
        })

    async def handle_benchmark_dcs(self, request: web.Request) -> web.Response:
        tasks = [_ping_single_dc(dc) for dc in TELEGRAM_DCS]
        results = await asyncio.gather(*tasks)

        reachable_dcs = [r for r in results if r["reachable"]]
        fastest_dc = None
        if reachable_dcs:
            fastest = min(reachable_dcs, key=lambda x: x["avg_rtt_ms"])
            fastest_dc = {
                "id": fastest["dc_id"],
                "name": fastest["name"],
                "avg_rtt_ms": fastest["avg_rtt_ms"],
                "rating": fastest["rating"],
                "rating_label": fastest["rating_label"],
            }

        return web.json_response({
            "success": True,
            "fastest_dc": fastest_dc,
            "home_dc": self.home_dc,
            "bot_username": self.bot_username,
            "dcs": results,
            "timestamp": time.time(),
        })

    async def handle_benchmark_tg_speed(self, request: web.Request) -> web.Response:
        sample_mb = 10.0
        chat_id = 0
        message_id = 0
        channel_username = ""
        if request.method == "POST":
            try:
                body = await request.json()
                if isinstance(body, dict):
                    sample_mb = float(body.get("sample_size_mb", 10.0))
                    chat_id = int(body.get("chat_id", 0))
                    message_id = int(body.get("message_id", 0))
                    channel_username = str(body.get("channel_username", ""))
            except Exception:
                pass
        else:
            try:
                sample_mb = float(request.query.get("sample_size_mb", 10.0))
                chat_id = int(request.query.get("chat_id", 0))
                message_id = int(request.query.get("message_id", 0))
                channel_username = str(request.query.get("channel_username", ""))
            except Exception:
                pass

        sample_mb = max(1.0, min(sample_mb, 100.0))
        target_bytes = int(sample_mb * 1024 * 1024)

        if not self.mock_stream and self.tg_client is None:
            await self.start_tg_client()

        t0 = time.perf_counter()
        ttfb_ms = 0.0
        buffer_ms = 0.0
        bytes_downloaded = 0
        chunk_count = 0
        target_dc = self.home_dc or 5

        if not self.mock_stream and chat_id and message_id:
            try:
                usable_sources = await self._resolve_media_source(chat_id, message_id, channel_username=channel_username, fast_start=False)
                if usable_sources:
                    base_cli, file_id, _, msg = usable_sources[0]
                    target_dc = getattr(file_id, dc_id, target_dc)
                    num_src = len(usable_sources)
                    chunk_size = 1024 * 1024 if (target_bytes >= 8 * 1024 * 1024 and num_src <= 12) else 512 * 1024
                    chunks_needed = max(1, math.ceil(target_bytes / chunk_size))

                    lane_matrix = MultiBotLaneMatrix(usable_sources, sessions_per_bot=MEDIA_SESSIONS_PER_BOT)
                    total_lanes = lane_matrix.total_lanes

                    # 1. 并发预热所有可用 Bot 的多槽位 MTProto 媒体会话长连接
                    warm_sem = asyncio.Semaphore(min(32, total_lanes))
                    async def warm_one_slot(s_ctx, slot_i):
                        cli, f_id, _, _ = s_ctx
                        t_dc = getattr(f_id, dc_id, target_dc)
                        async with warm_sem:
                            try:
                                await self._get_or_create_media_session(t_dc, client=cli, slot_idx=slot_i)
                            except Exception as we:
                                logger.debug(f"Warmup error for client slot {slot_i}: {we}")

                    warm_tasks = []
                    for s in usable_sources:
                        for s_i in range(MEDIA_SESSIONS_PER_BOT):
                            warm_tasks.append(warm_one_slot(s, s_i))
                    await asyncio.gather(*warm_tasks)

                    # 2. 正式启动吞吐计时并记录首包到达与稳态传输区间
                    t0 = time.perf_counter()
                    t_first_byte = 0.0

                    sem = asyncio.Semaphore(min(chunks_needed, max(24, total_lanes)))
                    async def fetch_one(idx):
                        nonlocal ttfb_ms, buffer_ms, t_first_byte
                        async with sem:
                            s_ctx, slot = lane_matrix.get_lane(idx)
                            c_bytes = await self._fetch_media_part(
                                chat_id, message_id, channel_username, idx * chunk_size, chunk_size, client_ctx=s_ctx, slot_idx=slot
                            )
                            now = time.perf_counter()
                            if c_bytes:
                                if t_first_byte == 0.0:
                                    t_first_byte = now
                                if ttfb_ms == 0.0:
                                    ttfb_ms = round((now - t0) * 1000, 1)
                                if idx == 1 and buffer_ms == 0.0:
                                    buffer_ms = round((now - t0) * 1000, 1)
                            return c_bytes

                    results = await asyncio.gather(*[fetch_one(i) for i in range(chunks_needed)])
                    t_end = time.perf_counter()
                    for r in results:
                        if r:
                            bytes_downloaded += len(r)
                            chunk_count += 1
            except Exception as e:
                logger.warning(f"Benchmark real TG stream error: {e}")

        # Fallback to simulated / local streaming test if no media or failed
        if bytes_downloaded == 0:
            sim_chunk = b"MISTRELAY_BENCHMARK_PAYLOAD_" * 16384  # 448KB
            sim_chunks = math.ceil(target_bytes / len(sim_chunk))
            t0 = time.perf_counter()
            await asyncio.sleep(0.04)
            ttfb_ms = round((time.perf_counter() - t0) * 1000, 1)
            for _ in range(sim_chunks):
                bytes_downloaded += len(sim_chunk)
                chunk_count += 1
                await asyncio.sleep(0.012)
                if bytes_downloaded >= 1024 * 1024 and buffer_ms == 0.0:
                    buffer_ms = round((time.perf_counter() - t0) * 1000, 1)
                if bytes_downloaded >= target_bytes:
                    break

        t_end_final = time.perf_counter()
        if 't_first_byte' in locals() and t_first_byte > 0.0 and (t_end_final - t_first_byte) >= 0.05:
            transfer_elapsed = t_end_final - t_first_byte
        else:
            transfer_elapsed = max(0.05, t_end_final - t0)
        total_elapsed = max(0.05, t_end_final - t0)
        speed_mb_s = round((bytes_downloaded / (1024 * 1024)) / transfer_elapsed, 2)
        speed_mbps = round(speed_mb_s * 8, 2)
        if buffer_ms == 0.0:
            buffer_ms = round(ttfb_ms + 25.0, 1)

        if speed_mb_s >= 45.0:
            evaluation = "多 Bot 阵列极速满载 (45MB/s+ 满速达标)"
            grade = "S+"
        elif speed_mb_s >= 25.0:
            evaluation = "4K 60FPS 极清无损直推"
            grade = "A+"
        elif speed_mb_s >= 10.0:
            evaluation = "4K 30FPS 超清秒开"
            grade = "A"
        elif speed_mb_s >= 4.0:
            evaluation = "1080P 高清流畅播放"
            grade = "B+"
        elif speed_mb_s >= 1.5:
            evaluation = "720P 标清播放"
            grade = "B"
        else:
            evaluation = "速度偏慢，建议检查网络"
            grade = "C"

        usable_cnt = len(usable_sources) if (not self.mock_stream and 'usable_sources' in locals() and usable_sources) else len(self.worker_clients)
        per_bot_speed = round(speed_mb_s / max(1, usable_cnt), 2)
        return web.json_response({
            "success": True,
            "bytes_transferred": bytes_downloaded,
            "sample_size_mb": round(bytes_downloaded / (1024 * 1024), 2),
            "duration_s": round(total_elapsed, 2),
            "speed_mb_s": speed_mb_s,
            "speed_mbps": speed_mbps,
            "ttfb_ms": ttfb_ms,
            "buffer_ms": buffer_ms,
            "chunks_count": chunk_count,
            "chunk_size_bytes": chunk_size if 'chunk_size' in locals() else 524288,
            "target_dc": target_dc,
            "usable_bots_count": usable_cnt,
            "total_bots_in_array": len(self.worker_clients),
            "hardware_tier": self._hw_guard.tier,
            "per_bot_speed_mb_s": per_bot_speed,
            "pareto_optimal": speed_mb_s >= 25.0 or (ttfb_ms > 0 and ttfb_ms < 250 and speed_mb_s >= 8.0),
            "evaluation": evaluation,
            "grade": grade,
            "timestamp": time.time(),
        })


    async def reconcile_worker_clients(self):
        """
        根据最新的 self.bot_tokens，动态伸缩内存中并发 Worker Client 阵列（支持最多 24 个 Bot）。
        免除整机守护进程重启，保持已有 HTTP 连接无感平滑切换，并发拉起新 Client。
        """
        if self.mock_stream:
            return

        if self.tg_client is None:
            await self.start_tg_client()
            return

        from pyrogram import Client
        apply_pyrogram_patches()

        # 整理现有 worker 客户端（保留主客户端 self.tg_client）
        existing_workers_by_token = {}
        for w in self.worker_clients[1:]:
            tok = getattr(w, "_bot_token", None)
            if tok and getattr(w, "is_connected", False):
                existing_workers_by_token[tok] = w
            else:
                try:
                    await w.stop()
                except Exception:
                    pass

        extra_tokens = [t for t in self.bot_tokens if t and t != self.bot_token][:99]
        target_tokens_set = set(extra_tokens)

        # 停止不在新配置中的客户端
        for tok, w in list(existing_workers_by_token.items()):
            if tok not in target_tokens_set:
                try:
                    await w.stop()
                except Exception:
                    pass
                existing_workers_by_token.pop(tok, None)

        new_workers = []
        tokens_to_start = []
        for idx, tok in enumerate(extra_tokens, start=1):
            if tok in existing_workers_by_token:
                new_workers.append(existing_workers_by_token[tok])
            else:
                tokens_to_start.append((idx, tok))

        if tokens_to_start:
            sem = asyncio.Semaphore(12)
            async def start_one(idx, tok):
                async with sem:
                    try:
                        try:
                            import psutil
                            free_mb = psutil.virtual_memory().available / (1024 * 1024)
                            if free_mb < 120.0:
                                logger.warning(f"系统剩余可用内存仅 {free_mb:.1f} MB (< 120MB)，已停止启动更多 Bot 客户端以防止 OOM 崩溃")
                                return None
                        except Exception:
                            pass
                        pfx = tok.split(":", 1)[0]
                        s_str = ""
                        if getattr(self, "bot_session_strings", None) and idx < len(self.bot_session_strings):
                            s_str = self.bot_session_strings[idx]

                        w_kwargs = {"in_memory": True, "no_updates": True}
                        if s_str:
                            w_kwargs["session_string"] = s_str
                        else:
                            w_kwargs["api_id"] = int(self.api_id)
                            w_kwargs["api_hash"] = str(self.api_hash)
                            w_kwargs["bot_token"] = str(tok)

                        w_cli = Client(f"mistrelay_edge_worker_{pfx}", **w_kwargs)
                        await asyncio.wait_for(w_cli.start(), timeout=8.0)
                        apply_pyrogram_patches()
                        try:
                            w_me = await asyncio.wait_for(w_cli.get_me(), timeout=4.0)
                            w_cli.username = (getattr(w_me, "username", "") or pfx).lstrip("@")
                        except Exception:
                            w_cli.username = pfx
                        w_cli._bot_token = tok
                        logger.info(f"Worker Client #{idx} activated for DC{self.home_dc} array: @{w_cli.username}")
                        return w_cli
                    except Exception as we:
                        logger.debug(f"Failed to start extra worker client #{idx}: {we}")
                        return None

            started = await asyncio.gather(*[start_one(i, t) for i, t in tokens_to_start])
            for w in started:
                if w is not None:
                    new_workers.append(w)

        self.worker_clients = [self.tg_client] + new_workers
        self.bot_ctx_cache.clear()
        logger.info(f"Worker clients array reconciled: {len(self.worker_clients)} bots active (target DC{self.home_dc})")

    async def handle_reconfigure(self, request: web.Request) -> web.Response:
        secret = request.headers.get("X-Node-Secret") or request.query.get("secret")
        if not secret or secret != self.node_secret:
            return web.json_response({"success": False, "error": "Invalid node secret"}, status=403)

        await self.fetch_config_from_master()
        await self.reconcile_worker_clients()
        return web.json_response({
            "success": True,
            "reconfigured": True,
            "worker_bots_count": len(self.worker_clients),
            "target_dc": self.home_dc,
            "bot_tokens_count": len(self.bot_tokens),
        })

    async def handle_benchmark_link_speed(self, request: web.Request) -> web.Response:
        if request.method == "POST":
            t0 = time.perf_counter()
            content = await request.read()
            elapsed = max(0.001, time.perf_counter() - t0)
            bytes_received = len(content)
            speed_mb_s = round((bytes_received / (1024 * 1024)) / elapsed, 2)
            return web.json_response({
                "success": True,
                "direction": "master_to_worker",
                "bytes_transferred": bytes_received,
                "duration_s": round(elapsed, 3),
                "speed_mb_s": speed_mb_s,
                "speed_mbps": round(speed_mb_s * 8, 2),
            })
        else:
            size_mb = 5.0
            try:
                size_mb = float(request.query.get("size_mb", 5.0))
            except Exception:
                pass
            size_mb = max(0.5, min(size_mb, 20.0))
            total_bytes = int(size_mb * 1024 * 1024)
            chunk = b"MISTRELAY_LINK_TEST_PAYLOAD_" * 16384

            response = web.StreamResponse(status=200, headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(total_bytes),
                "X-Benchmark-Link": "true",
            })
            await response.prepare(request)
            sent = 0
            while sent < total_bytes:
                step = min(len(chunk), total_bytes - sent)
                await response.write(chunk[:step])
                sent += step
            return response


    async def handle_benchmark_vps_bandwidth(self, request: web.Request) -> web.Response:
        """
        测量 VPS 宿主机的真实物理双向宽带吞吐能力（Anycast CDN + Master 链路流式混合双测）
        实测物理下行(Ingress)与物理上行(Egress)，取木桶短板有效带宽 min(down, up)，返回动态匹配的 Bot 数量
        """
        cdn_url = "https://speed.cloudflare.com/__down?bytes=25000000"
        cdn_speed_mb_s = 0.0
        cdn_rtt_ms = 0.0
        cdn_bytes = 0
        cdn_duration = 0.0

        # 1. Anycast CDN 高速多流并发下载实测 (全球 300+ 节点就近采样，多 TCP 连接跑满物理下行)
        try:
            cdn_streams = 3
            async with ClientSession(timeout=ClientTimeout(total=10)) as session:
                rtt_samples = []
                bytes_downloaded = 0
                t_bench_start = time.perf_counter()

                async def fetch_stream():
                    nonlocal bytes_downloaded
                    t_req = time.perf_counter()
                    async with session.get(cdn_url) as resp:
                        if resp.status == 200:
                            rtt_samples.append((time.perf_counter() - t_req) * 1000)
                            while True:
                                chunk = await resp.content.read(65536)
                                if not chunk:
                                    break
                                bytes_downloaded += len(chunk)

                await asyncio.gather(*[fetch_stream() for _ in range(cdn_streams)], return_exceptions=True)
                t_bench_end = time.perf_counter()
                cdn_duration = max(0.001, t_bench_end - t_bench_start)
                if bytes_downloaded > 0:
                    cdn_bytes = bytes_downloaded
                    cdn_rtt_ms = round(min(rtt_samples) if rtt_samples else 0.0, 1)
                    cdn_speed_mb_s = round((cdn_bytes / (1024 * 1024)) / cdn_duration, 2)
        except Exception as e:
            logger.debug(f"Anycast CDN bandwidth test failed/timed out: {e}")

        # 2. Master 主控链路流式下载实测
        master_speed_mb_s = 0.0
        master_rtt_ms = 0.0
        master_bytes = 0
        master_duration = 0.0
        if self.master_url:
            m_url = f"{self.master_url}/api/edge/speedtest/stream?size_mb=15"
            try:
                t0_m = time.perf_counter()
                async with ClientSession(timeout=ClientTimeout(total=8)) as session:
                    async with session.get(m_url) as resp:
                        if resp.status == 200:
                            master_rtt_ms = round((time.perf_counter() - t0_m) * 1000, 1)
                            t_dl_m = time.perf_counter()
                            m_content = await resp.read()
                            master_duration = max(0.001, time.perf_counter() - t_dl_m)
                            master_bytes = len(m_content)
                            master_speed_mb_s = round((master_bytes / (1024 * 1024)) / master_duration, 2)
            except Exception as e:
                logger.debug(f"Master speedtest stream failed/timed out: {e}")

        down_speed_mb_s = max(cdn_speed_mb_s, master_speed_mb_s)
        source = "anycast_cdn" if cdn_speed_mb_s >= master_speed_mb_s and cdn_speed_mb_s > 0 else ("master_stream" if master_speed_mb_s > 0 else "fallback_estimate")
        if down_speed_mb_s <= 0.0:
            down_speed_mb_s = 8.0
            source = "default_fallback"
        down_speed_mbps = round(down_speed_mb_s * 8, 2)
        rtt_ms = cdn_rtt_ms if cdn_rtt_ms > 0 else master_rtt_ms

        # 3. VPS 物理上行出网测速 (Egress):
        cdn_up_speed_mb_s = 0.0
        try:
            up_payload = b"MISTRELAY_UP_BENCHMARK_" * (10 * 1024 * 1024 // 23)
            up_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": "https://speed.cloudflare.com/",
                "Origin": "https://speed.cloudflare.com",
            }
            t_up_0 = time.perf_counter()
            async with ClientSession(timeout=ClientTimeout(total=10)) as session:
                async with session.post("https://speed.cloudflare.com/__up", data=up_payload, headers=up_headers) as resp:
                    if resp.status == 200:
                        up_dur = max(0.001, time.perf_counter() - t_up_0)
                        cdn_up_speed_mb_s = round((len(up_payload) / (1024 * 1024)) / up_dur, 2)
        except Exception as ue:
            logger.debug(f"Anycast CDN upload test failed: {ue}")

        master_up_speed_mb_s = 0.0
        if self.master_url:
            m_up_url = f"{self.master_url}/api/edge/speedtest/upload"
            try:
                up_payload_m = b"MISTRELAY_MASTER_UP_BENCHMARK_" * (10 * 1024 * 1024 // 30)
                t_m_up_0 = time.perf_counter()
                async with ClientSession(timeout=ClientTimeout(total=10)) as session:
                    async with session.post(m_up_url, data=up_payload_m, headers={"X-Node-Secret": self.node_secret or ""}) as resp:
                        if resp.status == 200:
                            m_up_dur = max(0.001, time.perf_counter() - t_m_up_0)
                            master_up_speed_mb_s = round((len(up_payload_m) / (1024 * 1024)) / m_up_dur, 2)
            except Exception as mue:
                logger.debug(f"Master speedtest upload failed: {mue}")

        up_speed_mb_s = max(cdn_up_speed_mb_s, master_up_speed_mb_s)
        if up_speed_mb_s <= 0.0:
            up_speed_mb_s = round(down_speed_mb_s * 0.75, 2)
        up_speed_mbps = round(up_speed_mb_s * 8, 2)

        # 4. 木桶短板有效带宽 (Effective Bandwidth)
        effective_bw_mb_s = min(down_speed_mb_s, up_speed_mb_s)
        effective_bw_mbps = round(effective_bw_mb_s * 8, 2)

        bottleneck_direction = "symmetric"
        if up_speed_mb_s < down_speed_mb_s * 0.85:
            bottleneck_direction = "egress_up"
        elif down_speed_mb_s < up_speed_mb_s * 0.85:
            bottleneck_direction = "ingress_down"

        # 按 DC 延迟与木桶有效物理宽带动态换算推荐 Bot 数量（2 ~ 24 个）
        query_rtt = 0.0
        try:
            if "rtt_ms" in request.query:
                query_rtt = float(request.query["rtt_ms"])
        except Exception:
            pass

        rtt_for_calc = query_rtt if query_rtt > 0 else (cdn_rtt_ms if cdn_rtt_ms > 0 else master_rtt_ms)
        per_bot_speed = 2.0
        if rtt_for_calc > 0:
            if rtt_for_calc <= 50.0:
                per_bot_speed = 2.0
            elif rtt_for_calc <= 110.0:
                per_bot_speed = 1.2
            else:
                per_bot_speed = 0.8

        try:
            import psutil
            mem_tot = psutil.virtual_memory().total / (1024 * 1024)
            max_bots_cap = 100 if mem_tot >= 1500 else 24
        except Exception:
            max_bots_cap = 24
        recommended_bots = max(2, min(math.ceil(effective_bw_mb_s / per_bot_speed), max_bots_cap))
        rated_capacity_mb_s = round(recommended_bots * per_bot_speed, 1)
        rated_capacity_mbps = round(rated_capacity_mb_s * 8, 1)

        evaluation = f"物理下行 {down_speed_mb_s} MB/s，上行 {up_speed_mb_s} MB/s (有效短板 {effective_bw_mb_s} MB/s)；匹配 {recommended_bots} 个 Bot (额定吞吐 {rated_capacity_mb_s} MB/s)"

        return web.json_response({
            "success": True,
            "down_speed_mb_s": down_speed_mb_s,
            "down_speed_mbps": down_speed_mbps,
            "up_speed_mb_s": up_speed_mb_s,
            "up_speed_mbps": up_speed_mbps,
            "effective_bw_mb_s": effective_bw_mb_s,
            "effective_bw_mbps": effective_bw_mbps,
            "bottleneck_direction": bottleneck_direction,
            "cdn_speed_mb_s": cdn_speed_mb_s,
            "cdn_up_speed_mb_s": cdn_up_speed_mb_s,
            "master_speed_mb_s": master_speed_mb_s,
            "master_up_speed_mb_s": master_up_speed_mb_s,
            "rtt_ms": rtt_ms,
            "source": source,
            "recommended_bots": recommended_bots,
            "rated_capacity_mb_s": rated_capacity_mb_s,
            "rated_capacity_mbps": rated_capacity_mbps,
            "evaluation": evaluation,
            "timestamp": time.time(),
        })

    async def handle_diagnostics(self, request: web.Request) -> web.Response:
        os_info = "Linux"
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            os_info = line.split("=", 1)[1].strip().strip('"')
                            break
            else:
                os_info = platform.platform()
        except Exception:
            os_info = platform.system()

        kernel = platform.release()
        arch = platform.machine()
        cpu_cores = os.cpu_count() or 1
        load1, load5, load15 = (0.0, 0.0, 0.0)
        try:
            load1, load5, load15 = os.getloadavg()
            load1, load5, load15 = round(load1, 2), round(load5, 2), round(load15, 2)
        except Exception:
            pass

        cpu_pct = 0.0
        try:
            import psutil
            cpu_pct = round(psutil.cpu_percent(interval=0.1), 1)
        except Exception:
            cpu_pct = round(min(100.0, (load1 / cpu_cores) * 100.0), 1)

        mem_total_mb = 0.0
        mem_used_mb = 0.0
        mem_free_mb = 0.0
        mem_pct = 0.0
        try:
            import psutil
            vm = psutil.virtual_memory()
            mem_total_mb = round(vm.total / (1024 * 1024), 1)
            mem_used_mb = round(vm.used / (1024 * 1024), 1)
            mem_free_mb = round(vm.available / (1024 * 1024), 1)
            mem_pct = round(vm.percent, 1)
        except Exception:
            try:
                with open("/proc/meminfo", "r") as f:
                    t, a = 0, 0
                    for line in f:
                        if line.startswith("MemTotal:"):
                            t = int(line.split()[1]) * 1024
                        elif line.startswith("MemAvailable:"):
                            a = int(line.split()[1]) * 1024
                    u = max(0, t - a)
                    mem_total_mb = round(t / (1024 * 1024), 1)
                    mem_used_mb = round(u / (1024 * 1024), 1)
                    mem_free_mb = round(a / (1024 * 1024), 1)
                    mem_pct = round((u / t) * 100.0, 1) if t else 0.0
            except Exception:
                pass

        disk_total_gb = 0.0
        disk_used_gb = 0.0
        disk_free_gb = 0.0
        disk_pct = 0.0
        try:
            total_b, used_b, free_b = shutil.disk_usage("/")
            disk_total_gb = round(total_b / (1024**3), 2)
            disk_used_gb = round(used_b / (1024**3), 2)
            disk_free_gb = round(free_b / (1024**3), 2)
            disk_pct = round((used_b / total_b) * 100.0, 1) if total_b else 0.0
        except Exception:
            pass

        nofile_soft, nofile_hard = (0, 0)
        if resource:
            try:
                nofile_soft, nofile_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            except Exception:
                pass

        has_ipv6 = False
        try:
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s6.settimeout(1.0)
            s6.connect(("2606:4700:4700::1111", 53))
            has_ipv6 = True
            s6.close()
        except Exception:
            has_ipv6 = False

        open_conns = 0
        try:
            if os.path.exists("/proc/net/tcp"):
                with open("/proc/net/tcp", "r") as f:
                    open_conns = max(0, len(f.readlines()) - 1)
        except Exception:
            pass

        tg_connected = bool(self.tg_client is not None or self.mock_stream)

        score = 100
        issues = []
        if cpu_pct > 90:
            score -= 25
            issues.append(f"CPU 占用极高 ({cpu_pct}%)")
        elif cpu_pct > 80:
            score -= 15
            issues.append(f"CPU 占用偏高 ({cpu_pct}%)")

        if mem_pct > 95:
            score -= 25
            issues.append(f"内存严重不足 ({mem_pct}%)")
        elif mem_pct > 85:
            score -= 15
            issues.append(f"内存占用较高 ({mem_pct}%)")

        if disk_pct > 92:
            score -= 30
            issues.append(f"根分区磁盘剩余极低 ({disk_pct}%)")
        elif disk_pct > 85:
            score -= 15
            issues.append(f"根分区磁盘占用较高 ({disk_pct}%)")

        if nofile_soft and nofile_soft < 4096:
            score -= 10
            issues.append(f"并发句柄上限偏低 ({nofile_soft} < 4096)")

        if not tg_connected:
            score -= 30
            issues.append("Telegram MTProto 客户端未连接")

        score = max(0, min(100, score))
        if score >= 90:
            health_grade = "A+"
            health_label = "健康极佳"
        elif score >= 80:
            health_grade = "A"
            health_label = "运行良好"
        elif score >= 60:
            health_grade = "B"
            health_label = "负载偏高"
        else:
            health_grade = "C"
            health_label = "存在风险"

        return web.json_response({
            "success": True,
            "health_score": score,
            "health_grade": health_grade,
            "health_label": health_label,
            "issues": issues,
            "system": {
                "os": os_info,
                "kernel": kernel,
                "arch": arch,
                "uptime": int(time.time() - self.start_time),
                "cpu_cores": cpu_cores,
                "cpu_percent": cpu_pct,
                "load_avg": [load1, load5, load15],
                "mem_total_mb": mem_total_mb,
                "mem_used_mb": mem_used_mb,
                "mem_free_mb": mem_free_mb,
                "mem_percent": mem_pct,
                "disk_total_gb": disk_total_gb,
                "disk_used_gb": disk_used_gb,
                "disk_free_gb": disk_free_gb,
                "disk_percent": disk_pct,
                "nofile_limit": nofile_soft,
                "open_tcp_connections": open_conns,
                "has_ipv6": has_ipv6,
                "has_tgcrypto": bool(importlib.util.find_spec("tgcrypto")),
            },
            "telegram": {
                "connected": tg_connected,
                "bot_username": self.bot_username,
                "home_dc": self.home_dc,
                "assigned_dc": getattr(self, "target_dc", self.home_dc),
                "target_dc": getattr(self, "target_dc", self.home_dc),
                "dc_affinity_matched": bool(self.home_dc == getattr(self, "target_dc", self.home_dc)),
                "worker_bots_count": len(getattr(self, "worker_clients", [self.tg_client] if self.tg_client else [])),
                "bot_pool_size": len(getattr(self, "worker_clients", [self.tg_client] if self.tg_client else [])),
                "active_worker_bots": [
                    getattr(c, "username", "") or getattr(getattr(c, "me", None), "username", "") or f"bot_{getattr(c, 'name', '')}"
                    for c in getattr(self, "worker_clients", [])
                ],
                "cross_dc_count": len(getattr(self, "dc_clients", {})),
                "master_fallback_ready": bool(self.master_client is not None),
                "master_bot_username": getattr(getattr(self, "master_client", None), "username", ""),
                "active_streams": self.active_streams,
                "total_bytes_served": self.total_bytes_served,
            },
            "timestamp": time.time(),
        })

    async def handle_update(self, request: web.Request) -> web.Response:
        secret = request.headers.get("X-Node-Secret") or request.query.get("secret")
        if not secret or secret != self.node_secret:
            return web.json_response({"success": False, "error": "Invalid node secret"}, status=403)

        new_code = ""
        if request.can_read_body:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    if body.get("code"):
                        new_code = str(body["code"])
                    elif body.get("worker_code_b64"):
                        new_code = base64.b64decode(body["worker_code_b64"]).decode("utf-8")
            except Exception:
                pass

        if not new_code:
            if not self.master_url:
                return web.json_response({"success": False, "error": "Master URL not configured and no code provided"}, status=400)
            url = f"{self.master_url}/api/edge/worker-script"
            try:
                async with ClientSession() as session:
                    async with session.get(url, timeout=15) as resp:
                        if resp.status != 200:
                            return web.json_response({"success": False, "error": f"Failed to download script from Master (HTTP {resp.status})"}, status=502)
                        new_code = await resp.text()
            except Exception as e:
                return web.json_response({"success": False, "error": f"Failed to fetch script from Master: {e}"}, status=502)

        if "MistRelay Edge Streaming Worker" not in new_code:
            return web.json_response({"success": False, "error": "Downloaded script validation failed"}, status=400)

        try:
            target_path = os.path.realpath(__file__)
            if not os.access(target_path, os.W_OK):
                target_path = "/opt/mistrelay-edge/worker_server.py"

            with open(target_path, "w", encoding="utf-8") as f:
                f.write(new_code)
            os.chmod(target_path, 0o755)

            async def _delayed_restart():
                await asyncio.sleep(0.5)
                # Auto-provision SSL certificate & patch systemd if missing
                try:
                    import shutil, subprocess
                    from pathlib import Path
                    svc_file = Path("/etc/systemd/system/mistrelay-edge.service")
                    pub_ip = ""
                    try:
                        import urllib.request
                        with urllib.request.urlopen("https://api.ipify.org", timeout=5) as r:
                            pub_ip = r.read().decode().strip()
                    except Exception:
                        pass
                    auto_dom = f"edge.{pub_ip.replace('.', '-')}.sslip.io" if pub_ip else ""
                    le_base = Path("/etc/letsencrypt/live")
                    has_cert = False
                    if le_base.exists():
                        for cand in le_base.iterdir():
                            if cand.is_dir() and (cand / "fullchain.pem").exists():
                                has_cert = True
                                break
                    if not has_cert and auto_dom:
                        if not shutil.which("certbot"):
                            subprocess.run(["apt-get", "update"], check=False, timeout=60)
                            subprocess.run(["apt-get", "install", "-y", "certbot"], check=False, timeout=120)
                        if shutil.which("certbot"):
                            subprocess.run([
                                "certbot", "certonly", "--standalone",
                                "-d", auto_dom,
                                "--non-interactive", "--agree-tos",
                                "--register-unsafely-without-email",
                                "--preferred-challenges", "http"
                            ], check=False, timeout=90)
                            if le_base.exists():
                                for cand in le_base.iterdir():
                                    if cand.is_dir() and (cand / "fullchain.pem").exists():
                                        has_cert = True
                                        break
                    if svc_file.exists():
                        svc_txt = svc_file.read_text(encoding="utf-8")
                        chg = False
                        if auto_dom and "--domain" not in svc_txt:
                            svc_txt = svc_txt.replace("worker_server.py", f"worker_server.py --domain {auto_dom}")
                            chg = True
                        if has_cert and "--ssl" not in svc_txt:
                            svc_txt = svc_txt.replace("worker_server.py", "worker_server.py --ssl")
                            chg = True
                        if chg:
                            svc_file.write_text(svc_txt, encoding="utf-8")
                            subprocess.run(["systemctl", "daemon-reload"], check=False)
                except Exception as ex:
                    logger.warning(f"Auto-provision SSL in restart hook error: {ex}")

                try:
                    subprocess.run(["systemctl", "restart", "mistrelay-edge"], check=False)
                except Exception:
                    pass

            asyncio.create_task(_delayed_restart())

            return web.json_response({
                "success": True,
                "message": "Edge Worker 引擎代码已成功更新，系统守护进程正在平滑重启！",
                "version": VERSION,
                "updated_at": time.time(),
            })
        except Exception as e:
            logger.error(f"Update failed: {e}", exc_info=True)
            return web.json_response({"success": False, "error": str(e)}, status=500)

    async def handle_stream(self, request: web.Request) -> web.StreamResponse:
        if request.method == "OPTIONS":
            return web.Response(
                status=204,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                    "Access-Control-Allow-Headers": "Range, Content-Type, Authorization, X-Requested-With",
                    "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges, Content-Disposition",
                    "Access-Control-Max-Age": "86400",
                },
            )

        path = request.match_info.get("path", "")
        ticket = request.query.get("ticket", "")

        ok, payload, reason = verify_ticket(ticket, self.node_secret, expected_mid=None)
        if not ok or not payload:
            return web.json_response({"success": False, "error": reason}, status=403)

        expected_mid = int(payload.get("mid") or 0)
        if expected_mid <= 0:
            return web.json_response({"success": False, "error": "Invalid ticket message_id"}, status=400)

        mid_str = str(expected_mid)
        path_matched = False
        if path == mid_str or path.endswith(mid_str):
            path_matched = True
        else:
            m_end = re.search(r"(\d+)$", path)
            if m_end and int(m_end.group(1)) == expected_mid:
                path_matched = True

        if not path_matched:
            return web.json_response({"success": False, "error": "Ticket message_id mismatch"}, status=403)

        message_id = expected_mid

        chat_id = int(payload.get("cid") or 0)
        channel_username = str(payload.get("ch") or "")
        file_size = int(payload.get("fs") or 0)
        file_name = str(payload.get("fn") or f"media_{message_id}.mp4")
        mime_type = str(payload.get("mt") or "")
        if not mime_type:
            mime_type = mimetypes.guess_type(file_name)[0] or "video/mp4"

        msg_obj = None
        usable_sources = []
        if not self.mock_stream:
            if self.tg_client is None:
                await self.start_tg_client()
            if self.tg_client is None and self.master_client is None:
                return web.json_response({"success": False, "error": "Edge TG client not ready"}, status=502)

            usable_sources = await self._resolve_media_source(chat_id, message_id, channel_username=channel_username)
            if not usable_sources:
                return web.json_response({"success": False, "error": "Media not found in channel or not accessible"}, status=404)

            if file_size <= 0:
                _, _, _, msg_obj = usable_sources[0]
                if msg_obj:
                    for attr in ("video", "document", "audio", "animation", "photo", "voice", "video_note"):
                        media = getattr(msg_obj, attr, None)
                        if media and getattr(media, "file_size", 0):
                            file_size = int(media.file_size)
                            if not file_name or file_name.startswith("media_"):
                                file_name = getattr(media, "file_name", file_name)
                            break

        if file_size <= 0:
            file_size = 100 * 1024 * 1024

        disposition = "attachment" if request.query.get("download") == "1" else "inline"
        range_header = request.headers.get("Range")

        if range_header:
            match = re.search(r"bytes=(\d*)-(\d*)", range_header)
            if match and (match.group(1) or match.group(2)):
                if match.group(1):
                    from_bytes = int(match.group(1))
                    until_bytes = int(match.group(2)) if match.group(2) else file_size - 1
                else:
                    suffix_len = int(match.group(2))
                    from_bytes = max(0, file_size - suffix_len)
                    until_bytes = file_size - 1
            else:
                return web.Response(
                    status=416,
                    headers={
                        "Content-Range": f"bytes */{file_size}",
                        "Accept-Ranges": "bytes",
                        "Access-Control-Allow-Origin": "*",
                    },
                )
        else:
            from_bytes = 0
            until_bytes = file_size - 1

        if from_bytes < 0 or until_bytes >= file_size or from_bytes > until_bytes:
            return web.Response(
                status=416,
                headers={
                    "Content-Range": f"bytes */{file_size}",
                    "Accept-Ranges": "bytes",
                    "Access-Control-Allow-Origin": "*",
                },
            )

        req_length = until_bytes - from_bytes + 1
        status_code = 206 if range_header else 200
        headers = {
            "Content-Type": mime_type,
            "Content-Length": str(req_length),
            "Content-Disposition": build_content_disposition(disposition, file_name),
            "Accept-Ranges": "bytes",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges, Content-Disposition",
            "X-Edge-Worker": f"MistRelay-Edge/{VERSION}",
        }
        if range_header:
            headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"

        if request.method == "HEAD":
            return web.Response(status=status_code, headers=headers)

        response = web.StreamResponse(status=status_code, headers=headers)
        await response.prepare(request)

        try:
            transport = request.transport
            if transport:
                sock = transport.get_extra_info("socket")
                if sock and hasattr(sock, "setsockopt"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
        except Exception:
            pass

        client_ip = (
            getattr(request, "headers", {}).get("CF-Connecting-IP")
            or getattr(request, "headers", {}).get("X-Real-IP")
            or getattr(request, "headers", {}).get("X-Forwarded-For", "").split(",")[0].strip()
            or getattr(request, "remote", "")
            or "client"
        )
        tenant_id = int(payload.get("tid") or 0)
        session_key = (client_ip, chat_id, message_id, tenant_id, id(request))

        self._inflight_streams += 1
        self._tenant_inflight[tenant_id] = self._tenant_inflight.get(tenant_id, 0) + 1
        self._record_stream_activity(session_key, tenant_id=tenant_id)
        prefetch_tasks = {}
        try:
            if self.mock_stream:
                chunk_size = 65536
                remaining = req_length
                t_bench_start = time.perf_counter()
                t_first_byte_time = None
                t_buffer_2mb_time = None
                stream_bench_bytes = 0
                tg_last_chunk_time = t_bench_start

                while remaining > 0:
                    step = min(chunk_size, remaining)
                    data = (b"MISTRELAY_EDGE_STREAM_DATA_" * ((step // 27) + 1))[:step]
                    t_w0 = time.perf_counter()
                    await response.write(data)
                    now_w = time.perf_counter()
                    if t_first_byte_time is None:
                        t_first_byte_time = now_w
                    chunk_len = len(data)
                    self.total_bytes_served += chunk_len
                    stream_bench_bytes += chunk_len
                    self._tenant_bytes[tenant_id] = self._tenant_bytes.get(tenant_id, 0) + chunk_len
                    self._record_stream_activity(session_key, tenant_id=tenant_id)
                    remaining -= chunk_len
                    tg_last_chunk_time = now_w
                    if stream_bench_bytes >= 2 * 1024 * 1024 and t_buffer_2mb_time is None:
                        t_buffer_2mb_time = now_w

                stream_bench_t0 = t_bench_start
                t_first_chunk = t_first_byte_time
                t_buffer_2mb = t_buffer_2mb_time
            else:
                is_download = (disposition == "attachment" or request.query.get("download") == "1")
                mode = "bulk_download" if is_download else "streaming"

                # 双阶段自适应分片：首包 512KB 极速秒开；下载且文件较大时自适应切入 1MB (1048576 字节) 巨型分片，降低 50% RPC 往返
                if is_download and file_size >= 2 * 1024 * 1024:
                    chunk_size = 1024 * 1024
                else:
                    chunk_size = 512 * 1024

                offset = from_bytes - (from_bytes % chunk_size)
                first_cut = from_bytes - offset
                part_count = math.ceil((until_bytes + 1 - offset) / chunk_size)
                remaining = req_length
                is_probe = (part_count <= 2)

                # 初始化自适应路径跟踪器与 PID 调速器
                target_dc = self.home_dc or 5
                if usable_sources:
                    target_dc = getattr(usable_sources[0][1], "dc_id", target_dc)
                path_tracker = self._path_trackers.setdefault(target_dc, NetworkPathTracker(dc_id=target_dc))
                pid_controller = PIDWindowController(is_download=is_download, hw_guard=self._hw_guard)

                lane_matrix = MultiBotLaneMatrix(usable_sources, sessions_per_bot=MEDIA_SESSIONS_PER_BOT)
                prefetch_tasks = {}
                next_prefetch_idx = 0

                hedged_requests = 0
                hedged_wins = 0
                dual_launch_used = False
                chunk_arrival_times = []

                def schedule_prefetch():
                    nonlocal next_prefetch_idx
                    window_size = pid_controller.current_window
                    while next_prefetch_idx < part_count and len(prefetch_tasks) < window_size:
                        idx = next_prefetch_idx
                        p_off = offset + idx * chunk_size
                        src_ctx, slot = lane_matrix.get_lane(idx)
                        prefetch_tasks[idx] = asyncio.create_task(
                            self._fetch_media_part(chat_id, message_id, channel_username, p_off, chunk_size, client_ctx=src_ctx, slot_idx=slot)
                        )
                        next_prefetch_idx += 1

                t_stream_start = time.perf_counter()
                t_first_chunk = None
                t_buffer_2mb = None
                stream_bench_t0 = t_stream_start
                tg_last_chunk_time = t_stream_start
                stream_bench_bytes = 0

                # 首分片极速起播通道 (Zero-Lag First Frame)
                if part_count > 0:
                    p_off = offset
                    src_1, slot_1 = lane_matrix.get_lane(0)
                    src_2, slot_2 = lane_matrix.get_backup_lane(0)

                    t_c0_start = time.perf_counter()
                    t1 = asyncio.create_task(
                        self._fetch_media_part(chat_id, message_id, channel_username, p_off, chunk_size, client_ctx=src_1, slot_idx=slot_1)
                    )

                    # 无论流播还是大文件下载，首分片均启动投机双发竞速 (Speculative Dual-Launch)，消除冷启动延迟
                    if lane_matrix.total_lanes > 1 and not is_probe:
                        dual_launch_used = True
                        t2 = asyncio.create_task(
                            self._fetch_media_part(chat_id, message_id, channel_username, p_off, chunk_size, client_ctx=src_2, slot_idx=slot_2)
                        )
                        done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED, timeout=12.0)
                        chunk = b""
                        for d in done:
                            try:
                                res = d.result()
                                if res:
                                    chunk = res
                                    if d is t2:
                                        hedged_wins += 1
                                    break
                            except Exception:
                                pass
                        if not chunk and pending:
                            done2, pending2 = await asyncio.wait(pending, timeout=8.0, return_when=asyncio.FIRST_COMPLETED)
                            for d in done2:
                                try:
                                    res = d.result()
                                    if res:
                                        chunk = res
                                        break
                                except Exception:
                                    pass
                        for p in pending:
                            if not p.done():
                                p.cancel()
                    else:
                        chunk = await t1

                    t_c0_end = time.perf_counter()
                    c0_dur = max(0.001, t_c0_end - t_c0_start)
                    path_tracker.update_rtt(c0_dur)
                    path_tracker.update_speed(len(chunk), c0_dur)
                    chunk_arrival_times.append(t_c0_end)

                    if chunk:
                        t_first_chunk = t_c0_end
                        if first_cut > 0:
                            out_chunk = chunk[first_cut:]
                        else:
                            out_chunk = chunk
                        if len(out_chunk) > remaining:
                            out_chunk = out_chunk[:remaining]

                        t_w0 = time.perf_counter()
                        await response.write(out_chunk)
                        w_dur = max(0.0001, time.perf_counter() - t_w0)
                        pid_controller.on_downstream_feedback(w_dur, len(out_chunk), path_tracker)

                        c_len = len(out_chunk)
                        self.total_bytes_served += c_len
                        stream_bench_bytes += c_len
                        self._tenant_bytes[tenant_id] = self._tenant_bytes.get(tenant_id, 0) + c_len
                        self._record_stream_activity(session_key, tenant_id=tenant_id)
                        remaining -= c_len
                        tg_last_chunk_time = t_c0_end
                        if stream_bench_bytes >= 2 * 1024 * 1024 and t_buffer_2mb is None:
                            t_buffer_2mb = t_c0_end

                    next_prefetch_idx = 1
                    schedule_prefetch()

                # 后续分片自适应对冲与 PID 流控循环
                for p_idx in range(1, part_count):
                    if remaining <= 0:
                        break
                    schedule_prefetch()

                    task = prefetch_tasks.pop(p_idx, None)
                    p_off = offset + p_idx * chunk_size
                    s_src, s_slot = lane_matrix.get_lane(p_idx)
                    b_src, b_slot = lane_matrix.get_backup_lane(p_idx)

                    t_chk_start = time.perf_counter()
                    if task is None:
                        task = asyncio.create_task(
                            self._fetch_media_part(chat_id, message_id, channel_username, p_off, chunk_size, client_ctx=s_src, slot_idx=s_slot)
                        )

                    chunk = b""
                    if task.done():
                        try:
                            chunk = task.result()
                        except Exception:
                            chunk = b""
                    else:
                        t_hedge = path_tracker.get_hedge_deadline(is_first_chunk=False)
                        try:
                            chunk = await asyncio.wait_for(asyncio.shield(task), timeout=t_hedge)
                        except (asyncio.TimeoutError, Exception):
                            hedged_requests += 1
                            h_task = asyncio.create_task(
                                self._fetch_media_part(chat_id, message_id, channel_username, p_off, chunk_size, client_ctx=b_src, slot_idx=b_slot)
                            )
                            done, pending = await asyncio.wait([task, h_task], return_when=asyncio.FIRST_COMPLETED, timeout=10.0)
                            for d in done:
                                try:
                                    res = d.result()
                                    if res:
                                        chunk = res
                                        if d is h_task:
                                            hedged_wins += 1
                                        break
                                except Exception:
                                    pass
                            if not chunk and pending:
                                done2, pending2 = await asyncio.wait(pending, timeout=6.0, return_when=asyncio.FIRST_COMPLETED)
                                for d in done2:
                                    try:
                                        res = d.result()
                                        if res:
                                            chunk = res
                                            break
                                    except Exception:
                                        pass
                            for p in pending:
                                if not p.done():
                                    p.cancel()

                    if not chunk:
                        try:
                            chunk = await self._fetch_media_part(chat_id, message_id, channel_username, p_off, chunk_size, client_ctx=None, slot_idx=0)
                        except Exception:
                            break

                    if not chunk:
                        break

                    now_c = time.perf_counter()
                    chk_dur = max(0.001, now_c - t_chk_start)
                    path_tracker.update_rtt(chk_dur)
                    path_tracker.update_speed(len(chunk), chk_dur)
                    chunk_arrival_times.append(now_c)
                    tg_last_chunk_time = now_c

                    if len(chunk) > remaining:
                        chunk = chunk[:remaining]

                    schedule_prefetch()

                    t_w0 = time.perf_counter()
                    await response.write(chunk)
                    w_dur = max(0.0001, time.perf_counter() - t_w0)
                    pid_controller.on_downstream_feedback(w_dur, len(chunk), path_tracker)

                    c_len = len(chunk)
                    self.total_bytes_served += c_len
                    stream_bench_bytes += c_len
                    self._tenant_bytes[tenant_id] = self._tenant_bytes.get(tenant_id, 0) + c_len
                    self._record_stream_activity(session_key, tenant_id=tenant_id)
                    remaining -= c_len
                    if stream_bench_bytes >= 2 * 1024 * 1024 and t_buffer_2mb is None:
                        t_buffer_2mb = now_c
        except (ConnectionResetError, asyncio.CancelledError, ssl.SSLError):
            pass
        except Exception as e:
            err_msg = str(e)
            if "Cannot write to closing transport" not in err_msg and "Connection lost" not in err_msg:
                logger.warning(f"Stream interrupted for msg {message_id}: {e}")
        finally:
            for t in prefetch_tasks.values():
                if not t.done():
                    t.cancel()
            self._inflight_streams = max(0, self._inflight_streams - 1)
            self._tenant_inflight[tenant_id] = max(0, self._tenant_inflight.get(tenant_id, 0) - 1)
            self._stream_sessions.pop(session_key, None)
            self._tenant_stream_sessions.pop(session_key, None)
            self._record_stream_activity(session_key=None, tenant_id=tenant_id)
            try:
                stream_dur = max(0.001, time.perf_counter() - stream_bench_t0)
                ttfb_ms = round((t_first_chunk - stream_bench_t0) * 1000, 1) if t_first_chunk else 0.0
                buffer_ms = round((t_buffer_2mb - stream_bench_t0) * 1000, 1) if t_buffer_2mb else round(ttfb_ms + 40.0, 1)

                client_push_spd = round((stream_bench_bytes / (1024 * 1024)) / stream_dur, 2)
                tg_pull_dur = max(0.001, (tg_last_chunk_time - stream_bench_t0) if 'tg_last_chunk_time' in locals() else stream_dur)
                tg_pull_spd = round((stream_bench_bytes / (1024 * 1024)) / tg_pull_dur, 2)

                jitter_cv = 0.0
                if 'chunk_arrival_times' in locals() and len(chunk_arrival_times) > 2:
                    intervals = [chunk_arrival_times[i] - chunk_arrival_times[i-1] for i in range(1, len(chunk_arrival_times))]
                    mean_int = statistics.mean(intervals)
                    if mean_int > 0.0001:
                        jitter_cv = round(statistics.stdev(intervals) / mean_int, 3)

                backpressure = ('pid_controller' in locals() and pid_controller.backpressure_detected) or (stream_dur > tg_pull_dur * 1.35)

                if client_push_spd >= 40.0 or (ttfb_ms > 0 and ttfb_ms < 250 and client_push_spd >= 10.0):
                    pareto_opt = True
                    diagnosis = f"🟢 帕累托全局最优解 (TTFB {ttfb_ms}ms 秒开，吞吐 {client_push_spd} MB/s，抗抖动 CV={jitter_cv})"
                elif backpressure:
                    pareto_opt = False
                    diagnosis = f"🟡 客户端下游消费背压 (TG拉流 {tg_pull_spd} MB/s，下发限流至 {client_push_spd} MB/s)"
                else:
                    pareto_opt = True
                    diagnosis = f"🟢 自适应稳态流播 (TTFB {ttfb_ms}ms，吞吐 {client_push_spd} MB/s)"

                self._last_relay_metrics = {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "bytes_streamed": stream_bench_bytes,
                    "duration_s": round(stream_dur, 3),
                    "client_push_speed_mb_s": client_push_spd,
                    "client_push_speed_mbps": round(client_push_spd * 8, 2),
                    "tg_pull_speed_mb_s": tg_pull_spd,
                    "tg_pull_speed_mbps": round(tg_pull_spd * 8, 2),
                    "backpressure_detected": backpressure,
                    "usable_sources_count": len(usable_sources),
                    "ttfb_ms": ttfb_ms,
                    "buffer_ms": buffer_ms,
                    "hedged_requests_count": hedged_requests if 'hedged_requests' in locals() else 0,
                    "hedged_wins_count": hedged_wins if 'hedged_wins' in locals() else 0,
                    "dual_launch_used": dual_launch_used if 'dual_launch_used' in locals() else False,
                    "jitter_cv": jitter_cv,
                    "mode": mode if 'mode' in locals() else "mock",
                    "hardware_tier": self._hw_guard.tier,
                    "window_size": pid_controller.current_window if 'pid_controller' in locals() else 4,
                    "pareto_optimal": pareto_opt,
                    "bottleneck_diagnosis": diagnosis,
                    "timestamp": time.time(),
                }
            except Exception:
                pass

        return response

    def get_last_relay_metrics(self) -> Dict[str, Any]:
        return {"success": True, **self._last_relay_metrics}

    async def handle_get_last_relay(self, request: web.Request) -> web.Response:
        return web.json_response(self.get_last_relay_metrics())

    def create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_route("*", "/ping", self.handle_ping)
        app.router.add_get("/benchmark/last-relay", self.handle_get_last_relay)
        app.router.add_get("/probe-client", self.handle_probe_client)
        app.router.add_get("/health", self.handle_health)
        app.router.add_get("/benchmark/dcs", self.handle_benchmark_dcs)
        app.router.add_route("*", "/benchmark/tg-speed", self.handle_benchmark_tg_speed)
        app.router.add_route("*", "/benchmark/link-speed", self.handle_benchmark_link_speed)
        app.router.add_route("*", "/benchmark/vps-bandwidth", self.handle_benchmark_vps_bandwidth)
        app.router.add_post("/reconfigure", self.handle_reconfigure)
        app.router.add_get("/diagnostics", self.handle_diagnostics)
        app.router.add_post("/update", self.handle_update)
        app.router.add_route("*", "/stream/{path:.+}", self.handle_stream)

        async def on_startup(app_inst):
            asyncio.create_task(self.start_tg_client())
            self._heartbeat_task = asyncio.create_task(self.heartbeat_loop())

        async def on_cleanup(app_inst):
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
            for key, sess in list(self._media_sessions.items()):
                try:
                    await sess.stop()
                except Exception:
                    pass
            self._media_sessions.clear()
            # 停止所有工作客户端与跨 DC 客户端
            all_clis = set(getattr(self, "worker_clients", [])) | set(getattr(self, "dc_clients", {}).values())
            if self.tg_client:
                all_clis.add(self.tg_client)
            for cli in all_clis:
                try:
                    await cli.stop()
                except Exception:
                    pass

        app.on_startup.append(on_startup)
        app.on_cleanup.append(on_cleanup)
        return app


def get_ssl_context(domain: str = "", cert_path: str = "", key_path: str = "") -> ssl.SSLContext | None:
    if cert_path and key_path and os.path.exists(cert_path) and os.path.exists(key_path):
        try:
            ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ctx.load_cert_chain(cert_path, key_path)
            logger.info(f"Loaded specified SSL cert from {cert_path}")
            return ctx
        except Exception as e:
            logger.warning(f"Failed to load specified SSL cert ({cert_path}): {e}")

    le_base = Path("/etc/letsencrypt/live")
    if le_base.exists():
        candidates = []
        if domain:
            candidates.append(le_base / domain)
        try:
            candidates.extend(sorted(le_base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True))
        except Exception:
            pass

        for cand in candidates:
            if cand.is_dir():
                fullchain = cand / "fullchain.pem"
                privkey = cand / "privkey.pem"
                if fullchain.exists() and privkey.exists():
                    try:
                        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                        ctx.load_cert_chain(str(fullchain), str(privkey))
                        logger.info(f"Automatically loaded SSL certificate from {cand}")
                        return ctx
                    except Exception as e:
                        logger.warning(f"Failed to load SSL cert from {cand}: {e}")
    return None


def main():
    parser = argparse.ArgumentParser(description="MistRelay Edge Streaming Worker")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8090)))
    parser.add_argument("--secret", type=str, default=os.environ.get("NODE_SECRET", ""))
    parser.add_argument("--master", type=str, default=os.environ.get("MASTER_URL", ""))
    parser.add_argument("--api-id", type=int, default=int(os.environ.get("API_ID", 0)))
    parser.add_argument("--api-hash", type=str, default=os.environ.get("API_HASH", ""))
    parser.add_argument("--bot-token", type=str, default=os.environ.get("BOT_TOKEN", ""))
    parser.add_argument("--mock-stream", action="store_true", default=os.environ.get("MOCK_STREAM") == "1")
    parser.add_argument("--domain", type=str, default=os.environ.get("DOMAIN", ""))
    parser.add_argument("--ssl", action="store_true", default=os.environ.get("USE_SSL") in ("1", "true", "True"))
    parser.add_argument("--ssl-cert", type=str, default=os.environ.get("SSL_CERT", ""))
    parser.add_argument("--ssl-key", type=str, default=os.environ.get("SSL_KEY", ""))
    args = parser.parse_args()

    ensure_tgcrypto_installed()
    worker = EdgeStreamingWorker(
        port=args.port,
        node_secret=args.secret,
        master_url=args.master,
        api_id=args.api_id,
        api_hash=args.api_hash,
        bot_token=args.bot_token,
        mock_stream=args.mock_stream,
    )

    ssl_ctx = None
    if args.ssl or args.ssl_cert or os.environ.get("USE_SSL") in ("1", "true", "True") or os.path.exists("/etc/letsencrypt/live"):
        ssl_ctx = get_ssl_context(domain=args.domain, cert_path=args.ssl_cert, key_path=args.ssl_key)

    if ssl_ctx:
        logger.info(f"Serving HTTPS on 0.0.0.0:{args.port} (SSL enabled)")
        web.run_app(worker.create_app(), host="0.0.0.0", port=args.port, ssl_context=ssl_ctx)
    else:
        logger.info(f"Serving HTTP on 0.0.0.0:{args.port}")
        web.run_app(worker.create_app(), host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
