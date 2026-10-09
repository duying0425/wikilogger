"""飞书 OpenAPI 客户端（知识库 / 新版文档 / 云空间下载与导出）。

与 chatlogger 共用 pm-assist 认证跳板：OAuth 由跳板代理，token 拿到后直连飞书。
配额按飞书应用计，pm-assist 下所有客户端共享，因此这里对每类接口做进程内限速，
并对限流 / 瞬时错误做指数退避重试。
"""
import re
import threading
import time
from urllib.parse import unquote

import requests

from config import Config


class FeishuApiError(Exception):
    """飞书业务错误（code != 0 或 HTTP 非 2xx）"""

    def __init__(self, message, code=None, http_status=None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status

    @property
    def is_permission_error(self):
        # 131006 知识库无权限；1770032 / 403 文档无权限；99991672/99991679 应用/用户未开通 scope
        return (self.code in (131006, 1770032, 99991672, 99991679, 1069902, 1061004)
                or self.http_status == 403)


class SizeExceededError(Exception):
    """附件超过大小限制"""


# 可重试的飞书业务码：通用限流 / 过载、docx 限流、云空间下载限流、导出限流、知识库 rpc 失败、文档服务维护
RETRYABLE_API_CODES = {99991663, 99991664, 99991400, 1061045, 1069923, 131001, 1771005}
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}

_token_refresh_lock = threading.Lock()


# ===== 限速 =====

class RateLimiter:
    """线程安全的令牌桶：rate 次 / per 秒，burst 为桶容量。"""

    def __init__(self, rate, per, burst=None):
        self.rate = float(rate)
        self.per = float(per)
        self.capacity = float(burst if burst is not None else max(1.0, min(self.rate, 10.0)))
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self):
        refill_per_sec = self.rate / self.per
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * refill_per_sec)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / refill_per_sec
            time.sleep(min(wait, 5.0))


_limiters = {}
_limiters_lock = threading.Lock()


def get_limiter(kind):
    """按接口类别取全局限速器（进程内共享，多知识库并发同步也受同一限额约束）。"""
    with _limiters_lock:
        lim = _limiters.get(kind)
        if lim is None:
            # 秒级接口不留突发（burst=1），避免首秒超过官方 5 次/秒
            if kind == "wiki":
                lim = RateLimiter(Config.WIKI_API_PER_MIN, 60)
            elif kind == "docx":
                lim = RateLimiter(Config.DOCX_API_PER_SEC, 1, burst=1)
            elif kind == "drive":
                lim = RateLimiter(Config.DRIVE_DOWNLOAD_PER_SEC, 1, burst=1)
            elif kind == "export":
                lim = RateLimiter(Config.EXPORT_API_PER_MIN, 60)
            else:
                lim = RateLimiter(10, 1)
            _limiters[kind] = lim
        return lim


def reset_limiters():
    """测试用：按当前 Config 重建限速器。"""
    with _limiters_lock:
        _limiters.clear()


def _kind_for_path(path):
    if path.startswith("/wiki/"):
        return "wiki"
    if path.startswith("/docx/"):
        return "docx"
    if path.startswith("/drive/v1/export_tasks"):
        return "export"
    if path.startswith("/drive/"):
        return "drive"
    return "other"


def _retry_wait(resp, attempt):
    """优先使用飞书网关返回的限流重置时间，否则指数退避（1,2,4,8,16s）。"""
    if resp is not None:
        reset = resp.headers.get("x-ogw-ratelimit-reset")
        if reset:
            try:
                return min(max(float(reset), 0.5), 60.0)
            except ValueError:
                pass
    return min(1.0 * (2 ** attempt), 30.0)


def _json_code(resp):
    ctype = resp.headers.get("content-type", "") or resp.headers.get("Content-Type", "")
    if "application/json" not in ctype:
        return None, None
    try:
        data = resp.json()
    except ValueError:
        return None, None
    if isinstance(data, dict):
        return data.get("code"), data
    return None, data


