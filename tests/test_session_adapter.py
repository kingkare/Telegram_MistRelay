import tests  # noqa: F401
import os
import struct
import base64
import sqlite3
import tempfile
import unittest

from session_adapter import (
    pack_pyrogram_session,
    extract_from_pyrogram_string,
    extract_dc_and_auth_key_from_telethon_string,
    extract_from_sqlite_session,
    parse_session_to_pyrogram_string,
)


class TestSessionAdapter(unittest.TestCase):
    def test_pyrogram_session_pack_and_extract(self):
        auth_key = b"P" * 256
        session_str = pack_pyrogram_session(
            dc_id=5,
            auth_key=auth_key,
            api_id=123456,
            test_mode=False,
            user_id=99887766,
            is_bot=False,
        )
        dc_id, extracted_key, api_id, test_mode, user_id, is_bot = extract_from_pyrogram_string(session_str)
        self.assertEqual(dc_id, 5)
        self.assertEqual(extracted_key, auth_key)
        self.assertEqual(api_id, 123456)
        self.assertFalse(test_mode)
        self.assertEqual(user_id, 99887766)
        self.assertFalse(is_bot)

    def test_telethon_string_session_conversion(self):
        auth_key = b"T" * 256
        packed_telethon = struct.pack(">B4sH256s", 4, b"\x95\xa2\x04\x38", 443, auth_key)
        telethon_str = "1" + base64.urlsafe_b64encode(packed_telethon).decode("utf-8")

        pyro_str = parse_session_to_pyrogram_string(telethon_str, default_api_id=2040)
        dc_id, extracted_key, api_id, _, _, _ = extract_from_pyrogram_string(pyro_str)
        self.assertEqual(dc_id, 4)
        self.assertEqual(extracted_key, auth_key)
        self.assertEqual(api_id, 2040)

    def test_telethon_sqlite_session_file_conversion(self):
        auth_key = b"S" * 256
        with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as tf:
            temp_path = tf.name

        try:
            conn = sqlite3.connect(temp_path)
            cur = conn.cursor()
            cur.execute(
                "CREATE TABLE sessions (dc_id INTEGER, server_address TEXT, port INTEGER, auth_key BLOB, takeout_id INTEGER)"
            )
            cur.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)", (2, "149.154.167.50", 443, auth_key, None))
            conn.commit()
            conn.close()

            with open(temp_path, "rb") as f:
                raw_bytes = f.read()

            pyro_str = parse_session_to_pyrogram_string(raw_bytes, default_api_id=9999)
            dc_id, extracted_key, api_id, _, _, _ = extract_from_pyrogram_string(pyro_str)
            self.assertEqual(dc_id, 2)
            self.assertEqual(extracted_key, auth_key)
            self.assertEqual(api_id, 9999)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_pyrogram_sqlite_session_file_conversion(self):
        auth_key = b"K" * 256
        with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as tf:
            temp_path = tf.name

        try:
            conn = sqlite3.connect(temp_path)
            cur = conn.cursor()
            cur.execute(
                "CREATE TABLE sessions (dc_id INTEGER, api_id INTEGER, test_mode INTEGER, auth_key BLOB, date INTEGER, user_id INTEGER, is_bot INTEGER)"
            )
            cur.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)", (1, 8888, 0, auth_key, 0, 11223344, 0))
            conn.commit()
            conn.close()

            with open(temp_path, "rb") as f:
                raw_bytes = f.read()

            pyro_str = parse_session_to_pyrogram_string(raw_bytes, default_api_id=1111)
            dc_id, extracted_key, api_id, _, user_id, _ = extract_from_pyrogram_string(pyro_str)
            self.assertEqual(dc_id, 1)
            self.assertEqual(extracted_key, auth_key)
            self.assertEqual(api_id, 8888)
            self.assertEqual(user_id, 11223344)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_invalid_session_rejected(self):
        with self.assertRaises(ValueError):
            parse_session_to_pyrogram_string("invalid_random_string")


if __name__ == "__main__":
    unittest.main()
