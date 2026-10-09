import json
import os

import pytest

import local_store
import models
import wiki_sync
from config import Config
from fake_feishu import FakeClient, FakeWiki, simple_doc, text_block
from feishu import FeishuApiError


def build_wiki():
    w = FakeWiki()
    w.add("A", "产品")
    w.add("A1", "需求文档", parent="A", blocks=simple_doc("需求文档", [
        "见设计：",
        text_block("lnk", "root", "设计稿链接", link="https%3A%2F%2Fexample.feishu.cn%2Fwiki%2FA2"),
    ], images=["imgtok1"]))
    w.add("A2", "设计", parent="A")
    w.add("B", "研发")
    w.add("B1", "接口说明", parent="B")
    w.add("T", "数据表", obj_type="sheet")
    return w


def root_of(space):
    return local_store.space_dir(space["cache_dir"])


def read(space, rel):
    return local_store.read_text(root_of(space), rel)


def run(client, space, force=False):
    return wiki_sync.sync_space(client, models.get_space_by_ref(space["id"]), force=force)


def test_initial_sync_builds_tree(space_row):
    w = build_wiki()
    c = FakeClient(w)
    s = run(c, space_row)
    assert s["nodes"] == 6 and s["fetched"] == 6 and s["failed"] == 0 and s["added"] == 6
    root = root_of(space_row)
    for rel in ("产品.md", "产品/需求文档.md", "产品/设计.md", "研发.md", "研发/接口说明.md", "数据表.md",
                "README.md", "_manifest.json"):
        assert os.path.isfile(os.path.join(root, *rel.split("/"))), rel
    doc = read(space_row, "产品/需求文档.md")
    assert doc.startswith("---\n") and '"node_token": ' not in doc  # front matter 为 yaml 键值
    assert 'node_token: "A1"' in doc
    assert "# 需求文档" in doc
    # 编码过的超链接指向本库节点 → 改写为本地相对链接（带 wiki 标记）
    assert '[设计稿链接](<设计.md> "wiki:A2")' in doc
    # 图片下载到 _assets/{obj_token}/ 并用相对路径引用
    assert "![图片](<../_assets/obj_A1/imgtok1.png>)" in doc
    assert os.path.isfile(os.path.join(root, "_assets", "obj_A1", "imgtok1.png"))
    # 表格类导出 xlsx
    sheet = read(space_row, "数据表.md")
    assert "obj_T.xlsx" in sheet and os.path.isfile(os.path.join(root, "_assets", "obj_T", "obj_T.xlsx"))
    readme = read(space_row, "README.md")
    assert "- 📄 [产品](<产品.md>)" in readme and "  - 📄 [需求文档](<产品/需求文档.md>)" in readme
    manifest = json.loads(read(space_row, "_manifest.json"))
    assert len(manifest["nodes"]) == 6


def test_second_sync_is_incremental(space_row):
    w = build_wiki()
    c = FakeClient(w)
    run(c, space_row)
    c.calls.clear()
    s = run(c, space_row)
    assert s["fetched"] == 0 and s["unchanged"] == 6
    assert c.calls["get_docx_blocks"] == 0 and c.calls["export_file"] == 0
    # 编辑一篇文档：只重拉这一篇；图片 token 未变，不重复下载
    w.edit("A1")
    c.calls.clear()
    s = run(c, space_row)
    assert s["fetched"] == 1 and s["updated"] == 1
    assert c.calls["get_docx_blocks"] == 1 and c.calls["download_media"] == 0


def test_move_relocates_without_refetch_and_relinks(space_row):
    w = build_wiki()
    c = FakeClient(w)
    run(c, space_row)
    before = models.get_node(space_row["id"], "A2")["synced_at"]
    w.move("A2", "B")  # 设计 从「产品」移到「研发」下
    c.calls.clear()
    s = run(c, space_row)
    # 被移动的文档本身不重拉；新旧父页面的子页面列表变了，各重写一次
    assert s["moved"] == 1 and s["fetched"] == 2 and c.calls["get_docx_blocks"] == 2
    assert models.get_node(space_row["id"], "A2")["synced_at"] == before
    root = root_of(space_row)
    assert os.path.isfile(os.path.join(root, "研发", "设计.md"))
    assert not os.path.exists(os.path.join(root, "产品", "设计.md"))
    # 引用它的文档链接被重算
    assert '[设计稿链接](<../研发/设计.md> "wiki:A2")' in read(space_row, "产品/需求文档.md")


def test_move_parent_with_children_and_asset_prefix(space_row):
    w = build_wiki()
    c = FakeClient(w)
    run(c, space_row)
    w.move("A", "B")  # 整个「产品」子树挪到「研发」下，深度 +1
    s = run(c, space_row)
    assert s["moved"] == 3 and s["fetched"] == 1  # 只有新父页面「研发」因子页面变化重写
    doc = read(space_row, "研发/产品/需求文档.md")
    assert "![图片](<../../_assets/obj_A1/imgtok1.png>)" in doc
    assert not os.path.exists(os.path.join(root_of(space_row), "产品"))  # 空目录被清理


