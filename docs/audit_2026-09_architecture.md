# 架构与数据模型审计（2026-09-20）

> 范围：数据模型、入口层抽象、领域子系统、接口面与文档。方法：四路只读审计（代码 + 生产库 SELECT + 文档），关键结论经二次核实。
> 基线：代码 `81ea62f`，库版本 `0024_watch_status_backlog`，当前库自 2026-08-30 重建。
> 状态：方案已于 2026-09-20 确认并开始执行。决策：流水线与电子书域暂不动；RSS 照常全局清理、收藏受保护；影片不拆列式表；术语统一为「数据源」；外部推送通路保留。
>
> 进度：**P0 ✅**（清理只作用于网络采集类数据源 + 媒体收藏纳入保护；用户数据类数据源拒绝非级联删除）· **P1 ✅**（`content_items.kind` + 迁移 0025 回填；影片身份改按 kind 判定并加部分唯一索引；内容列表 / 未读 / 全部已读 / delete-all / 仪表盘 / 日报周报 / MCP 统一带 `FEED_SCOPE`；部署脚本改为先迁移后切换容器）

---

## 1. 一句话诊断

系统最初按「**信息流**：采集 → 流水线 → LLM 分析」设计，后来长出了「**资料库**：影视、电子书、书签」这条完全不同性质的主线。资料库没有获得自己的一等抽象，而是借住在信息流的表和字段里。现在的大部分混乱——判定方式多套、用户状态散布、采集按钮无效、清理任务危及影视库——都是这一个错位的不同症状。

与此同时，原主线的后半段（流水线 + LLM 分析）在当前库里**基本没有运行**，文档和模型注释却仍以它为主叙事。

## 2. 现状总图

```
             ┌─ 采集 Collector ──────┐  collection_records   调度/退避/健康度 ✅
  数据进来 ──┼─ 内置同步 Fetcher ────┤  sync_task_progress   仅进度
             ├─ 外部推送 API ×3 ─────┤  无记录
             └─ 旁路（笔记/上传/视频下载/手工影片/MCP）  无记录
                        │
                        ▼
     source_configs（69）──1:N──> content_items（9990）
       三重角色：                     万能表：
       · 可调度的采集任务              · 信息流条目 9272（rss 9104 + podcast 168）
       · 同步插件的凭证绑定点          · 影片 718（领域字段全在 raw_data）
       · 纯数据归属容器                · 书 / 书签 / 笔记（当前 0 行）
                        │
                        ▼
     领域附表：watch_records/watch_logs ✅活跃   book_* ×3 空   finance_data_points 空
     用户状态：收藏 ×3 处  进度 ×4 套  笔记 ×4 处  `status` 同名三义
```

18 条内容入口路径中，**9 条写入不留任何运行痕迹**。

## 3. 五个根因

### A. `content_items` 没有「领域」一等字段

判断一条内容是文章 / 视频 / 书 / 影片，系统里有 **6 种并存的答法**：`media_items.media_type`、`source_type` 精确集合、`source_type` 前缀（且有三份互相矛盾的名单）、`raw_data` 里的键、各专用路由自带的 filter、`SYNC_PLUGINS.category`。文章靠排除法判定；影片在通用列表里的 `content_type` 是 `"text"`。

后果（均已验证）：
- 通用 `/api/content`、未读数、MCP `list_content` 对资料库数据零隔离。未读总数 3897 里有 **715 条是影片**；已有 3 部影片被当文章点开，写进了「阅读活跃度」。
- 仪表盘的今日新增、采集趋势、状态分布，日报周报的查询口径，全部把批量入库的影片算作「采集到的内容」。
- 按 `published_at` 排序时，1950 年代的电影和当天新闻在同一条时间轴上（影片的上映日借用了这个字段）。

### B. `source_configs` 一张表承担三个角色

可调度的采集任务、同步插件的凭证绑定点、纯归属容器（「手工影片」）共用同一张表、同一套字段、同一个页面、同一个「采集」按钮。