def request_with_retry(request_fn, kind="other", max_retries=5):
    """执行请求：先过限速器，再对限流 / 瞬时错误重试。返回 requests.Response。"""
    limiter = get_limiter(kind)
    last_exc = None
    resp = None
    for attempt in range(max_retries + 1):
        limiter.acquire()
        try:
            resp = request_fn()
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            if attempt < max_retries:
                time.sleep(_retry_wait(None, attempt))
                continue
            raise
        retry = resp.status_code in RETRYABLE_HTTP_STATUS
        if not retry:
            code, _ = _json_code(resp)
            retry = code in RETRYABLE_API_CODES
        if retry and attempt < max_retries:
            time.sleep(_retry_wait(resp, attempt))
            continue
        return resp
    if last_exc:
        raise last_exc
    return resp


def _check(data, what):
    if not isinstance(data, dict) or data.get("code") != 0:
        code = data.get("code") if isinstance(data, dict) else None
        msg = data.get("msg") if isinstance(data, dict) else str(data)
        http_status = data.get("_http_status") if isinstance(data, dict) else None
        raise FeishuApiError(f"{what}失败: {msg} (code={code})", code=code, http_status=http_status)
    return data.get("data") or {}


def _filename_from_disposition(header):
    if not header:
        return ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", header, re.IGNORECASE)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename="?([^";]+)"?', header, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        try:
            # requests 以 latin-1 解码头部，中文文件名需还原为 UTF-8
            name = name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return unquote(name)
    return ""


class FeishuClient:
    """飞书 OpenAPI 客户端，使用 user_access_token 调用"""

    def __init__(self, access_token, refresh_token, token_expires_at, refresh_expires_at, user_id):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = token_expires_at or 0
        self.refresh_expires_at = refresh_expires_at or 0
        self.user_id = user_id

    # ===== token =====

    def _ensure_token(self):
        if time.time() < self.token_expires_at - 300:
            return
        if not self.refresh_token or time.time() > self.refresh_expires_at:
            raise FeishuApiError("Token 已过期且无法刷新，请重新登录授权", code=20073)
        self._refresh_access_token()

    def _refresh_access_token(self):
        """经认证跳板刷新 user_access_token（refresh_token 一次性，全局锁串行化）。"""
        if time.time() < self.token_expires_at - 300:
            return
        with _token_refresh_lock:
            if time.time() < self.token_expires_at - 300:
                return
            # 其他线程 / 请求可能已刷新并写库：先从库里取最新 token
            import models
            latest = models.get_user(self.user_id)
            if latest and (latest.get("token_expires_at") or 0) > time.time() + 300:
                self.access_token = latest["access_token"]
                self.refresh_token = latest["refresh_token"]
                self.token_expires_at = latest["token_expires_at"]
                self.refresh_expires_at = latest["refresh_expires_at"]
                return
            if latest and latest.get("refresh_token"):
                self.refresh_token = latest["refresh_token"]
            resp = requests.post(f"{Config.HUB_URL}/hub/api/refresh", json={
                "client_id": Config.HUB_CLIENT_ID,
                "client_secret": Config.HUB_CLIENT_SECRET,
                "refresh_token": self.refresh_token,
            }, timeout=15)
            try:
                data = resp.json()
            except ValueError:
                data = {"raw": resp.text[:200]}
            if resp.status_code != 200 or "access_token" not in data:
                raise FeishuApiError(f"刷新 token 失败: {data}", code=20073)
            self.access_token = data["access_token"]
            self.refresh_token = data["refresh_token"]
            self.token_expires_at = time.time() + data["expires_in"]
            self.refresh_expires_at = time.time() + data["refresh_token_expires_in"]
            models.update_user_tokens(self.user_id, self.access_token, self.refresh_token,
                                      data["expires_in"], data["refresh_token_expires_in"])

    def _headers(self):
        self._ensure_token()
        return {"Authorization": f"Bearer {self.access_token}"}

    def _api_get(self, path, params=None):
        url = f"{Config.API_BASE}{path}"
        resp = request_with_retry(
            lambda: requests.get(url, headers=self._headers(), params=params, timeout=60),
            kind=_kind_for_path(path))
        return self._parse(resp)

    def _api_post(self, path, json=None):
        url = f"{Config.API_BASE}{path}"
        resp = request_with_retry(
            lambda: requests.post(url, headers=self._headers(), json=json, timeout=60),
            kind=_kind_for_path(path))
        return self._parse(resp)

    @staticmethod
    def _parse(resp):
        try:
            data = resp.json()
        except ValueError:
            data = {"code": -1, "msg": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        if isinstance(data, dict) and resp.status_code >= 400:
            data["_http_status"] = resp.status_code
        return data

    # ===== OAuth 静态方法 =====

    @staticmethod
    def get_authorize_url(state=""):
        from urllib.parse import urlencode
        params = {"client_id": Config.HUB_CLIENT_ID, "state": state}
        return f"{Config.HUB_URL}/hub/authorize?{urlencode(params)}"

    @staticmethod
    def exchange_code_for_token(auth_code):
        resp = requests.post(f"{Config.HUB_URL}/hub/api/token", json={
            "client_id": Config.HUB_CLIENT_ID,
            "client_secret": Config.HUB_CLIENT_SECRET,
            "auth_code": auth_code,
        }, timeout=15)
        return resp.json()

    @staticmethod
    def get_user_info(access_token):
        resp = requests.get(f"{Config.API_BASE}/authen/v1/user_info",
                            headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
        return resp.json()

    # ===== 知识库 =====

    def list_spaces(self):
        """获取当前用户有权限访问的知识空间（不含「我的文档库」）。自动翻页。"""
        spaces = []
        page_token = None
        seen = set()
        while True:
            params = {"page_size": 50}
            if page_token:
                params["page_token"] = page_token
            d = _check(self._api_get("/wiki/v2/spaces", params=params), "获取知识空间列表")
            spaces.extend(d.get("items") or [])
            # 权限过滤可能导致空页但 has_more=true，必须继续翻
            page_token = d.get("page_token")
            if not d.get("has_more") or not page_token or page_token in seen:
                break
            seen.add(page_token)
        return spaces

    def get_space(self, space_id):
        """获取知识空间信息。space_id 传 my_library 时返回「我的文档库」。"""
        params = {"lang": "zh"} if space_id == "my_library" else None
        d = _check(self._api_get(f"/wiki/v2/spaces/{space_id}", params=params), "获取知识空间信息")
        return d.get("space") or {}

    def list_nodes_page(self, space_id, parent_node_token=None, page_token=None, page_size=50):
        """获取某父节点下的一页子节点。返回 {items, has_more, page_token}。"""
        params = {"page_size": page_size}
        if parent_node_token:
            params["parent_node_token"] = parent_node_token
        if page_token:
            params["page_token"] = page_token
        return _check(self._api_get(f"/wiki/v2/spaces/{space_id}/nodes", params=params),
                      "获取知识空间子节点列表")

    def get_node(self, token, obj_type="wiki"):
        d = _check(self._api_get("/wiki/v2/spaces/get_node",
                                 params={"token": token, "obj_type": obj_type}),
                   "获取知识空间节点信息")
        return d.get("node") or {}

    # ===== 新版文档 =====

    def get_docx_blocks(self, doc_token):
        """分页拉取新版文档全部 Block。"""
        blocks = []
        page_token = ""
        seen = set()
        while True:
            params = {"page_size": 500, "document_revision_id": -1}
            if page_token:
                params["page_token"] = page_token
            d = _check(self._api_get(f"/docx/v1/documents/{doc_token}/blocks", params=params),
                       "获取文档内容")
            blocks.extend(d.get("items") or [])
            page_token = d.get("page_token") or ""
            if not d.get("has_more") or not page_token or page_token in seen:
                break
            seen.add(page_token)
        return blocks

    # ===== 下载 =====

    def _download(self, url, what, max_size_mb=None, kind="drive"):
        """流式下载并做大小限制。返回 (bytes, content_type, filename)。"""
        if max_size_mb is None:
            max_size_mb = Config.MAX_ATTACHMENT_SIZE_MB
        limit = max_size_mb * 1024 * 1024
        resp = request_with_retry(
            lambda: requests.get(url, headers=self._headers(), stream=True, timeout=120), kind=kind)
        if resp.status_code != 200:
            code, data = _json_code(resp)
            msg = (data or {}).get("msg") if isinstance(data, dict) else None
            raise FeishuApiError(f"{what}失败: {msg or 'HTTP ' + str(resp.status_code)}",
                                 code=code, http_status=resp.status_code)
        length = int(resp.headers.get("Content-Length") or 0)
        if length > limit:
            resp.close()
            raise SizeExceededError(f"{length / 1048576:.1f}MB 超过上限 {max_size_mb}MB")
        buf = bytearray()
        for chunk in resp.iter_content(chunk_size=256 * 1024):
            buf.extend(chunk)
            if len(buf) > limit:
                resp.close()
                raise SizeExceededError(f"超过上限 {max_size_mb}MB")
        return (bytes(buf), resp.headers.get("Content-Type", ""),
                _filename_from_disposition(resp.headers.get("Content-Disposition", "")))

    def download_media(self, file_token, max_size_mb=None):
        """下载文档内素材（图片、文件块）。"""
        return self._download(f"{Config.API_BASE}/drive/v1/medias/{file_token}/download",
                              "下载文档素材", max_size_mb)

    def download_drive_file(self, file_token, max_size_mb=None):
        """下载知识库中的文件节点（obj_type=file）。"""
        return self._download(f"{Config.API_BASE}/drive/v1/files/{file_token}/download",
                              "下载文件", max_size_mb)

    def export_file(self, obj_token, obj_type, file_extension, max_size_mb=None, timeout=180):
        """创建导出任务 → 轮询结果 → 下载导出文件。返回 (bytes, filename)。

        支持：docx/doc → docx|pdf，sheet/bitable → xlsx（csv 需指定子表，这里不用）。
        """
        d = _check(self._api_post("/drive/v1/export_tasks", json={
            "file_extension": file_extension, "token": obj_token, "type": obj_type,
        }), "创建导出任务")
        ticket = d.get("ticket")
        if not ticket:
            raise FeishuApiError("创建导出任务失败: 未返回 ticket")
        deadline = time.time() + timeout
        wait = 1.0
        result = {}
        while time.time() < deadline:
            time.sleep(wait)
            wait = min(wait * 1.5, 8.0)
            d = _check(self._api_get(f"/drive/v1/export_tasks/{ticket}", params={"token": obj_token}),
                       "查询导出任务")
            result = d.get("result") or {}
            status = result.get("job_status")
            if status == 0:
                break
            if status in (1, 2, None):
                continue
            raise FeishuApiError(f"导出失败: {result.get('job_error_msg') or 'job_status=' + str(status)}")
        else:
            raise FeishuApiError("导出任务超时")
        size = int(result.get("file_size") or 0)
        limit_mb = max_size_mb if max_size_mb is not None else Config.MAX_ATTACHMENT_SIZE_MB
        if size > limit_mb * 1024 * 1024:
            raise SizeExceededError(f"导出文件 {size / 1048576:.1f}MB 超过上限 {limit_mb}MB")
        content, _, fname = self._download(
            f"{Config.API_BASE}/drive/v1/export_tasks/file/{result.get('file_token')}/download",
            "下载导出文件", max_size_mb, kind="export")
        name = result.get("file_name") or fname or obj_token
        if not name.lower().endswith("." + file_extension):
            name = f"{name}.{file_extension}"
        return content, name


def decode_link_url(url):
    """docx 超链接 url 是 URL 编码的（https%3A%2F%2F...），还原为可点击地址。"""
    if not url:
        return ""
    if re.match(r"^https?%3A", url, re.IGNORECASE) or "%2F" in url[:16]:
        return unquote(url)
    return url
