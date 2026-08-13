import hashlib
import ipaddress
import os
import time
from collections import defaultdict, deque
from collections.abc import Iterable


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class LoginAttemptLimiter:
    """Bound failed login attempts by both client address and account name."""

    def __init__(
        self,
        max_failures: int = 5,
        window_seconds: int = 15 * 60,
        lockout_seconds: int = 15 * 60,
    ) -> None:
        self.max_failures = max(1, int(max_failures))
        self.window_seconds = max(1, int(window_seconds))
        self.lockout_seconds = max(1, int(lockout_seconds))
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}

    def retry_after(self, keys: Iterable[str], *, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        retry_after = 0
        for key in set(keys):
            locked_until = self._locked_until.get(key, 0.0)
            if locked_until <= current:
                self._locked_until.pop(key, None)
                self._prune(key, current)
                continue
            retry_after = max(retry_after, int(locked_until - current + 0.999))
        return retry_after

    def record_failure(self, keys: Iterable[str], *, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        for key in set(keys):
            self._prune(key, current)
            failures = self._failures[key]
            failures.append(current)
            if len(failures) >= self.max_failures:
                self._locked_until[key] = current + self.lockout_seconds
        return self.retry_after(keys, now=current)

    def record_success(self, keys: Iterable[str]) -> None:
        for key in set(keys):
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def _prune(self, key: str, now: float) -> None:
        failures = self._failures.get(key)
        if not failures:
            return
        cutoff = now - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(key, None)


def login_limit_keys(client_ip: str, username: str) -> tuple[str]:
    normalized_username = username.strip().casefold()
    username_hash = hashlib.sha256(normalized_username.encode("utf-8")).hexdigest()[:16]
    # Scope a lock to one source/account pair. A global account lock lets any
    # unauthenticated caller deny the sole administrator access indefinitely.
    return (f"ip-account:{client_ip}:{username_hash}",)


def audit_username(username: str) -> str:
    normalized_username = username.strip().casefold()
    return hashlib.sha256(normalized_username.encode("utf-8")).hexdigest()[:16]


def sanitize_log_value(value: object, max_length: int = 200) -> str:
    text = str(value or "")[:max_length]
    return "".join(character if character.isprintable() else "?" for character in text)


def _trusted_proxy_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    networks = []
    for raw_value in os.environ.get("MISTRELAY_TRUSTED_PROXY_CIDRS", "").split(","):
        value = raw_value.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def get_client_ip(request) -> str:
    """Use proxy headers only when the direct peer is explicitly trusted."""
    remote = str(getattr(request, "remote", "") or "unknown")
    try:
        remote_ip = ipaddress.ip_address(remote)
    except ValueError:
        return sanitize_log_value(remote, 64) or "unknown"

    if any(remote_ip in network for network in _trusted_proxy_networks()):
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        candidate = forwarded_for.split(",", 1)[0].strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            pass
    return str(remote_ip)


LOGIN_LIMITER = LoginAttemptLimiter(
    max_failures=_positive_int_env("MISTRELAY_LOGIN_MAX_FAILURES", 5),
    window_seconds=_positive_int_env("MISTRELAY_LOGIN_WINDOW_SECONDS", 15 * 60),
    lockout_seconds=_positive_int_env("MISTRELAY_LOGIN_LOCKOUT_SECONDS", 15 * 60),
)