后果（均已验证）：
- 「源能不能采集」**没有单点判定**。采集任务对任意类型都会执行：未知类型仍写一条 `completed / 0 条` 的记录、清零失败数、更新 `last_collected_at`、计算下次采集时间。生产库里 `sync.bilibili` 有 **261 条**这样的假成功记录，`sync.emby` 有 3 条（2026-09-20 01:29，即「页面触发没用」那次）。假记录进入了成功率统计和调度活跃度计算。
- `last_collected_at` 一个字段两种语义（采集尝试完成 / 同步数据落库）、六个写入者。`/api/sync/status` 已打补丁绕开，但三个领域 status 端点仍在读它，外部脚本用它做增量起点。
- **删掉「Emby」或「手工影片」这条源，718 部影片会从影视库消失**：影片身份靠 JOIN 源类型判定，而删源默认行为是保留内容、`source_id` 置空。片子不丢但隐形，观看记录成无主数据；唯一约束对 NULL 不生效，同一部片还能重复入库。尚未发生。
- `source_type` 已不能表示影片出处：`user.film` 下有 13 部带 Emby 块。真正的出处记在 `raw_data.source` / `raw_data.sources[]`，同一概念三处表达。

### C. 入口层三套并行机制，没有统一的执行器和运行记录

| | 采集 | 内置同步 | 外部推送 / 旁路 |
|---|---|---|---|
| 运行记录 | collection_records | sync_task_progress | 无 |
| 调度 / 退避 / 健康度 | 有 | 无 | 无 |
| 崩溃恢复 | 部分 | **无**（进度行卡在 running 后该源永久 409） | — |

- 「源类型」的知识散在**后端 12 处以上、前端 3 处**。新增一种同步类型要改 8 个地方。「不采集的类型」有三份名单且互相矛盾（`file.upload`、`sync.*`、`user.film` 在三处的归类都不同）。
- 同步的 setup 端点有 **5 个**，其中 3 个逐行重复，且 ebook / video 的 setup 和推送端点都不校验领域——可以把视频数据写进电子书源。
- upsert 逻辑 4 份，结构同构，去重键三种。
- B 站、微信读书各有内置 Fetcher 和外部脚本两条通路并存，写同一个源。

### D. 用户状态没有统一归属，保护规则只认通用字段

收藏 3 处（content / media / `raw_data.emby`，单向传播、取消不对称，实测 35 个 media 收藏了但内容未收藏）；进度 4 套（秒 / 0–1 浮点 / Emby ticks / 观看日期）；笔记 4 处；标签 3 种；`status` 同名三义（处理态 / 下载态 / 观影态）。

**最严重的后果**：自动清理的保护条件只认 `content_items.is_favorited` 和 `user_note`，而影片的评分、感想在 `watch_logs` 里——详见 §4 🔴-1。

### E. 主叙事与实际使用脱节

- `analysis_result` 全库 9990 行皆空（却建了 GIN 索引）；`chat_history`、`user_note` 0 行；69 个源**没有一个绑定流水线模板**；`ContentStatus` 5 种只出现 2 种，且 `analyzed` 的实际含义已变成「有一条流水线跑完了」（29 条全是媒体下载）。
- 日报 20 次、周报 3 次**全部静默失败**（LLM Key 未配置，无重试无告警）。
- 根 `CLAUDE.md` 的六条「核心架构约束」只有三条仍成立。「抓取与处理分离」「三级抓取」已不成立（AkShare 采集器不产出内容；browser-use 不存在，实际是 HTTP → Crawl4AI → Browserless，且同一个 Browserless 在两个文件里分别叫 L2 和 L3）。同步、影视、电子书、金融四个子系统只把核心表当存储壳，约束对此只字未提。
- `design_scheduler_pipeline.md`（APScheduler / SQLite / Huey）与 `design_ebook_reader.md`（阅读器已移除，文中端点无一存在）整体过期，仍被 `system_design.md` 当权威引用。

## 4. 问题清单

### 🔴 数据安全与结构性

