# Allin-One

个人信息聚合与智能分析平台。从 RSS/YouTube/网页等渠道自动采集内容，通过外部同步脚本接入 Bilibili/微信读书/Apple Books 等个人数据，经 LLM 分析后结构化呈现。

## 核心架构约束

系统有**两条主线**，性质不同、各有一等表达。2026-09 审计前资料库借住在信息流的抽象里，是当时多数混乱的根源（见 `docs/audit_2026-09_architecture.md`）。

| | 信息流 (stream) | 资料库 (library) |
|---|---|---|
| 内容 | RSS / 播客 / 网页抓取等时效性内容 | 影视、电子书、书签、笔记、上传文件、同步来的视频 |
| 进入方式 | **采集**（Collector，增量追加，可调度） | **同步**（内置 Syncer 全量对账 / 外部推送）或手工添加 |
| 后续处理 | 可选流水线（模板显式定义步骤） | 不进流水线，直接 READY；元数据补全各领域自理 |
| 清理 | 按保留期自动清理，收藏 / 有笔记 / 媒体已收藏的受保护 | **永不自动清理** |

- **内容的领域身份只看 `content_items.kind`**（ContentKind，写入时确定）。不要从 `source_type`、`media_type`、`raw_data` 的键去反推。新增 ContentItem 写入路径必须显式设置 `kind`。
- **信息流口径统一带 `FEED_SCOPE`**：通用内容列表、未读数、仪表盘、日报、MCP `list_content` 都排除有专属页面的资料库领域（目前是影视）。新增这类统计时别忘了它。
- **关于「源类型」的知识只在 `backend/app/models/source_types.py` 定义一次**：执行器（collector / syncer / push / none）、默认 kind、能否调度、是否需凭证、所属领域、自动同步间隔、是否已实现。新增源类型 = 在注册表加一条 + 写执行器；禁止在别处自维护类型名单或按 `sync.` 前缀判断。`COLLECTOR_MAP` / `SYNC_FETCHERS` 在导入时与注册表对账。
- **「能不能采集」由注册表在入口处强制**：调度器、采集任务、采集端点对非采集型数据源一律拒绝（400），不写采集记录、不动调度状态。同步型由同步面板 / 自动同步驱动，运行记录在 `sync_task_progress`（内置同步、外部推送都写）；采集型的运行记录在 `collection_records`，它同时是调度算法的输入。
- **可清理范围与保护条件只在 `services/content_retention.py` 定义**；用户数据类数据源下有内容时拒绝非级联删除（`SourceDeleteBlocked`）。
- **数据源与流水线解耦**: 数据源只管「从哪来」，流水线只管「怎么处理」，通过 `source.pipeline_template_id` FK 绑定；流水线步骤全部来自模板，Orchestrator 不自动注入，无模板绑定时内容直接 READY。
- **媒体项独立**: ContentItem 没有 media_type 字段，媒体通过 MediaItem 一对多关联。MediaType 描述一个媒体文件是什么；ContentKind 描述一条内容属于哪个领域（带视频的 RSS 文章仍是 `article`）。
- **全文抓取分级**: L1 HTTP → L2 Crawl4AI → L3 Browserless，按需升级。
- **金融数据不走 ContentItem**: AkShare 采集器写 `finance_data_points` 列式表、不产出内容。领域实体需要列式查询时，这是落地先例。
- **数据目录**: `data/` 在项目根目录（非 backend/data/），backend 和 worker 共享同一挂载
- **迁移先于切换**: `deploy-home-server.sh` 用新镜像跑迁移成功后才重建容器，所以迁移必须对旧代码向后兼容（加列 / 加表 / 加索引）；破坏性变更拆两次发布。

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

# 部署（本地开发容器）
docker compose up -d --build

