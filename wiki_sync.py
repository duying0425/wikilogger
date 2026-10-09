"""知识库整库遍历与增量同步引擎（与 Flask 解耦，便于测试）。

流程：
1. 遍历：从根开始按 parent_node_token 逐层分页列出子节点（飞书没有一次拉整库的接口）
2. 规划：按节点标题计算本地目录树路径；与上次同步结果对比
3. 删除：飞书侧消失的节点移入 _deleted/（遍历有失败时跳过，避免误删）
4. 移动：只是位置 / 父节点变化的文档直接在本地挪文件，不重新拉取
5. 拉取：新增或 obj_edit_time 变化的节点重新拉取（docx 转 Markdown；表格类导出 xlsx）
6. 收尾：重算文档间相对链接，生成 README.md 目录索引与 _manifest.json
"""
import hashlib
import json
import os
import threading
import time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import local_store
import models
from config import Config
from feishu import FeishuApiError, SizeExceededError
from feishu_doc import DocxConverter, escape_link_text, parse_feishu_url

# 转换逻辑有不兼容升级时修改此版本号，下次同步会重新拉取全部文档
CONVERTER_VERSION = "2"

OBJ_TYPE_LABEL = {
    "docx": ("📄", "文档"), "doc": ("📃", "旧版文档"), "sheet": ("📊", "电子表格"),
    "bitable": ("🗂️", "多维表格"), "mindnote": ("🧠", "思维笔记"), "file": ("📎", "文件"),
    "slides": ("🖼️", "幻灯片"),
}
EXPORT_EXT = {"sheet": "xlsx", "bitable": "xlsx", "doc": "docx"}
TZ = timezone(timedelta(hours=8))


class SyncCancelled(Exception):
    pass


class FatalSyncError(Exception):
    """需要中止整个同步的错误（如 token 失效）"""


def fmt_ts(ts):
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return ""
    if ts > 1e11:
        ts //= 1000
    return datetime.fromtimestamp(ts, tz=TZ).strftime("%Y-%m-%d %H:%M")


def node_url(node_token, web_base=None):
    return f"{(web_base or Config.FEISHU_WEB_BASE).rstrip('/')}/wiki/{node_token}"


def node_signature(n, extra=""):
    """决定是否需要重新拉取：内容编辑时间、标题、类型，以及 extra（子页面列表 / 快捷方式目标标题）。"""
    return "|".join(str(n.get(k) or "") for k in
                    ("obj_type", "node_type", "obj_edit_time", "title", "origin_node_token")) \
        + "|" + extra + "|v" + CONVERTER_VERSION


def _signature_extras(nodes):
    """页面里会渲染子页面列表（占位页、子页面列表块），子节点增删改名后需要重写。"""
    kids = {}
    titles = {n["node_token"]: n.get("title") or "" for n in nodes}
    for n in nodes:
        kids.setdefault(n.get("parent_node_token") or "", []).append(f"{n['node_token']}:{n.get('title') or ''}")
    extras = {}
    for n in nodes:
        tok = n["node_token"]
        e = hashlib.md5("|".join(kids[tok]).encode("utf-8")).hexdigest()[:10] if tok in kids else ""
        if n.get("node_type") == "shortcut":
            e += ">" + titles.get(n.get("origin_node_token") or "", "")
        extras[tok] = e
    return extras


def _is_permanent(err):
    """不值得每次重试的失败：超大小、无权限。其他（网络、限流耗尽、5xx）下次同步重试。"""
    return isinstance(err, SizeExceededError) or (isinstance(err, FeishuApiError) and err.is_permission_error)


def _is_fatal(err):
    return isinstance(err, FeishuApiError) and err.code in (20073, 99991668, 99991677, 99991661)


# ===== 1. 遍历 =====

