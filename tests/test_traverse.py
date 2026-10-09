import pytest

from fake_feishu import FakeClient, FakeWiki
from feishu import FeishuApiError
from wiki_sync import traverse_space


def build():
    w = FakeWiki()
    w.add("A", "产品")
    w.add("A1", "需求", parent="A")
    w.add("A2", "设计", parent="A")
    w.add("A3", "评审", parent="A")
    w.add("A2a", "交互稿", parent="A2")
    w.add("B", "研发")
    w.add("C", "运维")
    return w


def test_preorder_depth_and_pagination():
    w = build()
    w.page_size = 2  # 强制多页
    c = FakeClient(w)
    nodes, errors = traverse_space(c, w.space_id)
    assert errors == []
    assert [n["node_token"] for n in nodes] == ["A", "A1", "A2", "A2a", "A3", "B", "C"]
    assert [n["depth"] for n in nodes] == [0, 1, 1, 2, 1, 0, 0]
    assert [n["sort_index"] for n in nodes] == list(range(7))
    # 根 2 页 + A 2 页 + A2 1 页 = 5 次（叶子节点 has_child=false 不调用）
    assert c.calls["list_nodes_page"] == 5


def test_empty_page_with_has_more_keeps_paging():
    """权限过滤导致首页为空但 has_more=true 时不能当作结束。"""
    w = build()
    w.empty_pages = True
    nodes, errors = traverse_space(FakeClient(w), w.space_id)
    assert len(nodes) == 7 and errors == []


def test_hidden_nodes_are_skipped():
    w = build()
    w.hidden.add("A2")
    nodes, _ = traverse_space(FakeClient(w), w.space_id)
    tokens = [n["node_token"] for n in nodes]
    assert "A2" not in tokens and "A2a" not in tokens


def test_shortcut_not_expanded():
    w = build()
    w.add("S", "快捷方式", node_type="shortcut", origin="A")
    c = FakeClient(w)
    nodes, _ = traverse_space(c, w.space_id)
    s = [n for n in nodes if n["node_token"] == "S"][0]
    assert s["node_type"] == "shortcut"


def test_child_list_error_is_recorded_and_traversal_continues():
    w = build()
    w.list_errors.add("A")
    nodes, errors = traverse_space(FakeClient(w), w.space_id)
    assert [e["parent"] for e in errors] == ["A"]
    assert [n["node_token"] for n in nodes] == ["A", "B", "C"]


def test_root_error_raises():
    w = build()
    w.list_errors.add("")
    with pytest.raises(FeishuApiError):
        traverse_space(FakeClient(w), w.space_id)


def test_max_nodes_guard():
    w = build()
    nodes, errors = traverse_space(FakeClient(w), w.space_id, max_nodes=3)
    assert errors and "上限" in errors[-1]["error"]
    assert len(nodes) <= 4
