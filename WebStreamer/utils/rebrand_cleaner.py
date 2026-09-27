"""
Telegram 转发消息无痕洗白与智能归属替换引擎

核心能力：
1. 自动探测本频道公开标识（配置项 FORWARD_TARGET_CHANNEL 或主 Bot 嗅探到的 channel_public_handle）；
2. 清洗配文（Caption）中的第三方引流广告词、替换第三方 @username 与 t.me 链接为本频道标识；
3. 支持自定义替换/剔除规则与频道落款签名追加（控制在 Telegram 1024 字符上限内）；
4. 净化网盘文件名中的第三方引流后缀，严格保留原始文件扩展名与集数编号。
"""

import os
import re
from typing import List, Optional, Tuple


# 强侵入性水印引流词（如 电报TG@xxx、tg搜@xxx），在配文和文件名中直接整体剔除
_WATERMARK_PROMO_RE = re.compile(
    r"(?:电报\s*TG|TG\s*搜(?:索)?|电报\s*搜(?:索)?|飞机\s*搜(?:索)?)\s*[:：]?\s*@?[A-Za-z0-9_]{3,32}",
    re.IGNORECASE,
)

# 频道归属引导前缀（在文件名中连同 handle 一起剔除；在配文中保留引导语并将 handle 替换为本频道）
_PROMO_PREFIX_HANDLE_RE = re.compile(
    r"(?:关注\s*频道|官方\s*频道|资源\s*频道|来源\s*频道|电报\s*频道|TG\s*频道|"
    r"认准\s*频道|订阅\s*频道|首发\s*频道|福利\s*频道|更新\s*频道|更多资源\s*搜?)"
    r"\s*[:：]?\s*@?([A-Za-z0-9_]{3,32})",
    re.IGNORECASE,
)

# 独立残留的引流引导词（无后续 handle 时清理）
_STANDALONE_PROMO_WORD_RE = re.compile(
    r"(?:电报\s*TG|TG\s*搜(?:索)?|电报\s*搜(?:索)?|飞机\s*搜(?:索)?)\s*[:：]?",
    re.IGNORECASE,
)

# Telegram 链接匹配（支持 https://t.me/xxx, http://telegram.me/xxx, t.me/+xxx, t.me/joinchat/xxx）
_TME_LINK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/(?:joinchat/|\+)?([A-Za-z0-9_-]{3,64})(?:/\d+)?",
    re.IGNORECASE,
)

# 通用 @username 匹配（允许前面为连字符、下划线、空格或括号，仅排除字母数字邮箱前缀）
_AT_USERNAME_RE = re.compile(
    r"(?<![A-Za-z0-9])@([A-Za-z0-9_]{3,32})"
)

# 合法文件扩展名正则（1~8 位字母数字，常见媒体/文档/压缩包扩展名）
_VALID_EXT_RE = re.compile(r"^\.[A-Za-z0-9]{1,8}$")

# 清理后残留的空括号对
_EMPTY_BRACKETS_RE = re.compile(
    r"(?:\(\s*\)|\[\s*\]|【\s*】|（\s*）|《\s*》|「\s*」|『\s*』)"
)


def normalize_channel_identity(raw_target: Optional[str]) -> Tuple[str, str, str]:
    """
    将频道配置规范化为 (at_handle, bare_username, tme_url) 三元组。
    例如:
      "@jiuyue1314520" -> ("@jiuyue1314520", "jiuyue1314520", "https://t.me/jiuyue1314520")
      "https://t.me/jiuyue1314520" -> ("@jiuyue1314520", "jiuyue1314520", "https://t.me/jiuyue1314520")
      "" -> ("", "", "")
    """
    if not raw_target:
        return ("", "", "")
    cleaned = str(raw_target).strip()
    if not cleaned:
        return ("", "", "")

    link_match = _TME_LINK_RE.search(cleaned)
    if link_match:
        bare = link_match.group(1).strip().lstrip("@")
    else:
        bare = cleaned.lstrip("@").strip().split("/")[0].strip()

    if not bare or not re.match(r"^[A-Za-z0-9_]{3,64}$", bare):
        return ("", "", "")

    return (f"@{bare}", bare, f"https://t.me/{bare}")


