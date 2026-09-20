# Allin-One 系统方案

> 版本: v1.4 | 更新日期: 2026-03-06

---

## 1. 架构总览

> 任务调度见本文 §7，流水线引擎见 §3。早期的独立设计稿已归档到 `docs/archive/`（内容是 APScheduler / SQLite / Huey 时代的，仅供考古）。

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
│  │  │ extract/localize │ │ 采集循环/同步/清理     │  │     │
│  │  │ analyze/publish  │ │                       │  │     │
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
| MCP Server (FastMCP) | mcp | AI 助手数据接口，stdio/streamable-http 双模式 |
| PostgreSQL | allin-postgres | 主数据库 + Procrastinate 任务队列 |
| RSSHub | allin-rsshub | RSS 转换服务 |
| Browserless | allin-browserless | 无头浏览器服务 |

---

## 2. 数据库设计

### 2.1 ER 关系图

```
pipeline_templates 1─ ─ ─ ─ ┐ (pipeline_template_id, SET NULL)
platform_credentials 1─ ─ ─ ┤ (credential_id, SET NULL)
                            ▼
source_configs ──1:N── content_items ──1:N── pipeline_executions ──1:N── pipeline_steps
      │           (SET NULL)  │
      │                       ├──1:N── media_items          (CASCADE)
      │                       ├──1:1── watch_records ──1:N── watch_logs   影视库 (CASCADE)
      │                       ├──1:1── reading_progress                   电子书 (CASCADE)
      │                       ├──1:N── book_annotations                   电子书 (CASCADE)
      │                       └──1:N── book_bookmarks                     电子书 (CASCADE)
      │
      ├──1:N── collection_records    采集型的运行记录 (CASCADE)
      ├──1:N── sync_task_progress    同步型的运行记录 (CASCADE)
      └──1:N── finance_data_points   金融时序 (CASCADE)

prompt_templates、system_settings：独立表
```

三个要点：

- **两条主线共用 `content_items`**：信息流条目与资料库条目（影片、书、书签……）都是这张表的行，领域身份看 `kind`。资料库的领域字段目前在 `raw_data`，用户侧的标记在各自的附表（`watch_*`、`reading_progress`、`book_*`）。
- **`content_items.source_id` 是 SET NULL**，而采集记录、同步记录、金融数据点随数据源 CASCADE。因此删除数据源时：信息流内容可以成为无主行；用户数据类数据源下有内容时拒绝非级联删除（见下方「内容保留策略」）。
- **数据源与流水线解耦**：`source_configs.pipeline_template_id → pipeline_templates.id`，而非硬编码映射。

### 2.2 表结构

> **本节的表结构由模型生成，不要手改。** 改了模型后运行 `scripts/verify/drift/check.sh --write` 更新；`scripts/verify/drift/check.sh` 同时检查「模型 vs 真实库」与「本节 vs 模型」两项漂移。
> 枚举取值、字段语义见 `docs/business_glossary.md`；某种源类型能做什么见 `backend/app/models/source_types.py`。

**数据源的两大类**（由源类型注册表决定，非 DB 列）：网络数据 (network) 由 Collector 采集、可定时调度；用户数据 (user) 是用户 / 系统主动提交或同步进来的资料（`sync.*` / `user.*` / `file.*` / `system.*`）。

**内容保留策略**（唯一判定处 `app/services/content_retention.py`，定时清理与清理预览共用）：

- 每日清理只作用于**网络采集类**数据源。保留期 = `source.retention_days`，为空则用全局 `default_retention_days`（未配置时 30 天，0 = 永久）。`source.auto_cleanup_enabled` 目前不参与判定。
- **用户数据类**数据源（影视库、书、书签、笔记、上传文件）**永不自动清理**。
- 采集类内容满足任一条件即受保护：内容已收藏、有用户笔记、其下任一媒体项已收藏。
- 删除数据源时，用户数据类数据源下若有内容，**拒绝非级联删除**（`SourceDeleteBlocked` → 409）。

**通用内容提交**：`POST /api/content/submit`（文本，恒为 `kind=note`）、`POST /api/content/upload`（文件，`kind=file`，目标源必须是 `file.upload`）。

`steps_config` JSON 结构 — 模板包含所有步骤（含 extract_content、localize_media），Orchestrator 不再自动注入:
```json
[
  {"step_type": "extract_content",  "is_critical": true,  "config": {}},
  {"step_type": "localize_media",   "is_critical": false, "config": {}},
  {"step_type": "analyze_content",  "is_critical": true,  "config": {}},
  {"step_type": "publish_content",  "is_critical": false, "config": {"channel": "none"}}
]
```

<!-- BEGIN GENERATED: schema -->

#### book_annotations

电子书标注。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `content_id` | VARCHAR | 否 |  | FK → content_items.id（ON DELETE CASCADE） |
| `external_id` | VARCHAR | 是 |  |  |
| `cfi_range` | TEXT | 是 |  |  |
| `section_index` | INTEGER | 是 |  |  |
| `location` | VARCHAR | 是 |  |  |
| `type` | VARCHAR | 是 | `highlight`（ORM 端） |  |
| `color` | VARCHAR | 是 | `yellow`（ORM 端） |  |
| `selected_text` | TEXT | 是 |  |  |
| `note` | TEXT | 是 |  |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |
| `updated_at` | DATETIME | 是 | （ORM 端） |  |

- 索引 `ix_annotation_content`: (content_id)
- 索引 `ix_annotation_external_id`: (external_id)
- 唯一索引 `uq_annotation_content_external`: (content_id, external_id) WHERE external_id IS NOT NULL

#### book_bookmarks

电子书书签。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `content_id` | VARCHAR | 否 |  | FK → content_items.id（ON DELETE CASCADE） |
| `cfi` | TEXT | 否 |  |  |
| `title` | VARCHAR | 是 |  |  |
| `section_title` | VARCHAR | 是 |  |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |

- 索引 `ix_bookmark_content`: (content_id)

#### collection_records