def traverse_space(client, space_id, on_progress=None, max_nodes=None, cancel_event=None):
    """遍历整个知识空间，返回 (先序节点列表, 列目录失败列表)。

    - 每个有子节点的节点都要调用一次（或多页）子节点列表接口
    - 权限过滤会产生「空页但 has_more=true」，必须继续翻页
    - 快捷方式节点不展开（子节点属于源节点）；用 visited 防环
    """
    max_nodes = max_nodes or Config.MAX_NODES
    children = {}
    errors = []
    seen = set()
    queue = deque([""])
    listed = 0
    while queue:
        if cancel_event is not None and cancel_event.is_set():
            raise SyncCancelled()
        parent = queue.popleft()
        items = []
        page_token = None
        seen_pages = set()
        try:
            while True:
                d = client.list_nodes_page(space_id, parent or None, page_token)
                items.extend(d.get("items") or [])
                page_token = d.get("page_token")
                if not d.get("has_more") or not page_token or page_token in seen_pages:
                    break
                seen_pages.add(page_token)
        except Exception as e:
            if _is_fatal(e) or not parent:
                raise
            errors.append({"parent": parent, "error": str(e)})
        listed += 1
        kept = []
        for it in items:
            tok = it.get("node_token")
            if not tok or tok in seen:
                continue
            seen.add(tok)
            it = dict(it)
            it["parent_node_token"] = parent
            kept.append(it)
            if it.get("has_child") and it.get("node_type") != "shortcut":
                queue.append(tok)
        children[parent] = kept
        if on_progress:
            on_progress(listed, len(seen), len(queue))
        if len(seen) >= max_nodes:
            errors.append({"parent": "", "error": f"节点数超过上限 {max_nodes}，后续节点未遍历"})
            break

    ordered = []
    stack = [(n, 0) for n in reversed(children.get("", []))]
    while stack:
        n, depth = stack.pop()
        n["depth"] = depth
        n["sort_index"] = len(ordered)
        ordered.append(n)
        for c in reversed(children.get(n["node_token"], [])):
            stack.append((c, depth + 1))
    return ordered, errors


# ===== 2. 单节点渲染 =====

class SyncContext:
    def __init__(self, client, space, root, nodes, paths, web_base=None):
        self.client = client
        self.space = space
        self.root = root
        self.paths = paths
        self.web_base = web_base or Config.FEISHU_WEB_BASE
        self.nodes = {n["node_token"]: n for n in nodes}
        self.children = {}
        for n in nodes:
            self.children.setdefault(n.get("parent_node_token") or "", []).append(n)
        # 文档实际 token → 节点 token（快捷方式不参与，指向源节点）
        self.obj_to_node = {}
        for n in nodes:
            if n.get("obj_token") and n.get("node_type") != "shortcut":
                self.obj_to_node.setdefault(n["obj_token"], n["node_token"])
        self.now = fmt_ts(time.time())

    def resolve_token(self, token):
        if token in self.nodes:
            return token
        return self.obj_to_node.get(token)

    def link_resolver(self, rel_path):
        def resolve(url=None, token=None):
            target = None
            if token:
                target = self.resolve_token(token)
            if not target and url:
                kind, tok = parse_feishu_url(url)
                if tok:
                    target = self.resolve_token(tok)
            if target and target in self.paths:
                return local_store.wiki_link_dest(rel_path, self.paths[target], target)
            return None
        return resolve


def _front_matter(n, ctx):
    fields = [
        ("title", n.get("title") or ""),
        ("node_token", n["node_token"]),
        ("obj_type", n.get("obj_type") or ""),
        ("source", node_url(n["node_token"], ctx.web_base)),
        ("edit_time", fmt_ts(n.get("obj_edit_time"))),
        ("synced_at", ctx.now),
    ]
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fields] + ["---", ""]
    return "\n".join(lines)


def _header(n, ctx, kind_label=None):
    title = n.get("title") or "未命名"
    url = node_url(n["node_token"], ctx.web_base)
    bits = []
    if kind_label:
        bits.append(kind_label)
    bits.append(f"[在飞书中打开]({url})")
    if n.get("obj_edit_time"):
        bits.append(f"最后编辑 {fmt_ts(n['obj_edit_time'])}")
    bits.append(f"同步于 {ctx.now}")
    return f"{_front_matter(n, ctx)}# {title}\n\n> {' · '.join(bits)}\n"


def _ext_from_ctype(ctype, default="png"):
    ctype = (ctype or "").lower()
    for key, ext in (("png", "png"), ("jpeg", "jpg"), ("jpg", "jpg"), ("gif", "gif"),
                     ("webp", "webp"), ("bmp", "bmp"), ("svg", "svg")):
        if key in ctype:
            return ext
    return default