def test_rename_refetches_and_moves(space_row):
    w = build_wiki()
    c = FakeClient(w)
    run(c, space_row)
    w.edit("B", title="研发中心", bump=0)
    s = run(c, space_row)
    assert s["moved"] == 2  # 研发.md 与 研发/接口说明.md
    assert s["fetched"] == 1  # 标题变化需要重写页头
    assert "# 研发中心" in read(space_row, "研发中心.md")
    assert read(space_row, "研发中心/接口说明.md") is not None


def test_delete_moves_to_deleted(space_row):
    w = build_wiki()
    c = FakeClient(w)
    run(c, space_row)
    w.remove("A1")
    s = run(c, space_row)
    assert s["deleted"] == 1
    root = root_of(space_row)
    assert not os.path.exists(os.path.join(root, "产品", "需求文档.md"))
    assert os.path.isfile(os.path.join(root, "_deleted", "产品", "需求文档.md"))
    assert os.path.isfile(os.path.join(root, "_deleted", "_assets", "obj_A1", "imgtok1.png"))
    assert models.get_node(space_row["id"], "A1") is None


def test_traverse_error_skips_deletion(space_row):
    w = build_wiki()
    c = FakeClient(w)
    run(c, space_row)
    w.list_errors.add("A")  # 列「产品」子节点失败 → 需求文档、设计看起来「消失」了
    s = run(c, space_row)
    assert s["traverse_errors"] == 1 and s["deleted"] == 0 and s["skipped_delete"]
    assert read(space_row, "产品/需求文档.md") is not None


def test_duplicate_titles_get_suffix(space_row):
    w = build_wiki()
    w.add("D1", "会议纪要", parent="B")
    w.add("D2", "会议纪要", parent="B")
    run(FakeClient(w), space_row)
    root = root_of(space_row)
    assert os.path.isfile(os.path.join(root, "研发", "会议纪要~D1.md"))
    assert os.path.isfile(os.path.join(root, "研发", "会议纪要~D2.md"))


def test_export_failure_is_warning_and_not_retried(space_row):
    w = build_wiki()
    w.export_fail["obj_T"] = FeishuApiError("no permission", code=1069902)
    c = FakeClient(w)
    s = run(c, space_row)
    assert s["warned"] == 1 and s["failed"] == 0
    assert "导出失败" in read(space_row, "数据表.md")
    c.calls.clear()
    run(c, space_row)
    assert c.calls["export_file"] == 0  # 未编辑不重试，避免浪费配额


def test_doc_fetch_error_retried_next_time(space_row):
    w = build_wiki()
    lost = w.docs.pop("obj_B1")
    c = FakeClient(w)
    s = run(c, space_row)
    assert s["failed"] == 1
    assert "拉取失败" in read(space_row, "研发/接口说明.md")
    w.docs["obj_B1"] = lost
    s = run(c, space_row)
    assert s["fetched"] == 1 and s["failed"] == 0
    assert "接口说明 的正文" in read(space_row, "研发/接口说明.md")


def test_force_refetches_everything(space_row):
    w = build_wiki()
    c = FakeClient(w)
    run(c, space_row)
    s = run(c, space_row, force=True)
    assert s["fetched"] == 6


def test_shortcut_and_file_nodes(space_row):
    w = build_wiki()
    w.add("S", "设计（快捷方式）", node_type="shortcut", origin="A2", obj_type="docx", obj_token="obj_A2")
    w.add("F", "合同.pdf", obj_type="file")
    run(FakeClient(w), space_row)
    sc = read(space_row, "设计（快捷方式）.md")
    assert '(<产品/设计.md> "wiki:A2")' in sc
    f = read(space_row, "合同.pdf.md")
    assert "原始文件.pdf" in f


def test_fatal_error_aborts(space_row):
    w = build_wiki()
    c = FakeClient(w)
    w.fatal = True
    with pytest.raises(wiki_sync.FatalSyncError):
        run(c, space_row)


def test_image_too_big_is_noted(space_row):
    w = build_wiki()
    w.media["imgtok1"] = b"TOO_BIG"
    s = run(FakeClient(w), space_row)
    assert s["warned"] == 1
    doc = read(space_row, "产品/需求文档.md")
    assert "[图片]" in doc and "超过上限" in doc


def test_compute_paths_reserved_and_sanitize():
    nodes = [
        {"node_token": "x00001", "parent_node_token": "", "title": "_assets"},
        {"node_token": "x00002", "parent_node_token": "", "title": "a/b:c*?"},
        {"node_token": "x00003", "parent_node_token": "", "title": "CON"},
        {"node_token": "x00004", "parent_node_token": "", "title": "   "},
        {"node_token": "x00005", "parent_node_token": "", "title": "Readme"},
    ]
    p = local_store.compute_paths(nodes)
    assert p["x00001"] == "_assets~x00001.md"
    assert p["x00002"] == "a_b_c_.md"
    assert p["x00003"] == "CON_.md"
    assert p["x00004"] == "未命名.md"
    assert p["x00005"] == "Readme~x00005.md"