| # | 问题 | 证据 |
|---|---|---|
| 1 | **自动清理无视 `auto_cleanup_enabled`，影视库将于 2026-10-16 03:00 起被批量删除**，405 条观看记录、371 个评分、64 条感想级联消失。RSS 条目自 2026-09-29 起被删。 | `scheduled_tasks.py:345` 是 `db.query(SourceConfig).all()`；全仓无任何代码读取该开关；库无 `default_retention_days` → 回落 30 天；影片 `collected_at` 为 09-16/17，收藏 0、笔记 0；`watch_records → content_items` 为 CASCADE；任务每日 03:00 运行（`cleanup_content_last_run=2026-09-20`）。**已二次核实。** |
| 2 | 删库型源 → 影片隐形 + 可重复入库 | 根因 B |
| 3 | 采集任务对任意类型执行，产生假成功记录并污染调度与统计 | 根因 B |
| 4 | 资料库数据混入信息流、未读数、仪表盘、日报、MCP 口径 | 根因 A |
| 5 | `run_sync` 无崩溃恢复，进度行卡住后该源永久无法再同步 | `sync.py:218-223` 对 pending/running 一律 409；清理只删终态 |
| 6 | 错误以 HTTP 200 + `code` 字段返回，业务码取值不统一（类 HTTP 数字 / `1` / `-1` / 手拼 dict），前端 153 处各自判断；`APIResponse` 模型无人使用，全路由 `response_model` 为 0 | `schemas/base.py:19` |
| 7 | 视频 / 媒体 / 音频三模块整段复制：播放进度端点逐行相同；删除逻辑两份且行为不一致；音频目录约定两处相反 | `video.py:230` ↔ `media.py:294`；`video.py:253` ↔ `media.py:317` |

### 🟡 不一致

- **枚举**：`SourceType` 声明 22 种，库里用到 7 种；`douban_books` / `douban_movies` / `zhihu` / `github_stars` / `twitter` 纯空壳，且能通过 setup 接口建出无实现的源。所有枚举列都是裸 VARCHAR，无 CHECK 约束。
- **调度开关**：`schedule_enabled=False` 与 `schedule_mode='manual'` 语义重叠，7 条创建路径的默认组合各不相同；全量导入和 PUT 不按类别约束；周期性分析只看 mode 不看 enabled（`sync.bilibili` 确实被分析过）。
- **模型 vs 库**：死列 `content_items.language`（库有、模型无，Schema 仍声明 → 恒为 None）；模型声明的 2 个索引库里没有，迁移建的 12+ 个索引模型未声明（autogenerate 会产出假 diff）；`uq_annotation_external` 模型写全量唯一、库里是部分唯一。
- **`create_all` 与 alembic 并存**：每次启动都 `create_all`，迫使 0023 手写 `CREATE TABLE IF NOT EXISTS`；规范要求 autogenerate，但 0014 / 0022 / 0023 / 0024 都是手写 SQL。
- **死结构**：`book_bookmarks` 整表无写入方；`reading_progress` 的 cfi / section 三列无写入方；`_PLATFORM_MAP` 无引用；`services/ebook_parser.py` 无引用；前端 `VideoView.vue`、`annotations-view.vue` 无路由；`content-detail-panel.vue:149` 兜底地址 `/api/media/{id}/stream` 后端不存在。
- **同一资源多入口、语义不同**：收藏（REST 会触发媒体下载，MCP 直写库不触发）；删除一条内容有 5 个入口、级联范围各写各的；`delete_ebook` 不校验领域，传任意 ID 都删；「enrich」一词三义；提交内容 4 个入口都在路由里自己建行并拉流水线。
- **运维**：`procrastinate_jobs` 无清理（4.9 万行 + 事件 14.7 万行，合计 30MB ≈ content_items 的体量）；7 条历史遗留的 `doing` 采集作业；scheduled 队列并发 2，同时承担每分钟心跳、长同步、带 sleep 的重试、报告生成；流水线恢复逻辑写在采集循环里。
- **接口风格**：前缀单复数混用；列表入口四种写法（`""` / `/list` / `/downloads` / `/sources`）；排序参数 `sort_by/sort_order` vs `sort/order`；`page_size` 默认值 20 / 50 / 60 不一。
- **前端**：同步触发 + SSE 进度写了 2 遍、收藏切换 7 处、URL query 同步 13 个文件各自手写，无 composable；侧边栏是按功能添加顺序堆出来的。
- **术语**：界面全用「信息源」，文档和后端用「数据源」；采集 / 抓取 / 同步 / 拉取 / 导入 / 推送混用；`Collector` / `*Fetcher` / 文档里的 `BaseSyncService` 三套类名。
- **文档漂移**：`system_design.md` §2 的 `sync_task_progress`、`book_annotations`、`book_bookmarks` 与实际几乎是不同的表；ER 图缺 `watch_*`；SQL 方言仍是 SQLite 时代；cron 写的是本地时间而代码是 UTC；README 说 10 种数据源。