采集型数据源的运行记录，同时是智能调度算法的输入。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `source_id` | VARCHAR | 否 |  | FK → source_configs.id（ON DELETE CASCADE） |
| `status` | VARCHAR | 是 | `running`（ORM 端） |  |
| `items_found` | INTEGER | 是 | `0`（ORM 端） |  |
| `items_new` | INTEGER | 是 | `0`（ORM 端） |  |
| `error_message` | TEXT | 是 |  |  |
| `started_at` | DATETIME | 是 | （ORM 端） |  |
| `completed_at` | DATETIME | 是 |  |  |

- 索引 `ix_colrec_source_id`: (source_id)
- 索引 `ix_colrec_source_started`: (source_id, started_at)
- 索引 `ix_colrec_source_status_started`: (source_id, status, started_at)

#### content_items

内容项。信息流条目与资料库条目共用此表，领域身份看 `kind`（ContentKind）。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `source_id` | VARCHAR | 是 |  | FK → source_configs.id（ON DELETE SET NULL） |
| `title` | VARCHAR | 否 |  |  |
| `external_id` | VARCHAR | 否 |  |  |
| `kind` | VARCHAR | 否 | `article`（库级） |  |
| `url` | VARCHAR | 是 |  |  |
| `author` | VARCHAR | 是 |  |  |
| `raw_data` | JSONB | 是 |  |  |
| `processed_content` | TEXT | 是 |  |  |
| `analysis_result` | JSONB | 是 |  |  |
| `status` | VARCHAR | 是 | `pending`（ORM 端） |  |
| `published_at` | DATETIME | 是 |  |  |
| `collected_at` | DATETIME | 是 | （ORM 端） |  |
| `is_favorited` | BOOLEAN | 是 | `False`（ORM 端） |  |
| `favorited_at` | DATETIME | 是 |  |  |
| `user_note` | TEXT | 是 |  |  |
| `chat_history` | JSONB | 是 |  |  |
| `view_count` | INTEGER | 是 | `0`（ORM 端） |  |
| `last_viewed_at` | DATETIME | 是 |  |  |
| `opened_at` | DATETIME | 是 |  |  |
| `title_hash` | BIGINT | 是 |  |  |
| `duplicate_of_id` | VARCHAR | 是 |  | FK → content_items.id（ON DELETE SET NULL） |
| `created_at` | DATETIME | 是 | （ORM 端） |  |
| `updated_at` | DATETIME | 是 | （ORM 端） |  |

- 唯一约束 `uq_source_external`: (source_id, external_id)
- 索引 `ix_content_analysis_gin`: (analysis_result)
- 索引 `ix_content_collected_at`: (collected_at)
- 索引 `ix_content_duplicate_of`: (duplicate_of_id)
- 索引 `ix_content_is_favorited`: (is_favorited)
- 索引 `ix_content_items_opened_at`: (opened_at)
- 索引 `ix_content_kind`: (kind)
- 索引 `ix_content_source_id`: (source_id)
- 索引 `ix_content_source_status_collected`: (source_id, status, collected_at)
- 索引 `ix_content_status`: (status)
- 索引 `ix_content_title_hash`: (title_hash)
- 索引 `ix_content_url`: (url)
- 唯一索引 `uq_content_film_external`: (external_id) WHERE kind = 'film'

#### finance_data_points

金融时序数据点。AkShare 采集器直接写这里，不产出 ContentItem。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `source_id` | VARCHAR | 否 |  | FK → source_configs.id（ON DELETE CASCADE） |
| `category` | VARCHAR | 否 | `unknown`（ORM 端） |  |
| `date_key` | VARCHAR | 否 |  |  |
| `published_at` | DATETIME | 是 |  |  |
| `value` | FLOAT | 是 |  |  |
| `open` | FLOAT | 是 |  |  |
| `high` | FLOAT | 是 |  |  |
| `low` | FLOAT | 是 |  |  |
| `close` | FLOAT | 是 |  |  |
| `volume` | FLOAT | 是 |  |  |
| `unit_nav` | FLOAT | 是 |  |  |
| `cumulative_nav` | FLOAT | 是 |  |  |
| `alert_json` | JSONB | 是 |  |  |
| `analysis_result` | JSONB | 是 |  |  |
| `collected_at` | DATETIME | 是 | （ORM 端） |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |

- 唯一约束 `uq_finance_source_date`: (source_id, date_key)
- 索引 `ix_finance_source_date`: (source_id, date_key)

#### media_items

内容关联的媒体项（一对多）。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `content_id` | VARCHAR | 否 |  | FK → content_items.id（ON DELETE CASCADE） |
| `media_type` | VARCHAR | 否 |  |  |
| `original_url` | VARCHAR | 否 |  |  |
| `local_path` | VARCHAR | 是 |  |  |
| `filename` | VARCHAR | 是 |  |  |
| `status` | VARCHAR | 是 | `pending`（ORM 端） |  |
| `metadata_json` | JSONB | 是 |  |  |
| `playback_position` | INTEGER | 是 | `0`（ORM 端） |  |
| `last_played_at` | DATETIME | 是 |  |  |
| `is_favorited` | BOOLEAN | 否 | `false`（库级） |  |
| `favorited_at` | DATETIME | 是 |  |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |

- 索引 `ix_media_item_content_id`: (content_id)
- 索引 `ix_media_media_type`: (media_type)
- 索引 `ix_media_status`: (status)

#### pipeline_executions

流水线执行记录。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `content_id` | VARCHAR | 否 |  | FK → content_items.id（ON DELETE CASCADE） |
| `source_id` | VARCHAR | 是 |  | FK → source_configs.id（ON DELETE SET NULL） |
| `template_id` | VARCHAR | 是 |  | FK → pipeline_templates.id（ON DELETE SET NULL） |
| `template_name` | VARCHAR | 是 |  |  |
| `status` | VARCHAR | 是 | `pending`（ORM 端） |  |
| `current_step` | INTEGER | 是 | `0`（ORM 端） |  |
| `total_steps` | INTEGER | 是 | `0`（ORM 端） |  |
| `trigger_source` | VARCHAR | 是 | `manual`（ORM 端） |  |
| `error_message` | TEXT | 是 |  |  |
| `started_at` | DATETIME | 是 |  |  |
| `completed_at` | DATETIME | 是 |  |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |

