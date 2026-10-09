import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import traceback
from urllib.parse import quote

from flask import Flask, abort, jsonify, make_response, redirect, render_template_string, request, send_file, session

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import local_store
import models
import wiki_sync
from config import Config
from feishu import FeishuApiError, FeishuClient
from templates import INDEX_PAGE, LOGIN_PAGE, VIEW_PAGE

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
models.init_db()
if Config.SECRET_KEY in ("change-this-to-a-random-secret-key", "your-random-secret-key-here", ""):
    print("[wikilogger] ⚠️ SECRET_KEY 仍是默认值，会话可被伪造，请在 .env 中设置随机字符串", flush=True)

# ===== 同步进度（进程内存；gunicorn 须单 worker 多线程） =====
sync_progress = {}
cancel_events = {}
sync_lock = threading.Lock()


def _set_progress(ref, **kw):
    with sync_lock:
        cur = dict(sync_progress.get(ref) or {})
        cur.update(kw)
        sync_progress[ref] = cur


def _get_progress(ref):
    with sync_lock:
        p = sync_progress.get(ref)
        return dict(p) if p else None


# ===== 辅助 =====

def get_current_user():
    uid = session.get("user_id")
    return models.get_user(uid) if uid else None


def make_client(user):
    if not user or not user.get("access_token"):
        return None
    return FeishuClient(user["access_token"], user["refresh_token"], user["token_expires_at"],
                        user["refresh_expires_at"], user["id"])


def _new_oauth_state():
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    return state


def _plain(text, status=200):
    """纯文本响应：错误信息里可能带有外部输入，不能按 HTML 输出。"""
    resp = make_response(text, status)
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


def _api_error(e, default_status=500):
    msg = str(e)
    if isinstance(e, FeishuApiError):
        if e.code == 20073 or "20073" in msg or "Token 已过期" in msg:
            return jsonify({"error": "登录已过期，请退出后重新登录", "error_type": "auth"}), 401
        if e.is_permission_error:
            return jsonify({"error": f"无权限：{msg}（请确认你是该知识库成员，且 pm-assist 已开通对应权限）",
                            "error_type": "permission"}), 403
        return jsonify({"error": msg}), 400
    return jsonify({"error": msg}), default_status


def _space_payload(s):
    p = _get_progress(s["id"])
    root = local_store.space_dir(s["cache_dir"])
    return {
        "id": s["id"], "space_id": s["space_id"], "name": s.get("name") or s.get("feishu_name") or s["space_id"],
        "feishu_name": s.get("feishu_name") or "", "description": s.get("description") or "",
        "space_type": s.get("space_type") or "", "node_count": s.get("node_count") or 0,
        "doc_count": s.get("doc_count") or 0, "failed_count": s.get("failed_count") or 0,
        "last_sync_at": wiki_sync.fmt_ts(s["last_sync_at"]) if s.get("last_sync_at") else "",
        "last_sync_status": s.get("last_sync_status") or "", "summary": s.get("summary") or {},
        "has_cache": os.path.isfile(os.path.join(root, local_store.README)),
        "web_url": (f"{Config.FEISHU_WEB_BASE}/wiki/" if s.get("space_type") == "my_library"
                    else f"{Config.FEISHU_WEB_BASE}/wiki/settings/{s['space_id']}"),
        "progress": p,
    }


SPACE_SETTINGS_RE = re.compile(r"/wiki/(?:settings|space)/(\d+)")
WIKI_NODE_RE = re.compile(r"/wiki/([A-Za-z0-9]+)")
SPACE_ID_RE = re.compile(r"^\d{6,}$")