def test_resolve_inside_blocks_traversal(tmp_path):
    root = str(tmp_path)
    assert local_store.resolve_inside(root, "../etc/passwd") is None
    assert local_store.resolve_inside(root, "a/../../x") is None
    assert local_store.resolve_inside(root, "a/b.md").endswith(os.path.join("a", "b.md"))


def test_cancel_keeps_progress_and_resumes(space_row):
    import threading
    w = build_wiki()
    c = FakeClient(w)
    ev = threading.Event()
    orig = c.get_docx_blocks

    def cancel_after_first(token):
        ev.set()  # 第一篇拉取时触发停止
        return orig(token)

    c.get_docx_blocks = cancel_after_first
    Config.FETCH_CONCURRENCY, old = 1, Config.FETCH_CONCURRENCY
    try:
        with pytest.raises(wiki_sync.SyncCancelled):
            wiki_sync.sync_space(c, models.get_space_by_ref(space_row["id"]), cancel_event=ev)
    finally:
        Config.FETCH_CONCURRENCY = old
    assert read(space_row, "README.md") is not None
    done = [n for n in models.get_nodes(space_row["id"]) if n["synced_sig"]]
    assert len(done) == 1
    c.get_docx_blocks = orig
    s = run(c, space_row)
    assert s["fetched"] == 5 and s["unchanged"] == 1


# ===== 评审发现问题的回归测试 =====

def test_partial_traversal_does_not_overwrite_unlisted_files(space_row):
    w = build_wiki()
    w.add("C1", "草稿", parent="B")
    w.add("C2", "定稿", parent="B")
    c = FakeClient(w)
    run(c, space_row)
    w.page_size = 1
    w.hidden.add("C2")  # 本次列不出 C2（模拟权限 / 翻页失败）
    w.list_errors.add("A")  # 让遍历不完整，跳过删除
    w.edit("C1", title="定稿")  # C1 改名成与 C2 同名
    run(c, space_row)
    root = root_of(space_row)
    assert "定稿 的正文" in read(space_row, "研发/定稿.md")  # C2 原文件未被覆盖
    assert models.get_node(space_row["id"], "C1")["rel_path"] != "研发/定稿.md"
    w.hidden.clear(); w.list_errors.clear()
    run(c, space_row)
    p1 = models.get_node(space_row["id"], "C1")["rel_path"]
    p2 = models.get_node(space_row["id"], "C2")["rel_path"]
    assert p1 != p2
    assert 'node_token: "C1"' in read(space_row, p1) and 'node_token: "C2"' in read(space_row, p2)


def test_deleted_then_recreated_same_title_keeps_old_version(space_row):
    w = build_wiki()
    c = FakeClient(w)
    run(c, space_row)
    w.remove("B1")
    w.add("B1new", "接口说明", parent="B")
    run(c, space_row)
    assert 'node_token: "B1"' in read(space_row, "_deleted/研发/接口说明.md")
    assert 'node_token: "B1new"' in read(space_row, "研发/接口说明.md")


def test_md_suffix_title_does_not_collide_with_dir(space_row):
    w = build_wiki()
    w.add("X", "notes")
    w.add("Y", "notes.md")
    w.add("Y1", "child", parent="Y")
    w.add("R", "README.md")
    w.add("R1", "child", parent="R")
    s = run(FakeClient(w), space_row)
    assert s["failed"] == 0
    assert read(space_row, "notes.md") is not None
    assert read(space_row, "notes_md/child.md") is not None
    assert read(space_row, "README.md").startswith("# ")  # 索引未被覆盖


def test_hash_in_title_and_link(space_row):
    w = build_wiki()
    w.add("CS", "C# 指南", parent="B")
    run(FakeClient(w), space_row)
    assert read(space_row, "研发/C＃ 指南.md") is not None


def test_transient_image_failure_is_retried(space_row):
    w = build_wiki()
    c = FakeClient(w)
    orig = c.download_media
    c.download_media = lambda token, max_size_mb=None: (_ for _ in ()).throw(ConnectionError("reset"))
    s = run(c, space_row)
    assert s["failed"] == 1
    c.download_media = orig
    s = run(c, space_row)
    assert s["failed"] == 0 and "![图片]" in read(space_row, "产品/需求文档.md")


def test_stub_child_list_refreshes(space_row):
    w = build_wiki()
    c = FakeClient(w)
    run(c, space_row)
    w.add("T1", "明细", parent="T")
    run(c, space_row)
    assert "明细" in read(space_row, "数据表.md")


def test_cache_dir_not_reused(fresh_env):
    os.makedirs(os.path.join(Config.LOCAL_CACHE_DIR, "库_1"))
    name = local_store.choose_cache_dir_name("库", "1", lambda n: False)
    assert name == "库_1_2"