def render_docx(ctx, n, rel):
    obj = n["obj_token"]
    prefix = local_store.asset_prefix(rel)
    used = set()
    notes = []
    retry = []

    def image_saver(token):
        if not Config.CACHE_DOC_IMAGES:
            return None
        name = local_store.find_asset(ctx.root, obj, token)
        if not name:
            try:
                content, ctype, _ = ctx.client.download_media(token)
            except SizeExceededError as e:
                notes.append(f"图片未下载（{e}）")
                return None
            except Exception as e:
                if _is_fatal(e):
                    raise
                notes.append(f"图片下载失败：{e}")
                if not _is_permanent(e):
                    retry.append(token)
                return None
            name = local_store.save_asset(ctx.root, obj, f"{token}.{_ext_from_ctype(ctype)}", content)
        used.add(name)
        return f"<{prefix}{local_store.ASSETS_DIR}/{obj}/{name}>"

    def file_saver(token, fname):
        if not Config.CACHE_DOC_FILES or not token:
            return None
        name = local_store.find_asset(ctx.root, obj, token + "_")
        if not name:
            try:
                content, _, _ = ctx.client.download_media(token)
            except SizeExceededError as e:
                notes.append(f"附件「{fname}」未下载（{e}）")
                return None
            except Exception as e:
                if _is_fatal(e):
                    raise
                notes.append(f"附件「{fname}」下载失败：{e}")
                if not _is_permanent(e):
                    retry.append(token)
                return None
            name = local_store.save_asset(ctx.root, obj, f"{token}_{fname}", content)
        used.add(name)
        return f"<{prefix}{local_store.ASSETS_DIR}/{obj}/{name}>"

    def children_provider():
        return [(c.get("title") or "未命名",
                 local_store.wiki_link_dest(rel, ctx.paths[c["node_token"]], c["node_token"]))
                for c in ctx.children.get(n["node_token"], []) if c["node_token"] in ctx.paths]

    blocks = ctx.client.get_docx_blocks(obj)
    conv = DocxConverter(blocks, image_saver=image_saver, file_saver=file_saver,
                         doc_link_resolver=ctx.link_resolver(rel), children_provider=children_provider)
    body = conv.convert() or "*（空文档）*"
    md = _header(n, ctx) + "\n" + body + "\n"
    if notes:
        md += "\n> ⚠️ " + "；".join(notes[:20]) + ("…" if len(notes) > 20 else "") + "\n"
    local_store.prune_assets(ctx.root, obj, used)
    return md, ("；".join(notes) if notes else None), bool(retry)


def render_stub(ctx, n, rel):
    """非 docx 节点：生成说明页；表格类按配置导出 xlsx，文件节点下载原文件。"""
    obj_type = n.get("obj_type") or ""
    icon, label = OBJ_TYPE_LABEL.get(obj_type, ("📦", obj_type or "未知类型"))
    obj = n.get("obj_token") or ""
    prefix = local_store.asset_prefix(rel)
    lines = []
    warn = None
    retry = False
    saved = None
    try:
        if obj_type in EXPORT_EXT and Config.EXPORT_OFFICE_FILES and obj:
            content, fname = ctx.client.export_file(obj, obj_type, EXPORT_EXT[obj_type])
            saved = local_store.save_asset(ctx.root, obj, fname, content)
        elif obj_type == "file" and Config.DOWNLOAD_WIKI_FILES and obj:
            content, _, fname = ctx.client.download_drive_file(obj)
            saved = local_store.save_asset(ctx.root, obj, fname or (n.get("title") or obj), content)
    except Exception as e:
        if _is_fatal(e):
            raise
        warn = f"{'导出' if obj_type in EXPORT_EXT else '下载'}失败：{e}"
        retry = not _is_permanent(e)
    if saved:
        local_store.prune_assets(ctx.root, obj, {saved})
        lines.append(f"[📎 {escape_link_text(saved)}](<{prefix}{local_store.ASSETS_DIR}/{obj}/{saved}>)")
    elif warn:
        lines.append(f"> ⚠️ {warn}")
    else:
        lines.append(f"*{label}暂不支持转换为 Markdown，请在飞书中查看。*")
    kids = ctx.children.get(n["node_token"], [])
    if kids:
        lines.append("**子页面**\n\n" + "\n".join(
            f"- [{escape_link_text(c.get('title') or '未命名')}]"
            f"({local_store.wiki_link_dest(rel, ctx.paths[c['node_token']], c['node_token'])})"
            for c in kids if c["node_token"] in ctx.paths))
    return _header(n, ctx, f"{icon} {label}") + "\n" + "\n\n".join(lines) + "\n", warn, retry


