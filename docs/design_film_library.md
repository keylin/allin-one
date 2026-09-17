# 技术方案: 影视资料库 (Film Library)

> 版本: v1.0 | 日期: 2026-09-16 | 状态: 第一期已实现（模型/迁移 0021、EmbyFetcher、/api/films、FilmsView、MCP 三工具）

---

## 1. 背景与目标

Emby 是家庭媒体服务器，只知道"盘上有什么、播过什么"。用户的观影记录远大于 Emby 库存（大量影片在院线/其他渠道看过），推荐场景需要一个**以人为中心的影视记录库**，而不是 Emby 的镜像。

目标：

1. Emby 的库存和观看事实同步进 allin-one，作为行动证据。
2. 用户在页面上对每部影片做标记（状态 / 评分 / 评论 / 标签），Emby 没有的片也能维护。
3. Claude 等 agent 通过 MCP 读库做推荐，推荐结果里用户已看过的可一键批量落库。

非目标：allin-one 不内置推荐引擎；不做单集级追剧管理；不镜像 Emby 删除。

### 核心原则

- **复用现有体系**：影片是 ContentItem 的一种，走 Fountain 同步框架（`BaseSyncFetcher` + `SYNC_PLUGINS` + 凭证关联 + SSE 进度），不引入新的顶层实体。
- **事实与主张分层**：Emby 的 played/进度 是行动证据，用户标记是主张，两者分开存、并排展示、不合并。
- **只读 Emby**：只调 GET 接口。**绝不调用 `DELETE /Items/{id}`**（会连同磁盘文件一起删除，the-one `project/家庭网络/08-注意事项.md` §6 事故）。
- **手动触发**：同步只在页面点击时执行，不做定时、不做 webhook。后续有需要再加。

---

## 2. 数据模型

### 2.1 SourceType 扩展

```python
class SourceType(str, Enum):
    SYNC_EMBY = "sync.emby"          # 新增：Emby 媒体库同步（SourceCategory.USER）
    USER_FILM = "user.film"          # 新增：用户手工添加的影片（SourceCategory.USER）
    # SYNC_DOUBAN_MOVIES 已预留，Phase 2 实现
```

`sync.emby` 注册进 `SYNC_PLUGINS`（`app/api/routes/sync.py`），mode=internal，credential_type=`api_key`，页面 SyncView 自动出现"运行"按钮，即手动触发入口。

### 2.2 ContentItem 复用

```
ContentItem (影片 / 剧集)
  ├── title         = 中文标题（Emby Name；手工添加取 TMDb zh-CN title）
  ├── external_id   = 身份键，见 2.3
  ├── url           = https://www.themoviedb.org/movie/603  （无 TMDb ID 时为 emby://item/<Id>）
  ├── author        = 导演（多位用 " / " 连接，仅冗余展示）
  ├── published_at  = 上映日期（仅知年份时取 YYYY-01-01）
  ├── source_id     → sync.emby 或 user.film 的 SourceConfig
  ├── is_favorited  = 沿用（user_note 不再用于影视：长评已并入 watch_logs.note，0023）
  ├── status        = READY（不走流水线）
  └── raw_data      = 见 2.4
```

### 2.3 身份键：TMDb ID

```
external_id 格式：
  tmdb:movie:<id>     电影
  tmdb:tv:<id>        剧集
  emby:<ItemId>       兜底，Emby 未刮到 ProviderIds.Tmdb 时使用
```

理由：Emby 刮削后 `ProviderIds` 已含 Tmdb/Imdb/Tvdb；豆瓣无公开 API，只能作二期导入映射。推荐闭环依赖它——agent 推荐时带 TMDb ID，用户确认"看过"后 `mark_films` 一次落库。

Upsert 规则：先按 `external_id` 精确匹配；Emby 条目从 `emby:<Id>` 升级为 `tmdb:*` 时（后来手动识别补上了 ID）用 `raw_data.emby.item_id` 二次匹配并改写 external_id。

### 2.4 raw_data 结构

