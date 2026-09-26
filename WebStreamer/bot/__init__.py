# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

import os
import os.path
import re
import time
import threading
from ..vars import Var
import logging
from pyrogram import Client

logger = logging.getLogger("bot")

sessions_dir = os.environ.get("MISTRELAY_SESSION_DIR", "/app/db/sessions")
os.makedirs(sessions_dir, mode=0o700, exist_ok=True)
try:
    os.chmod(sessions_dir, 0o700)
except Exception:
    pass

_primary_bot_id = str(Var.BOT_TOKEN or "default").split(":", 1)[0]

# 使用持久化 session 文件避免重启重复触发 ImportBotAuthorization FloodWait
StreamBot = Client(
    name=f"pyrogram_bot_{_primary_bot_id}",
    api_id=Var.API_ID,
    api_hash=Var.API_HASH,
    workdir=sessions_dir,
    plugins={"root": "WebStreamer.bot.plugins"},
    bot_token=Var.BOT_TOKEN,
    sleep_threshold=Var.SLEEP_THRESHOLD,
    workers=Var.WORKERS,
    in_memory=False,
)

multi_clients = {}
work_loads = {}
# 跟踪哪些客户端可以访问 BIN_CHANNEL 进行读取与分流 (下载/流播/缩略图)
channel_accessible_clients = set()
# 跟踪哪些客户端具备 BIN_CHANNEL 写权限 (上传/发帖/删帖)
channel_write_clients = set()
# 客户端访问模式与元信息: {idx: {"mode": "primary_admin" | "direct_admin" | "no_join_resolved" | "unreachable", "can_read": bool, "can_write": bool, "username": str}}
bot_channel_modes = {}
# 频道的公开标识 (公开用户名或关联讨论组公开用户名)
channel_public_handle = None
bot_runtime = {}

_scheduler_lock = threading.Lock()
_scheduler_cursor = -1


# Telegram 数据中心物理分区与地理分布映射
DC_LOCATIONS = {
    1: "DC1 (美西 / 迈阿密)",
    2: "DC2 (欧洲 / 阿姆斯特丹)",
    3: "DC3 (美东 / 迈阿密)",
    4: "DC4 (欧洲 / 阿姆斯特丹)",
    5: "DC5 (亚太 / 新加坡)",
}


def _ensure_bot_runtime(index: int) -> dict:
    state = bot_runtime.get(index)
    if state is None:
        state = {
            "cooldown_until": 0.0,
            "cooldown_reason": "",
            "failure_streak": 0,
            "success_count": 0,
            "failure_count": 0,
            "request_count": 0,
            "bytes_served": 0,
            "throughput_bps": 0.0,
            "last_byte_at": 0.0,
            "last_selected_at": 0.0,
            "last_error": "",
            "home_dc": None,
            "warm_dcs": set(),
            "dc_requests": {},
        }
        bot_runtime[index] = state
    else:
        state.setdefault("home_dc", None)
        state.setdefault("warm_dcs", set())
        state.setdefault("dc_requests", {})
    return state


def set_bot_home_dc(index: int, dc_id: int | None) -> None:
    if dc_id is None:
        return
    with _scheduler_lock:
        state = _ensure_bot_runtime(index)
        state["home_dc"] = int(dc_id)
        state["warm_dcs"].add(int(dc_id))


def mark_bot_warm_dc(index: int, dc_id: int | None) -> None:
    if dc_id is None:
        return
    with _scheduler_lock:
        state = _ensure_bot_runtime(index)
        state["warm_dcs"].add(int(dc_id))


def get_dc_partition_summary(media_records: list[dict] | None = None) -> dict:
    try:
        from pyrogram.file_id import FileId
    except Exception:
        FileId = None

    summary = {}
    for dc_num in range(1, 6):
        summary[str(dc_num)] = {
            "dc_id": dc_num,
            "label": DC_LOCATIONS.get(dc_num, f"DC{dc_num}"),
            "home_bots": [],
            "warm_bots": [],
            "files_count": 0,
            "requests_count": 0,
        }

    with _scheduler_lock:
        for idx in sorted(multi_clients.keys()):
            st = _ensure_bot_runtime(idx)
            hdc = st.get("home_dc")
            if hdc and str(hdc) in summary:
                summary[str(hdc)]["home_bots"].append(idx)
            for wdc in sorted(st.get("warm_dcs", ())):
                if str(wdc) in summary and idx not in summary[str(wdc)]["warm_bots"]:
                    summary[str(wdc)]["warm_bots"].append(idx)
            for d_req, count in st.get("dc_requests", {}).items():
                if str(d_req) in summary:
                    summary[str(d_req)]["requests_count"] += count

    if media_records is None:
        try:
            import db
            media_records = db.list_all_tg_media_records()
        except Exception:
            media_records = []

    if FileId is not None:
        for rec in (media_records or []):
            fid = rec.get("file_id")
            if fid:
                try:
                    dec = FileId.decode(fid)
                    if dec.dc_id and str(dec.dc_id) in summary:
                        summary[str(dec.dc_id)]["files_count"] += 1
                except Exception:
                    pass

    return summary


