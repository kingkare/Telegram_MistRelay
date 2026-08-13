import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import db
from activation_preflight import (
    evaluate_container,
    evaluate_database,
    evaluate_filesystem,
)
from auth import hash_password
from rotate_credentials import load_and_validate, rotate_database


class ActivationPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database_dir = self.root / "db"
        self.download_root = self.root / "downloads"
        self.cache_root = self.root / "cache" / "thumbnails"
        for directory in (self.database_dir, self.download_root, self.cache_root):
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)

        self.database = self.database_dir / "downloads.db"
        with patch.object(db, "DB_PATH", str(self.database)):
            db.init_db()
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO users (username, password_hash, role, created_at, updated_at) "
                "VALUES ('admin', ?, 'admin', 'old', 'old')",
                (hash_password("old-test-password-123"),),
            )
            old_configs = (
                ("API_ID", "87654321", "int", "telegram"),
                ("API_HASH", "ffffffffffffffffffffffffffffffff", "string", "telegram"),
                ("BOT_TOKEN", "111111:oldoldoldoldoldoldoldoldoldold", "string", "telegram"),
                ("MULTI_BOT_TOKENS", "[]", "list", "stream"),
                ("RPC_SECRET", "old-secret", "string", "aria2"),
            )
            connection.executemany(
                "INSERT INTO config_settings "
                "(key, value, value_type, category, description, updated_at) "
                "VALUES (?, ?, ?, ?, '', 'old')",
                old_configs,
            )
        self.database.chmod(0o600)

        self.legacy_config = self.database_dir / "config.yml"
        self.legacy_config.write_text(
            "BOT_TOKEN: exposed\nRPC_SECRET: exposed\n",
            encoding="utf-8",
        )
        self.legacy_config.chmod(0o600)
        self.credential_input = self.root / "credentials.yml"
        self.credential_input.write_text(
            yaml.safe_dump({
                "API_ID": 12345678,
                "API_HASH": "0123456789abcdef0123456789abcdef",
                "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
                "ADMIN_ID": 123456789,
                "BIN_CHANNEL": "-1001234567890",
                "STREAM_ALLOWED_USERS": [123456789],
                "RPC_SECRET": "0123456789abcdefABCDEFGHIJKLMNOPQRSTUVWXYZ_-ghijklmnop",
                "MULTI_BOT_TOKENS": [],
                "ADMIN_PASSWORD": "new-test-password-456",
                "PUBLIC_BASE_URL": "https://files.example.test",
                "SEND_STREAM_LINK": True,
            }),
            encoding="utf-8",
        )
        self.credential_input.chmod(0o600)
        values = load_and_validate(self.credential_input)
        rotate_database(self.database, values, self.legacy_config)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{self.database}{suffix}")
            if sidecar.exists():
                sidecar.chmod(0o600)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _filesystem_checks(self):
        return evaluate_filesystem(
            self.database,
            self.download_root,
            self.cache_root,
            os.geteuid(),
            os.getegid(),
        )

    def test_rotated_database_and_filesystem_pass(self):
        checks = self._filesystem_checks()
        checks.extend(evaluate_database(self.database, "https://files.example.test"))
        self.assertTrue(checks)
        self.assertEqual([item.name for item in checks if not item.ok], [])

    def test_session_material_is_a_hard_failure(self):
        session = self.database_dir / "bot.session"
        session.write_text("test-only", encoding="utf-8")
        failed = {item.name for item in self._filesystem_checks() if not item.ok}
        self.assertIn("session_material_absent", failed)

    def test_legacy_forward_target_and_origin_mismatch_fail(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO config_settings "
                "(key, value, value_type, category, description, updated_at) "
                "VALUES ('FORWARD_ID', '-1001234567890', 'string', 'telegram', '', 'test')"
            )
        failed = {
            item.name
            for item in evaluate_database(self.database, "https://other.example.test")
            if not item.ok
        }
        self.assertIn("security_runtime_config", failed)
        self.assertIn("public_origin", failed)

    def test_preserved_compromised_database_value_fails(self):
        fingerprint = hashlib.sha256(
            "0123456789abcdef0123456789abcdef".encode("utf-8")
        ).hexdigest()
        with patch.dict(
            "security_validation.PRESERVED_COMPROMISED_VALUE_HASHES",
            {"API_HASH": frozenset({fingerprint})},
        ):
            failed = {
                item.name
                for item in evaluate_database(
                    self.database, "https://files.example.test"
                )
                if not item.ok
            }
        self.assertIn("preserved_compromised_credentials_absent", failed)

    def test_hardened_stopped_container_passes(self):
        document = {
            "Image": "sha256:test-image",
            "State": {"Status": "created", "Running": False},
            "Config": {
                "User": "10001:10001",
                "Env": [
                    "MISTRELAY_TRUSTED_PROXY_CIDRS=172.25.0.1/32",
                    "MISTRELAY_ALLOW_LEGACY_YAML_BOOTSTRAP=0",
                ],
                "Healthcheck": {"Test": [
                    "CMD",
                    "python3",
                    "-c",
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=5).read()",
                ]},
            },
            "HostConfig": {
                "ReadonlyRootfs": True,
                "Privileged": False,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Init": True,
                "NetworkMode": "mistrelay-dev_default",
                "PortBindings": {"8080/tcp": [{"HostIp": "127.0.0.1"}]},
                "Memory": 2 * 1024**3,
                "NanoCpus": 2_000_000_000,
                "PidsLimit": 512,
                "RestartPolicy": {"Name": "no"},
            },
            "Mounts": [
                {"Type": "bind", "RW": True, "Source": "/srv/mistrelay/db", "Destination": "/app/db"},
                {"Type": "bind", "RW": True, "Source": "/srv/mistrelay/downloads", "Destination": "/data/downloads"},
                {"Type": "bind", "RW": True, "Source": "/srv/mistrelay/cache", "Destination": "/app/cache/thumbnails"},
            ],
            "NetworkSettings": {"Networks": {"mistrelay-dev_default": {}}},
        }
        network = {
            "Internal": False,
            "IPAM": {"Config": [{"Subnet": "172.25.0.0/16", "Gateway": "172.25.0.1"}]},
        }
        expected_sources = {
            "/app/db": "/srv/mistrelay/db",
            "/data/downloads": "/srv/mistrelay/downloads",
            "/app/cache/thumbnails": "/srv/mistrelay/cache",
        }
        with patch("activation_preflight._docker_inspect", return_value=document), patch(
            "activation_preflight._docker_image_id", return_value="sha256:test-image"
        ), patch(
            "activation_preflight._container_source_matches", return_value=True
        ), patch(
            "activation_preflight._docker_network_inspect", return_value=network
        ):
            checks = evaluate_container(
                "mistrelay",
                "mistrelay:test",
                source_root=self.root,
                expected_mount_sources=expected_sources,
            )
        self.assertEqual([item.name for item in checks if not item.ok], [])

    def test_public_container_bind_is_rejected(self):
        document = {
            "Image": "sha256:test-image",
            "State": {"Status": "created", "Running": False},
            "Config": {
                "User": "10001:10001",
                "Env": ["MISTRELAY_TRUSTED_PROXY_CIDRS=172.25.0.1/32"],
                "Healthcheck": {"Test": [
                    "CMD",
                    "python3",
                    "-c",
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=5).read()",
                ]},
            },
            "HostConfig": {
                "ReadonlyRootfs": True,
                "Privileged": False,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Init": True,
                "NetworkMode": "host",
                "PortBindings": {"8080/tcp": [{"HostIp": "0.0.0.0"}]},
                "Memory": 2 * 1024**3,
                "NanoCpus": 2_000_000_000,
                "PidsLimit": 512,
                "RestartPolicy": {"Name": "no"},
            },
            "Mounts": [
                {"Type": "bind", "RW": True, "Source": "/srv/mistrelay/db", "Destination": "/app/db"},
                {"Type": "bind", "RW": True, "Source": "/srv/mistrelay/downloads", "Destination": "/data/downloads"},
                {"Type": "bind", "RW": True, "Source": "/srv/mistrelay/cache", "Destination": "/app/cache/thumbnails"},
            ],
            "NetworkSettings": {"Networks": {"mistrelay-dev_default": {}}},
        }
        network = {
            "Internal": False,
            "IPAM": {"Config": [{"Subnet": "172.25.0.0/16", "Gateway": "172.25.0.1"}]},
        }
        with patch("activation_preflight._docker_inspect", return_value=document), patch(
            "activation_preflight._docker_image_id", return_value="sha256:test-image"
        ), patch(
            "activation_preflight._container_source_matches", return_value=True
        ), patch(
            "activation_preflight._docker_network_inspect", return_value=network
        ):
            failed = {
                item.name
                for item in evaluate_container(
                    "mistrelay", "mistrelay:test", source_root=self.root
                )
                if not item.ok
            }
        self.assertIn("container_network", failed)


if __name__ == "__main__":
    unittest.main()
