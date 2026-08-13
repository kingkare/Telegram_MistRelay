import hashlib
import json
import re


RPC_SECRET_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,256}")
API_HASH_PATTERN = re.compile(r"[0-9a-fA-F]{32}")
BOT_TOKEN_PATTERN = re.compile(r"[0-9]{5,12}:[A-Za-z0-9_-]{30,}")
USER_ID_PATTERN = re.compile(r"[1-9][0-9]{0,19}")
PLACEHOLDER_MARKERS = (
    "change-me",
    "change_me",
    "replace-with",
    "placeholder",
    "example",
)

# SHA-256 fingerprints that remain blocked locally. Plaintext credentials must
# remain only in restricted incident evidence; Telegram API and Bot credentials
# are supplied by the operator and are not blocked by this local table.
PRESERVED_COMPROMISED_VALUE_HASHES = {
    "RPC_SECRET": frozenset({
        "7b70d3ab4c7641542e1f158b458eeae7cfb7bdb815d4110cc6178bafcfdf43f8",
    }),
}


def credential_matches_preserved_fingerprint(value: object, category: str) -> bool:
    fingerprints = PRESERVED_COMPROMISED_VALUE_HASHES.get(category)
    text = str(value or "").strip()
    if not fingerprints or not text:
        return False
    if category == "API_HASH":
        text = text.lower()
    fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return fingerprint in fingerprints


def contains_preserved_compromised_credentials(
    *,
    api_id: object = None,
    api_hash: object = None,
    bot_tokens: object = None,
    rpc_secret: object = None,
) -> bool:
    """Check preserved secret fingerprints; API_ID is intentionally excluded."""
    if isinstance(bot_tokens, str):
        token_values = [bot_tokens]
    elif isinstance(bot_tokens, (list, tuple, set, frozenset)):
        token_values = list(bot_tokens)
    else:
        token_values = []
    return any((
        credential_matches_preserved_fingerprint(api_hash, "API_HASH"),
        credential_matches_preserved_fingerprint(rpc_secret, "RPC_SECRET"),
        any(
            credential_matches_preserved_fingerprint(token, "BOT_TOKENS")
            for token in token_values
        ),
    ))


def is_valid_rpc_secret(value: object) -> bool:
    secret = str(value or "")
    lowered = secret.lower()
    return (
        RPC_SECRET_PATTERN.fullmatch(secret) is not None
        and len(set(secret)) >= 12
        and not any(marker in lowered for marker in PLACEHOLDER_MARKERS)
    )


def parse_allowed_user_ids(raw_value: object) -> list[str]:
    if isinstance(raw_value, list):
        values = [str(value).strip() for value in raw_value]
    else:
        text = str(raw_value or "").strip()
        decoded = None
        if text.startswith("["):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                return []
        values = (
            [str(value).strip() for value in decoded]
            if isinstance(decoded, list)
            else [value.strip() for value in text.split(",") if value.strip()]
        )
    if not values or not all(USER_ID_PATTERN.fullmatch(value) for value in values):
        return []
    return values


def are_valid_telegram_credentials(
    api_id: object,
    api_hash: object,
    bot_token: object,
    allowed_users: object,
) -> bool:
    api_id_text = str(api_id or "").strip()
    return (
        api_id_text.isdigit()
        and int(api_id_text) > 0
        and API_HASH_PATTERN.fullmatch(str(api_hash or "").strip()) is not None
        and BOT_TOKEN_PATTERN.fullmatch(str(bot_token or "").strip()) is not None
        and bool(parse_allowed_user_ids(allowed_users))
    )


def merge_additional_bot_tokens(
    existing_tokens: object,
    new_tokens: object,
    primary_token: object = None,
) -> list[str]:
    """Validate and append additional Bot tokens without exposing stored values."""
    if not isinstance(existing_tokens, list):
        raise ValueError("现有多机器人 Token 配置格式错误")
    if not isinstance(new_tokens, list):
        raise ValueError("多机器人 Token 必须使用列表格式")

    normalized_existing = []
    for token in existing_tokens:
        if not isinstance(token, str) or BOT_TOKEN_PATTERN.fullmatch(token.strip()) is None:
            raise ValueError("现有多机器人 Token 配置包含无效 Token")
        normalized_existing.append(token.strip())

    normalized_primary = str(primary_token or "").strip()
    merged = list(dict.fromkeys(normalized_existing))
    seen = set(merged)
    for token in new_tokens:
        if not isinstance(token, str):
            raise ValueError("多机器人 Token 必须是字符串")
        normalized = token.strip()
        if BOT_TOKEN_PATTERN.fullmatch(normalized) is None:
            raise ValueError("多机器人 Token 格式错误")
        if normalized == normalized_primary:
            raise ValueError("多机器人 Token 不能与主 Bot Token 相同")
        if credential_matches_preserved_fingerprint(normalized, "BOT_TOKENS"):
            raise ValueError("多机器人 Token 已失效，请使用新 Token")
        if normalized not in seen:
            merged.append(normalized)
            seen.add(normalized)

    if len(merged) > 100:
        raise ValueError("多机器人 Token 数量不能超过 100 个")
    return merged
