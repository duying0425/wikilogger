"""内存版飞书知识库，模拟 wiki / docx / drive 接口行为（含分页与权限过滤空页）。"""
import threading
from collections import Counter

from feishu import FeishuApiError, SizeExceededError


def text_block(bid, parent, content, btype=2, children=None, link=None):
    key = {2: "text", 3: "heading1", 4: "heading2", 12: "bullet", 13: "ordered",
           15: "quote", 17: "todo"}.get(btype, "text")
    style = {"link": {"url": link}} if link else {}
    b = {"block_id": bid, "parent_id": parent, "block_type": btype,
         key: {"elements": [{"text_run": {"content": content, "text_element_style": style}}]}}
    if children:
        b["children"] = children
    return b


def simple_doc(title, paragraphs=(), images=(), extra_blocks=()):
    """构造一篇 docx 的 blocks：page → 段落 / 图片 / 额外块。"""
    blocks = []
    children = []
    for i, p in enumerate(paragraphs):
        bid = f"p{i}"
        children.append(bid)
        if isinstance(p, dict):
            p = dict(p, block_id=bid, parent_id="root")
            blocks.append(p)
        else:
            blocks.append(text_block(bid, "root", p))
    for i, tok in enumerate(images):
        bid = f"img{i}"
        children.append(bid)
        blocks.append({"block_id": bid, "parent_id": "root", "block_type": 27, "image": {"token": tok}})
    for b in extra_blocks:
        children.append(b["block_id"])
        blocks.append(b)
    page = {"block_id": "root", "block_type": 1, "children": children,
            "page": {"elements": [{"text_run": {"content": title}}]}}
    return [page] + blocks


class FakeWiki:
    """一个知识空间：nodes 为 {node_token: node}，按 children 顺序组织。"""

    def __init__(self, space_id="7000000000000000001", name="测试知识库"):
        self.space_id = space_id
        self.name = name
        self.nodes = {}
        self.order = []  # 插入顺序（决定同级顺序）
        self.docs = {}  # obj_token -> blocks
        self.media = {}  # token -> bytes
        self.hidden = set()  # 无权限节点：列表中被过滤
        self.list_errors = set()  # 列这些父节点时报错
        self.export_fail = {}  # obj_token -> FeishuApiError
        self.page_size = 2
        self.empty_pages = False  # 模拟「空页 + has_more」
        self.fatal = False

    def add(self, token, title, parent="", obj_type="docx", obj_token=None, edit_time=1700000000,
            node_type="origin", origin=None, blocks=None):
        obj_token = obj_token or ("obj_" + token)
        self.nodes[token] = {
            "space_id": self.space_id, "node_token": token, "obj_token": obj_token,
            "obj_type": obj_type, "parent_node_token": parent, "node_type": node_type,
            "origin_node_token": origin or "", "title": title, "has_child": False,
            "obj_edit_time": str(edit_time), "obj_create_time": "1690000000",
        }
        self.order.append(token)
        if obj_type == "docx" and node_type == "origin":
            self.docs[obj_token] = blocks or simple_doc(title, [f"{title} 的正文"])
        self._refresh_has_child()
        return self.nodes[token]

    def remove(self, token):
        for t in [t for t, n in self.nodes.items() if n["parent_node_token"] == token]:
            self.remove(t)
        self.nodes.pop(token, None)
        self.order.remove(token)
        self._refresh_has_child()

    def move(self, token, new_parent):
        self.nodes[token]["parent_node_token"] = new_parent
        self._refresh_has_child()

    def edit(self, token, title=None, blocks=None, bump=100):
        n = self.nodes[token]
        n["obj_edit_time"] = str(int(n["obj_edit_time"]) + bump)
        if title:
            n["title"] = title
        if blocks is not None:
            self.docs[n["obj_token"]] = blocks

    def _refresh_has_child(self):
        parents = {n["parent_node_token"] for n in self.nodes.values()}
        for t, n in self.nodes.items():
            n["has_child"] = t in parents and n["node_type"] != "shortcut"

    def children_of(self, parent):
        return [self.nodes[t] for t in self.order if self.nodes[t]["parent_node_token"] == (parent or "")]


class FakeClient:
    def __init__(self, wiki):
        self.wiki = wiki
        self.calls = Counter()
        self.lock = threading.Lock()

    def _count(self, name):
        with self.lock:
            self.calls[name] += 1
        if self.wiki.fatal:
            raise FeishuApiError("refresh token has been used", code=20073)

    # wiki
    def list_spaces(self):
        self._count("list_spaces")
        return [{"space_id": self.wiki.space_id, "name": self.wiki.name, "description": "",
                 "space_type": "team", "visibility": "private"}]

    def get_space(self, space_id):
        self._count("get_space")
        if space_id == "my_library":
            return {"space_id": "7999", "name": "我的文档库", "space_type": "my_library"}
        if space_id != self.wiki.space_id:
            raise FeishuApiError("not found", code=131005)
        return {"space_id": self.wiki.space_id, "name": self.wiki.name, "description": "desc",
                "space_type": "team", "visibility": "private"}

    def get_node(self, token, obj_type="wiki"):
        self._count("get_node")
        n = self.wiki.nodes.get(token)
        if not n:
            raise FeishuApiError("not found", code=131005)
        return dict(n)

    def list_nodes_page(self, space_id, parent_node_token=None, page_token=None, page_size=50):
        self._count("list_nodes_page")
        parent = parent_node_token or ""
        if parent in self.wiki.list_errors:
            raise FeishuApiError("rpc fail", code=131001)
        kids = self.wiki.children_of(parent)
        if self.wiki.empty_pages and page_token is None and kids:
            # 模拟权限过滤：首页为空但 has_more=true，必须继续翻页
            return {"items": [], "has_more": True, "page_token": "e0"}
        ps = self.wiki.page_size
        start = int(str(page_token or "0").lstrip("e"))
        chunk = kids[start:start + ps]
        has_more = start + ps < len(kids)
        items = [dict(n) for n in chunk if n["node_token"] not in self.wiki.hidden]
        return {"items": items, "has_more": has_more, "page_token": str(start + ps) if has_more else ""}

    # docx
    def get_docx_blocks(self, doc_token):
        self._count("get_docx_blocks")
        if doc_token not in self.wiki.docs:
            raise FeishuApiError("forbidden", code=1770032, http_status=403)
        return [dict(b) for b in self.wiki.docs[doc_token]]

    # drive
    def download_media(self, file_token, max_size_mb=None):
        self._count("download_media")
        data = self.wiki.media.get(file_token, b"\x89PNG fake " + file_token.encode())
        if data == b"TOO_BIG":
            raise SizeExceededError("60.0MB 超过上限 50MB")
        return data, "image/png", ""

    def download_drive_file(self, file_token, max_size_mb=None):
        self._count("download_drive_file")
        return b"file-bytes", "application/pdf", "原始文件.pdf"

    def export_file(self, obj_token, obj_type, file_extension, max_size_mb=None, timeout=180):
        self._count("export_file")
        if obj_token in self.wiki.export_fail:
            raise self.wiki.export_fail[obj_token]
        return b"xlsx-bytes", f"{obj_token}.{file_extension}"