# 部署到家庭服务器生产环境（在服务器本机执行：rsync → /opt/allin-one → 构建 → up -d → 迁移 → 健康检查）
./deploy-home-server.sh          # 全流程；镜像源拉不动时自动切换候选源
./deploy-home-server.sh status   # 容器状态
```

生产目录 `/opt/allin-one` 是仓库的 rsync 镜像，不是 git checkout；其中 `docker-compose.home-server.yml`、`.env`、`.restic-password`、`.backup.env` 是机器本地文件，不在仓库、不会被同步覆盖。**发版一律跑 `deploy-home-server.sh`，不要手工 rsync / docker build**。备份脚本 `scripts/backup-home-server.sh`（pg_dump + data/ → restic，见 `docs/system_design.md` §9.3）**手动运行**；systemd timer 已装但按用户决定停用。

## 代码规范

- Python: PEP 8, type hints, async/await 优先
- Vue: `<script setup>` Composition API
- 命名: snake_case (Python), camelCase (JS), kebab-case (文件名)
- Git: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:` 前缀
- **时间戳**: 全项目使用 `from app.core.time import utcnow`，禁止 `datetime.now(timezone.utc)`（详见 `backend/CLAUDE.md` 时间戳陷阱章节）
- **文档同步**: 完成涉及架构、API、数据模型、枚举、配置、部署方式等变更后，须主动评估并更新 `docs/` 和 `CLAUDE.md` 系列文档。评估标准见 `.claude/agents/doc-maintainer.md` 中的变更类型→文档映射矩阵。有把握的直接更新，不确定的才问用户。文档变更随功能代码同 commit，保持原子性；纯文档维护（定期对齐、批量校正）才用独立 `docs:` commit。

## 项目组织规范

### 脚本与临时文件管理

项目使用标准化目录结构管理脚本和临时文件：

```
allin-one/
├── scripts/          # 脚本目录（提交到 git）
│   ├── init/         # 初始化脚本（数据库设置等）
│   ├── migration/    # 数据迁移脚本（保留历史记录）
│   ├── verify/       # 验证脚本（按功能分子目录，如 verify/timezone/）
│   ├── utils/        # 可复用工具脚本
│   └── README.md     # 脚本目录说明文档
└── .temp/            # 纯临时文件（.gitignore 忽略，不提交）
```

**规则**：
- **验证脚本**: 放在 `scripts/verify/<功能名>/`，有长期价值的提交到 git，一次性的可选择性保留
- **临时文档**: 放在 `.temp/`，内容整理后归档到正式文档或 commit message，不提交到 git
- **工具脚本**: 可复用的放在 `scripts/utils/`，提交到 git
- **迁移脚本**: 放在 `scripts/migration/`，保留历史记录
- **初始化脚本**: 放在 `scripts/init/`，如数据库初始化 SQL

**示例**：
```bash
# 创建验证脚本
mkdir -p scripts/verify/feature-name
vim scripts/verify/feature-name/verify_feature.py

# 临时文档（验证后删除或归档）
echo "临时笔记" > .temp/notes.md

# 工具脚本
vim scripts/utils/cleanup_data.py
```

详细说明见 `scripts/README.md`。

## 关键决策

