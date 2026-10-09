"""知识库本地镜像的目录布局与文件操作。

cache/{知识库名}_{space_id}/
├── README.md             目录索引（树形，链接到各文档）
├── _manifest.json        节点元数据
├── 一级文档.md
├── 一级文档/             子节点目录（与同名 .md 并列）
│   └── 二级文档.md
├── _assets/{obj_token}/  每篇文档的图片、附件、导出文件
└── _deleted/             飞书侧已删除节点的最后一版（KEEP_DELETED=true）
"""
import os
import posixpath
import re
import shutil
import tempfile
import zipfile
from collections import Counter

from config import Config

ASSETS_DIR = "_assets"
DELETED_DIR = "_deleted"
TMP_DIR = ".wl_tmp"
README = "README.md"
MANIFEST = "_manifest.json"
RESERVED_ROOT = {ASSETS_DIR.lower(), DELETED_DIR.lower(), TMP_DIR.lower(), "readme", "_manifest.json"}
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                    *(f"lpt{i}" for i in range(1, 10))}
MAX_SEGMENT_LEN = 60

# 本地 wiki 链接：](<相对路径> "wiki:<node_token>") 或 ](https://... "wiki:<node_token>")
WIKI_LINK_RE = re.compile(r'\]\((<[^>\n]*>|[^)\s]+)\s+"wiki:([A-Za-z0-9_-]+)"\)')
# 资源链接：](<../../_assets/...
ASSET_LINK_RE = re.compile(r"\]\(<((?:\.\./)*)" + ASSETS_DIR + "/")


def sanitize_segment(name, fallback="未命名", max_len=MAX_SEGMENT_LEN):
    """生成安全的文件 / 目录名（兼容 Windows / Linux）。
    # 会被 Markdown 链接当作锚点，替换为全角 ＃。"""
    cleaned = re.sub(r'[\\/*?:"<>|\x00-\x1f]+', "_", str(name or "")).replace("#", "＃")
    cleaned = cleaned.strip().strip(".").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > max_len:
        stem, dot, ext = cleaned.rpartition(".")
        if dot and 0 < len(ext) <= 8 and len(stem) > 0:
            # 截断时保留扩展名
            cleaned = stem[:max_len - len(ext) - 1].rstrip(" .") + "." + ext
        else:
            cleaned = cleaned[:max_len].rstrip(" .")
    if not cleaned:
        cleaned = fallback
    if cleaned.split(".")[0].lower() in WINDOWS_RESERVED:
        cleaned = cleaned + "_"
    return cleaned


def get_cache_root():
    os.makedirs(Config.LOCAL_CACHE_DIR, exist_ok=True)
    return Config.LOCAL_CACHE_DIR


def space_dir(cache_dir_name):
    return os.path.join(get_cache_root(), cache_dir_name)


def choose_cache_dir_name(space_name, space_id, in_use_fn):
    base = f"{sanitize_segment(space_name, 'wiki')}_{space_id}"
    name = base
    i = 2
    # 不复用已存在的目录：删除配置时保留的旧镜像可能包含其他用户有权限的内容
    while in_use_fn(name) or os.path.exists(os.path.join(get_cache_root(), name)):
        name = f"{base}_{i}"
        i += 1
    return name


def resolve_inside(root, rel_path):
    """把相对路径解析到 root 内的绝对路径；越界返回 None（防目录遍历）。"""
    root_abs = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_abs, *rel_path.split("/")))
    if target != root_abs and not target.startswith(root_abs + os.sep):
        return None
    return target


# ===== 路径规划 =====

def compute_paths(nodes, reserved=None):
    """为遍历到的节点计算本地相对路径（posix 风格，如 "父/子.md"）。

    nodes: 先序列表，每项含 node_token / parent_node_token / title。
    reserved: 需要避开的已占用路径（小写），如遍历不完整时未列出节点的旧文件。
    同级重名（大小写不敏感）的节点追加 ~token 后 6 位以区分；根目录避开保留名。
    名称不以 .md 结尾，保证「X.md」文件与「X/」目录不会互相冲突。
    返回 {node_token: rel_path}
    """
    reserved = reserved or set()
    children = {}
    for n in nodes:
        children.setdefault(n.get("parent_node_token") or "", []).append(n)
    paths = {}
    stack = [("", "")]
    while stack:
        parent_token, parent_dir = stack.pop()
        siblings = children.get(parent_token, [])
        names = [_strip_md_suffix(sanitize_segment(n.get("title"))) for n in siblings]
        counts = Counter(x.lower() for x in names)
        for n, name in zip(siblings, names):
            lower = name.lower()
            if counts[lower] > 1 or (not parent_dir and (lower in RESERVED_ROOT or lower.startswith("_"))):
                name = f"{name}~{n['node_token'][-6:]}"
            rel_dir = f"{parent_dir}/{name}" if parent_dir else name
            if (rel_dir + ".md").lower() in reserved:
                name = f"{name}~{n['node_token'][-6:]}"
                rel_dir = f"{parent_dir}/{name}" if parent_dir else name
            paths[n["node_token"]] = rel_dir + ".md"
            if n["node_token"] in children:
                stack.append((n["node_token"], rel_dir))
    return paths


def _strip_md_suffix(name):
    if name.lower().endswith(".md"):
        return name[:-3] + "_md"
    return name


def asset_prefix(rel_path):
    return "../" * rel_path.count("/")


def wiki_link_dest(from_rel_path, target_rel_path, node_token):
    """从 from 文档指向 target 文档的 Markdown 链接目标（带 wiki 标记）。"""
    start = posixpath.dirname(from_rel_path) or "."
    rel = posixpath.relpath(target_rel_path, start)
    return f'<{rel}> "wiki:{node_token}"'


