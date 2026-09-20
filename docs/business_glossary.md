# Allin-One 系统业务术语表 (Business Glossary)

> 基于脑图最新设计更新，核心变更: 数据源与流水线完全解耦

## 1. 核心业务概念

| 概念 | 代码对应 | 描述 |
| :--- | :--- | :--- |
| **数据源 (Source)** | `SourceConfig` | 信息的来源配置。只描述「从哪获取」，如一个 RSSHub 路由、一个 RSS 地址。 |
| **内容 (Content)** | `ContentItem` | 从数据源采集到的具体条目。包含原始内容→中间内容→最终内容三层。 |
| **流水线模板 (Template)** | `PipelineTemplate` | 预定义的一组有序原子步骤，定义「怎么处理」。可绑定到任意数据源。 |
| **流水线执行 (Execution)** | `PipelineExecution` | 一次具体的流水线运行实例。 |
| **步骤 (Step)** | `PipelineStep` | 流水线中的原子操作执行记录。 |
| **原子操作类型 (StepType)** | `StepType` 枚举 | 步骤的操作类型，如"抓取全文"、"媒体本地化"、"模型分析"。 |
| **提示词 (Prompt)** | `PromptTemplate` | 指导 LLM 进行分析的指令模板。 |
| **媒体项 (MediaItem)** | `MediaItem` | 内容关联的媒体文件 (图片/视频/音频/电子书)，ContentItem 一对多 MediaItem。由 localize_media 步骤创建。 |
| **采集记录** | `CollectionRecord` | 每次数据源采集的执行记录，独立于流水线。 |

## 2. 专有名词

| 名词 | 描述 |
| :--- | :--- |
| **RSSHub** | 开源项目，将各种网站 (B站、微博、YouTube) 转换为标准 RSS Feed。 |
| **Browserless** | 基于 Headless Chrome 的服务，用于网页渲染与抓取。 |
| **browser-use** | AI 驱动的浏览器操控框架，L3 级别抓取。 |
| **Procrastinate** | Python 异步任务队列库，基于 PostgreSQL 后端，与应用共用同一数据库。 |
| **yt-dlp** | 命令行视频下载工具，从 YouTube/Bilibili 等平台下载视频。 |
| **FFmpeg** | 音视频处理工具，用于转码、音频提取等。 |
| **DeepSeek** | 默认 LLM 服务提供商，兼容 OpenAI API 格式。 |
| **AkShare** | 金融数据接口库，用于获取宏观经济数据。 |
| **Fountain 模式** | 数据由 Tauri 桌面客户端主动读取本地数据或调用平台 API 后推送给后端，适用于个人私有数据（阅读历史、标注、书签）。 |
| **Collect 模式** | 后端 Procrastinate worker 定时拉取公网数据，由 Collector 实现，适用于 RSS/网页/API 等公开内容。 |

## 3. 枚举变量

### 3.1 SourceType (数据源类型)

只描述「信息从哪来」，不涉及处理逻辑。采用两段式命名 `{Category}.{Specific}`。
定义在 `app/models/content.py`。

数据源分为两大类（`SourceCategory`）：
- **network（网络数据）**: 有 Collector，定时自动采集，需要 URL/配置
- **user（用户数据）**: 无 Collector（或目录扫描），用户/系统主动提交，无调度

分类由 `get_source_category(source_type)` 函数根据前缀自动推导，无需 DB 列。