- 索引 `ix_pexec_content_id`: (content_id)
- 索引 `ix_pexec_created_at`: (created_at)
- 索引 `ix_pexec_source_id`: (source_id)
- 索引 `ix_pexec_status`: (status)

#### pipeline_steps

流水线步骤执行记录。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `pipeline_id` | VARCHAR | 否 |  | FK → pipeline_executions.id（ON DELETE CASCADE） |
| `step_index` | INTEGER | 否 |  |  |
| `step_type` | VARCHAR | 否 |  |  |
| `step_config` | JSONB | 是 |  |  |
| `is_critical` | BOOLEAN | 是 | `False`（ORM 端） |  |
| `status` | VARCHAR | 是 | `pending`（ORM 端） |  |
| `input_data` | JSONB | 是 |  |  |
| `output_data` | JSONB | 是 |  |  |
| `error_message` | TEXT | 是 |  |  |
| `retry_count` | INTEGER | 是 | `0`（ORM 端） |  |
| `started_at` | DATETIME | 是 |  |  |
| `completed_at` | DATETIME | 是 |  |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |

- 索引 `ix_pstep_pipeline_id`: (pipeline_id)
- 索引 `ix_pstep_status`: (status)

#### pipeline_templates

流水线模板：显式定义全部步骤。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `name` | VARCHAR | 否 |  |  |
| `description` | TEXT | 是 |  |  |
| `steps_config` | JSONB | 否 |  |  |
| `is_builtin` | BOOLEAN | 是 | `False`（ORM 端） |  |
| `is_active` | BOOLEAN | 是 | `True`（ORM 端） |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |
| `updated_at` | DATETIME | 是 | （ORM 端） |  |

- 唯一约束 `None`: (name)

#### platform_credentials

平台凭证（`credential_data` Fernet 加密）。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `platform` | VARCHAR | 否 |  |  |
| `credential_type` | VARCHAR | 是 | `cookie`（ORM 端） |  |
| `credential_data` | TEXT | 否 |  |  |
| `display_name` | VARCHAR | 否 |  |  |
| `status` | VARCHAR | 是 | `active`（ORM 端） |  |
| `expires_at` | DATETIME | 是 |  |  |
| `extra_info` | JSONB | 是 |  |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |
| `updated_at` | DATETIME | 是 | （ORM 端） |  |

- 索引 `ix_credential_platform`: (platform)

#### prompt_templates

提示词模板。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `name` | VARCHAR | 否 |  |  |
| `template_type` | VARCHAR | 是 | `news_analysis`（ORM 端） |  |
| `system_prompt` | TEXT | 是 |  |  |
| `user_prompt` | TEXT | 否 |  |  |
| `output_format` | TEXT | 是 |  |  |
| `is_default` | BOOLEAN | 是 | `False`（ORM 端） |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |
| `updated_at` | DATETIME | 是 | （ORM 端） |  |

#### reading_progress

电子书阅读进度（与书 1:1）。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `content_id` | VARCHAR | 否 |  | FK → content_items.id（ON DELETE CASCADE） |
| `cfi` | TEXT | 是 |  |  |
| `progress` | FLOAT | 是 | `0`（ORM 端） |  |
| `section_index` | INTEGER | 是 | `0`（ORM 端） |  |
| `section_title` | VARCHAR | 是 |  |  |
| `updated_at` | DATETIME | 是 | （ORM 端） |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |

- 唯一索引 `uq_reading_progress_content`: (content_id)

#### source_configs

数据源配置。只描述「从哪来」；某种源类型能做什么由源类型注册表 `app/models/source_types.py` 决定。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `name` | VARCHAR | 否 |  |  |
| `source_type` | VARCHAR | 否 |  |  |
| `url` | VARCHAR | 是 |  |  |
| `description` | TEXT | 是 |  |  |
| `schedule_enabled` | BOOLEAN | 是 | `True`（ORM 端） |  |
| `schedule_mode` | VARCHAR | 否 | `auto`（库级） |  |
| `schedule_interval_override` | INTEGER | 是 |  |  |
| `calculated_interval` | INTEGER | 是 |  |  |
| `next_collection_at` | DATETIME | 是 |  |  |
| `periodicity_data` | JSONB | 是 |  |  |
| `periodicity_updated_at` | DATETIME | 是 |  |  |
| `hotspot_level` | VARCHAR | 是 |  |  |
| `hotspot_detected_at` | DATETIME | 是 |  |  |
| `pipeline_template_id` | VARCHAR | 是 |  | FK → pipeline_templates.id（ON DELETE SET NULL） |
| `config_json` | JSONB | 是 |  |  |
| `credential_id` | VARCHAR | 是 |  | FK → platform_credentials.id（ON DELETE SET NULL） |
| `auto_cleanup_enabled` | BOOLEAN | 是 | `False`（ORM 端） |  |
| `retention_days` | INTEGER | 是 |  |  |
| `last_collected_at` | DATETIME | 是 |  |  |
| `consecutive_failures` | INTEGER | 是 | `0`（ORM 端） |  |
| `is_active` | BOOLEAN | 是 | `True`（ORM 端） |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |
| `updated_at` | DATETIME | 是 | （ORM 端） |  |

- 索引 `ix_source_credential_id`: (credential_id)
- 索引 `ix_source_next_collection`: (is_active, schedule_enabled, next_collection_at)

#### sync_task_progress

同步的运行记录与进度通道：内置同步（手动 / 自动）与外部推送都写，`options_json._trigger` 区分。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `source_id` | VARCHAR | 否 |  | FK → source_configs.id（ON DELETE CASCADE） |
| `status` | VARCHAR | 是 | `pending`（ORM 端） |  |
| `phase` | VARCHAR | 是 |  |  |
| `message` | VARCHAR | 是 |  |  |
| `current` | INTEGER | 是 | `0`（ORM 端） |  |
| `total` | INTEGER | 是 | `0`（ORM 端） |  |
| `result_data` | JSONB | 是 |  |  |
| `error_message` | TEXT | 是 |  |  |
| `options_json` | JSONB | 是 |  |  |
| `started_at` | DATETIME | 是 |  |  |
| `completed_at` | DATETIME | 是 |  |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |
| `updated_at` | DATETIME | 是 | （ORM 端） |  |