def register_bot_client(index: int) -> None:
    with _scheduler_lock:
        work_loads.setdefault(index, 0)
        _ensure_bot_runtime(index)


def unregister_bot_client(index: int) -> None:
    with _scheduler_lock:
        work_loads.pop(index, None)
        bot_runtime.pop(index, None)
        channel_accessible_clients.discard(index)
        channel_write_clients.discard(index)
        bot_channel_modes.pop(index, None)


def _channel_candidate_indices(prefer_channel: bool = True) -> list[int]:
    if prefer_channel:
        indices = [idx for idx in channel_accessible_clients if idx in multi_clients]
        if indices:
            return sorted(indices)
    return sorted(idx for idx in multi_clients.keys())


def _parse_cooldown_seconds(error: Exception | str | None, failure_streak: int) -> int:
    if error is None:
        return min(30, 3 + failure_streak * 3)

    if hasattr(error, "value"):
        try:
            return max(5, int(error.value))
        except Exception:
            pass

    text = str(error)
    lowered = text.lower()

    if "flood" in lowered:
        match = re.search(r"(\d+)\s*second", lowered)
        if match:
            return max(5, int(match.group(1)))
        return 60

    if any(marker in lowered for marker in [
        "connection lost",
        "connection closed",
        "broken pipe",
        "timeout",
        "timed out",
        "network",
        "reset by peer",
    ]):
        return min(20, 2 + failure_streak * 2)

    return min(45, 5 + failure_streak * 4)


def get_available_channel_bot_count() -> int:
    indices = _channel_candidate_indices(prefer_channel=True)
    return max(1, len(indices))


def get_bot_runtime_snapshot() -> dict:
    now = time.time()
    with _scheduler_lock:
        snapshot = {}
        for idx in sorted(multi_clients.keys()):
            state = _ensure_bot_runtime(idx)
            client = multi_clients.get(idx)
            uname = getattr(client, "username", "") or ""
            mode_entry = bot_channel_modes.get(idx, {})
            mode = mode_entry.get("mode") or (
                "primary_admin" if idx == 0 else (
                    "direct_admin" if idx in channel_write_clients else (
                        "no_join_resolved" if idx in channel_accessible_clients else "unreachable"
                    )
                )
            )
            snapshot[idx] = {
                "username": uname,
                "mode": mode,
                "home_dc": state.get("home_dc"),
                "warm_dcs": sorted(list(state.get("warm_dcs", ()))),
                "dc_requests": dict(state.get("dc_requests", {})),
                "can_read": idx in channel_accessible_clients,
                "can_write": idx in channel_write_clients or idx == 0,
                "active_requests": work_loads.get(idx, 0),
                "cooldown_remaining": max(0.0, state["cooldown_until"] - now),
                "cooldown_reason": state["cooldown_reason"],
                "failure_streak": state["failure_streak"],
                "success_count": state["success_count"],
                "failure_count": state["failure_count"],
                "request_count": state["request_count"],
                "bytes_served": state["bytes_served"],
                "throughput_bps": state["throughput_bps"],
                "last_selected_at": state["last_selected_at"],
                "last_error": state["last_error"],
            }
        return snapshot


def acquire_bot_slot(index: int) -> None:
    now = time.time()
    with _scheduler_lock:
        work_loads[index] = work_loads.get(index, 0) + 1
        state = _ensure_bot_runtime(index)
        state["request_count"] += 1
        state["last_selected_at"] = now


def release_bot_slot(index: int) -> None:
    with _scheduler_lock:
        if index in work_loads and work_loads[index] > 0:
            work_loads[index] -= 1


