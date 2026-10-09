from feishu_doc import DocxConverter, parse_feishu_url
from fake_feishu import text_block


def page(children):
    return {"block_id": "root", "block_type": 1, "children": children}


def conv(blocks, **kw):
    return DocxConverter(blocks, **kw).convert()


def test_encoded_link_is_decoded():
    md = conv([page(["a"]), text_block("a", "root", "官网", link="https%3A%2F%2Fwww.example.com%2Fa%3Fb%3D1")])
    assert md == "[官网](https://www.example.com/a?b=1)"


def test_nested_lists_and_ordered_numbering():
    blocks = [page(["o1", "o2", "t", "o3"]),
              text_block("o1", "root", "一", 13, children=["b1"]),
              text_block("b1", "o1", "子项", 12),
              text_block("o2", "root", "二", 13),
              text_block("t", "root", "插入段落"),
              text_block("o3", "root", "重新开始", 13)]
    md = conv(blocks)
    assert md == "1. 一\n    - 子项\n2. 二\n\n插入段落\n\n1. 重新开始"


def test_bullet_with_empty_text_and_children_does_not_crash():
    # chatlogger 里这种情况会触发未定义变量 pad
    blocks = [page(["b"]), {"block_id": "b", "parent_id": "root", "block_type": 12,
                            "bullet": {"elements": []}, "children": ["c"]},
              text_block("c", "b", "子", 12)]
    assert conv(blocks) == "-\n    - 子"


def test_heading_levels_capped():
    blocks = [page(["h"]), {"block_id": "h", "parent_id": "root", "block_type": 9,
                            "heading7": {"elements": [{"text_run": {"content": "七级"}}]}}]
    assert conv(blocks) == "###### 七级"


def test_table_and_callout():
    cells = [f"c{i}" for i in range(4)]
    blocks = [page(["tbl", "co"]),
              {"block_id": "tbl", "parent_id": "root", "block_type": 31, "children": cells,
               "table": {"cells": cells, "property": {"row_size": 2, "column_size": 2}}}]
    for i, cid in enumerate(cells):
        blocks.append({"block_id": cid, "parent_id": "tbl", "block_type": 32, "children": [f"t{i}"]})
        blocks.append(text_block(f"t{i}", cid, f"v|{i}"))
    blocks.append({"block_id": "co", "parent_id": "root", "block_type": 19, "children": ["l1", "l2"]})
    blocks.append(text_block("l1", "co", "第一行"))
    blocks.append(text_block("l2", "co", "第二行"))
    md = conv(blocks)
    assert "| v\\|0 | v\\|1 |\n| --- | --- |\n| v\\|2 | v\\|3 |" in md
    assert "> 第一行\n>\n> 第二行" in md


def test_mention_doc_resolved_to_local():
    blocks = [page(["a"]), {"block_id": "a", "parent_id": "root", "block_type": 2, "text": {"elements": [
        {"mention_doc": {"token": "objX", "obj_type": 22, "title": "架构说明",
                         "url": "https%3A%2F%2Fx.feishu.cn%2Fdocx%2FobjX"}}]}}]

    def resolver(url=None, token=None):
        return '<sub/架构说明.md> "wiki:nodeX"' if token == "objX" else None

    assert conv(blocks, doc_link_resolver=resolver) == '[📄 架构说明](<sub/架构说明.md> "wiki:nodeX")'
    assert conv(blocks) == "[📄 架构说明](https://x.feishu.cn/docx/objX)"


def test_code_block_and_styles():
    blocks = [page(["c", "s"]),
              {"block_id": "c", "parent_id": "root", "block_type": 14,
               "code": {"style": {"language": 49}, "elements": [{"text_run": {"content": "print(1)\n"}}]}},
              {"block_id": "s", "parent_id": "root", "block_type": 2, "text": {"elements": [
                  {"text_run": {"content": " 加粗 ", "text_element_style": {"bold": True}}},
                  {"text_run": {"content": "代码", "text_element_style": {"inline_code": True}}}]}}]
    assert conv(blocks) == "```python\nprint(1)\n```\n\n**加粗** `代码`"


def test_javascript_link_neutralized():
    md = conv([page(["a"]), text_block("a", "root", "x", link="javascript:alert(1)")])
    assert md == "[x](#)"


def test_parse_feishu_url():
    assert parse_feishu_url("https://abc.feishu.cn/wiki/TokenAbc123?from=x") == ("wiki", "TokenAbc123")
    assert parse_feishu_url("https://abc.larksuite.com/docx/D0c") == ("docx", "D0c")
    assert parse_feishu_url("https://example.com/wiki/x") == (None, None)


def test_malformed_blocks_do_not_crash():
    blocks = [page(["i", "c", "loop"]),
              {"block_id": "i", "parent_id": "root", "block_type": 26, "iframe": {"component": None}},
              {"block_id": "c", "parent_id": "root", "block_type": 14,
               "code": {"elements": [{"text_run": {"content": None}}]}},
              {"block_id": "loop", "parent_id": "root", "block_type": 24, "children": ["loop2"]},
              {"block_id": "loop2", "parent_id": "loop", "block_type": 25, "children": ["loop"]}]
    md = conv(blocks)
    assert "[嵌入内容]" in md and "```" in md


def test_code_block_inside_list_is_indented():
    blocks = [page(["b"]), {"block_id": "b", "parent_id": "root", "block_type": 12,
                            "bullet": {"elements": [{"text_run": {"content": "步骤"}}]}, "children": ["c"]},
              {"block_id": "c", "parent_id": "b", "block_type": 14,
               "code": {"style": {"language": 7}, "elements": [{"text_run": {"content": "ls -la"}}]}}]
    assert conv(blocks) == "- 步骤\n    ```bash\n    ls -la\n    ```"