- 索引 `ix_sync_progress_created`: (created_at)
- 索引 `ix_sync_progress_source_status`: (source_id, status)

#### system_settings

键值配置。含 `content.filters` 等 JSON 业务对象。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `key` | VARCHAR | 否 |  | PK |
| `value` | TEXT | 是 |  |  |
| `description` | TEXT | 是 |  |  |
| `updated_at` | DATETIME | 是 | （ORM 端） |  |

#### watch_logs

影视库：一部影片的多次观看记录（日期 + 精度 / 评分 / 感想）。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `record_id` | VARCHAR | 否 |  | FK → watch_records.id（ON DELETE CASCADE） |
| `watched_at` | DATE | 是 |  |  |
| `watched_precision` | VARCHAR | 是 |  |  |
| `my_rating` | SMALLINT | 是 |  |  |
| `note` | TEXT | 是 |  |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |
| `updated_at` | DATETIME | 是 | （ORM 端） |  |

- 索引 `ix_watch_logs_record`: (record_id)

#### watch_records

影视库：用户对一部影片的标记（与影片 1:1）。`my_rating` / `watched_at` 是最近一次观看记录的缓存。

| 列 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | VARCHAR | 否 | （ORM 端） | PK |
| `content_id` | VARCHAR | 否 |  | FK → content_items.id（ON DELETE CASCADE） |
| `status` | VARCHAR | 否 | `unmarked`（ORM 端） |  |
| `my_rating` | SMALLINT | 是 |  |  |
| `watched_at` | DATE | 是 |  |  |
| `watched_precision` | VARCHAR | 是 |  |  |
| `tags` | ARRAY | 否 | （ORM 端） |  |
| `status_source` | VARCHAR | 否 | `manual`（ORM 端） |  |
| `created_at` | DATETIME | 是 | （ORM 端） |  |
| `updated_at` | DATETIME | 是 | （ORM 端） |  |

- 索引 `ix_watch_records_status`: (status)
- 唯一索引 `uq_watch_records_content`: (content_id)

<!-- END GENERATED: schema -->

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

### 4.0 数据怎么进来：四种执行器

每种数据源类型在源类型注册表（`backend/app/models/source_types.py`）里登记一种执行器（`runner`），它决定这个数据源能被谁驱动、运行记录写在哪。

| 执行器 | 语义 | 触发 | 运行记录 | 产出 | 典型类型 |
|---|---|---|---|---|---|
| `collector` 采集 | 增量追加 | 智能调度器每分钟选源；「采集」按钮 | `collection_records`（同时是调度算法的输入） | PENDING → 可选流水线 | `rss.*` `podcast.apple` `web.scraper` `account.generic` `api.akshare`；`file.upload` 只能手动 |
| `syncer` 内置同步 | 全量对账（upsert + 标记已消失） | 同步管理页 / 领域页按钮；注册表 `auto_sync_minutes` 开启的自动同步 | `sync_task_progress`（带 SSE 进度） | 直接 READY，不进流水线 | `sync.emby`（每 30 分钟）`sync.bilibili` `sync.wechat_read` |
| `push` 外部推送 | 同上，但抓取在用户机器上 | 本机脚本（`scripts/*-sync.py`）/ Fountain 客户端调推送 API | `sync_task_progress`（`_trigger=push`） | 直接 READY | `sync.apple_books` `sync.kindle` `sync.*_bookmarks` |
| `none` 无执行器 | 纯归属容器 | — | — | 由领域接口直接写入 | `user.film` `user.note` |

- **入口处强制**：调度器、采集任务、采集端点只接受 `collector`，其余返回 400——不写采集记录、不动调度状态。（审计前采集任务会对同步类数据源照常执行并写下「成功 0 条」的假记录。）
- **选哪种**：公网可访问、无需用户登录 → 采集；需要登录态但凭证可以加密存在服务端 → 内置同步；数据在用户本地（文件、系统数据库）→ 外部推送；用户直接创建 → 领域接口。
- B 站、微信读书同时接受外部推送（注册表 `accepts_push`），两条通路共用同一份 upsert。
- 同步任务的发起与回收在 `services/sync/runner.py`：`start_sync`（手动 / 自动共用）、`run_push_sync`、`expire_stale_progress`（进度行 15 分钟无更新即判定 worker 已死并回收，否则该数据源会永久 409）。

### 4.1 Collector 接口

```python
class BaseCollector(ABC):
    @abstractmethod
    async def collect(self, source: SourceConfig, db: Session) -> list[ContentItem]:
        """从数据源抓取新条目并写库，返回成功插入的新 ContentItem。
        去重在 DB 层由 (source_id, external_id) 唯一约束 + SAVEPOINT 处理。
        新建 ContentItem 必须显式设置 kind。"""
```

### 4.2 Collector 实现矩阵

| Collector | 适用 SourceType | 采集方式 | 说明 |
|-----------|-----------------|----------|------|
| `RSSCollector` | `rss.hub`, `rss.standard` | RSSHub 服务 / feedparser 直接解析 | 统一处理所有 RSS 类型 |
| `ScraperCollector` | `web.scraper` | L1/L2/L3 三级策略 | 通用网页抓取 |
| `AkShareCollector` | `api.akshare` | AkShare API | 金融数据 |
| `PodcastCollector` | `podcast.apple` | 播客 RSS 解析 | Apple Podcasts |
| `FileUploadCollector` | `file.upload` | 扫描数据源目录 | 只能手动触发，不进调度 |
| `GenericAccountCollector` | `account.generic` | 平台特定 API | 其他需认证的平台 |

