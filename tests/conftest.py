import os
import shutil
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="wikilogger_test_")
Config.DB_PATH = os.path.join(_tmp, "test.db")
Config.LOCAL_CACHE_DIR = os.path.join(_tmp, "cache")
# 测试时放开限速
Config.WIKI_API_PER_MIN = 100000
Config.DOCX_API_PER_SEC = 100000
Config.DRIVE_DOWNLOAD_PER_SEC = 100000
Config.EXPORT_API_PER_MIN = 100000
Config.FEISHU_WEB_BASE = "https://example.feishu.cn"

import feishu  # noqa: E402
import models  # noqa: E402

feishu.reset_limiters()
models.init_db()


@pytest.fixture
def fresh_env():
    """每个测试使用独立的数据库与缓存目录。"""
    d = tempfile.mkdtemp(prefix="wl_case_")
    old = (Config.DB_PATH, Config.LOCAL_CACHE_DIR)
    Config.DB_PATH = os.path.join(d, "t.db")
    Config.LOCAL_CACHE_DIR = os.path.join(d, "cache")
    models.init_db()
    yield d
    Config.DB_PATH, Config.LOCAL_CACHE_DIR = old
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def space_row(fresh_env):
    user = models.get_or_create_user("ou_test", "测试用户")
    ref = models.add_space(user["id"], "7000000000000000001", "测试知识库", "测试知识库", "", "team",
                           "private", "测试知识库_7000000000000000001")
    return models.get_space(user["id"], ref)