```jsonc
{
  "kind": "movie" | "series",
  "year": 2017,
  "original_title": "Blade Runner 2049",
  "overview": "...",
  "genres": ["科幻", "剧情"],
  "directors": ["Denis Villeneuve"],
  "cast": ["Ryan Gosling", "Harrison Ford"],      // 最多 10 人
  "countries": ["US"],
  "runtime_min": 164,
  "community_rating": 8.0,                          // Emby CommunityRating（TMDb 分）
  "official_rating": "R",
  "provider_ids": {"tmdb": "335984", "imdb": "tt1856101", "tvdb": null},
  "poster": {"emby_item_id": "6188", "tmdb_path": "/xxx.jpg"},
  "emby": {                                         // 仅 Emby 来源有；每次同步整体覆盖
    "item_ids": ["6188", "9229"],                   // 同一影片多副本
    "in_library": true,
    "date_created": "2026-04-05T...",
    "played": false,
    "play_count": 6,
    "playback_position_ticks": 0,
    "progress": 0.22,                               // position / runtime
    "last_played_at": "2026-09-14T04:42:37Z",
    "is_favorite": false,
    "episodes_total": 58,                           // series 专用
    "episodes_played": 1,
    "last_synced_at": "..."
  },
  "source": "emby" | "manual" | "douban"
}
```

### 2.5 新增表: watch_records（片级标记）+ watch_logs（观看记录）

```sql
CREATE TABLE watch_records (                        -- 一部片一行
    id           TEXT PRIMARY KEY,
    content_id   TEXT NOT NULL UNIQUE REFERENCES content_items(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'unmarked',  -- unmarked / want / watching / watched / dropped
    tags         TEXT[] DEFAULT '{}',
    status_source TEXT DEFAULT 'manual',            -- manual / emby_autofill / douban_import
    -- 以下为「最近一次观看」的缓存（sync_record_from_logs 维护），供列表排序/筛选/卡片
    my_rating    SMALLINT,                          -- 最近一次打过分的观看的评分
    watched_at   DATE,                              -- 最近一次观看的日期，NULL = 时间不详
    watched_precision TEXT,                         -- day / month / year / release
    created_at / updated_at
);
CREATE TABLE watch_logs (                           -- 一次观看一行；同一部片可多条（不同阶段重看）
    id           TEXT PRIMARY KEY,
    record_id    TEXT NOT NULL REFERENCES watch_records(id) ON DELETE CASCADE,
    watched_at   DATE,                              -- NULL = 时间不详
    watched_precision TEXT,                         -- day / month / year / release
    my_rating    SMALLINT,                          -- 这一次的评分
    note         TEXT,                              -- 这一次的感想，长短不限（不再分短评/长评）
    created_at / updated_at
);
```

**观看记录（0023，2026-09-17）**：短评/长评的区分取消，改为"一部片多条观看记录"。片级只有状态和标签；评分、日期、感想都属于某一次观看。
- 「最近一次」的判定：有效日期 = 具体日期本身 / 记到月或年取区间末日（封顶今天）/ 没写日期取录入日；同日按录入先后。刚记的一次没写日期也算最新。
- 片级缓存：`watched_at` 取最近一次；`my_rating` 取最近一次**打过分**的观看（重看没打分则沿用上次）。
- 快捷路径（卡片打分/感想、`PUT /record` 的 my_rating/watched_at/comment、MCP mark_films）都落到最近一次观看，没有则新建；`rewatch=true` 先新建一条再写。
- 看过必有至少一条观看记录（点看过 / 打分 → 自动建一条空记录，时间不详，因为多半是补记以前看的）。主动「再记一次」（详情页按钮、`POST /logs`、`rewatch=true`）默认日期 = 当天（精度 day），可改。删观看记录不改状态。
- 迁移 0023：每条看过/带评分/带短评/带长评的记录 → 一条观看记录，短评 + 长评合并为 note；`watch_records.comment` 删除，影视条目的 `user_note` 清空。