注意:
- 没有 BilibiliVideoCollector / YouTubeVideoCollector。视频下载由流水线中的 `localize_media` 步骤 (yt-dlp) 处理, 不是 Collector 的职责。
- `sync.*` / `user.*` 类型没有 Collector，见 §4.0。`COLLECTOR_MAP` 在导入时与源类型注册表对账，不一致则启动失败。
- `FileUploadCollector` 扫描的是 `data/uploads/<source_id>/` 目录；`POST /api/content/upload` 写入的是 `data/uploads/<content_id>/`，两者互不相干。
- `AkShareCollector` 写 `finance_data_points`，不产出 ContentItem。

### 4.3 全文抓取分级（L1 HTTP → L2 Crawl4AI → L3 Browserless）

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

对于需要用户凭证（Cookie）且不适合作为 Collector 的平台，支持两种同步模式：

**同步模式**:

| 模式 | 说明 | 适用类型 |
|------|------|---------|
| **internal** | Worker 内置 Fetcher，通过 `/api/sync/run/{source_type}` 触发 | sync.wechat_read, sync.bilibili, sync.emby |
| **script** | 外部脚本独立采集后推送 | sync.apple_books 等需要本地数据的类型 |

**统一同步管理 API** (`/api/sync`):

| 端点 | 说明 |
|------|------|
| `GET /api/sync/status` | 所有同步源状态 |
| `POST /api/sync/run/{source_type}` | 触发 internal 模式同步 |
| `GET /api/sync/progress/{progress_id}` | SSE 实时进度推送 |
| `POST /api/sync/link-credential` | 关联凭证到同步源 |

**传统三步式同步 API** (兼容外部脚本):

| API 前缀 | 适用类型 | 端点 |
|----------|---------|------|
| `/api/ebook/sync` | `sync.apple_books`, `sync.wechat_read` | setup / status / sync (书籍+标注) |
| `/api/video/sync` | `sync.bilibili` | setup / status / sync (视频元数据) |
| `/api/bookmark/sync` | `sync.safari_bookmarks`, `sync.chrome_bookmarks` | setup / status / sync (书签) |
| `/api/films/sync/setup` | `sync.emby` | 仅 setup；拉取由 internal Fetcher 完成（`app/services/sync/emby.py`） |

**同步流程** (三步式):
1. `POST /setup?source_type=sync.xxx` — 获取或创建 SourceConfig，返回 source_id
2. `GET /status?source_id=xxx` — 查询上次同步时间，用于增量过滤
3. `POST /sync` — 推送数据（支持批量 upsert）

**外部脚本**:

| 脚本 | 平台 | 数据 |
|------|------|------|
| `scripts/bilibili-sync.py` | B站 | 收藏夹/历史/动态视频 |
| `scripts/wechat-read-sync.py` | 微信读书 | 书籍元数据、阅读进度、划线标注 |
| `scripts/apple-books-sync.py` | Apple Books | 书籍+标注 (读取本地 BKLibrary SQLite) |

脚本独立于后端环境，仅依赖 `httpx`，支持增量/全量/预览模式。

**同步进度机制**: `sync_task_progress` 表记录同步任务进度，Worker 更新进度行，API 端通过 SSE (`/api/sync/progress/{id}`) 推送给前端实时显示。

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
GET  /api/dashboard/stats              → { sources_count, contents_today/yesterday/total(剔除重复项), pipelines_running, pipelines_failed(近 24h), pipelines_pending, as_of }
GET  /api/dashboard/collection-trend   → 采集趋势数据（count 剔除重复项；含采集成功率）
GET  /api/dashboard/daily-stats        → 每日统计（items_found 为源端发现总数，items_new 为实际新增）
GET  /api/dashboard/source-health      → { window_days, summary{healthy,warning,error,disabled,sync}, sources[] }。只对启用且需采集的源分 healthy/warning/error 三级（consecutive_failures + 近 7 天失败率），每源附 reasons[]、窗口内采集/失败/新增数、last_collected_at、last_item_at；disabled/sync 仅计数
GET  /api/dashboard/content-status-distribution → 内容状态分布
GET  /api/dashboard/storage-stats      → 存储统计
GET  /api/dashboard/dedup-stats        → 去重统计（重复条数、重复组数、今日新增重复、按数据源的重复率）
GET  /api/dashboard/recent-activity    → 最近活动
GET  /api/dashboard/user-behavior-stats → 用户行为统计。概览含 read_*（已处理，view_count>0）与 opened_*（已打开，opened_at）两套口径；热力图/趋势/偏好按 opened_at 计
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
POST   /api/sources/import            → { imported: int } (OPML 导入；与 /api/sources 同前缀，注册顺序须在 /{source_id} 之前)
GET    /api/sources/export            → OPML file
GET    /api/sources/export/full       → 数据源配置全量导出 (JSON)
POST   /api/sources/import/full       → 全量导入（按源类型注册表校验类型，非采集型强制不进调度）
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
POST   /api/media/{media_id}/favorite  → 切换媒体收藏
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

#### Bilibili Auth (B站认证，挂载在 Credentials 路由下)
```
POST   /api/credentials/bilibili/qrcode/generate → { qr_url, token } (B站扫码登录)
GET    /api/credentials/bilibili/qrcode/poll     → { status } (轮询扫码结果)
```

#### Finance (金融数据)
```
GET    /api/finance/presets             → 预设金融指标
GET    /api/finance/sources             → 金融数据源列表
GET    /api/finance/summary             → 金融数据概要
GET    /api/finance/timeseries/{source_id} → 时间序列数据
```

#### Export (全量导入导出，挂载在 Sources 路由下)
```
GET    /api/sources/export/full        → 全量导出
POST   /api/sources/import/full        → 全量导入
```

#### Bookmark Sync (书签同步)
```
POST   /api/bookmark/sync/setup        → { source_id } (创建/获取 sync 数据源)
GET    /api/bookmark/sync/status        → SyncStatus (同步状态)
POST   /api/bookmark/sync               → SyncResponse (推送书签数据)
```

