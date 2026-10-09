import os


def _env_bool(name, default):
    return os.environ.get(name, default).lower() in ("true", "1", "yes")


class Config:
    # ===== 认证跳板配置 =====
    # OAuth 由 pm-assist 认证跳板（https://pm.tmhcorps.cn/hub）代理完成，
    # 本应用不持有飞书应用凭证；client_id/secret 在 pm-assist .env 的 HUB_CLIENTS 注册
    HUB_URL = os.environ.get("HUB_URL", "https://pm.tmhcorps.cn")
    HUB_CLIENT_ID = os.environ.get("HUB_CLIENT_ID", "")
    HUB_CLIENT_SECRET = os.environ.get("HUB_CLIENT_SECRET", "")

    # 飞书 OpenAPI 基础地址（拿到的 user_access_token 依旧直连调用）
    API_BASE = "https://open.feishu.cn/open-apis"
    # 生成「打开原文」链接用的飞书网页域名（可设为企业域名，如 https://xxx.feishu.cn）
    FEISHU_WEB_BASE = os.environ.get("FEISHU_WEB_BASE", "https://feishu.cn").rstrip("/")

    # ===== 应用配置 =====
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-to-a-random-secret-key")
    DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "wikilogger.db"))
    # 知识库本地镜像根目录：每个知识库一个子目录
    LOCAL_CACHE_DIR = os.environ.get("LOCAL_CACHE_DIR", os.path.join(os.path.dirname(__file__), "cache"))

    # ===== 同步内容 =====
    # 单个附件 / 图片 / 导出文件大小上限（MB），超出跳过并在文档中标注
    MAX_ATTACHMENT_SIZE_MB = int(os.environ.get("MAX_ATTACHMENT_SIZE_MB", "50"))
    # 单篇文档最多转换的 Block 数，超出截断并标注
    MAX_DOC_BLOCKS = int(os.environ.get("MAX_DOC_BLOCKS", "20000"))
    # 单个知识库最多遍历的节点数（防御异常数据导致无限遍历）
    MAX_NODES = int(os.environ.get("MAX_NODES", "20000"))
    # 是否下载文档内图片
    CACHE_DOC_IMAGES = _env_bool("CACHE_DOC_IMAGES", "true")
    # 是否下载文档内嵌的附件（docx 文件块）
    CACHE_DOC_FILES = _env_bool("CACHE_DOC_FILES", "true")
    # 是否导出电子表格 / 多维表格为 xlsx、旧版文档为 docx（需 drive:export:readonly 权限）
    EXPORT_OFFICE_FILES = _env_bool("EXPORT_OFFICE_FILES", "true")
    # 是否下载知识库中直接上传的文件节点（需 drive:file:download 权限）
    DOWNLOAD_WIKI_FILES = _env_bool("DOWNLOAD_WIKI_FILES", "true")
    # 飞书侧已删除的节点：true 移入 _deleted/ 保留最后一版；false 直接删除本地文件
    KEEP_DELETED = _env_bool("KEEP_DELETED", "true")
    # 文档内容拉取并发数（总速率仍受下方限速约束）
    FETCH_CONCURRENCY = int(os.environ.get("FETCH_CONCURRENCY", "3"))

    # ===== 限速（按飞书应用计，pm-assist 下所有客户端共享配额，留出余量） =====
    # 知识库接口官方 100 次/分钟
    WIKI_API_PER_MIN = int(os.environ.get("WIKI_API_PER_MIN", "80"))
    # docx 接口官方 5 次/秒
    DOCX_API_PER_SEC = float(os.environ.get("DOCX_API_PER_SEC", "4"))
    # 素材 / 文件下载
    DRIVE_DOWNLOAD_PER_SEC = float(os.environ.get("DRIVE_DOWNLOAD_PER_SEC", "4"))
    # 导出任务官方 100 次/分钟
    EXPORT_API_PER_MIN = int(os.environ.get("EXPORT_API_PER_MIN", "80"))

    # 服务器配置
    HOST = os.environ.get("HOST", "0.0.0.0")
    PORT = int(os.environ.get("PORT", "5000"))
    DEBUG = _env_bool("DEBUG", "false")