def resolve_space_input(client, text):
    """把用户输入（知识库链接 / 设置页链接 / space_id / my_library）解析为 space_id。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("请输入知识库链接或 space_id")
    if text in ("my_library", "我的文档库"):
        return client.get_space("my_library").get("space_id")
    m = SPACE_SETTINGS_RE.search(text)
    if m:
        return m.group(1)
    if SPACE_ID_RE.match(text):
        return text
    m = WIKI_NODE_RE.search(text)
    token = m.group(1) if m else (text if re.match(r"^[A-Za-z0-9]{20,}$", text) else None)
    if token and token not in ("settings", "space"):
        node = client.get_node(token)
        if node.get("space_id"):
            return str(node["space_id"])
    raise ValueError("无法识别：请粘贴知识库内任一页面链接、知识库设置页链接或 space_id")


# ===== 页面 =====

@app.route("/")
def index():
    user = get_current_user()
    if not user:
        return _no_cache(make_response(render_template_string(
            LOGIN_PAGE, auth_url=FeishuClient.get_authorize_url(_new_oauth_state()))))
    spaces = [_space_payload(s) for s in models.list_spaces(user["id"])]
    return _no_cache(make_response(render_template_string(INDEX_PAGE, user=user, spaces=spaces)))


@app.route("/auth/callback")
def auth_callback():
    if request.args.get("error"):
        return _plain(f"授权失败: {request.args.get('error')}", 400)
    auth_code = request.args.get("auth_code")
    if not auth_code:
        return _plain("缺少授权码", 400)
    # pm-hub 会把 state 原样带回：校验以防登录 CSRF（把别人的账号登录到你的浏览器）
    expected = session.pop("oauth_state", None)
    if not expected or not secrets.compare_digest(expected, request.args.get("state", "")):
        return _plain("登录状态已失效，请返回首页重新点击「飞书登录」", 400)
    token_data = FeishuClient.exchange_code_for_token(auth_code)
    if "access_token" not in token_data:
        return _plain(f"获取 token 失败: {json.dumps(token_data, ensure_ascii=False)}", 500)
    open_id = token_data.get("open_id", "")
    name = token_data.get("name", "")
    if not open_id:
        info = FeishuClient.get_user_info(token_data["access_token"])
        if info.get("code") != 0:
            return _plain(f"获取用户信息失败: {json.dumps(info, ensure_ascii=False)}", 500)
        open_id = info["data"]["open_id"]
        name = info["data"].get("name", open_id)
    user = models.get_or_create_user(open_id, name or open_id)
    models.update_user_tokens(user["id"], token_data["access_token"], token_data["refresh_token"],
                              token_data["expires_in"], token_data["refresh_token_expires_in"])
    models.update_user_name(user["id"], name or open_id)
    session["user_id"] = user["id"]
    return redirect("/")


@app.route("/auth/logout")
def logout():
    session.clear()
    return redirect("/")


# ===== 知识库管理 API =====

@app.route("/api/spaces", methods=["GET"])
def api_list_spaces():
    user = get_current_user()
    if not user:
        return jsonify({"error": "未登录"}), 401
    return jsonify({"spaces": [_space_payload(s) for s in models.list_spaces(user["id"])]})


@app.route("/api/user_spaces", methods=["GET"])
def api_user_spaces():
    """列出当前用户可访问的知识库（含「我的文档库」），供添加时选择。"""
    user = get_current_user()
    client = make_client(user)
    if not client:
        return jsonify({"error": "未登录"}), 401
    try:
        items = client.list_spaces()
    except Exception as e:
        return _api_error(e)
    added = {s["space_id"] for s in models.list_spaces(user["id"])}
    out = [{"space_id": str(x.get("space_id")), "name": x.get("name") or "", "description": x.get("description") or "",
            "space_type": x.get("space_type") or "", "visibility": x.get("visibility") or "",
            "added": str(x.get("space_id")) in added} for x in items]
    try:
        lib = client.get_space("my_library")
        if lib.get("space_id"):
            out.insert(0, {"space_id": str(lib["space_id"]), "name": lib.get("name") or "我的文档库",
                           "description": "个人文档库", "space_type": "my_library", "visibility": "private",
                           "added": str(lib["space_id"]) in added})
    except Exception:
        pass
    return jsonify({"spaces": out})


@app.route("/api/spaces", methods=["POST"])
def api_add_space():
    user = get_current_user()
    client = make_client(user)
    if not client:
        return jsonify({"error": "未登录"}), 401
    data = request.get_json(silent=True) or {}
    try:
        space_id = resolve_space_input(client, data.get("input") or data.get("space_id"))
        if models.find_space(user["id"], space_id):
            return jsonify({"error": "该知识库已添加"}), 409
        meta = client.get_space(space_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return _api_error(e)
    feishu_name = meta.get("name") or space_id
    name = (data.get("name") or "").strip() or feishu_name
    cache_dir = local_store.choose_cache_dir_name(feishu_name, space_id, models.cache_dir_in_use)
    ref = models.add_space(user["id"], str(space_id), name, feishu_name, meta.get("description"),
                           meta.get("space_type"), meta.get("visibility"), cache_dir)
    return jsonify({"ok": True, "space": _space_payload(models.get_space(user["id"], ref))})


@app.route("/api/spaces/<int:ref>/rename", methods=["POST"])
def api_rename_space(ref):
    user = get_current_user()
    if not user:
        return jsonify({"error": "未登录"}), 401
    s = models.get_space(user["id"], ref)
    if not s:
        return jsonify({"error": "知识库不存在"}), 404
    name = ((request.get_json(silent=True) or {}).get("name") or "").strip()
    models.update_space_meta(ref, name=name or s.get("feishu_name") or s["space_id"])
    return jsonify({"ok": True, "space": _space_payload(models.get_space(user["id"], ref))})


@app.route("/api/spaces/<int:ref>", methods=["DELETE"])
def api_delete_space(ref):
    user = get_current_user()
    if not user:
        return jsonify({"error": "未登录"}), 401
    s = models.get_space(user["id"], ref)
    if not s:
        return jsonify({"error": "知识库不存在"}), 404
    p = _get_progress(ref)
    if p and p.get("running"):
        return jsonify({"error": "同步进行中，请先停止同步"}), 409
    removed = False
    if request.args.get("delete_cache") == "1":
        removed = local_store.delete_space_dir(s["cache_dir"])
    models.delete_space(ref)
    with sync_lock:
        sync_progress.pop(ref, None)
    return jsonify({"ok": True, "cache_removed": removed})


# ===== 同步 =====

def _run_sync(user_id, ref, force):
    try:
        _run_sync_inner(user_id, ref, force)
    except Exception as e:  # 兜底：任何异常都不能让进度卡在「同步中」
        traceback.print_exc()
        _set_progress(ref, running=False, stage="error", error=str(e), message="")
    finally:
        p = _get_progress(ref)
        if p and p.get("running"):
            _set_progress(ref, running=False, stage="error", error=p.get("error") or "同步异常结束", message="")


def _run_sync_inner(user_id, ref, force):
    user = models.get_user(user_id)
    space = models.get_space(user_id, ref)
    client = make_client(user)
    cancel = cancel_events[ref]

    def on_progress(stage, current, total, message):
        _set_progress(ref, stage=stage, current=current, total=total, message=message)

    if not space or not client:
        _set_progress(ref, running=False, stage="error", error="知识库不存在或登录已失效", message="")
        return
    try:
        summary = wiki_sync.sync_space(client, space, on_progress, force=force, cancel_event=cancel)
        status = "ok" if not (summary["failed"] or summary["traverse_errors"]) else "partial"
        models.update_space_sync(ref, status, summary, node_count=summary["nodes"],
                                 doc_count=summary["docs"], failed_count=summary["failed"])
        msg = (f"同步完成：{summary['nodes']} 个节点，拉取 {summary['fetched']} 个，"
               f"未变化 {summary['unchanged']} 个，用时 {summary['seconds']}s")
        _set_progress(ref, running=False, stage="done", message=msg, result=summary, error=None)
    except wiki_sync.SyncCancelled:
        nodes = models.get_nodes(ref)
        models.update_space_sync(
            ref, "cancelled", {"cancelled": True}, node_count=len(nodes) or None,
            doc_count=sum(1 for n in nodes if n.get("obj_type") == "docx" and n.get("node_type") != "shortcut") or None)
        _set_progress(ref, running=False, stage="cancelled", message="同步已停止（已完成的部分已保存）",
                      error=None)
    except wiki_sync.FatalSyncError as e:
        models.update_space_sync(ref, "error", {"error": str(e)})
        _set_progress(ref, running=False, stage="error", error=f"登录已失效：{e}，请退出后重新登录",
                      error_type="auth", message="")
    except Exception as e:
        traceback.print_exc()
        etype = "permission" if isinstance(e, FeishuApiError) and e.is_permission_error else None
        models.update_space_sync(ref, "error", {"error": str(e)})
        _set_progress(ref, running=False, stage="error", error=str(e), error_type=etype, message="")


@app.route("/api/spaces/<int:ref>/sync", methods=["POST"])
def api_sync(ref):
    user = get_current_user()
    if not make_client(user):
        return jsonify({"error": "未登录"}), 401
    if not models.get_space(user["id"], ref):
        return jsonify({"error": "知识库不存在"}), 404
    force = bool((request.get_json(silent=True) or {}).get("force"))
    with sync_lock:
        p = sync_progress.get(ref)
        if p and p.get("running"):
            return jsonify({"error": "已有同步任务进行中", "progress": p}), 409
        sync_progress[ref] = {"running": True, "stage": "starting", "current": 0, "total": 0,
                              "message": "准备开始同步...", "result": None, "error": None,
                              "force": force, "started_at": time.time()}
        cancel_events[ref] = threading.Event()
    threading.Thread(target=_run_sync, args=(user["id"], ref, force), daemon=True).start()
    return jsonify({"ok": True, "started": True})


@app.route("/api/spaces/<int:ref>/cancel", methods=["POST"])
def api_cancel(ref):
    user = get_current_user()
    if not user or not models.get_space(user["id"], ref):
        return jsonify({"error": "未登录或知识库不存在"}), 401
    ev = cancel_events.get(ref)
    if ev:
        ev.set()
        _set_progress(ref, message="正在停止...")
    return jsonify({"ok": True})


@app.route("/api/spaces/<int:ref>/status", methods=["GET"])
def api_status(ref):
    user = get_current_user()
    if not user:
        return jsonify({"error": "未登录"}), 401
    s = models.get_space(user["id"], ref)
    if not s:
        return jsonify({"error": "知识库不存在"}), 404
    return jsonify(_space_payload(s))


# ===== 预览与下载 =====

def _space_or_404(ref):
    user = get_current_user()
    if not user:
        abort(401)
    s = models.get_space(user["id"], ref)
    if not s:
        abort(404)
    return s


@app.route("/space/<int:ref>")
def view_space(ref):
    user = get_current_user()
    if not user:
        return redirect("/")
    s = models.get_space(user["id"], ref)
    if not s:
        return "知识库不存在", 404
    return _no_cache(make_response(render_template_string(
        VIEW_PAGE, space=_space_payload(s), info=local_store.get_dir_info(local_store.space_dir(s["cache_dir"])))))


@app.route("/api/spaces/<int:ref>/tree")
def api_tree(ref):
    s = _space_or_404(ref)
    nodes = models.get_nodes(ref)
    return jsonify({"nodes": [{
        "t": n["node_token"], "p": n.get("parent_node_token") or "", "title": n.get("title") or "未命名",
        "type": n.get("obj_type") or "", "shortcut": n.get("node_type") == "shortcut",
        "path": n.get("rel_path"), "depth": n.get("depth") or 0, "status": n.get("status"),
        "error": n.get("error"),
    } for n in nodes], "space_id": s["space_id"]})


@app.route("/space/<int:ref>/files/<path:rel>")
def space_file(ref, rel):
    """知识库镜像内的文件：.md 返回文本；图片内联；其他附件下载。"""
    s = _space_or_404(ref)
    root = local_store.space_dir(s["cache_dir"])
    path = local_store.resolve_inside(root, rel)
    if not path or not os.path.isfile(path):
        return "文件不存在", 404
    name = os.path.basename(path)
    if name.lower().endswith(".md"):
        if request.args.get("download") == "1":
            resp = send_file(path, mimetype="text/markdown", as_attachment=True, download_name=name)
            resp.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
            return resp
        with open(path, "r", encoding="utf-8") as f:
            resp = make_response(f.read())
        resp.headers["Content-Type"] = "text/markdown; charset=utf-8"
        return _no_cache(resp)
    is_image = name.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"))
    download = request.args.get("download") == "1" or not is_image
    resp = send_file(path, mimetype=mimetypes.guess_type(name)[0] or "application/octet-stream",
                     as_attachment=download, download_name=name)
    if download:
        resp.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.route("/space/<int:ref>/download")
def space_zip(ref):
    s = _space_or_404(ref)
    root = local_store.space_dir(s["cache_dir"])
    if not os.path.isdir(root):
        return "尚未同步", 404
    buf, fname = local_store.build_zip(root, s.get("name") or s["cache_dir"])
    resp = send_file(buf, mimetype="application/zip", as_attachment=True, download_name=fname)
    resp.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(fname)}"
    return resp


if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, threaded=True)
