# Allin-One 系统方案

> 版本: v1.3 | 更新日期: 2026-02-25

---

## 1. 架构总览

> 💡 **提示**: 任务调度与流水线引擎的详细设计请参考独立文档: [docs/design_scheduler_pipeline.md](./design_scheduler_pipeline.md)

### 1.1 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                      用户层 (User Layer)                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  Web UI (Vue) │  │  REST API    │  │  Webhook     │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
└─────────┼──────────────────┼──────────────────┼──────────┘
          │                  │                  │
┌─────────┼──────────────────┼──────────────────┼──────────┐
│         ▼                  ▼                  ▼          │
│  ┌─────────────────────────────────────────────────┐     │
│  │              FastAPI Application                 │     │
│  │  ┌─────────┐ ┌─────────────────┐                │     │
│  │  │ Router  │ │ Static Files    │                │     │
│  │  │ Layer   │ │ (Vue dist/)     │                │     │
│  │  └────┬────┘ └─────────────────┘                │     │
│  │       │                                          │     │
│  │  ┌────▼──────────────────────────────────────┐  │     │
│  │  │           Service Layer                    │  │     │
│  │  │  ┌──────────────────────────────────────┐  │  │     │
│  │  │  │     Pipeline Orchestrator             │  │  │     │
│  │  │  │  ┌────────┐ ┌─────────┐ ┌─────────┐  │  │  │     │
│  │  │  │  │Registry│ │Executor │ │Template │  │  │  │     │
│  │  │  │  └────────┘ └─────────┘ └─────────┘  │  │  │     │
│  │  │  └──────────────────────────────────────┘  │  │     │
│  │  └────────────────────┬───────────────────────┘  │     │
│  └───────────────────────┼──────────────────────────┘     │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────┐     │
│  │      Procrastinate Workers (异步任务层)           │     │
│  │  ┌──────────────────┐ ┌──────────────────────┐  │     │
│  │  │ pipeline 队列     │ │ scheduled 队列        │  │     │
│  │  │ (concurrency=4)  │ │ (concurrency=2)      │  │     │
│  │  │ enrich/analyze/  │ │ 采集循环/日报/清理     │  │     │
│  │  │ localize/publish │ │                       │  │     │
│  │  └──────────────────┘ └──────────────────────┘  │     │
│  └───────┼───────────┼───────────┼─────────────────┘     │
│                                                           │
│       处理层 (Processing Layer)                            │
└───────┼───────────┼───────────┼──────────────────────────┘
        │           │           │
┌───────┼───────────┼───────────┼──────────────────────────┐
│       ▼           ▼           ▼                          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │ RSSHub  │ │Browser- │ │ yt-dlp  │ │ LLM API │       │
│  │         │ │ less    │ │         │ │(DeepSeek)│       │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │
│                                                          │
│       外部服务层 (External Services)                       │
└──────────────────────────────────────────────────────────┘
        │           │           │           │
┌───────┼───────────┼───────────┼───────────┼──────────────┐
│       ▼           ▼           ▼           ▼              │
│  ┌────────────┐ ┌──────────────────────────────────┐     │
│  │ PostgreSQL │ │ File System                      │     │
│  │(应用数据 +  │ │ data/media/ data/logs/           │     │
│  │ 任务队列)   │ │ data/reports/                    │     │
│  └────────────┘ └──────────────────────────────────┘     │
│                                                          │
│       数据层 (Data Layer)                                 │
└──────────────────────────────────────────────────────────┘
```

### 1.2 进程模型

系统运行时包含以下进程:

| 进程 | 容器 | 职责 |
|------|------|------|
| FastAPI (uvicorn) | allin-one | Web 服务、API、静态文件服务 |
| Procrastinate Worker (pipeline) | allin-worker-pipeline | 流水线步骤执行 (concurrency=4) |
| Procrastinate Worker (scheduled) | allin-worker-scheduled | 定时采集/报告/清理 (concurrency=2) |
| PostgreSQL | allin-postgres | 主数据库 + Procrastinate 任务队列 |
| RSSHub | allin-rsshub | RSS 转换服务 |
| Browserless | allin-browserless | 无头浏览器服务 |

---

## 2. 数据库设计

### 2.1 ER 关系图

```
pipeline_templates 1─ ─ ─ ─ ┐ (绑定)
                             ▼
source_configs 1───∞ content_items 1───∞ pipeline_executions 1───∞ pipeline_steps
      │                  │                       │
      │                  └──1───∞ media_items     └──── template_id → pipeline_templates
      │
      └──1───∞ collection_records

prompt_templates (独立, 被 step_config 引用)
system_settings  (独立配置表)

platform_credentials 1─ ─ ─ ─∞ source_configs  (credential_id FK)