def render_shortcut(ctx, n, rel):
    origin = n.get("origin_node_token") or ""
    target = ctx.nodes.get(origin)
    title = escape_link_text((target or n).get("title") or "源文档")
    if origin and origin in ctx.paths:
        dest = local_store.wiki_link_dest(rel, ctx.paths[origin], origin)
    elif origin:
        dest = f'<{node_url(origin, ctx.web_base)}> "wiki:{origin}"'
    else:
        dest = node_url(n["node_token"], ctx.web_base)
    note = "" if target else "（源文档不在本知识库，链接到飞书）"
    return _header(n, ctx, "🔗 快捷方式") + f"\n指向：[{title}]({dest}){note}\n", None, False


def sync_node(ctx, n):
    """拉取单个节点并写入本地文件。返回结果 dict（在线程池中执行）。"""
    rel = ctx.paths[n["node_token"]]
    try:
        if n.get("node_type") == "shortcut":
            md, warn, retry = render_shortcut(ctx, n, rel)
            status = "stub"
        elif n.get("obj_type") == "docx":
            md, warn, retry = render_docx(ctx, n, rel)
            status = "ok"
        else:
            md, warn, retry = render_stub(ctx, n, rel)
            status = "stub"
        local_store.write_text(ctx.root, rel, md)
        if retry:
            # 临时性失败（网络 / 限流 / 5xx）：内容已写入，但标记为失败，下次同步重试
            return {"node_token": n["node_token"], "status": "error", "error": warn}
        return {"node_token": n["node_token"], "status": "warn" if warn else status, "error": warn}
    except Exception as e:
        if _is_fatal(e):
            return {"node_token": n["node_token"], "status": "fatal", "error": str(e)}
        if not local_store.exists(ctx.root, rel):
            # 首次拉取失败也写一个占位页，保证目录树完整
            msg = (f"{_header(n, ctx)}\n> ❌ 拉取失败：{e}\n>\n> 下次同步会自动重试。\n")
            try:
                local_store.write_text(ctx.root, rel, msg)
            except Exception:
                pass
        return {"node_token": n["node_token"], "status": "error", "error": str(e)}


# ===== 3. 索引 =====

def build_readme(space, nodes, paths, web_base=None):
    name = space.get("name") or space.get("feishu_name") or space["space_id"]
    docs = sum(1 for n in nodes if n.get("obj_type") == "docx" and n.get("node_type") != "shortcut")
    lines = [f"# {name}", "",
             f"> 飞书知识库本地镜像 · space_id `{space['space_id']}` · 共 {len(nodes)} 个节点"
             f"（{docs} 篇文档）· 同步于 {fmt_ts(time.time())}", ""]
    for n in nodes:
        icon = "🔗" if n.get("node_type") == "shortcut" else OBJ_TYPE_LABEL.get(n.get("obj_type"), ("📦",))[0]
        title = escape_link_text(n.get("title") or "未命名")
        lines.append(f"{'  ' * n.get('depth', 0)}- {icon} [{title}](<{paths[n['node_token']]}>)")
    if not nodes:
        lines.append("*（知识库为空或无可见节点）*")
    return "\n".join(lines) + "\n"


def build_manifest(space, nodes, paths, results):
    return json.dumps({
        "space_id": space["space_id"],
        "name": space.get("name") or space.get("feishu_name"),
        "synced_at": fmt_ts(time.time()),
        "nodes": [{
            "node_token": n["node_token"], "parent_node_token": n.get("parent_node_token") or "",
            "title": n.get("title"), "obj_type": n.get("obj_type"), "obj_token": n.get("obj_token"),
            "node_type": n.get("node_type"), "path": paths[n["node_token"]],
            "edit_time": fmt_ts(n.get("obj_edit_time")),
            "status": (results.get(n["node_token"]) or {}).get("status"),
        } for n in nodes],
    }, ensure_ascii=False, indent=1)


# ===== 4. 编排 =====

