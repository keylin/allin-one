# Allin-One 系统方案

> 版本: v1.1 | 更新日期: 2026-02-14

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
│  │  ┌─────────┐ ┌───────────┐ ┌─────────────────┐ │     │
│  │  │ Router  │ │ Scheduler │ │ Static Files    │ │     │
│  │  │ Layer   │ │(APScheduler)│(Vue dist/)      │ │     │
│  │  └────┬────┘ └─────┬─────┘ └─────────────────┘ │     │
│  │       │             │                            │     │
│  │  ┌────▼─────────────▼────────────────────────┐  │     │
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
│  │           Huey Worker (异步任务层)                │     │
│  │              ┌─────────┐ ┌─────────┐           │     │
│  │              │ enrich  │ │ analyze │ ...        │     │
│  │              │_content │ │_content │            │     │
│  │              └────┬────┘ └────┬────┘           │     │
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
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────┐     │
│  │ SQLite   │ │ Huey DB  │ │ File System          │     │
│  │ (主数据库)│ │ (任务队列)│ │ videos/images/files  │     │
│  └──────────┘ └──────────┘ └──────────────────────┘     │
│                                                          │
│       数据层 (Data Layer)                                 │
└──────────────────────────────────────────────────────────┘
```

### 1.2 进程模型

系统运行时包含以下进程:

| 进程 | 容器 | 职责 |
|------|------|------|
| FastAPI (uvicorn) | allin-one | Web 服务、API、调度器 |
| Huey Consumer | allin-worker | 异步任务执行 |
| RSSHub | rsshub | RSS 转换服务 |
| Browserless | browserless | 无头浏览器服务 |

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
platform_credentials (平台凭证)
finance_data_points (金融数据)
```

**核心解耦关系**: `source_configs.pipeline_template_id → pipeline_templates.id`
数据源通过此外键绑定流水线模板，而非硬编码映射。

### 2.2 表结构详细定义

#### source_configs (数据源配置)

只描述「从哪获取信息」，source_type 不含视频平台等混合类型。

数据源分为两大类（派生属性，非 DB 列）：
- **网络数据 (network)**: rss.hub, rss.standard, api.akshare, web.scraper, account.bilibili, account.generic — 有 Collector，定时自动采集
- **用户数据 (user)**: user.note, file.upload, system.notification — 用户/系统主动提交，schedule_enabled 自动置 false

通用内容提交 API：`POST /api/content/submit`（文本）、`POST /api/content/upload`（文件），校验目标源必须为 user 分类。

```sql
CREATE TABLE source_configs (
    id              TEXT PRIMARY KEY,           -- UUID
    name            TEXT NOT NULL,              -- 源名称 (e.g. "B站-某UP主")
    source_type     TEXT NOT NULL,              -- 来源渠道: rss.hub/rss.standard/web.scraper/api.akshare/...
    url             TEXT,                       -- 订阅/采集地址
    description     TEXT,
    schedule_enabled BOOLEAN DEFAULT TRUE,
    schedule_interval INTEGER DEFAULT 3600,
    pipeline_template_id TEXT,                  -- 绑定的流水线模板 (解耦关键!)
    config_json     TEXT,                       -- 渠道特定配置 (JSON)
    credential_id   TEXT,                       -- 关联的平台凭证
    auto_cleanup_enabled BOOLEAN DEFAULT FALSE, -- 启用自动清理
    retention_days  INTEGER,                    -- 内容保留天数 (null=使用全局默认)
    last_collected_at DATETIME,
    consecutive_failures INTEGER DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pipeline_template_id) REFERENCES pipeline_templates(id)
);
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
    source_id       TEXT NOT NULL,              -- 外键 -> source_configs
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
    user_note       TEXT,                       -- 用户笔记
    view_count      INTEGER DEFAULT 0,           -- 浏览次数
    last_viewed_at  DATETIME,                     -- 最后浏览时间
    playback_position INTEGER DEFAULT 0,          -- 视频播放进度（秒）
    last_played_at  DATETIME,                     -- 最后播放时间
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES source_configs(id),
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
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (content_id) REFERENCES content_items(id)
);

CREATE INDEX ix_media_item_content_id ON media_items(content_id);
```