# ===== 文件读写 =====

def write_text(root, rel_path, text):
    path = resolve_inside(root, rel_path)
    if path is None:
        raise ValueError(f"非法路径: {rel_path}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def read_text(root, rel_path):
    path = resolve_inside(root, rel_path)
    if path is None or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def exists(root, rel_path):
    path = resolve_inside(root, rel_path)
    return bool(path) and os.path.exists(path)


def asset_dir(root, obj_token):
    return os.path.join(root, ASSETS_DIR, sanitize_segment(obj_token, "obj"))


def find_asset(root, obj_token, prefix):
    """在文档资源目录里找以 prefix 开头的已下载文件（素材 token 不变，可复用）。"""
    d = asset_dir(root, obj_token)
    if not os.path.isdir(d):
        return None
    for name in os.listdir(d):
        if name.startswith(prefix) and not name.endswith(".tmp"):
            return name
    return None


def save_asset(root, obj_token, filename, content):
    d = asset_dir(root, obj_token)
    os.makedirs(d, exist_ok=True)
    filename = sanitize_segment(filename, "file", max_len=120)
    path = os.path.join(d, filename)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(content)
    os.replace(tmp, path)
    return filename


def prune_assets(root, obj_token, keep_names):
    """删除文档资源目录里本次未引用的旧文件。"""
    d = asset_dir(root, obj_token)
    if not os.path.isdir(d):
        return
    for name in os.listdir(d):
        if name not in keep_names:
            try:
                os.remove(os.path.join(d, name))
            except OSError:
                pass
    try:
        if not os.listdir(d):
            os.rmdir(d)
    except OSError:
        pass


def move_files(root, moves):
    """两阶段移动 {old_rel: new_rel}，避免互换 / 链式移动时互相覆盖。"""
    staged = []
    tmp_root = os.path.join(root, TMP_DIR)
    for i, (old, new) in enumerate(moves.items()):
        src = resolve_inside(root, old)
        if not src or not os.path.isfile(src):
            continue
        os.makedirs(tmp_root, exist_ok=True)
        tmp = os.path.join(tmp_root, f"{i}.md")
        os.replace(src, tmp)
        staged.append((tmp, new))
    for tmp, new in staged:
        dst = resolve_inside(root, new)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(tmp, dst)
    shutil.rmtree(tmp_root, ignore_errors=True)


def retire_file(root, rel_path, obj_token, keep=True):
    """飞书侧删除的节点：移入 _deleted/（保留最后一版）或直接删除。"""
    src = resolve_inside(root, rel_path)
    if src and os.path.isfile(src):
        if keep:
            dst = resolve_inside(root, f"{DELETED_DIR}/{rel_path}")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(src, dst)
        else:
            os.remove(src)
    if obj_token:
        adir = asset_dir(root, obj_token)
        if os.path.isdir(adir):
            if keep:
                dst = os.path.join(root, DELETED_DIR, ASSETS_DIR, os.path.basename(adir))
                if os.path.exists(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(adir, dst)
            else:
                shutil.rmtree(adir, ignore_errors=True)


def remove_empty_dirs(root):
    """清理文档树中的空目录（不动根目录、_assets、_deleted）。"""
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        rel = os.path.relpath(dirpath, root)
        if rel == "." or rel.split(os.sep)[0] in (ASSETS_DIR, DELETED_DIR):
            continue
        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:
            pass


# ===== 链接重算 =====

def relink_markdown(text, rel_path, token_to_path, web_base=None):
    """按当前目录结构重算文档内的资源链接和知识库内部链接。"""
    web_base = (web_base or Config.FEISHU_WEB_BASE).rstrip("/")
    prefix = asset_prefix(rel_path)
    text = ASSET_LINK_RE.sub(lambda m: f"](<{prefix}{ASSETS_DIR}/", text)

    def repl(m):
        token = m.group(2)
        target = token_to_path.get(token)
        if target:
            return "](" + wiki_link_dest(rel_path, target, token) + ")"
        return f'](<{web_base}/wiki/{token}> "wiki:{token}")'

    return WIKI_LINK_RE.sub(repl, text)


def relink_all(root, token_to_path, web_base=None):
    """对知识库内全部文档执行链接重算，只回写有变化的文件。返回改写的文件数。"""
    changed = 0
    for rel in token_to_path.values():
        text = read_text(root, rel)
        if text is None:
            continue
        new = relink_markdown(text, rel, token_to_path, web_base)
        if new != text:
            write_text(root, rel, new)
            changed += 1
    return changed


# ===== 统计 / 打包 / 删除 =====

def get_dir_info(root):
    info = {"file_count": 0, "asset_count": 0, "total_size": 0}
    if not os.path.isdir(root):
        return info
    for dirpath, _, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        for fn in filenames:
            try:
                info["total_size"] += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                continue
            if rel.split(os.sep)[0] == ASSETS_DIR:
                info["asset_count"] += 1
            elif fn.endswith(".md"):
                info["file_count"] += 1
    return info


def build_zip(root, zip_name):
    """打包整个知识库镜像目录到临时文件（不占内存），返回 (文件对象, 文件名)。"""
    buf = tempfile.TemporaryFile()
    top = sanitize_segment(zip_name, "wiki")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != TMP_DIR]
            for fn in filenames:
                if fn.endswith(".tmp"):
                    continue
                abs_path = os.path.join(dirpath, fn)
                arc = os.path.relpath(abs_path, root).replace(os.sep, "/")
                zf.write(abs_path, arcname=f"{top}/{arc}")
    buf.seek(0)
    return buf, f"{top}.zip"


def delete_space_dir(cache_dir_name):
    d = space_dir(cache_dir_name)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False
