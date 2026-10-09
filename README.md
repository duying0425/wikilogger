# 飞书知识库归档（wikilogger）

以**知识库**为单位，把整个飞书知识库（Wiki 空间）镜像为本地 Markdown 目录树，支持手动增量同步、在线预览与 ZIP 打包下载。架构与 [chatlogger](../chatlogger) 一致：pm-assist 认证跳板 + Flask + SQLite + 本地缓存。

## 功能

- 飞书 OAuth 登录（经 pm-assist 认证跳板，用户身份访问，权限与本人在飞书中一致）
- 添加知识库：粘贴知识库内任一页面链接 / 知识库设置页链接 / space_id，或从「我有权限的知识库」列表中选择（含「我的文档库」）
- **整库拉取**：递归遍历全部节点，按知识库目录结构生成本地文件树
- **手动增量同步**：只重新拉取 `obj_edit_time` 变化的文档；仅移动位置的文档直接在本地挪文件，不重新拉取
- **全量重建**：忽略本地状态，重新拉取全部节点
- 同步过程可随时**停止**，已完成部分保留，下次同步从未完成的节点继续
- 新版文档（docx）转 Markdown：标题、列表（含嵌套 / 有序编号）、代码块、表格、引用、高亮块、待办、公式、分栏、图片、附件等
- 文档内**图片 / 附件**下载到本地；知识库内文档互链改写为**本地相对链接**（节点移动后自动重算）
- 电子表格 / 多维表格导出为 xlsx，旧版文档导出为 docx，上传到知识库的文件下载原文件；思维笔记、幻灯片生成带飞书链接的占位页
- 飞书侧删除的节点移入 `_deleted/` 保留最后一版
- 在线预览：左侧目录树（可筛选）+ 右侧 Markdown 渲染，图片灯箱、附件下载卡片、文档间链接站内跳转

## 遍历原理：飞书有没有「拉取整个知识库」的接口？

**没有一次性导出整库的接口，但有按层分页列子节点的接口，递归即可遍历整库**（开源工具 feishu2md 的 `dl --wiki` 也是同样做法）。

| 用途 | 接口 | 官方频控 |
|---|---|---|
| 列出可访问的知识库 | `GET /open-apis/wiki/v2/spaces`（不含「我的文档库」） | 100 次/分钟 |
| 知识库信息 | `GET /open-apis/wiki/v2/spaces/{space_id}`（`space_id=my_library` 取我的文档库） | — |
| **遍历节点** | `GET /open-apis/wiki/v2/spaces/{space_id}/nodes?parent_node_token=…&page_size=50` | **100 次/分钟** |
| 链接 → 节点 | `GET /open-apis/wiki/v2/spaces/get_node?token=…` | 100 次/分钟 |
| 文档内容 | `GET /open-apis/docx/v1/documents/{obj_token}/blocks` | 5 次/秒 |
| 图片 / 附件 | `GET /open-apis/drive/v1/medias/{token}/download` | — |
| 表格类导出 | `POST /open-apis/drive/v1/export_tasks` → 轮询 → 下载 | 100 次/分钟 |
| 文件节点下载 | `GET /open-apis/drive/v1/files/{token}/download` | 5 QPS，1 万次/天 |

实现中需要注意的几点（均已处理）：

- **没有变更订阅 / 增量接口**：每次同步都要重新遍历整棵树；遍历调用次数 ≈ 有子节点的节点数（每个父节点至少 1 次，超过 50 个子节点再翻页）。按 100 次/分钟，约 500 个「目录型」节点需要 5 分钟以上。内容拉取则只针对 `obj_edit_time` 变化的文档。
- **空页但 `has_more=true`**：因权限过滤，某页可能为空但仍有下一页，必须继续翻页而不是结束。
- **快捷方式节点**（`node_type=shortcut`）不展开子节点，只生成指向源节点的链接页；用已访问集合防环。
- **配额按飞书应用计算**：wikilogger 与 chatlogger 都使用 pm-assist 的同一个飞书应用，共享上述配额。因此本服务按接口类别做进程内限速（默认知识库 80 次/分、docx 4 次/秒，留出余量），并对限流码（`99991400` / `99991663` / `1061045` / `1069923` 等）和 429 / 5xx 做指数退避重试，优先使用网关返回的 `x-ogw-ratelimit-reset`。
- **遍历失败不误删**：任一目录列取失败时，本次跳过删除处理，避免把没列出来的节点当成已删除。

## 前置条件：在 pm-assist 注册本应用

pm-hub 的接入应用与授权 scope 都在 pm-assist 的 `hub_config.json` 中（改动即时生效，无需重启）。在 `clients` 数组中加入一项：

```json
{"id": "wikilogger", "secret": "<随机密钥>", "redirect_uri": "https://wikilogger.tmhcorps.cn/auth/callback"}
```

scope 是全局一份（`scopes` 数组），本应用用到的权限如下，当前全局列表均已包含，无需改动：

| 权限 | 用途 | 必需 |
|---|---|---|
| `wiki:wiki`（或 `wiki:node:retrieve` + `wiki:space:retrieve`） | 列知识库、遍历节点 | ✅ |
| `docx:document` | 读取新版文档内容 | ✅ |
| `docs:document.media:download` | 下载文档内图片 / 附件 | ✅ |
| `offline_access` | 刷新 user_access_token | ✅ |
| `docs:document:export` | 电子表格 / 多维表格导出 xlsx、旧版文档导出 docx | 可选（`EXPORT_OFFICE_FILES`） |
| `drive:file:download` | 下载知识库中上传的文件 | 可选（`DOWNLOAD_WIKI_FILES`） |