def get_effective_target_channel(configured_target: Optional[str] = None) -> str:
    """
    获取当前生效的目标归属频道（格式为 @username，若无则返回空字符串）。
    优先使用传入参数 -> 数据库/配置 FORWARD_TARGET_CHANNEL -> 主客户端自动探测的 channel_public_handle。
    """
    candidate = configured_target
    if candidate is None or not str(candidate).strip():
        try:
            from configer import get_config_value
            candidate = get_config_value("FORWARD_TARGET_CHANNEL", "")
        except Exception:
            candidate = ""

    if not candidate or not str(candidate).strip():
        try:
            import WebStreamer.bot as bot_mod
            candidate = getattr(bot_mod, "channel_public_handle", None) or ""
        except Exception:
            candidate = ""

    at_handle, _, _ = normalize_channel_identity(candidate)
    return at_handle


def parse_custom_replace_rules(rules_text: Optional[str]) -> List[Tuple[str, str]]:
    """
    解析多行自定义替换规则。
    支持格式：
      - "原词=>替换词" 或 "原词->替换词"：将原词替换为替换词
      - "广告词"：直接剔除该广告词
    忽略空行及以 # 开头的注释行。
    """
    if not rules_text:
        return []
    rules: List[Tuple[str, str]] = []
    for raw_line in str(rules_text).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=>" in line:
            src, dst = line.split("=>", 1)
            src = src.strip()
            dst = dst.strip()
            if src:
                rules.append((src, dst))
        elif "->" in line:
            src, dst = line.split("->", 1)
            src = src.strip()
            dst = dst.strip()
            if src:
                rules.append((src, dst))
        else:
            rules.append((line, ""))
    return rules


def _apply_custom_rules(text: str, custom_rules: Optional[str]) -> str:
    for src, dst in parse_custom_replace_rules(custom_rules):
        if src:
            text = text.replace(src, dst)
    return text


def clean_and_rebrand_caption(
    raw_caption: Optional[str],
    target_channel: Optional[str] = None,
    signature: Optional[str] = None,
    custom_rules: Optional[str] = None,
    max_length: int = 1024,
) -> str:
    """
    清洗配文中的第三方引流标识，并将第三方 @username / t.me 链接替换为本频道标识，
    末尾按需追加签名落款，确保总长度不超过 Telegram 1024 字符上限。
    """
    effective_target = get_effective_target_channel(target_channel)
    at_handle, bare_username, tme_url = normalize_channel_identity(effective_target)

    if signature is None:
        try:
            from configer import get_config_value
            signature = get_config_value("FORWARD_CHANNEL_SIGNATURE", "") or ""
        except Exception:
            signature = ""

    if custom_rules is None:
        try:
            from configer import get_config_value
            custom_rules = get_config_value("FORWARD_CUSTOM_REPLACE_RULES", "") or ""
        except Exception:
            custom_rules = ""

    text = str(raw_caption or "")
    if text:
        # 1. 先执行用户自定义规则
        text = _apply_custom_rules(text, custom_rules)

        # 2. 替换或清理 t.me 链接
        def _replace_tme(match: re.Match) -> str:
            matched_user = match.group(1) or ""
            if bare_username and matched_user.lower() == bare_username.lower():
                return tme_url
            return tme_url if tme_url else ""

        text = _TME_LINK_RE.sub(_replace_tme, text)

        # 3. 清除强侵入式引流水印（如 电报TG@yijiqwq、tg搜@xxx）
        text = _WATERMARK_PROMO_RE.sub("", text)
        text = _STANDALONE_PROMO_WORD_RE.sub("", text)

        # 4. 替换普通第三方 @username 为本频道 @handle（若未配置本频道则移除）
        def _replace_at_user(match: re.Match) -> str:
            matched_user = match.group(1) or ""
            if bare_username and matched_user.lower() == bare_username.lower():
                return at_handle
            return at_handle if at_handle else ""

        text = _AT_USERNAME_RE.sub(_replace_at_user, text)

        # 5. 清理残留空括号与重复连续的本频道 @handle
        text = _EMPTY_BRACKETS_RE.sub("", text)
        if at_handle:
            dup_re = re.compile(
                rf"({re.escape(at_handle)})(?:\s+{re.escape(at_handle)})+",
                re.IGNORECASE,
            )
            text = dup_re.sub(r"\1", text)

        # 6. 规整空白与多余空行
        lines = [re.sub(r"[^\S\r\n]{2,}", " ", ln).strip() for ln in text.splitlines()]
        text = "\n".join(lines).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)

    # 7. 处理频道签名落款
    resolved_sig = ""
    if signature and str(signature).strip():
        resolved_sig = str(signature).strip()
        resolved_sig = resolved_sig.replace("{channel}", at_handle or "")
        resolved_sig = resolved_sig.replace("{url}", tme_url or "")
        resolved_sig = re.sub(r"[^\S\r\n]{2,}", " ", resolved_sig).strip()

    if resolved_sig:
        if not text:
            text = resolved_sig
        elif resolved_sig not in text:
            text = f"{text}\n\n{resolved_sig}"

    # 8. 严格控制在 Telegram 1024 字符上限内
    if len(text) > max_length:
        if resolved_sig and len(resolved_sig) + 6 < max_length and text.endswith(resolved_sig):
            body_budget = max_length - len(resolved_sig) - 5
            body = text[:body_budget].rstrip()
            text = f"{body}...\n\n{resolved_sig}"
        else:
            text = text[: max_length - 3].rstrip() + "..."

    return text


