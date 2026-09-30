"""
MistRelay 边缘推流节点调度与动态 Ticket 凭据签发引擎
=====================================================
负责向客户端签发去中心化流播 Ticket，以及决策 302 智能分流路由。
内置：客户端真实 IP 穿透识别、网段级延迟路由缓存、Telegram DC 延迟打分与多候选低延迟择优。
"""

import os
import re
import time
import json
import copy
from datetime import datetime, timezone
import secrets
import hmac
import hashlib
import base64
import logging
import asyncio
import glob
import ipaddress
import math
from aiohttp import web, ClientSession, ClientTimeout
from typing import Optional, Dict, Any, Tuple, List

import db
from WebStreamer import Var

logger = logging.getLogger("edge_node_manager")


def get_ip_subnet_key(ip_str: str) -> str:
    """将客户端 IP 归一化为 /24 (IPv4) 或 /48 (IPv6) 网段键，用于复用延迟测量结果"""
    if not ip_str:
        return "default"
    try:
        ip_obj = ipaddress.ip_address(ip_str.strip())
        if ip_obj.is_private or ip_obj.is_loopback:
            return f"local:{ip_obj}"
        if isinstance(ip_obj, ipaddress.IPv4Address):
            net = ipaddress.IPv4Network(f"{ip_obj}/24", strict=False)
            return str(net)
        else:
            net = ipaddress.IPv6Network(f"{ip_obj}/48", strict=False)
            return str(net)
    except ValueError:
        return "default"


_LOCAL_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _is_local_lan_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(ip_obj in net for net in _LOCAL_NETWORKS) or ip_obj.is_unspecified


def extract_routing_client_ip(request: web.Request) -> str:
    """从请求中提取用于分流路由与地理延迟判定的真实客户端 IP"""
    if request is None:
        return "127.0.0.1"
    headers = getattr(request, "headers", {}) or {}
    for hdr in ("CF-Connecting-IP", "X-Real-IP", "True-Client-IP"):
        val = (headers.get(hdr) or "").strip()
        if val:
            try:
                ip_obj = ipaddress.ip_address(val)
                if not _is_local_lan_ip(ip_obj):
                    return str(ip_obj)
            except ValueError:
                pass
    xff = headers.get("X-Forwarded-For") or ""
    if xff:
        for part in xff.split(","):
            cand = part.strip()
            if cand:
                try:
                    ip_obj = ipaddress.ip_address(cand)
                    if not _is_local_lan_ip(ip_obj):
                        return str(ip_obj)
                except ValueError:
                    pass
    if xff:
        first_cand = xff.split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(first_cand))
        except ValueError:
            pass
    remote = str(getattr(request, "remote", "") or "127.0.0.1")
    return remote


class EdgeLatencyRouter:
    """多维边缘节点延迟打分与智能路由中心"""

    def __init__(self, cache_ttl: int = 1800):
        self.cache_ttl = cache_ttl
        # _cache: { subnet_key: { node_id: { 'rtt_ms': float, 'source': str, 'updated_at': float } } }
        self._cache: Dict[str, Dict[int, Dict[str, Any]]] = {}

    def record_client_latency(
        self,
        client_ip: str,
        node_id: int,
        rtt_ms: float,
        source: str = "browser",
    ) -> None:
        subnet = get_ip_subnet_key(client_ip)
        if subnet not in self._cache:
            self._cache[subnet] = {}
        self._cache[subnet][int(node_id)] = {
            "rtt_ms": max(1.0, float(rtt_ms)),
            "source": source,
            "updated_at": time.time(),
        }

    def get_cached_entry(self, client_ip: str, node_id: int) -> Optional[Dict[str, Any]]:
        subnet = get_ip_subnet_key(client_ip)
        node_map = self._cache.get(subnet)
        if not node_map:
            return None
        entry = node_map.get(int(node_id))
        if not entry:
            return None
        if time.time() - entry["updated_at"] > self.cache_ttl:
            node_map.pop(int(node_id), None)
            return None
        return entry

    def get_node_dc_rtt(self, node: Dict[str, Any], target_dc: int) -> float:
        """提取节点到目标 Telegram DC 的已知实测延迟"""
        bench = node.get("benchmark_data") or {}
        dcs = bench.get("dcs") or []
        if isinstance(dcs, list):
            for d in dcs:
                if isinstance(d, dict) and d.get("dc_id") == target_dc:
                    avg_rtt = d.get("avg_rtt_ms")
                    if avg_rtt is not None and float(avg_rtt) > 0:
                        return float(avg_rtt)

        fastest = bench.get("fastest_dc") or {}
        if isinstance(fastest, dict) and fastest.get("avg_rtt_ms"):
            return float(fastest["avg_rtt_ms"])
        return 100.0

    def estimate_fallback_client_rtt(self, client_ip: str, node: Dict[str, Any]) -> float:
        """当未命中缓存时，依据客户端 IP 所属大区与节点已知 DC 延迟进行就近距离估算"""
        try:
            ip_obj = ipaddress.ip_address(client_ip.strip())
            if ip_obj.is_private or ip_obj.is_loopback:
                return 25.0
        except ValueError:
            return 80.0

        # 判断节点所属大区 (APAC / NA / EU)
        node_region = "APAC"
        bench = node.get("benchmark_data") or {}
        fastest_id = (bench.get("fastest_dc") or {}).get("id")
        if fastest_id in (1, 3):
            node_region = "NA"
        elif fastest_id in (2, 4):
            node_region = "EU"
        elif fastest_id == 5:
            node_region = "APAC"
        else:
            name = (node.get("node_name") or "").lower()
            if any(k in name for k in ("美", "us", "america")):
                node_region = "NA"
            elif any(k in name for k in ("欧", "eu", "de", "fr", "uk")):
                node_region = "EU"
            else:
                node_region = "APAC"

        # 简单粗粒度判断客户端 IP 大区
        client_region = "APAC"
        first_octet = int(client_ip.split(".")[0]) if "." in client_ip else 0
        if client_ip.startswith(("209.9.", "104.28.", "172.68.", "172.69.", "45.192.")):
            client_region = "APAC"
        elif first_octet in (3, 4, 8, 12, 15, 16, 23, 24, 32, 34, 35, 40, 44, 50, 52, 54, 104, 107, 108, 184, 198, 199, 204, 205, 206, 207, 208, 216):
            client_region = "NA"
        elif first_octet in (2, 5, 25, 31, 37, 46, 62, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 109, 141, 145, 151, 176, 177, 178, 179, 185, 188, 193, 194, 195, 212, 213, 217):
            client_region = "EU"

        if client_region == node_region:
            return 30.0
        return 180.0

    def compute_node_score(
        self,
        client_ip: str,
        node: Dict[str, Any],
        target_dc: int = 0,
    ) -> Dict[str, Any]:
        node_id = int(node.get("id", 0))
        cached = self.get_cached_entry(client_ip, node_id)
        if cached is not None:
            client_rtt = float(cached["rtt_ms"])
            rtt_source = cached["source"]
        else:
            client_rtt = self.estimate_fallback_client_rtt(client_ip, node)
            rtt_source = "geo_dc_estimate"

        dc_rtt = self.get_node_dc_rtt(node, target_dc)
        active_streams = int((node.get("metrics") or {}).get("active_streams", 0))

        # 综合调度评分：客户端 RTT + 0.35 * TG数据中心 RTT + 并发负载惩罚 (每路 2.0ms)
        score = round(client_rtt + (0.35 * dc_rtt) + (active_streams * 2.0), 2)
        return {
            "node_id": node_id,
            "score": score,
            "client_rtt_ms": round(client_rtt, 1),
            "dc_rtt_ms": round(dc_rtt, 1),
            "active_streams": active_streams,
            "rtt_source": rtt_source,
        }

    async def probe_nodes_for_ip(
        self,
        client_ip: str,
        candidate_nodes: List[Dict[str, Any]],
        timeout_sec: float = 2.0,
    ) -> None:
        """异步向各候选边缘节点调度 ICMP Ping 探测客户端真实 IP"""
        try:
            ip_obj = ipaddress.ip_address(client_ip.strip())
            if ip_obj.is_private or ip_obj.is_loopback:
                return
        except ValueError:
            return

        async def _probe_single(node: Dict[str, Any]):
            node_id = int(node.get("id", 0))
            domain = (node.get("domain") or "").strip()
            node_ip = (node.get("ip") or "").strip()
            port = int(node.get("port") or 8090)
            use_ssl = bool(node.get("use_ssl"))
            auth_secret = node.get("auth_secret") or ""

            if domain:
                scheme = "https" if use_ssl else "http"
                netloc = domain if port in (80, 443) else f"{domain}:{port}"
            elif node_ip:
                scheme = "http"
                netloc = f"{node_ip}:{port}"
            else:
                return

            url = f"{scheme}://{netloc}/probe-client?ip={client_ip}"
            headers = {"X-Node-Secret": auth_secret}
            try:
                timeout = ClientTimeout(total=timeout_sec)
                async with ClientSession(timeout=timeout) as session:
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("reachable") and data.get("avg_rtt_ms"):
                                self.record_client_latency(
                                    client_ip=client_ip,
                                    node_id=node_id,
                                    rtt_ms=float(data["avg_rtt_ms"]),
                                    source="ping",
                                )
            except Exception:
                pass

        tasks = [_probe_single(n) for n in candidate_nodes]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def select_best_edge_node(
        self,
        client_ip: str,
        candidate_nodes: List[Dict[str, Any]],
        target_dc: int = 0,
        preferred_node_id: Optional[int] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """在候选节点池中根据低延迟算法优选最优节点"""
        if not candidate_nodes:
            return None, {}

        # 显式指定节点优先
        if preferred_node_id is not None:
            for n in candidate_nodes:
                if int(n.get("id", 0)) == int(preferred_node_id):
                    return n, {"method": "preferred_node", "score": 0.0, "node_id": preferred_node_id}

        if len(candidate_nodes) == 1:
            n = candidate_nodes[0]
            return n, {"method": "single_candidate", "score": 0.0, "node_id": n.get("id")}

        # 调度打分
        scored_nodes = []
        missing_probes = False
        for n in candidate_nodes:
            score_data = self.compute_node_score(client_ip, n, target_dc)
            if score_data["rtt_source"] == "geo_dc_estimate":
                missing_probes = True
            scored_nodes.append((score_data["score"], n, score_data))

        # 触发后台异步真实 IP 探测
        if missing_probes:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.probe_nodes_for_ip(client_ip, candidate_nodes))
            except RuntimeError:
                pass

        # 最低分优先；同分按 active_streams 和 ID 升序
        scored_nodes.sort(
            key=lambda item: (
                item[0],
                int((item[1].get("metrics") or {}).get("active_streams", 0)),
                int(item[1].get("id", 0)),
            )
        )

        best = scored_nodes[0]
        return best[1], best[2]


