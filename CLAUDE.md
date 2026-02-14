# Allin-One

个人信息聚合与智能分析平台。从 RSS/Bilibili/YouTube/网页等渠道自动采集内容，通过 LLM 分析后结构化呈现。

## 核心架构约束

- **数据源与流水线解耦**: 数据源只管「从哪来」，流水线只管「怎么处理」，通过 `source.pipeline_template_id` FK 绑定
- **没有** `video_bilibili` 等混合 SourceType，视频通过 rsshub 发现 + localize_media 步骤处理
- **抓取与处理分离**: Collector 负责抓取产出 ContentItem，流水线只做处理，不含 fetch 步骤
- **自动预处理**: 流水线分两阶段——系统用 raw_data 填充 processed_content 并自动注入 localize_media，然后拼接用户模板的后置步骤。enrich_content 保留为可选步骤，用户可在模板中手动添加
- **媒体项独立**: ContentItem 不再有 media_type 字段，媒体通过 MediaItem 一对多关联管理
- **三级抓取**: L1 HTTP → L2 Browserless → L3 browser-use，按需升级
- **数据目录**: `data/` 在项目根目录（非 backend/data/），backend 和 worker 共享同一挂载

## 技术栈

后端 Python 3.11+ (FastAPI + PostgreSQL + Procrastinate)，前端 Vue 3 + Vite + TailwindCSS，部署 Docker Compose。
RSSHub 生成非标准平台 feed，RSS 采集通过 feedparser 直连。

## 常用命令

```bash
# 开发
cd backend && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev

# 任务 Worker (两个进程，队列隔离)
cd backend && procrastinate --app=app.tasks.procrastinate_app.proc_app worker --concurrency=4 --queues=pipeline
cd backend && procrastinate --app=app.tasks.procrastinate_app.proc_app worker --concurrency=2 --queues=scheduled

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

- PostgreSQL: 单一 PG 实例，应用数据 + Procrastinate 任务队列共用 `allinone` database
- Procrastinate (非 Celery/Huey): PG-backed 任务队列，同一数据库管所有状态，无额外依赖
- Worker 双进程队列隔离: `pipeline` 队列 (concurrency=4) 跑流水线步骤，`scheduled` 队列 (concurrency=2) 跑定时采集/报告/清理，互不阻塞
- 定时任务由 Procrastinate worker 的 periodic 功能驱动，FastAPI 进程为纯 API 服务器
- 前后端同容器: Vite 构建产物由 FastAPI 静态服务

## 文档导航

- `docs/product_spec.md` — 产品方案 PRD
- `docs/system_design.md` — 系统架构与 API 规范
- `docs/business_glossary.md` — 业务术语与枚举定义
- `backend/CLAUDE.md` — 后端开发规范
- `backend/app/services/CLAUDE.md` — Pipeline/Collector 开发规范
- `frontend/CLAUDE.md` — 前端开发规范