def clean_drive_filename(
    raw_name: Optional[str],
    clean_enabled: Optional[bool] = None,
    custom_rules: Optional[str] = None,
) -> str:
    """
    净化网盘媒体文件名中的第三方引流后缀与广告标签，
    同时严格保留原始文件扩展名（如 .mp4, .mkv）与集数序号（如 (1), 01）。
    """
    if not raw_name:
        return ""
    name_str = str(raw_name).strip()
    if not name_str:
        return ""

    if clean_enabled is None:
        try:
            from configer import get_config_value
            clean_enabled = bool(get_config_value("FORWARD_CLEAN_FILENAMES", True))
        except Exception:
            clean_enabled = True

    if not clean_enabled:
        return name_str

    if custom_rules is None:
        try:
            from configer import get_config_value
            custom_rules = get_config_value("FORWARD_CUSTOM_REPLACE_RULES", "") or ""
        except Exception:
            custom_rules = ""

    # 分离文件名主干与扩展名
    stem, ext = os.path.splitext(name_str)
    if not _VALID_EXT_RE.match(ext) or ext.lower() in (".me", ".dog", ".com", ".org", ".net", ".cn", ".cc"):
        stem = name_str
        ext = ""

    cleaned_stem = stem
    # 1. 应用自定义替换/剔除规则
    cleaned_stem = _apply_custom_rules(cleaned_stem, custom_rules)

    # 2. 移除 t.me 链接与 http/https URL
    cleaned_stem = _TME_LINK_RE.sub("", cleaned_stem)
    cleaned_stem = re.sub(r"https?://\S+", "", cleaned_stem, flags=re.IGNORECASE)

    # 3. 移除引流词+handle（如 电报TG@yijiqwq、tg搜@xxx）以及独立的 @username
    cleaned_stem = _WATERMARK_PROMO_RE.sub("", cleaned_stem)
    cleaned_stem = _PROMO_PREFIX_HANDLE_RE.sub("", cleaned_stem)
    cleaned_stem = _STANDALONE_PROMO_WORD_RE.sub("", cleaned_stem)
    cleaned_stem = _AT_USERNAME_RE.sub("", cleaned_stem)

    # 4. 移除残留空括号
    cleaned_stem = _EMPTY_BRACKETS_RE.sub("", cleaned_stem)

    # 5. 合并多余空白与连接符，保留如 (1)、01、E01 等集数标记
    cleaned_stem = re.sub(r"\s{2,}", " ", cleaned_stem)
    cleaned_stem = re.sub(r"[-_]{2,}", "-", cleaned_stem)
    cleaned_stem = cleaned_stem.strip(" -_.")

    # 若整个文件名原本只有广告词导致主干为空，保底回退为安全名称
    if not cleaned_stem:
        fallback = re.sub(r"[@/\\:*?\"<>|]+", "", stem).strip(" -_.")
        cleaned_stem = fallback if fallback else "media"

    return f"{cleaned_stem}{ext}"