**覆盖规则（核心）**：
- 同步**永不**修改 `watch_records` 中 `status_source = manual` 的行。
- 同步仅在 `status = unmarked` 且 Emby `played = true` 时写入 `status = watched, status_source = emby_autofill`；已是 `emby_autofill` 且缺 `watched_at` 的行允许补日期。
- Emby 的 0% 播放记录、playCount 不触发任何自动填充（整理库时的验证播放会污染）。
- 用户任何一次手动修改都把 `status_source` 置回 `manual`。
- 看过日期带精度（迁移 0022，`watched_precision`）：手填 `YYYY` / `YYYY-MM` / `YYYY-MM-DD` → year / month / day；详情页主动选「不记得（按上映）」→ 传 `release`，按上映时间近似并标 precision=release，展示「≈2019（上映）」。**自动规则从不填日期**（点看过、打分自动看过都留空 = 时间不详，以后再补；2026-09-17 定）。Emby 自动填充用真实播放日期（day）。**评分蕴含看过**：给任何非看过状态（含弃了）的片打分即记为看过，仅在主动打分时触发。
- 卡片坑位（桌面/手机同一套，手机两列，无长按面板）：星评一行 + 第二行按状态切换——未标记/想看/在看显示 想看/看过/弃了 按钮；看过/弃了显示最近一次感想入口（原地编辑、回车保存）、看过多次时显示 ×N，和「⋯」改状态菜单。详情页「观看记录」逐条编辑日期/评分/感想，「再记一次」新增。

---

## 2.6 外部依赖原则（2026-09-17 定）

**浏览路径零外部调用。** 列表 / 详情 / 统计接口只读本地数据库与本地文件；TMDb、豆瓣、Emby 只在用户主动触发的写入动作上出网一次（搜索候选、添加、补全、重新识别、同步、豆瓣解析）。静态资源在元数据落库那一刻一起存好：
- 海报：`upsert_films` 写入 poster 时即拉取落盘到 `DATA_DIR/posters/<content_id>-<来源哈希>.jpg`（`cache_poster`）；`GET /films/{id}/poster?v=<来源哈希>` 命中直接回文件、未命中异步拉一次后落盘，响应 `Cache-Control: immutable` 30 天。来源变化（重新识别 / Emby 换图）→ 哈希变 → URL 变。
- 曾经的教训：海报代理每次现拉 TMDb（约 1s/张、同步占线程池），一页 60 张拖死后端，移动端点开影视库卡死。

---

## 3. Emby 同步

### 3.1 凭证

`PlatformCredential`：`platform = "emby"`，`credential_type = "api_key"`，`credential_data` = 服务器级 API key（加密存储），`extra_info = {"base_url": "http://192.168.1.103:8096", "user_name": "emby", "user_id": "<emby 用户 Guid>"}`。base_url 必须是容器可达的 LAN 地址（allin-one 走 bridge 网络，127.0.0.1 是容器自身）。通过现有 `POST /api/sync/link-credential` 关联到 `sync.emby` 源。

### 3.2 拉取

`EmbyFetcher(BaseSyncFetcher)`，`app/services/sync/emby.py`：

```
GET {base}/emby/Users/{user_id}/Items
    ?IncludeItemTypes=Movie,Series&Recursive=true
    &Fields=ProviderIds,Genres,People,Overview,ProductionYear,PremiereDate,RunTimeTicks,
            CommunityRating,OfficialRating,ProductionLocations,DateCreated,OriginalTitle,UserData
    &StartIndex=0&Limit=200          （分页）
GET {base}/emby/Users/{user_id}/Items/{id}                                    （逐条补全完整 UserData）
GET {base}/emby/Shows/{series_id}/Episodes?UserId={user_id}&Fields=UserData   （series 计已看集数）
```

- `validate_credential`：`GET /emby/System/Info` 200 即有效。
- 本期一律**全量**拉取（库存量级 ~50 条，秒级完成）。`MinDateLastSaved` / `MinDateLastSavedForUser` 增量参数留作后续优化，未实测。
- 多副本合并：同一 TMDb ID 多个 Emby 条目（如两块盘上的两个 Blade Runner 2049）合并为一条，`play_count` 取和、`last_played_at` 取最大、`progress` 取最大。
- 本次拉取中未出现、但 `raw_data.emby.in_library = true` 的既有记录 → 置 `in_library = false`，记录保留。
- 进度通过 `on_progress` 回调走现有 SSE。

