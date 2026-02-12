# Allin-One

个人信息聚合与智能分析平台。从 RSS / Bilibili / YouTube / 网页等渠道自动采集内容，通过 LLM 分析后结构化呈现。

## 功能特性

- **多源采集** — 支持 RSS、B站、YouTube、网页抓取、文件上传、AkShare 等 8 种数据源，统一通过 RSSHub 网关聚合
- **三级抓取** — L1 HTTP → L2 Browserless (无头浏览器) → L3 browser-use (AI 驱动)，按需自动升级
- **流水线引擎** — 数据源与处理流水线解耦，可编排多步骤分析链（摘要、翻译、分类、评分等）
- **LLM 分析** — 接入 OpenAI 兼容接口，支持自定义 Prompt 模板进行智能分析
- **多渠道推送** — Webhook、钉钉、邮件，分析结果实时推送
- **视频处理** — 支持视频下载（yt-dlp）与在线播放（ArtPlayer）
- **响应式 UI** — 卡片式信息流、仪表盘、内容管理，适配移动端

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2 |
| 前端 | Vue 3.4, Vite 5, TailwindCSS 3.4, Pinia, Axios |
| 数据库 | SQLite (WAL 模式) |
| 任务队列 | Huey (SQLite 后端) |
| 定时调度 | APScheduler |
| 外部服务 | RSSHub, Browserless, OpenAI 兼容 API |
| 部署 | Docker Compose |

## 快速开始

### Docker 部署（推荐）

```bash
# 克隆项目
git clone <repo-url> && cd allin-one

# 配置环境变量
cp backend/.env.example backend/.env
# 编辑 .env 填入 LLM API Key 等配置

# 一键启动
docker compose up -d --build
```

启动后访问 `http://localhost:8000`。

### 本地开发

```bash
# 后端
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 前端（另一个终端）
cd frontend
npm install
npm run dev

# 任务 Worker（另一个终端）
cd backend
huey_consumer app.tasks.huey_instance.huey
```

或使用一键开发脚本：

```bash
./local-dev.sh
```

## 项目结构

```
allin-one/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── core/                # 配置与数据库
│   │   ├── models/              # SQLAlchemy 模型
│   │   ├── schemas/             # Pydantic Schema
│   │   ├── api/routes/          # API 路由
│   │   ├── services/
│   │   │   ├── collectors/      # 数据采集器 (RSS, B站, 网页...)
│   │   │   ├── pipeline/        # 流水线引擎 (编排/执行/注册)
│   │   │   ├── analyzers/       # LLM 分析器
│   │   │   └── publishers/      # 推送渠道 (Webhook, 钉钉, 邮件)
│   │   └── tasks/               # Huey 异步任务 + APScheduler
│   ├── alembic/                 # 数据库迁移
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── views/               # 8 个页面视图
│       ├── components/          # 可复用组件
│       ├── stores/              # Pinia 状态管理
│       ├── composables/         # 组合函数
│       └── api/                 # Axios 封装
├── docs/                        # 设计文档
├── docker-compose.yml           # 生产部署配置
└── Dockerfile                   # 多阶段构建
```

## 核心架构

```
数据源 (Source)          流水线 (Pipeline)           输出
┌──────────┐           ┌──────────────────┐       ┌──────────┐
│ RSS      │──┐        │ fetch_content    │       │ 结构化存储│
│ B站      │  │ 采集   │ llm_analyze      │  推送 │ Webhook  │
│ YouTube  │──┼──────→ │ extract_summary  │─────→ │ 钉钉     │
│ 网页抓取  │  │        │ translate        │       │ 邮件     │
│ 文件上传  │──┘        │ ...              │       │ 仪表盘   │
└──────────┘           └──────────────────┘       └──────────┘
     ↑                        ↑
     │                        │
  Collector              Pipeline Engine
  负责「从哪来」          负责「怎么处理」
```

- **数据源与流水线解耦**：通过 `pipeline_template_id` 外键绑定，灵活组合
- **抓取与处理分离**：Collector 产出 ContentItem，Pipeline 负责后续处理
- **步骤可编排**：Pipeline 步骤通过 Registry 注册，支持自定义扩展

## 页面概览

| 页面 | 路径 | 功能 |
|------|------|------|
| 仪表盘 | `/dashboard` | 统计概览、采集趋势、告警 |
| 信息流 | `/feed` | 卡片式浏览、筛选、排序 |
| 数据源 | `/sources` | 数据源 CRUD、OPML 导入导出 |
| 内容库 | `/content` | 表格检索、批量操作 |
| 提示词模板 | `/prompt-templates` | LLM Prompt 配置管理 |
| 流水线 | `/pipelines` | 执行历史、状态监控 |
| 视频 | `/video-download` | 视频下载与播放 |
| 设置 | `/settings` | 系统配置、代理设置 |

## 文档

- [产品方案 PRD](docs/product_spec.md)
- [系统架构与 API 规范](docs/system_design.md)
- [业务术语与枚举定义](docs/business_glossary.md)
- [调度器与流水线设计](docs/design_scheduler_pipeline.md)

## 关键设计决策

| 决策 | 原因 |
|------|------|
| SQLite 而非 PostgreSQL | 个人项目，单机部署，WAL 模式性能足够 |
| Huey 而非 Celery | 无需 Redis，SQLite 后端更轻量 |
| 前后端同容器 | Vite 构建产物由 FastAPI 静态服务，简化部署 |
| RSSHub 统一网关 | B站/YouTube 等均走 RSSHub，避免维护多种采集协议 |

## License

MIT
