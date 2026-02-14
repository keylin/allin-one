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
| **媒体项 (MediaItem)** | `MediaItem` | 内容关联的媒体文件 (图片/视频/音频)，ContentItem 一对多 MediaItem。由 localize_media 步骤创建。 |
| **采集记录** | `CollectionRecord` | 每次数据源采集的执行记录，独立于流水线。 |

## 2. 专有名词

| 名词 | 描述 |
| :--- | :--- |
| **RSSHub** | 开源项目，将各种网站 (B站、微博、YouTube) 转换为标准 RSS Feed。 |
| **Browserless** | 基于 Headless Chrome 的服务，用于网页渲染与抓取。 |
| **browser-use** | AI 驱动的浏览器操控框架，L3 级别抓取。 |
| **Huey** | Python 轻量级异步任务队列库，本项目使用 SQLite 后端。 |
| **yt-dlp** | 命令行视频下载工具，从 YouTube/Bilibili 等平台下载视频。 |
| **FFmpeg** | 音视频处理工具，用于转码、音频提取等。 |
| **DeepSeek** | 默认 LLM 服务提供商，兼容 OpenAI API 格式。 |
| **AkShare** | 金融数据接口库，用于获取宏观经济数据。 |

## 3. 枚举变量

### 3.1 SourceType (数据源类型)

只描述「信息从哪来」，不涉及处理逻辑。采用两段式命名 `{Category}.{Specific}`。
定义在 `app/models/content.py`。

| 枚举值 | 描述 | 备注 |
| :--- | :--- | :--- |
| `rss.hub` | RSSHub 生成的订阅源 | B站/YouTube/微博等都通过这个 |
| `rss.standard` | 标准 RSS/Atom 订阅源 | 博客、新闻站点 |
| `api.akshare` | AkShare 金融数据 | 宏观经济指标 |
| `web.scraper` | 网页抓取 | 内部分 L1/L2/L3 级别 |
| `file.upload` | 用户上传文件 | 文本/图片/文档 |
| `account.bilibili` | B站账号 | 需要 Cookie/登录态 |
| `account.generic` | 其他平台账号 | 需要认证的平台 |
| `user.note` | 日常笔记 | 用户手动输入 |
| `system.notification` | 系统消息 | 系统通知 |

### 3.2 StepType (原子操作类型)

定义在 `app/models/pipeline.py`。对照脑图「原子操作」。

| 枚举值 | 显示名 | 配置项 | 说明 |
| :--- | :--- | :--- | :--- |
| `enrich_content` | 抓取全文 | `scrape_level`: L1/L2/L3/auto | 预处理步骤，系统自动注入 |
| `localize_media` | 媒体本地化 | — | 预处理步骤，检测并下载图片/视频/音频，创建 MediaItem |
| `extract_audio` | 音频提取 | (待实现) | |
| `transcribe_content` | 语音转文字 | — | |
| `translate_content` | 文章翻译 | `target_language`: zh/en/ja... | |
| `analyze_content` | 模型分析 | `model`: 下拉枚举, `prompt_template_id`: 关联, `output_format`: json/markdown/text | |
| `publish_content` | 消息推送 | `channel`: email/dingtalk/webhook, `frequency`: immediate/daily | |

注意:
- 没有 `fetch_content`。数据抓取由定时器 + Collector 完成，不是流水线步骤。
- `enrich_content` 和 `localize_media` 是预处理步骤，由 Orchestrator 自动注入，用户模板中无需包含。
- 原 `download_video` 已被 `localize_media` 取代，后者统一处理所有媒体类型。

### 3.3 MediaType (媒体项类型)

MediaType 现在仅用于 `MediaItem`（媒体项），不再是 ContentItem 或 SourceConfig 的属性。

| 枚举值 | 描述 |
| :--- | :--- |
| `image` | 图片 |
| `video` | 视频 |
| `audio` | 音频 |

### 3.4 ContentStatus (内容状态)

| 枚举值 | 描述 |
| :--- | :--- |
| `pending` | 待处理 |
| `processing` | 处理中 |
| `ready` | 已就绪 (预处理完成，无后置流水线) |
| `analyzed` | 已分析 |
| `failed` | 失败 |

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

### 3.9 TemplateType (提示词模板类型)

| 枚举值 | 描述 |
| :--- | :--- |
| `news_analysis` | 新闻分析 |
| `summary` | 摘要 |
| `translation` | 翻译 |
| `custom` | 自定义 |

## 4. 内置流水线模板

定义在 `app/services/pipeline/registry.py`，首次启动写入数据库。

| 模板名称 | 包含步骤 (用户模板部分) | 适用场景 |
| :--- | :--- | :--- |
| 文章分析 | analyze → publish | 中文新闻/博客 |
| 英文文章翻译分析 | translate → analyze → publish | 英文站点 |
| 视频下载分析 | transcribe → analyze → publish | B站视频 |
| 视频翻译分析 | transcribe → translate → analyze → publish | YouTube 视频 |
| 仅分析 | analyze → publish | RSS 全文输出的源 |
| 仅推送 | publish | 纯通知, 不做分析 |

**关键变更**: 用户模板不再包含预处理步骤 (enrich_content / localize_media)。Orchestrator 会根据内容检测自动注入预处理步骤，然后拼接用户模板的后置步骤。启动时会自动更新内置模板的 steps_config。

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
| 关注某 B站 UP 主 | `rsshub` | `{"rsshub_route": "/bilibili/user/video/12345"}` | 视频下载分析 |
| 订阅 YouTube 频道 | `rsshub` | `{"rsshub_route": "/youtube/channel/UCxxx"}` | 视频翻译分析 |
| 读英文科技博客 | `rss_std` | URL: feeds.arstechnica.com | 英文文章翻译分析 |
| 读 36kr 新闻 | `rss_std` | URL: 36kr.com/feed | 文章分析 |
| 监控政府公告页 | `scraper` | `{"scrape_level": "L2", "selectors": {...}}` | 文章分析 |
| 跟踪宏观数据 | `akshare` | `{"indicator": "macro_china_cpi"}` | 仅分析 |
| 纯采集不处理 | `rss_std` | URL: any-feed.xml | (不绑定模板) |