source_configs 1───∞ finance_data_points  (source_id FK)
```

**核心解耦关系**: `source_configs.pipeline_template_id → pipeline_templates.id`
数据源通过此外键绑定流水线模板，而非硬编码映射。

### 2.2 表结构详细定义

#### source_configs (数据源配置)

只描述「从哪获取信息」，source_type 不含视频平台等混合类型。

数据源分为两大类（派生属性，非 DB 列）：
- **网络数据 (network)**: rss.hub, rss.standard, api.akshare, web.scraper, podcast.apple, account.generic — 有 Collector，定时自动采集
- **用户数据 (user)**: user.note, file.upload, system.notification, sync.apple_books, sync.wechat_read, sync.bilibili — 用户/系统主动提交或外部脚本推送，schedule_enabled 自动置 false

通用内容提交 API：`POST /api/content/submit`（文本）、`POST /api/content/upload`（文件），校验目标源必须为 user 分类。

```sql
CREATE TABLE source_configs (
    id              TEXT PRIMARY KEY,           -- UUID
    name            TEXT NOT NULL,              -- 源名称 (e.g. "B站-某UP主")
    source_type     TEXT NOT NULL,              -- 来源渠道: rss.hub/rss.standard/web.scraper/api.akshare/podcast.apple/...
    url             TEXT,                       -- 订阅/采集地址
    description     TEXT,
    -- 调度
    schedule_enabled BOOLEAN DEFAULT TRUE,
    schedule_mode   TEXT DEFAULT 'auto',        -- auto / fixed / manual
    schedule_interval_override INTEGER,         -- 固定间隔覆盖值（仅 fixed 模式）
    calculated_interval INTEGER,                -- 系统计算的间隔（仅供展示）
    next_collection_at DATETIME,                -- 预计算的下次采集时间
    -- 高级调度
    periodicity_data TEXT,                      -- 周期模式识别结果 JSON
    periodicity_updated_at DATETIME,            -- 周期分析更新时间
    hotspot_level   TEXT,                       -- 热点等级: extreme/high/instant
    hotspot_detected_at DATETIME,               -- 热点检测时间
    -- 流水线绑定
    pipeline_template_id TEXT,                  -- 绑定的流水线模板 (解耦关键!)
    config_json     TEXT,                       -- 渠道特定配置 (JSON)
    credential_id   TEXT,                       -- 关联的平台凭证
    -- 内容保留
    auto_cleanup_enabled BOOLEAN DEFAULT FALSE, -- 启用自动清理
    retention_days  INTEGER,                    -- 内容保留天数 (null=使用全局默认)
    -- 运行状态
    last_collected_at DATETIME,
    consecutive_failures INTEGER DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pipeline_template_id) REFERENCES pipeline_templates(id),
    FOREIGN KEY (credential_id) REFERENCES platform_credentials(id)
);

CREATE INDEX ix_source_credential_id ON source_configs(credential_id);
CREATE INDEX ix_source_next_collection ON source_configs(is_active, schedule_enabled, next_collection_at);
```

#### collection_records (数据源抓取记录)

独立于 Pipeline，记录每次数据源采集结果。

```sql
CREATE TABLE collection_records (
    id              TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL,
    status          TEXT DEFAULT 'running',     -- running/completed/failed
    items_found     INTEGER DEFAULT 0,
    items_new       INTEGER DEFAULT 0,
    error_message   TEXT,
    started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at    DATETIME,
    FOREIGN KEY (source_id) REFERENCES source_configs(id)
);
```

#### content_items (内容项)

```sql
CREATE TABLE content_items (
    id              TEXT PRIMARY KEY,           -- UUID
    source_id       TEXT,                       -- 外键 -> source_configs (SET NULL on delete)
    title           TEXT NOT NULL,              -- 内容标题
    external_id     TEXT NOT NULL,              -- 外部唯一标识 (URL hash)
    url             TEXT,                       -- 原始链接
    author          TEXT,                       -- 作者
    raw_data        TEXT,                       -- 原始数据 (JSON)
    processed_content TEXT,                     -- 清洗后全文
    analysis_result TEXT,                       -- LLM 分析结果 (JSON/Markdown/Text)
    status          TEXT DEFAULT 'pending',     -- ContentStatus 枚举 (pending/processing/ready/analyzed/failed)
    language        TEXT,                       -- 内容语言 (zh/en/ja...)
    published_at    DATETIME,                   -- 原始发布时间
    collected_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_favorited    BOOLEAN DEFAULT FALSE,      -- 是否收藏
    favorited_at    DATETIME,                   -- 收藏时间
    user_note       TEXT,                       -- 用户笔记
    chat_history    TEXT,                       -- AI 对话历史 (JSON: [{role, content}, ...])
    view_count      INTEGER DEFAULT 0,           -- 浏览次数
    last_viewed_at  DATETIME,                     -- 最后浏览时间
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES source_configs(id) ON DELETE SET NULL,
    UNIQUE (source_id, external_id)            -- 去重约束
);

CREATE INDEX idx_content_status ON content_items(status);
CREATE INDEX idx_content_source ON content_items(source_id);
CREATE INDEX idx_content_collected ON content_items(collected_at);
CREATE INDEX idx_content_external ON content_items(external_id);
```

#### media_items (媒体项)

ContentItem 一对多 MediaItem，由 `localize_media` 步骤创建。

```sql
CREATE TABLE media_items (
    id              TEXT PRIMARY KEY,           -- UUID
    content_id      TEXT NOT NULL,              -- 外键 -> content_items
    media_type      TEXT NOT NULL,              -- MediaType: image/video/audio
    original_url    TEXT NOT NULL,              -- 远程 URL
    local_path      TEXT,                       -- 下载后的本地路径
    filename        TEXT,                       -- 本地文件名
    status          TEXT DEFAULT 'pending',     -- pending/downloaded/failed
    metadata_json   TEXT,                       -- JSON: 类型特定元数据 (thumbnail_path, duration 等)
    playback_position INTEGER DEFAULT 0,       -- 播放进度（秒）
    last_played_at  DATETIME,                  -- 最后播放时间
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (content_id) REFERENCES content_items(id)
);

