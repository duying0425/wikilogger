"""飞书新版文档（docx）Block → Markdown 转换。

在 chatlogger 的转换器基础上扩展，面向「整库镜像」：
- 超链接 / @文档 指向本知识库内节点时，改写为本地相对链接（带 "wiki:<token>" 标记，节点移动后可重新计算）
- 图片、文件块下载到本地，由回调决定保存位置
- 支持更多块类型（公式、链接预览、子页面列表、同步块、议程等）
"""
import re

from config import Config
from feishu import decode_link_url

CODE_LANG_MAP = {
    1: "", 2: "abap", 3: "ada", 4: "apache", 5: "apex", 6: "asm", 7: "bash",
    8: "csharp", 9: "cpp", 10: "c", 11: "cobol", 12: "css", 13: "coffeescript",
    14: "d", 15: "dart", 16: "delphi", 17: "django", 18: "dockerfile",
    19: "erlang", 20: "fortran", 22: "go", 23: "groovy", 24: "html",
    26: "http", 27: "haskell", 28: "json", 29: "java", 30: "javascript",
    31: "julia", 32: "kotlin", 33: "latex", 34: "lisp", 36: "lua", 37: "matlab",
    38: "makefile", 39: "markdown", 40: "nginx", 41: "objectivec", 43: "php",
    44: "perl", 46: "powershell", 48: "protobuf", 49: "python", 50: "r",
    52: "ruby", 53: "rust", 56: "sql", 57: "scala", 59: "shell", 60: "swift",
    61: "thrift", 62: "typescript", 63: "vbscript", 64: "vb", 65: "xml",
    66: "yaml", 67: "cmake", 68: "diff",
}

BLOCK_TYPE_NAME = {
    1: "page", 2: "text", 3: "heading1", 4: "heading2", 5: "heading3",
    6: "heading4", 7: "heading5", 8: "heading6", 9: "heading7",
    10: "heading8", 11: "heading9", 12: "bullet", 13: "ordered", 14: "code",
    15: "quote", 16: "equation", 17: "todo", 18: "bitable", 19: "callout",
    20: "chat_card", 21: "diagram", 22: "divider", 23: "file", 24: "grid",
    25: "grid_column", 26: "iframe", 27: "image", 28: "isv", 29: "mindnote",
    30: "sheet", 31: "table", 32: "table_cell", 33: "view",
    34: "quote_container", 35: "task", 36: "okr", 37: "okr_objective",
    38: "okr_key_result", 39: "okr_progress", 40: "add_ons", 41: "jira_issue",
    42: "wiki_catalog", 43: "board", 44: "agenda", 45: "agenda_item",
    46: "agenda_item_title", 47: "agenda_item_content", 48: "link_preview",
    49: "source_synced", 50: "reference_synced", 51: "sub_page_list",
    52: "ai_template",
}

TEXT_BLOCK_TYPES = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17)
LIST_BLOCK_TYPES = (12, 13, 17)
# 仅作为容器、透传渲染子块的块
PASSTHROUGH_TYPES = (24, 25, 33, 44, 45, 47, 49)

# 飞书云文档链接：/wiki/<token>、/docx/<token>、/docs/<token>、/sheets/<token>、/base/<token>
FEISHU_DOC_URL_RE = re.compile(
    r"https?://[A-Za-z0-9.-]*(?:feishu\.cn|larksuite\.com|feishu-pre\.cn)/"
    r"(wiki|docx|docs|sheets|base|mindnotes|file|slides)/([A-Za-z0-9]+)", re.IGNORECASE)


INDENT = "    "  # 嵌套列表缩进 4 空格：有序列表「1. 」后的子项需要 ≥3 空格才算嵌套


class _ListItem(str):
    """列表项行：相邻列表项之间用单换行连接（紧凑列表），其余块之间空一行。"""


def join_lines(lines):
    out = ""
    prev = None
    for l in lines:
        if not l:
            continue
        if prev is not None:
            out += "\n" if isinstance(prev, _ListItem) and isinstance(l, _ListItem) else "\n\n"
        out += l
        prev = l
    return out


def escape_link_text(text):
    return (text or "").replace("[", "\\[").replace("]", "\\]")


