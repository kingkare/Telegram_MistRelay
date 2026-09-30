import tests  # noqa: F401
import os
import time
import json
import hmac
import hashlib
import urllib.parse
import tempfile
import unittest

os.environ["MISTRELAY_DB_PATH"] = tempfile.mktemp(
    prefix="mistrelay_tma_tests_import_",
    suffix=".db",
    dir="/tmp",
)

import auth
import db


def _generate_valid_tma_init_data(bot_token: str, user_dict: dict, auth_date: int = None, query_id: str = "AAHdF6IQAAAAAN0XohD123") -> tuple[str, str]:
    if auth_date is None:
        auth_date = int(time.time())
    params = {
        "auth_date": str(auth_date),
        "query_id": query_id,
        "user": json.dumps(user_dict, separators=(",", ":")),
    }
    sorted_items = sorted(params.items(), key=lambda x: x[0])
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_items)
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    params["hash"] = expected_hash
    return urllib.parse.urlencode(params), expected_hash


class TelegramMiniAppAuthTests(unittest.TestCase):
    def setUp(self):
        self.orig_db_path = db.DB_PATH
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = self._tmp.name
        db.DB_PATH = self.db_path
        db.init_db()

        self.bot_token = "123456789:ABCDefGhIJklMNopQRstUVwxyz1234567"
        self.test_tg_uid = 88776655

        with db.db_conn() as connection:
            connection.execute(
                """
                INSERT INTO users
                    (id, username, password_hash, role, tg_user_id, tg_username, tg_first_name, dc_id, created_at, updated_at)
                VALUES (1, 'tma_user', 'unused-test-hash', 'user', ?, 'tma_user_tg', 'TMA Tester', 5, '2026-09-30', '2026-09-30')
                """,
                (self.test_tg_uid,),
            )

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        if hasattr(self, "db_path") and os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_verify_tma_init_data_success(self):
        user_dict = {
            "id": self.test_tg_uid,
            "first_name": "TMA Tester",
            "username": "tma_user_tg",
        }
        init_data, expected_hash = _generate_valid_tma_init_data(self.bot_token, user_dict)

        result = auth.verify_telegram_webapp_init_data(init_data, self.bot_token)
        self.assertIsNotNone(result)
        self.assertEqual(result["user"]["id"], self.test_tg_uid)
        self.assertEqual(result["user"]["username"], "tma_user_tg")
        self.assertEqual(result["query_id"], "AAHdF6IQAAAAAN0XohD123")

    def test_verify_tma_init_data_tampered_hash(self):
        user_dict = {"id": self.test_tg_uid, "first_name": "TMA Tester"}
        init_data, _ = _generate_valid_tma_init_data(self.bot_token, user_dict)

        # 篡改 hash
        tampered = init_data.replace("hash=", "hash=bad0000000000000000000000000000000000000000000000000000000000000")
        result = auth.verify_telegram_webapp_init_data(tampered, self.bot_token)
        self.assertIsNone(result)

    def test_verify_tma_init_data_tampered_payload(self):
        user_dict = {"id": self.test_tg_uid, "first_name": "TMA Tester"}
        init_data, expected_hash = _generate_valid_tma_init_data(self.bot_token, user_dict)

        # 篡改用户 ID，但保留原 hash
        tampered = init_data.replace(str(self.test_tg_uid), "99999999")
        result = auth.verify_telegram_webapp_init_data(tampered, self.bot_token)
        self.assertIsNone(result)

    def test_verify_tma_init_data_expired(self):
        user_dict = {"id": self.test_tg_uid, "first_name": "TMA Tester"}
        # 超过 86400 秒前（例如 2 天前）
        past_date = int(time.time()) - 100000
        init_data, _ = _generate_valid_tma_init_data(self.bot_token, user_dict, auth_date=past_date)

        result = auth.verify_telegram_webapp_init_data(init_data, self.bot_token, max_age_seconds=86400)
        self.assertIsNone(result)

    def test_verify_tma_init_data_future_clock_skew(self):
        user_dict = {"id": self.test_tg_uid, "first_name": "TMA Tester"}
        # 未来时钟偏差超过 5 分钟
        future_date = int(time.time()) + 600
        init_data, _ = _generate_valid_tma_init_data(self.bot_token, user_dict, auth_date=future_date)

        result = auth.verify_telegram_webapp_init_data(init_data, self.bot_token)
        self.assertIsNone(result)

    def test_tma_db_user_linkage_and_session(self):
        user = db.get_user_by_tg_id(self.test_tg_uid)
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "tma_user")
        self.assertEqual(user["dc_id"], 5)

        token = auth.create_token(user["id"], user["username"], role=user.get("role", "user"))
        payload = auth.verify_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["uid"], user["id"])
        self.assertEqual(payload["sub"], "tma_user")

        refresh_token = auth.create_refresh_token()
        session = db.create_auth_session(
            user["id"],
            auth.hash_refresh_token(refresh_token),
            auth.get_refresh_token_expires_at(),
            device_id="tma",
            session_name="Telegram Mini App",
        )
        self.assertIsNotNone(session)
        self.assertEqual(session["device_id"], "tma")
        self.assertEqual(session["session_name"], "Telegram Mini App")


if __name__ == "__main__":
    unittest.main()