CREATE INDEX ix_media_item_content_id ON media_items(content_id);
```

#### pipeline_executions (流水线执行记录)

```sql
CREATE TABLE pipeline_executions (
    id              TEXT PRIMARY KEY,
    content_id      TEXT NOT NULL,               -- 外键 -> content_items
    source_id       TEXT,                       -- 外键 -> source_configs
    template_id     TEXT,                       -- 外键 -> pipeline_templates
    template_name   TEXT,                       -- 冗余存储, 方便展示
    status          TEXT DEFAULT 'pending',
    current_step    INTEGER DEFAULT 0,
    total_steps     INTEGER DEFAULT 0,
    trigger_source  TEXT DEFAULT 'manual',
    error_message   TEXT,
    started_at      DATETIME,
    completed_at    DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (content_id) REFERENCES content_items(id),
    FOREIGN KEY (source_id) REFERENCES source_configs(id),
    FOREIGN KEY (template_id) REFERENCES pipeline_templates(id)
);
```

#### pipeline_steps (步骤执行记录)

```sql
CREATE TABLE pipeline_steps (
    id              TEXT PRIMARY KEY,
    pipeline_id     TEXT NOT NULL,
    step_index      INTEGER NOT NULL,
    step_type       TEXT NOT NULL,              -- 原子操作类型 (StepType 枚举)
    step_config     TEXT,                       -- 操作配置 (JSON, 从模板复制)
    status          TEXT DEFAULT 'pending',
    is_critical     BOOLEAN DEFAULT FALSE,
    input_data      TEXT,                       -- 输入 (JSON)
    output_data     TEXT,                       -- 输出 (JSON)
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    started_at      DATETIME,
    completed_at    DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pipeline_id) REFERENCES pipeline_executions(id)
);
```

#### pipeline_templates (流水线模板)

```sql
CREATE TABLE pipeline_templates (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT,
    steps_config    TEXT NOT NULL,              -- 步骤定义列表 (JSON)
    is_builtin      BOOLEAN DEFAULT FALSE,     -- 是否内置模板
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

`steps_config` JSON 结构 — 模板包含所有步骤（含 extract_content、localize_media），Orchestrator 不再自动注入:
```json
[
  {"step_type": "extract_content",  "is_critical": true,  "config": {}},
  {"step_type": "localize_media",   "is_critical": false, "config": {}},
  {"step_type": "analyze_content",  "is_critical": true,  "config": {}},
  {"step_type": "publish_content",  "is_critical": false, "config": {"channel": "none"}}
]
```

#### prompt_templates (提示词模板)

```sql
CREATE TABLE prompt_templates (
    id              TEXT PRIMARY KEY,           -- UUID
    name            TEXT NOT NULL,              -- 模板名称
    template_type   TEXT DEFAULT 'news_analysis', -- TemplateType 枚举
    system_prompt   TEXT,                       -- 系统提示词
    user_prompt     TEXT NOT NULL,              -- 用户提示词 (支持变量插值)
    output_format   TEXT,                       -- 期望输出格式描述
    is_default      BOOLEAN DEFAULT FALSE,      -- 是否为默认模板
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### system_settings (系统设置)

```sql
CREATE TABLE system_settings (
    key             TEXT PRIMARY KEY,           -- 配置键
    value           TEXT,                       -- 配置值；api_key/token/secret 等敏感键使用 Fernet 加密存储
    description     TEXT,                       -- 说明
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### platform_credentials (平台凭证)

集中管理 Cookie/Token 等平台认证信息，多个数据源可引用同一凭证。

```sql
CREATE TABLE platform_credentials (
    id              TEXT PRIMARY KEY,           -- UUID
    platform        TEXT NOT NULL,              -- 平台标识: bilibili/twitter/...
    credential_type TEXT DEFAULT 'cookie',      -- cookie/oauth_token/api_key
    credential_data TEXT NOT NULL,              -- 凭证内容 (加密存储)
    display_name    TEXT NOT NULL,              -- 显示名称
    status          TEXT DEFAULT 'active',      -- active/expired/error
    expires_at      DATETIME,                   -- 过期时间
    extra_info      TEXT,                       -- JSON: 附加信息 (uid, username 等)
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_credential_platform ON platform_credentials(platform);
```

#### finance_data_points (金融数据点)

专用列式存储金融数值数据，替代 ContentItem 的 raw_data JSON 存储。按数据类型使用不同列：宏观用 value，股票用 OHLCV，基金用 NAV。

```sql
CREATE TABLE finance_data_points (
    id              TEXT PRIMARY KEY,           -- UUID
    source_id       TEXT NOT NULL,              -- 外键 -> source_configs
    category        TEXT NOT NULL DEFAULT 'unknown', -- 数据分类: macro/stock/fund
    date_key        TEXT NOT NULL,              -- 原始日期格式: "2024-01-15", "2024-01", "2024Q3"
    published_at    DATETIME,                   -- 解析后标准时间 (用于排序和范围查询)
    -- 宏观指标
    value           FLOAT,                      -- 单值指标 (CPI, GDP 等)
    -- OHLCV (股票/ETF)
    open            FLOAT,
    high            FLOAT,
    low             FLOAT,
    close           FLOAT,
    volume          FLOAT,
    -- 基金净值
    unit_nav        FLOAT,                      -- 单位净值
    cumulative_nav  FLOAT,                      -- 累计净值
    -- 分析
    alert_json      TEXT,                       -- 告警信息 (JSON)
    analysis_result TEXT,                       -- LLM 分析结果
    collected_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES source_configs(id)
);

CREATE UNIQUE INDEX uq_finance_source_date ON finance_data_points(source_id, date_key);
CREATE INDEX ix_finance_source_date ON finance_data_points(source_id, date_key);
```

---

## 3. Pipeline 引擎设计

### 3.1 核心类结构

```python
# app/services/pipeline/registry.py

STEP_DEFINITIONS = {
    # 原子操作注册表 — 没有 fetch_content (抓取由定时器+Collector完成)
    "extract_content":     StepDefinition(display_name="提取内容",   description="从 raw_data 提取文本到 processed_content"),
    "enrich_content":      StepDefinition(display_name="抓取全文",   config_schema={"scrape_level": "L1/L2/L3/auto"}),
    "localize_media":      StepDefinition(display_name="媒体本地化", description="检测并下载图片/视频/音频，创建 MediaItem"),
    "extract_audio":       StepDefinition(display_name="音频提取"),
    "transcribe_content":  StepDefinition(display_name="语音转文字"),
    "translate_content":   StepDefinition(display_name="文章翻译",   config_schema={"target_language": "zh"}),
    "analyze_content":     StepDefinition(display_name="模型分析",   config_schema={"model": "下拉枚举", "prompt_template_id": "关联"}),
    "publish_content":     StepDefinition(display_name="消息推送",   config_schema={"channel": "email/dingtalk/webhook/none", "frequency": "immediate/hourly/daily"}),
}

# 模板包含所有步骤（含 extract_content、localize_media），不再由 Orchestrator 自动注入
BUILTIN_TEMPLATES = [
    {"name": "文章分析",         "steps": ["extract → localize → analyze → publish"]},
    {"name": "英文文章翻译分析", "steps": ["extract → localize → translate → analyze → publish"]},
    {"name": "视频下载分析",     "steps": ["extract → localize → transcribe → analyze → publish"]},
    {"name": "视频翻译分析",     "steps": ["extract → localize → transcribe → translate → analyze → publish"]},
    {"name": "仅分析",          "steps": ["extract → analyze → publish"]},
    {"name": "仅推送",          "steps": ["extract → publish"]},
    {"name": "金融数据分析",     "steps": ["extract → analyze → publish"]},
    {"name": "媒体下载",         "steps": ["localize"]},
]
```

```python
# app/services/pipeline/orchestrator.py
class PipelineOrchestrator:
    """编排器 - 为已存在的 ContentItem 创建流水线执行

    有模板才创建流水线，无模板直接标记 READY。
    步骤完全来自模板（包含 extract_content、localize_media 等），不再自动注入。
    """

    def get_template_for_source(self, source: SourceConfig) -> PipelineTemplate | None:
        """获取源绑定的模板, 未绑定返回 None (纯采集场景)"""

    def trigger_for_content(self, content: ContentItem, template_override_id=None, trigger=...) -> PipelineExecution | None:
        """为一条已存在的 ContentItem 创建并启动流水线
        有模板才创建流水线，无模板直接标记 READY。"""
```

```python
# app/services/pipeline/executor.py
class PipelineExecutor:
    """执行器 - 按 step_type 分派到处理函数, 传入 step_config"""
    
    def get_step_context(self, execution_id, step_index) -> dict:
        """返回 {step_type, step_config, previous_steps, source_id, content_id}"""
        
    def advance_pipeline(self, execution_id) -> None:
        """推进或标记完成"""
```

### 3.2 步骤执行流程

```
Pipeline 创建
     │
     ▼
┌─── Step[0] 执行 ───┐
│  Procrastinate 任务  │
│  ┌────────────────┐  │
│  │ 成功 → output   │──│──▶ 推进到 Step[1]
│  │ 失败 & 关键步骤  │──│──▶ Pipeline 标记失败
│  │ 失败 & 非关键    │──│──▶ Step 标记 skipped，推进到 Step[1]
│  │ 重试 (≤3次)     │──│──▶ 重新执行当前步骤
│  └────────────────┘  │
└──────────────────────┘
     │
     ▼
   ... 重复直到所有步骤完成 ...
     │
     ▼
Pipeline 标记 completed
```

### 3.3 步骤间数据传递

每个步骤的 `output_data` 作为下游步骤的可用输入:

```python
# 步骤执行时可访问之前所有步骤的输出和内容信息
context = {
    "content_id": "abc123",
    "content_url": "https://example.com/article",
    "content_title": "文章标题",
    "source_id": "source_xyz",
    "step_config": {"scrape_level": "auto"},   # 当前步骤的操作配置
    "previous_steps": {
        "enrich_content": {"full_text": "...", "word_count": 1200},
        "translate_content": {"target_language": "zh", "translated_text": "..."},
    }
}
```

---

## 4. 抓取引擎设计

### 4.0 两种数据接入模式

系统支持两种互补的数据接入模式，适用于不同类型的数据源：

| 维度 | Collect（采集）| Fountain（同步）|
|------|--------------|----------------|
| 数据位置 | 公网可访问 | 用户本地文件 / 平台私有数据 |
| 认证要求 | 无 / 服务端 API Key | 用户登录态（cookies/token） |
| 数据性质 | 公开内容 | 个人私有数据 |
| 时机控制 | 服务端定时调度 | 用户在 Fountain 客户端手动触发 |
| 实现方式 | `BaseCollector` 子类 + `COLLECTOR_MAP` | Rust 同步器 + HTTP Sync API |
| SourceCategory | `network` | `user` |

**决策规则**（新增数据源时参考）：
- 公网可访问且无需用户登录 → **Collect**
- 需要用户 cookies/token 且无法服务端长期保存 → **Fountain**
- 数据在用户本地（文件、系统数据库）→ **Fountain**
- 用户直接创建内容（笔记）→ 直接 POST API（`user.note` 类型，不经 Collector）

### 4.1 Collector 接口

```python
from abc import ABC, abstractmethod

class BaseCollector(ABC):
    @abstractmethod
    async def collect(self, source: SourceConfig) -> list[RawContentItem]:
        """采集原始内容列表 (由定时器调用, 不是流水线步骤)"""
        """富化单条内容 (全文提取等)"""
```

### 4.2 Collector 实现矩阵

| Collector | 适用 SourceType | 采集方式 | 说明 |
|-----------|-----------------|----------|------|
| `RSSHubCollector` | `rss.hub` | RSSHub 服务 → feedparser | 统一处理 B站/YouTube/微博等 |
| `RSSStdCollector` | `rss.standard` | feedparser 直接解析 | 标准 RSS/Atom |
| `ScraperCollector` | `web.scraper` | L1/L2/L3 三级策略 | 通用网页抓取 |
| `AkShareCollector` | `api.akshare` | AkShare API | 金融数据 |
| `PodcastCollector` | `podcast.apple` | 播客 RSS 解析 | Apple Podcasts |
| `FileUploadCollector` | `file.upload` | 读取上传文件 | 文本/图片/文档 |
| `GenericAccountCollector` | `account.generic` | 平台特定 API | 其他需认证的平台 |

注意:
- 没有 BilibiliVideoCollector / YouTubeVideoCollector。视频下载由流水线中的 `localize_media` 步骤 (yt-dlp) 处理, 不是 Collector 的职责。
- `sync.*` 类型（apple_books / wechat_read / bilibili / kindle / safari_bookmarks / chrome_bookmarks）均属于 **Fountain 模式**，无 Collector 实现，不参与定时调度。数据由 Fountain 桌面客户端采集后通过 Sync API 三步协议推送（见 §4.4）。

### 4.3 三级抓取策略实现

```python
class ContentEnricher:
    """内容富化器 - 三级递进抓取"""
    
    async def enrich(self, url: str, level: int = 1) -> str:
        if level == 1:
            content = await self._http_fetch(url)
            if self._is_content_valid(content):
                return content
        
        if level <= 2:
            content = await self._browserless_fetch(url)
            if self._is_content_valid(content):
                return content
        
        if level <= 3:
            content = await self._browser_use_fetch(url)
            return content
        
        return ""
    
    async def _http_fetch(self, url: str) -> str:
        """L1: httpx + trafilatura 提取 (输出 Markdown)"""
        
    async def _browserless_fetch(self, url: str) -> str:
        """L2: Browserless Chrome 渲染 + 提取"""
        
    async def _browser_use_fetch(self, url: str) -> str:
        """L3: browser-use AI 操控浏览器"""
```

### 4.4 外部数据同步 (Sync API)

对于需要用户凭证（Cookie）且不适合作为 Collector 的平台，采用「外部脚本 + 同步 API」模式。

**架构**: 外部脚本（独立运行，不依赖后端环境）负责从平台获取数据，通过 HTTP API 推送到后端。

**同步 API 端点**:

| API 前缀 | 适用类型 | 端点 |
|----------|---------|------|
| `/api/ebook/sync` | `sync.apple_books`, `sync.wechat_read` | setup / status / sync (书籍+标注) |
| `/api/video/sync` | `sync.bilibili` | setup / status / sync (视频元数据) |

**同步流程** (三步式):
1. `POST /setup?source_type=sync.xxx` — 获取或创建 SourceConfig，返回 source_id
2. `GET /status?source_id=xxx` — 查询上次同步时间，用于增量过滤
3. `POST /sync` — 推送数据（支持批量 upsert）

**外部脚本**:

| 脚本 | 平台 | 数据 |
|------|------|------|
| `scripts/bilibili-sync.py` | B站 | 收藏夹/历史/动态视频 |
| `scripts/wechat-read-sync.py` | 微信读书 | 书籍元数据、阅读进度、划线标注 |

脚本独立于后端环境，仅依赖 `httpx`，支持增量/全量/预览模式。

---

## 5. LLM 分析引擎

### 5.1 分析器接口

LLM 配置存储在 `system_settings` 表中（键: `llm_api_key`, `llm_base_url`, `llm_model`），
通过 `app.core.config.get_llm_config()` 读取，支持运行时动态修改无需重启。

```python
class LLMAnalyzer:
    def __init__(self, provider: str, api_key: str, base_url: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
    
    async def analyze(self, content: str, prompt_template: PromptTemplate) -> dict:
        """使用指定提示词模板分析内容"""
        system_prompt = prompt_template.system_prompt
        user_prompt = prompt_template.user_prompt.format(content=content)

        # 根据配置决定响应格式
        output_format = prompt_template.output_format or "json"
        response_format = {"type": "json_object"} if output_format == "json" else None

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=response_format
        )

        result_text = response.choices[0].message.content

        if output_format == "json":
            return json.loads(result_text)
        else:
            # Markdown/Text 封装为标准结构
            return {"content": result_text, "format": output_format}
```

### 5.2 默认提示词配置

```yaml
# 新闻分析模板
news_analysis:
  system_prompt: |
    你是一位专业的信息分析师。请对以下内容进行结构化分析，输出 JSON 格式。
  user_prompt: |
    请分析以下内容：
    
    {content}
    
    请输出以下字段：
    - summary: 一句话核心摘要
    - key_points: 3-5 个关键要点 (数组)
    - entities: 提取的实体 (time, people, locations, organizations)
    - background: 事件背景 (1-2 句)
    - stance: 作者/来源的立场倾向
    - evidence: 关键佐证 (数组)
    - sentiment: 情感倾向 (positive/neutral/negative)
    - tags: 主题标签 (数组)
```

---

## 6. API 接口设计

### 6.1 统一响应格式

```python
class APIResponse(BaseModel):
    code: int = 0                # 0=成功, >0=业务错误
    data: Any = None
    message: str = "ok"
    
class PaginatedResponse(APIResponse):
    data: list
    total: int
    page: int
    page_size: int
```

### 6.2 接口清单

#### Dashboard
```
GET  /api/dashboard/stats              → { sources_count, contents_today, pipelines_running, pipelines_failed }
GET  /api/dashboard/collection-trend   → 采集趋势数据
GET  /api/dashboard/daily-stats        → 每日统计
GET  /api/dashboard/source-health      → 数据源健康状态
GET  /api/dashboard/recent-content     → 最近采集的内容
GET  /api/dashboard/content-status-distribution → 内容状态分布
GET  /api/dashboard/storage-stats      → 存储统计
GET  /api/dashboard/today-summary      → 今日概要
GET  /api/dashboard/recent-activity    → 最近活动
GET  /api/dashboard/user-behavior-stats → 用户行为统计（阅读/收藏/热力图/趋势/偏好）
```

#### Sources
```
GET    /api/sources                    → PaginatedResponse[SourceConfig]
POST   /api/sources                    → SourceConfig  (创建)
GET    /api/sources/options            → 数据源选项列表 (用于下拉)
POST   /api/sources/cleanup-duplicates → 清理重复数据源
GET    /api/sources/{id}               → SourceConfig
PUT    /api/sources/{id}               → SourceConfig  (更新)
DELETE /api/sources/{id}?cascade=false  → null          (cascade=true 关联删除)
POST   /api/sources/batch-delete       → { deleted }   (批量删除, body: {ids}, ?cascade=false)
POST   /api/sources/batch-collect      → 一键采集所有启用源
POST   /api/sources/{id}/collect       → 触发单源采集
GET    /api/sources/{id}/history       → PaginatedResponse[CollectionRecord]
```

#### OPML (导入导出)
```
POST   /api/opml/import               → { imported: int } (OPML导入)
GET    /api/opml/export                → OPML file
```

#### Content
```
GET    /api/content                    → PaginatedResponse[ContentItem]
       ?source_id=&status=&has_video=&q=&sort_by=&order=&is_favorited=&is_unread=&date_range=
POST   /api/content/delete-all         → { deleted } (清空全部内容)
POST   /api/content/batch-delete       → { deleted } (批量删除, body: {ids})
POST   /api/content/batch-read         → 批量标记已读
POST   /api/content/batch-favorite     → 批量收藏
POST   /api/content/batch-unfavorite   → 批量取消收藏
POST   /api/content/mark-all-read      → 全部标记已读
GET    /api/content/stats              → { total, today, pending, processing, ready, analyzed, failed }
POST   /api/content/submit             → ContentSubmitResponse (用户提交文本内容)
POST   /api/content/upload             → ContentSubmitResponse (用户上传文件)
GET    /api/content/{id}               → ContentItem (含分析结果和 media_items)
POST   /api/content/{id}/analyze       → PipelineExecution (重新分析)
POST   /api/content/{id}/enrich        → 抓取全文
POST   /api/content/{id}/enrich/apply  → 应用抓取结果
POST   /api/content/{id}/favorite      → null (切换收藏)
POST   /api/content/{id}/view          → 记录浏览
PATCH  /api/content/{id}/note          → null (更新笔记)
GET    /api/content/{id}/chat/history  → AI 对话历史
PUT    /api/content/{id}/chat/history  → 更新对话历史
DELETE /api/content/{id}/chat/history  → 清除对话历史
POST   /api/content/{id}/chat          → AI 对话
```

#### Pipelines
```
GET    /api/pipelines                  → PaginatedResponse[PipelineExecution]
       ?status=&source_id=
POST   /api/pipelines/manual           → PipelineExecution (手动URL处理)
POST   /api/pipelines/test-step        → 测试单个步骤
POST   /api/pipelines/cancel-all       → 取消所有运行中的流水线
GET    /api/pipelines/{id}             → PipelineExecution (含步骤详情)
POST   /api/pipelines/{id}/cancel      → null
POST   /api/pipelines/{id}/retry       → PipelineExecution (重试失败步骤)
```

#### Templates
```
GET    /api/pipeline-templates         → list[PipelineTemplate]
GET    /api/pipeline-templates/step-definitions → dict[str, StepDefinition]
GET    /api/pipeline-templates/{id}    → PipelineTemplate
POST   /api/pipeline-templates         → PipelineTemplate
PUT    /api/pipeline-templates/{id}    → PipelineTemplate
DELETE /api/pipeline-templates/{id}    → null

GET    /api/prompt-templates           → list[PromptTemplate]
GET    /api/prompt-templates/{id}      → PromptTemplate
POST   /api/prompt-templates           → PromptTemplate
PUT    /api/prompt-templates/{id}      → PromptTemplate
DELETE /api/prompt-templates/{id}      → null
```

#### Settings
```
GET    /api/settings                   → dict[str, Any]
PUT    /api/settings                   → null  (批量更新)
POST   /api/settings/test-llm          → { model } (LLM 连接测试)
POST   /api/settings/clear-executions  → { deleted } (手动清理执行记录)
POST   /api/settings/clear-collections → { deleted } (手动清理采集记录)
POST   /api/settings/preview-cleanup   → 预览清理结果
POST   /api/settings/manual-cleanup    → 手动执行清理
```

#### Video
```
POST   /api/video/download             → 提交下载任务
GET    /api/video/downloads             → PaginatedResponse[DownloadTask]
PUT    /api/video/{id}/progress         → 更新播放进度
DELETE /api/video/{id}                  → 删除视频
GET    /api/video/{id}/thumbnail        → image file (封面图)
GET    /api/video/{id}/stream           → video stream (Range 支持)
```

#### Video Sync (外部同步)
```
POST   /api/video/sync/setup           → { source_id } (创建/获取 sync 数据源)
GET    /api/video/sync/status           → VideoSyncStatus (同步状态)
POST   /api/video/sync                  → VideoSyncResponse (批量推送视频数据)
```

#### Ebook Sync (外部同步)
```
POST   /api/ebook/sync/setup           → { source_id } (创建/获取 sync 数据源)
GET    /api/ebook/sync/status           → EbookSyncStatus (同步状态)
POST   /api/ebook/sync                  → EbookSyncResponse (批量推送书籍+标注)
```

#### Media (通用媒体文件服务)
```
GET    /api/media/list                 → 媒体列表
PUT    /api/media/{content_id}/progress → 更新播放进度
DELETE /api/media/{content_id}          → 删除媒体
GET    /api/media/{content_id}/thumbnail → 封面图
GET    /api/media/{content_id}/{file_path} → FileResponse (从 MEDIA_DIR 读取)
POST   /api/media/{content_id}/retry    → 重试媒体下载
```

#### Audio
```
GET    /api/audio/{content_id}/stream  → 音频流
```

#### Credentials (平台凭证)
```
GET    /api/credentials/options        → 凭证选项列表
GET    /api/credentials                → list[PlatformCredential]
POST   /api/credentials                → PlatformCredential (创建)
GET    /api/credentials/{id}           → PlatformCredential
PUT    /api/credentials/{id}           → PlatformCredential (更新)
DELETE /api/credentials/{id}           → null
POST   /api/credentials/{id}/check     → { valid } (校验凭证)
POST   /api/credentials/{id}/sync-rsshub → { synced } (同步 RSSHub)
```

#### Bilibili Auth (B站认证)
```
POST   /api/bilibili-auth/qrcode/generate → { qr_url, token } (B站扫码登录)
GET    /api/bilibili-auth/qrcode/poll     → { status } (轮询扫码结果)
```

#### Finance (金融数据)
```
GET    /api/finance/presets             → 预设金融指标
GET    /api/finance/sources             → 金融数据源列表
GET    /api/finance/summary             → 金融数据概要
GET    /api/finance/timeseries/{source_id} → 时间序列数据
```

#### Export (全量导入导出)
```
GET    /api/export/export/full         → 全量导出
POST   /api/export/import/full         → 全量导入
```

---

## 7. 任务调度详细设计

### 7.1 Procrastinate periodic 配置

所有定时任务由 Procrastinate worker 的 periodic 功能驱动，定义在 `app/tasks/scheduled_tasks.py`:

```python
# 主采集循环 - 每 1 分钟检查 next_collection_at <= now 的源
@proc_app.periodic(cron="*/1 * * * *")
@proc_app.task(queue="scheduled", queueing_lock="collection_loop")
async def check_and_collect_sources(timestamp):
    """查询到期的源，defer 采集任务到 worker 并发执行"""

# 日报 - 每天 22:00
@proc_app.periodic(cron="0 22 * * *")
@proc_app.task(queue="scheduled", queueing_lock="daily_report")
async def trigger_daily_report(timestamp): ...

# 周报 - 每周一 09:00
@proc_app.periodic(cron="0 9 * * 1")
@proc_app.task(queue="scheduled", queueing_lock="weekly_report")
async def trigger_weekly_report(timestamp): ...

# 周期性分析 - 每天 04:00 (分析源的更新模式)
@proc_app.periodic(cron="0 4 * * *")
@proc_app.task(queue="scheduled", queueing_lock="analyze_periodicity")
async def analyze_source_periodicity(timestamp): ...

# 清理调度器 - 每小时检查，按 system_settings 配置的时间动态执行
@proc_app.periodic(cron="0 * * * *")
@proc_app.task(queue="scheduled", queueing_lock="cleanup_scheduler")
async def cleanup_scheduler(timestamp): ...
```

### 7.2 智能调度系统

调度服务位于 `app/services/scheduling/`，支持三种调度模式:

| 模式 | 字段 | 说明 |
|------|------|------|
| `auto` | `schedule_mode='auto'` | 系统基于周期性分析和采集历史自动计算间隔 |
| `fixed` | `schedule_mode='fixed'` | 使用 `schedule_interval_override` 固定间隔 |
| `manual` | `schedule_mode='manual'` | 仅手动触发，不自动采集 |

核心组件:
- **SchedulingService**: 计算 `next_collection_at`，判断是否应采集
- **SchedulingConfig**: 调度配置参数（最小/最大间隔、退避因子等）
- **周期性分析** (`periodicity.py`): 分析源的更新模式，优化间隔
- **热点检测** (`hotspot.py`): 检测突发更新，临时缩短采集间隔

`next_collection_at` 是预计算字段，由 `SchedulingService.update_next_collection_time()` 在每次采集后更新。主循环查询 `next_collection_at <= now` 的源进行采集。

---

## 8. 部署架构

### 8.1 Docker Compose

```yaml
version: "3.8"

services:
  postgres:
    image: postgres:17-alpine
    command: postgres -c timezone=UTC
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init/init-databases.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]

  rsshub:
    image: diygod/rsshub:latest
    environment:
      PUPPETEER_WS_ENDPOINT: ws://browserless:3000
    depends_on:
      - browserless

  browserless:
    image: browserless/chrome:latest
    environment:
      MAX_CONCURRENT_SESSIONS: 3

  allin-one:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    environment:
      DATABASE_URL: postgresql://allinone:allinone@postgres:5432/allinone
      RSSHUB_URL: http://rsshub:1200
      BROWSERLESS_URL: http://browserless:3000
    depends_on:
      postgres:
        condition: service_healthy

  allin-worker-pipeline:
    build:
      context: .
      dockerfile: Dockerfile
    command: ["python", "-m", "procrastinate", "--app=app.tasks.procrastinate_app.proc_app", "worker", "--concurrency=4", "--queues=pipeline"]
    volumes:
      - ./data:/app/data
    environment:
      DATABASE_URL: postgresql://allinone:allinone@postgres:5432/allinone
      RSSHUB_URL: http://rsshub:1200
      BROWSERLESS_URL: http://browserless:3000
    depends_on:
      postgres:
        condition: service_healthy

  allin-worker-scheduled:
    build:
      context: .
      dockerfile: Dockerfile
    command: ["python", "-m", "procrastinate", "--app=app.tasks.procrastinate_app.proc_app", "worker", "--concurrency=2", "--queues=scheduled"]
    volumes:
      - ./data:/app/data
    environment:
      DATABASE_URL: postgresql://allinone:allinone@postgres:5432/allinone
      RSSHUB_URL: http://rsshub:1200
      BROWSERLESS_URL: http://browserless:3000
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  postgres_data:
```

### 8.2 多阶段 Dockerfile

```dockerfile
# Stage 1: Frontend Build
FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Docker CLI (for RSSHub container management)
FROM docker:cli AS docker-cli

# Stage 3: Backend Runtime
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend-builder /app/frontend/dist ./static
RUN mkdir -p data/db data/media data/reports data/logs
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 8.3 部署脚本

```bash
#!/bin/bash
# deploy-remote.sh - 一键部署到远程服务器
REMOTE_HOST="user@your-server"
REMOTE_DIR="/opt/allin-one"

# 1. 增量同步
rsync -avz --exclude '.git' --exclude 'venv' --exclude 'data' \
    --exclude 'node_modules' --exclude '__pycache__' \
    ./ ${REMOTE_HOST}:${REMOTE_DIR}/

# 2. 远程构建与重启
ssh ${REMOTE_HOST} << 'EOF'
cd /opt/allin-one
docker compose up -d --build
docker compose exec allin-one alembic upgrade head
docker image prune -f
EOF
```

---

## 9. 监控与运维

### 9.1 日志体系

结构化文件日志，由 `app/core/logging_config.py` 统一配置:

| 文件 | 写入者 | 级别 | 用途 |
|------|--------|------|------|
| `data/logs/backend.log` | FastAPI 进程 | WARNING+ | API 服务的警告与异常 |
| `data/logs/worker.log` | Procrastinate Worker 进程 | WARNING+ | 任务执行的警告与异常 |
| `data/logs/error.log` | 所有进程共写 | ERROR+ | 所有严重错误汇总 |

日志格式: `时间 级别 [模块名] 消息`，含完整 traceback。控制台同时输出 INFO+ 级别。

### 9.2 健康检查

`GET /health` 返回综合健康状态，`status` 由 database/rsshub/browserless 三项共同决定：

```json
{
  "status": "ok | degraded",
  "checks": {
    "database":    "ok | error: ...",
    "rsshub":      "ok | unreachable: ...",
    "browserless": "ok | unreachable: ...",
    "queue_depth": {
      "pipeline":  {"todo": 0, "doing": 0},
      "scheduled": {"todo": 0, "doing": 0}
    },
    "disk": {
      "total_gb": 50.0, "used_gb": 12.3,
      "free_gb": 37.7,  "used_pct": 24.6
    }
  }
}
```

`queue_depth` 和 `disk` 为观测字段，不参与 `status` 降级判断。

**容器 TZ 策略**（`docker-compose.remote.yml`）:
- `worker-pipeline` / `worker-scheduled` / `mcp`: `TZ=UTC`（cron 表达式基于 UTC，与数据库 naive UTC 存储一致）
- `allin-one` / `rsshub` / `browserless`: `TZ=Asia/Shanghai`（日志时间戳、仪表盘本地日边界计算使用北京时间）
- `postgres`: `TZ=UTC`（数据库服务器时区必须为 UTC）

### 9.3 数据备份

PostgreSQL 数据库通过 `pg_dump` 实现备份:

```bash
# 手动备份
docker compose exec postgres pg_dump -U allinone allinone > data/backups/backup_$(date +%Y%m%d).sql

# 恢复
docker compose exec -T postgres psql -U allinone allinone < data/backups/backup_20260221.sql
```