def _escape_table_cell(text):
    return text.replace("|", "\\|").replace("\n", "<br>")


class DocxConverter:
    """把 docx Block 列表转换为 Markdown。

    回调（均可省略）：
    - image_saver(token) -> Markdown 链接目标（如 "<../_assets/x/img.png>"）或 None
    - file_saver(token, name) -> Markdown 链接目标 或 None
    - doc_link_resolver(url=None, token=None) -> Markdown 链接目标（含标题标记）或 None
      用于把指向本知识库节点的链接改写为本地链接
    - children_provider() -> [(title, 链接目标)]，渲染「子页面列表 / 知识库子目录」块
    """

    def __init__(self, blocks, image_saver=None, file_saver=None, doc_link_resolver=None,
                 children_provider=None, max_blocks=None):
        self.blocks_by_id = {b.get("block_id"): b for b in blocks if isinstance(b, dict)}
        self.image_saver = image_saver or (lambda token: None)
        self.file_saver = file_saver or (lambda token, name: None)
        self.doc_link_resolver = doc_link_resolver or (lambda url=None, token=None: None)
        self.children_provider = children_provider or (lambda: [])
        self.max_blocks = max_blocks or Config.MAX_DOC_BLOCKS
        self.rendered_count = 0
        self.truncated = False
        self._visiting = set()  # 防御异常数据中的循环 children
        self.image_count = 0
        self.file_count = 0

    # ---------- 行内 ----------

    def _link(self, text, url):
        dest = self.doc_link_resolver(url=url) if url else None
        if dest:
            return f"[{escape_link_text(text)}]({dest})"
        return f"[{escape_link_text(text)}]({_safe_url(url)})"

    def inline(self, text_obj):
        if not isinstance(text_obj, dict):
            return ""
        parts = []
        for elem in text_obj.get("elements") or []:
            if not isinstance(elem, dict):
                continue
            run = elem.get("text_run")
            if isinstance(run, dict):
                content = run.get("content") or ""
                if not content:
                    continue
                style = run.get("text_element_style") or {}
                link = style.get("link") or {}
                url = decode_link_url(link.get("url", "")) if isinstance(link, dict) else ""
                if style.get("inline_code"):
                    content = f"`{content}`"
                else:
                    # 首尾空白不能包在强调标记内，否则 Markdown 不识别
                    lead = content[:len(content) - len(content.lstrip())]
                    trail = content[len(content.rstrip()):]
                    core = content.strip()
                    if core:
                        if style.get("bold"):
                            core = f"**{core}**"
                        if style.get("italic"):
                            core = f"*{core}*"
                        if style.get("strikethrough"):
                            core = f"~~{core}~~"
                        if style.get("underline"):
                            core = f"<u>{core}</u>"
                    content = lead + core + trail
                parts.append(self._link(content, url) if url else content)
                continue
            md = elem.get("mention_doc")
            if isinstance(md, dict):
                title = md.get("title") or "文档"
                url = decode_link_url(md.get("url", ""))
                dest = self.doc_link_resolver(url=url, token=md.get("token"))
                if dest:
                    parts.append(f"[📄 {escape_link_text(title)}]({dest})")
                elif url:
                    parts.append(f"[📄 {escape_link_text(title)}]({_safe_url(url)})")
                else:
                    parts.append(f"📄 {title}")
                continue
            if isinstance(elem.get("mention_user"), dict):
                parts.append("@成员")
            elif isinstance(elem.get("equation"), dict):
                eq = (elem["equation"].get("content") or "").strip()
                if eq:
                    parts.append(f"${eq}$")
            elif isinstance(elem.get("link_preview"), dict):
                lp = elem["link_preview"]
                url = decode_link_url(lp.get("url", ""))
                parts.append(self._link(lp.get("title") or url, url) if url else "")
            elif elem.get("reminder") is not None:
                parts.append("⏰[提醒]")
            elif isinstance(elem.get("file"), dict):
                f = elem["file"]
                dest = self.file_saver(f.get("file_token") or f.get("token"), f.get("name") or "附件")
                parts.append(f"[📎 附件]({dest})" if dest else "[📎 附件]")
        return "".join(parts)

    # ---------- 块 ----------

    def convert(self):
        root = None
        for b in self.blocks_by_id.values():
            if b.get("block_type") == 1 and not b.get("parent_id"):
                root = b
                break
        if root is None:
            root = next(iter(self.blocks_by_id.values()), None)
        if root is None:
            return ""
        md = join_lines(self._render_children(root, indent=0))
        if self.truncated:
            md += f"\n\n> ⚠️ 文档过长（超过 {self.max_blocks} 个内容块），已截断"
        return md

    def _render_children(self, block, indent):
        bid = block.get("block_id")
        if bid in self._visiting:
            return []
        self._visiting.add(bid)
        try:
            return self._render_children_inner(block, indent)
        finally:
            self._visiting.discard(bid)

    def _render_children_inner(self, block, indent):
        lines = []
        children = block.get("children") or []
        counter = 0
        prev_type = None
        for child_id in children:
            if self.rendered_count >= self.max_blocks:
                self.truncated = True
                break
            child = self.blocks_by_id.get(child_id)
            if child is None:
                continue
            btype = child.get("block_type")
            if btype == 13:
                counter = counter + 1 if prev_type == 13 else 1
            prev_type = btype
            line = self._render_block(child, indent, counter)
            # 文本类块的子块：列表 / 待办缩进一层（嵌套列表），其他文本块按同级紧随
            if child.get("children") and btype in TEXT_BLOCK_TYPES and btype != 14:
                nested_indent = indent + 1 if btype in LIST_BLOCK_TYPES else indent
                nested = self._render_children(child, nested_indent)
                if nested:
                    if btype in LIST_BLOCK_TYPES:
                        line = (line or (INDENT * indent + "-")) + "\n" + "\n".join(nested)
                    else:
                        line = join_lines([line] + nested)
            if line:
                lines.append(_ListItem(line) if btype in LIST_BLOCK_TYPES else line)
        return lines

    def _render_block(self, block, indent, order_num):
        self.rendered_count += 1
        btype = block.get("block_type")
        pad = INDENT * indent

        if btype in TEXT_BLOCK_TYPES:
            key = BLOCK_TYPE_NAME[btype]
            text_obj = block.get(key) or {}
            if btype == 14:
                style = text_obj.get("style") or {}
                lang = CODE_LANG_MAP.get(style.get("language"), "")
                code = "".join((e.get("text_run") or {}).get("content") or ""
                               for e in text_obj.get("elements") or [] if isinstance(e, dict))
                fence = "````" if "```" in code else "```"
                body = f"{fence}{lang}\n{code.rstrip()}\n{fence}"
                # 列表中的代码块需要整体缩进才属于该列表项
                return "\n".join(pad + l if l else l for l in body.split("\n")) if pad else body
            inline = self.inline(text_obj).strip()
            if btype == 2:
                return (pad + inline) if inline else None
            if 3 <= btype <= 11:
                level = min(btype - 2, 6)
                return f"{'#' * level} {inline}" if inline else None
            if btype == 12:
                return f"{pad}- {inline}" if inline else f"{pad}-"
            if btype == 13:
                return f"{pad}{order_num or 1}. {inline}"
            if btype == 15:
                return f"{pad}> {inline}" if inline else None
            if btype == 17:
                done = (text_obj.get("style") or {}).get("done", False)
                return f"{pad}- [{'x' if done else ' '}] {inline}"
            return inline or None

        if btype == 16:
            inline = self.inline(block.get("equation") or {}).strip()
            return f"$$\n{inline.strip('$')}\n$$" if inline else None

        if btype == 22:
            return "---"

        if btype == 27:
            token = (block.get("image") or {}).get("token", "")
            dest = self.image_saver(token) if token else None
            if dest:
                self.image_count += 1
                return f"{pad}![图片]({dest})"
            return f"{pad}[图片]"

        if btype == 23:
            f = block.get("file") or {}
            name = f.get("name") or "附件"
            dest = self.file_saver(f.get("token"), name) if f.get("token") else None
            if dest:
                self.file_count += 1
                return f"{pad}[📎 {escape_link_text(name)}]({dest})"
            return f"{pad}[📎 {name}]"

        if btype == 31:
            return self._render_table(block)

        if btype == 26:
            iframe = block.get("iframe") or {}
            url = decode_link_url((iframe.get("component") or {}).get("url") or iframe.get("url") or "")
            return f"[🔗 嵌入内容]({_safe_url(url)})" if url else "[嵌入内容]"

        if btype == 48:
            url = decode_link_url((block.get("link_preview") or {}).get("url", ""))
            return self._link(url, url) if url else None

        if btype in (19, 34):  # 高亮块 / 引用容器
            inner = self._render_children(block, 0)
            if not inner:
                return None
            body = join_lines(inner)
            return "\n".join(pad + "> " + l if l else pad + ">" for l in body.split("\n"))

        if btype == 46:  # 议程项标题
            inline = self.inline(block.get("agenda_item_title") or {}).strip()
            return f"**{inline}**" if inline else None

        if btype in PASSTHROUGH_TYPES:
            inner = self._render_children(block, indent)
            return join_lines(inner) if inner else None

        if btype in (42, 51):  # 知识库子目录 / 子页面列表：用本地树渲染
            items = self.children_provider()
            if not items:
                return "[📚 子页面列表]"
            return "\n".join(f"{pad}- [{escape_link_text(t)}]({d})" for t, d in items)

        placeholders = {
            18: "[📊 多维表格]", 29: "[🧠 思维笔记]", 30: "[📊 电子表格]", 21: "[🎨 流程图]",
            43: "[🎨 画板]", 50: "[🔁 同步块引用]", 20: "[💬 会话卡片]", 35: "[✅ 任务]",
        }
        if btype in placeholders:
            return pad + placeholders[btype]
        if btype in (28, 36, 37, 38, 39, 40, 41, 52):
            return f"{pad}[{BLOCK_TYPE_NAME.get(btype, '未知')} 内容块]"

        for key in ("text", "heading1", "heading2", "heading3"):
            if isinstance(block.get(key), dict):
                return self.inline(block[key]).strip() or None
        return f"[不支持的内容块: {BLOCK_TYPE_NAME.get(btype, btype)}]"

    def _render_table(self, block):
        table = block.get("table") or {}
        prop = table.get("property") or {}
        row_size = int(prop.get("row_size") or 0)
        col_size = int(prop.get("column_size") or 0)
        cell_ids = table.get("cells") or prop.get("cells") or block.get("children") or []
        if not row_size or not col_size or len(cell_ids) < row_size * col_size:
            return "[表格]"
        rows = []
        for r in range(row_size):
            rows.append([self._cell_text(self.blocks_by_id.get(cell_ids[r * col_size + c]))
                         for c in range(col_size)])
        header = rows[0]
        body = rows[1:] or [[""] * col_size]
        out = ["| " + " | ".join(_escape_table_cell(x) for x in header) + " |",
               "| " + " | ".join(["---"] * col_size) + " |"]
        for row in body:
            out.append("| " + " | ".join(_escape_table_cell(x) for x in row) + " |")
        return "\n".join(out)

    def _cell_text(self, cell_block):
        """单元格内子块渲染为单行（多块以换行拼接，表格中转为 <br>）。"""
        if not isinstance(cell_block, dict):
            return ""
        lines = self._render_children(cell_block, 0)
        return "\n".join(l.replace("\n", " ") for l in lines).strip()


def _safe_url(url):
    """链接目标：阻止 javascript: 等危险协议；含空格时用尖括号包裹。"""
    url = (url or "").strip()
    if re.match(r"^\s*(javascript|vbscript|data):", url, re.IGNORECASE):
        return "#"
    if re.search(r"[\s()<>]", url):
        return "<" + url.replace("<", "%3C").replace(">", "%3E") + ">"
    return url


def parse_feishu_url(url):
    """解析飞书云文档链接，返回 (kind, token) 或 (None, None)。"""
    if not url:
        return None, None
    m = FEISHU_DOC_URL_RE.search(url)
    if not m:
        return None, None
    return m.group(1).lower(), m.group(2)
