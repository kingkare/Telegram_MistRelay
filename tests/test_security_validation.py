import tests  # noqa: F401
import hashlib
import unittest
from unittest.mock import patch

from security_validation import (
    are_valid_telegram_credentials,
    contains_preserved_compromised_credentials,
    is_valid_rpc_secret,
    merge_additional_bot_tokens,
    parse_allowed_user_ids,
)


class SecurityValidationTests(unittest.TestCase):
    def test_additional_bot_tokens_append_without_replacing_existing_values(self):
        existing = ["123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"]
        additions = [
            "234567:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
            "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
        ]
        self.assertEqual(
            merge_additional_bot_tokens(existing, additions),
            [existing[0], additions[0]],
        )

    def test_additional_bot_tokens_reject_invalid_and_primary_tokens(self):
        primary = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        with self.assertRaisesRegex(ValueError, "格式错误"):
            merge_additional_bot_tokens([], ["bad-token"], primary)
        with self.assertRaisesRegex(ValueError, "主 Bot Token"):
            merge_additional_bot_tokens([], [primary], primary)

    def test_rpc_secret_rejects_known_long_placeholder(self):
        self.assertFalse(
            is_valid_rpc_secret("replace-with-at-least-32-random-characters")
        )

    def test_rpc_secret_rejects_low_entropy_value(self):
        self.assertFalse(is_valid_rpc_secret("a" * 64))

    def test_rpc_secret_accepts_urlsafe_high_entropy_value(self):
        self.assertTrue(
            is_valid_rpc_secret(
                "0123456789abcdefABCDEFGHIJKLMNOPQRSTUVWXYZ_-ghijklmnop"
            )
        )

    def test_allowlist_accepts_only_numeric_user_ids(self):
        self.assertEqual(parse_allowed_user_ids("123456, 987654"), ["123456", "987654"])
        self.assertEqual(parse_allowed_user_ids("trusted_username"), [])
        self.assertEqual(parse_allowed_user_ids("123456,username"), [])

    def test_telegram_credentials_require_all_valid_fields(self):
        self.assertTrue(
            are_valid_telegram_credentials(
                12345,
                "0123456789abcdef0123456789abcdef",
                "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
                "123456789",
            )
        )
        self.assertFalse(
            are_valid_telegram_credentials(
                12345,
                "0123456789abcdef0123456789abcdef",
                "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
                "mutable_username",
            )
        )
    def test_api_id_does_not_trigger_preserved_credential_block(self):
        api_id = 123456
        fingerprint = hashlib.sha256(str(api_id).encode("utf-8")).hexdigest()
        with patch.dict(
            "security_validation.PRESERVED_COMPROMISED_VALUE_HASHES",
            {"API_ID": frozenset({fingerprint})},
        ):
            self.assertFalse(
                contains_preserved_compromised_credentials(api_id=api_id)
            )


if __name__ == "__main__":
    unittest.main()