- PostgreSQL: 单一 PG 实例，应用数据 + Procrastinate 任务队列共用 `allinone` database
- Procrastinate (非 Celery/Huey): PG-backed 任务队列，同一数据库管所有状态，无额外依赖
- Worker 双进程队列隔离: `pipeline` 队列 (concurrency=4) 跑流水线步骤，`scheduled` 队列 (concurrency=2) 跑定时采集/报告/清理，互不阻塞
- 定时任务由 Procrastinate worker 的 periodic 功能驱动，FastAPI 进程为纯 API 服务器
- 前后端同容器: Vite 构建产物由 FastAPI 静态服务
- 凭证加密: `platform_credentials.credential_data` 使用 Fernet 对称加密 (`CREDENTIAL_ENCRYPTION_KEY` 环境变量)，未配置时透传明文，兼容历史数据
- DB 连接池: `DB_POOL_SIZE`（默认 10）/ `DB_MAX_OVERFLOW`（默认 5）环境变量控制，各容器独立配置
- LLM API Key 加密存储: `system_settings` 中 `api_key/token/password/secret` 关键词的键值与 `credential_data` 同套 Fernet 加密；`GET /api/settings` 返回解密后掩码（显示末 4 位原始字符）
- 源是否在采集 = `is_active AND schedule_enabled` **两个字段的与**（`scheduled_tasks.py` 选源条件，对应索引 `ix_source_next_collection`）。两者语义不同：`is_active` 是源的启停，前端源列表的开关改的是它；`schedule_enabled` 是定时采集开关，只有源类型注册表里 `schedulable` 的类型才可能为 true（建源 / 改源 / 导入时强制，调度器选源时再校验一次）。**排查「某源为何不采集/为何还在采集」必须同时查两个**，只看其一会误判。重新启用时前端会顺带把可调度数据源（接口返回的 `schedulable`）的 `schedule_enabled` 恢复为 true（见 SourcesView 的 restoreSchedule）
- 内容过滤器（无表无字段，三层分离）: **定义层** `system_settings` 的 `content.filters`（`{version, filters[]}`，每个过滤器 = `{id,name,emoji,pinned,order,conditions}`，conditions 覆盖 source_ids / media_type / status / unread / favorited / date_range / tag / q 全部维度）；**状态层** `stores/contentFilter.js` 是数据消费状态的唯一所有者，持有「定义 + 当前激活 + 临时覆盖(overrides)」，其 `params` computed 是列表请求参数的唯一来源；**消费端** FeedView 只渲染 pinned 过滤器的快捷方式并读 store，不自行拼装筛选参数，**配置端** 设置 → 内容过滤器 负责增删改。两端只经 store 与 settings 通信。
  - 筛选条（chip 区）只渲染 `overrides`，绝不渲染过滤器自身的条件——否则选中一个含 55 个来源的过滤器会把它们全铺成标签，这是历史上返工两次的形态。过滤器自身条件由快捷方式高亮表达。
  - 分类是消费视角不是源的属性，**不要给 `source_configs` 加 purpose 之类的字段**；同一个源在不同过滤器里可归不同组。
  - 外部消费方（the-one 的 `scripts/intel-query.py`）读同一个 key，**按名字正列取「情报」过滤器的 source_ids**（2026-09-10 起；早先的「全部源 − 浏览类」排除法已废弃——过滤器允许重叠，排除法会把同时在浏览里的源踢出研判池），只取 source_ids、忽略过滤器的 unread / date_range 等消费条件；未被覆盖的新源在 stderr 提示；`--all-sources` 为逃生阀；旧 `feed.source_groups` 仍可回退
- MCP 金融数据源: 蚂蚁 financial-data API 为主源（`FINANCIAL_DATA_*` 环境变量，key 走基础设施密钥模式，不经 system_settings+Fernet），akshare/雪球为降级路径；`FINANCIAL_DATA_ENABLED=false` 或留空 API key 即一键全量回退，详见 `docs/system_design.md` §10.6

## 文档导航

- `docs/10-立项.md` `20-架构.md` `30-模型.md` `40-流程.md` `50-用例.md` — **现状全景**：只写系统今天是什么样（定位与场景、领域与分层、现有表与存储、链路与操作、用法与验证），不写判断逻辑；每章头部有核实日期，改了架构 / 模型 / 流程后同步更新
- `docs/product_spec.md` — 产品方案 PRD
- `docs/system_design.md` — 系统架构与 API 规范
- `docs/business_glossary.md` — 业务术语与枚举定义
- `docs/audit_2026-09_architecture.md` — 2026-09 架构审计：现状、根因、目标模型、分阶段对齐记录
- `docs/design_data_model.md` — 个人内容系统的数据模型与存储模型（五概念、两真相单元、六张业务表、kinds 注册表）。决策与待定项在 the-one `project/allin-one/`
- `backend/CLAUDE.md` — 后端开发规范
- `backend/app/services/CLAUDE.md` — Pipeline/Collector 开发规范
- `frontend/CLAUDE.md` — 前端开发规范