| 枚举值 | 分类 | 描述 | 备注 |
| :--- | :--- | :--- | :--- |
| `rss.hub` | network | RSSHub 生成的订阅源 | B站/YouTube/微博等都通过这个 |
| `rss.standard` | network | 标准 RSS/Atom 订阅源 | 博客、新闻站点 |
| `api.akshare` | network | AkShare 金融数据 | 宏观经济指标 |
| `web.scraper` | network | 网页抓取 | 内部分 L1/L2/L3 级别 |
| `podcast.apple` | network | Apple Podcasts | 播客 RSS 解析 |
| `account.generic` | network | 其他平台账号 | 需要认证的平台 |
| `sync.apple_books` | user | Apple Books 同步 | Fountain 客户端读取 macOS BKLibrary SQLite 推送书籍+标注 |
| `sync.wechat_read` | user | 微信读书同步 | 内置同步器（服务端存加密凭证）；也接受外部脚本推送 |
| `sync.bilibili` | user | B站视频同步 | 内置同步器；也接受外部脚本推送 |
| `sync.kindle` | user | Kindle 标注同步 | Fountain 客户端读取 My Clippings.txt 推送标注 |
| `sync.safari_bookmarks` | user | Safari 书签同步 | Fountain 客户端读取本地书签库推送 |
| `sync.chrome_bookmarks` | user | Chrome 书签同步 | Fountain 客户端读取本地书签文件推送 |
| `sync.douban_books` | user | 豆瓣书单同步 | **未实现**（只占枚举值，不允许建源） |
| `sync.douban_movies` | user | 豆瓣影单同步 | **未实现**（影视库二期预留，不允许建源） |
| `sync.emby` | user | Emby 媒体库同步 | Worker 内置 Fetcher 只读拉取 Emby 电影/剧集与观看状态，写入影视资料库；页面手动触发 + 每 30 分钟自动同步 |
| `sync.zhihu` | user | 知乎收藏夹同步 | **未实现** |
| `sync.github_stars` | user | GitHub Star 同步 | **未实现** |
| `sync.twitter` | user | Twitter/X 推文同步 | **未实现**（`twitter` 凭证仅供 RSSHub 路由使用） |
| `user.note` | user | 日常笔记 | 用户手动输入，通过 `/api/content/submit` 提交 |
| `user.film` | user | 手工添加的影片 | 影视资料库手工/agent 添加的影片，经 TMDb 补元数据或片名+年份骨架 |
| `file.upload` | user | 用户上传文件 | 文本/图片/文档，通过 `/api/content/upload` 上传 |
| `system.notification` | user | 系统消息 | 系统通知 |

### 3.10 SourceCategory 与执行器

定义在 `app/models/source_types.py`（源类型注册表）。**都不是 DB 列**，由 `source_type` 查注册表得到；不要按字符串前缀判断。

| SourceCategory | 含义 | 后果 |
| :--- | :--- | :--- |
| `network` | 网络数据，由采集器抓取 | 内容会过期，按保留期自动清理 |
| `user` | 用户数据：同步进来的资料、用户笔记、上传文件、手工影片 | **永不自动清理**；有内容时拒绝非级联删除数据源 |

| Runner（执行器） | 含义 |
| :--- | :--- |
| `collector` | 采集：增量追加，可调度，运行记录在 `collection_records` |
| `syncer` | 内置同步：全量对账，运行记录在 `sync_task_progress`，可按 `auto_sync_minutes` 自动同步 |
| `push` | 外部推送：本机脚本 / Fountain 客户端经推送 API 写入，同样记 `sync_task_progress` |
| `none` | 无执行器：纯归属容器（`user.film`、`user.note`）或尚未实现 |

完整对照见 `docs/system_design.md` §4.0。

**术语约定**：实体统一叫「**数据源**」（界面、接口文案、文档一致；「订阅源」专指 RSS feed 本身）。动作上，「**采集**」专指 collector 的增量抓取，「**同步**」专指 syncer / push 的全量对账，「抓取」只用于全文抓取（enrich）这一步。

### 3.2 StepType (原子操作类型)

定义在 `app/models/pipeline.py`。对照脑图「原子操作」。

| 枚举值 | 显示名 | 配置项 | 说明 |
| :--- | :--- | :--- | :--- |
| `extract_content` | 提取内容 | — | 从 raw_data 提取文本到 processed_content |
| `enrich_content` | 抓取全文 | `scrape_level`: L1/L2/L3/auto | 三级递进全文抓取 |
| `localize_media` | 媒体本地化 | — | 检测并下载图片/视频/音频，创建 MediaItem |
| `extract_audio` | 音频提取 | (待实现) | |
| `transcribe_content` | 语音转文字 | — | |
| `translate_content` | 文章翻译 | `target_language`: zh/en/ja... | |
| `analyze_content` | 模型分析 | `model`: 下拉枚举, `prompt_template_id`: 关联, `output_format`: json/markdown/text | |
| `publish_content` | 消息推送 | `channel`: email/dingtalk/webhook/none, `frequency`: immediate/hourly/daily | |

注意:
- 没有 `fetch_content`。数据抓取由定时器 + Collector 完成，不是流水线步骤。
- 模板显式包含所有步骤（含 `extract_content`、`localize_media`），Orchestrator 不再自动注入预处理步骤。
- 原 `download_video` 已被 `localize_media` 取代，后者统一处理所有媒体类型。

### 3.3 MediaType (媒体项类型)

MediaType 现在仅用于 `MediaItem`（媒体项），不再是 ContentItem 或 SourceConfig 的属性。

| 枚举值 | 描述 |
| :--- | :--- |
| `image` | 图片 |
| `video` | 视频 |
| `audio` | 音频 |
| `ebook` | 电子书 |