### 3.3 手动触发

SyncView 现有"运行"按钮 → `POST /api/sync/run/sync.emby`。不注册 periodic 任务。

---

## 4. 手工添加与 TMDb

- 系统设置新增 `tmdb_api_key`（`system_settings` 表，与 llm_* 同机制）。
- `GET /api/films/search?q=&year=` 代理 TMDb `/search/multi`（language=zh-CN），返回候选列表。
- `POST /api/films` 传 `{tmdb_id, kind}` 或 `{title, year}`：有 TMDb key 则拉详情落 raw_data；无 key 时只建标题+年份的骨架记录，`external_id = manual:<uuid5(title+year)>`，后续可补 ID。
- Emby 后来出现同一 TMDb ID 的条目时，upsert 命中已有手工记录，补 `raw_data.emby`，`source_id` 保持不变、`raw_data.source` 加 `emby`。
- **元数据唯一来源是 TMDb**（2026-09-16 定案）：曾用 Emby 的 `RemoteSearch` 接口做无 key 时的替代，实测它只给片名/年份/ProviderIds/海报/英文简介，拿不到导演、主演、类型、中文简介（`MetadataLanguage` 无效），且有误匹配（"首"→首尔之春、"碁盘斩"→格斗片 Bushido），已整体移除。没有 TMDb key 时手工添加只建骨架、补全按钮禁用并提示配 key。`POST /api/films/enrich-missing?limit=` 批量、`POST /api/films/{id}/enrich` 单条，搜不到的记 `raw_data.enrich_failed`。剧集导演 `created_by` 为空时退到 `aggregate_credits` 的 Director。`enrichment_state()`：full（sources 含 emby/tmdb）/ partial / skeleton / failed。
- **豆瓣直达链接**（2026-09-16）：豆瓣无公开 API，用其联想接口 `movie.douban.com/j/subject_suggest?q=` 按片名（其次原名）解析条目 id，年份差 >1 不认，存 `provider_ids.douban`。**详情页手动触发、一次生效永久保存**（`POST /api/films/{id}/douban`，body 可粘豆瓣链接/ID 手填；`DELETE` 清除）；不做批量，因为该接口连续请求几条后即被限流（对已知影片也返回空）。`douban_probe()` 先查一部必定存在的片判断限流，限流/无匹配都不持久标记，可重试。解析不到时详情页链接退回按 IMDb id 或片名+年份的豆瓣搜索页。
- **纠错入口**（2026-09-17）：详情页「编辑」改片名/年份/类型（`PUT /meta`，无 ID 的骨架改完自动重搜）；「重新识别」搜 TMDb 候选点选关联（`POST /relink`，撞到库里已有条目则拒绝）。豆瓣合成一个动作：点「豆瓣」有直达直接开，没有则解析后开，失败退回搜索页并出现粘贴框。
- **Emby 的职责收敛为一件事**：库存与观看事实（sync.emby + 库内条目海报）。它不可用时搜索/添加/补全不受影响。
- 页面：卡片底部常显快捷操作（想看/看过/弃、评分条、删除二次确认），移动端长按卡片弹操作面板；列表无限滚动（sentinel + IntersectionObserver）；详情抽屉移动端空白处双击关闭。

---

## 5. API

```
GET    /api/films                     列表；query: status, kind, genre, year_from, year_to, in_emby, min_rating, q, sort, page
GET    /api/films/{id}                详情（ContentItem + watch_record）
POST   /api/films                     手工添加
PUT    /api/films/{id}/record         更新标记 {status, tags, my_rating, watched_at, comment, rewatch}（后三项落到最近一次观看）
POST   /api/films/{id}/logs           再记一次观看 {watched_at?, my_rating?, note?}
PUT    /api/films/{id}/logs/{log_id}  改一次观看
DELETE /api/films/{id}/logs/{log_id}  删一次观看
POST   /api/films/records/batch       批量标记 [{tmdb_id|content_id|title+year, status, my_rating?, watched_at?, comment?}]
GET    /api/films/search?q=           TMDb 搜索
GET    /api/films/{id}/poster         海报代理（Emby Primary 图 → 无则 TMDb → 无则 404），不向前端暴露 Emby key
GET    /api/films/stats               按状态/类型/年代计数（页面头部）
```