def sync_space(client, space, on_progress=None, force=False, cancel_event=None):
    """同步一个知识库。space 为 models 中的 spaces 行（dict）。返回结果摘要 dict。"""
    t0 = time.time()
    progress = on_progress or (lambda *a, **k: None)
    root = local_store.space_dir(space["cache_dir"])
    os.makedirs(root, exist_ok=True)

    # 「我的文档库」按官方约定用 my_library 代替 space_id 调用
    api_space_id = "my_library" if space.get("space_type") == "my_library" else space["space_id"]

    # 刷新知识库真实名称（失败不影响同步）
    try:
        meta = client.get_space(api_space_id)
        if meta.get("name"):
            models.update_space_meta(space["id"], feishu_name=meta.get("name"),
                                     description=meta.get("description"),
                                     space_type=meta.get("space_type"), visibility=meta.get("visibility"))
            space = dict(space, feishu_name=meta.get("name"))
    except Exception as e:
        if _is_fatal(e):
            raise FatalSyncError(str(e))

    # 1. 遍历
    progress("traverse", 0, 0, "正在遍历知识库目录...")

    def _trav(listed, found, pending):
        progress("traverse", listed, listed + pending,
                 f"遍历目录中：已列出 {listed} 个目录，发现 {found} 个节点，待列 {pending} 个")

    try:
        nodes, trav_errors = traverse_space(client, api_space_id, _trav, cancel_event=cancel_event)
    except SyncCancelled:
        raise
    except Exception as e:
        if _is_fatal(e):
            raise FatalSyncError(str(e))
        raise
    local = {n["node_token"]: n for n in models.get_nodes(space["id"])}
    remote_tokens = {n["node_token"] for n in nodes}
    gone = [t for t in local if t not in remote_tokens]
    can_delete = not trav_errors
    # 遍历不完整时：没列出来的旧节点保留原文件，新路径规划要避开它们，链接也继续指向它们
    kept = {} if can_delete else {t: local[t] for t in gone if local[t].get("rel_path")}
    paths = local_store.compute_paths(nodes, reserved={r["rel_path"].lower() for r in kept.values()})
    link_paths = dict({t: r["rel_path"] for t, r in kept.items()}, **paths)
    active_objs = {n.get("obj_token") for n in nodes if n.get("node_type") != "shortcut"}

    # 2. 删除：先于移动 / 拉取执行，确保被删节点的最后一版在路径被复用前移入 _deleted/
    deleted = []
    if gone and can_delete:
        for t in gone:
            old = local[t]
            if old.get("rel_path"):
                obj = old.get("obj_token") if old.get("obj_token") not in active_objs else None
                local_store.retire_file(root, old["rel_path"], obj, keep=Config.KEEP_DELETED)
            deleted.append(t)
        models.delete_nodes(space["id"], deleted)

    # 3. 移动 / 改父节点：本地挪文件即可。
    #    若多个节点记录了同一个旧路径（历史异常），文件归属不可信：不移动，直接重拉
    old_counts = Counter((local[n["node_token"]].get("rel_path") or "").lower()
                         for n in nodes if n["node_token"] in local)
    conflicted = {n["node_token"] for n in nodes if n["node_token"] in local
                  and local[n["node_token"]].get("rel_path")
                  and old_counts[local[n["node_token"]]["rel_path"].lower()] > 1}
    moves = {}
    for n in nodes:
        old = local.get(n["node_token"])
        if n["node_token"] in conflicted:
            continue
        if old and old.get("rel_path") and old["rel_path"] != paths[n["node_token"]] \
                and local_store.exists(root, old["rel_path"]):
            moves[old["rel_path"]] = paths[n["node_token"]]
    if moves:
        progress("move", 0, len(moves), f"本地调整 {len(moves)} 个文档位置...")
        local_store.move_files(root, moves)

    # 4. 拉取有变化的节点
    extras = _signature_extras(nodes)
    to_fetch = []
    added = 0
    for n in nodes:
        old = local.get(n["node_token"])
        sig = node_signature(n, extras.get(n["node_token"], ""))
        n["_sig"] = sig
        if not old:
            added += 1
        if force or not old or old.get("synced_sig") != sig or old.get("status") == "error" \
                or n["node_token"] in conflicted or not local_store.exists(root, paths[n["node_token"]]):
            to_fetch.append(n)

    ctx = SyncContext(client, space, root, nodes, link_paths)
    results = {}
    fatal = None
    total = len(to_fetch)
    progress("fetch", 0, total, f"需要拉取 {total} 个节点（共 {len(nodes)} 个）")
    if to_fetch:
        stop = threading.Event()

        def _run(n):
            if stop.is_set() or (cancel_event is not None and cancel_event.is_set()):
                return {"node_token": n["node_token"], "status": "skipped"}
            return sync_node(ctx, n)

        with ThreadPoolExecutor(max_workers=max(1, Config.FETCH_CONCURRENCY)) as ex:
            futures = [ex.submit(_run, n) for n in to_fetch]
            done = 0
            for f in as_completed(futures):
                r = f.result()
                results[r["node_token"]] = r
                done += 1
                if r["status"] == "fatal" and not fatal:
                    fatal = r["error"]
                    stop.set()
                title = ctx.nodes[r["node_token"]].get("title") or ""
                progress("fetch", done, total, f"拉取中 ({done}/{total})：{title[:40]}")

    # 5. 收尾：链接重算（每次都做，只回写有变化的文件）、索引、状态
    progress("finalize", total, total, "重算文档链接、生成目录索引...")
    local_store.relink_all(root, link_paths, ctx.web_base)
    _write_index(root, space, nodes, paths, results, ctx.web_base)
    local_store.remove_empty_dirs(root)
    _persist(space, nodes, paths, local, results)
    if cancel_event is not None and cancel_event.is_set():
        raise SyncCancelled()
    if fatal:
        raise FatalSyncError(fatal)

    failed = [r for r in results.values() if r["status"] == "error"]
    warned = [r for r in results.values() if r["status"] == "warn"]
    summary = {
        "nodes": len(nodes),
        "docs": sum(1 for n in nodes if n.get("obj_type") == "docx" and n.get("node_type") != "shortcut"),
        "fetched": sum(1 for r in results.values() if r["status"] in ("ok", "stub", "warn")),
        "added": added,
        "updated": sum(1 for n in to_fetch if n["node_token"] in local
                       and results.get(n["node_token"], {}).get("status") in ("ok", "stub", "warn")),
        "moved": len(moves),
        "deleted": len(deleted),
        "failed": len(failed),
        "warned": len(warned),
        "traverse_errors": len(trav_errors),
        "skipped_delete": bool(gone and trav_errors),
        "unchanged": len(nodes) - len(to_fetch),
        "seconds": round(time.time() - t0, 1),
        "force": force,
        "errors": ([{"title": ctx.nodes[r["node_token"]].get("title"), "error": r["error"]}
                    for r in failed + warned][:30]
                   + [{"title": "目录遍历", "error": e["error"]} for e in trav_errors[:10]]),
    }
    return summary


