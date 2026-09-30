import pyrogram_patch
try:
    import pyrogram.errors.rpc_error
    _orig_rpc_init = pyrogram.errors.rpc_error.RPCError.__init__
    def _safe_rpc_init(self, *args, **kwargs):
        try:
            if "is_unknown" in kwargs:
                kwargs["is_unknown"] = False
            _orig_rpc_init(self, *args, **kwargs)
        except OSError:
            pass
    pyrogram.errors.rpc_error.RPCError.__init__ = _safe_rpc_init
except Exception:
    pass

"""
@BotFather 自动化流水线与协议号资产池服务 (BotFather Creator & Account Pool)
========================================================================
使用 Telegram API 协议号自动化与 @BotFather 对话：
1. 协议号资产池持久化纳管（支持多行 [手机号|接码链接]、Session String、多 .session 文件批量导入）；
2. 多号跨账号自动接力扩容（单号达 20 上限或受限时自动无缝切换下一账号，突破单号 20 机器人限制）；
3. 单号精准独立铸造（指定特定协议号提取存量或新建机器人）；
4. 签发 Token 即时热挂载至负载均衡集群。
"""

import os
import sqlite3
import re
import json
import time
import hashlib
import secrets
import asyncio
import logging
from typing import List, Dict, Tuple, Optional, Any, Callable, Union

try:
    from pyrogram import Client, raw
    from pyrogram.errors import FloodWait, RPCError
except ImportError:
    Client = None
    FloodWait = Exception
    RPCError = Exception

import db
from session_adapter import (
    parse_session_to_pyrogram_string,
    pack_pyrogram_session,
    extract_dc_and_auth_key_from_telethon_string,
    extract_from_pyrogram_string,
    inspect_session_metadata,
)
from WebStreamer.vars import Var

logger = logging.getLogger("botfather_creator")

TOKEN_REGEX = re.compile(r"(\d{5,12}:[A-Za-z0-9_-]{30,})")

_PHONE_SESSION_CACHE: Dict[str, str] = {}
_CACHE_FILES = [
    "/app/db/sessions/tg_phone_sessions.json",
    "/tmp/tg_phone_sessions.json",
    "db/sessions/tg_phone_sessions.json",
]
_CREDENTIALS_CACHE_FILES = [
    "/app/db/sessions/tg_api_credentials.json",
    "/tmp/tg_api_credentials.json",
    "db/sessions/tg_api_credentials.json",
]


def _normalize_phone_key(phone: str) -> str:
    norm = str(phone or "").strip()
    if re.fullmatch(r"\d{8,15}", norm):
        norm = "+" + norm
    return norm


