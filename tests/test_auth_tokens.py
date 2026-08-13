import unittest
import hashlib
from unittest.mock import patch

import auth


class AuthTokenTests(unittest.TestCase):
    def test_password_hashes_are_versioned_and_legacy_hashes_still_verify(self):
        password = "test-only-password-123"
        current_hash = auth.hash_password(password)
        self.assertTrue(current_hash.startswith("pbkdf2_sha256$600000$"))
        self.assertTrue(auth.verify_password(password, current_hash))
        self.assertFalse(auth.password_needs_rehash(current_hash))

        salt = "0123456789abcdef0123456789abcdef"
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
        legacy_hash = f"{salt}${digest.hex()}"
        self.assertTrue(auth.verify_password(password, legacy_hash))
        self.assertTrue(auth.password_needs_rehash(legacy_hash))

    def test_resource_ticket_is_bound_to_path_and_expiry(self):
        with patch("auth.time.time", return_value=1000):
            ticket = auth.create_resource_ticket("/api/telegram/thumbnail/42", 60)

        with patch("auth.time.time", return_value=1059):
            self.assertTrue(auth.verify_resource_ticket(ticket, "/api/telegram/thumbnail/42"))
            self.assertFalse(auth.verify_resource_ticket(ticket, "/api/telegram/thumbnail/43"))

        with patch("auth.time.time", return_value=1061):
            self.assertFalse(auth.verify_resource_ticket(ticket, "/api/telegram/thumbnail/42"))

    def test_signing_secret_rotation_invalidates_access_and_resource_tokens(self):
        access_token = auth.create_token(1, "admin")
        ticket = auth.create_resource_ticket("/api/telegram/thumbnail/42")

        auth.rotate_signing_secret()

        self.assertIsNone(auth.verify_token(access_token))
        self.assertFalse(auth.verify_resource_ticket(ticket, "/api/telegram/thumbnail/42"))


if __name__ == "__main__":
    unittest.main()
