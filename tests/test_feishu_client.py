"""FeishuClient 与真实接口约定的对接测试（mock requests）。"""
import json
import time

import pytest

import feishu
from feishu import FeishuApiError, FeishuClient, SizeExceededError, decode_link_url


class Resp:
    def __init__(self, status=200, body=None, headers=None, content=b""):
        self.status_code = status
        self._body = body
        self.headers = headers or ({"content-type": "application/json; charset=utf-8"} if body is not None else {})
        self.content = content
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(feishu.time, "sleep", lambda s: None)
    return FeishuClient("tok", "rtok", time.time() + 7200, time.time() + 86400, 1)


def test_retry_on_docx_rate_limit(client, monkeypatch):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None, stream=False):
        calls.append(params)
        if len(calls) == 1:
            return Resp(400, {"code": 99991400, "msg": "request trigger frequency limit"})
        return Resp(200, {"code": 0, "data": {"items": [{"block_id": "root"}], "has_more": False}})

    monkeypatch.setattr(feishu.requests, "get", fake_get)
    assert client.get_docx_blocks("doc") == [{"block_id": "root"}]
    assert len(calls) == 2 and calls[0]["document_revision_id"] == -1


def test_list_nodes_params_and_error(client, monkeypatch):
    seen = {}

    def fake_get(url, headers=None, params=None, timeout=None, stream=False):
        seen["url"], seen["params"] = url, params
        return Resp(400, {"code": 131006, "msg": "permission denied"})

    monkeypatch.setattr(feishu.requests, "get", fake_get)
    with pytest.raises(FeishuApiError) as ei:
        client.list_nodes_page("123", "parentTok", "pt")
    assert ei.value.code == 131006 and ei.value.is_permission_error
    assert seen["url"].endswith("/wiki/v2/spaces/123/nodes")
    assert seen["params"] == {"page_size": 50, "parent_node_token": "parentTok", "page_token": "pt"}


def test_list_spaces_continues_through_empty_page(client, monkeypatch):
    pages = [
        {"code": 0, "data": {"items": [], "has_more": True, "page_token": "p1"}},
        {"code": 0, "data": {"items": [{"space_id": "1"}], "has_more": True, "page_token": "p2"}},
        {"code": 0, "data": {"items": [{"space_id": "2"}], "has_more": False}},
    ]
    monkeypatch.setattr(feishu.requests, "get", lambda *a, **k: Resp(200, pages.pop(0)))
    assert [s["space_id"] for s in client.list_spaces()] == ["1", "2"]


def test_download_size_limit(client, monkeypatch):
    monkeypatch.setattr(feishu.requests, "get", lambda *a, **k: Resp(
        200, None, {"Content-Length": str(3 * 1024 * 1024), "Content-Type": "image/png"}, b"x"))
    with pytest.raises(SizeExceededError):
        client.download_media("t", max_size_mb=1)


def test_download_error_json(client, monkeypatch):
    monkeypatch.setattr(feishu.requests, "get", lambda *a, **k: Resp(403, {"code": 1061004, "msg": "forbidden"}))
    with pytest.raises(FeishuApiError) as ei:
        client.download_drive_file("f")
    assert ei.value.is_permission_error


def test_export_flow(client, monkeypatch):
    state = {"polls": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        assert url.endswith("/drive/v1/export_tasks")
        assert json == {"file_extension": "xlsx", "token": "sht", "type": "sheet"}
        return Resp(200, {"code": 0, "data": {"ticket": "tk"}})

    def fake_get(url, headers=None, params=None, timeout=None, stream=False):
        if url.endswith("/export_tasks/tk"):
            state["polls"] += 1
            status = 2 if state["polls"] == 1 else 0
            return Resp(200, {"code": 0, "data": {"result": {
                "job_status": status, "file_token": "ft", "file_name": "销售数据", "file_size": 10}}})
        assert url.endswith("/export_tasks/file/ft/download")
        return Resp(200, None, {"Content-Type": "application/octet-stream"}, b"XLSX")

    monkeypatch.setattr(feishu.requests, "post", fake_post)
    monkeypatch.setattr(feishu.requests, "get", fake_get)
    content, name = client.export_file("sht", "sheet", "xlsx")
    assert content == b"XLSX" and name == "销售数据.xlsx" and state["polls"] == 2


def test_decode_link_and_disposition():
    assert decode_link_url("https%3A%2F%2Fa.com%2Fb%3Fc%3D1") == "https://a.com/b?c=1"
    assert decode_link_url("https://a.com/b%20c") == "https://a.com/b%20c"
    assert feishu._filename_from_disposition("attachment; filename*=UTF-8''%E5%90%88%E5%90%8C.pdf") == "合同.pdf"
    raw = "合同.pdf".encode("utf-8").decode("latin-1")
    assert feishu._filename_from_disposition(f'attachment; filename="{raw}"') == "合同.pdf"


def test_rate_limiter_paces_calls(monkeypatch):
    lim = feishu.RateLimiter(rate=10, per=1, burst=1)
    t0 = time.monotonic()
    for _ in range(4):
        lim.acquire()
    assert time.monotonic() - t0 >= 0.25