#### Films (影视资料库)
```
POST   /api/films/sync/setup           → { source_id } (创建/获取 sync.emby 源)
GET    /api/films/stats                → 状态/类型计数 + 类型/年份筛选项 + tmdb/emby 是否配置
GET    /api/films/search?q=&year=      → TMDb 候选（需 tmdb_api_key）
GET    /api/films                      → 分页列表；q/status/kind/genre/year_from/year_to/in_emby/min_rating/sort
POST   /api/films                      → 手工添加（tmdb_id+kind 或 title+year）
POST   /api/films/records/batch        → 批量标记（content_id | tmdb_id | title+year 定位）
GET    /api/films/{id}                 → 详情（元数据 + emby 事实 + record）
PUT    /api/films/{id}/record          → 更新用户标记
POST   /api/films/{id}/logs            → 新增一次观看记录（日期 + 精度 / 评分 / 感想）；PUT / DELETE /api/films/{id}/logs/{log_id}
DELETE /api/films/{id}                 → 删除资料库记录（不触碰 Emby）
POST   /api/films/enrich-missing?limit= → 批量补全元数据（TMDb 详情；需 tmdb_api_key），返回 remaining
POST   /api/films/{id}/enrich          → 单条补全
POST   /api/films/{id}/douban          → 解析/手填豆瓣条目 id（详情页手动触发）；DELETE 清除
PUT    /api/films/{id}/meta            → 修正片名/年份/类型（骨架顺手重搜 TMDb）
POST   /api/films/{id}/relink          → 重新识别：关联指定 TMDb 条目，元数据整体替换，标记与 Emby 事实保留
GET    /api/films/{id}/poster          → 海报代理（Emby → TMDb），免认证 GET
```
数据模型与覆盖规则见 `docs/design_film_library.md`；用户标记表 `watch_records`。

#### Sync (统一同步管理)
```
GET    /api/sync/status                 → 所有同步源状态（`last_sync_at` = 最近一次成功同步，取自 `sync_task_progress`；script 模式无进度记录，退回 `source.last_collected_at`）
POST   /api/sync/run/{source_type}      → 触发内置同步 (internal 模式)
GET    /api/sync/progress/{progress_id} → SSE 实时进度推送
POST   /api/sync/link-credential        → 关联凭证到同步源
```