edge_latency_router = EdgeLatencyRouter(cache_ttl=1800)


def generate_edge_stream_ticket(
    tenant_id: int,
    chat_id: int,
    message_id: int,
    file_unique_id: str,
    node_secret: str,
    file_name: str = "",
    file_size: int = 0,
    mime_type: str = "",
    dc_id: int = 0,
    expire_seconds: int = 7200,
    channel_username: str = "",
) -> str:
    """生成附带 HMAC-SHA256 防篡改签名的边缘流播 Ticket"""
    now_ts = int(time.time())
    payload = {
        "tid": int(tenant_id or 0),
        "cid": int(chat_id or 0),
        "mid": int(message_id),
        "fuid": str(file_unique_id or ""),
        "fn": str(file_name or ""),
        "fs": int(file_size or 0),
        "mt": str(mime_type or ""),
        "dc": int(dc_id or 0),
        "ch": str(channel_username or ""),
        "iat": now_ts,
        "exp": now_ts + int(expire_seconds),
        "salt": secrets.token_hex(6),
    }
    json_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(json_bytes).decode("ascii")
    sig = hmac.new(
        node_secret.encode("utf-8"),
        b64_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"{b64_payload}.{sig}"


def verify_edge_stream_ticket(
    ticket: str,
    node_secret: str,
    expected_message_id: Optional[int] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """校验 Ticket 防伪签名与有效期"""
    if not ticket or "." not in ticket:
        return False, None, "Ticket 格式无效"
    parts = ticket.split(".", 1)
    if len(parts) != 2:
        return False, None, "Ticket 结构不完整"
    b64_payload, sig = parts

    expected_sig = hmac.new(
        node_secret.encode("utf-8"),
        b64_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected_sig):
        return False, None, "Ticket 签名不匹配或已被篡改"

    try:
        json_bytes = base64.urlsafe_b64decode(b64_payload.encode("ascii"))
        payload = json.loads(json_bytes.decode("utf-8"))
    except Exception as e:
        return False, None, f"Ticket 数据解码失败: {e}"

    exp = payload.get("exp", 0)
    if time.time() > exp:
        return False, payload, "Ticket 已过期"

    if expected_message_id is not None:
        if payload.get("mid") != expected_message_id:
            return False, payload, "Ticket 绑定的消息 ID 与请求不一致"

    return True, payload, "OK"


def resolve_edge_stream_info(
    request: Any,
    message_id: int,
    secure_hash: str,
    source_record: Optional[Dict[str, Any]] = None,
    record_chat_id: Optional[int] = None,
    preferred_node_override: Optional[Any] = None,
    force_download: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    边缘分流决策核心引擎：
    1. 检查 direct 标识（显式指定 direct=1 或 preferred_node='direct' 则回源主控）；
    2. 检查 preferred_node 参数（优先采用显式指定的边缘节点）；
    3. 识别媒体所属租户与请求者身份；
    4. 获取候选边缘节点池（租户专属池优先，公共共享池兜底）；
    5. 执行智能低延迟选路（若未指定节点，综合客户端 IP 延迟、Telegram DC 延迟与节点负载择优）；
    6. 构造签名 Ticket 与 Edge Worker 终态流播 URL。
    返回包含 url、node_id、node_name、is_edge、ticket 等信息的字典。
    """
    req_query = getattr(request, "query", {}) or {}
    req_headers = getattr(request, "headers", {}) or {}
    is_https = getattr(request, "scheme", "http") == "https" or req_headers.get("X-Forwarded-Proto") == "https"
    is_download = force_download if force_download is not None else (req_query.get("download", "").lower() in {"1", "true", "yes"})
    ua_str = req_headers.get("User-Agent", "")

    # 1. 检查 direct 标识
    preferred_node_raw = preferred_node_override or req_query.get("preferred_node") or req_headers.get("X-Preferred-Node")
    if req_query.get("direct") == "1" or str(preferred_node_raw or "").lower() in ("direct", "master", "origin"):
        return {"url": None, "is_edge": False, "node_id": None, "node_name": "主控服务器 (直连)"}

    # 2. 检查 User-Agent (本地 FFmpeg 抽帧回源主控，保证缩略图生成稳定)
    if ua_str.startswith(("Lavf/", "FFmpeg")) and not preferred_node_override:
        return {"url": None, "is_edge": False, "node_id": None, "node_name": "主控服务器 (抽帧)"}

    actual_record = source_record or {}
    target_chat_id = record_chat_id or actual_record.get("chat_id")

    # 3. 识别频道所属租户与请求者身份
    channel_tenant_id: Optional[int] = None
    channel_username: str = ""
    # 注意：全局默认频道 Var.BIN_CHANNEL (-1001998444696) 属于系统公共存储池，不能归属为任何单一租户
    if target_chat_id and target_chat_id != Var.BIN_CHANNEL:
        tenant_user = db.get_user_by_bin_channel_id(target_chat_id)
        if tenant_user:
            channel_tenant_id = tenant_user.get("id")
            channel_username = tenant_user.get("bin_channel_username") or ""
        if not channel_username:
            channel_username = db.get_channel_username_by_chat_id(target_chat_id) or ""

    user_obj = request.get("user") if hasattr(request, "get") else None
    req_uid: Optional[int] = user_obj.get("uid") if user_obj else None
    is_admin: bool = bool(user_obj and user_obj.get("role") == "admin")

    if not req_uid and req_query.get("uid"):
        try:
            u_rec = db.get_user_by_id(int(req_query.get("uid")))
            if u_rec:
                req_uid = u_rec.get("id")
                if u_rec.get("role") == "admin":
                    is_admin = True
        except Exception:
            pass

    # 优先采用发起请求用户的 tenant_id (若没有登录用户则回退为专属频道归属租户)
    tenant_id: Optional[int] = req_uid if req_uid is not None else channel_tenant_id

    # 4. 检查 preferred_node
    preferred_node_param = preferred_node_override or req_query.get("preferred_node") or req_headers.get("X-Preferred-Node")
    preferred_node_id: Optional[int] = None
    if preferred_node_param and str(preferred_node_param).lower() not in ("auto", "none", "", "direct"):
        try:
            preferred_node_id = int(preferred_node_param)
        except (ValueError, TypeError):
            pass

    # 5. 提取文件关键属性用于签发 Ticket
    file_unique_id = actual_record.get("file_unique_id") or ""
    raw_unique_id = file_unique_id.split("@")[0] if file_unique_id else ""
    file_name = actual_record.get("file_name") or ""
    file_size = actual_record.get("file_size") or 0
    mime_type = actual_record.get("mime_type") or ""
    dc_id = actual_record.get("dc_id") or 0

    # 6. 获取候选边缘节点池 (专属池优先，共享池兜底)
    candidates = db.get_candidate_edge_nodes_for_tenant(tenant_id, max_stale_seconds=180, include_secrets=True)
    if not candidates and is_admin:
        all_avail = db.get_available_edge_nodes_for_user(tenant_id=tenant_id, is_admin=True, include_secrets=True)
        candidates = [n for n in all_avail if db._is_edge_node_fresh(n, 180)]

    chosen_node = None
    if preferred_node_id is not None:
        matched = [c for c in candidates if int(c["id"]) == preferred_node_id]
        if matched:
            chosen_node = matched[0]
        else:
            # 检查指定节点是否允许当前用户访问（共享池节点、管理员、所属租户，或公共默认频道显式指定）
            spec_node = db.get_edge_node_by_id(preferred_node_id, include_secrets=True)
            if spec_node and spec_node.get("status") == "online" and db._is_edge_node_fresh(spec_node, 180):
                if (
                    is_admin
                    or spec_node.get("allow_shared_pool")
                    or (tenant_id and spec_node.get("tenant_id") == tenant_id)
                    or (channel_tenant_id is None and user_obj is None and not req_uid)
                ):
                    chosen_node = spec_node

    if not chosen_node:
        if not candidates:
            return {"url": None, "is_edge": False, "node_id": None, "node_name": "主控服务器 (无可用边缘节点)"}

        # 若请求来自前端 HTTPS 页面内的浏览器音视频播放，为避免 Mixed Content 导致播放失败，
        # 优先筛选支持 SSL 或配有安全域名的边缘节点；若用户未显式指定 preferred_node 且无 SSL 节点可用，自动回退 Master 直出
        is_browser_media = req_headers.get("Sec-Fetch-Dest") in {"video", "audio"} or (
            "Mozilla" in ua_str and not is_download
        )

        if is_https and is_browser_media and preferred_node_id is None:
            ssl_candidates = [
                c for c in candidates
                if bool(c.get("use_ssl")) or c.get("domain")
            ]
            if ssl_candidates:
                candidates = ssl_candidates
            else:
                return {"url": None, "is_edge": False, "node_id": None, "node_name": "主控服务器 (无SSL边缘节点)"}

        client_ip = extract_routing_client_ip(request)
        chosen_node, score_meta = edge_latency_router.select_best_edge_node(
            client_ip=client_ip,
            candidate_nodes=candidates,
            target_dc=int(dc_id or 0),
            preferred_node_id=None,
        )

    if not chosen_node:
        return {"url": None, "is_edge": False, "node_id": None, "node_name": "主控服务器 (未命中节点)"}

    node_secret = chosen_node.get("auth_secret")
    if not node_secret:
        return {"url": None, "is_edge": False, "node_id": None, "node_name": "主控服务器 (缺少节点凭证)"}

    ticket = generate_edge_stream_ticket(
        tenant_id=tenant_id or 0,
        chat_id=target_chat_id or 0,
        message_id=message_id,
        file_unique_id=raw_unique_id,
        node_secret=node_secret,
        file_name=file_name,
        file_size=file_size,
        mime_type=mime_type,
        dc_id=dc_id,
        expire_seconds=7200,
        channel_username=channel_username,
    )

    # 7. 组装目标节点 URL
    from db import get_default_edge_domain
    domain = (chosen_node.get("domain") or "").strip()
    node_ip = (chosen_node.get("ip") or "").strip()
    port = int(chosen_node.get("port") or 8090)
    use_ssl = bool(chosen_node.get("use_ssl"))

    if not domain and node_ip:
        domain = get_default_edge_domain(node_ip)
        if domain:
            use_ssl = True

    if domain:
        scheme = "https" if (use_ssl or is_https) else "http"
        netloc = domain if port in (80, 443) else f"{domain}:{port}"
    elif node_ip:
        scheme = "http"
        netloc = f"{node_ip}:{port}"
    else:
        return {"url": None, "is_edge": False, "node_id": None, "node_name": "主控服务器 (无效节点地址)"}

    extra_params = []
    if is_download:
        extra_params.append("download=1")
    query_str = f"?ticket={ticket}" + ("&" + "&".join(extra_params) if extra_params else "")

    edge_url = f"{scheme}://{netloc}/stream/{secure_hash}{message_id}{query_str}"
    return {
        "url": edge_url,
        "node_id": chosen_node.get("id"),
        "node_name": chosen_node.get("node_name"),
        "is_edge": True,
        "ticket": ticket,
        "base_url": f"{scheme}://{netloc}",
        "chosen_node": chosen_node,
    }


def resolve_edge_redirect_url(
    request: Any,
    message_id: int,
    secure_hash: str,
    source_record: Optional[Dict[str, Any]] = None,
    record_chat_id: Optional[int] = None,
) -> Optional[str]:
    """
    302 智能分流路由决策：包装 resolve_edge_stream_info，返回重定向 URL（若回源主控则返回 None）。
    """
    info = resolve_edge_stream_info(
        request=request,
        message_id=message_id,
        secure_hash=secure_hash,
        source_record=source_record,
        record_chat_id=record_chat_id,
    )
    return info.get("url") if info and info.get("is_edge") else None


# =====================================================================
# Telegram 数据中心 (DC) 亲和 Bot 资产调度与多 Bot 阵列共享
# =====================================================================

_bot_pool_cache: Dict[int, List[Dict[str, Any]]] = {}
_bot_pool_cache_time: float = 0.0


def _resolve_sessions_dir() -> str:
    candidates = [
        os.path.join(os.path.dirname(db.DB_PATH), "sessions"),
        "/root/MistRelay-dev/db/sessions",
        "/app/db/sessions",
    ]
    best_candidate = None
    max_count = -1
    for c in candidates:
        if os.path.exists(c):
            count = len(glob.glob(os.path.join(c, "*.session")))
            if count > max_count:
                max_count = count
                best_candidate = c
    return best_candidate or "/app/db/sessions"


def export_bot_session_string(token: str, api_id: int = 0) -> str:
    """从本地 sessions 目录无锁提取指定 Bot 的已授权 session_string (免 Telegram 登录与 FloodWait)"""
    if not token or ":" not in token:
        return ""
    pfx = token.split(":", 1)[0]
    sessions_dir = _resolve_sessions_dir()
    spath = os.path.join(sessions_dir, f"pyrogram_bot_{pfx}.session")
    if not os.path.exists(spath):
        return ""
    try:
        import sqlite3
        import struct
        from pyrogram.storage.storage import Storage
        actual_api_id = int(api_id or getattr(Var, "API_ID", 0) or 2420373)
        with sqlite3.connect(f"file:{spath}?mode=ro", uri=True, timeout=2.0) as sconn:
            sc = sconn.cursor()
            sc.execute("SELECT dc_id, test_mode, auth_key, user_id, is_bot FROM sessions")
            row = sc.fetchone()
            if not row or not row[2]:
                return ""
            dc_id, test_mode, auth_key, user_id, is_bot = row
            packed = struct.pack(
                Storage.SESSION_STRING_FORMAT,
                int(dc_id),
                int(actual_api_id),
                bool(test_mode),
                auth_key,
                int(user_id),
                bool(is_bot),
            )
            return base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")
    except Exception as e:
        logger.debug(f"提取 Bot {pfx} session_string 失败: {e}")
        return ""


def get_dc_bot_pool(force_refresh: bool = False) -> Dict[int, List[Dict[str, Any]]]:
    """
    扫描全集群所有已接入的 Bot 令牌并归类为其物理原生数据中心 (DC) 资产池。
    返回结构: { dc_id: [ { 'token': str, 'prefix': str, 'dc_id': int, 'username': str }, ... ] }
    """
    global _bot_pool_cache, _bot_pool_cache_time
    now = time.time()
    if not force_refresh and _bot_pool_cache and (now - _bot_pool_cache_time) < 60.0:
        return _bot_pool_cache

    import glob
    import sqlite3

    primary_token = str(db.get_config("BOT_TOKEN") or getattr(Var, "BOT_TOKEN", "") or "").strip()
    multi_tokens = db.get_config("MULTI_BOT_TOKENS") or getattr(Var, "MULTI_BOT_TOKENS", []) or []

    all_tokens: List[str] = []
    if primary_token:
        all_tokens.append(primary_token)
    if isinstance(multi_tokens, list):
        for t in multi_tokens:
            tok_str = str(t or "").strip()
            if tok_str and tok_str not in all_tokens:
                all_tokens.append(tok_str)

    sessions_dir = _resolve_sessions_dir()
    dc_pool: Dict[int, List[Dict[str, Any]]] = {1: [], 2: [], 3: [], 4: [], 5: []}

    # 尝试从运行中内存同步已有 bot_runtime / username
    active_bot_map: Dict[str, Dict[str, Any]] = {}
    try:
        import WebStreamer.bot as bot_mod
        bot_modes = getattr(bot_mod, "bot_channel_modes", {})
        bot_runtime = getattr(bot_mod, "bot_runtime", {})

        # 检查 StreamBot (index 0)
        stream_bot = getattr(bot_mod, "StreamBot", None)
        if stream_bot:
            s_tok = str(getattr(Var, "BOT_TOKEN", "") or "").strip()
            s_name = (
                getattr(stream_bot, "username", "")
                or (getattr(stream_bot, "me", None) and getattr(stream_bot.me, "username", ""))
                or (bot_modes.get(0, {}).get("username") or "")
            ).lstrip("@")
            s_dc = bot_runtime.get(0, {}).get("home_dc")
            if s_tok:
                active_bot_map[s_tok] = {"username": s_name, "home_dc": s_dc}

        for idx, cli in getattr(bot_mod, "multi_clients", {}).items():
            tok = getattr(cli, "bot_token", None) or (
                getattr(Var, "BOT_TOKEN", "")
                if idx == 0
                else (
                    getattr(Var, "MULTI_BOT_TOKENS", [])[idx - 1]
                    if getattr(Var, "MULTI_BOT_TOKENS", None) and idx - 1 < len(getattr(Var, "MULTI_BOT_TOKENS", []))
                    else ""
                )
            )
            u_name = (
                getattr(cli, "username", "")
                or (getattr(cli, "me", None) and getattr(cli.me, "username", ""))
                or (bot_modes.get(idx, {}).get("username") or "")
            ).lstrip("@")
            st = bot_runtime.get(idx, {})
            h_dc = st.get("home_dc")
            if tok:
                active_bot_map[str(tok).strip()] = {"username": u_name, "home_dc": h_dc}
    except Exception:
        pass

    for tok in all_tokens:
        if not tok or ":" not in tok:
            continue
        pfx = tok.split(":", 1)[0]
        dc_id = 5
        username = ""

        # 优先读取内存活跃状态
        mem_info = active_bot_map.get(tok)
        if mem_info:
            username = mem_info.get("username") or ""
            if mem_info.get("home_dc"):
                dc_id = int(mem_info["home_dc"])

        # 校验底层 session 数据库文件
        if not mem_info or not mem_info.get("home_dc"):
            spath = os.path.join(sessions_dir, f"pyrogram_bot_{pfx}.session")
            if os.path.exists(spath):
                try:
                    with sqlite3.connect(spath, timeout=2.0) as sconn:
                        sc = sconn.cursor()
                        sc.execute("SELECT dc_id FROM sessions")
                        srow = sc.fetchone()
                        if srow and srow[0]:
                            dc_id = int(srow[0])
                except Exception:
                    pass

        entry = {
            "token": tok,
            "prefix": pfx,
            "dc_id": dc_id,
            "username": username or f"bot_{pfx}",
        }
        dc_pool.setdefault(dc_id, []).append(entry)

    _bot_pool_cache = dc_pool
    _bot_pool_cache_time = now
    return dc_pool


def get_bots_by_dc(dc_id: int) -> List[Dict[str, Any]]:
    """获取指定 Telegram DC 下的所有健康可用 Bot"""
    pool = get_dc_bot_pool()
    return pool.get(int(dc_id), [])


def infer_node_target_dc(node: Dict[str, Any]) -> int:
    """综合判定边缘节点的物理就近 Telegram DC (1~5)"""
    # 1. 显式指定 DC 优先
    explicit_dc = node.get("target_dc_id")
    if explicit_dc is not None and str(explicit_dc).isdigit() and int(explicit_dc) in (1, 2, 3, 4, 5):
        return int(explicit_dc)

    # 2. 测速实测物理最优 DC (fastest_dc)
    bench = node.get("benchmark_data") or {}
    fastest = bench.get("fastest_dc") or {}
    fid = fastest.get("id")
    if fid in (1, 3):
        return 1  # DC1 / DC3 同在美东迈阿密
    elif fid in (2, 4):
        return 4  # 欧洲
    elif fid == 5:
        return 5  # 亚太新加坡

    # 3. 节点地域与名称启发式推断
    name_str = (str(node.get("node_name") or "") + " " + str(node.get("ip") or "")).lower()
    if any(k in name_str for k in ("美", "us", "america", "rn-", "racknerd", "miami", "la", "virginia")):
        return 1
    if any(k in name_str for k in ("欧", "eu", "de", "fr", "uk", "nl", "frankfurt", "london")):
        return 4
    if any(k in name_str for k in ("港", "hk", "新", "sg", "jp", "东京", "亚太", "ap-")):
        return 5

    # 4. 租户注册 DC 兜底
    tenant_id = node.get("tenant_id")
    if tenant_id:
        try:
            u = db.get_user_by_id(int(tenant_id))
            if u and u.get("dc_id") in (1, 2, 3, 4, 5):
                return int(u["dc_id"])
        except Exception:
            pass

    return 5


def get_cluster_bots_catalog(search_query: str = "", dc_id: int | None = None) -> List[Dict[str, Any]]:
    """
    返回全集群 80 个 Bot 的元数据大清单，用于前端展示与手动精确分配。
    支持按 DC 筛选及按用户名/前缀搜索。
    """
    pool = get_dc_bot_pool()
    primary_token = str(db.get_config("BOT_TOKEN") or getattr(Var, "BOT_TOKEN", "") or "").strip()

    # 查询当前所有边缘节点已分配的 Bot 统计
    assigned_map: Dict[str, List[Dict[str, Any]]] = {}
    try:
        nodes = db.list_edge_nodes()
        for n in nodes:
            t = (n.get("assigned_bot_token") or "").strip()
            if t:
                assigned_map.setdefault(t, []).append({
                    "id": n.get("id"),
                    "name": n.get("node_name") or f"Node-{n.get('id')}",
                })
    except Exception:
        pass

    catalog: List[Dict[str, Any]] = []
    seen_tokens = set()
    idx = 0

    # 按照 DC 排序: DC5, DC1, DC2, DC3, DC4
    for d in (5, 1, 2, 3, 4):
        bots_in_dc = pool.get(d, [])
        for b in bots_in_dc:
            tok = b["token"]
            if tok in seen_tokens:
                continue
            seen_tokens.add(tok)

            pfx = b.get("prefix") or (tok.split(":", 1)[0] if ":" in tok else "")
            uname = b.get("username") or f"bot_{pfx}"
            is_main = (tok == primary_token)
            assigned_nodes = assigned_map.get(tok, [])

            if dc_id is not None and int(dc_id) != int(d):
                continue
            if search_query:
                sq = search_query.strip().lower().lstrip("@")
                if sq not in uname.lower() and sq not in pfx.lower():
                    continue

            mask = f"{pfx}:{'*' * 8}{tok[-4:]}" if len(tok) > 12 else tok

            catalog.append({
                "bot_index": idx,
                "token": tok,
                "token_mask": mask,
                "prefix": pfx,
                "username": uname,
                "dc_id": int(d),
                "is_main": is_main,
                "assigned_nodes": assigned_nodes,
                "assigned_count": len(assigned_nodes),
            })
            idx += 1

    return catalog


def calculate_recommended_bots(
    down_speed_mb_s: Optional[float] = None,
    max_cap: int = 24,
    rtt_ms: Optional[float] = None,
    up_speed_mb_s: Optional[float] = None,
    effective_bw_mb_s: Optional[float] = None,
) -> int:
    """
    根据实测 VPS 物理宽带下行(Ingress)与上行出网(Egress)吞吐 (MB/s) 取木桶短板有效带宽 min(down, up)，
    并结合目标 Telegram DC 往返延迟 (RTT)，动态换算推荐匹配的 Bot 数量。
    - RTT <= 50ms (低延迟直连，如香港到新加坡 DC5): 单 Bot 额定吞吐 ~2.0 MB/s
    - 50ms < RTT <= 110ms (跨大陆链路，如美西到美东迈阿密 DC1): 单 Bot 额定吞吐 ~1.2 MB/s
    - RTT > 110ms (跨大洋高延迟): 单 Bot 额定吞吐 ~0.8 MB/s
    保底 2 个 Bot，最高封顶 max_cap (默认 24 个 Bot)。
    """
    if effective_bw_mb_s is not None and float(effective_bw_mb_s) > 0:
        eff_bw = float(effective_bw_mb_s)
    elif down_speed_mb_s is not None and float(down_speed_mb_s) > 0:
        down = float(down_speed_mb_s)
        if up_speed_mb_s is not None and float(up_speed_mb_s) > 0:
            eff_bw = min(down, float(up_speed_mb_s))
        else:
            eff_bw = down
    elif up_speed_mb_s is not None and float(up_speed_mb_s) > 0:
        eff_bw = float(up_speed_mb_s)
    else:
        return 4

    if rtt_ms is not None and float(rtt_ms) > 0:
        rtt = float(rtt_ms)
        if rtt <= 50.0:
            per_bot_speed = 2.0
        elif rtt <= 110.0:
            per_bot_speed = 1.2
        else:
            per_bot_speed = 0.8
    else:
        per_bot_speed = 2.0

    needed = math.ceil(eff_bw / per_bot_speed)
    return max(2, min(needed, max_cap))


def allocate_bots_for_edge_node(node: Dict[str, Any], requested_bot_count: Optional[int] = None) -> Dict[str, Any]:
    """
    为边缘节点智能分配同 DC 原生主 Bot 与弹性并发 Bot 阵列，并组装跨 DC 路由表与主控保底凭证。
    支持跨 DC 精确手动指定 Bot Token。
    """
    node_id = int(node.get("id") or 0)
    target_dc = infer_node_target_dc(node)
    pool = get_dc_bot_pool()

    # 1. 确定原生主 Bot (支持全库跨 DC 精确匹配)
    assigned_token = (node.get("assigned_bot_token") or "").strip()
    primary_token = ""
    primary_username = (node.get("assigned_bot_username") or "").strip()
    matched_dc = None

    if assigned_token:
        for d, b_list in pool.items():
            for b in b_list:
                if b["token"] == assigned_token or b["prefix"] == assigned_token:
                    primary_token = b["token"]
                    if not primary_username:
                        primary_username = b.get("username", "")
                    matched_dc = d
                    break
            if primary_token:
                break
        if not primary_token:
            primary_token = assigned_token
        if matched_dc:
            target_dc = matched_dc
    else:
        dc_bots = pool.get(target_dc, [])
        if not dc_bots:
            dc_bots = pool.get(5) or pool.get(1) or []
        if dc_bots:
            idx = node_id % len(dc_bots)
            chosen = dc_bots[idx]
            primary_token = chosen["token"]
            primary_username = chosen.get("username", "")
        else:
            primary_token = str(getattr(Var, "BOT_TOKEN", "") or "").strip()

    # 2. 组建同 DC 弹性并发 Bot 阵列 (依据实测 VPS 物理宽带按 2.0 MB/s/Bot 动态匹配，上限 24)
    allow_pool = bool(node.get("allow_bot_pool", True))
    bot_tokens: List[str] = []
    if primary_token:
        bot_tokens.append(primary_token)

    if requested_bot_count is not None and int(requested_bot_count) > 0:
        target_count = max(2, min(int(requested_bot_count), 100))
    elif node.get("target_bot_count"):
        target_count = max(2, min(int(node["target_bot_count"]), 100))
    else:
        bench_data = node.get("benchmark_data") or {}
        if isinstance(bench_data, str):
            try:
                bench_data = json.loads(bench_data)
            except Exception:
                bench_data = {}
        bw_info = bench_data.get("bandwidth") or {}
        down_spd = bw_info.get("down_speed_mb_s") or bench_data.get("link", {}).get("down_speed_mb_s")
        up_spd = bw_info.get("up_speed_mb_s")
        eff_spd = bw_info.get("effective_bw_mb_s")
        fastest_dc = bench_data.get("fastest_dc") or {}
        dc_rtt = fastest_dc.get("avg_rtt_ms") or fastest_dc.get("rtt_ms")
        sys_info = bench_data.get("diagnostics", {}).get("system") or {}
        mem_mb = float(sys_info.get("mem_total_mb") or 0.0)
        auto_cap = 100 if mem_mb >= 1500 else 24
        target_count = calculate_recommended_bots(
            down_speed_mb_s=down_spd,
            up_speed_mb_s=up_spd,
            effective_bw_mb_s=eff_spd,
            max_cap=auto_cap,
            rtt_ms=dc_rtt,
        )

    dc_bots = pool.get(target_dc, [])
    if allow_pool and dc_bots:
        for b in dc_bots:
            t = b["token"]
            if t not in bot_tokens:
                bot_tokens.append(t)
            if len(bot_tokens) >= target_count:
                break
    # 仅当用户显式指定请求的 Bot 数超过当前 DC 资产数时，才从其他 DC 自动补充
    if allow_pool and (requested_bot_count is not None and int(requested_bot_count) > 0) and len(bot_tokens) < target_count:
        for o_dc, o_bots in pool.items():
            if o_dc != target_dc:
                for b in o_bots:
                    t = b["token"]
                    if t not in bot_tokens:
                        bot_tokens.append(t)
                    if len(bot_tokens) >= target_count:
                        break
            if len(bot_tokens) >= target_count:
                break

    # 3. 构造跨 DC 直通 Bot 映射表 (至少包含 DC1 与 DC5)
    dc_bot_map: Dict[str, str] = {}
    for d_num in (1, 2, 3, 4, 5):
        bl = pool.get(d_num, [])
        if bl:
            dc_bot_map[str(d_num)] = bl[0]["token"]

    # 虚拟/镜像映射
    if "1" in dc_bot_map and "3" not in dc_bot_map:
        dc_bot_map["3"] = dc_bot_map["1"]
    if "4" in dc_bot_map and "2" not in dc_bot_map:
        dc_bot_map["2"] = dc_bot_map["4"]
    elif "2" in dc_bot_map and "4" not in dc_bot_map:
        dc_bot_map["4"] = dc_bot_map["2"]

    # 4. Master Bot 全局保底凭证 (用于私有 BIN_CHANNEL 等兜底)
    master_tok = str(getattr(Var, "BOT_TOKEN", "") or "").strip()
    master_uname = ""
    try:
        from WebStreamer.bot import StreamBot
        if StreamBot and getattr(StreamBot, "me", None):
            master_uname = getattr(StreamBot.me, "username", "") or ""
    except Exception:
        pass
    if not master_uname:
        for b_list in pool.values():
            for b in b_list:
                if b["token"] == master_tok:
                    master_uname = b.get("username", "")
                    break
            if master_uname:
                break

    # 5. 生成无锁已授权 Session Strings (彻底避免远程节点启动触发 Telegram 420 FLOOD_WAIT)
    api_id_val = int(getattr(Var, "API_ID", 0) or 2420373)
    primary_session_str = export_bot_session_string(primary_token, api_id_val)
    bot_session_strings = [export_bot_session_string(t, api_id_val) for t in bot_tokens]
    dc_session_map = {str(d): export_bot_session_string(t, api_id_val) for d, t in dc_bot_map.items()}
    master_session_str = export_bot_session_string(master_tok, api_id_val)

    return {
        "target_dc": target_dc,
        "primary_bot_token": primary_token,
        "primary_bot_username": primary_username,
        "primary_session_string": primary_session_str,
        "target_bot_count": len(bot_tokens),
        "bot_tokens": bot_tokens,
        "bot_session_strings": bot_session_strings,
        "dc_bot_map": dc_bot_map,
        "dc_session_map": dc_session_map,
        "allow_bot_pool": allow_pool,
        "master_bot_token": master_tok,
        "master_bot_username": master_uname.lstrip("@"),
        "master_session_string": master_session_str,
    }


def mask_username(username: str) -> str:
    """对多租户借用公共池节点展示时的用户名进行脱敏保护"""
    if not username:
        return "公共/访客"
    uname = str(username).strip()
    if uname in ("公共/访客", "Public", "访客") or uname.startswith("租户#"):
        return uname

    has_at = uname.startswith("@")
    clean = uname[1:] if has_at else uname

    if len(clean) <= 2:
        masked = f"{clean[:1]}***"
    elif len(clean) == 3:
        masked = f"{clean[:2]}***"
    else:
        masked = f"{clean[:3]}***"

    return f"@{masked}"


def enrich_node_tenants(raw_tenants: Any, node_owner_id: Optional[int] = None) -> list:
    """
    将边缘节点上报的 tenants 字典或列表富化为带用户名、身份、时间戳的结构化列表
    并按活跃状态、实时速率、累计流量降序排序
    """
    result = []
    items = []
    if isinstance(raw_tenants, dict):
        for k, v in raw_tenants.items():
            if isinstance(v, dict):
                item_copy = dict(v)
                if "tenant_id" not in item_copy or item_copy.get("tenant_id") is None:
                    try:
                        item_copy["tenant_id"] = int(k)
                    except Exception:
                        item_copy["tenant_id"] = 0
                items.append(item_copy)
    elif isinstance(raw_tenants, list):
        items = list(raw_tenants)

    owner_id = int(node_owner_id or 0)
    user_cache = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            tid = int(item.get("tenant_id") if item.get("tenant_id") is not None else 0)
        except Exception:
            tid = 0

        username = "公共/访客"
        role = "guest"
        if tid == 0:
            username = "公共/访客"
        else:
            if tid not in user_cache:
                u = db.get_user_by_id(tid)
                user_cache[tid] = u
            else:
                u = user_cache[tid]

            if u:
                username = u.get("username") or f"租户#{tid}"
                role = u.get("role") or "user"
            else:
                username = f"租户#{tid}"

        active = int(item.get("active_streams") or 0)
        net_tx = int(item.get("net_tx") or 0)
        total_bytes = int(item.get("total_bytes") or 0)
        last_active = item.get("last_active")

        last_active_iso = ""
        if isinstance(last_active, (int, float)) and last_active > 0:
            try:
                last_active_iso = datetime.fromtimestamp(last_active, timezone.utc).isoformat()
            except Exception:
                last_active_iso = str(last_active)
        elif isinstance(last_active, str):
            last_active_iso = last_active

        is_owner = (tid > 0 and tid == owner_id)

        result.append({
            "tenant_id": tid,
            "username": username,
            "is_owner": is_owner,
            "role": role,
            "active_streams": active,
            "net_tx": net_tx,
            "total_bytes": total_bytes,
            "last_active": last_active_iso,
        })

    result.sort(key=lambda x: (
        1 if (x["active_streams"] > 0 or x["net_tx"] > 0) else 0,
        x["net_tx"],
        x["total_bytes"],
    ), reverse=True)

    return result


def merge_node_tenants_metrics(
    existing_tenants: Any,
    new_raw_tenants: Any,
    node_owner_id: Optional[int] = None,
) -> list:
    """
    合并新上报的 tenants 指标与已持久化的 tenants 数据（防 Worker 重启流量倒退）
    并富化为格式化有序列表
    """
    old_by_tid = {}
    if isinstance(existing_tenants, list):
        for item in existing_tenants:
            if isinstance(item, dict) and "tenant_id" in item:
                try:
                    old_by_tid[int(item["tenant_id"])] = item
                except Exception:
                    pass
    elif isinstance(existing_tenants, dict):
        for k, item in existing_tenants.items():
            if isinstance(item, dict):
                try:
                    tid = int(item.get("tenant_id") if item.get("tenant_id") is not None else k)
                    old_by_tid[tid] = item
                except Exception:
                    pass

    new_by_tid = {}
    if isinstance(new_raw_tenants, list):
        for item in new_raw_tenants:
            if isinstance(item, dict):
                try:
                    tid = int(item.get("tenant_id") or 0)
                    new_by_tid[tid] = item
                except Exception:
                    pass
    elif isinstance(new_raw_tenants, dict):
        for k, item in new_raw_tenants.items():
            if isinstance(item, dict):
                try:
                    tid = int(item.get("tenant_id") if item.get("tenant_id") is not None else k)
                except Exception:
                    tid = 0
                new_by_tid[tid] = item

    all_tids = set(old_by_tid.keys()) | set(new_by_tid.keys())
    merged_raw_dict = {}

    for tid in all_tids:
        old_data = old_by_tid.get(tid, {})
        new_data = new_by_tid.get(tid, {})

        old_total = int(old_data.get("total_bytes") or 0)
        new_total = int(new_data.get("total_bytes") or 0)
        merged_total = max(old_total, new_total)

        active_streams = int(new_data.get("active_streams") or 0)
        net_tx = int(new_data.get("net_tx") or 0)
        last_active = new_data.get("last_active") or old_data.get("last_active")

        merged_raw_dict[tid] = {
            "tenant_id": tid,
            "active_streams": active_streams,
            "net_tx": net_tx,
            "total_bytes": merged_total,
            "last_active": last_active,
        }

    return enrich_node_tenants(merged_raw_dict, node_owner_id=node_owner_id)


def sanitize_node_tenants_for_user(node: dict, user_id: Optional[int], is_admin: bool) -> dict:
    """
    针对普通租户视角，对非本人的借用者用户名进行脱敏
    返回处理后的深拷贝 node 字典
    """
    node_copy = copy.deepcopy(node)
    metrics = node_copy.get("metrics")
    if not isinstance(metrics, dict):
        return node_copy

    tenants = metrics.get("tenants")
    if isinstance(tenants, dict):
        from edge_node_manager import enrich_node_tenants
        tenants = enrich_node_tenants(tenants, node_owner_id=node_copy.get("tenant_id"))
        node_copy["metrics"]["tenants"] = tenants
    if not isinstance(tenants, list):
        return node_copy

    if is_admin:
        return node_copy

    current_uid = int(user_id or 0)
    sanitized_tenants = []
    for t in tenants:
        t_copy = dict(t)
        tid = int(t_copy.get("tenant_id") or 0)
        if tid != current_uid and tid > 0:
            orig_uname = t_copy.get("username", "")
            t_copy["username"] = mask_username(orig_uname)
            t_copy["masked"] = True
        sanitized_tenants.append(t_copy)

    node_copy["metrics"]["tenants"] = sanitized_tenants
    return node_copy


def compute_edge_summary(nodes: list) -> dict:
    """统一计算边缘节点 KPI 汇总指标及全网租户分流总榜"""
    total_nodes = len(nodes)
    online_nodes = sum(1 for n in nodes if n.get("status") == "online")
    deploying_nodes = sum(1 for n in nodes if n.get("status") == "deploying")
    shared_pool_nodes = sum(1 for n in nodes if n.get("allow_shared_pool") and n.get("status") == "online")
    active_streams = sum(int((n.get("metrics") or {}).get("active_streams", 0)) for n in nodes)
    total_tx_speed = sum(int((n.get("metrics") or {}).get("net_tx", 0)) for n in nodes)
    total_bytes_served = sum(int((n.get("metrics") or {}).get("total_bytes_served", 0)) for n in nodes)

    tenant_agg = {}
    for n in nodes:
        metrics = n.get("metrics") or {}
        tenants = metrics.get("tenants") or []
        tenant_items = []
        if isinstance(tenants, list):
            tenant_items = tenants
        elif isinstance(tenants, dict):
            for k, val in tenants.items():
                if isinstance(val, dict):
                    val_c = dict(val)
                    if "tenant_id" not in val_c:
                        try:
                            val_c["tenant_id"] = int(k)
                        except Exception:
                            val_c["tenant_id"] = 0
                    tenant_items.append(val_c)

        for t in tenant_items:
            if not isinstance(t, dict):
                continue
            tid = t.get("tenant_id")
            if tid is None:
                continue
            try:
                tid = int(tid)
            except Exception:
                continue
            if tid not in tenant_agg:
                raw_uname = t.get("username")
                if not raw_uname:
                    if tid == 0:
                        raw_uname = "公共/访客"
                    else:
                        try:
                            import db
                            u = db.get_user_by_id(tid)
                            raw_uname = u.get("username") if u else f"租户#{tid}"
                        except Exception:
                            raw_uname = f"租户#{tid}"
                tenant_agg[tid] = {
                    "tenant_id": tid,
                    "username": raw_uname,
                    "active_streams": 0,
                    "net_tx": 0,
                    "total_bytes": 0,
                    "node_count": 0,
                    "last_active": t.get("last_active") or "",
                }
            tenant_agg[tid]["active_streams"] += int(t.get("active_streams") or 0)
            tenant_agg[tid]["net_tx"] += int(t.get("net_tx") or 0)
            tenant_agg[tid]["total_bytes"] += int(t.get("total_bytes") or 0)
            tenant_agg[tid]["node_count"] += 1
            if t.get("last_active") and str(t.get("last_active")) > str(tenant_agg[tid]["last_active"]):
                tenant_agg[tid]["last_active"] = t.get("last_active")

    top_tenants = list(tenant_agg.values())
    top_tenants.sort(key=lambda x: (
        1 if (x["active_streams"] > 0 or x["net_tx"] > 0) else 0,
        x["net_tx"],
        x["total_bytes"],
    ), reverse=True)

    return {
        "total_nodes": total_nodes,
        "online_nodes": online_nodes,
        "deploying_nodes": deploying_nodes,
        "shared_pool_nodes": shared_pool_nodes,
        "active_streams": active_streams,
        "total_tx_speed": total_tx_speed,
        "total_bytes_served": total_bytes_served,
        "tenants": top_tenants,
    }


async def broadcast_edge_node_update(node_id: int):
    """向管理端及所属租户 WebSocket 客户端实时推送单节点及其汇总状态更新"""
    try:
        from WebStreamer.server.ws_manager import ws_manager
        node = db.get_edge_node_by_id(node_id)
        if not node:
            return
        uid = node.get("tenant_id")

        # 1. 广播给管理员（附带全局 summary，仅管理员可见，绝不泄露给普通租户）
        all_nodes = db.list_edge_nodes(tenant_id=None, include_secrets=False)
        admin_summary = compute_edge_summary(all_nodes)
        await ws_manager.send_edge_node_update(
            node_data=node,
            summary=admin_summary,
            target_user_id=None,
            admin_only=True,
        )

        # 2. 若归属普通租户，精确广播给该租户（附带该租户个人 summary，脱敏其他租户用户名）
        if uid:
            target_user = db.get_user_by_id(uid)
            # 若节点主人是管理员，管理员已在第1步接收全网全局 summary，绝不可发送局部租户 summary 冲刷管理员视角
            if not target_user or target_user.get("role") != "admin":
                tenant_node_data = sanitize_node_tenants_for_user(node, user_id=uid, is_admin=False)
                tenant_nodes = db.list_edge_nodes(tenant_id=uid, include_secrets=False)
                tenant_summary = compute_edge_summary(tenant_nodes)
                sanitized_summary_tenants = []
                for st in tenant_summary.get("tenants", []):
                    st_c = dict(st)
                    if st_c.get("tenant_id") != uid and st_c.get("tenant_id", 0) > 0:
                        st_c["username"] = mask_username(st_c.get("username", ""))
                        st_c["masked"] = True
                    sanitized_summary_tenants.append(st_c)
                tenant_summary["tenants"] = sanitized_summary_tenants

                await ws_manager.send_edge_node_update(
                    node_data=tenant_node_data,
                    summary=tenant_summary,
                    target_user_id=uid,
                    exact_target=True,
                )
    except Exception as e:
        logger.debug(f"广播边缘节点更新失败: {e}")


async def broadcast_edge_node_deleted(node_id: int, target_user_id: Optional[int] = None):
    """向管理端及所属租户 WebSocket 客户端实时推送节点删除事件"""
    try:
        from WebStreamer.server.ws_manager import ws_manager
        all_nodes = db.list_edge_nodes(tenant_id=None, include_secrets=False)
        admin_summary = compute_edge_summary(all_nodes)
        await ws_manager.send_edge_node_deleted(
            node_id=node_id,
            summary=admin_summary,
            target_user_id=None,
            admin_only=True,
        )
        if target_user_id:
            target_user = db.get_user_by_id(target_user_id)
            if not target_user or target_user.get("role") != "admin":
                tenant_nodes = db.list_edge_nodes(tenant_id=target_user_id, include_secrets=False)
                tenant_summary = compute_edge_summary(tenant_nodes)
                await ws_manager.send_edge_node_deleted(
                    node_id=node_id,
                    summary=tenant_summary,
                    target_user_id=target_user_id,
                    exact_target=True,
                )
    except Exception as e:
        logger.debug(f"广播边缘节点删除失败: {e}")


async def broadcast_edge_deploy_log(node_id: int, line: Optional[str] = None, deploy_log: Optional[str] = None, status: Optional[str] = None, target_user_id: Optional[int] = None):
    """实时推送边缘节点部署日志流"""
    try:
        from WebStreamer.server.ws_manager import ws_manager
        await ws_manager.send_edge_deploy_log(
            node_id=node_id,
            line=line,
            deploy_log=deploy_log,
            status=status,
            target_user_id=target_user_id,
        )
    except Exception as e:
        logger.debug(f"推送边缘节点部署日志失败: {e}")