def _save_cached_credentials(phone: str, api_id: Optional[int], api_hash: Optional[str]) -> None:
    norm = _normalize_phone_key(phone)
    if not norm or not api_id or not api_hash:
        return
    for cpath in _CREDENTIALS_CACHE_FILES:
        try:
            os.makedirs(os.path.dirname(cpath), exist_ok=True)
            data: Dict[str, Any] = {}
            if os.path.exists(cpath):
                with open(cpath, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    if isinstance(content, dict):
                        data = content
            data[norm] = {
                "api_id": int(api_id),
                "api_hash": str(api_hash).strip(),
                "updated_at": db._now_iso(),
            }
            with open(cpath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"保存凭证文件备份异常 {cpath}: {e}")


def _remove_cached_credentials(phone: str) -> None:
    norm = _normalize_phone_key(phone)
    if not norm:
        return
    for cpath in _CREDENTIALS_CACHE_FILES:
        try:
            if os.path.exists(cpath):
                with open(cpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and norm in data:
                    data.pop(norm, None)
                    with open(cpath, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"清理凭证文件备份异常 {cpath}: {e}")


def _load_cached_credentials() -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for cpath in _CREDENTIALS_CACHE_FILES:
        if os.path.exists(cpath):
            try:
                with open(cpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, dict) and v.get("api_id") and v.get("api_hash"):
                                merged[_normalize_phone_key(k)] = v
            except Exception:
                pass
    return merged


def _normalize_session_str(sess_str: str) -> str:
    if sess_str and sess_str.startswith("1") and len(sess_str) > 280:
        try:
            dc_id, auth_key = extract_dc_and_auth_key_from_telethon_string(sess_str)
            return pack_pyrogram_session(
                dc_id=dc_id,
                auth_key=auth_key,
                api_id=Var.API_ID or 2040,
                user_id=1,
            )
        except Exception:
            pass
    return sess_str


def _get_cached_session(phone: str) -> Optional[str]:
    norm_phone = phone.strip()
    if re.fullmatch(r"\d{8,15}", norm_phone):
        norm_phone = "+" + norm_phone

    # 1. 优先从 SQLite 协议号资产池查询
    try:
        acc = db.get_protocol_account_by_phone(norm_phone)
        if acc and acc.get("session_data"):
            sess = _normalize_session_str(acc["session_data"])
            _PHONE_SESSION_CACHE[norm_phone] = sess
            return sess
    except Exception:
        pass

    # 2. 内存与 JSON 文件兜底
    if norm_phone in _PHONE_SESSION_CACHE:
        return _PHONE_SESSION_CACHE[norm_phone]
    for cpath in _CACHE_FILES:
        if os.path.exists(cpath):
            try:
                with open(cpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get(norm_phone):
                        sess = _normalize_session_str(data[norm_phone])
                        _PHONE_SESSION_CACHE[norm_phone] = sess
                        try:
                            db.upsert_protocol_account(phone=norm_phone, session_data=sess)
                        except Exception:
                            pass
                        return sess
            except Exception:
                pass
    return None


def _save_cached_session(
    phone: str,
    session_str: str,
    code_url: Optional[str] = None,
    bot_count: Optional[int] = None,
    status: Optional[str] = None,
    remark: Optional[str] = None,
    session_type: str = "pyrogram_string",
    api_id: Optional[int] = None,
    api_hash: Optional[str] = None,
    two_fa_password: Optional[str] = None,
    two_fa_hint: Optional[str] = None,
    has_two_fa: Optional[int] = None,
    local_otp_token: Optional[str] = None,
) -> Optional[Dict]:
    norm_phone = phone.strip()
    if re.fullmatch(r"\d{8,15}", norm_phone):
        norm_phone = "+" + norm_phone
    session_str = _normalize_session_str(session_str)

    _PHONE_SESSION_CACHE[norm_phone] = session_str
    for cpath in _CACHE_FILES:
        try:
            os.makedirs(os.path.dirname(cpath), exist_ok=True)
            data = {}
            if os.path.exists(cpath):
                with open(cpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data[norm_phone] = session_str
            with open(cpath, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    if api_id and api_hash:
        _save_cached_credentials(norm_phone, api_id, api_hash)

    try:
        return db.upsert_protocol_account(
            phone=norm_phone,
            session_data=session_str,
            session_type=session_type,
            code_url=code_url,
            bot_count=bot_count,
            status=status,
            remark=remark,
            api_id=api_id,
            api_hash=api_hash,
            two_fa_password=two_fa_password,
            two_fa_hint=two_fa_hint,
            has_two_fa=has_two_fa,
            local_otp_token=local_otp_token,
        )
    except Exception as e:
        logger.debug(f"持久化协议号到数据库异常: {e}")
        return None


DEFAULT_TELEGRAM_API_PROXY_URL = os.getenv("TELEGRAM_API_PROXY_URL", "").strip()

PREFIX_REGION_MAP = {
    # 4-digit prefixes (Canada area codes & NANP territories)
    '1204': 'CA', '1226': 'CA', '1236': 'CA', '1249': 'CA', '1250': 'CA', '1263': 'CA', '1289': 'CA',
    '1306': 'CA', '1343': 'CA', '1354': 'CA', '1365': 'CA', '1367': 'CA', '1368': 'CA', '1382': 'CA',
    '1403': 'CA', '1416': 'CA', '1418': 'CA', '1428': 'CA', '1431': 'CA', '1437': 'CA', '1438': 'CA',
    '1450': 'CA', '1468': 'CA', '1474': 'CA', '1506': 'CA', '1514': 'CA', '1519': 'CA', '1548': 'CA',
    '1579': 'CA', '1581': 'CA', '1584': 'CA', '1587': 'CA', '1604': 'CA', '1613': 'CA', '1639': 'CA',
    '1647': 'CA', '1672': 'CA', '1683': 'CA', '1705': 'CA', '1709': 'CA', '1742': 'CA', '1753': 'CA',
    '1778': 'CA', '1780': 'CA', '1782': 'CA', '1807': 'CA', '1819': 'CA', '1825': 'CA', '1867': 'CA',
    '1873': 'CA', '1879': 'CA', '1902': 'CA', '1905': 'CA',
    '1242': 'BS', '1246': 'BB', '1264': 'AI', '1268': 'AG', '1441': 'BM', '1473': 'GD', '1649': 'TC',
    '1664': 'MS', '1670': 'MP', '1671': 'GU', '1684': 'AS', '1721': 'SX', '1758': 'LC', '1767': 'DM',
    '1784': 'VC', '1787': 'PR', '1939': 'PR', '1809': 'DO', '1829': 'DO', '1849': 'DO', '1868': 'TT',
    '1869': 'KN', '1876': 'JM', '1658': 'JM', '1345': 'KY', '1284': 'VG', '1340': 'VI',
    # 3-digit prefixes
    '852': 'HK', '853': 'MO', '855': 'KH', '856': 'LA', '880': 'BD', '886': 'TW',
    '960': 'MV', '961': 'LB', '962': 'JO', '963': 'SY', '964': 'IQ', '965': 'KW', '966': 'SA', '967': 'YE', '968': 'OM',
    '970': 'PS', '971': 'AE', '972': 'IL', '973': 'BH', '974': 'QA', '975': 'BT', '976': 'MN', '977': 'NP',
    '992': 'TJ', '993': 'TM', '994': 'AZ', '995': 'GE', '996': 'KG', '998': 'UZ',
    '351': 'PT', '352': 'LU', '353': 'IE', '354': 'IS', '355': 'AL', '356': 'MT', '357': 'CY', '358': 'FI', '359': 'BG',
    '370': 'LT', '371': 'LV', '372': 'EE', '373': 'MD', '374': 'AM', '375': 'BY', '376': 'AD', '377': 'MC', '378': 'SM',
    '380': 'UA', '381': 'RS', '382': 'ME', '383': 'XK', '385': 'HR', '386': 'SI', '387': 'BA', '389': 'MK',
    '420': 'CZ', '421': 'SK', '423': 'LI',
    '211': 'SS', '212': 'MA', '213': 'DZ', '216': 'TN', '218': 'LY', '220': 'GM', '221': 'SN', '222': 'MR', '223': 'ML',
    '224': 'GN', '225': 'CI', '226': 'BF', '227': 'NE', '228': 'TG', '229': 'BJ', '230': 'MU', '231': 'LR', '232': 'SL',
    '233': 'GH', '234': 'NG', '235': 'TD', '236': 'CF', '237': 'CM', '238': 'CV', '239': 'ST', '240': 'GQ', '241': 'GA',
    '242': 'CG', '243': 'CD', '244': 'AO', '245': 'GW', '248': 'SC', '249': 'SD', '250': 'RW', '251': 'ET', '252': 'SO',
    '253': 'DJ', '254': 'KE', '255': 'TZ', '256': 'UG', '257': 'BI', '258': 'MZ', '260': 'ZM', '261': 'MG', '263': 'ZW',
    '264': 'NA', '265': 'MW', '266': 'LS', '267': 'BW', '268': 'SZ', '269': 'KM',
    '501': 'BZ', '502': 'GT', '503': 'SV', '504': 'HN', '505': 'NI', '506': 'CR', '507': 'PA', '509': 'HT',
    '590': 'GP', '591': 'BO', '592': 'GY', '593': 'EC', '594': 'GF', '595': 'PY', '596': 'MQ', '597': 'SR', '598': 'UY', '599': 'CW',
    '670': 'TL', '672': 'NF', '673': 'BN', '674': 'NR', '675': 'PG', '676': 'TO', '677': 'SB', '678': 'VU', '679': 'FJ',
    '680': 'PW', '681': 'WF', '682': 'CK', '683': 'NU', '685': 'WS', '686': 'KI', '687': 'NC', '688': 'TV', '689': 'PF',
    '690': 'TK', '691': 'FM', '692': 'MH',
    '76': 'KZ', '77': 'KZ',
    # 2-digit prefixes
    '20': 'EG', '27': 'ZA', '30': 'GR', '31': 'NL', '32': 'BE', '33': 'FR', '34': 'ES', '36': 'HU', '39': 'IT',
    '40': 'RO', '41': 'CH', '43': 'AT', '44': 'GB', '45': 'DK', '46': 'SE', '47': 'NO', '48': 'PL', '49': 'DE',
    '51': 'PE', '52': 'MX', '53': 'CU', '54': 'AR', '55': 'BR', '56': 'CL', '57': 'CO', '58': 'VE',
    '60': 'MY', '61': 'AU', '62': 'ID', '63': 'PH', '64': 'NZ', '65': 'SG', '66': 'TH',
    '81': 'JP', '82': 'KR', '84': 'VN', '86': 'CN',
    '90': 'TR', '91': 'IN', '92': 'PK', '93': 'AF', '94': 'LK', '95': 'MM', '98': 'IR',
    # 1-digit prefixes
    '1': 'US', '7': 'RU',
}

def detect_region_from_phone(phone: str) -> str:
    """根据国际电话号码最长前缀识别所属国家/地区 ISO 两位代码 (如 US, MM, GB)"""
    digits = re.sub(r"\D+", "", str(phone or ""))
    if not digits:
        return "US"
    for length in (4, 3, 2, 1):
        if len(digits) >= length:
            prefix = digits[:length]
            if prefix in PREFIX_REGION_MAP:
                return PREFIX_REGION_MAP[prefix]
    return "US"

def get_api_proxy_config() -> str:
    """获取当前配置的 Telegram API 家宽代理接口地址"""
    return db.get_config("TELEGRAM_API_PROXY_URL", "") or DEFAULT_TELEGRAM_API_PROXY_URL

def set_api_proxy_config(proxy_api_url: str) -> str:
    """持久化保存 Telegram API 家宽代理接口地址"""
    val = (proxy_api_url or "").strip() or DEFAULT_TELEGRAM_API_PROXY_URL
    db.set_config("TELEGRAM_API_PROXY_URL", val)
    return val

def build_regional_proxy_api_url(region: str, proxy_api_url: Optional[str] = None) -> str:
    """
    根据目标国家/地区代码生成家宽代理提取 API 链接：
    - 无论配置的 URL 是模板（含 {region} 占位符）还是已写死 region=US，
      均自动替换为目标账号真实的 region（如 region=MM、region=US、region=GB 等）。
    """
    clean_region = (region or "US").strip().upper()
    base_url = (proxy_api_url or "").strip() or get_api_proxy_config()
    if not base_url:
        raise ValueError("未配置家宽代理提取接口 URL，请在 Web 端协议号资产池设置或配置环境变量 TELEGRAM_API_PROXY_URL")

    if "{region}" in base_url:
        return base_url.replace("{region}", clean_region)
    if re.search(r"([?&]region=)[^&]*", base_url, flags=re.IGNORECASE):
        return re.sub(r"([?&]region=)[^&]*", rf"\g<1>{clean_region}", base_url, flags=re.IGNORECASE)

    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}region={clean_region}"

def parse_proxy_line(raw_text: str) -> Optional[str]:
    """从代理 API 响应文本中解析并归一化代理地址为标准 URL 格式 (http://ip:port 或 http://user:pass@ip:port)"""
    if not raw_text:
        return None
    raw_clean = raw_text.strip()
    if (raw_clean.startswith("{") and raw_clean.endswith("}")) or (raw_clean.startswith("[") and raw_clean.endswith("]")):
        try:
            data = json.loads(raw_clean)
            if isinstance(data, dict):
                code = data.get("code")
                if code is not None and code not in (0, 200, "0", "200"):
                    msg = data.get("msg") or data.get("error") or data.get("message") or raw_clean
                    raise ValueError(f"代理接口返回错误: {msg}")
                for k in ("proxy", "proxies", "data", "list", "ips"):
                    val = data.get(k)
                    if isinstance(val, str):
                        cand = parse_proxy_line(val)
                        if cand:
                            return cand
                    elif isinstance(val, list) and val:
                        cand = parse_proxy_line(str(val[0]))
                        if cand:
                            return cand
        except json.JSONDecodeError:
            pass

    for line in raw_clean.splitlines():
        line = line.strip()
        if not line or line.startswith("<"):
            continue
        if re.match(r"^(https?|socks5h?)://[^\s]+$", line, re.IGNORECASE):
            return line
        m_4 = re.match(r"^((?:\d{1,3}\.){3}\d{1,3}|[a-zA-Z0-9.-]+):(\d{2,5}):([^:\s]+):([^:\s]+)$", line)
        if m_4:
            return f"http://{m_4.group(3)}:{m_4.group(4)}@{m_4.group(1)}:{m_4.group(2)}"
        m_auth = re.match(r"^([^:\s]+:[^@\s]+@(?:(?:\d{1,3}\.){3}\d{1,3}|[a-zA-Z0-9.-]+):\d{2,5})$", line)
        if m_auth:
            return f"http://{m_auth.group(1)}"
        m_2 = re.match(r"^((?:\d{1,3}\.){3}\d{1,3}|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}):(\d{2,5})$", line)
        if m_2:
            return f"http://{m_2.group(1)}:{m_2.group(2)}"
    return None

def mask_proxy_url(proxy_url: Optional[str]) -> str:
    """脱敏代理 URL 中的认证信息"""
    if not proxy_url:
        return "直连"
    return re.sub(r"://([^:@]+):[^@]+@", r"://:***@", proxy_url)

def parse_proxy_lines(raw_text: str) -> List[str]:
    """从代理 API 响应文本中解析并归一化全部候选代理地址列表"""
    if not raw_text:
        return []
    raw_clean = raw_text.strip()
    results: List[str] = []

    if (raw_clean.startswith("{") and raw_clean.endswith("}")) or (raw_clean.startswith("[") and raw_clean.endswith("]")):
        try:
            data = json.loads(raw_clean)
            if isinstance(data, dict):
                code = data.get("code")
                if code is not None and code not in (0, 200, "0", "200"):
                    msg = data.get("msg") or data.get("error") or data.get("message") or raw_clean
                    raise ValueError(f"代理接口返回错误: {msg}")
                for k in ("proxy", "proxies", "data", "list", "ips"):
                    val = data.get(k)
                    if isinstance(val, str):
                        cand = parse_proxy_line(val)
                        if cand and cand not in results:
                            results.append(cand)
                    elif isinstance(val, list):
                        for item in val:
                            cand = parse_proxy_line(str(item))
                            if cand and cand not in results:
                                results.append(cand)
        except json.JSONDecodeError:
            pass
        if results:
            return results

    for line in raw_clean.splitlines():
        line = line.strip()
        if not line or line.startswith("<"):
            continue
        cand = parse_proxy_line(line)
        if cand and cand not in results:
            results.append(cand)
    return results


_EXHAUSTED_CREATE_PROXIES: Dict[str, float] = {}

def mark_proxy_create_exhausted(proxy_url: str):
    """记录某个代理节点在 my.telegram.org/apps/create 触发了单 IP 创建频控限制 (ERROR)"""
    if proxy_url:
        _EXHAUSTED_CREATE_PROXIES[proxy_url] = time.time()

def is_proxy_create_exhausted(proxy_url: str, ttl_seconds: float = 900.0) -> bool:
    """检查代理节点是否在 15 分钟内曾被 Telegram 官网标记为创建频控"""
    if not proxy_url:
        return False
    ts = _EXHAUSTED_CREATE_PROXIES.get(proxy_url)
    if not ts:
        return False
    if time.time() - ts > ttl_seconds:
        _EXHAUSTED_CREATE_PROXIES.pop(proxy_url, None)
        return False
    return True

async def fetch_residential_proxy_for_region(
    region: str,
    proxy_api_url: Optional[str] = None,
    attempt_index: int = 0,
) -> str:
    """
    向家宽代理接口动态请求匹配目标账号地区的 10 分钟粘性住宅家宽代理。
    支持自动请求多节点并过滤已触发 ERROR 频控的节点，实现智能轮换。
    返回 http://ip:port 标准代理 URL。
    """
    clean_region = (region or "US").strip().upper()
    api_url = build_regional_proxy_api_url(clean_region, proxy_api_url=proxy_api_url)
    request_url = api_url
    if "num=1" in request_url:
        request_url = re.sub(r"([?&]num=)1(?=&|$)", r"\g<1>5", request_url)

    logger.info(f"正在从家宽代理接口拉取 {clean_region} 地区住宅代理 (URL: {request_url})...")

    import aiohttp
    timeout_cfg = aiohttp.ClientTimeout(total=15) if hasattr(aiohttp, "ClientTimeout") else None
    connector = aiohttp.TCPConnector(ssl=False) if hasattr(aiohttp, "TCPConnector") else None

    async with aiohttp.ClientSession(timeout=timeout_cfg, connector=connector) as sess:
        try:
            async with sess.get(request_url, headers={"User-Agent": "curl/7.88.1"}) as resp:
                text = await resp.text()
        except Exception as net_err:
            raise RuntimeError(f"请求家宽代理接口网络异常: {net_err}")

    cand_list = parse_proxy_lines(text)
    if not cand_list:
        parsed_single = parse_proxy_line(text)
        if parsed_single:
            cand_list = [parsed_single]

    if not cand_list:
        clean_hint = text.strip()[:160]
        raise ValueError(f"未能从家宽代理接口获取地区 {clean_region} 的有效代理节点 (接口响应: {clean_hint})")

    # 优先选取未在 15 分钟内因创建应用触发 ERROR 的新鲜代理
    fresh_candidates = [p for p in cand_list if not is_proxy_create_exhausted(p)]
    pool = fresh_candidates if fresh_candidates else cand_list
    selected = pool[attempt_index % len(pool)]

    logger.info(f"成功获取 {clean_region} 地区住宅家宽代理 (候选池 {len(pool)} 个可用): {mask_proxy_url(selected)}")
    return selected



SELLER_DEFAULT_2FA_PASSWORDS = {"z4422404", "qq1122", "8899", "123456", "666888", "888888", "112233"}


def is_account_taken_over(row: Dict) -> bool:
    """判断协议号是否已完成安全接管（独立高强 2FA 云密码 + 本机自主接码链接）"""
    if not row:
        return False
    if row.get("is_taken_over"):
        return True
    code_url = str(row.get("code_url") or "").strip()
    if not code_url.startswith("/api/telegram/botfather/otp/"):
        return False
    pwd = str(row.get("two_fa_password") or "").strip()
    if not pwd:
        return False
    if pwd.startswith("Mr-"):
        return True
    hint = str(row.get("two_fa_hint") or "").strip()
    if hint.startswith("MistRelay"):
        return True
    return pwd not in SELLER_DEFAULT_2FA_PASSWORDS and len(pwd) >= 8


def sanitize_account_record(
    row: Dict,
    tenant_aggregates: Optional[Dict[int, Dict]] = None,
    active_cluster_bots: Optional[set] = None,
) -> Dict:
    """脱敏协议号记录，隐藏底层 auth_key 密文，保留管理所需的元数据与解码参数，并聚合多租户频道与集群节点数据"""
    code_url = row.get("code_url") or ""
    masked_url = ""
    if code_url:
        parts = code_url.split("/")
        masked_url = "/".join(parts[:3]) + "/***" if len(parts) >= 3 else "***"

    bot_count = int(row.get("bot_count") or 0)
    status = row.get("status") or "active"
    if bot_count >= 20 and status == "active":
        status = "limit_reached"

    # 尝试从内存解码会话元数据（DC、用户ID、密钥指纹等）
    meta = {}
    sess_data = row.get("session_data")
    if sess_data:
        try:
            meta = inspect_session_metadata(sess_data)
        except Exception:
            meta = {}

    dc_id = row.get("dc_id") if row.get("dc_id") is not None else meta.get("dc_id")
    dc_name = meta.get("dc_name") or (f"DC{dc_id}" if dc_id else "")
    dc_ip = meta.get("dc_ip") or ""
    tg_user_id = row.get("tg_user_id") if row.get("tg_user_id") is not None else meta.get("user_id")

    db_api_id = row.get("api_id")
    api_id = int(db_api_id) if db_api_id and str(db_api_id).strip() not in ("0", "") else None

    api_hash = str(row.get("api_hash") or "").strip()
    has_api_hash = bool(api_hash)
    masked_api_hash = ""
    if api_hash:
        masked_api_hash = f"{api_hash[:4]}****{api_hash[-4:]}" if len(api_hash) >= 8 else "***"

    phone_val = str(row.get("phone") or "")
    region = row.get("region") or detect_region_from_phone(phone_val)

    acc_id = row.get("id")
    if tenant_aggregates is None and acc_id is not None:
        try:
            tenant_aggregates = db.get_protocol_account_tenant_aggregates()
        except Exception:
            tenant_aggregates = {}

    t_info = (tenant_aggregates or {}).get(int(acc_id)) if acc_id is not None else {}
    created_channels_count = int(t_info.get("channel_count", 0)) if t_info else 0
    tenant_usernames = list(t_info.get("tenant_usernames", [])) if t_info else []

    if active_cluster_bots is None:
        try:
            import WebStreamer.bot as bot_mod
            active_cluster_bots = {
                str(getattr(cli, "username", "")).lower().lstrip("@")
                for cli in getattr(bot_mod, "multi_clients", {}).values()
                if getattr(cli, "username", None)
            }
        except Exception:
            active_cluster_bots = set()

    raw_bot_names = row.get("bot_usernames")
    bot_usernames_list: List[str] = []
    if raw_bot_names:
        try:
            parsed = json.loads(raw_bot_names)
            if isinstance(parsed, list):
                bot_usernames_list = [str(b).lstrip("@") for b in parsed]
        except Exception:
            bot_usernames_list = [b.strip().lstrip("@") for b in str(raw_bot_names).split(",") if b.strip()]

    cluster_active_bots_count = sum(
        1 for b in bot_usernames_list if b.lower() in (active_cluster_bots or set())
    )

    return {
        "id": row.get("id"),
        "region": region,
        "phone": row.get("phone"),
        "session_type": row.get("session_type") or "pyrogram_string",
        "has_code_url": bool(code_url),
        "masked_code_url": masked_url,
        "bot_count": bot_count,
        "max_bots": 20,
        "remaining_quota": max(0, 20 - bot_count),
        "status": status,
        "dc_id": dc_id,
        "dc_name": dc_name,
        "dc_ip": dc_ip,
        "tg_user_id": tg_user_id,
        "username": row.get("username") or "",
        "first_name": row.get("first_name") or "",
        "api_id": api_id,
        "has_api_hash": has_api_hash,
        "masked_api_hash": masked_api_hash,
        "auth_key_fingerprint": meta.get("auth_key_fingerprint") or "",
        "last_keepalive_at": row.get("last_keepalive_at") or "",
        "keepalive_ping_ms": row.get("keepalive_ping_ms"),
        "last_error": row.get("last_error") or "",
        "last_used_at": row.get("last_used_at"),
        "remark": row.get("remark") or "",
        "created_at": row.get("created_at"),
        "has_two_fa": bool(row.get("has_two_fa") or row.get("two_fa_password")),
        "two_fa_hint": row.get("two_fa_hint") or "",
        "masked_two_fa": f"{str(row.get('two_fa_password'))[:2]}****{str(row.get('two_fa_password'))[-2:]}" if len(str(row.get("two_fa_password") or "")) >= 4 else ("***" if row.get("two_fa_password") else ""),
        "local_otp_token": row.get("local_otp_token") or "",
        "is_taken_over": is_account_taken_over(row),
        "is_local_otp": str(code_url).strip().startswith("/api/telegram/botfather/otp/"),
        "taken_over_at": row.get("taken_over_at") or "",
        "created_channels_count": created_channels_count,
        "max_channels": 10,
        "tenant_usernames": tenant_usernames,
        "bot_usernames": bot_usernames_list,
        "cluster_active_bots_count": cluster_active_bots_count,
    }


def remove_protocol_account(account_identifier: Union[int, str], phone_hint: Optional[str] = None) -> bool:
    """
    从 SQLite 协议号资产池、内存缓存及所有磁盘 JSON 缓存中彻底移除指定协议号。
    彻底杜绝移除协议号后又被旧 JSON 缓存重新复活的问题。
    支持传入账号 ID (int/str) 或手机号 (str)，并可附带 phone_hint 双重保障。
    """
    phone = phone_hint.strip() if phone_hint else None
    account_id = None
    if isinstance(account_identifier, int) or (isinstance(account_identifier, str) and account_identifier.isdigit()):
        account_id = int(account_identifier)
        acc = db.get_protocol_account_by_id(account_id)
        if acc and not phone:
            phone = acc.get("phone")
    else:
        ident_str = str(account_identifier).strip()
        if not phone:
            phone = ident_str
        acc = db.get_protocol_account_by_phone(ident_str)
        if acc and not account_id:
            account_id = acc.get("id")

    deleted = False
    if account_id:
        deleted = db.delete_protocol_account(account_id) or deleted

    # 无论是否通过 ID 删成功，只要有 phone，彻底删除数据库中所有匹配记录（带+和不带+）
    phones_to_remove = set()
    if phone:
        norm_phone = phone.strip()
        if re.fullmatch(r"\d{8,15}", norm_phone):
            norm_phone = "+" + norm_phone
        phones_to_remove.update({phone, norm_phone, phone.lstrip("+"), norm_phone.lstrip("+")})

        try:
            with db.db_conn() as conn:
                for p in phones_to_remove:
                    cur = conn.execute("DELETE FROM tg_protocol_accounts WHERE phone = ?", (p,))
                    if cur.rowcount > 0:
                        deleted = True
        except Exception as e:
            logger.debug(f"通过手机号删除协议号失败: {e}")

    for p in phones_to_remove:
        _PHONE_SESSION_CACHE.pop(p, None)
        _remove_cached_credentials(p)

    for cpath in _CACHE_FILES:
        if os.path.exists(cpath):
            try:
                with open(cpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    changed = False
                    for p in phones_to_remove:
                        if p in data:
                            del data[p]
                            changed = True
                    if changed:
                        with open(cpath, "w", encoding="utf-8") as f:
                            json.dump(data, f)
            except Exception as e:
                logger.debug(f"清理文件缓存异常 {cpath}: {e}")

    return deleted or bool(phones_to_remove)


def sync_cached_sessions_to_db() -> List[Dict]:
    """
    获取所有已纳管的协议号资产列表。
    当且仅当数据库表为空时（如首次系统启动、历史升级迁移），才从历史 JSON 文件和内存会话中同步迁移数据，
    避免反复将管理员已主动移除的协议号从磁盘遗留缓存中重新复原。
    同时实现磁盘凭证备份与 SQLite 数据库的双向自愈同步。
    """
    try:
        existing_rows = db.list_protocol_accounts()
        cached_creds = _load_cached_credentials()

        # 双向自愈：同步磁盘凭证备份与 SQLite 数据库
        if existing_rows:
            for row in existing_rows:
                r_phone = _normalize_phone_key(row.get("phone") or "")
                r_api_id = row.get("api_id")
                r_api_hash = row.get("api_hash")
                # 1. 若 SQLite 缺失 api_id/api_hash，但磁盘凭证备份中存在，则自动回填 SQLite
                if (not r_api_id or not r_api_hash) and r_phone in cached_creds:
                    c_info = cached_creds[r_phone]
                    try:
                        db.update_protocol_account(
                            row["id"],
                            api_id=int(c_info["api_id"]),
                            api_hash=str(c_info["api_hash"]).strip(),
                        )
                        row["api_id"] = int(c_info["api_id"])
                        row["api_hash"] = str(c_info["api_hash"]).strip()
                        logger.info(f"从磁盘凭证备份成功自愈协议号 {r_phone} API 凭证: api_id={c_info['api_id']}")
                    except Exception as e_heal:
                        logger.debug(f"自愈协议号 API 凭证异常: {e_heal}")
                # 2. 若 SQLite 存有有效凭证，确保同步备份至磁盘 JSON
                elif r_api_id and r_api_hash:
                    _save_cached_credentials(r_phone, r_api_id, r_api_hash)

            t_aggs = db.get_protocol_account_tenant_aggregates()
            try:
                import WebStreamer.bot as bot_mod
                a_bots = {
                    str(getattr(cli, "username", "")).lower().lstrip("@")
                    for cli in getattr(bot_mod, "multi_clients", {}).values()
                    if getattr(cli, "username", None)
                }
            except Exception:
                a_bots = set()
            return [sanitize_account_record(r, tenant_aggregates=t_aggs, active_cluster_bots=a_bots) for r in existing_rows]

        # 仅当数据库完全为空时执行一次初始化历史迁移
        found = dict(_PHONE_SESSION_CACHE)
        for cpath in _CACHE_FILES:
            if os.path.exists(cpath):
                try:
                    with open(cpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            for k, v in data.items():
                                if v:
                                    found[k] = v
                except Exception:
                    pass

        existing_phones = {r["phone"] for r in existing_rows}
        for phone_k, sess_v in found.items():
            norm_p = _normalize_phone_key(phone_k)
            if norm_p not in existing_phones:
                c_cred = cached_creds.get(norm_p)
                db.upsert_protocol_account(
                    phone=norm_p,
                    session_data=_normalize_session_str(sess_v),
                    session_type="pyrogram_string",
                    status="active",
                    api_id=c_cred.get("api_id") if c_cred else None,
                    api_hash=c_cred.get("api_hash") if c_cred else None,
                )
        return [sanitize_account_record(r) for r in db.list_protocol_accounts()]
    except Exception as e:
        logger.debug(f"获取或同步协议号资产列表异常: {e}")
        return [sanitize_account_record(r) for r in db.list_protocol_accounts()]


def list_cached_phone_sessions() -> List[Dict[str, Any]]:
    """列出已纳管的协议号会话（兼容旧版 cached_sessions 字段）"""
    accounts = sync_cached_sessions_to_db()
    return [{"phone": a["phone"], "cached": True, **a} for a in accounts]


async def wait_for_botfather_reply(
    client: Client,
    after_id: int,
    timeout: float = 12.0,
    poll_interval: float = 0.5,
):
    """轮询等待 @BotFather 的最新回复消息"""
    start_t = time.time()
    while time.time() - start_t < timeout:
        try:
            async for msg in client.get_chat_history("BotFather", limit=5):
                if msg.id > after_id and not (msg.from_user and msg.from_user.is_self):
                    return msg
        except Exception as e:
            logger.debug(f"轮询 BotFather 回复异常: {e}")
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"等待 @BotFather 响应超时 (>{timeout}s)")


async def fetch_existing_bot_tokens(client: Client, max_limit: int = 20) -> List[Dict[str, str]]:
    """向 @BotFather 发送 /token 命令，尝试解析已有机器人的 Token"""
    existing = []
    try:
        await client.send_message("BotFather", "/cancel")
        await asyncio.sleep(0.8)

        sent = await client.send_message("BotFather", "/token")
        reply = await wait_for_botfather_reply(client, sent.id, timeout=8.0)

        if not reply or not reply.reply_markup:
            logger.info("BotFather 未返回机器人列表按钮，可能该账号尚无已建机器人")
            return []

        kb_rows = getattr(reply.reply_markup, "keyboard", None)
        if kb_rows and isinstance(kb_rows, list):
            kb_buttons = []
            for row in kb_rows:
                for btn in row:
                    text = getattr(btn, "text", btn) if btn else ""
                    if isinstance(text, str) and text.strip().startswith("@"):
                        kb_buttons.append(text.strip())

            if kb_buttons:
                logger.info(f"检测到 ReplyKeyboard 存量机器人按钮 {len(kb_buttons)} 个")
                for idx_b, b_text in enumerate(kb_buttons[:max_limit]):
                    try:
                        if idx_b > 0:
                            sent_t = await client.send_message("BotFather", "/token")
                            await wait_for_botfather_reply(client, sent_t.id, timeout=6.0)
                        sent_u = await client.send_message("BotFather", b_text)
                        res_msg = await wait_for_botfather_reply(client, sent_u.id, timeout=8.0)
                        if res_msg and res_msg.text:
                            match = TOKEN_REGEX.search(res_msg.text)
                            if match:
                                token = match.group(1)
                                uname = b_text.lstrip("@")
                                existing.append({"username": uname, "token": token})
                                logger.info(f"成功探测并提取存量 Bot: @{uname}")
                        await asyncio.sleep(0.8)
                    except Exception as kb_err:
                        logger.debug(f"通过 ReplyKeyboard 提取 {b_text} 异常: {kb_err}")
                return existing

        inline_rows = getattr(reply.reply_markup, "inline_keyboard", None)
        if not inline_rows:
            logger.info("BotFather 未返回机器人列表按钮，可能该账号尚无已建机器人")
            return []

        buttons = []
        for row in inline_rows:
            for btn in row:
                if btn.text and btn.callback_data:
                    buttons.append(btn)

        logger.info(f"检测到存量机器人候选按钮 {len(buttons)} 个")
        for btn in buttons[:max_limit]:
            try:
                if hasattr(reply, "click"):
                    res_msg = await reply.click(btn.text)
                else:
                    await client.request_callback_answer(
                        chat_id="BotFather",
                        message_id=reply.id,
                        callback_data=btn.callback_data,
                    )
                    res_msg = await wait_for_botfather_reply(client, reply.id, timeout=6.0)

                if res_msg and res_msg.text:
                    match = TOKEN_REGEX.search(res_msg.text)
                    if match:
                        token = match.group(1)
                        uname = btn.text.lstrip("@")
                        existing.append({"username": uname, "token": token})
                        logger.info(f"成功探测并提取存量 Bot: @{uname}")
                await asyncio.sleep(1.0)
            except Exception as click_err:
                logger.debug(f"点击 Bot 按钮 {btn.text} 提取 Token 异常: {click_err}")
    except Exception as e:
        logger.warning(f"获取存量 Bot Token 过程异常: {e}")

    return existing


async def create_single_bot(
    client: Client,
    display_name: str,
    username_prefix: str = "mr_node",
    max_cooldown_wait: int = 60,
    cooldown_callback=None,
    cancel_check=None,
) -> Tuple[str, str]:
    """与 @BotFather 交互创建单个机器人并返回 (username, token)"""
    reply1 = None
    for newbot_attempt in range(5):
        try:
            await client.send_message("BotFather", "/cancel")
            await asyncio.sleep(0.8)
        except Exception:
            pass

        sent_newbot = await client.send_message("BotFather", "/newbot")
        reply1 = await wait_for_botfather_reply(client, sent_newbot.id, timeout=10.0)

        reply1_text = (reply1.text or "").lower()
        if "cannot create new bots" in reply1_text or "spambot" in reply1_text:
            raise ValueError("该 Telegram 协议号账号受限 (被 Telegram @SpamBot 限制)，@BotFather 拒绝创建新机器人。")
        if "sorry" in reply1_text and ("20 bots" in reply1_text or "limit" in reply1_text):
            raise ValueError("该 Telegram 账号已达到单号 20 个机器人的最大上限，无法再新建")
        if "flood" in reply1_text or "too many" in reply1_text or "please try again" in reply1_text:
            m_wait = re.search(r"(\d+)\s*second", reply1_text)
            wait_sec = int(m_wait.group(1)) if m_wait else 4
            if wait_sec <= max_cooldown_wait and newbot_attempt < 8:
                logger.info(f"@BotFather 提示冷却 {wait_sec}s，休眠 {wait_sec + 2}s 后自动重试创建...")
                if max_cooldown_wait <= 60 and cooldown_callback is None and cancel_check is None:
                    await asyncio.sleep(wait_sec + 1.5)
                else:
                    total_wait = wait_sec + 2
                    for rem in range(total_wait, 0, -1):
                        if cancel_check and cancel_check():
                            raise asyncio.CancelledError("自动铸造任务已被手动中止")
                        if cooldown_callback:
                            try:
                                cooldown_callback(rem, total_wait)
                            except Exception:
                                pass
                        await asyncio.sleep(1.0)
                continue
            raise ValueError(f"@BotFather 触发限流: {reply1.text}")
        break

    sent_name = await client.send_message("BotFather", display_name)
    reply2 = await wait_for_botfather_reply(client, sent_name.id, timeout=10.0)

    clean_prefix = re.sub(r"[^a-zA-Z0-9]+", "_", username_prefix).strip("_").lower()
    if not clean_prefix or len(clean_prefix) < 2 or not clean_prefix[0].isalpha():
        clean_prefix = "mistrelay"
    clean_prefix = clean_prefix[:14].rstrip("_")

    token_found = None
    username_used = None

    for attempt in range(5):
        random_suffix = secrets.token_hex(3)
        candidate_uname = f"{clean_prefix}_{random_suffix}_bot"

        sent_uname = await client.send_message("BotFather", candidate_uname)
        reply3 = await wait_for_botfather_reply(client, sent_uname.id, timeout=10.0)
        reply3_text = reply3.text or ""

        if "taken" in reply3_text.lower() or "invalid" in reply3_text.lower():
            logger.info(f"用户名 {candidate_uname} 不可用 ({reply3_text[:40]}), 进行第 {attempt + 1} 次重试...")
            await asyncio.sleep(0.8)
            continue

        match = TOKEN_REGEX.search(reply3_text)
        if match:
            token_found = match.group(1)
            username_used = candidate_uname
            logger.info(f"BotFather 成功签发机器人: @{username_used}")
            break
        else:
            logger.warning(f"BotFather 回复未包含有效 Token (回复: {reply3_text[:60]}...)，重试...")
            await asyncio.sleep(0.8)

    if not token_found or not username_used:
        raise RuntimeError("多次尝试未能成功获取 @BotFather 签发的有效 Token")

    return username_used, token_found


async def login_via_phone_and_code_url(
    phone_and_url_str: str,
    on_progress: Optional[Callable[[str, Optional[str], int], None]] = None,
    api_id: Optional[int] = None,
    api_hash: Optional[str] = None,
) -> str:
    """
    通过 '手机号|接码链接' 格式全自动完成接码与 2FA 登录并返回 Pyrogram Session String。
    支持 on_progress(msg, phone, cooldown) 实时汇报当前阶段与频率保护冷却倒计时。
    """
    import urllib.request
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import SessionPasswordNeededError

    parts = phone_and_url_str.split("|", 1)
    raw_phone = parts[0].strip()
    raw_url_part = parts[1].strip()

    phone_match = re.search(r"(\+?\d{8,15})", raw_phone)
    if not phone_match:
        raise ValueError(f"未能从输入中识别出有效的国际手机号: {raw_phone}")
    phone = phone_match.group(1)
    if not phone.startswith("+"):
        phone = "+" + phone

    url_match = re.search(r"https?://[^\s()\"\x27<>|]+", raw_url_part)
    if not url_match:
        raise ValueError(f"未能从输入中识别出有效的 HTTP 接码链接: {raw_url_part}")
    code_url = url_match.group(0).rstrip(")>]\x27\x22")

    def report_progress(msg: str, cooldown: int = 0):
        if on_progress:
            try:
                on_progress(msg, phone, cooldown)
            except Exception:
                pass

    # 1. 优先检查本地已登录缓存
    cached_sess = _get_cached_session(phone)
    if cached_sess:
        cached_sess = _normalize_session_str(cached_sess)
        if Client is not None:
            logger.info(f"发现手机号 {phone} 的已登录会话缓存，正在验证有效性...")
            report_progress(f"发现手机号 {phone} 已登录会话缓存，正在验证有效性...")
            test_cli = Client(
                name=f"verify_cache_{secrets.token_hex(4)}",
                api_id=Var.API_ID or 2040,
                api_hash=Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
                session_string=cached_sess,
                in_memory=True,
                no_updates=True,
            )
            try:
                await test_cli.start()
                me = await test_cli.get_me()
                if me:
                    logger.info(f"成功复用已缓存会话: {me.first_name} (@{me.username or '无用户名'}, ID: {me.id})")
                    report_progress(f"成功复用已缓存会话: {me.first_name}")
                    _save_cached_session(phone, cached_sess, code_url=code_url, status="active", api_id=api_id, api_hash=api_hash)
                    return cached_sess
            except Exception as e:
                logger.warning(f"缓存会话已失效 ({e})，将重新发起接码登录")
                report_progress("缓存会话已失效，正在重新发起接码登录...")
            finally:
                try:
                    if getattr(test_cli, "is_connected", False):
                        await test_cli.stop()
                except Exception:
                    pass
        else:
            return cached_sess

    logger.info(f"正在为手机号 {phone} 启动 Telethon 自动接码登录，接码地址: {code_url}")
    report_progress(f"正在为手机号 {phone} 建立 Telegram 连接并请求下发验证码...")

    effective_api_id = api_id or Var.API_ID or 2040
    effective_api_hash = api_hash or Var.API_HASH or "b18441a1ff607e10a989891a5462e627"
    t_client = TelegramClient(
        StringSession(),
        effective_api_id,
        effective_api_hash,
        device_model="Desktop",
        system_version="Windows 10",
        app_version="4.16.8 x64",
    )

    try:
        await asyncio.wait_for(t_client.connect(), timeout=25.0)
    except Exception as conn_err:
        report_progress(f"连接 Telegram MTProto 网关失败: {conn_err}")
        raise TimeoutError(f"连接 Telegram MTProto 网关超时或失败: {conn_err}")

    try:
        try:
            sent = await asyncio.wait_for(t_client.send_code_request(phone), timeout=30.0)
        except Exception as send_err:
            err_str = str(send_err)
            if "PHONE_NUMBER_BANNED" in err_str or "banned" in err_str.lower():
                raise ValueError(f"手机号 {phone} 已被 Telegram 官方封禁 (PHONE_NUMBER_BANNED)")
            if "PHONE_NUMBER_INVALID" in err_str:
                raise ValueError(f"无效的国际手机号: {phone}")
            if "FLOOD_WAIT" in err_str:
                raise ValueError(f"Telegram 官方触发下发验证码限流: {err_str}")
            raise RuntimeError(f"请求 Telegram 下发验证码失败: {send_err}")

        phone_code_hash = sent.phone_code_hash
        logger.info(f"Telegram 已向 {phone} 签发验证码 (hash={phone_code_hash[:8]}...)")
        report_progress(f"Telegram 已向 {phone} 签发验证码，正在监听接码平台返回...")

        html_content = ""
        verification_code = None
        two_fa_password = None
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

        async def _fetch_code_html() -> str:
            try:
                import aiohttp
                if hasattr(aiohttp, "ClientTimeout"):
                    timeout_cfg = aiohttp.ClientTimeout(total=12)
                    connector = aiohttp.TCPConnector(ssl=False) if hasattr(aiohttp, "TCPConnector") else None
                    async with aiohttp.ClientSession(timeout=timeout_cfg, connector=connector, headers={"User-Agent": ua}) as http_sess:
                        async with http_sess.get(code_url) as resp:
                            return await resp.text(errors="ignore")
            except Exception:
                pass

            def _sync_get() -> str:
                import ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(code_url, headers={"User-Agent": ua})
                with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
                    return resp.read().decode("utf-8", errors="ignore")

            return await asyncio.to_thread(_sync_get)

        await asyncio.sleep(2.5)
        # 后台支持长达 240 秒的轮询时间窗口，足够跨越多轮接码平台频率冷却保护
        poll_deadline = time.monotonic() + 240.0

        for attempt in range(60):
            if time.monotonic() >= poll_deadline:
                break
            try:
                html_content = await _fetch_code_html()
            except Exception as req_err:
                logger.warning(f"第 {attempt + 1} 次轮询接码链接异常: {req_err}")
                report_progress(f"第 {attempt + 1} 次轮询接码链接异常，3 秒后重试...")
                await asyncio.sleep(3.0)
                continue

            clean_html = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", html_content, flags=re.DOTALL | re.IGNORECASE)

            # 致命错误快速探测：发卡网/接码平台明确提示账号死亡、已失效或订单错误，立即终止避免无效轮询
            if any(w in clean_html for w in ("账号死亡", "账号已死", "账号失效", "账号被封", "已封禁", "账号已注销")):
                raise ValueError("接码平台提示：该账号已死亡或被 Telegram 官方封禁（请向号商反馈或更换号码）")
            if any(w in clean_html for w in ("订单不存在", "卡密错误", "记录不存在")):
                raise ValueError("接码平台提示：订单或卡密链接不存在")
            if "已退款" in clean_html:
                raise ValueError("接码平台提示：该号码订单已退款")

            if "请求过于频繁" in html_content or ("等待" in html_content and "秒" in html_content):
                m_wait = re.search(r"等待\s*(\d+)\s*秒", html_content) or re.search(r"(\d+)\s*秒", html_content)
                wait_sec = min(int(m_wait.group(1)) if m_wait else 15, 65)
                remaining_budget = poll_deadline - time.monotonic()
                if remaining_budget <= 2:
                    break
                actual_sleep = min(wait_sec + 2.0, remaining_budget)
                logger.info(f"接码链接触发频率保护，等待 {actual_sleep:.0f} 秒后重试...")
                for sec_left in range(int(actual_sleep), 0, -1):
                    report_progress(
                        f"接码平台触发频率保护，冷却倒计时: 剩余 {sec_left} 秒后自动重试...",
                        cooldown=sec_left,
                    )
                    await asyncio.sleep(1.0)
                report_progress("频率保护冷却结束，正在重新读取验证码...", cooldown=0)
                continue

            if "无三十分钟内的登录消息" in html_content:
                logger.info(f"第 {attempt + 1} 次轮询: 接码页面暂未收到验证码，继续等待...")
                report_progress(f"第 {attempt + 1} 次轮询: 接码页面暂未收到验证码，继续等待...")
                await asyncio.sleep(3.5)
                continue

            clean_html = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", html_content, flags=re.DOTALL | re.IGNORECASE)
            m_code = re.search(r"id=[\x22\x27]code[\x22\x27][^>]+value=[\x22\x27](\d{5,6})[\x22\x27]", clean_html)
            m_pass = re.search(r"id=[\x22\x27]pass2fa[\x22\x27][^>]+value=[\x22\x27]([^\x22\x27]+)[\x22\x27]", clean_html)
            if m_code:
                verification_code = m_code.group(1)
                if m_pass:
                    two_fa_password = m_pass.group(1).strip()
                break

            code_matches = re.findall(r"\b(\d{5,6})\b", clean_html)
            if code_matches:
                verification_code = code_matches[0]
                break

            await asyncio.sleep(3.0)

        if not verification_code:
            raise TimeoutError("等待接码超时：未能在接码页面提取到 5 位验证码")

        logger.info(f"成功获取到登录验证码: {verification_code}")
        report_progress(f"成功捕获验证码: {verification_code}，正在执行登录校验...", cooldown=0)

        if not two_fa_password:
            clean_html = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", html_content, flags=re.DOTALL | re.IGNORECASE)
            inputs = re.findall(r"value=[\x22\x27]([^\x22\x27]+)[\x22\x27]", clean_html)
            if len(inputs) >= 3:
                two_fa_password = inputs[2].strip()
            elif inputs:
                for val in inputs:
                    val = val.strip()
                    if val and val != verification_code and val != phone and val != phone.lstrip("+"):
                        two_fa_password = val
                        break

        try:
            await t_client.sign_in(phone=phone, code=verification_code, phone_code_hash=phone_code_hash)
            logger.info("验证码校验通过，无需 2FA 直接登录成功！")
            report_progress("验证码校验通过，登录成功！")
        except SessionPasswordNeededError:
            if not two_fa_password:
                raise ValueError("Telegram 要求两步验证(2FA)密码，但接码页面中未能自动识别出密码")
            logger.info(f"正在验证两步验证密码: {two_fa_password}")
            report_progress("正在校验两步验证(2FA)密码...")
            await t_client.sign_in(password=two_fa_password)
            logger.info("两步验证校验通过，登录成功！")
            report_progress("两步验证校验通过，登录成功！")

        me = await t_client.get_me()
        t_session_str = t_client.session.save()
        dc_id, auth_key = extract_dc_and_auth_key_from_telethon_string(t_session_str)
        pyro_session = pack_pyrogram_session(
            dc_id=dc_id,
            auth_key=auth_key,
            api_id=effective_api_id,
            user_id=me.id if me else 1,
        )
        _save_cached_session(
            phone,
            pyro_session,
            code_url=code_url,
            status="active",
            session_type="telethon_string",
            api_id=api_id,
            api_hash=api_hash,
            two_fa_password=two_fa_password,
            has_two_fa=1 if two_fa_password else 0,
        )
        logger.info(f"协议号登录并转换完成: {me.first_name} (@{me.username or '无用户名'}, ID: {me.id})")
        report_progress(f"协议号 {phone} 登录并转换完成 ({me.first_name})")
        return pyro_session
    finally:
        try:
            await t_client.disconnect()
        except Exception:
            pass


def parse_account_line(raw_str: str) -> Dict[str, Any]:
    """
    多格式协议号文本行解析器：
    支持提取 phone, code_url, api_id, api_hash, session_str, remark
    兼容格式：
    - 手机号|接码链接(|备注)
    - 手机号|api_id|api_hash|接码链接或Session(|备注)
    - 手机号|接码链接|api_id|api_hash
    - api_id:api_hash:session_string 或 api_id|api_hash|session_string
    - 纯 Session String 或纯手机号
    """
    s = str(raw_str or "").strip()
    res: Dict[str, Any] = {
        "phone": None,
        "code_url": None,
        "api_id": None,
        "api_hash": None,
        "session_str": None,
        "remark": None,
    }
    if not s:
        return res

    # 冒号分隔格式: api_id:api_hash:session 或 phone:api_id:api_hash:session
    if ":" in s and "|" not in s and not s.startswith("http"):
        parts = [p.strip() for p in s.split(":")]
        if len(parts) >= 3:
            if parts[0].isdigit() and re.fullmatch(r"[a-fA-F0-9]{32}", parts[1]):
                res["api_id"] = int(parts[0])
                res["api_hash"] = parts[1].lower()
                res["session_str"] = ":".join(parts[2:])
                return res
            elif re.fullmatch(r"\+?\d{8,15}", parts[0]) and parts[1].isdigit() and re.fullmatch(r"[a-fA-F0-9]{32}", parts[2]):
                res["phone"] = parts[0] if parts[0].startswith("+") else "+" + parts[0]
                res["api_id"] = int(parts[1])
                res["api_hash"] = parts[2].lower()
                if len(parts) > 3:
                    res["session_str"] = ":".join(parts[3:])
                return res

    # 管道符分隔格式
    if "|" in s:
        parts = [p.strip() for p in s.split("|") if p.strip()]
        remaining = []
        numeric_tokens = []

        for part in parts:
            if re.match(r"^https?://", part):
                url_m = re.search(r"https?://[^\s()\"\x27<>|]+", part)
                res["code_url"] = url_m.group(0).rstrip(")>]\x27\x22") if url_m else part
            elif re.fullmatch(r"[a-fA-F0-9]{32}", part):
                res["api_hash"] = part.lower()
            elif (part.startswith("1") and len(part) > 150) or (len(part) > 150 and not part.startswith("http")):
                res["session_str"] = part
            elif re.fullmatch(r"\+\d{7,15}", part):
                if not res["phone"]:
                    res["phone"] = part
                else:
                    numeric_tokens.append(part)
            elif re.fullmatch(r"\d{4,15}", part):
                numeric_tokens.append(part)
            else:
                remaining.append(part)

        for tok in numeric_tokens:
            clean_digits = tok.lstrip("+")
            if not res["phone"]:
                if (
                    len(numeric_tokens) == 1
                    and res["api_hash"]
                    and res["session_str"]
                    and not res["code_url"]
                    and not tok.startswith("+")
                    and len(clean_digits) <= 10
                ):
                    res["api_id"] = int(clean_digits)
                else:
                    res["phone"] = "+" + clean_digits
            elif not res["api_id"] and 4 <= len(clean_digits) <= 10:
                res["api_id"] = int(clean_digits)
            else:
                remaining.append(tok)

        if remaining:
            res["remark"] = " ".join(remaining)
        return res

    if re.fullmatch(r"\+?\d{8,15}", s):
        res["phone"] = s if s.startswith("+") else "+" + s
    else:
        res["session_str"] = s
    return res


async def _resolve_account_entry(
    source: str | bytes | bytearray,
    filename: Optional[str] = None,
    remark: Optional[str] = None,
    on_progress: Optional[Callable[[str, Optional[str], int], None]] = None,
    extra_api_id: Optional[int] = None,
    extra_api_hash: Optional[str] = None,
) -> Dict:
    """
    解析任意单条协议号来源（手机号|链接、带 api_id|api_hash 组合行、已缓存手机号、Session String、.session/.json 字节），
    写入或更新协议号资产池并返回数据库记录。
    """
    if isinstance(source, (bytes, bytearray)):
        if filename and filename.lower().endswith(".json"):
            try:
                jdata = json.loads(source.decode("utf-8", errors="ignore"))
            except Exception as je:
                raise ValueError(f"无法解析 JSON 档案文件 {filename}: {je}")

            phone = str(jdata.get("phone") or jdata.get("phone_number") or "").strip()
            if phone and not phone.startswith("+") and phone.isdigit():
                phone = "+" + phone
            if not phone and filename:
                m = re.search(r"(\+?\d{8,15})", filename)
                if m:
                    phone = m.group(1) if m.group(1).startswith("+") else "+" + m.group(1)

            app_id = jdata.get("app_id") or jdata.get("api_id")
            app_hash = jdata.get("app_hash") or jdata.get("api_hash")
            api_id_val = int(app_id) if app_id and str(app_id).isdigit() else extra_api_id
            api_hash_val = str(app_hash).strip().lower() if app_hash else extra_api_hash
            first_name = jdata.get("first_name") or ""
            username = jdata.get("username") or ""

            sess_raw = jdata.get("session_data") or jdata.get("session_string") or jdata.get("session") or ""
            if sess_raw:
                pyro_session = parse_session_to_pyrogram_string(sess_raw, default_api_id=api_id_val or Var.API_ID or 2040)
                rec = _save_cached_session(
                    phone=phone or f"+sess_{hashlib.sha1(pyro_session.encode(utf-8)).hexdigest()[:10]}",
                    session_str=pyro_session,
                    remark=remark or (filename or "JSON 档案导入"),
                    status="active",
                    session_type="json_file",
                    api_id=api_id_val,
                    api_hash=api_hash_val,
                )
                if rec and (first_name or username):
                    db.update_protocol_account(rec["id"], first_name=first_name, username=username)
                    rec = db.get_protocol_account_by_id(rec["id"]) or rec
                return rec or {"phone": phone, "session_data": pyro_session, "api_id": api_id_val, "api_hash": api_hash_val, "status": "active", "bot_count": 0}
            elif phone:
                existing = db.get_protocol_account_by_phone(phone)
                if existing:
                    updates = {}
                    if api_id_val:
                        updates["api_id"] = api_id_val
                    if api_hash_val:
                        updates["api_hash"] = api_hash_val
                    if first_name:
                        updates["first_name"] = first_name
                    if username:
                        updates["username"] = username
                    if updates:
                        db.update_protocol_account(existing["id"], **updates)
                    return db.get_protocol_account_by_id(existing["id"]) or existing
                else:
                    cached = _get_cached_session(phone)
                    if cached:
                        rec = _save_cached_session(
                            phone=phone,
                            session_str=cached,
                            remark=remark or (filename or "JSON 档案关联"),
                            status="active",
                            api_id=api_id_val,
                            api_hash=api_hash_val,
                        )
                        return rec or {"phone": phone, "session_data": cached, "api_id": api_id_val, "api_hash": api_hash_val, "status": "active", "bot_count": 0}
                    raise ValueError(f"JSON 文件 {filename} 包含 API 凭证但缺少对应 Session 数据，请同时上传同名 .session 文件")
            else:
                raise ValueError(f"JSON 文件 {filename} 中未发现有效的手机号或 Session 凭证")

        pyro_session = parse_session_to_pyrogram_string(source, default_api_id=extra_api_id or Var.API_ID or 2040)
        phone = None
        if filename:
            m = re.search(r"(\+?\d{8,15})", filename)
            if m:
                phone = m.group(1)
                if not phone.startswith("+"):
                    phone = "+" + phone
        if not phone:
            try:
                _, _, _, _, uid, _ = extract_from_pyrogram_string(pyro_session)
                if uid and uid > 1:
                    phone = f"+uid_{uid}"
            except Exception:
                pass
        if not phone:
            h = hashlib.sha1(pyro_session.encode("utf-8")).hexdigest()[:10]
            phone = f"+sess_{h}"

        rec = _save_cached_session(
            phone=phone,
            session_str=pyro_session,
            remark=remark or (filename or "上传 .session 文件"),
            status="active",
            session_type="session_file",
            api_id=extra_api_id,
            api_hash=extra_api_hash,
        )
        if on_progress:
            try:
                on_progress(f"文件 {filename or phone} 解析入库成功", phone, 0)
            except Exception:
                pass
        return rec or {"phone": phone, "session_data": pyro_session, "api_id": extra_api_id, "api_hash": extra_api_hash, "status": "active", "bot_count": 0}

    raw_str = str(source or "").strip()
    if not raw_str:
        raise ValueError("空的协议号输入内容")

    parsed = parse_account_line(raw_str)
    api_id = parsed["api_id"] or extra_api_id
    api_hash = parsed["api_hash"] or extra_api_hash
    line_remark = remark or parsed["remark"]

    # 1. [手机号|接码链接] 或 [手机号|api_id|api_hash|接码链接]
    if parsed["code_url"]:
        phone = parsed["phone"]
        code_url = parsed["code_url"]
        if not phone:
            phone_m = re.search(r"(\+?\d{8,15})", raw_str)
            phone = phone_m.group(1) if phone_m else "+unknown"
            if not phone.startswith("+"):
                phone = "+" + phone

        login_target = f"{phone}|{code_url}"
        if on_progress is not None:
            try:
                pyro_session = await login_via_phone_and_code_url(login_target, on_progress=on_progress, api_id=api_id, api_hash=api_hash)
            except TypeError:
                try:
                    pyro_session = await login_via_phone_and_code_url(raw_str, on_progress=on_progress)
                except TypeError:
                    pyro_session = await login_via_phone_and_code_url(raw_str)
        else:
            try:
                pyro_session = await login_via_phone_and_code_url(login_target, api_id=api_id, api_hash=api_hash)
            except TypeError:
                pyro_session = await login_via_phone_and_code_url(raw_str)

        rec = _save_cached_session(
            phone=phone,
            session_str=pyro_session,
            code_url=code_url,
            remark=line_remark,
            status="active",
            session_type="telethon_string",
            api_id=api_id,
            api_hash=api_hash,
        )
        return rec or {"phone": phone, "session_data": pyro_session, "code_url": code_url, "api_id": api_id, "api_hash": api_hash, "status": "active", "bot_count": 0}

    # 2. 纯手机号（从已缓存资产池读取）
    if parsed["phone"] and not parsed["session_str"]:
        phone_key = parsed["phone"]
        cached = _get_cached_session(phone_key)
        if not cached:
            raise ValueError(f"手机号 {phone_key} 尚无已缓存会话，请提供 [手机号|接码链接] 格式")
        rec = _save_cached_session(phone=phone_key, session_str=cached, remark=line_remark, api_id=api_id, api_hash=api_hash)
        if on_progress:
            try:
                on_progress(f"成功复用手机号 {phone_key} 已缓存会话", phone_key, 0)
            except Exception:
                pass
        return rec or {"phone": phone_key, "session_data": cached, "api_id": api_id, "api_hash": api_hash, "status": "active", "bot_count": 0}

    # 3. Session String (Pyrogram / Telethon)
    session_text = parsed["session_str"] or raw_str
    s_type = "telethon_string" if (session_text.startswith("1") and len(session_text) > 280) else "pyrogram_string"
    pyro_session = parse_session_to_pyrogram_string(session_text, default_api_id=api_id or Var.API_ID or 2040)
    phone = parsed["phone"]
    if not phone:
        try:
            _, _, _, _, uid, _ = extract_from_pyrogram_string(pyro_session)
            if uid and uid > 1:
                phone = f"+uid_{uid}"
        except Exception:
            pass
    if not phone:
        h = hashlib.sha1(pyro_session.encode("utf-8")).hexdigest()[:10]
        phone = f"+sess_{h}"

    rec = _save_cached_session(
        phone=phone,
        session_str=pyro_session,
        remark=line_remark,
        status="active",
        session_type=s_type,
        api_id=api_id,
        api_hash=api_hash,
    )
    if on_progress:
        try:
            on_progress(f"成功解析 Session 字符串并入库 ({phone})", phone, 0)
        except Exception:
            pass
    return rec or {"phone": phone, "session_data": pyro_session, "api_id": api_id, "api_hash": api_hash, "status": "active", "bot_count": 0}


async def batch_import_protocol_accounts(
    lines: Optional[List[str]] = None,
    files: Optional[List[Tuple[str, bytes]]] = None,
    remark: Optional[str] = None,
    on_progress: Optional[Callable[[str, Optional[str], int], None]] = None,
) -> Dict:
    """
    批量导入多个协议号到资产池（支持多行 [手机号|接码链接]、带 api_id|api_hash 组合行、多行 Session String、多个 .session / .json 文件）。
    采用受控并发（Semaphore=3）处理，避免多账号串行接码导致整体耗时叠加超时。
    """
    imported: List[Dict] = []
    errors: List[str] = []
    sem = asyncio.Semaphore(3)

    async def _import_line(idx: int, clean_line: str):
        async with sem:
            try:
                if on_progress:
                    try:
                        on_progress(f"开始解析第 {idx} 行协议号...", None, 0)
                    except Exception:
                        pass
                rec = await _resolve_account_entry(clean_line, remark=remark, on_progress=on_progress)
                return ("ok", sanitize_account_record(rec))
            except Exception as e:
                err_msg = f"第 {idx} 行 ({clean_line[:24]}...) 导入失败: {e}"
                logger.warning(err_msg)
                if on_progress:
                    try:
                        on_progress(err_msg, None, 0)
                    except Exception:
                        pass
                return ("err", err_msg)

    async def _import_file(
        fname: str,
        fbytes: bytes,
        extra_api_id: Optional[int] = None,
        extra_api_hash: Optional[str] = None,
    ):
        async with sem:
            try:
                if on_progress:
                    try:
                        on_progress(f"开始解析文件 {fname}...", None, 0)
                    except Exception:
                        pass
                rec = await _resolve_account_entry(
                    fbytes,
                    filename=fname,
                    remark=remark,
                    on_progress=on_progress,
                    extra_api_id=extra_api_id,
                    extra_api_hash=extra_api_hash,
                )
                return ("ok", sanitize_account_record(rec))
            except Exception as e:
                err_msg = f"文件 {fname} 导入失败: {e}"
                logger.warning(err_msg)
                if on_progress:
                    try:
                        on_progress(err_msg, None, 0)
                    except Exception:
                        pass
                return ("err", err_msg)

    tasks = []
    if lines:
        for idx, line in enumerate(lines, start=1):
            clean_line = str(line or "").strip()
            if not clean_line or clean_line.startswith("#"):
                continue
            tasks.append(_import_line(idx, clean_line))

    if files:
        json_files = []
        session_files = []
        other_files = []
        for fname, fbytes in files:
            low = fname.lower()
            if low.endswith(".json"):
                json_files.append((fname, fbytes))
            elif low.endswith(".session"):
                session_files.append((fname, fbytes))
            else:
                other_files.append((fname, fbytes))

        json_meta_by_stem = {}
        json_meta_by_phone = {}
        for jname, jbytes in json_files:
            try:
                jdata = json.loads(jbytes.decode("utf-8", errors="ignore"))
                stem = os.path.splitext(jname)[0].strip()
                phone = str(jdata.get("phone") or jdata.get("phone_number") or "").strip()
                if phone and not phone.startswith("+") and phone.isdigit():
                    phone = "+" + phone
                app_id = jdata.get("app_id") or jdata.get("api_id")
                app_hash = jdata.get("app_hash") or jdata.get("api_hash")
                api_id_val = int(app_id) if app_id and str(app_id).isdigit() else None
                api_hash_val = str(app_hash).strip().lower() if app_hash else None
                m_info = {
                    "api_id": api_id_val,
                    "api_hash": api_hash_val,
                    "phone": phone,
                    "filename": jname,
                }
                if stem:
                    json_meta_by_stem[stem] = m_info
                    json_meta_by_stem[stem.lstrip("+")] = m_info
                    json_meta_by_stem["+" + stem.lstrip("+")] = m_info
                if phone:
                    json_meta_by_phone[phone] = m_info
                    json_meta_by_phone[phone.lstrip("+")] = m_info
            except Exception as je:
                logger.debug(f"预解析 JSON 档案 {jname} 异常: {je}")

        paired_json_names = set()
        for fname, fbytes in (session_files + other_files):
            stem = os.path.splitext(fname)[0].strip()
            extra = json_meta_by_stem.get(stem) or json_meta_by_phone.get(stem)
            if extra:
                paired_json_names.add(extra.get("filename"))
            tasks.append(_import_file(
                fname,
                fbytes,
                extra_api_id=extra.get("api_id") if extra else None,
                extra_api_hash=extra.get("api_hash") if extra else None,
            ))

        for jname, jbytes in json_files:
            if jname not in paired_json_names:
                tasks.append(_import_file(jname, jbytes))

    if tasks:
        results = await asyncio.gather(*tasks)
        for status_tag, payload in results:
            if status_tag == "ok":
                imported.append(payload)
            else:
                errors.append(payload)

    pool = sync_cached_sessions_to_db()
    return {
        "imported_count": len(imported),
        "failed_count": len(errors),
        "imported": imported,
        "errors": errors,
        "pool": pool,
    }


# 后台异步导入任务存储池（彻底规避 Cloudflare 100~120s HTTP 524 代理超时）
_IMPORT_TASKS: Dict[str, Dict[str, Any]] = {}
# 强引用集合：防止 Python 垃圾回收机制 (GC) 销毁正在运行的 asyncio.Task
_RUNNING_IMPORT_TASKS: set = set()


def create_import_task(
    lines: Optional[List[str]] = None,
    files: Optional[List[Tuple[str, bytes]]] = None,
    remark: Optional[str] = None,
) -> str:
    """
    创建并启动后台异步协议号导入任务，立即返回 task_id。
    """
    now = time.time()
    for tid, info in list(_IMPORT_TASKS.items()):
        if now - info.get("created_at", now) > 3600:
            _IMPORT_TASKS.pop(tid, None)

    task_id = f"import_{secrets.token_hex(6)}"
    _IMPORT_TASKS[task_id] = {
        "task_id": task_id,
        "status": "running",
        "progress": 5,
        "progress_msg": "正在初始化协议号后台导入任务...",
        "current_phone": "",
        "cooldown_remaining": 0,
        "imported_count": 0,
        "failed_count": 0,
        "imported": [],
        "errors": [],
        "logs": [],
        "pool": [],
        "created_at": now,
        "updated_at": now,
    }

    t = asyncio.create_task(_run_import_task(task_id, lines, files, remark))
    _RUNNING_IMPORT_TASKS.add(t)
    t.add_done_callback(_RUNNING_IMPORT_TASKS.discard)
    return task_id


def get_import_task_status(task_id: str) -> Optional[Dict[str, Any]]:
    """获取指定协议号导入任务的状态与实时进度"""
    return _IMPORT_TASKS.get(task_id)


async def _run_import_task(
    task_id: str,
    lines: Optional[List[str]],
    files: Optional[List[Tuple[str, bytes]]],
    remark: Optional[str],
):
    task_info = _IMPORT_TASKS.get(task_id)
    if not task_info:
        return

    def on_progress(msg: str, phone: Optional[str] = None, cooldown: int = 0):
        if not task_info:
            return
        now_str = time.strftime("%H:%M:%S")
        task_info["updated_at"] = time.time()
        task_info["progress_msg"] = msg
        if phone:
            task_info["current_phone"] = phone
        task_info["cooldown_remaining"] = int(cooldown or 0)
        task_info["logs"].append({"time": now_str, "msg": msg})
        if len(task_info["logs"]) > 80:
            task_info["logs"] = task_info["logs"][-80:]

    try:
        on_progress("已启动后台接码入库流水线，正在连接 Telegram...")
        res = await batch_import_protocol_accounts(
            lines=lines,
            files=files,
            remark=remark,
            on_progress=on_progress,
        )
        task_info["status"] = "completed"
        task_info["progress"] = 100
        task_info["cooldown_remaining"] = 0
        task_info["imported_count"] = res.get("imported_count", 0)
        task_info["failed_count"] = res.get("failed_count", 0)
        task_info["imported"] = res.get("imported", [])
        task_info["errors"] = res.get("errors", [])
        task_info["pool"] = res.get("pool", [])
        task_info["updated_at"] = time.time()
        summary_msg = f"导入完成：成功 {res.get('imported_count', 0)} 个，失败 {res.get('failed_count', 0)} 个"
        task_info["progress_msg"] = summary_msg
        on_progress(summary_msg, task_info.get("current_phone"), 0)
    except BaseException as e:
        logger.error(f"[ImportTask {task_id}] 异常终止: {e}", exc_info=True)
        task_info["status"] = "failed"
        task_info["error"] = str(e)
        task_info["cooldown_remaining"] = 0
        task_info["progress_msg"] = f"导入任务异常终止: {e}"
        task_info["updated_at"] = time.time()
        on_progress(f"导入任务异常终止: {e}", task_info.get("current_phone"), 0)


async def check_protocol_account(account_id: int) -> Dict:
    """
    检测指定协议号资产的连接健康状态，并向 @BotFather 查询该账号当前已持有的机器人数量
    """
    acc = db.get_protocol_account_by_id(int(account_id))
    if not acc:
        raise KeyError(f"未找到 ID={account_id} 的协议号记录")

    phone = acc["phone"]
    pyro_session = _normalize_session_str(acc["session_data"])

    if Client is None:
        raise RuntimeError("Pyrogram Client 环境未就绪")

    user_client = Client(
        name=f"check_acc_{account_id}_{secrets.token_hex(3)}",
        api_id=Var.API_ID or 2040,
        api_hash=Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
        session_string=pyro_session,
        in_memory=True,
        no_updates=True,
    )

    try:
        try:
            await user_client.start()
        except Exception as conn_err:
            if acc.get("code_url"):
                logger.info(f"协议号 {phone} 会话失效 ({conn_err})，尝试通过接码链接重新登录...")
                pyro_session = await login_via_phone_and_code_url(f"{phone}|{acc['code_url']}")
                user_client = Client(
                    name=f"recheck_acc_{account_id}_{secrets.token_hex(3)}",
                    api_id=Var.API_ID or 2040,
                    api_hash=Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
                    session_string=pyro_session,
                    in_memory=True,
                    no_updates=True,
                )
                await user_client.start()
            else:
                db.update_protocol_account(account_id, status="invalid")
                raise ValueError(f"协议号 {phone} 会话已失效且无接码链接: {conn_err}")

        me = await user_client.get_me()
        real_phone = f"+{me.phone_number}" if getattr(me, "phone_number", None) else phone
        existing_bots = await fetch_existing_bot_tokens(user_client, max_limit=20)
        bot_count = len(existing_bots)
        new_status = "limit_reached" if bot_count >= 20 else "active"

        dc_id = getattr(getattr(user_client, "storage", None), "dc_id", None)
        if callable(dc_id):
            try:
                dc_id = await dc_id()
            except Exception:
                dc_id = None

        bot_uname_list = [b["username"] for b in existing_bots if b.get("username")]
        bot_uname_list = [b["username"] for b in existing_bots if b.get("username")] if check_bots else None
        update_kw = {
            "phone": real_phone if real_phone == phone else phone,
            "bot_count": bot_count,
        }
        if bot_uname_list is not None:
            update_kw["bot_usernames"] = json.dumps(bot_uname_list)
        db.update_protocol_account(
            account_id,
            **update_kw,
            bot_usernames=json.dumps(bot_uname_list),
            status=new_status,
            first_name=getattr(me, "first_name", "") or "",
            username=getattr(me, "username", "") or "",
            tg_user_id=getattr(me, "id", None),
            dc_id=dc_id if dc_id else None,
            last_keepalive_at=db._now_iso(),
            last_used_at=db._now_iso(),
        )
        updated = db.get_protocol_account_by_id(account_id)
        return {
            "account": sanitize_account_record(updated),
            "user_info": {
                "id": getattr(me, "id", None),
                "first_name": getattr(me, "first_name", ""),
                "username": getattr(me, "username", ""),
            },
            "bots_found": bot_count,
            "bots": [{"username": b["username"]} for b in existing_bots],
        }
    finally:
        try:
            if getattr(user_client, "is_connected", False):
                await user_client.stop()
        except Exception:
            pass


async def run_botfather_pipeline(
    session_source: str | bytes | bytearray,
    count: int = 3,
    name_prefix: str = "MistRelay Node",
    reuse_existing: bool = True,
) -> Dict:
    """
    全自动协议号 BotFather 对接入网流水线（兼容单号或多行输入）
    """
    from WebStreamer.bot.clients import hot_add_bot_client
    import WebStreamer.bot as bot_mod

    count = max(1, min(int(count), 100))

    sources: List[Any] = []
    if isinstance(session_source, (bytes, bytearray)):
        sources = [session_source]
    else:
        raw_lines = [ln.strip() for ln in str(session_source or "").splitlines() if ln.strip()]
        sources = raw_lines if raw_lines else [str(session_source or "").strip()]

    results = {
        "reused_count": 0,
        "created_count": 0,
        "total_active_workers": 0,
        "bots": [],
        "errors": [],
        "accounts_used": 0,
    }

    handled_tokens = set()

    for src in sources:
        if len(handled_tokens) >= count:
            break

        raw_str = str(src).strip() if not isinstance(src, (bytes, bytearray)) else ""
        phone_label = "协议号"
        acc_record = None
        if isinstance(src, (bytes, bytearray)):
            pyro_session = parse_session_to_pyrogram_string(src, default_api_id=Var.API_ID or 2040)
        elif "|" in raw_str and "http" in raw_str:
            p_m = re.search(r"(\+?\d{8,15})", raw_str.split("|", 1)[0])
            phone_label = p_m.group(1) if p_m else raw_str.split("|", 1)[0].strip()
            if not phone_label.startswith("+") and phone_label.isdigit():
                phone_label = "+" + phone_label
            pyro_session = await login_via_phone_and_code_url(raw_str)
            acc_record = db.get_protocol_account_by_phone(phone_label)
        elif re.fullmatch(r"\+?\d{8,15}", raw_str):
            phone_label = raw_str if raw_str.startswith("+") else f"+{raw_str}"
            cached = _get_cached_session(phone_label)
            if not cached:
                raise ValueError(f"手机号 {phone_label} 尚无已缓存会话，请提供 [手机号|接码链接] 格式")
            pyro_session = _normalize_session_str(cached)
            acc_record = db.get_protocol_account_by_phone(phone_label)
        else:
            pyro_session = parse_session_to_pyrogram_string(src, default_api_id=Var.API_ID or 2040)
            acc_record = _save_cached_session(
                phone=f"+sess_{hashlib.sha1(pyro_session.encode('utf-8')).hexdigest()[:8]}",
                session_str=pyro_session,
            )

        user_client = Client(
            name=f"botfather_flow_{secrets.token_hex(4)}",
            api_id=Var.API_ID or 2040,
            api_hash=Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
            session_string=pyro_session,
            in_memory=True,
            no_updates=True,
        )

        await user_client.start()
        results["accounts_used"] += 1
        try:
            user_info = await user_client.get_me()
            logger.info(f"协议号已登录: {user_info.first_name} (@{user_info.username or '无用户名'}, ID: {user_info.id})")

            acc_bot_count = 0
            if reuse_existing:
                existing_bots = await fetch_existing_bot_tokens(user_client, max_limit=20)
                acc_bot_count = len(existing_bots)
                for item in existing_bots:
                    tok = item["token"]
                    if tok in handled_tokens:
                        continue
                    try:
                        mount_res = await hot_add_bot_client(tok, persist=True)
                        results["bots"].append(mount_res)
                        handled_tokens.add(tok)
                        results["reused_count"] += 1
                        if len(handled_tokens) >= count:
                            break
                    except Exception as add_err:
                        results["errors"].append(f"挂载存量 Bot (@{item.get('username')}) 失败: {add_err}")

            if acc_record and acc_record.get("id"):
                db.update_protocol_account(
                    acc_record["id"],
                    bot_count=acc_bot_count,
                    status="limit_reached" if acc_bot_count >= 20 else "active",
                    last_used_at=db._now_iso(),
                )

            needed = count - len(handled_tokens)
            if needed > 0 and acc_bot_count < 20:
                can_mint = min(needed, 20 - acc_bot_count)
                existing_total = len(bot_mod.multi_clients)
                for i in range(1, can_mint + 1):
                    display_name = f"{name_prefix} #{existing_total + i}"
                    try:
                        uname, tok = await create_single_bot(
                            user_client,
                            display_name=display_name,
                            username_prefix=name_prefix.replace(" ", "_").lower(),
                        )
                        mount_res = await hot_add_bot_client(tok, persist=True)
                        results["bots"].append(mount_res)
                        handled_tokens.add(tok)
                        results["created_count"] += 1
                        acc_bot_count += 1
                        if acc_record and acc_record.get("id"):
                            db.update_protocol_account(
                                acc_record["id"],
                                bot_count=acc_bot_count,
                                status="limit_reached" if acc_bot_count >= 20 else "active",
                                last_used_at=db._now_iso(),
                            )
                        if len(handled_tokens) >= count:
                            break
                    except Exception as create_err:
                        err_msg = f"创建第 {i} 个机器人失败: {create_err}"
                        logger.error(err_msg)
                        results["errors"].append(err_msg)
                        low_err = str(create_err).lower()
                        if acc_record and acc_record.get("id"):
                            if "上限" in low_err or "20" in low_err or "limit" in low_err:
                                db.update_protocol_account(acc_record["id"], bot_count=20, status="limit_reached")
                            elif "受限" in low_err or "spambot" in low_err:
                                db.update_protocol_account(acc_record["id"], status="restricted")
                            elif "限流" in low_err or "flood" in low_err:
                                db.update_protocol_account(acc_record["id"], status="cooling_down")
                        if any(k in low_err for k in ["上限", "limit", "限流", "受限", "spambot"]):
                            break

                    await asyncio.sleep(3.5)
        finally:
            try:
                if hasattr(user_client, "is_connected") and user_client.is_connected:
                    await user_client.stop()
            except Exception:
                pass

    results["total_active_workers"] = max(0, len(bot_mod.multi_clients) - 1)
    return results


class BackgroundMintManager:
    """
    后台异步批量铸造机器人任务管理器
    支持：
    - 多号跨账号自动接力扩容（Relay Mode，突破单号 20 上限，达上限/限流自动切下一账号）
    - 单号精准独立铸造（Single Mode，指定单号独立操作）
    """
    def __init__(self):
        self.task_id: Optional[str] = None
        self.mode: str = "relay"  # "relay" | "single"
        self.status: str = "idle"  # idle, running, cooling_down, completed, stopped, failed
        self.target_count: int = 0
        self.created_count: int = 0
        self.reused_count: int = 0
        self.total_workers: int = 0
        self.cooldown_remaining: int = 0
        self.cooldown_total: int = 0
        self.current_step: str = ""
        self.current_account_phone: str = ""
        self.account_index: int = 0
        self.total_accounts: int = 0
        self.account_history: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, str]] = []
        self.bots: List[Dict] = []
        self.error: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._cancel_requested: bool = False

    def add_log(self, level: str, msg: str):
        now_str = time.strftime("%H:%M:%S")
        self.logs.append({"time": now_str, "level": level, "msg": msg})
        if len(self.logs) > 150:
            self.logs = self.logs[-150:]
        logger.info(f"[MintTask][{level.upper()}] {msg}")

    def get_status(self) -> Dict:
        import WebStreamer.bot as bot_mod
        self.total_workers = max(0, len(bot_mod.multi_clients) - 1)
        done_cnt = self.reused_count + self.created_count
        pct = round(min(100.0, done_cnt / max(1, self.target_count) * 100.0), 1) if self.target_count > 0 else 0.0
        accounts = sync_cached_sessions_to_db()
        return {
            "task_id": self.task_id,
            "mode": self.mode,
            "status": self.status,
            "target_count": self.target_count,
            "created_count": self.created_count,
            "reused_count": self.reused_count,
            "total_active_workers": self.total_workers,
            "cooldown_remaining": self.cooldown_remaining,
            "cooldown_total": self.cooldown_total,
            "current_step": self.current_step,
            "current_account_phone": self.current_account_phone,
            "account_index": self.account_index,
            "total_accounts": self.total_accounts,
            "account_history": self.account_history,
            "percent": pct,
            "logs": self.logs[-60:],
            "bots": self.bots,
            "error": self.error,
            "cached_sessions": [{"phone": a["phone"], "cached": True, **a} for a in accounts],
            "accounts": accounts,
        }

    def start_task(
        self,
        session_source: Optional[str | bytes | bytearray] = None,
        count: int = 20,
        name_prefix: str = "MistRelay Node",
        reuse_existing: bool = True,
        mode: str = "relay",
        account_ids: Optional[List[int]] = None,
        single_account_id: Optional[int] = None,
    ) -> Dict:
        if self.status in ("running", "cooling_down") and self._task and not self._task.done():
            raise ValueError("后台已有正在执行的自动铸造任务，请等待或先点击停止")

        sync_cached_sessions_to_db()
        norm_mode = "single" if mode == "single" else "relay"

        # 构建待执行的账号队列
        queue_items: List[Dict[str, Any]] = []

        if norm_mode == "single":
            if single_account_id is not None:
                acc = db.get_protocol_account_by_id(int(single_account_id))
                if not acc:
                    raise ValueError(f"未找到指定的协议号 (ID={single_account_id})")
                queue_items.append({"type": "db_account", "account": acc, "label": acc["phone"]})
            elif session_source is not None:
                if isinstance(session_source, (bytes, bytearray)):
                    queue_items.append({"type": "raw", "source": session_source, "label": "上传.session文件"})
                else:
                    lines = [ln.strip() for ln in str(session_source).splitlines() if ln.strip()]
                    if not lines:
                        raise ValueError("请提供有效的协议号或选择资产池账号")
                    queue_items.append({"type": "raw", "source": lines[0], "label": lines[0].split("|")[0][:20]})
            else:
                raise ValueError("单号精准模式请指定一个协议号账号")
            max_allowed = 20
        else:
            # 多号接力模式 (Relay Mode)
            if account_ids:
                for aid in account_ids:
                    acc = db.get_protocol_account_by_id(int(aid))
                    if acc:
                        queue_items.append({"type": "db_account", "account": acc, "label": acc["phone"]})
            if session_source is not None:
                if isinstance(session_source, (bytes, bytearray)):
                    queue_items.append({"type": "raw", "source": session_source, "label": "上传.session文件"})
                else:
                    lines = [ln.strip() for ln in str(session_source).splitlines() if ln.strip()]
                    for ln in lines:
                        lbl = ln.split("|")[0][:20]
                        # 避免与已选 db_account 重复
                        if not any(item["label"] == lbl for item in queue_items):
                            queue_items.append({"type": "raw", "source": ln, "label": lbl})
            if not queue_items:
                # 默认使用资产池中所有未失效账号
                all_accs = db.list_protocol_accounts()
                usable = [a for a in all_accs if a.get("status") not in ("invalid", "restricted")]
                if not usable:
                    usable = all_accs
                for acc in usable:
                    queue_items.append({"type": "db_account", "account": acc, "label": acc["phone"]})

            if not queue_items:
                raise ValueError("协议号资产池为空且未提供新协议号，请先导入或输入协议号")
            max_allowed = max(20, min(200, len(queue_items) * 20))

        self.task_id = f"mint_{int(time.time())}_{secrets.token_hex(3)}"
        self.mode = norm_mode
        self.status = "running"
        self.target_count = max(1, min(int(count), max_allowed))
        self.created_count = 0
        self.reused_count = 0
        self.cooldown_remaining = 0
        self.cooldown_total = 0
        self.current_account_phone = queue_items[0]["label"]
        self.account_index = 1
        self.total_accounts = len(queue_items)
        self.account_history = []
        self.current_step = f"正在启动{'多号接力' if norm_mode == 'relay' else '单号精准'}铸造流水线 (共 {len(queue_items)} 个账号候选)..."
        self.logs.clear()
        self.bots.clear()
        self.error = None
        self._cancel_requested = False

        mode_label = f"多号接力模式 (候选账号 {len(queue_items)} 个)" if norm_mode == "relay" else f"单号精准模式 ({queue_items[0]['label']})"
        self.add_log("info", f"启动自动化铸造流水线 [{mode_label}]，目标总节点数: {self.target_count}")
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(
            self._worker(queue_items, self.target_count, name_prefix, reuse_existing)
        )
        return self.get_status()

    def stop_task(self) -> Dict:
        self._cancel_requested = True
        if self._task and not self._task.done():
            self._task.cancel()
        self.status = "stopped"
        self.cooldown_remaining = 0
        self.current_step = "已手动停止任务"
        self.add_log("warn", "管理员手动中止了铸造流水线")
        return self.get_status()

    async def _prepare_account_session(self, item: Dict[str, Any]) -> Tuple[str, Optional[int], str]:
        """返回 (pyro_session, db_account_id, phone_label)"""
        if item["type"] == "db_account":
            acc = item["account"]
            phone = acc["phone"]
            sess = _normalize_session_str(acc["session_data"])
            return sess, acc["id"], phone

        raw_source = item["source"]
        if isinstance(raw_source, (bytes, bytearray)):
            rec = await _resolve_account_entry(raw_source)
            return rec["session_data"], rec.get("id"), rec.get("phone", "上传.session")

        raw_str = str(raw_source).strip()
        if "|" in raw_str and "http" in raw_str:
            self.current_step = f"正在通过接码链接为 {item['label']} 自动获取验证码..."
            self.add_log("info", f"检测到 [{item['label']}] 接码链接，正在执行自动接码登录...")
            rec = await _resolve_account_entry(raw_str)
            return rec["session_data"], rec.get("id"), rec.get("phone", item["label"])
        elif re.fullmatch(r"\+?\d{8,15}", raw_str):
            phone_key = raw_str if raw_str.startswith("+") else f"+{raw_str}"
            cached = _get_cached_session(phone_key)
            if not cached:
                raise ValueError(f"手机号 {phone_key} 尚无缓存会话，请附带接码链接")
            rec = _save_cached_session(phone_key, cached)
            return _normalize_session_str(cached), (rec["id"] if rec else None), phone_key
        else:
            rec = await _resolve_account_entry(raw_str)
            return rec["session_data"], rec.get("id"), rec.get("phone", item["label"])

    async def _worker(
        self,
        queue_items: List[Dict[str, Any]],
        count: int,
        name_prefix: str,
        reuse_existing: bool,
    ):
        from WebStreamer.bot.clients import hot_add_bot_client
        import WebStreamer.bot as bot_mod

        handled_tokens = set()

        try:
            for idx_acc, item in enumerate(queue_items, start=1):
                if self._cancel_requested:
                    raise asyncio.CancelledError("任务已被停止")

                if len(handled_tokens) >= count:
                    break

                self.account_index = idx_acc
                self.current_account_phone = item["label"]
                acc_reused = 0
                acc_created = 0
                acc_id = None
                user_client = None

                try:
                    pyro_session, acc_id, phone_label = await self._prepare_account_session(item)
                    self.current_account_phone = phone_label
                    self.current_step = f"[账号 {idx_acc}/{len(queue_items)}: {phone_label}] 正在建立加密连接..."
                    self.add_log("info", f"🚀 开始调度第 {idx_acc}/{len(queue_items)} 个协议号: {phone_label}")

                    user_client = Client(
                        name=f"bf_bg_{idx_acc}_{secrets.token_hex(3)}",
                        api_id=Var.API_ID or 2040,
                        api_hash=Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
                        session_string=pyro_session,
                        in_memory=True,
                        no_updates=True,
                    )

                    await user_client.start()
                    me = await user_client.get_me()
                    self.add_log("success", f"[{phone_label}] 协议号连接成功: {getattr(me, 'first_name', 'User')} (ID: {getattr(me, 'id', '')})")

                    acc_bot_total = 0
                    if reuse_existing:
                        self.current_step = f"[{phone_label}] 正在向 @BotFather 探测存量机器人..."
                        existing_bots = await fetch_existing_bot_tokens(user_client, max_limit=20)
                        acc_bot_total = len(existing_bots)
                        self.add_log("info", f"[{phone_label}] 探测到 {acc_bot_total} 个存量机器人")

                        if acc_id:
                            db.update_protocol_account(
                                acc_id,
                                bot_count=acc_bot_total,
                                status="limit_reached" if acc_bot_total >= 20 else "active",
                                last_used_at=db._now_iso(),
                            )

                        for b_item in existing_bots:
                            if self._cancel_requested:
                                raise asyncio.CancelledError("任务已被停止")
                            tok = b_item["token"]
                            if tok in handled_tokens:
                                continue
                            try:
                                mount_res = await hot_add_bot_client(tok, persist=True)
                                self.bots.append(mount_res)
                                handled_tokens.add(tok)
                                self.reused_count += 1
                                acc_reused += 1
                                self.add_log(
                                    "success",
                                    f"[{phone_label}] 复用并挂载节点 #{mount_res.get('index')}: @{b_item.get('username')} ({mount_res.get('mode')})"
                                )
                                if len(handled_tokens) >= count:
                                    break
                            except Exception as add_err:
                                self.add_log("warn", f"[{phone_label}] 挂载存量 Bot @{b_item.get('username')} 异常: {add_err}")

                    if len(handled_tokens) >= count:
                        self.account_history.append({
                            "phone": phone_label,
                            "reused": acc_reused,
                            "created": acc_created,
                            "status": "completed",
                        })
                        break

                    if acc_bot_total >= 20:
                        if acc_id:
                            db.update_protocol_account(acc_id, bot_count=20, status="limit_reached")
                        self.account_history.append({
                            "phone": phone_label,
                            "reused": acc_reused,
                            "created": 0,
                            "status": "limit_reached",
                        })
                        if idx_acc < len(queue_items):
                            self.add_log("warn", f"⚡ [{phone_label}] 存量已满 20 个机器人上限，自动接力切换至下一个账号！")
                        else:
                            self.add_log("warn", f"[{phone_label}] 已满 20 个机器人上限，无更多候选账号")
                        continue

                    needed = count - len(handled_tokens)
                    can_create_on_this_acc = min(needed, 20 - acc_bot_total)
                    self.add_log("info", f"[{phone_label}] 准备在本账号上新铸造最多 {can_create_on_this_acc} 个机器人 (总剩余差额: {needed})...")

                    for i in range(1, can_create_on_this_acc + 1):
                        if self._cancel_requested:
                            raise asyncio.CancelledError("任务已被停止")

                        existing_total = len(bot_mod.multi_clients)
                        display_name = f"{name_prefix} #{existing_total + 1}"
                        self.status = "running"
                        self.cooldown_remaining = 0
                        self.current_step = f"[{phone_label} ({idx_acc}/{len(queue_items)})] 正在铸造第 {i}/{can_create_on_this_acc} 个新机器人 ({display_name})..."

                        def _on_cd(rem: int, total: int):
                            self.status = "cooling_down"
                            self.cooldown_remaining = rem
                            self.cooldown_total = total
                            self.current_step = f"[{phone_label}] @BotFather 冷却保护中，剩余 {rem}s 后自动继续..."
                            if rem == total or rem % 30 == 0 or rem == 5:
                                self.add_log("warn", f"[{phone_label}] BotFather 冷却等待: 剩余 {rem}s / {total}s")

                        try:
                            # 若有后续账号可接力，单号最长冷却容忍设为 30s，超过则直接切号免等待！
                            max_cd = 30 if idx_acc < len(queue_items) else 600
                            uname, tok = await create_single_bot(
                                user_client,
                                display_name=display_name,
                                username_prefix=name_prefix.replace(" ", "_").lower(),
                                max_cooldown_wait=max_cd,
                                cooldown_callback=_on_cd,
                                cancel_check=lambda: self._cancel_requested,
                            )
                            self.status = "running"
                            self.cooldown_remaining = 0
                            self.current_step = f"[{phone_label}] 正在热挂载新机器人 @{uname}..."
                            mount_res = await hot_add_bot_client(tok, persist=True)
                            self.bots.append(mount_res)
                            handled_tokens.add(tok)
                            self.created_count += 1
                            acc_created += 1
                            acc_bot_total += 1

                            if acc_id:
                                db.update_protocol_account(
                                    acc_id,
                                    bot_count=acc_bot_total,
                                    status="limit_reached" if acc_bot_total >= 20 else "active",
                                    last_used_at=db._now_iso(),
                                )

                            self.add_log(
                                "success",
                                f"[{phone_label}] 成功铸造并激活节点 #{mount_res.get('index')}: @{uname} (模式: {mount_res.get('mode')})"
                            )
                            if len(handled_tokens) >= count:
                                break
                        except asyncio.CancelledError:
                            raise
                        except Exception as create_err:
                            err_str = str(create_err)
                            low_err = err_str.lower()
                            self.add_log("error", f"[{phone_label}] 创建机器人异常: {err_str}")

                            if "上限" in low_err or "20 bots" in low_err or "20 个" in low_err or "limit" in low_err:
                                if acc_id:
                                    db.update_protocol_account(acc_id, bot_count=20, status="limit_reached")
                                if idx_acc < len(queue_items):
                                    self.add_log("warn", f"⚡ [跨号接力] 账号 {phone_label} 已达到单号 20 个机器人上限，立即无缝切换至下一个协议号接力铸造！")
                                else:
                                    self.add_log("warn", f"账号 {phone_label} 已达到单号 20 个机器人上限")
                                break

                            if "受限" in low_err or "spambot" in low_err or "cannot create new bots" in low_err:
                                if acc_id:
                                    db.update_protocol_account(acc_id, status="restricted")
                                if idx_acc < len(queue_items):
                                    self.add_log("warn", f"⚡ [跨号接力] 账号 {phone_label} 被 @SpamBot 限制建机，自动切换下一个协议号接力！")
                                break

                            if "限流" in low_err or "flood" in low_err or "too many" in low_err:
                                if acc_id:
                                    db.update_protocol_account(acc_id, status="cooling_down")
                                if idx_acc < len(queue_items):
                                    self.add_log("warn", f"⚡ [跨号接力] 账号 {phone_label} 触发频率冷却，自动切换下一个协议号免等待接力！")
                                break

                        await asyncio.sleep(3.2)

                    self.account_history.append({
                        "phone": phone_label,
                        "reused": acc_reused,
                        "created": acc_created,
                        "status": "limit_reached" if acc_bot_total >= 20 else "ok",
                    })

                except asyncio.CancelledError:
                    raise
                except Exception as acc_err:
                    self.add_log("error", f"[{item['label']}] 账号执行异常: {acc_err}")
                    self.account_history.append({
                        "phone": item["label"],
                        "reused": acc_reused,
                        "created": acc_created,
                        "status": "error",
                        "error": str(acc_err),
                    })
                    if idx_acc < len(queue_items):
                        self.add_log("warn", f"⚡ [跨号接力] 账号 {item['label']} 异常跳过，自动切换至下一个候选账号...")
                        continue
                    elif self.reused_count + self.created_count == 0:
                        raise
                finally:
                    try:
                        if user_client and getattr(user_client, "is_connected", False):
                            await user_client.stop()
                    except Exception:
                        pass

            self.status = "completed"
            self.cooldown_remaining = 0
            self.total_workers = max(0, len(bot_mod.multi_clients) - 1)
            self.current_step = (
                f"流水线完成！共调度 {len(self.account_history)} 个协议号，"
                f"复用 {self.reused_count} 个，新造 {self.created_count} 个，集群当前活跃从机 {self.total_workers} 个。"
            )
            self.add_log("success", self.current_step)

        except asyncio.CancelledError:
            self.status = "stopped"
            self.cooldown_remaining = 0
            self.current_step = "任务已手动停止"
        except Exception as e:
            self.status = "failed"
            self.cooldown_remaining = 0
            self.error = str(e)
            self.current_step = f"任务执行失败: {e}"
            self.add_log("error", f"流水线失败: {e}")


mint_manager = BackgroundMintManager()



async def get_protocol_account_detail(account_id: int, refresh_online: bool = False) -> Dict[str, Any]:
    """获取单个协议号的详细参数、双端 Session 凭证及名下 Bot 资产"""
    acc = db.get_protocol_account_by_id(int(account_id))
    if not acc:
        raise KeyError(f"未找到 ID={account_id} 的协议号记录")

    sess_data = acc.get("session_data", "")
    try:
        meta = inspect_session_metadata(sess_data, default_api_id=Var.API_ID or 2040)
    except Exception as e:
        logger.warning(f"解析协议号 {acc['phone']} 会话元数据失败: {e}")
        meta = {
            "dc_id": acc.get("dc_id") or 1,
            "dc_name": f"DC{acc.get('dc_id') or 1}",
            "dc_region": "未知",
            "dc_ip": "",
            "dc_port": 443,
            "user_id": acc.get("tg_user_id") or 0,
            "api_id": Var.API_ID or 2040,
            "test_mode": False,
            "is_bot": False,
            "auth_key_len": 256,
            "auth_key_fingerprint": "",
            "telethon_session_string": "",
            "pyrogram_session_string": sess_data,
        }

    online_user = None
    online_bots = None
    if refresh_online:
        check_res = await check_protocol_account(account_id)
        acc = db.get_protocol_account_by_id(int(account_id)) or acc
        online_user = check_res.get("user_info")
        online_bots = check_res.get("bots")

    sanitized = sanitize_account_record(acc)
    tenant_channels = []
    try:
        with db.db_conn() as conn:
            conn.row_factory = sqlite3.Row
            t_rows = conn.execute(
                """
                SELECT id AS user_id, username, bin_channel_id, bin_channel_username, dc_id, role, created_at
                FROM users
                WHERE creator_account_id = ? AND bin_channel_id IS NOT NULL
                ORDER BY id ASC
                """,
                (int(account_id),),
            ).fetchall()
            tenant_channels = [dict(r) for r in t_rows]
    except Exception as e:
        logger.warning(f"获取母号 #{account_id} 托管租户频道明细失败: {e}")

    return {
        "account": sanitized,
        "tenant_channels": tenant_channels,
        "metadata": {
            "dc_id": acc.get("dc_id") or meta.get("dc_id"),
            "dc_name": meta.get("dc_name"),
            "dc_region": meta.get("dc_region"),
            "dc_ip": meta.get("dc_ip"),
            "dc_port": meta.get("dc_port"),
            "tg_user_id": acc.get("tg_user_id") or meta.get("user_id"),
            "username": acc.get("username") or "",
            "first_name": acc.get("first_name") or "",
            "api_id": int(acc["api_id"]) if acc.get("api_id") and str(acc.get("api_id")).strip() not in ("0", "") else None,
            "api_hash": str(acc.get("api_hash") or "").strip(),
            "has_api_hash": bool(str(acc.get("api_hash") or "").strip()),
            "session_embedded_api_id": meta.get("api_id"),
            "test_mode": meta.get("test_mode"),
            "is_bot": meta.get("is_bot"),
            "auth_key_len": meta.get("auth_key_len"),
            "auth_key_fingerprint": meta.get("auth_key_fingerprint"),
            "code_url": acc.get("code_url") or "",
            "last_keepalive_at": acc.get("last_keepalive_at") or "",
            "keepalive_ping_ms": acc.get("keepalive_ping_ms"),
            "last_error": acc.get("last_error") or "",
            "region": acc.get("region") or detect_region_from_phone(acc.get("phone") or ""),
            "proxy_api_url": get_api_proxy_config(),
        },
        "sessions": {
            "telethon_session_string": meta.get("telethon_session_string") or "",
            "pyrogram_session_string": meta.get("pyrogram_session_string") or sess_data,
        },
        "user_info": online_user,
        "bots": online_bots,
        "two_fa": {
            "has_two_fa": bool(acc.get("has_two_fa") or acc.get("two_fa_password")),
            "two_fa_password": acc.get("two_fa_password") or "",
            "two_fa_hint": acc.get("two_fa_hint") or "",
        },
        "otp": {
            "local_otp_token": acc.get("local_otp_token") or "",
            "local_otp_path": f"/api/telegram/botfather/otp/{acc.get('local_otp_token') or ''}",
        },
    }


async def fetch_api_credentials_from_my_telegram(
    account_id: int,
    proxy_api_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    通过 Telegram 协议号会话全自动登录 https://my.telegram.org 抓取或自动创建 App api_id 与 api_hash。
    全链路注入与协议号归属国家/地区一致的 10 分钟粘性住宅家宽代理，有效穿透 my.telegram.org 机房与跨区风控：
    1. 启动协议号 MTProto 客户端，获取账号真实绑定手机号；
    2. 根据 E.164 手机区号解析账号归属地区 (如 +1 ➔ US, +95 ➔ MM)，从家宽代理 API 获取对应地区的住宅 IP；
    3. 全程通过该家宽代理向 https://my.telegram.org/auth/send_password 发送请求下发 Web 登录码；
    4. 轮询读取 peer 777000 (Telegram 官方服务号) 的通知消息，正则匹配拦截 Web 登录代码；
    5. 全程通过该家宽代理向 https://my.telegram.org/auth/login 提交登录，获取会话 Cookie (stel_token)；
    6. 访问 https://my.telegram.org/apps：
       - 若已存在 App：抓取 App api_id 与 App api_hash；
       - 若尚未创建 App：提交 /apps/create 表单自动创建桌面客户端应用，再抓取凭证；
    7. 若代理节点异常或创建被拒，支持自动换拉新节点重试 (最多 3 次)；
    8. 保存至 tg_protocol_accounts，并更新会话内嵌 api_id。
    """
    if proxy_api_url and proxy_api_url.strip():
        set_api_proxy_config(proxy_api_url.strip())

    acc = db.get_protocol_account_by_id(int(account_id))
    if not acc:
        raise KeyError(f"未找到 ID={account_id} 的协议号记录")

    phone = acc["phone"]
    pyro_session = _normalize_session_str(acc["session_data"])

    if Client is None:
        raise RuntimeError("Pyrogram Client 环境未就绪")

    user_client = Client(
        name=f"my_tg_{account_id}_{secrets.token_hex(3)}",
        api_id=acc.get("api_id") or Var.API_ID or 2040,
        api_hash=acc.get("api_hash") or Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
        session_string=pyro_session,
        in_memory=True,
        no_updates=True,
    )

    try:
        await user_client.start()
        me = await user_client.get_me()
        real_phone = f"+{me.phone_number}" if getattr(me, "phone_number", None) else phone
        if not real_phone.startswith("+") and real_phone.isdigit():
            real_phone = "+" + real_phone

        region = acc.get("region") or detect_region_from_phone(real_phone)
        logger.info(f"开始为协议号 {real_phone} (识别归属地区: {region}) 提取 Telegram API 凭证...")

        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        base_headers = {
            "User-Agent": ua,
            "Origin": "https://my.telegram.org",
            "Referer": "https://my.telegram.org/auth",
            "X-Requested-With": "XMLHttpRequest",
        }

        import aiohttp

        def _call_http(method_fn, url: str, **kwargs):
            try:
                return method_fn(url, **kwargs)
            except TypeError:
                kwargs.pop("proxy", None)
                return method_fn(url, **kwargs)

        def _extract_creds(html_content: str) -> Tuple[Optional[int], Optional[str]]:
            id_match = (
                re.search(r"App\s*api_id:[^<]*<[^>]+>\s*<strong[^>]*>(\d+)</strong>", html_content, re.IGNORECASE)
                or re.search(r"id=[\x22\x27]app_id[\x22\x27][^>]*value=[\x22\x27](\d+)[\x22\x27]", html_content, re.IGNORECASE)
                or re.search(r"value=[\x22\x27](\d+)[\x22\x27][^>]*id=[\x22\x27]app_id[\x22\x27]", html_content, re.IGNORECASE)
                or re.search(r"<strong>(\d{5,10})</strong>", html_content)
            )
            hash_match = (
                re.search(r"App\s*api_hash:[^<]*<[^>]+>\s*<span[^>]*>([a-fA-F0-9]{32})</span>", html_content, re.IGNORECASE)
                or re.search(r"id=[\x22\x27]app_hash[\x22\x27][^>]*value=[\x22\x27]([a-fA-F0-9]{32})[\x22\x27]", html_content, re.IGNORECASE)
                or re.search(r"value=[\x22\x27]([a-fA-F0-9]{32})[\x22\x27][^>]*id=[\x22\x27]app_hash[\x22\x27]", html_content, re.IGNORECASE)
                or re.search(r"\b([a-fA-F0-9]{32})\b", html_content)
            )
            ext_id = int(id_match.group(1)) if id_match else None
            ext_hash = hash_match.group(1).lower() if hash_match else None
            return ext_id, ext_hash

        max_attempts = 3
        last_err: Optional[Exception] = None
        used_codes = set()
        masked_proxy = "直连"
        found_id: Optional[int] = None
        found_hash: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            try:
                proxy_url = await fetch_residential_proxy_for_region(
                    region,
                    proxy_api_url=proxy_api_url,
                    attempt_index=attempt - 1,
                )
                masked_proxy = mask_proxy_url(proxy_url)
                logger.info(f"[API提取] 账号 {real_phone} (地区: {region}) 第 {attempt}/{max_attempts} 次尝试，已分配同地区家宽代理: {masked_proxy}")

                # 每轮重试必须新建独立的 TCPConnector 与 CookieJar，防止上一轮退出时自动关闭 connector 引发 "Session is closed"
                timeout_cfg = aiohttp.ClientTimeout(total=25) if hasattr(aiohttp, "ClientTimeout") else None
                connector = aiohttp.TCPConnector(ssl=False) if hasattr(aiohttp, "TCPConnector") else None
                jar = aiohttp.CookieJar(unsafe=True) if hasattr(aiohttp, "CookieJar") else None

                # 在发送请求前，记录当前 777000 会话中已有的消息 ID，防止读取到过期的旧验证码
                initial_msg_ids = set()
                try:
                    async for old_m in user_client.get_chat_history(777000, limit=5):
                        if getattr(old_m, "id", None) is not None:
                            initial_msg_ids.add(old_m.id)
                except Exception as pre_hist_err:
                    logger.debug(f"预记录 777000 历史消息异常: {pre_hist_err}")

                async with aiohttp.ClientSession(timeout=timeout_cfg, connector=connector, cookie_jar=jar) as http_sess:
                    # 1. 请求下发 Web 登录码
                    logger.info(f"正在向 my.telegram.org 请求为 {real_phone} 下发 Web 登录码 (代理: {masked_proxy})...")
                    async with _call_http(
                        http_sess.post,
                        "https://my.telegram.org/auth/send_password",
                        data={"phone": real_phone},
                        headers=base_headers,
                        proxy=proxy_url,
                    ) as resp:
                        resp_text = await resp.text()
                        random_hash = None
                        clean_resp = (resp_text or "").strip()
                        try:
                            data = json.loads(clean_resp)
                            if isinstance(data, dict):
                                random_hash = data.get("random_hash")
                        except Exception:
                            # 仅当响应为无空格、长度在 10~64 位之间的纯十六进制/base64-like hash 时才视为合法 random_hash
                            if re.fullmatch(r"[A-Za-z0-9_\-]{10,64}", clean_resp):
                                random_hash = clean_resp

                        if not random_hash:
                            low_resp = clean_resp.lower()
                            if "too many" in low_resp or "sorry" in low_resp or "flood" in low_resp or "try again later" in low_resp:
                                raise RuntimeError(f"Telegram 官网下发登录码触发频控限制:「{clean_resp}」。该号码短时间内请求登录码过多，已被 Telegram 临时冷却，请等待约 15~30 分钟后再试")
                            if "banned" in low_resp or "deactivated" in low_resp:
                                raise RuntimeError(f"Telegram 官网拒绝为该号码提供开发者服务:「{clean_resp}」")
                            raise ValueError(f"my.telegram.org 请求下发验证码失败:「{clean_resp}」")

                    logger.info(f"my.telegram.org 已向 {real_phone} 下发登录验证码 (random_hash={random_hash[:8]}...)，正在从 777000 官方通知中截获...")

                    # 2. 从 777000 服务号中监听并提取 Web login code (跳过已消耗过的 code 与旧历史消息)
                    web_code = None
                    for _ in range(20):
                        await asyncio.sleep(1.5)
                        try:
                            async for msg in user_client.get_chat_history(777000, limit=5):
                                # 若是发送请求前已存在的消息，跳过
                                if getattr(msg, "id", None) is not None and msg.id in initial_msg_ids:
                                    continue
                                txt = msg.text or ""
                                m = re.search(r"(?:Web\s*login\s*code|Web\s*登录代码|Web\s*code)[^\w\d]*\s*([A-Za-z0-9_\-]{8,24})", txt, re.IGNORECASE)
                                cand = None
                                if m:
                                    cand = m.group(1).strip()
                                elif "my.telegram.org" in txt or "web login" in txt.lower():
                                    for line in txt.splitlines():
                                        line = line.strip()
                                        if re.fullmatch(r"[A-Za-z0-9_\-]{8,24}", line):
                                            cand = line
                                            break
                                if cand and cand not in used_codes:
                                    web_code = cand
                                    break
                        except Exception as read_err:
                            logger.debug(f"读取 777000 官方消息异常: {read_err}")
                        if web_code:
                            break

                    if not web_code:
                        raise TimeoutError(f"已成功向 Telegram 官网请求登录码 (hash={random_hash[:8]}...)，但等待 30 秒仍未在 777000 收到新验证码通知。请确认该账号未在其他客户端屏蔽 777000 通知，或稍后重试")

                    used_codes.add(web_code)
                    logger.info(f"成功截获 Web 登录验证码: {web_code}，正在登录 my.telegram.org...")

                    # 3. 登录 my.telegram.org
                    async with _call_http(
                        http_sess.post,
                        "https://my.telegram.org/auth/login",
                        data={"phone": real_phone, "random_hash": random_hash, "password": web_code},
                        headers=base_headers,
                        proxy=proxy_url,
                    ) as resp:
                        login_res = await resp.text()
                        if "true" not in login_res.lower():
                            raise ValueError(f"my.telegram.org 校验验证码登录失败: {login_res}")

                    logger.info("my.telegram.org 登录成功，正在访问 /apps 提取 API 凭证...")

                    # 4. 获取 /apps 页面
                    async with _call_http(
                        http_sess.get,
                        "https://my.telegram.org/apps",
                        headers={"User-Agent": ua, "Referer": "https://my.telegram.org/"},
                        proxy=proxy_url,
                    ) as resp:
                        apps_html = await resp.text()

                    ext_id, ext_hash = _extract_creds(apps_html)

                    # 若未创建 App，自动提交表单创建
                    if not (ext_id and ext_hash):
                        logger.info(f"账号 {real_phone} 尚未创建 Telegram App，正在自动提交创建表单 (代理: {masked_proxy})...")
                        form_hash_m = (
                            re.search(r"name=[\x22\x27]hash[\x22\x27][^>]*value=[\x22\x27]([^\x22\x27]+)[\x22\x27]", apps_html)
                            or re.search(r"value=[\x22\x27]([^\x22\x27]+)[\x22\x27][^>]*name=[\x22\x27]hash[\x22\x27]", apps_html)
                        )
                        if not form_hash_m:
                            raise ValueError("my.telegram.org/apps 页面未找到已有 App 也未能提取到创建表单 hash")

                        rand_suffix = secrets.token_hex(3)
                        create_payload = {
                            "hash": form_hash_m.group(1),
                            "app_title": f"DesktopStudio{rand_suffix.upper()}",
                            "app_shortname": f"studio{rand_suffix}",
                            "app_url": "",
                            "app_platform": "desktop",
                            "app_desc": f"Desktop Client {rand_suffix}",
                        }
                        async with _call_http(
                            http_sess.post,
                            "https://my.telegram.org/apps/create",
                            data=create_payload,
                            headers={"User-Agent": ua, "Origin": "https://my.telegram.org", "Referer": "https://my.telegram.org/apps"},
                            proxy=proxy_url,
                        ) as create_resp:
                            create_text = await create_resp.text()
                            if create_text.strip().upper() == "ERROR":
                                logger.warning(f"my.telegram.org/apps/create 响应 ERROR (代理: {masked_proxy})")
                                mark_proxy_create_exhausted(proxy_url)

                        async with _call_http(
                            http_sess.get,
                            "https://my.telegram.org/apps",
                            headers={"User-Agent": ua, "Referer": "https://my.telegram.org/apps"},
                            proxy=proxy_url,
                        ) as resp2:
                            apps_html2 = await resp2.text()
                        ext_id, ext_hash = _extract_creds(apps_html2)

                        # 若创建被拒，尝试复用当前已登录会话 (stel_token)，通过其他新鲜代理快速重试创建，避免重新走登录流程触发 send_password 频控
                        if not (ext_id and ext_hash):
                            for sub_retry_idx in range(1, 3):
                                try:
                                    sub_proxy = await fetch_residential_proxy_for_region(
                                        region,
                                        proxy_api_url=proxy_api_url,
                                        attempt_index=sub_retry_idx,
                                    )
                                    if sub_proxy == proxy_url:
                                        continue
                                    masked_sub = mask_proxy_url(sub_proxy)
                                    logger.info(f"正在复用已登录会话，通过新代理 {masked_sub} 重试提交创建表单 (免除重新发验证码)...")
                                    async with _call_http(
                                        http_sess.get,
                                        "https://my.telegram.org/apps",
                                        headers={"User-Agent": ua, "Referer": "https://my.telegram.org/"},
                                        proxy=sub_proxy,
                                    ) as get_sub_resp:
                                        sub_html = await get_sub_resp.text()
                                    ext_id, ext_hash = _extract_creds(sub_html)
                                    if ext_id and ext_hash:
                                        break
                                    sub_hash_m = (
                                        re.search(r"name=[\x22\x27]hash[\x22\x27][^>]*value=[\x22\x27]([^\x22\x27]+)[\x22\x27]", sub_html)
                                        or re.search(r"value=[\x22\x27]([^\x22\x27]+)[\x22\x27][^>]*name=[\x22\x27]hash[\x22\x27]", sub_html)
                                    )
                                    if sub_hash_m:
                                        sub_suffix = secrets.token_hex(3)
                                        sub_payload = {
                                            "hash": sub_hash_m.group(1),
                                            "app_title": f"DesktopStudio{sub_suffix.upper()}",
                                            "app_shortname": f"studio{sub_suffix}",
                                            "app_url": "",
                                            "app_platform": "desktop",
                                            "app_desc": f"Desktop Client {sub_suffix}",
                                        }
                                        async with _call_http(
                                            http_sess.post,
                                            "https://my.telegram.org/apps/create",
                                            data=sub_payload,
                                            headers={"User-Agent": ua, "Origin": "https://my.telegram.org", "Referer": "https://my.telegram.org/apps"},
                                            proxy=sub_proxy,
                                        ) as post_sub_resp:
                                            post_sub_txt = await post_sub_resp.text()
                                            if post_sub_txt.strip().upper() == "ERROR":
                                                mark_proxy_create_exhausted(sub_proxy)
                                        async with _call_http(
                                            http_sess.get,
                                            "https://my.telegram.org/apps",
                                            headers={"User-Agent": ua, "Referer": "https://my.telegram.org/apps"},
                                            proxy=sub_proxy,
                                        ) as check_sub_resp:
                                            check_sub_html = await check_sub_resp.text()
                                        ext_id, ext_hash = _extract_creds(check_sub_html)
                                        if ext_id and ext_hash:
                                            break
                                except Exception as sub_err:
                                    logger.debug(f"复用登录会话换代理提交表单异常: {sub_err}")

                    if not (ext_id and ext_hash):
                        raise RuntimeError(f"未能从 my.telegram.org/apps 成功解析出 api_id 与 api_hash (代理: {masked_proxy})")

                    found_id = ext_id
                    found_hash = ext_hash
                    break  # 成功，跳出重试循环
            except Exception as attempt_err:
                last_err = attempt_err
                err_str = str(attempt_err)
                logger.warning(f"[API提取] 账号 {real_phone} 第 {attempt}/{max_attempts} 次尝试失败: {attempt_err}")
                
                # 如果是 Telegram 官方频控冷却 (如 Sorry, too many tries)，立即终止重试并向用户清晰汇报，避免连续重试加重冷却
                if "频控限制" in err_str or "too many" in err_str.lower() or "sorry" in err_str.lower():
                    raise last_err

                if attempt < max_attempts:
                    await asyncio.sleep(2.0)
                    continue
                else:
                    if "ERROR" in err_str or "频控" in err_str:
                        raise RuntimeError(f"Telegram 官网限制当前 IP/地区短时间内创建多个 App（连续 {max_attempts} 次触发 ERROR）。建议稍等 2~3 分钟后再试，或在协议号详情中配置其他可用代理")
                    raise last_err

        logger.info(f"成功为协议号 {real_phone} (地区: {region}) 提取 Telegram API 凭证: api_id={found_id}, api_hash={found_hash[:6]}**** (代理: {masked_proxy})")

        # 5. 持久化到 SQLite 数据库与磁盘凭证备份
        db.update_protocol_account(account_id, api_id=found_id, api_hash=found_hash)
        _save_cached_credentials(real_phone, found_id, found_hash)

        # 校验写入结果
        verified = db.get_protocol_account_by_id(account_id)
        if not verified or verified.get("api_id") != found_id:
            logger.error(f"协议号 {account_id} 凭证写入数据库校验失败！")
        else:
            logger.info(f"协议号 {real_phone} 凭证已成功持久化落库到 SQLite 与磁盘 JSON 备份: api_id={found_id}")

        # 尝试将会话内嵌的 api_id 更新为真实提取的 api_id
        try:
            dc_id, auth_key, _, test_mode, uid, is_bot = extract_from_pyrogram_string(pyro_session)
            new_pyro = pack_pyrogram_session(
                dc_id=dc_id,
                auth_key=auth_key,
                api_id=found_id,
                test_mode=test_mode,
                user_id=uid,
                is_bot=is_bot,
            )
            db.update_protocol_account(account_id, session_data=new_pyro)
            _save_cached_session(real_phone, new_pyro, api_id=found_id, api_hash=found_hash)
        except Exception as e_pack:
            logger.debug(f"更新会话内嵌 api_id 跳过: {e_pack}")

        updated_detail = await get_protocol_account_detail(account_id)
        updated_pool = [sanitize_account_record(r) for r in db.list_protocol_accounts()]
        return {
            "api_id": found_id,
            "api_hash": found_hash,
            "region": region,
            "proxy_used": masked_proxy,
            "detail": updated_detail,
            "pool": updated_pool,
        }

    finally:
        try:
            if getattr(user_client, "is_connected", False):
                await user_client.stop()
        except Exception:
            pass


async def batch_fetch_api_credentials(
    account_ids: Optional[List[int]] = None,
    proxy_api_url: Optional[str] = None,
    only_missing: bool = True,
) -> Dict[str, Any]:
    """
    按协议号归属地区匹配家宽代理，批量为协议号自动提取/创建 App api_id 与 api_hash
    """
    if proxy_api_url and proxy_api_url.strip():
        set_api_proxy_config(proxy_api_url.strip())

    all_accs = db.list_protocol_accounts()
    if account_ids:
        acc_set = {int(x) for x in account_ids}
        targets = [a for a in all_accs if a["id"] in acc_set]
    elif only_missing:
        targets = [
            a for a in all_accs
            if not (a.get("api_id") and a.get("api_hash")) and a.get("status") != "invalid"
        ]
    else:
        targets = [a for a in all_accs if a.get("status") != "invalid"]

    results = []
    succeeded = 0
    failed = 0

    for idx, acc in enumerate(targets):
        acc_id = acc["id"]
        phone = acc["phone"]
        reg = detect_region_from_phone(phone)
        try:
            res = await fetch_api_credentials_from_my_telegram(acc_id, proxy_api_url=proxy_api_url)
            succeeded += 1
            results.append({
                "account_id": acc_id,
                "phone": phone,
                "region": res.get("region") or reg,
                "proxy_used": res.get("proxy_used") or "",
                "api_id": res.get("api_id"),
                "success": True,
            })
        except Exception as err:
            failed += 1
            results.append({
                "account_id": acc_id,
                "phone": phone,
                "region": reg,
                "error": str(err),
                "success": False,
            })
        if idx < len(targets) - 1:
            await asyncio.sleep(1.0)

    updated_accs = [sanitize_account_record(r) for r in db.list_protocol_accounts()]
    return {
        "total": len(targets),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
        "accounts": updated_accs,
    }


async def update_protocol_account_credentials(
    account_id: int,
    api_id: Optional[int] = None,
    api_hash: Optional[str] = None,
    remark: Optional[str] = None,
) -> Dict[str, Any]:
    """
    手动更新指定协议号的 api_id、api_hash 与备注
    """
    acc = db.get_protocol_account_by_id(int(account_id))
    if not acc:
        raise KeyError(f"未找到 ID={account_id} 的协议号记录")

    updates = {}
    if api_id is not None:
        updates["api_id"] = int(api_id) if api_id else None
    if api_hash is not None:
        clean_hash = str(api_hash).strip()
        if clean_hash and not re.fullmatch(r"[a-fA-F0-9]{32}", clean_hash):
            raise ValueError("api_hash 必须为 32 位十六进制字符串 (0-9, a-f)")
        updates["api_hash"] = clean_hash.lower() if clean_hash else None
    if remark is not None:
        updates["remark"] = str(remark).strip()

    if updates:
        db.update_protocol_account(int(account_id), **updates)

    acc_after = db.get_protocol_account_by_id(int(account_id))
    if acc_after and acc_after.get("api_id") and acc_after.get("api_hash"):
        _save_cached_credentials(acc_after.get("phone") or "", acc_after["api_id"], acc_after["api_hash"])
    elif acc_after and (not acc_after.get("api_id") or not acc_after.get("api_hash")):
        _remove_cached_credentials(acc_after.get("phone") or "")

    detail = await get_protocol_account_detail(int(account_id))
    detail["pool"] = [sanitize_account_record(r) for r in db.list_protocol_accounts()]
    return detail



async def fetch_account_login_code(account_id: int, limit: int = 10) -> Dict[str, Any]:
    """
    通过协议号本地 MTProto 活跃会话实时截获 Telegram 官方服务通知 (777000) 的最新登录验证码及安全上下文
    """
    acc = db.get_protocol_account_by_id(int(account_id))
    if not acc:
        raise KeyError(f"未找到 ID={account_id} 的协议号记录")

    pyro_session = _normalize_session_str(acc["session_data"])
    if Client is None:
        raise RuntimeError("Pyrogram Client 环境未就绪")

    user_client = Client(
        name=f"otp_read_{account_id}_{secrets.token_hex(3)}",
        api_id=acc.get("api_id") or Var.API_ID or 2040,
        api_hash=acc.get("api_hash") or Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
        session_string=pyro_session,
        in_memory=True,
    )

    await user_client.start()
    try:
        latest_code = None
        code_time = None
        age_seconds = None
        device = None
        ip = None
        location = None
        raw_text = None
        recent_messages = []

        now_ts = time.time()
        async for msg in user_client.get_chat_history(777000, limit=max(1, min(limit, 20))):
            txt = (msg.text or "").strip()
            if not txt:
                continue

            msg_dt = msg.date
            msg_ts = msg_dt.timestamp() if msg_dt else now_ts
            diff_sec = max(0, int(now_ts - msg_ts))

            # 智能提取 5~6 位纯数字验证码
            extracted_code = None
            m_code = re.search(r"(?:Login\s*code|登录代码|登录验证码|验证码)[^\w\d]*\s*(\d{5,6})\b", txt, re.IGNORECASE)
            if m_code:
                extracted_code = m_code.group(1)
            elif any(k in txt.lower() for k in ("login", "sign in", "登录", "777000", "code")):
                m_code2 = re.search(r"\b(\d{5,6})\b", txt)
                if m_code2:
                    extracted_code = m_code2.group(1)

            # 提取设备、IP 与位置信息
            dev_m = re.search(r"(?:Device|设备)[^\w\d]*\s*([^\n,，]+)", txt, re.IGNORECASE)
            ip_m = re.search(r"(?:IP|IP地址)[^\w\d]*\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", txt, re.IGNORECASE)
            loc_m = re.search(r"(?:Location|位置)[^\w\d]*\s*([^\n]+)", txt, re.IGNORECASE)

            msg_item = {
                "id": msg.id,
                "text": txt,
                "code": extracted_code,
                "date": msg_dt.strftime("%Y-%m-%d %H:%M:%S") if msg_dt else "",
                "age_seconds": diff_sec,
                "device": dev_m.group(1).strip() if dev_m else None,
                "ip": ip_m.group(1).strip() if ip_m else None,
                "location": loc_m.group(1).strip() if loc_m else None,
            }
            recent_messages.append(msg_item)

            if latest_code is None and extracted_code:
                latest_code = extracted_code
                code_time = msg_item["date"]
                age_seconds = diff_sec
                device = msg_item["device"]
                ip = msg_item["ip"]
                location = msg_item["location"]
                raw_text = txt

        relative_time_str = "暂无验证码"
        is_recent = False
        if age_seconds is not None:
            is_recent = age_seconds < 600  # 10 分钟以内
            if age_seconds < 60:
                relative_time_str = f"{age_seconds} 秒前 (刚刚收到)"
            elif age_seconds < 3600:
                relative_time_str = f"{age_seconds // 60} 分钟前"
            else:
                relative_time_str = f"{age_seconds // 3600} 小时前"

        return {
            "account_id": account_id,
            "phone": acc["phone"],
            "latest_code": latest_code,
            "code_time": code_time,
            "relative_time": relative_time_str,
            "age_seconds": age_seconds,
            "is_recent": is_recent,
            "device": device or "未知设备",
            "ip": ip or "未知 IP",
            "location": location or "未知位置",
            "raw_text": raw_text or "",
            "pass2fa": acc.get("two_fa_password") or "",
            "has_two_fa": bool(acc.get("has_two_fa") or acc.get("two_fa_password")),
            "messages": recent_messages[:6],
        }
    finally:
        try:
            await user_client.stop()
        except Exception:
            pass


async def get_account_2fa_status(account_id: int) -> Dict[str, Any]:
    """
    通过 MTProto account.GetPassword 实时探测 Telegram 官方 2FA 状态、密码提示与重置风险
    """
    acc = db.get_protocol_account_by_id(int(account_id))
    if not acc:
        raise KeyError(f"未找到 ID={account_id} 的协议号记录")

    pyro_session = _normalize_session_str(acc["session_data"])
    if Client is None or raw is None:
        raise RuntimeError("Pyrogram Client 环境未就绪")

    user_client = Client(
        name=f"2fa_chk_{account_id}_{secrets.token_hex(3)}",
        api_id=acc.get("api_id") or Var.API_ID or 2040,
        api_hash=acc.get("api_hash") or Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
        session_string=pyro_session,
        in_memory=True,
    )

    await user_client.start()
    try:
        r = await user_client.invoke(raw.functions.account.GetPassword())
        has_password = bool(getattr(r, "has_password", False))
        hint = str(getattr(r, "hint", "") or "")
        has_recovery = bool(getattr(r, "has_recovery", False))
        login_email = getattr(r, "login_email_pattern", None)
        pending_reset_date = getattr(r, "pending_reset_date", None)
        has_pending_reset = bool(pending_reset_date and pending_reset_date > 0)

        db_updates = {}
        if has_password != bool(acc.get("has_two_fa")):
            db_updates["has_two_fa"] = 1 if has_password else 0
        if hint and hint != (acc.get("two_fa_hint") or ""):
            db_updates["two_fa_hint"] = hint
        if db_updates:
            db.update_protocol_account(account_id, **db_updates)

        return {
            "account_id": account_id,
            "phone": acc["phone"],
            "has_password": has_password,
            "hint": hint,
            "has_recovery": has_recovery,
            "login_email_pattern": login_email or "",
            "pending_reset_date": pending_reset_date,
            "has_pending_reset": has_pending_reset,
            "saved_two_fa_password": acc.get("two_fa_password") or "",
        }
    finally:
        try:
            await user_client.stop()
        except Exception:
            pass


def generate_strong_2fa_password(prefix: str = "Mr-", length: int = 12) -> str:
    """
    生成格式清晰、防视觉混淆的高强度 2FA 密码
    采用 Mr- 前缀 + 12 位不混淆的大小写字母与数字组合（如 Mr-8kP4xV9mQ2wL）
    """
    alphabet = "23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"
    rand_part = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"{prefix}{rand_part}"


async def update_account_2fa_password(
    account_id: int,
    new_password: Optional[str] = None,
    current_password: Optional[str] = None,
    hint: str = "",
) -> Dict[str, Any]:
    """
    为协议号开启或修改 2FA 云密码并更新本地数据库
    支持自动生成高强度新密码，并按优先级自动尝试候选旧密码完成验证
    """
    clean_new_pass = str(new_password or "").strip()
    if not clean_new_pass or clean_new_pass.lower() == "auto":
        clean_new_pass = generate_strong_2fa_password()

    acc = db.get_protocol_account_by_id(int(account_id))
    if not acc:
        raise KeyError(f"未找到 ID={account_id} 的协议号记录")

    pyro_session = _normalize_session_str(acc["session_data"])
    if Client is None or raw is None:
        raise RuntimeError("Pyrogram Client 环境未就绪")

    user_client = Client(
        name=f"2fa_up_{account_id}_{secrets.token_hex(3)}",
        api_id=acc.get("api_id") or Var.API_ID or 2040,
        api_hash=acc.get("api_hash") or Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
        session_string=pyro_session,
        in_memory=True,
    )

    await user_client.start()
    try:
        r = await user_client.invoke(raw.functions.account.GetPassword())
        has_password = bool(getattr(r, "has_password", False))

        matched_old = None
        if not has_password:
            logger.info(f"协议号 {acc['phone']} 尚未设置 2FA 云密码，正在开启...")
            await user_client.enable_cloud_password(password=clean_new_pass, hint=hint or "")
            action = "created"
        else:
            candidates: List[str] = []
            if current_password and str(current_password).strip():
                candidates.append(str(current_password).strip())
            if acc.get("two_fa_password") and str(acc["two_fa_password"]).strip():
                p = str(acc["two_fa_password"]).strip()
                if p not in candidates:
                    candidates.append(p)

            # 号商历史高频默认密码池兜底
            for dp in ("z4422404", "qq1122", "8899"):
                if dp not in candidates:
                    candidates.append(dp)

            logger.info(f"协议号 {acc['phone']} 已存在 2FA 云密码，正在尝试候选原密码修改为新密码...")
            success = False
            last_err = None
            for cand in candidates:
                try:
                    await user_client.change_cloud_password(
                        current_password=cand,
                        new_password=clean_new_pass,
                        new_hint=hint or "",
                    )
                    success = True
                    matched_old = cand
                    action = "updated"
                    logger.info(f"协议号 {acc['phone']} 原 2FA 密码匹配成功 ({cand})，已更新为新密码！")
                    break
                except Exception as cand_err:
                    err_str = str(cand_err).upper()
                    err_cls = cand_err.__class__.__name__
                    if "PASSWORD_HASH_INVALID" in err_str or "INVALID PASSWORD" in err_str or "PasswordHashInvalid" in err_cls:
                        last_err = cand_err
                        continue
                    raise cand_err

            if not success:
                raise ValueError(f"修改 2FA 密码失败：候选原密码校验未通过 ({last_err or '请手动输入原密码'})")

        db.update_protocol_account(
            account_id,
            two_fa_password=clean_new_pass,
            two_fa_hint=hint or "",
            has_two_fa=1,
        )
        logger.info(f"协议号 {acc['phone']} 2FA 云密码已成功更新并落库！")

        return {
            "success": True,
            "action": action,
            "message": "2FA 云密码已成功设置并持久化落库！",
            "phone": acc["phone"],
            "new_password": clean_new_pass,
            "has_two_fa": True,
            "hint": hint or "",
            "matched_old_password": matched_old,
        }
    finally:
        try:
            await user_client.stop()
        except Exception:
            pass


async def terminate_account_other_sessions(account_id: int) -> Dict[str, Any]:
    """
    一键注销除当前 MistRelay 之外的所有外部已登录会话 (Terminate All Other Sessions)
    """
    acc = db.get_protocol_account_by_id(int(account_id))
    if not acc:
        raise KeyError(f"未找到 ID={account_id} 的协议号记录")

    pyro_session = _normalize_session_str(acc["session_data"])
    if Client is None or raw is None:
        raise RuntimeError("Pyrogram Client 环境未就绪")

    user_client = Client(
        name=f"term_sess_{account_id}_{secrets.token_hex(3)}",
        api_id=acc.get("api_id") or Var.API_ID or 2040,
        api_hash=acc.get("api_hash") or Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
        session_string=pyro_session,
        in_memory=True,
    )

    await user_client.start()
    try:
        before_auths = []
        try:
            res_auths = await user_client.invoke(raw.functions.account.GetAuthorizations())
            before_auths = getattr(res_auths, "authorizations", []) or []
        except Exception as e:
            logger.warning(f"获取授权会话列表失败: {e}")

        total_before = len(before_auths)

        try:
            await user_client.invoke(raw.functions.auth.ResetAuthorizations())
        except Exception as reset_err:
            err_name = reset_err.__class__.__name__
            if "FreshReset" in err_name or "FRESH_RESET_AUTHORISATION_FORBIDDEN" in str(reset_err):
                return {
                    "success": False,
                    "restricted": True,
                    "total_sessions": total_before,
                    "message": "该会话在当前设备登录未满 24 小时，受 Telegram 官方安全风控限制暂不可踢除其他设备。但只要 2FA 云密码已修改，号商外部会话掉线后无法再次登录，请在 24 小时后重试踢除！",
                }
            raise reset_err

        after_count = 1
        try:
            res_auths2 = await user_client.invoke(raw.functions.account.GetAuthorizations())
            after_count = len(getattr(res_auths2, "authorizations", []) or [])
        except Exception:
            pass

        terminated_count = max(0, total_before - after_count)
        return {
            "success": True,
            "terminated_count": terminated_count,
            "remaining_sessions": after_count,
            "message": f"成功踢除 {terminated_count} 个外部设备会话！当前仅保留 MistRelay 本地会话。",
        }
    finally:
        try:
            await user_client.stop()
        except Exception:
            pass


async def cancel_account_password_reset(account_id: int) -> Dict[str, Any]:
    """
    一键撤销正在进行的 Telegram 密码重置申请，阻断外部收回
    """
    acc = db.get_protocol_account_by_id(int(account_id))
    if not acc:
        raise KeyError(f"未找到 ID={account_id} 的协议号记录")

    pyro_session = _normalize_session_str(acc["session_data"])
    if Client is None or raw is None:
        raise RuntimeError("Pyrogram Client 环境未就绪")

    user_client = Client(
        name=f"cancel_reset_{account_id}_{secrets.token_hex(3)}",
        api_id=acc.get("api_id") or Var.API_ID or 2040,
        api_hash=acc.get("api_hash") or Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
        session_string=pyro_session,
        in_memory=True,
    )

    await user_client.start()
    try:
        await user_client.invoke(raw.functions.account.DeclinePasswordReset())
        return {
            "success": True,
            "message": "已成功撤销 Telegram 密码重置申请，账号所有权锁定！",
        }
    finally:
        try:
            await user_client.stop()
        except Exception:
            pass


def bind_local_otp_url(account_id: int, replace_code_url: bool = True) -> Dict[str, Any]:
    """
    为协议号绑定专属本地安全接码链接，并可选替换号商原有 code_url
    """
    acc = db.get_protocol_account_by_id(int(account_id))
    if not acc:
        raise KeyError(f"未找到 ID={account_id} 的协议号记录")

    token = acc.get("local_otp_token")
    if not token:
        token = secrets.token_hex(16)
        db.update_protocol_account(account_id, local_otp_token=token)

    local_path = f"/api/telegram/botfather/otp/{token}"
    if replace_code_url:
        db.update_protocol_account(account_id, code_url=local_path)

    return {
        "account_id": account_id,
        "token": token,
        "otp_path": local_path,
        "code_url": local_path if replace_code_url else (acc.get("code_url") or ""),
    }


async def takeover_protocol_account(
    account_id: int,
    new_password: Optional[str] = None,
    hint: str = "MistRelay",
) -> Dict[str, Any]:
    """
    一键全自动安全接管指定协议号：
    1. 自动生成（或使用指定的）高强度 2FA 云密码并更新至 Telegram 与本地数据库；
    2. 自动绑定本机自主接码链接并替换号商 code_url；
    3. 自动注销号商其他所有外部设备会话 (Terminate Other Sessions)。
    """
    acc = db.get_protocol_account_by_id(int(account_id))
    if not acc:
        raise KeyError(f"未找到 ID={account_id} 的协议号记录")

    clean_new_pass = str(new_password or "").strip()
    if not clean_new_pass or clean_new_pass.lower() == "auto":
        clean_new_pass = generate_strong_2fa_password()

    pass_res = await update_account_2fa_password(
        account_id=account_id,
        new_password=clean_new_pass,
        hint=hint,
    )
    final_new_pass = pass_res.get("new_password", clean_new_pass)

    otp_res = bind_local_otp_url(account_id=account_id, replace_code_url=True)

    try:
        term_res = await terminate_account_other_sessions(account_id=account_id)
    except Exception as term_err:
        logger.warning(f"接管协议号 {acc['phone']} 时踢除外部设备异常: {term_err}")
        term_res = {"success": False, "terminated_count": 0, "message": str(term_err)}

    db.update_protocol_account(
        account_id,
        is_taken_over=1,
        taken_over_at=db._now_iso(),
    )

    detail = await get_protocol_account_detail(account_id)
    terminated_cnt = term_res.get("terminated_count", 0)
    is_restricted = bool(term_res.get("restricted", False))

    msg = f"协议号 {acc['phone']} 已完成全自动安全接管！新 2FA 密码 ({final_new_pass}) 已加锁落库，接码已切换为本机链接。"
    if is_restricted:
        msg += "（注：新会话未满 24h 暂不可踢旧设备，但因 2FA 已改，号商无法再登）"
    elif term_res.get("success"):
        msg += f" 已踢除 {terminated_cnt} 个外部设备！"

    return {
        "success": True,
        "account_id": account_id,
        "phone": acc["phone"],
        "new_password": final_new_pass,
        "hint": hint,
        "otp_path": otp_res.get("otp_path"),
        "code_url": otp_res.get("code_url"),
        "terminated_count": terminated_cnt,
        "restricted": is_restricted,
        "message": msg,
        "detail": detail,
    }


async def takeover_all_protocol_accounts(
    account_ids: Optional[List[int]] = None,
    only_unsecured: bool = True,
    force_all: bool = False,
) -> Dict[str, Any]:
    """
    全池（或指定账号列表）批量自动生成专属强密码并一键安全接管。
    默认自动跳过已完成安全接管的协议号，仅对未接管账号执行操作。
    """
    all_pool = db.list_protocol_accounts()
    pool_total = len(all_pool)
    already_taken_over_count = sum(1 for a in all_pool if is_account_taken_over(a))

    if account_ids:
        candidates = [db.get_protocol_account_by_id(int(aid)) for aid in account_ids]
        candidates = [a for a in candidates if a]
    else:
        candidates = [a for a in all_pool if a.get("status") != "invalid"]

    if only_unsecured and not force_all:
        accounts = [a for a in candidates if not is_account_taken_over(a)]
        skipped_count = already_taken_over_count
    else:
        accounts = candidates
        skipped_count = 0

    total = len(accounts)
    success_count = 0
    failed_count = 0
    results = []

    for idx, acc in enumerate(accounts):
        aid = acc["id"]
        phone = acc["phone"]
        try:
            res = await takeover_protocol_account(aid)
            success_count += 1
            results.append({
                "account_id": aid,
                "phone": phone,
                "success": True,
                "new_password": res["new_password"],
                "terminated_count": res.get("terminated_count", 0),
                "restricted": res.get("restricted", False),
                "message": res["message"],
            })
        except Exception as e:
            failed_count += 1
            logger.error(f"批量接管协议号 {phone} 失败: {e}")
            results.append({
                "account_id": aid,
                "phone": phone,
                "success": False,
                "error": str(e),
            })
        if idx < total - 1:
            await asyncio.sleep(1.2)

    return {
        "success": True,
        "pool_total": pool_total,
        "total": total,
        "skipped_count": skipped_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "results": results,
        "pool": [sanitize_account_record(a) for a in db.list_protocol_accounts()],
    }


async def keepalive_protocol_account(account_id: int, check_bots: bool = False) -> Dict[str, Any]:
    """
    对指定协议号资产发起一次轻量 MTProto 保活连接，刷新账号档案与活跃时间，
    测量 ping 延迟，并在会话失效且有接码链接时自动尝试重登续期。
    """
    acc = db.get_protocol_account_by_id(int(account_id))
    if not acc:
        raise KeyError(f"未找到 ID={account_id} 的协议号记录")

    phone = acc["phone"]
    pyro_session = _normalize_session_str(acc["session_data"])

    if Client is None:
        raise RuntimeError("Pyrogram Client 环境未就绪")

    start_ts = time.time()
    user_client = Client(
        name=f"keepalive_acc_{account_id}_{secrets.token_hex(3)}",
        api_id=Var.API_ID or 2040,
        api_hash=Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
        session_string=pyro_session,
        in_memory=True,
        no_updates=True,
    )

    try:
        try:
            await user_client.start()
        except Exception as conn_err:
            if acc.get("code_url"):
                logger.info(f"协议号 {phone} 会话失效 ({conn_err})，尝试通过接码链接重新登录续期...")
                pyro_session = await login_via_phone_and_code_url(f"{phone}|{acc['code_url']}")
                user_client = Client(
                    name=f"re_keepalive_acc_{account_id}_{secrets.token_hex(3)}",
                    api_id=Var.API_ID or 2040,
                    api_hash=Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
                    session_string=pyro_session,
                    in_memory=True,
                    no_updates=True,
                )
                await user_client.start()
            else:
                db.update_protocol_account(
                    account_id,
                    status="invalid",
                    last_error=str(conn_err),
                    last_keepalive_at=db._now_iso(),
                )
                return {
                    "success": False,
                    "account_id": account_id,
                    "phone": phone,
                    "error": str(conn_err),
                    "status": "invalid",
                }

        ping_ms = max(1, int((time.time() - start_ts) * 1000))
        me = await user_client.get_me()
        real_phone = f"+{me.phone_number}" if getattr(me, "phone_number", None) else phone

        bot_count = acc.get("bot_count", 0)
        existing_bots = []
        if check_bots:
            try:
                existing_bots = await fetch_existing_bot_tokens(user_client, max_limit=20)
                bot_count = len(existing_bots)
            except Exception as b_err:
                logger.debug(f"保活查询 Bot 数量跳过: {b_err}")

        new_status = "limit_reached" if bot_count >= 20 else "active"
        dc_id = getattr(getattr(user_client, "storage", None), "dc_id", None)
        if callable(dc_id):
            try:
                dc_id = await dc_id()
            except Exception:
                dc_id = None

        db.update_protocol_account(
            account_id,
            phone=real_phone if real_phone == phone else phone,
            bot_count=bot_count,
            status=new_status,
            first_name=getattr(me, "first_name", "") or "",
            username=getattr(me, "username", "") or "",
            tg_user_id=getattr(me, "id", None),
            dc_id=dc_id if dc_id else None,
            last_keepalive_at=db._now_iso(),
            keepalive_ping_ms=ping_ms,
            last_error="",
            last_used_at=db._now_iso(),
        )
        updated = db.get_protocol_account_by_id(account_id)
        return {
            "success": True,
            "account_id": account_id,
            "phone": real_phone,
            "ping_ms": ping_ms,
            "status": new_status,
            "account": sanitize_account_record(updated),
            "user_info": {
                "id": getattr(me, "id", None),
                "first_name": getattr(me, "first_name", ""),
                "username": getattr(me, "username", ""),
            },
            "bots": [{"username": b["username"]} for b in existing_bots] if check_bots else None,
        }
    except Exception as e:
        db.update_protocol_account(
            account_id,
            last_error=str(e),
            last_keepalive_at=db._now_iso(),
        )
        return {
            "success": False,
            "account_id": account_id,
            "phone": phone,
            "error": str(e),
            "status": "error",
        }
    finally:
        try:
            if getattr(user_client, "is_connected", False):
                await user_client.stop()
        except Exception:
            pass


async def keepalive_all_protocol_accounts(
    account_ids: Optional[List[int]] = None,
    check_bots: bool = False,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    全量或批量对协议号资产池执行错峰保活巡检
    """
    if account_ids:
        accounts = [db.get_protocol_account_by_id(aid) for aid in account_ids]
        accounts = [a for a in accounts if a]
    else:
        accounts = db.list_protocol_accounts()

    total = len(accounts)
    results = []
    success_count = 0
    failed_count = 0
    ping_samples = []

    for idx, acc in enumerate(accounts, 1):
        aid = acc["id"]
        phone = acc["phone"]
        if on_progress:
            try:
                on_progress(f"正在保活协议号 [{idx}/{total}] {phone}...")
            except Exception:
                pass

        res = await keepalive_protocol_account(aid, check_bots=check_bots)
        results.append(res)
        if res.get("success"):
            success_count += 1
            if res.get("ping_ms"):
                ping_samples.append(res["ping_ms"])
        else:
            failed_count += 1

        if idx < total:
            await asyncio.sleep(1.5)

    avg_ping = int(sum(ping_samples) / len(ping_samples)) if ping_samples else 0
    pool = sync_cached_sessions_to_db()

    summary = {
        "total": total,
        "success_count": success_count,
        "failed_count": failed_count,
        "avg_ping_ms": avg_ping,
        "results": results,
        "pool": pool,
    }
    return summary


class ProtocolKeepaliveWorker:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_run_at: Optional[str] = None
        self._last_summary: Optional[Dict] = None

    def start(self):
        if self._running or (self._task and not self._task.done()):
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("协议号定时保活巡检 Worker 已启动")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("协议号定时保活巡检 Worker 已安全停止")

    async def _run_loop(self):
        # 启动后延迟 15 秒执行初次巡检
        await asyncio.sleep(15.0)
        while self._running:
            try:
                enabled = bool(db.get_config_value("PROTOCOL_KEEPALIVE_ENABLED", True))
                interval_hours = max(1, int(db.get_config_value("PROTOCOL_KEEPALIVE_INTERVAL_HOURS", 12)))
                if enabled:
                    logger.info("开始执行协议号资产池定时保活巡检...")
                    self._last_run_at = db._now_iso()
                    summary = await keepalive_all_protocol_accounts(check_bots=False)
                    self._last_summary = {
                        "run_at": self._last_run_at,
                        "success_count": summary["success_count"],
                        "failed_count": summary["failed_count"],
                        "avg_ping_ms": summary["avg_ping_ms"],
                    }
                    logger.info(
                        f"协议号定时保活巡检完成: 成功 {summary['success_count']}, "
                        f"失败 {summary['failed_count']}, 平均延迟 {summary['avg_ping_ms']}ms"
                    )

                # 间隔休眠，支持快速响应停止信号
                sleep_secs = interval_hours * 3600
                for _ in range(max(1, int(sleep_secs / 10))):
                    if not self._running:
                        break
                    await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"协议号保活巡检循环发生异常: {e}", exc_info=True)
                await asyncio.sleep(60)

    def get_status(self) -> Dict:
        enabled = bool(db.get_config_value("PROTOCOL_KEEPALIVE_ENABLED", True))
        interval_hours = int(db.get_config_value("PROTOCOL_KEEPALIVE_INTERVAL_HOURS", 12))
        return {
            "running": self._running,
            "enabled": enabled,
            "interval_hours": interval_hours,
            "last_run_at": self._last_run_at,
            "last_summary": self._last_summary,
        }


_keepalive_worker: Optional[ProtocolKeepaliveWorker] = None


def get_keepalive_worker() -> ProtocolKeepaliveWorker:
    global _keepalive_worker
    if _keepalive_worker is None:
        _keepalive_worker = ProtocolKeepaliveWorker()
    return _keepalive_worker



# ============================================================================
# 多租户专属存储频道开通与 DC 区域智能探测引擎
# ============================================================================

def detect_user_dc_id(tg_user: Any) -> int:
    """
    根据 Telegram 用户的 Peer/头像或客户端语言偏好智能探测其归属的 DC 数据中心编号 (1~5)
    """
    if tg_user is None:
        return 5

    # 1. 优先读取 Telegram 官方附带的 dc_id (若用户设置了头像，Pyrogram User 会解析出 dc_id)
    dc_attr = getattr(tg_user, "dc_id", None)
    if dc_attr and isinstance(dc_attr, int) and 1 <= dc_attr <= 5:
        return dc_attr

    # 2. 检查 photo 属性中是否有 dc_id
    photo = getattr(tg_user, "photo", None)
    if photo:
        p_dc = getattr(photo, "dc_id", None)
        if p_dc and isinstance(p_dc, int) and 1 <= p_dc <= 5:
            return p_dc

    # 3. 若无头像，根据客户端语言代码 language_code 智能判定
    lang = (getattr(tg_user, "language_code", None) or "").lower().strip()
    if any(lang.startswith(p) for p in ("zh", "ja", "ko", "my", "id", "th", "vi", "fil", "ms", "km", "lo")):
        return 5  # DC5 亚太/新加坡
    if any(lang.startswith(p) for p in ("ru", "uk", "be", "kz", "uz", "az", "hy", "ka")):
        return 2  # DC2 欧洲/阿姆斯特丹
    if any(lang.startswith(p) for p in ("en", "es", "pt", "fr", "de", "it", "nl")):
        return 1  # DC1 美洲/迈阿密

    # 4. 默认分配系统配置的 DEFAULT_TENANT_DC_ID (默认 DC5)
    try:
        default_dc = int(db.get_config("DEFAULT_TENANT_DC_ID", 5) or 5)
        if 1 <= default_dc <= 5:
            return default_dc
    except Exception:
        pass
    return 5


async def provision_user_storage_channel(
    username: str,
    target_dc_id: int = 5,
    tg_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    从协议号资产池中优先挑选与用户 target_dc_id 相同的有效协议号，
    自动调用 MTProto 创建专属公开存储频道（设置随机公开 Handle），
    并将主控 Bot 与同区写节点 Bot 提权为管理员。
    """
    accs = db.list_protocol_accounts()
    valid_accs = [a for a in accs if a.get("status") != "invalid" and a.get("session_data")]
    if not valid_accs:
        raise RuntimeError("协议号资产池中无可用的 Telegram 协议号，请先在「自动铸机」页面导入协议号")

    try:
        all_users = db.list_users()
        account_channel_counts = {}
        for u in all_users:
            cid_acc = u.get("creator_account_id")
            if cid_acc:
                account_channel_counts[int(cid_acc)] = account_channel_counts.get(int(cid_acc), 0) + 1
    except Exception:
        account_channel_counts = {}

    def _acc_score(acc_item: dict) -> tuple:
        s = sanitize_account_record(acc_item)
        acc_dc = s.get("dc_id") or 1
        is_same_dc = (acc_dc == target_dc_id)
        dc_diff = 0 if is_same_dc else abs(acc_dc - target_dc_id)
        ch_count = account_channel_counts.get(int(acc_item["id"]), 0)
        is_near_limit = ch_count >= 8
        return (is_near_limit, not is_same_dc, dc_diff, ch_count, acc_item["id"])

    sorted_accs = sorted(valid_accs, key=_acc_score)

    if Client is None:
        raise RuntimeError("Pyrogram Client 环境未就绪")

    last_err = None
    for acc_idx, selected_acc in enumerate(sorted_accs):
        selected_meta = sanitize_account_record(selected_acc)
        acc_dc_id = selected_meta.get("dc_id") or target_dc_id or 5

        logger.info(
            f"[多租户建频] 为用户 {username} (TG ID: {tg_user_id}, 偏好 DC: {target_dc_id}) "
            f"分配协议号 ID={selected_acc['id']} (Phone: {selected_acc['phone']}, 实际 DC: {acc_dc_id})"
        )

        pyro_session = _normalize_session_str(selected_acc["session_data"])
        user_client = Client(
            name=f"prov_chan_{selected_acc['id']}_{secrets.token_hex(3)}",
            api_id=selected_acc.get("api_id") or Var.API_ID or 2040,
            api_hash=selected_acc.get("api_hash") or Var.API_HASH or "b18441a1ff607e10a989891a5462e627",
            session_string=pyro_session,
            in_memory=True,
        )

        await user_client.start()
        try:
            title_suffix = f" - {username}" if username else ""
            chan_title = f"MistRelay Cloud{title_suffix}"
            chan_desc = "MistRelay Dedicated Cloud Storage Channel"
            created_chat = await user_client.create_channel(
                title=chan_title,
                description=chan_desc,
            )
            channel_id = created_chat.id

            channel_username = None
            quota_exceeded = False
            for attempt in range(5):
                suffix = secrets.token_hex(4)
                uid_tag = str(tg_user_id)[-4:] if tg_user_id else secrets.token_hex(2)
                raw_prefix = str(db.get_config("TENANT_CHANNEL_PREFIX", "mr_u") or "mr_u").strip()
                clean_prefix = re.sub(r"[^a-zA-Z0-9_]", "", raw_prefix).lower() or "mr_u"
                if not clean_prefix[0].isalpha():
                    clean_prefix = f"mr_{clean_prefix}"
                candidate_username = f"{clean_prefix}{uid_tag}_{suffix}" 
                try:
                    await user_client.set_chat_username(channel_id, candidate_username)
                    channel_username = candidate_username
                    break
                except Exception as e:
                    err_msg = str(e)
                    if "PUBLIC_TOO_MUCH" in err_msg or "CHANNELS_ADMIN_PUBLIC_TOO_MUCH" in err_msg or "CHANNELS_TOO_MUCH" in err_msg:
                        logger.warning(f"协议号 ID={selected_acc['id']} 公开频道配额已达上限: {e}")
                        quota_exceeded = True
                        break
                    logger.warning(f"设置频道公开 Handle @{candidate_username} 失败 (尝试 {attempt + 1}/5): {e}")
                    await asyncio.sleep(0.3)

            if not channel_username:
                if quota_exceeded and acc_idx < len(sorted_accs) - 1:
                    logger.info(f"协议号 ID={selected_acc['id']} 公开频道配额已满，清理空频道并自动切换下一个协议号重试...")
                    try:
                        await user_client.delete_channel(channel_id)
                    except Exception:
                        pass
                    continue

                candidate_username = f"mr_box_{int(time.time())}_{secrets.token_hex(2)}"
                try:
                    await user_client.set_chat_username(channel_id, candidate_username)
                    channel_username = candidate_username
                except Exception as e:
                    logger.warning(f"设置兜底频道 Handle 失败: {e}")
                    channel_username = f"channel_{abs(channel_id)}"

            try:
                from pyrogram.types import ChatPrivileges
                admin_privileges = ChatPrivileges(
                    can_manage_chat=True,
                    can_post_messages=True,
                    can_edit_messages=True,
                    can_delete_messages=True,
                    can_invite_users=True,
                )
            except Exception:
                admin_privileges = None

            bot_candidates = []
            try:
                from WebStreamer.bot import StreamBot
                if StreamBot and getattr(StreamBot, "me", None) and getattr(StreamBot.me, "username", None):
                    bot_candidates.append(StreamBot.me.username)
            except Exception:
                pass

            try:
                from WebStreamer.bot.clients import multi_clients
                for idx, cl in list(multi_clients.items())[:3]:
                    if getattr(cl, "me", None) and getattr(cl.me, "username", None):
                        if cl.me.username not in bot_candidates:
                            bot_candidates.append(cl.me.username)
            except Exception:
                pass

            for b_uname in bot_candidates:
                try:
                    if admin_privileges is not None:
                        await user_client.promote_chat_member(
                            chat_id=channel_id,
                            user_id=b_uname,
                            privileges=admin_privileges,
                        )
                    else:
                        await user_client.promote_chat_member(chat_id=channel_id, user_id=b_uname)
                    logger.info(f"成功将机器人 @{b_uname} 提权为专属频道管理员 (chat_id={channel_id})")
                except Exception as e:
                    logger.warning(f"提权机器人 @{b_uname} 失败 (已忽略): {e}")

            try:
                from WebStreamer.bot import StreamBot
                if StreamBot and getattr(StreamBot, "is_connected", False):
                    await StreamBot.send_message(
                        chat_id=channel_id,
                        text=(
                            f"🚀 <b>MistRelay 专属云盘存储空间初始化成功</b>\n\n"
                            f"👤 <b>归属用户:</b> <code>{username}</code> (ID: <code>{tg_user_id or 'N/A'}</code>)\n"
                            f"🌐 <b>数据中心:</b> <code>DC{acc_dc_id}</code>\n"
                            f"📡 <b>公开句柄:</b> @{channel_username}\n\n"
                            f"💡 <i>此频道用于安全物理隔离存储您的个人媒体与转存文件，支持全集群 55+ Bot 免加群并发极速串流。</i>"
                        ),
                    )
            except Exception as e:
                logger.warning(f"发送频道初始化消息失败 (已忽略): {e}")

            return {
                "bin_channel_id": channel_id,
                "bin_channel_username": channel_username,
                "dc_id": acc_dc_id,
                "creator_account_id": selected_acc["id"],
            }
        except Exception as e:
            last_err = e
            if acc_idx < len(sorted_accs) - 1:
                logger.warning(f"协议号 ID={selected_acc['id']} 建频异常 ({e})，切换下一协议号重试...")
                continue
            raise e
        finally:
            try:
                await user_client.stop()
            except Exception:
                pass

    if last_err:
        raise last_err
    raise RuntimeError("无法开通专属存储频道")