### 3.4 ContentStatus (内容状态)

| 枚举值 | 描述 |
| :--- | :--- |
| `pending` | 待处理 |
| `processing` | 处理中 |
| `ready` | 已就绪 (预处理完成，无后置流水线) |
| `analyzed` | 已分析 |
| `failed` | 失败 |


### 3.5 ContentKind (内容的领域身份)

`content_items.kind`，写入时确定、之后不变。**「这是什么内容」只看这一列**——不要从 `source_type`、`media_items.media_type` 或 `raw_data` 里的键反推（2026-09 审计前有 6 种并存的判定方式）。

| 值 | 含义 | 主线 |
|---|---|---|
| `article` | 信息流条目（RSS / 网页抓取 / 账号采集），默认值 | 信息流 |
| `audio` | 播客单集 | 信息流 |
| `video` | 视频（平台同步 / 手动下载） | 资料库 |
| `book` | 电子书 | 资料库 |
| `film` | 影视（电影 / 剧集） | 资料库 |
| `bookmark` | 浏览器书签 | 资料库 |
| `note` | 用户笔记 | 资料库 |
| `file` | 用户上传 / 目录扫描的文件 | 资料库 |

- **两条主线**：信息流是时效性内容，会过期、按保留期清理；资料库是用户的长期资产，永不自动清理。
- **信息流口径** `FEED_SCOPE`：通用内容列表、未读数、全部已读、仪表盘、日报周报、MCP `list_content` 都带这个过滤，排除有专属页面的资料库领域（目前是 `film`）。
- 影片跨 `sync.emby` / `user.film` 两个数据源，全局唯一性由部分唯一索引 `uq_content_film_external`（`external_id WHERE kind='film'`）保证。
- 与 `MediaType` 的区别：MediaType 描述一个媒体项是什么文件；ContentKind 描述一条内容属于哪个领域。一篇带视频的 RSS 文章仍是 `article`。

### 3.5 PipelineStatus (流水线状态)

| 枚举值 | 描述 |
| :--- | :--- |
| `pending` | 等待中 |
| `running` | 运行中 |
| `completed` | 已完成 |
| `failed` | 失败 |
| `paused` | 已暂停 |
| `cancelled` | 已取消 |

### 3.6 StepStatus (步骤状态)

| 枚举值 | 描述 |
| :--- | :--- |
| `pending` | 等待中 |
| `running` | 运行中 |
| `completed` | 已完成 |
| `failed` | 失败 |
| `skipped` | 已跳过 (非关键步骤失败) |

### 3.7 CollectionRecordStatus (采集记录状态)

| 枚举值 | 描述 |
| :--- | :--- |
| `running` | 采集中 |
| `completed` | 成功 |
| `failed` | 失败 |

### 3.8 TriggerSource (触发来源)

| 枚举值 | 描述 |
| :--- | :--- |
| `scheduled` | 定时任务 |
| `manual` | 手动触发 |
| `api` | API 调用 |
| `webhook` | 外部 Webhook |
| `favorite` | 收藏时自动触发媒体下载 |

### 3.9 TemplateType (提示词模板类型)

| 枚举值 | 描述 |
| :--- | :--- |
| `news_analysis` | 新闻分析 |
| `summary` | 摘要 |
| `translation` | 翻译 |
| `custom` | 自定义 |

## 4. 内置流水线模板

定义在 `app/services/pipeline/registry.py`，首次启动写入数据库。

| 模板名称 | 包含步骤 | 适用场景 |
| :--- | :--- | :--- |
| 文章分析 | extract → localize → analyze → publish | 中文新闻/博客 |
| 英文文章翻译分析 | extract → localize → translate → analyze → publish | 英文站点 |
| 视频下载分析 | extract → localize → transcribe → analyze → publish | B站视频 |
| 视频翻译分析 | extract → localize → transcribe → translate → analyze → publish | YouTube 视频 |
| 仅分析 | extract → analyze → publish | RSS 全文输出的源 |
| 仅推送 | extract → publish | 纯通知, 不做分析 |
| 金融数据分析 | extract → analyze → publish | AkShare 宏观数据 |
| 媒体下载 | localize | 仅执行媒体本地化（收藏触发或手动下载） |

**说明**: 模板包含所有步骤（含 extract_content、localize_media），Orchestrator 不再自动注入预处理步骤。

## 5. 术语使用规范

全系统 (前端 UI、后端注释、文档) 必须遵守以下用词规则，避免同一概念出现多种说法。

### 5.1 模板 (板, 非"版")