---

## 6. 前端

路由 `/films` → `FilmsView.vue`（列表）+ `FilmDetailDrawer.vue`（抽屉）。

- 列表：海报网格，卡片显示标题/年份/我的状态角标/Emby 角标；筛选栏：状态、类型、年代、是否在 Emby、我的评分；搜索框；排序（最近同步/年份/我的评分）。
- 抽屉三段：**元数据**（只读）/ **Emby 事实**（只读：在库、播放次数、进度、最后播放）/ **我的标记**（可编辑，改完即保存）。
- 顶部按钮：「手工添加」（TMDb 搜索弹窗）、「同步 Emby」（跳转 SyncView 或直接调 run 接口 + SSE 进度）。
- 复用 VideoView 的分页/筛选/URL query 同步模式。

---

## 7. MCP 工具（`backend/mcp_server.py`）

| 工具 | 只读 | 说明 |
|------|------|------|
| `list_films(status?, kind?, genre?, year_from?, year_to?, in_emby?, q?, limit=200)` | 是 | 返回精简行：content_id、tmdb 键、标题、年份、类型、导演、状态、我的评分、Emby 事实摘要 |
| `search_film(q, year?)` | 是 | TMDb 搜索，返回候选（供 agent 落库前确认 ID） |
| `mark_films(items: list[{tmdb_id?, kind?, content_id?, title?, year?, status, my_rating?, watched_at?, comment?, tags?, rewatch?}])` | 否 | 批量建/改标记；不存在的影片先建骨架再标记；`rewatch` 新记一次观看；返回每条的结果 |

推荐流程：agent 先 `list_films` 拉全库 → 推荐时排除已有记录并带 TMDb ID → 用户回复"1、3、5 看过" → agent `mark_films` 一次落库。

---

## 8. 实施顺序

1. 模型 + 迁移（SourceType 两项、`watch_records` 表）
2. `EmbyFetcher` + 注册 `SYNC_PLUGINS` + 凭证类型 `api_key` 的表单适配
3. `/api/films/*` 路由 + upsert 服务（`upsert_films`，放 `services/sync/upsert.py`）
4. `FilmsView` + 抽屉
5. MCP 三个工具
6. 文档同步：`business_glossary.md`（SourceType 表）、`system_design.md`（Sync 表、API 段）、`product_spec.md`

验证：在一次性容器里跑 alembic + uvicorn，用 Emby 的 `/System/Info/Public` 与本地 library.db 抽样比对同步结果；部署由用户执行 `deploy-home-server.sh`。

---

## 9. Phase 2（不在本期）

- `sync.douban_movies`：导入豆瓣"看过/想看"，按片名+年份映射到 TMDb ID，`status_source = douban_import`，同样不覆盖 manual。
- 增量同步与自动化（定时 / Emby Webhook）。
- 剧集单集级进度。

---

## 10. 待确认 / 风险

- ~~`Users/{uid}/Items` 用服务器级 API key 是否正常返回 UserData~~ 2026-09-16 实测：**列表接口**的 UserData 是精简版（无 `LastPlayedDate`，`PlayCount` 不准），**单条接口** `/Users/{uid}/Items/{id}` 才完整。Fetcher 列表后逐条补全（并发 8）。
- 部署注意：`deploy-home-server.sh` 先 `up -d` 再 `alembic upgrade`，而应用启动会 `Base.metadata.create_all`，新表在迁移前已被建出来 → `create_table` 报 DuplicateTable。首次上线 0021 时用 `alembic stamp 0021_add_watch_records` 收尾。后续含建表的迁移同样会撞上，要么迁移用 `IF NOT EXISTS`，要么部署脚本先迁移再起容器。
- TMDb API key 需申请（免费）；home-server 出网走 Emby 同一路径，可达性已被 Emby 刮削证明。
- 海报代理需注意 Emby 图片接口的缓存头，避免每次列表都打 Emby。