active_user_streams: int = 0
_stream_id_counter: int = 0


def acquire_stream_slot() -> int:
    """注册一个新的客户端真实 HTTP 流传输会话并返回自增 stream_id"""
    global active_user_streams, _stream_id_counter
    with _scheduler_lock:
        active_user_streams += 1
        _stream_id_counter += 1
        return _stream_id_counter


def release_stream_slot(stream_id: int | None = None) -> None:
    """释放客户端真实 HTTP 流传输会话"""
    global active_user_streams
    with _scheduler_lock:
        if active_user_streams > 0:
            active_user_streams -= 1


def get_active_stream_count() -> int:
    """获取当前活跃的真实客户端 HTTP 流会话数"""
    with _scheduler_lock:
        return max(0, active_user_streams)


def record_bot_bytes(index: int, byte_count: int) -> None:
    if byte_count <= 0:
        return

    now = time.time()
    with _scheduler_lock:
        state = _ensure_bot_runtime(index)
        state["bytes_served"] += byte_count
        last_byte_at = state["last_byte_at"]
        if last_byte_at > 0 and now > last_byte_at:
            instant_bps = byte_count / max(now - last_byte_at, 1e-3)
            if state["throughput_bps"] <= 0:
                state["throughput_bps"] = instant_bps
            else:
                state["throughput_bps"] = state["throughput_bps"] * 0.7 + instant_bps * 0.3
        state["last_byte_at"] = now


def mark_bot_success(index: int) -> None:
    with _scheduler_lock:
        state = _ensure_bot_runtime(index)
        state["success_count"] += 1
        state["failure_streak"] = 0
        state["cooldown_until"] = 0.0
        state["cooldown_reason"] = ""
        state["last_error"] = ""


def mark_bot_failure(index: int, error: Exception | str | None = None) -> None:
    now = time.time()
    with _scheduler_lock:
        state = _ensure_bot_runtime(index)
        state["failure_count"] += 1
        state["failure_streak"] += 1
        state["last_error"] = str(error or "")
        cooldown_seconds = _parse_cooldown_seconds(error, state["failure_streak"])
        state["cooldown_until"] = max(state["cooldown_until"], now + cooldown_seconds)
        state["cooldown_reason"] = str(error or f"cooldown:{cooldown_seconds}s")


def select_stream_bot(
    *,
    exclude_indices: set[int] | None = None,
    prefer_channel: bool = True,
    target_dc: int | None = None,
) -> int | None:
    global _scheduler_cursor

    excluded = set(exclude_indices or ())
    now = time.time()

    with _scheduler_lock:
        candidates = [idx for idx in _channel_candidate_indices(prefer_channel) if idx not in excluded]
        if not candidates:
            return None

        ready = [
            idx for idx in candidates
            if _ensure_bot_runtime(idx)["cooldown_until"] <= now
        ]
        if not ready:
            return None
        pool = ready

        ordered = sorted(pool)
        if ordered:
            if _scheduler_cursor not in ordered:
                rotation_start = 0
            else:
                rotation_start = (ordered.index(_scheduler_cursor) + 1) % len(ordered)
            rotated = ordered[rotation_start:] + ordered[:rotation_start]
        else:
            rotated = []

        position_map = {idx: pos for pos, idx in enumerate(rotated)}

        def score(idx: int) -> tuple[float, int, int]:
            state = _ensure_bot_runtime(idx)
            cooldown_remaining = max(0.0, state["cooldown_until"] - now)
            active_load = work_loads.get(idx, 0)
            failure_penalty = min(state["failure_streak"], 5) * 0.5
            cooldown_penalty = cooldown_remaining if not ready else 0.0

            dc_penalty = 0.0
            if target_dc is not None:
                if state.get("home_dc") == target_dc:
                    dc_penalty = 0.0
                elif target_dc in state.get("warm_dcs", ()):
                    dc_penalty = 0.2
                else:
                    dc_penalty = 2.5

            return (
                active_load + failure_penalty + cooldown_penalty + dc_penalty,
                position_map.get(idx, 0),
                idx,
            )

        selected = min(pool, key=score)
        _scheduler_cursor = selected
        st = _ensure_bot_runtime(selected)
        st["last_selected_at"] = now
        if target_dc is not None:
            st["dc_requests"][int(target_dc)] = st["dc_requests"].get(int(target_dc), 0) + 1
        return selected
