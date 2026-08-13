import unittest
from unittest.mock import patch

from request_security import LoginAttemptLimiter, get_client_ip, login_limit_keys


class _Request:
    def __init__(self, remote: str, forwarded_for: str = ""):
        self.remote = remote
        self.headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}


class RequestSecurityTests(unittest.TestCase):
    def test_limiter_locks_and_clears_ip_and_account_keys(self):
        limiter = LoginAttemptLimiter(max_failures=3, window_seconds=60, lockout_seconds=30)
        keys = login_limit_keys("203.0.113.10", "Admin")

        self.assertEqual(limiter.record_failure(keys, now=1), 0)
        self.assertEqual(limiter.record_failure(keys, now=2), 0)
        self.assertEqual(limiter.record_failure(keys, now=3), 30)
        self.assertEqual(limiter.retry_after(keys, now=4), 29)

        limiter.record_success(keys)
        self.assertEqual(limiter.retry_after(keys, now=4), 0)

    def test_one_source_cannot_globally_lock_an_account(self):
        first_source = login_limit_keys("203.0.113.10", "admin")
        second_source = login_limit_keys("203.0.113.11", "admin")
        self.assertNotEqual(first_source, second_source)
        self.assertEqual(len(first_source), 1)

    def test_old_failures_expire_outside_window(self):
        limiter = LoginAttemptLimiter(max_failures=2, window_seconds=10, lockout_seconds=30)
        keys = ("ip:test",)

        limiter.record_failure(keys, now=1)
        self.assertEqual(limiter.record_failure(keys, now=12), 0)

    def test_forwarded_address_requires_trusted_direct_peer(self):
        request = _Request("10.0.0.2", "198.51.100.8, 10.0.0.2")
        with patch.dict("os.environ", {"MISTRELAY_TRUSTED_PROXY_CIDRS": "10.0.0.0/24"}):
            self.assertEqual(get_client_ip(request), "198.51.100.8")

        with patch.dict("os.environ", {"MISTRELAY_TRUSTED_PROXY_CIDRS": "127.0.0.0/8"}):
            self.assertEqual(get_client_ip(request), "10.0.0.2")


if __name__ == "__main__":
    unittest.main()