统一使用 **"模板"**，禁止使用"模版"。包括流水线模板、提示词模板等所有场景。

### 5.2 采集 vs 抓取

| 术语 | 语义 | 适用场景 |
| :--- | :--- | :--- |
| **采集** | Collector 从数据源收集内容的通用动作 | 采集时间、定时采集、最近采集、采集记录、立即采集、采集中 |
| **抓取** | `enrich_content` 步骤的全文提取、`web.scraper` 的网页爬取 | 抓取全文、网页抓取、抓取方式、抓取级别 |

- `collected_at` 字段统一显示为 **"采集时间"**
- `enrich_content` 步骤显示名为 **"抓取全文"**

### 5.3 创建操作按钮

| 位置 | 用词 |
| :--- | :--- |
| 列表页创建按钮 | **新增** |
| Modal 标题 (新建) | **新增XXX** (如"新增数据源") |
| Modal 标题 (编辑) | **编辑XXX** (如"编辑数据源") |

### 5.4 状态标签格式

- 已完成的状态加"已"前缀: 已完成、已暂停、已取消、已跳过、已分析
- 进行中的状态: 等待中、运行中、处理中、采集中
- 异常状态: 失败、待处理

## 6. 组合示例 (数据源 + 流水线)

| 使用场景 | 数据源类型 | 数据源配置 | 绑定流水线 |
| :--- | :--- | :--- | :--- |
| 关注某 B站 UP 主 | `rss.hub` | `{"rsshub_route": "/bilibili/user/video/12345"}` | 视频下载分析 |
| 订阅 YouTube 频道 | `rss.hub` | `{"rsshub_route": "/youtube/channel/UCxxx"}` | 视频翻译分析 |
| 读英文科技博客 | `rss.standard` | URL: feeds.arstechnica.com | 英文文章翻译分析 |
| 读 36kr 新闻 | `rss.standard` | URL: 36kr.com/feed | 文章分析 |
| 监控政府公告页 | `web.scraper` | `{"scrape_level": "L2", "selectors": {...}}` | 文章分析 |
| 跟踪宏观数据 | `api.akshare` | `{"indicator": "macro_china_cpi"}` | 金融数据分析 |
| 纯采集不处理 | `rss.standard` | URL: any-feed.xml | (不绑定模板) |

以下为 Fountain 模式场景（数据源 `sync.*`，无需配置流水线模板，数据由 Fountain 客户端推送）：

### 场景 4：B 站个人观看历史同步
- **数据源类型**：`sync.bilibili`（SourceCategory.USER）
- **接入模式**：Fountain (internal 模式) — 通过 `/api/sync/run/sync.bilibili` 在服务端触发，或外部脚本 `scripts/bilibili-sync.py`
- **API 流程**：`POST /api/sync/run/sync.bilibili` (内置) 或 `POST /api/video/sync/setup` → `GET /api/video/sync/status` → `POST /api/video/sync` (脚本)
- **流水线模板**：媒体下载（仅收藏的视频触发 localize_media）

### 场景 5：Apple Books 阅读标注同步
- **数据源类型**：`sync.apple_books`（SourceCategory.USER）
- **接入模式**：Fountain (script 模式) — Rust 同步器读取 macOS BKLibrary SQLite，或外部脚本 `scripts/apple-books-sync.py`
- **API 流程**：`POST /api/ebook/sync/setup` → `GET /api/ebook/sync/status` → `POST /api/ebook/sync`
- **流水线模板**：无（标注写入 book_annotations 表）

### 场景 7：Emby 影视资料库同步
- **数据源类型**：`sync.emby`（SourceCategory.USER）
- **接入模式**：Fountain (internal 模式) — `POST /api/sync/run/sync.emby`，SyncView / 影视库页手动触发，另每 30 分钟自动同步一次（`auto_sync_sources`）
- **凭证**：`platform=emby`，`credential_type=api_key`，`extra_info={base_url, user_name, user_id}`
- **数据落点**：ContentItem（元数据 + `raw_data.emby` 观看事实）+ `watch_records`（用户标记，同步只填空不覆盖）
- **详细设计**：`docs/design_film_library.md`

### 场景 6：微信读书同步
- **数据源类型**：`sync.wechat_read`（SourceCategory.USER）
- **接入模式**：Fountain (internal 模式) — 通过 `/api/sync/run/sync.wechat_read` 在服务端触发
- **API 流程**：`POST /api/sync/run/sync.wechat_read` (内置)，支持 SSE 进度推送 (`GET /api/sync/progress/{id}`)
- **流水线模板**：无（标注写入 book_annotations 表）
