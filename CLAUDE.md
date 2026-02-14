# Allin-One

个人信息聚合与智能分析平台。从 RSS/Bilibili/YouTube/网页等渠道自动采集内容，通过 LLM 分析后结构化呈现。

## 核心架构约束

- **数据源与流水线解耦**: 数据源只管「从哪来」，流水线只管「怎么处理」，通过 `source.pipeline_template_id` FK 绑定
- **没有** `video_bilibili` 等混合 SourceType，视频通过 rsshub 发现 + localize_media 步骤处理
- **抓取与处理分离**: Collector 负责抓取产出 ContentItem，流水线只做处理，不含 fetch 步骤
- **自动预处理**: 流水线分两阶段——系统自动注入预处理步骤 (enrich_content / localize_media)，然后拼接用户模板的后置步骤
- **媒体项独立**: ContentItem 不再有 media_type 字段，媒体通过 MediaItem 一对多关联管理
- **三级抓取**: L1 HTTP → L2 Browserless → L3 browser-use，按需升级
- **数据目录**: `data/` 在项目根目录（非 backend/data/），backend 和 worker 共享同一挂载

## 技术栈

后端 Python 3.11+ (FastAPI + PostgreSQL + Huey + APScheduler)，前端 Vue 3 + Vite + TailwindCSS，部署 Docker Compose。
Miniflux 作为 RSS 前端（管理订阅+全文提取），RSSHub 生成非标准平台 feed。

## 常用命令

```bash
# 开发
cd backend && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev

# 任务 Worker
cd backend && huey_consumer app.tasks.huey_instance.huey

# 数据库迁移
cd backend && alembic revision --autogenerate -m "description"
cd backend && alembic upgrade head

# 部署
docker compose up -d --build
```

## 代码规范

- Python: PEP 8, type hints, async/await 优先
- Vue: `<script setup>` Composition API
- 命名: snake_case (Python), camelCase (JS), kebab-case (文件名)
- Git: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:` 前缀

## 关键决策

- PostgreSQL: 与 Miniflux 共用实例，一个 PG 两个 database (allinone + miniflux)
- Huey (非 Celery): 无需 Redis，SQLite 后端轻量（任务队列仍用 SqliteHuey）
- 前后端同容器: Vite 构建产物由 FastAPI 静态服务
- Miniflux: RSS 订阅管理+全文提取前端，MinifluxCollector 通过 API 拉取

## 文档导航

- `docs/product_spec.md` — 产品方案 PRD
- `docs/system_design.md` — 系统架构与 API 规范
- `docs/business_glossary.md` — 业务术语与枚举定义
- `backend/CLAUDE.md` — 后端开发规范
- `backend/app/services/CLAUDE.md` — Pipeline/Collector 开发规范
- `frontend/CLAUDE.md` — 前端开发规范