def _write_index(root, space, nodes, paths, results, web_base):
    local_store.write_text(root, local_store.README, build_readme(space, nodes, paths, web_base))
    local_store.write_text(root, local_store.MANIFEST, build_manifest(space, nodes, paths, results))


def _persist(space, nodes, paths, local, results):
    """写回节点状态：本次未拉取成功的节点保留上次的签名，下次继续重试。"""
    rows = []
    now = time.time()
    for n in nodes:
        tok = n["node_token"]
        old = local.get(tok) or {}
        r = results.get(tok)
        row = {
            "node_token": tok, "parent_node_token": n.get("parent_node_token") or "",
            "obj_token": n.get("obj_token"), "obj_type": n.get("obj_type"),
            "node_type": n.get("node_type"), "origin_node_token": n.get("origin_node_token"),
            "title": n.get("title"), "has_child": 1 if n.get("has_child") else 0,
            "depth": n.get("depth", 0), "sort_index": n.get("sort_index", 0),
            "obj_edit_time": str(n.get("obj_edit_time") or ""), "rel_path": paths[tok],
            "synced_sig": old.get("synced_sig"), "status": old.get("status") or "pending",
            "error": old.get("error"), "synced_at": old.get("synced_at"),
        }
        if r and r["status"] in ("ok", "stub", "warn"):
            row.update(synced_sig=n.get("_sig") or node_signature(n), status=r["status"],
                       error=r.get("error"), synced_at=now)
        elif r and r["status"] in ("error", "fatal"):
            row.update(status="error", error=r.get("error"))
        rows.append(row)
    models.save_nodes(space["id"], rows)