### 🟢 保持现状

- 表级模型与库完全一致，17 条外键逐条一致，JSON 列全部是 JSONB。
- 影视库的关系部分干净：718 部片 ↔ 718 条标记，无孤儿、无脏状态；Emby 事实与用户主张分层、手动标记不被同步覆盖，设计自洽。
- rss / podcast 的 `raw_data` 名副其实是原始 feed；标题相似去重确实在跑且不误伤影片。
- 金融已彻底搬出 `content_items`，列式表边界清晰——这是「领域实体该怎么落地」的现成先例。
- 成功响应信封与页码分页形状全路由一致；pipeline / scheduled 队列隔离；采集去重（唯一约束 + SAVEPOINT）各采集器一致。
- MCP 的 sources、films 两组工具复用了 service 层。

## 5. 目标模型（拟固化）

**核心主张：承认系统有两条主线，给每条主线一等的表达。**

| | 信息流（stream） | 资料库（library） |
|---|---|---|
| 性质 | 时效性、会过期、看过即弃 | 长期资产、永久保留、反复回看 |
| 进入方式 | 采集（增量追加） | 同步（全量对账）/ 手工添加 |
| 后续处理 | 可选流水线 | 元数据补全 |
| 用户动作 | 已读、收藏 | 状态、评分、观看 / 阅读记录 |
| 清理 | 按保留期 | **永不自动清理** |

1. **`content_items.kind`**（新列，NOT NULL，写入时确定）：`article / video / audio / book / film / bookmark / note / file`。由 kind 派生 `stream / library` 归类。一切列表、未读、统计、日报、MCP、清理的口径都按 kind 过滤。6 种判定方式收敛为 1 种。影片身份不再依赖 JOIN 源，删源不再致隐形。
2. **影片全局唯一性落到库**：对 `kind='film'` 的 `external_id` 建部分唯一索引，替代应用层 `_find_film` 的兜底。
   - 是否把影片字段从 `raw_data` 拆成列式表（仿 finance）？**建议暂不拆**：718 行规模无性能问题，当前的真问题是正确性（身份、唯一性、口径），kind + 唯一索引已能解决；拆表成本高且影视库模型两天内出了 4 个迁移、仍在变动。等它稳定后再议。
3. **源类型注册表单点化**：一张 `SOURCE_TYPES` 表定义每种类型的 `runner`（collector / syncer / push / none）、默认 `kind`、是否可调度、是否需凭证、所属领域。枚举、分类、`COLLECTOR_MAP`、`SYNC_FETCHERS`、`SYNC_PLUGINS`、三份「不采集」名单、前端 `PLUGIN_META` 全部由它派生。删除 5 个空壳枚举值。
4. **统一执行器与运行记录**：`SourceRunner` 协议两种实现（采集型 / 同步型），同一个触发入口、同一个调度器。`collection_records` 与 `sync_task_progress` 合并为 `source_runs`（保留进度字段）；`last_collected_at` 拆为语义明确的 `last_run_at` / `last_success_at`；外部推送也写运行记录。`runner=none` 的源在入口处拒绝，而不是写一条假成功。带来的直接收益：**Emby 同步可进调度，也可由下载完成钩子触发，下载 → 入库全自动**。
5. **库型源保护**：`library` 类内容所属的源禁止删除（或删除时必须显式级联），消除隐形数据。
6. **用户状态定规矩，不做大迁移**：
   - 收藏单一真源 = `content_items.is_favorited`；media 收藏改为双向同步或下线。
   - 清理保护 = 「是 library」∪「已收藏」∪「有笔记」∪「有 media 收藏」。
   - 各领域的进度、评分保留在各自附表，把单位和语义写进术语表；`status` 在接口层改名区分（`process_status` / `watch_status`）。
