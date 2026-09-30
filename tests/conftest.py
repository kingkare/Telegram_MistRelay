"""
Pytest 运行期全局沙箱与数据安全守护钩子 (Test Sandbox & Data Safety Guard)
========================================================================
确保任何自动化测试在运行期间默认操作于完全隔离的临时 SQLite 数据库，
彻底杜绝直接连接、篡改或清空生产数据库 (/root/MistRelay-dev/db/downloads.db)。
"""

import os
import sys
import tempfile
import pytest

_repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_dir not in sys.path:
    sys.path.insert(0, _repo_dir)

import db


@pytest.fixture(autouse=True, scope="session")
def auto_sandbox_test_database():
    """
    Session-level auto-sandbox for pytest:
    分配临时沙箱数据库并注入环境变量，兜底所有未显式隔离的测试用例。
    """
    orig_path = db.DB_PATH
    orig_env = os.environ.get("MISTRELAY_DB_PATH")

    temp_db = tempfile.NamedTemporaryFile(suffix="_pytest_sandbox.db", delete=False)
    temp_db.close()

    os.environ["MISTRELAY_DB_PATH"] = temp_db.name
    os.environ["MISTRELAY_TEST_MODE"] = "1"
    db.DB_PATH = temp_db.name
    db.init_db()

    yield temp_db.name

    db.DB_PATH = orig_path
    if orig_env is None:
        os.environ.pop("MISTRELAY_DB_PATH", None)
    else:
        os.environ["MISTRELAY_DB_PATH"] = orig_env
    os.environ.pop("MISTRELAY_TEST_MODE", None)

    if os.path.exists(temp_db.name):
        try:
            os.remove(temp_db.name)
        except OSError:
            pass