#### Ebook (书架管理)
```
GET    /api/ebook/list                  → 书籍列表
GET    /api/ebook/filters               → 筛选项
GET    /api/ebook/{id}                  → 书籍详情；DELETE 删除
GET    /api/ebook/{id}/cover            → 封面
PUT    /api/ebook/{id}/metadata         → 更新元数据；GET .../metadata/search、POST .../metadata/apply 联网补全
GET    /api/ebook/annotations           → 全部标注；GET /api/ebook/annotations/recent 最近标注
GET    /api/ebook/{id}/annotations      → 某本书的标注；POST 新增；PUT / DELETE .../{ann_id}
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

# 注意：cron 表达式一律是 UTC。下面括号里是对应的北京时间。

# 内置同步型数据源的自动同步 - 每 10 分钟检查，按注册表 auto_sync_minutes 到期发起（目前只有 Emby，30 分钟）
@proc_app.periodic(cron="*/10 * * * *")
@proc_app.task(queue="scheduled", queueing_lock="auto_sync_sources")
async def auto_sync_sources(timestamp): ...

# 日报 (0 14 * * *) / 周报 (0 1 * * 1)：2026-09-20 停用，定义在 scheduled_tasks.py 里注释保留。
# 此前从未成功过：get_llm_config() 在未配置 LLM Key 时 raise，而 report_tasks 期望的是静默降级。
# 恢复前先修这条降级路径。

# 周期性分析 - 20:00 UTC (次日 04:00 CST)，只分析可调度的采集型数据源
@proc_app.periodic(cron="0 20 * * *")
async def analyze_source_periodicity(timestamp): ...

# 清理调度器 - 每小时检查，按 system_settings 配置的时间动态执行内容清理 / 记录清理
@proc_app.periodic(cron="0 * * * *")
async def cleanup_scheduler(timestamp): ...

# 任务队列自身的清理 - 19:20 UTC (03:20 CST)：删 7 天前结束的作业，回收心跳丢失超 1 小时的僵死作业
@proc_app.periodic(cron="20 19 * * *")
async def cleanup_job_queue(timestamp): ...
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
      PUPPETEER_WS_ENDPOINT: ws://browserless:3000?token=${BROWSERLESS_TOKEN}
    depends_on:
      - browserless

  browserless:                               # v2（v1 browserless/chrome 已停更）
    image: ghcr.io/browserless/chromium:latest
    environment:
      TOKEN: ${BROWSERLESS_TOKEN}            # v2 强制鉴权，连接需带 ?token=
      CONCURRENT: 3

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
      BROWSERLESS_TOKEN: ${BROWSERLESS_TOKEN}
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
      BROWSERLESS_TOKEN: ${BROWSERLESS_TOKEN}
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
      BROWSERLESS_TOKEN: ${BROWSERLESS_TOKEN}
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

三套脚本对应三种拓扑：

| 脚本 | 运行位置 | 目标 | Compose 文件 |
|------|----------|------|--------------|
| `deploy-local.sh` | 开发机 | 本机开发容器（Colima） | `docker-compose.local.yml` |
| `deploy-remote.sh` | 开发机 | 通过 SSH 部署到远程服务器 | `docker-compose.remote.yml` |
| `deploy-home-server.sh` | 家庭服务器本机 | 同机 `/opt/allin-one` 生产目录 | `docker-compose.home-server.yml`（机器本地文件，不入库） |

`deploy-home-server.sh` 流程：rsync 源码到生产目录（`--delete`，排除 `.env`/compose/数据/证书等本地文件）→ 探测可用基础镜像源（依次拉取 node/docker-cli/python 三个基础镜像，超时即换下一个，最后直连 Docker Hub）→ `docker compose build --build-arg REGISTRY=<选中源>` → `up -d` → 等待 healthy → `alembic upgrade head` → 健康检查。Dockerfile 的 `ARG REGISTRY` 默认 `docker.1ms.run/`，其它部署路径行为不变。

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

---

## 10. MCP Server

### 10.1 概述

`backend/mcp_server.py` 基于 FastMCP，直连 PostgreSQL（独立 SQLAlchemy engine，pool_size=3），供 Claude Code / Cursor 等 AI 助手查询和管理个人信息流数据。

传输模式：
- 默认 `stdio`（本地开发，Claude Code 直接调用）
- `MCP_TRANSPORT=http` 时使用 `streamable-http`，监听 `0.0.0.0:8001`（远程部署）

### 10.2 工具清单

共 20 个工具，按读写属性分类：

**只读工具 (readOnlyHint=True)**

| 工具名 | 功能 | 关键参数 |
|--------|------|----------|
| `list_content` | 搜索内容列表（支持 offset 分页与未读过滤） | time_range / start_date / end_date / source_name / keyword / status / favorites_only / unread_only / limit / offset |
| `get_content_detail` | 获取内容全文及 AI 分析 | content_id |
| `get_sources` | 列出所有数据源及状态 | status / keyword |
| `get_favorites_summary` | 收藏统计（按源分布、按月趋势、最近列表） | time_range (7d/30d/90d/all) |
| `get_market_snapshot` | 11 个主要指数实时概览（A股六大 + 恒生系三个 + 道指/纳指） | — |
| `get_stock_quote` | 个股实时行情查询 | symbols / keyword / market (A/HK/US/crypto) / limit |
| `get_kline` | 历史 K 线数据 | symbol / market (A/HK/US/index/etf) / period (daily/weekly/monthly) / count / adjust |
| `get_macro_indicator` | 中国宏观经济指标 | indicator (cpi/ppi/pmi/gdp/m2/shibor) / count |
| `list_films` | 影视资料库列表（元数据 + Emby 事实 + 用户标记），推荐前先拉全库 | status / kind / genre / year_from / year_to / in_emby / keyword / limit / offset |
| `search_film` | TMDb 搜索取 tmdb_id（需 `tmdb_api_key`） | q / year |
| `get_system_health` | 「有东西悄悄挂了吗」一次回答：只列有问题的部分——采集源异常、同步 / 推送源异常（上次失败、僵死、缺凭证、自动同步落后）、后台任务失败（`still_failing` 标出至今没再成功过的）与卡住的作业 | time_range (1d/3d/7d，仅作用于后台任务窗口) |
| `get_source_health` | 数据源健康判定（与仪表盘同一口径）；指定数据源时附最近运行记录与错误文本，回答「某源为何停更」 | source_id / source_name / problems_only / runs |
| `get_recent_failures` | 按时间倒序的失败事件流，合并采集、同步 / 推送、后台任务三类运行记录 | time_range / source_id / source_name / limit |

运行健康度三个工具的判定逻辑在 `app/services/system_health.py`，`GET /api/dashboard/source-health` 调用同一份 `source_health()`，两边口径不会分叉。该模块只读：僵死的同步任务只标出、不回收。后台任务的失败来自 `procrastinate_jobs` / `procrastinate_events`——采集记录与同步记录都挂在数据源上，不属于任何数据源的定时任务（日报、清理、调度心跳）失败只有这里看得到；队列不保存异常文本（原因在 worker 容器日志），且已结束的作业 7 天后被 `cleanup_job_queue` 清除，所以最多回看 7 天。

金融数据工具以蚂蚁 financial-data API 为主数据源，akshare/雪球/腾讯/新浪为降级路径（crypto 走 CoinGecko），带内存缓存（TTL 按工具类型区分）和超时保护，不写入本地数据库。响应含 `data_source` 字段标识实际来源。详见 §10.6。

**写操作工具 (readOnlyHint=False)**

| 工具名 | destructiveHint | idempotentHint | 功能 |
|--------|----------------|----------------|------|
| `toggle_favorite` | False | False | 批量收藏/取消收藏内容 |
| `mark_read` | False | True | 批量标记内容已读（与 Web UI 共用 view_count 读态） |
| `create_source` | False | False | 创建数据源（支持 URL 自动推导 source_type） |
| `update_source` | False | True | 更新数据源配置 |
| `delete_source` | True | False | 删除数据源（cascade 参数控制是否级联删除内容） |
| `toggle_source` | False | True | 启用/禁用数据源 |
| `mark_films` | False | True | 批量建/改影片观影标记（content_id / tmdb_id / title+year 定位，缺失影片先建骨架）；写入即 `status_source=manual`，Emby 同步不再覆盖 |

### 10.3 错误返回约定

所有工具失败时返回同一形状：`{"error": "<给人看的文案>", "error_code": "<机器码>", ...附加字段}`，由 `_err()` / `_internal_error()` 生成，不要再手写 `json.dumps({"error": ...})`。`error` 保持为字符串（与早期形状兼容），agent 按 `error_code` 分支：

| error_code | 含义 | 附加字段 |
|------------|------|----------|
| `INVALID_ARGUMENT` | 参数缺失 / 取值不合法 | 可选 `valid_values` |
| `NOT_FOUND` | 指定的对象不存在 | 定位用的入参、可选 `hint` |
| `AMBIGUOUS` | 模糊匹配命中多个 | `candidates` |
| `CONFLICT` | 与现有状态冲突（重名、受保护的数据源不能非级联删除） | 可选 `hint` |
| `NOT_CONFIGURED` | 依赖的外部服务未配置 Key | — |
| `UPSTREAM_UNAVAILABLE` | 外部接口暂不可用 | 可选 `retryable` |
| `INTERNAL` | 未预期异常，堆栈在 `allin-mcp` 容器日志 | `hint` |

批量工具（`mark_films`）里逐条的 `{"ok": false, "error": ...}` 是结果的一部分，不走此约定。REST API 的 `{code, data, message}` 不在此次统一范围内（前端有 153 处按现有形状判断，见审计 §4 🔴-6）。

### 10.4 数据源定位辅助函数

`_resolve_source(db, source_id, source_name)` — 写操作工具共用的定位逻辑：
- `source_id` 精确匹配（优先）
- `source_name` 模糊匹配（ilike），匹配多条时返回 `AMBIGUOUS` + `candidates` 供 AI 确认

### 10.5 服务层复用

MCP 写操作调用 `app/services/source_service.py` 中的共享校验函数，与 Router 保持一致：
- `validate_source_type(source_type)` — 校验 SourceType 合法性
- `validate_source_config(source_type, url, config_json)` — 校验各类型必填配置
- `validate_source_name_unique(name, db, exclude_id)` — 校验名称唯一性
- `validate_template_exists(pipeline_template_id, db)` — 校验模板存在性

### 10.6 金融数据源架构

> 定稿于 2026-09-04（g-design：architect-designer 方案 + product-reviewer 有条件通过后精简）

#### 分层

```
@mcp.tool 工具函数 (mcp_server.py)          ← 契约层：参数校验 + 输出 JSON 组装，签名与既有键名不可变
        │
        ├─ 主路径 ─→ app/services/financial_data_client.py   ← 蚂蚁 financial-data API 适配
        │                 └─ app/services/financial_symbols.py ← 纯函数 symbol 映射（可单测无网络）
        │
        └─ 降级 ──→ 既有 _xq_spot / _ak_call 路径（雪球/腾讯/新浪/akshare，原地保留）
