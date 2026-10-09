import time

import pytest

import models
from fake_feishu import FakeClient
from test_sync import build_wiki


@pytest.fixture
def ctx(fresh_env, monkeypatch):
    import app as app_module
    wiki = build_wiki()
    client = FakeClient(wiki)
    monkeypatch.setattr(app_module, "make_client", lambda user: client if user else None)
    app_module.app.config["TESTING"] = True
    user = models.get_or_create_user("ou_app", "测试")
    tc = app_module.app.test_client()
    with tc.session_transaction() as s:
        s["user_id"] = user["id"]
    return tc, wiki, client


def wait_done(tc, ref, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        d = tc.get(f"/api/spaces/{ref}/status").get_json()
        if not (d.get("progress") or {}).get("running"):
            return d
        time.sleep(0.05)
    raise AssertionError("sync timeout")


def test_full_flow(ctx):
    tc, wiki, client = ctx
    # 用知识库内页面链接添加 → 解析出 space_id
    r = tc.post("/api/spaces", json={"input": "https://x.feishu.cn/wiki/A1?from=from_copylink"})
    assert r.status_code == 200, r.get_json()
    sp = r.get_json()["space"]
    assert sp["space_id"] == wiki.space_id and sp["name"] == "测试知识库"
    assert tc.post("/api/spaces", json={"input": wiki.space_id}).status_code == 409

    ref = sp["id"]
    assert tc.post(f"/api/spaces/{ref}/sync", json={}).get_json()["started"]
    d = wait_done(tc, ref)
    assert d["progress"]["stage"] == "done", d
    assert d["node_count"] == 6 and d["has_cache"] and d["last_sync_status"] == "ok"

    assert wiki.space_id in tc.get("/").get_data(as_text=True)
    assert tc.get(f"/space/{ref}").status_code == 200
    tree = tc.get(f"/api/spaces/{ref}/tree").get_json()["nodes"]
    assert [n["path"] for n in tree][:2] == ["产品.md", "产品/需求文档.md"]

    md = tc.get(f"/space/{ref}/files/产品/需求文档.md")
    assert md.status_code == 200 and "需求文档" in md.get_data(as_text=True)
    img = tc.get(f"/space/{ref}/files/_assets/obj_A1/imgtok1.png")
    assert img.status_code == 200 and "attachment" not in img.headers.get("Content-Disposition", "")
    xlsx = tc.get(f"/space/{ref}/files/_assets/obj_T/obj_T.xlsx")
    assert "attachment" in xlsx.headers["Content-Disposition"]
    assert tc.get(f"/space/{ref}/files/../../t.db").status_code == 404
    z = tc.get(f"/space/{ref}/download")
    assert z.status_code == 200 and z.data[:2] == b"PK"

    # 增量：无变化
    tc.post(f"/api/spaces/{ref}/sync", json={})
    d = wait_done(tc, ref)
    assert d["summary"]["fetched"] == 0

    r = tc.post(f"/api/spaces/{ref}/rename", json={"name": "别名"})
    assert r.get_json()["space"]["name"] == "别名"

    r = tc.delete(f"/api/spaces/{ref}?delete_cache=1")
    assert r.get_json()["cache_removed"] is True
    assert tc.get("/api/spaces").get_json()["spaces"] == []


def test_user_spaces_and_settings_url(ctx):
    tc, wiki, client = ctx
    d = tc.get("/api/user_spaces").get_json()
    assert d["spaces"][0]["space_type"] == "my_library"
    assert any(s["space_id"] == wiki.space_id for s in d["spaces"])
    r = tc.post("/api/spaces", json={"input": f"https://x.feishu.cn/wiki/settings/{wiki.space_id}"})
    assert r.status_code == 200
    assert tc.post("/api/spaces", json={"input": "随便写"}).status_code == 400


def test_auth_failure_reported(ctx):
    tc, wiki, client = ctx
    ref = tc.post("/api/spaces", json={"input": wiki.space_id}).get_json()["space"]["id"]
    wiki.fatal = True
    tc.post(f"/api/spaces/{ref}/sync", json={})
    d = wait_done(tc, ref)
    assert d["progress"]["stage"] == "error" and d["progress"]["error_type"] == "auth"


def test_requires_login(fresh_env):
    import app as app_module
    tc = app_module.app.test_client()
    assert tc.get("/api/spaces").status_code == 401
    assert "飞书登录" in tc.get("/").get_data(as_text=True)


def test_callback_error_not_reflected_as_html(fresh_env):
    import app as app_module
    r = app_module.app.test_client().get("/auth/callback?error=<script>alert(1)</script>")
    assert r.status_code == 400 and r.headers["Content-Type"].startswith("text/plain")


def test_progress_not_stuck_when_db_write_fails(ctx, monkeypatch):
    tc, wiki, client = ctx
    ref = tc.post("/api/spaces", json={"input": wiki.space_id}).get_json()["space"]["id"]

    def boom(*a, **k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(models, "update_space_sync", boom)
    tc.post(f"/api/spaces/{ref}/sync", json={})
    d = wait_done(tc, ref)
    assert d["progress"]["running"] is False and "locked" in d["progress"]["error"]


def test_space_home_url(ctx):
    tc, wiki, client = ctx
    r = tc.post("/api/spaces", json={"input": f"https://x.feishu.cn/wiki/space/{wiki.space_id}"})
    assert r.status_code == 200


def test_oauth_state_checked(fresh_env, monkeypatch):
    import app as app_module
    from feishu import FeishuClient
    monkeypatch.setattr(FeishuClient, "exchange_code_for_token", staticmethod(lambda code: {
        "access_token": "a", "refresh_token": "r", "expires_in": 7200,
        "refresh_token_expires_in": 86400, "open_id": "ou_s", "name": "S"}))
    tc = app_module.app.test_client()
    page = tc.get("/").get_data(as_text=True)
    import re
    state = re.search(r"state=([A-Za-z0-9_-]+)", page).group(1)
    assert tc.get("/auth/callback?auth_code=x&state=forged").status_code == 400
    tc.get("/")
    page = tc.get("/").get_data(as_text=True)
    state = re.search(r"state=([A-Za-z0-9_-]+)", page).group(1)
    r = tc.get(f"/auth/callback?auth_code=x&state={state}")
    assert r.status_code == 302
    assert tc.get("/api/spaces").status_code == 200