#### pipeline_executions (流水线执行记录)

```sql
CREATE TABLE pipeline_executions (
    id              TEXT PRIMARY KEY,
    content_id      TEXT,                       -- 外键 -> content_items
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

`steps_config` JSON 结构 — 用户模板只包含后置处理步骤，预处理 (enrich_content / localize_media) 由 Orchestrator 自动注入:
```json
[
  {"step_type": "analyze_content", "is_critical": true,  "config": {}},
  {"step_type": "publish_content", "is_critical": false, "config": {"channel": "none"}}
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
    value           TEXT,                       -- 配置值 (JSON)
    description     TEXT,                       -- 说明
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 3. Pipeline 引擎设计

### 3.1 核心类结构

```python
# app/services/pipeline/registry.py

STEP_DEFINITIONS = {
    # 原子操作注册表 — 没有 fetch_content (抓取由定时器+Collector完成)
    "enrich_content":      StepDefinition(display_name="抓取全文",   config_schema={"scrape_level": "L1/L2/L3/auto"}),
    "localize_media":      StepDefinition(display_name="媒体本地化", description="检测并下载图片/视频/音频，创建 MediaItem"),
    "extract_audio":       StepDefinition(display_name="音频提取"),
    "transcribe_content":  StepDefinition(display_name="语音转文字"),
    "translate_content":   StepDefinition(display_name="文章翻译",   config_schema={"target_language": "zh"}),
    "analyze_content":     StepDefinition(display_name="模型分析",   config_schema={"model": "下拉枚举", "prompt_template_id": "关联"}),
    "publish_content":     StepDefinition(display_name="消息推送",   config_schema={"channel": "email/dingtalk", "frequency": "immediate/daily"}),
}

# 用户模板只包含后置处理步骤，预处理由 Orchestrator 自动注入
BUILTIN_TEMPLATES = [
    {"name": "文章分析",         "steps": ["analyze → publish"]},
    {"name": "英文文章翻译分析", "steps": ["translate → analyze → publish"]},
    {"name": "视频下载分析",     "steps": ["transcribe → analyze → publish"]},
    {"name": "视频翻译分析",     "steps": ["transcribe → translate → analyze → publish"]},
    {"name": "仅分析",          "steps": ["analyze → publish"]},
    {"name": "仅推送",          "steps": ["publish"]},
]
```

```python
# app/services/pipeline/orchestrator.py
class PipelineOrchestrator:
    """编排器 - 为已存在的 ContentItem 创建流水线执行

    流水线分两阶段:
      1. 预处理 (自动): 基于内容检测自动执行
         - 文本量不足 → enrich_content (抓取全文)
         - 始终 → localize_media (媒体检测+下载+URL改写, api.akshare 除外)
      2. 后置处理 (用户模板): analyze / translate / publish 等
    """

    def get_template_for_source(self, source: SourceConfig) -> PipelineTemplate | None:
        """获取源绑定的模板, 未绑定返回 None (纯采集场景)"""

    def trigger_for_content(self, content: ContentItem, template_override_id=None, trigger=...) -> PipelineExecution | None:
        """为一条已存在的 ContentItem 创建并启动流水线
        自动注入预处理步骤, 然后拼接用户模板的后置步骤。
        无模板时仍执行预处理; 无预处理也无模板则标记 READY。"""
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
│  执行 Huey 任务      │
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
| `FileUploadCollector` | `file.upload` | 读取上传文件 | 文本/图片/文档 |
| `BilibiliCollector` | `account.bilibili` | B站账号 API | 动态/收藏夹/历史 (需Cookie) |
| `GenericAccountCollector` | `account.generic` | 平台特定 API | 其他需认证的平台 |

注意: 没有 BilibiliVideoCollector / YouTubeVideoCollector。
视频下载由流水线预处理阶段的 `localize_media` 步骤 (yt-dlp) 自动处理, 不是 Collector 的职责。

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
GET  /api/dashboard/stats
     → { sources_count, contents_today, pipelines_running, pipelines_failed }
```

#### Sources
```
GET    /api/sources                    → PaginatedResponse[SourceConfig]
POST   /api/sources                    → SourceConfig  (创建)
GET    /api/sources/{id}               → SourceConfig
PUT    /api/sources/{id}               → SourceConfig  (更新)
DELETE /api/sources/{id}?cascade=false  → null          (cascade=true 关联删除)
POST   /api/sources/batch-delete       → { deleted }   (批量删除, body: {ids}, ?cascade=false)
POST   /api/sources/batch-collect      → { sources_collected, total_items_new, pipelines_started } (一键采集所有启用源)
POST   /api/sources/{id}/collect       → PipelineExecution (触发采集)
GET    /api/sources/{id}/history       → PaginatedResponse[CollectionRecord]
POST   /api/sources/import             → { imported: int } (OPML导入)
GET    /api/sources/export             → OPML file
```

#### Content
```
GET    /api/content                    → PaginatedResponse[ContentItem]
       ?source_id=&status=&has_video=&q=&sort_by=&order=&is_favorited=&is_unread=&date_range=
GET    /api/content/{id}               → ContentItem (含分析结果和 media_items)
GET    /api/content/stats              → { total, today, pending, processing, ready, analyzed, failed }
POST   /api/content/{id}/analyze       → PipelineExecution (重新分析)
POST   /api/content/{id}/favorite      → null (切换收藏)
PATCH  /api/content/{id}/note          → null (更新笔记)
POST   /api/content/batch-delete       → { deleted } (批量删除, body: {ids})
POST   /api/content/delete-all         → { deleted } (清空全部内容)
```

#### Pipelines
```
GET    /api/pipelines                  → PaginatedResponse[PipelineExecution]
       ?status=&source_id=&pipeline_type=
GET    /api/pipelines/{id}             → PipelineExecution (含步骤详情)
POST   /api/pipelines/{id}/retry       → PipelineExecution (重试失败步骤)
POST   /api/pipelines/{id}/cancel      → null
POST   /api/pipelines/manual           → PipelineExecution (手动URL处理)
       body: { url: string, pipeline_type?: string }
```

#### Templates
```
GET    /api/pipeline-templates         → list[PipelineTemplate]
POST   /api/pipeline-templates         → PipelineTemplate
PUT    /api/pipeline-templates/{id}    → PipelineTemplate
DELETE /api/pipeline-templates/{id}    → null
GET    /api/pipeline-templates/step-definitions → dict[str, StepDefinition]

GET    /api/prompt-templates           → list[PromptTemplate]
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
```

#### Video
```
POST   /api/video/download             → { task_id } (提交下载任务)
       body: { url: string, quality?: string }
GET    /api/video/downloads             → PaginatedResponse[DownloadTask]
GET    /api/video/{id}/stream           → video stream (Range 支持)
GET    /api/video/{id}/thumbnail        → image file (封面图)
```

#### Media (通用媒体文件服务)
```
GET    /api/media/{content_id}/{file_path} → FileResponse (从 MEDIA_DIR 读取)
```

#### Credentials (平台凭证)
```
GET    /api/credentials                → list[PlatformCredential]
POST   /api/credentials                → PlatformCredential (创建)
DELETE /api/credentials/{id}           → null
POST   /api/credentials/{id}/check     → { valid } (校验凭证)
POST   /api/credentials/sync-rsshub    → { synced } (同步 RSSHub)
POST   /api/credentials/bilibili-qrcode → { qr_url, token } (B站扫码登录)
POST   /api/credentials/bilibili-poll   → { status } (轮询扫码结果)
```

#### Finance (金融数据)
```
GET    /api/finance/data               → PaginatedResponse[FinanceDataPoint]
GET    /api/finance/chart-data/{source_id} → { labels, datasets } (图表数据)
```

---

## 7. 任务调度详细设计

### 7.1 APScheduler 配置

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = AsyncIOScheduler()

# 主采集循环 - 每 5 分钟检查需要采集的源
scheduler.add_job(
    check_and_collect_sources,
    IntervalTrigger(minutes=5),
    id="main_collection_loop",
)

# 日报生成 - 每天 22:00
scheduler.add_job(
    generate_daily_report,
    CronTrigger(hour=22, minute=0),
    id="daily_report",
)

# 内容清理 - 每天 03:00 (按 retention_days 清理过期内容)
scheduler.add_job(
    cleanup_expired_content,
    CronTrigger(hour=3, minute=0),
    id="cleanup_expired_content",
)

# 记录清理 - 每天 03:30 (执行记录 + 采集记录)
scheduler.add_job(
    cleanup_records,
    CronTrigger(hour=3, minute=30),
    id="cleanup_records",
)
```

### 7.2 智能调度算法

```python
def calculate_next_collect_time(source: SourceConfig) -> datetime:
    """根据源的更新频率和失败次数计算下次采集时间"""
    base_interval = source.schedule_interval  # 默认 3600 秒
    
    # 退避策略: 连续失败时指数退避
    if source.consecutive_failures > 0:
        backoff = min(base_interval * (2 ** source.consecutive_failures), 7200)
        return datetime.utcnow() + timedelta(seconds=backoff)
    
    # 活跃度调整: 最近 24h 有更新的源缩短间隔
    if source.has_recent_updates:
        return datetime.utcnow() + timedelta(seconds=base_interval * 0.5)
    
    return datetime.utcnow() + timedelta(seconds=base_interval)
```

---

## 8. 部署架构

### 8.1 Docker Compose

```yaml
version: "3.8"

services:
  rsshub:
    image: diygod/rsshub:latest
    environment:
      - PUPPETEER_WS_ENDPOINT=ws://browserless:3000
    depends_on:
      - browserless
    restart: unless-stopped

  browserless:
    image: browserless/chrome:latest
    environment:
      - MAX_CONCURRENT_SESSIONS=5
      - CONNECTION_TIMEOUT=60000
    restart: unless-stopped

  allin-one:
    build:
      context: .
      dockerfile: docker/Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./data/reports:/app/reports
    environment:
      - DATABASE_URL=postgresql://allinone:allinone@postgres:5432/allinone
      - RSSHUB_URL=http://rsshub:1200
      - BROWSERLESS_URL=http://browserless:3000
      - API_KEY=                           # API 认证密钥（空=禁用认证）
      - CORS_ORIGINS=*                     # CORS 允许的来源
    env_file:
      - .env
    depends_on:
      - rsshub
      - browserless
    restart: unless-stopped

  allin-worker:
    build:
      context: .
      dockerfile: docker/Dockerfile
    command: ["huey_consumer", "app.tasks.huey_instance.huey", "-w", "4", "-k", "thread"]
    volumes:
      - ./data:/app/data
      - ./data/reports:/app/reports
    environment:
      - DATABASE_URL=postgresql://allinone:allinone@postgres:5432/allinone
      - RSSHUB_URL=http://rsshub:1200
      - BROWSERLESS_URL=http://browserless:3000
    env_file:
      - .env
    depends_on:
      - rsshub
      - browserless
    restart: unless-stopped
```

### 8.2 多阶段 Dockerfile

```dockerfile
# Stage 1: Frontend Build
FROM node:22-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Backend Runtime
FROM allin-base:latest
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend-builder /build/dist ./static
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 8.3 部署脚本

```bash
#!/bin/bash
# deploy.sh - 一键部署到远程服务器
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
| `data/logs/worker.log` | Huey Worker 进程 | WARNING+ | 任务执行的警告与异常 |
| `data/logs/error.log` | 两个进程共写 | ERROR+ | 所有严重错误汇总 |

日志格式: `时间 级别 [模块名] 消息`，含完整 traceback。控制台同时输出 INFO+ 级别。

### 9.2 健康检查

```python
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "db": await check_db_connection(),
        "rsshub": await check_rsshub(),
        "browserless": await check_browserless(),
        "worker": await check_worker_status(),
    }
```

### 9.3 数据备份

SQLite 数据库通过 `.backup` API 实现在线备份:

```python
async def backup_database():
    """每日自动备份数据库"""
    src = sqlite3.connect("data/db/allin.db")
    dst = sqlite3.connect(f"data/db/backup_{date.today()}.db")
    src.backup(dst)
```