```

工具函数内不出现 HTTP 调用或 `.SH/.O` 后缀字符串；所有蚂蚁 API 细节封闭在 client 内。crypto 路径（CoinGecko）不变。

#### 主数据源：蚂蚁 financial-data API

- 端点：`POST {FINANCIAL_DATA_BASE_URL}/api/v1/common_query`，headers `X-API-Key` + `X-API-Version`
- 固定场景直接 `mode=data` + 已知 url：`/api/v1/quote/basic-snapshot`（行情快照，支持多 symbol 批量）、`/api/v1/quote/derived-snapshot`（估值）、`/api/v1/quote/kline-batch`（K 线）
- 宏观走 `mode=macro_query` + 静态 seed 表（`_MACRO_FD_SEED`，indicator_code 由探针经 macro_recall 一次性解析并对拍验证后固化）；seed 未覆盖的指标（cpi/shibor，蚂蚁无同口径数据）无限期走 akshare legacy，运行时不做召回
- 响应解析：严格按 `meta.fields` 动态映射（`dict(zip(fields, row))`），禁止固定下标；`SUCCESS` 不代表有数据，`FAILED` 也检查可用子结果
- symbol 格式：A股 `600519.SH/.SZ/.BJ`（复用既有交易所判定规则改前缀为后缀）；港股 `zfill(5).HK`；美股需 `.O/.N/.A` 后缀——静态表（高频 ticker）→ 进程缓存 → entity_recognition 兜底 → 降级 legacy；指数用静态表 `_INDEX_SYMBOLS`（注意 `000001` 指数 SH / 平安银行 SZ 同码歧义，快照与个股走不同映射表），部署前由探针脚本一次性验证，不做运行时推断

#### 稳定性设计（个人项目量级，刻意轻量）

- **错误分类**：`classify_error(exc) → "retryable" | "fatal" | "quota"` 纯函数。retryable（超时/5xx/连接错误）重试 ≤2 次（退避 + jitter，单工具调用总预算 ≤12s）；fatal/quota 不重试直接降级
- **主源冷却**：不引入熔断状态机——记录最近主源失败时间戳，quota/连续失败后 N 秒内跳过主源直接走 legacy
- **降级链**：主源 → legacy（按 symbol 部分降级：批量查询中失败的标的单独回退补齐，不拖垮全批）→ 报错。响应 `data_source` 取值：`financial_data` / `legacy` / `mixed`
- **缓存**：单层落在 client（工具层不再叠加，避免双层 TTL 掩盖故障）。TTL：行情快照 30s、估值 300s、K 线 300s、宏观 3600s、entity/symbol 解析 7d。例外：`get_market_snapshot` 保留既有的工具层 JSON 缓存（30s，与 client 层同 TTL），使降级后的 legacy 结果也能被缓存
- **总预算**：单次主源请求（含重试）硬上限 12s（`asyncio.wait_for`），超时按可重试失败计入冷却
- **契约保护**：K 线日期归一化 `YYYY-MM-DD`；`hfq`（后复权）与港/美股复权请求蚂蚁不支持 → 降级 legacy，绝不静默换复权口径；跨市场混合来源时响应加 note 提示复权口径差异；宏观 `label` 取静态表保证中文标签字面量不变

#### 配置与回退

`FINANCIAL_DATA_ENABLED` / `FINANCIAL_DATA_API_KEY` / `FINANCIAL_DATA_BASE_URL` / `FINANCIAL_DATA_API_VERSION` / `FINANCIAL_DATA_TIMEOUT` / `FINANCIAL_DATA_TOOLS`（逗号分隔的工具级开关）。key 走环境变量（基础设施密钥，与 `BROWSERLESS_TOKEN` 同类，不走 system_settings+Fernet）。回退 = `ENABLED=false`（或从 `FINANCIAL_DATA_TOOLS` 移除单个工具）+ 重启 allin-mcp，无需构建。key 留空时自动全量降级，功能不受影响。

#### 质量门禁

1. **Phase 0 探针**（`scripts/verify/financial_data/probe_api.py`）：切换前验证 symbol 格式、字段单位（pct_chg %/小数、volume 股/手、market_cap 元/亿元、m2 亿/万亿）、宏观 indicator_code、批量入参上限、配额政策——未完成不开工
2. **宏观口径对拍**（`verify_parity.py`）：新旧源近 12 期数值偏差 <1% 才允许该指标进 seed；不达标的指标无限期保持 akshare（按指标粒度灰度）
3. **端到端冒烟**：每个工具切换后用真实投研 skill（如 investment-research）跑一次分析任务，验证下游消费正常
4. client 内保留廉价合理性断言（`abs(pct_chg)>30`、`price<=0` 打 WARNING 不改数据），拦截静默单位错位