> 缺少可选权限时，对应节点会在同步结果中标为「⚠️ 导出 / 下载失败」，不影响其他内容；未编辑的节点不会反复重试。
>
> 登录回调会校验 pm-hub 原样带回的 `state`，防止登录 CSRF。

## 部署与运行

### Docker Compose（推荐）

```bash
cp .env.example .env        # 填写 HUB_CLIENT_ID / HUB_CLIENT_SECRET / SECRET_KEY
mkdir -p data cache
docker compose up -d        # 宿主机端口取 .env 中的 PORT（NAS 上为 5051，chatlogger 为 5050）
docker compose logs -f
```

挂载：`./data` 存 SQLite（`wikilogger.db`），`./cache` 存知识库镜像。

### 直接运行

```bash
pip install -r requirements.txt
cp .env.example .env
export $(cat .env | xargs) && python app.py                         # 开发
export $(cat .env | xargs) && gunicorn -c gunicorn_config.py app:app # 生产
```

> 同步进度存在进程内存，gunicorn 必须单 worker 多线程（`gunicorn_config.py` 已配置）。

Nginx 反代配置同 chatlogger，`server_name` 改为 `wikilogger.tmhcorps.cn`、`proxy_pass` 指向对应端口即可。

## 本地镜像结构

```text
cache/{知识库名}_{space_id}/
├── README.md                 目录索引（树形，链接到每篇文档）
├── _manifest.json            节点元数据（token、类型、路径、编辑时间、同步状态）
├── 产品规划.md                一级节点
├── 产品规划/                  其子节点（与同名 .md 并列）
│   ├── 需求文档.md
│   └── 会议纪要~a1b2c3.md     同级重名时追加 token 后 6 位
├── 数据表.md                  电子表格占位页，链接到导出的 xlsx
├── _assets/{obj_token}/      每篇文档的图片、附件、导出文件
└── _deleted/                 飞书侧已删除节点的最后一版
```

每篇文档头部带 YAML front matter（`title` / `node_token` / `obj_type` / `source` / `edit_time` / `synced_at`），便于导入 Obsidian、RAG 等工具。文档间链接形如 `[设计](<../研发/设计.md> "wiki:<node_token>")`，标题里的 `wiki:` 标记用于节点移动后重算相对路径。

## 同步规则

| 情况 | 处理 |
|---|---|
| 新节点 | 拉取并写入 |
| `obj_edit_time` / 标题 / 类型变化 | 重新拉取；图片按 token 复用不重复下载，未再引用的旧图片清理 |
| 仅位置变化（移动、父节点改名） | 本地移动文件，重算链接，不调用文档接口 |
| 飞书侧删除 / 失去权限 | 移入 `_deleted/`（`KEEP_DELETED=false` 时直接删除） |
| 文档拉取失败 | 写入占位页说明原因，下次同步自动重试 |
| 导出 / 下载失败（如缺权限） | 占位页标注 ⚠️，节点未再编辑前不重试 |
| token 失效 | 中止同步，提示重新登录 |

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HUB_URL` | `https://pm.tmhcorps.cn` | 认证跳板地址 |
| `HUB_CLIENT_ID` / `HUB_CLIENT_SECRET` | 必填 | pm-assist 注册信息 |
| `SECRET_KEY` | — | Flask Session 密钥 |
| `FEISHU_WEB_BASE` | `https://feishu.cn` | 「打开原文」链接域名，建议设为企业域名 |
| `DB_PATH` | `./wikilogger.db` | SQLite 路径 |
| `LOCAL_CACHE_DIR` | `./cache` | 镜像根目录 |
| `MAX_ATTACHMENT_SIZE_MB` | `50` | 单个图片 / 附件 / 导出文件上限 |
| `MAX_DOC_BLOCKS` | `20000` | 单篇文档最多转换的块数 |
| `MAX_NODES` | `20000` | 单个知识库最多遍历节点数 |
| `CACHE_DOC_IMAGES` / `CACHE_DOC_FILES` | `true` | 下载文档内图片 / 附件 |
| `EXPORT_OFFICE_FILES` | `true` | 表格类导出 xlsx、旧版文档导出 docx |
| `DOWNLOAD_WIKI_FILES` | `true` | 下载文件节点 |
| `KEEP_DELETED` | `true` | 删除节点保留到 `_deleted/` |
| `FETCH_CONCURRENCY` | `3` | 文档拉取并发数（总速率仍受限速约束） |
| `WIKI_API_PER_MIN` | `80` | 知识库接口限速 |
| `DOCX_API_PER_SEC` | `4` | 文档接口限速 |
| `DRIVE_DOWNLOAD_PER_SEC` | `4` | 素材 / 文件下载限速 |
| `EXPORT_API_PER_MIN` | `80` | 导出接口限速 |

## 注意事项

- 遍历和拉取使用登录用户的身份，只能看到本人有权限的节点；无权限的子树会被飞书静默过滤。
- 多人添加同一知识库时，各自独立镜像（目录名自动加后缀），互不覆盖。
- Windows 下深层目录可能触及 260 字符路径限制（单级名称已截断到 60 字符）；建议部署在 Linux / NAS，或开启 Windows 长路径支持。
- 同步期间与 chatlogger 共享飞书应用配额；大型知识库首次同步建议避开 chatlogger 批量同步的时段。

## 运行测试

```bash
python -m pytest tests/ -v
```

测试使用内存版飞书（`tests/fake_feishu.py`）模拟知识库接口的分页、权限过滤空页、快捷方式、限流重试与导出流程，覆盖遍历、增量、移动、改名、删除、停止续传与 Web 接口。
