import json
import sqlite3
import time

from config import Config


def get_db():
    conn = sqlite3.connect(Config.DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            open_id TEXT UNIQUE NOT NULL,
            name TEXT,
            access_token TEXT,
            refresh_token TEXT,
            token_expires_at REAL,
            refresh_expires_at REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 知识库配置：每个用户可添加多个知识库；cache_dir 在添加时确定，改名不搬目录
    c.execute("""
        CREATE TABLE IF NOT EXISTS spaces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            space_id TEXT NOT NULL,
            name TEXT,
            feishu_name TEXT,
            description TEXT,
            space_type TEXT,
            visibility TEXT,
            cache_dir TEXT NOT NULL,
            node_count INTEGER DEFAULT 0,
            doc_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            last_sync_at REAL,
            last_sync_status TEXT,
            last_sync_summary TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, space_id)
        )
    """)

    # 知识库节点：遍历结果 + 本地同步状态
    c.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            space_ref INTEGER NOT NULL,
            node_token TEXT NOT NULL,
            parent_node_token TEXT,
            obj_token TEXT,
            obj_type TEXT,
            node_type TEXT,
            origin_node_token TEXT,
            title TEXT,
            has_child INTEGER DEFAULT 0,
            depth INTEGER DEFAULT 0,
            sort_index INTEGER DEFAULT 0,
            obj_edit_time TEXT,
            rel_path TEXT,
            synced_sig TEXT,
            status TEXT DEFAULT 'pending',
            error TEXT,
            synced_at REAL,
            FOREIGN KEY (space_ref) REFERENCES spaces(id),
            UNIQUE(space_ref, node_token)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_nodes_space ON nodes(space_ref, sort_index)")
    conn.commit()
    conn.close()


# ===== 用户 =====

def get_or_create_user(open_id, name):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE open_id = ?", (open_id,)).fetchone()
        if row:
            return dict(row)
        cur = conn.execute("INSERT INTO users (open_id, name) VALUES (?, ?)", (open_id, name))
        conn.commit()
        return {"id": cur.lastrowid, "open_id": open_id, "name": name}
    finally:
        conn.close()


def update_user_tokens(user_id, access_token, refresh_token, expires_in, refresh_expires_in):
    conn = get_db()
    try:
        conn.execute("""
            UPDATE users SET access_token = ?, refresh_token = ?, token_expires_at = ?,
                   refresh_expires_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (access_token, refresh_token, time.time() + expires_in,
              time.time() + refresh_expires_in, user_id))
        conn.commit()
    finally:
        conn.close()


def update_user_name(user_id, name):
    conn = get_db()
    try:
        conn.execute("UPDATE users SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (name, user_id))
        conn.commit()
    finally:
        conn.close()


def get_user(user_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ===== 知识库 =====

def _space_dict(row):
    if not row:
        return None
    d = dict(row)
    try:
        d["summary"] = json.loads(d.get("last_sync_summary") or "{}")
    except ValueError:
        d["summary"] = {}
    return d


def list_spaces(user_id):
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM spaces WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                            (user_id,)).fetchall()
        return [_space_dict(r) for r in rows]
    finally:
        conn.close()


def get_space(user_id, ref_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM spaces WHERE id = ? AND user_id = ?",
                           (ref_id, user_id)).fetchone()
        return _space_dict(row)
    finally:
        conn.close()


def get_space_by_ref(ref_id):
    conn = get_db()
    try:
        return _space_dict(conn.execute("SELECT * FROM spaces WHERE id = ?", (ref_id,)).fetchone())
    finally:
        conn.close()


def find_space(user_id, space_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM spaces WHERE user_id = ? AND space_id = ?",
                           (user_id, space_id)).fetchone()
        return _space_dict(row)
    finally:
        conn.close()


def cache_dir_in_use(cache_dir):
    conn = get_db()
    try:
        return conn.execute("SELECT 1 FROM spaces WHERE cache_dir = ?", (cache_dir,)).fetchone() is not None
    finally:
        conn.close()


def add_space(user_id, space_id, name, feishu_name, description, space_type, visibility, cache_dir):
    conn = get_db()
    try:
        cur = conn.execute("""
            INSERT INTO spaces (user_id, space_id, name, feishu_name, description, space_type,
                                visibility, cache_dir)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, space_id, name, feishu_name, description, space_type, visibility, cache_dir))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_space_meta(ref_id, **fields):
    allowed = {"name", "feishu_name", "description", "space_type", "visibility"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    conn = get_db()
    try:
        cols = ", ".join(f"{k} = ?" for k in sets)
        conn.execute(f"UPDATE spaces SET {cols}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (*sets.values(), ref_id))
        conn.commit()
    finally:
        conn.close()


def update_space_sync(ref_id, status, summary, node_count=None, doc_count=None, failed_count=None):
    conn = get_db()
    try:
        conn.execute("""
            UPDATE spaces SET last_sync_at = ?, last_sync_status = ?, last_sync_summary = ?,
                   node_count = COALESCE(?, node_count), doc_count = COALESCE(?, doc_count),
                   failed_count = COALESCE(?, failed_count), updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (time.time(), status, json.dumps(summary, ensure_ascii=False),
              node_count, doc_count, failed_count, ref_id))
        conn.commit()
    finally:
        conn.close()


def delete_space(ref_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM nodes WHERE space_ref = ?", (ref_id,))
        conn.execute("DELETE FROM spaces WHERE id = ?", (ref_id,))
        conn.commit()
    finally:
        conn.close()


# ===== 节点 =====

NODE_FIELDS = ("node_token", "parent_node_token", "obj_token", "obj_type", "node_type",
               "origin_node_token", "title", "has_child", "depth", "sort_index", "obj_edit_time",
               "rel_path", "synced_sig", "status", "error", "synced_at")


def get_nodes(space_ref):
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM nodes WHERE space_ref = ? ORDER BY sort_index",
                            (space_ref,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_node(space_ref, node_token):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM nodes WHERE space_ref = ? AND node_token = ?",
                           (space_ref, node_token)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_nodes(space_ref, nodes):
    """批量写入 / 更新节点（按 node_token upsert）。"""
    if not nodes:
        return
    conn = get_db()
    try:
        cols = ", ".join(NODE_FIELDS)
        placeholders = ", ".join("?" for _ in NODE_FIELDS)
        updates = ", ".join(f"{f} = excluded.{f}" for f in NODE_FIELDS if f != "node_token")
        conn.executemany(
            f"INSERT INTO nodes (space_ref, {cols}) VALUES (?, {placeholders}) "
            f"ON CONFLICT(space_ref, node_token) DO UPDATE SET {updates}",
            [(space_ref, *[n.get(f) for f in NODE_FIELDS]) for n in nodes])
        conn.commit()
    finally:
        conn.close()


def delete_nodes(space_ref, node_tokens):
    if not node_tokens:
        return
    conn = get_db()
    try:
        conn.executemany("DELETE FROM nodes WHERE space_ref = ? AND node_token = ?",
                         [(space_ref, t) for t in node_tokens])
        conn.commit()
    finally:
        conn.close()