7. **接口约定**：错误统一走 HTTP 状态码 + 信封；列表入口、分页、排序参数定一种写法；合并 video / media / audio 的重复端点；同步 setup 5 个并 1 个。
8. **文档**：重写 `system_design.md` §2；归档两份过期设计文档；根 `CLAUDE.md` 的架构约束按「两条主线」改写为现状；术语表定稿。

## 6. 分阶段方案

| 阶段 | 内容 | 规模 | 风险 |
|---|---|---|---|
| **P0 数据安全** | ① 清理任务只处理 `auto_cleanup_enabled=True` 的源，且跳过库型源；② 库型源禁止非级联删除 | 两处小改 | 极低。**不依赖后续任何阶段，建议立即做** |
| **P1 领域一等化** | `kind` 列 + 回填迁移 + 影片部分唯一索引；feed / 未读 / 仪表盘 / 日报 / MCP / 清理全部按 kind 过滤；影片判定改用 kind | 1 个迁移 + 约 10 处查询 | 低。回填规则明确，可逐口径验证 |
| **P2 入口统一** | 源类型注册表单点化；`SourceRunner` 协议；采集入口类型校验；`source_runs` 合表；setup 并 1；`run_sync` 崩溃恢复；Emby 同步自动化（钩子 + 调度） | 最大的一块 | 中。涉及表合并与 SSE 契约变更，需前后端同步 |
| **P3 收敛清理** | 合并重复端点；删死代码、死列、空壳枚举；前端 composable（同步进度、收藏、query 同步）；错误码统一；`procrastinate_jobs` 清理；去掉 `create_all` | 面广但每项独立 | 低，可零散推进 |
| **P4 文档固化** | 按 §5-8 重写；加一个「模型 vs 库 vs 文档」漂移检查脚本，防止再次跑偏 | 纯文档 + 1 个脚本 | 无 |

## 7. 需要拍板的决策

1. **LLM 流水线主线**：保留为可选能力（文档降级为「可选」），还是下线？日报 / 周报任务现在每天静默失败——配 LLM Key，还是停掉任务？
2. **电子书域**：当前 0 数据、阅读器已移除、两张表无读写接口。保留并接着做，还是冻结（删死表死代码，保留同步入口）？
3. **外部推送通路**：Fountain 客户端（最后提交 2026-03-06）和 `scripts/*-sync.py` 还在用吗？决定三套推送路由和书签 / Kindle 类型的去留。
4. **RSS 自动清理**：你从没开过任何源的自动清理，但按现状 09-29 起会删 30 天前的文章。要的是「全局 30 天」还是「只清理显式开启的源」？（P0 按后者修，即恢复开关的字面含义。）
5. **影片是否拆列式表**：建议暂不拆（§5-2）。
6. **术语**：「信息源」还是「数据源」，统一成哪个？

## 8. 未查清

- 2026-08-30 之前是否存在另一套历史库、是否用过 akshare / 流水线 / 电子书。
- 电子书域的 `raw_data` 事实结构（库里 0 本书，只能从代码推断）。
- `system_settings` 里 `content.filters`、`feed.source_groups` 内嵌的源 ID 是否已有悬空。
- `sync.bilibili` 为何 `schedule_enabled=true`（setup 写的是 False；推测为 SQLite → PG 迁移带入）。
- 外部脚本如何用 status 的 `last_sync_at` 做增量，被污染后的实际影响。
- 第二次下载同一 URL 是否返回 500（`video.py:66` 未捕获 IntegrityError，属推断）。
- 列级 nullable / server_default 的全量漂移（库里只有 3 列有 server_default，其余默认值全靠 ORM，裸 SQL 写入拿不到）。
