# Allin-One 产品方案 (PRD)

> 版本: v2.0-draft | 更新日期: 2026-02-22

---

## 1. 产品定位与目标

### 1.1 产品愿景

**别人的 AI 帮你读得更快，Allin-One 的 AI 帮你想得更深。**

Allin-One 是 AI 驱动的个人思维训练系统。它从海量信息源中自动采集内容，通过 AI 分析帮你快速筛选，然后在收藏、回顾、对质的过程中，把被动的信息消费变成主动的认知升级。

核心信念：**信息的价值不在于读了多少，而在于留下了什么、想清楚了什么。** 受林迪效应启发，系统帮助用户发现和沉淀经得起时间考验的内容，而非追逐转瞬即逝的热点。

产品三层价值：
1. **高效发现**（基础层）：多源聚合 + AI 分析，快速筛选值得关注的内容
2. **深度收藏**（核心层）：收藏不是存储，而是思考的起点——AI 追问、矛盾检测、主题聚类
3. **思维训练**（目标层）：间隔重现、认知追踪、跨内容综合，帮你建立和修正自己的认知框架

### 1.2 目标用户
技术从业者、信息重度消费者、内容创作者等需要跟踪大量信息源并希望从中构建个人认知体系的用户。

### 1.3 核心指标
| 指标 | 目标值 | 说明 |
|------|--------|------|
| 数据源容量 | 1,000+ | 支持同时监控的订阅源数量 |
| 日更新量 | ~2,000 条 | 每日自动采集的新内容条目 |
| 覆盖类型 | 文章/视频/音频 | 支持的媒体类型 |
| 分析延迟 | <5 分钟 | 从采集到分析完成的时间 |
| 部署方式 | 单机 Docker | 个人 VPS / NAS 即可运行 |
| 收藏深度互动率 | >30% | 收藏时触发 AI 对质的比例（v2.0 新增） |
| 重现回顾率 | >50% | 间隔重现内容被用户实际回顾的比例（v2.0 新增） |

---

## 2. 功能架构

### 2.1 信息流 (Feed)

信息流是用户的主要内容消费界面，类似 RSS 阅读器但增强了 AI 分析能力。

**导航与筛选**
- 顶部导航栏按数据源筛选，支持「仅看视频」快捷开关
- 支持按数据源分组浏览
- 支持时间排序 (最新 / 最早)

**信息卡片**
每条内容以卡片形式展示，支持以下操作:
- **查看原文**: 跳转原始链接或内嵌阅读器
- **展开全部**: 在页面内展开完整内容
- **AI 分析**: 查看 LLM 生成的摘要、关键观点、情感分析
- **删除**: 软删除该条目
- **收藏**: 标记为收藏，后续可快速检索

**卡片信息展示**
- 数据源标识 (图标 + 名称)
- 数据源配置链接
- 关联的 Pipeline 执行链接
- 发布时间 / 采集时间

### 2.2 数据源管理 (Sources)

> **数据接入模式说明**
> - **Collect 数据源**：在后台自动定时采集，用户只需配置 URL 和调度间隔。
> - **Fountain 数据源**（`sync.*` 类型）：需要在 Fountain 桌面客户端中配置凭证并手动触发同步，
>   后端通过 `/api/{ebook|video|bookmark}/sync` 三步 API 接收推送数据。

**数据源管理操作**
- **新增**: 支持多种类型的数据源创建 (详见 2.2.1)
- **修改**: 编辑数据源配置 (URL、名称、采集频率等)
- **删除**: 提供两种删除模式
  - 关联内容删除: 删除数据源及其所有采集内容
  - 只删除数据源: 保留已采集内容，仅移除订阅配置
- **批量操作**: 支持多选后批量删除数据源（含级联确认）
- **一键采集**: 批量触发所有启用的数据源立即采集
- **批量导入/导出**: 支持 OPML 格式批量导入导出 RSS 订阅

#### 2.2.1 数据源类型矩阵

数据源只描述「信息从哪来」，不涉及处理逻辑。处理方式由绑定的流水线模板决定。

| 类别 | 类型代码 | 描述 | 采集方式 | 接入模式 |
|------|----------|------|----------|---------|
| RSS | `rss.hub` | RSSHub 生成的订阅源 | RSSHub 服务 (B站/微博/YouTube 等都走这个) | Collect |
| RSS | `rss.standard` | 标准 RSS/Atom 订阅源 | feedparser 直接解析 | Collect |
| 数据 | `api.akshare` | AkShare 宏观经济数据 | AkShare API | Collect |
| 网页 | `web.scraper` | 网页抓取 | L1 HTTP / L2 Browserless / L3 browser-use | Collect |
| 文件 | `file.upload` | 用户上传文件 | Web UI 上传 | Collect |
| 播客 | `podcast.apple` | Apple Podcasts | 播客 RSS 解析 | Collect |
| 账号 | `account.generic` | 其他平台账号 | 平台特定 API | Collect |
| 同步 | `sync.apple_books` | Apple Books 同步 | Fountain 客户端读取本地 SQLite 推送 | Fountain |
| 同步 | `sync.wechat_read` | 微信读书同步 | Fountain 客户端调用微信 API 推送 | Fountain |
| 同步 | `sync.bilibili` | B站视频同步 | Fountain 客户端调用 B站 API 推送 | Fountain |
| 同步 | `sync.kindle` | Kindle 标注同步 | Fountain 客户端读取 My Clippings.txt 推送 | Fountain |
| 同步 | `sync.safari_bookmarks` | Safari 书签同步 | Fountain 客户端读取本地书签库推送 | Fountain |
| 同步 | `sync.chrome_bookmarks` | Chrome 书签同步 | Fountain 客户端读取本地书签文件推送 | Fountain |
| 同步 | `sync.douban_books` | 豆瓣书单同步 | 豆瓣读书数据同步 | Fountain |
| 同步 | `sync.douban_movies` | 豆瓣影单同步 | 豆瓣电影数据同步 | Fountain |
| 同步 | `sync.zhihu` | 知乎收藏夹同步 | 知乎收藏数据同步 | Fountain |
| 同步 | `sync.github_stars` | GitHub Star 同步 | GitHub Star 仓库数据同步 | Fountain |
| 同步 | `sync.twitter` | Twitter/X 推文同步 | Twitter 推文数据同步 | Fountain |
| 记录 | `user.note` | 日常笔记 | 用户手动输入 | 直接 POST API |
| 记录 | `system.notification` | 系统消息 | 系统通知 | 系统生成 |

**关键设计**: 没有 `video_bilibili` / `video_youtube` 等类型。B站/YouTube 视频通过 `rss.hub` 数据源发现新内容，再由流水线中的 `localize_media` 步骤处理。`sync.*` 类型通过外部脚本获取平台数据后推送到同步 API。

**组合示例**:
| 场景 | 数据源 | 绑定的流水线模板 |
|------|--------|------------------|
| B站UP主视频分析 | `rss.hub` (路由: /bilibili/user/video/12345) | "视频下载分析" |
| YouTube频道翻译 | `rss.hub` (路由: /youtube/channel/UCxxx) | "视频翻译分析" |
| 英文科技博客 | `rss.standard` (URL: feeds.arstechnica.com) | "英文文章翻译分析" |
| 中文新闻 | `rss.standard` (URL: 36kr.com/feed) | "文章分析" |
| 公告页面监控 | `web.scraper` (URL + 选择器) | "文章分析" |
| 宏观经济数据 | `api.akshare` (指标: macro_china_cpi) | "金融数据分析" |

### 2.3 内容管理 (Content)

以表格形式管理所有采集到的内容条目，提供:
- **筛选**: 按数据源、状态 (pending/ready/analyzed/failed)、是否含视频、时间范围、收藏、未读
- **排序**: 按发布时间、采集时间、标题
- **去重**: 基于 `external_id` (URL) 的自动去重，支持手动去重
- **批量操作**: 选中多条内容执行批量删除或批量 AI 分析
- **清空全部**: 一键删除所有内容（级联删除关联流水线和媒体）

### 2.4 仪表盘 (Dashboard)

系统运行状态概览:
- **统计概览**: 数据源总数、今日新增内容、Pipeline 执行统计
- **时间调度日志**: 最近的定时任务执行记录
- **Pipeline 执行记录**: 最近的 Pipeline 运行状态与耗时
- **异常告警**: 失败的任务与错误源高亮

用户行为统计:
- **四大指标卡片**: 已阅读、已收藏、AI 对话、笔记批注四项核心行为指标，每项含今昨对比趋势
- **阅读活跃度热力图**: 近 84 天的每日阅读量，GitHub 风格热力图可视化
- **阅读趋势图**: 近 7 天已读+收藏双线折线图，直观展示阅读与收藏走势
- **数据源消费偏好**: 按阅读量排序的 Top 5 数据源，展示用户内容消费分布

### 2.5 流水线管理 (Pipelines)

**流水线配置**
- 查看所有 Pipeline 模板及其步骤定义
- 创建自定义 Pipeline 模板
- 原子操作配置 (每个步骤的参数调整)
- 可视化流水线模板编辑器（通过 Modal 选择步骤类型、配置参数、排序步骤）
- 流水线模板的启用/禁用

**执行监控**
- Pipeline 执行列表 (状态、耗时、步骤进度)
- 单个执行的步骤级详情与日志
- 失败步骤的重试操作

### 2.6 视频管理 (Video)

- **视频下载**: 通过 yt-dlp 下载 Bilibili / YouTube 视频到本地，由 `localize_media` 步骤自动处理
- **视频播放**: 内嵌 Artplayer 播放器，三级回退（本地已下载 → Bilibili/YouTube iframe 嵌入 → 状态提示）
- **后台播放**: 关闭内容详情弹窗后，视频/播客音频通过底部迷你播放条继续播放音轨（降级为 audio 元素），支持进度条、暂停/播放、锁屏续播
- **元数据展示**: 视频标题、作者、时长、清晰度
- **视频封面**: 下载时自动获取封面图（yt-dlp 优先，ffmpeg 回退）
- **媒体查找**: 优先从 MediaItem 查找视频/封面路径，回退到 PipelineStep 输出

### 2.7 凭证管理 (Credentials)

管理需要登录凭证的平台账号:
- B站账号 (Cookie / 扫码登录)
- RSSHub 自部署实例同步
- 其他需要认证的平台账号
- 凭证值展示时掩码处理，更新时空值不覆盖已有密钥

### 2.8 系统配置 (Settings)

- **大模型 API**: API Key、Base URL、模型名称，支持连接测试
- **数据保留**: 默认保留天数、执行记录/采集记录保留策略 (天数+数量上限)
- **手动清理**: 手动清理已终态的执行记录和采集记录
- **通知配置**: 邮件、Webhook

### 2.9 收藏 2.0：深度收藏与思维训练 (v2.0)

> 产品核心升级。收藏从"存储动作"进化为"思维训练入口"。

#### 2.9.1 设计理念

现有内容平台的收藏功能普遍薄弱（一个按钮 + 一个列表），根源在于广告驱动的商业模式与用户沉淀旧内容的需求天然对立。Allin-One 作为自部署工具，没有这个利益冲突，可以把收藏做到极致。

核心原则：
- **林迪效应导向**：帮用户发现经得起时间考验的内容，而非最新最热的
- **收藏即思考**：每次收藏都伴随一次思维互动，而非无脑存储
- **认知可追踪**：记录用户在不同时间对同一话题的理解，形成思维演变轨迹

#### 2.9.2 林迪信号识别

**用户故事**：作为信息消费者，我希望系统能自动标识出"持久价值"高的内容，以便我优先深入阅读，而非被时效性新闻淹没。

**信号维度**：
| 信号 | 权重 | 说明 |
|------|------|------|
| 跨源引用 | 高 | 同一话题/观点被多个独立数据源引用或讨论 |
| 时间持久性 | 高 | 发布 N 天后仍有新互动（评论、引用、转发） |
| 内容深度 | 中 | AI 评估内容的论据完整性、信息密度 |
| 话题反复出现 | 中 | 用户的信息源中同一主题在不同时间段反复出现 |
| 原创性 | 中 | 非转载、非聚合，包含独立分析或一手数据 |

**产出**：每条内容在 AI 分析结果中增加 `lindy_score`（0-100），信息流和内容库支持按此分数排序和筛选。

**验收标准**：
- [ ] AC-1: 分析结果包含 lindy_score 字段，基于上述信号维度计算
- [ ] AC-2: 信息流支持按 lindy_score 排序
- [ ] AC-3: 内容卡片展示林迪分数标识（高分内容可视化突出）

#### 2.9.3 收藏时 AI 对质

**用户故事**：作为信息消费者，我希望收藏内容时 AI 能追问我一个有深度的问题，以便我在收藏的瞬间被迫认真思考这条内容的价值。

**交互流程**：
1. 用户点击收藏按钮
2. 内容被收藏，同时弹出一个轻量对话框
3. AI 基于内容分析结果生成一个追问（非必须回答，可跳过）
4. 用户的回答作为"收藏笔记"保存，关联到该收藏条目

**AI 追问类型**（由 LLM 根据内容自动选择）：
| 类型 | 示例 |
|------|------|
| 核心论点提炼 | "这篇文章的核心论点是什么？用一句话概括。" |
| 立场判断 | "你同意作者的观点吗？为什么？" |
| 矛盾发现 | "这和你之前收藏的《XX》观点相反，你怎么看？" |
| 应用延伸 | "这个观点对你当前的工作/项目有什么启发？" |
| 信息缺口 | "这篇文章没有提到 XX 方面，你觉得这会影响结论吗？" |

**验收标准**：
- [ ] AC-1: 收藏时弹出 AI 追问对话框（可配置开关）
- [ ] AC-2: AI 追问基于内容分析结果生成，与内容高度相关
- [ ] AC-3: 用户回答保存为收藏笔记，在收藏详情页可查看
- [ ] AC-4: 如果收藏内容与已有收藏存在矛盾，优先使用"矛盾发现"类型追问

#### 2.9.4 盲区检测与偏见提醒

**用户故事**：作为信息消费者，我希望系统能发现我的信息偏好盲区，以便我避免确认偏误，获得更全面的认知。

**机制**：
- 系统定期分析用户的收藏和阅读模式
- 当检测到单一话题的收藏内容立场高度一致时，生成"偏见提醒"
- 提醒中包含被忽略的反面观点或对立信息源建议

**验收标准**：
- [ ] AC-1: 系统能识别收藏内容的立场倾向（基于 AI 分析的 sentiment 和 stance 字段）
- [ ] AC-2: 当同一话题收藏内容立场一致性 >80% 时，触发偏见提醒
- [ ] AC-3: 提醒内容包含具体的反面论据或建议关注的反面信息源

#### 2.9.5 收藏主题聚类

**用户故事**：作为信息消费者，我希望收藏内容能按主题自动组织，以便我看到自己在哪些领域有深度积累，哪些只是浅尝辄止。

**实现**：
- 基于 AI 分析结果中的 tags 和语义相似度，自动将收藏聚类
- 每个聚类展示主题名称、内容数量、时间跨度、核心观点汇总
- 支持手动调整聚类归属

**验收标准**：
- [ ] AC-1: 收藏页增加"按主题"视图，自动聚类展示
- [ ] AC-2: 每个主题展示内容数量和时间跨度
- [ ] AC-3: 用户可手动将内容移入/移出主题

#### 2.9.6 间隔重现与认知追踪

**用户故事**：作为信息消费者，我希望收藏的内容能在合适的时间重新出现在我面前，并且带上我当时的想法和新的关联内容，以便我在不同时间节点重新审视自己的认知。

**间隔重现机制**：
- 收藏后 7 天、30 天、90 天、365 天分别重现一次（可配置）
- 重现时展示：原始内容 + 当时的收藏笔记 + 这段时间新增的相关收藏
- AI 追问："你当时认为 XX，现在还是这样想吗？"

**认知追踪**：
- 记录用户每次重现时的回答
- 形成该话题/内容的"认知演变时间线"
- 支持查看自己在某个主题上的思维变化历程

**验收标准**：
- [ ] AC-1: 收藏内容按间隔周期自动加入"今日重现"队列
- [ ] AC-2: 重现卡片展示原始内容摘要 + 收藏笔记 + 新关联内容
- [ ] AC-3: 用户可在重现时补充新的思考笔记
- [ ] AC-4: 支持查看单条内容的认知演变时间线（所有笔记按时间排列）

#### 2.9.7 跨内容知识综合

**用户故事**：作为信息消费者，我希望能对整个收藏库或某个主题下的所有收藏发起 AI 提问，以便我从碎片化的收藏中提炼出系统性的认知。

**交互**：
- 在收藏页或主题聚类页，提供"综合提问"入口
- AI 基于选定范围内的所有内容进行综合分析
- 支持的问题类型：
  - "这些内容的核心观点有哪些共识和分歧？"
  - "按时间线梳理这个话题的演变"
  - "帮我写一篇关于这个主题的综述"
  - 自由提问

**验收标准**：
- [ ] AC-1: 收藏页/主题页支持对选定范围发起 AI 综合提问
- [ ] AC-2: AI 回答基于收藏内容，包含引用来源
- [ ] AC-3: 综合分析结果可保存为独立的笔记内容

---

## 3. 原子操作详细设计

原子操作是 Pipeline 的基本构建单元，每个操作独立、可配置、可重试。

### 3.0 提取内容 (extract_content)

- **功能**: 从 `raw_data` 中提取文本内容到 `processed_content`
- **位置**: 通常作为流水线的第一个步骤，由模板显式包含
- **说明**: 将 Collector 采集的原始 JSON 数据解析为可读文本

### 3.1 抓取全文 (enrich_content)

采用三级递进策略，根据内容复杂度自动升级:

| 级别 | 方式 | 适用场景 | 成本 |
|------|------|----------|------|
| L1 | HTTP 模拟抓取 | 静态页面、API 接口 | 低 |
| L2 | 浏览器模拟抓取 (Browserless) | 需要 JS 渲染的页面 | 中 |
| L3 | browser-use (AI 操控浏览器) | 需要交互操作的页面 | 高 |

**策略**: 默认从 L1 开始尝试，如果提取内容为空或质量不佳，自动升级到下一级别。

### 3.2 文章翻译 (translate_content)

- **配置项**: 目标语言 (默认中文)
- **实现**: 调用 LLM 进行翻译，保留原文格式
- **触发条件**: 源内容语言 ≠ 目标语言时自动插入此步骤

### 3.3 媒体本地化 (localize_media)

- **功能**: 检测内容中的图片/视频/音频，下载到本地，创建 MediaItem 记录，改写URL为本地引用
- **视频**: 通过 yt-dlp 下载 Bilibili/YouTube 视频，同时获取封面和字幕
- **图片/音频**: 直接 HTTP 下载
- **输出**: MediaItem 记录 (含 local_path、metadata_json)，步骤 output_data 含 has_video 标记

### 3.4 音频提取 (transcribe_content)

- **状态**: 待实现
- **规划**: 使用 Whisper 或第三方 ASR 服务将视频/音频转为文字

### 3.5 模型分析 (analyze_content)

- **配置项**:
  - 模型选择: 下拉枚举 (deepseek-chat, gpt-4o, etc.)
  - 提示词: 关联 `prompt_templates` 中的模板
  - 输出格式: JSON (默认) / Markdown / Text
- **分析维度** (通过提示词配置):
  - 时间、人物、地点
  - 背景、立场、佐证
  - 摘要、关键观点
- **输出**: 结构化的分析报告 JSON，或非结构化的 Markdown/Text 文本


### 3.6 消息推送 (publish_content)

- **配置项**:
  - 渠道: Email / 钉钉 / Webhook
  - 频率: 即时 / 汇总 (按小时/天)
- **推送内容**: 标题 + AI 摘要 + 原文链接

---

## 4. 任务调度设计

采用「定时器 + 流水线」双层调度模式，均基于 Procrastinate (PG-backed 任务队列):

### 4.1 定时器层 (Procrastinate periodic)

| 任务类型 | 调度策略 | 说明 |
|----------|----------|------|
| 数据采集 | 智能调度 (每分钟检查) | 基于 `next_collection_at` 预计算字段，支持 auto/fixed/manual 三种调度模式 |
| 数据采集 | 退避策略 | 连续失败时指数退避，由 SchedulingService 计算 |
| 数据采集 | 并发 defer | 每个源的采集任务 defer 到 scheduled 队列并发执行 |
| 周期分析 | 每天 04:00 | 分析活跃源的更新模式 (periodicity)，优化调度间隔 |
| 日报 | 每天 22:00 | 自动生成日报 |
| 周报 | 每周一 09:00 | 自动生成周报 |
| 清理调度 | 每小时检查 | 根据 system_settings 配置的清理时间动态执行内容清理和记录清理 |

### 4.2 流水线层 (Procrastinate Worker)

- 采集产出新内容后，Orchestrator 为每条内容创建 Pipeline 实例
- Pipeline 步骤由 Procrastinate Worker (pipeline 队列, concurrency=4) 异步执行
- 定时调度任务由另一个 Worker (scheduled 队列, concurrency=2) 执行，互不阻塞
- 支持步骤级别的并发控制和卡住任务自动恢复

---

## 5. 数据模型

### 5.1 内容记录 (ContentItem)

| 字段 | 说明 |
|------|------|
| 原始内容 (`raw_data`) | 采集的原始 JSON 数据包 |
| 中间内容 (`processed_content`) | 清洗/富化后的全文 |
| 最终内容 (`analysis_result`) | LLM 分析结果 |
| 发布时间 (`published_at`) | 原始内容的发布时间 |
| 采集时间 (`collected_at`) | 系统采集该内容的时间 |

ContentItem 不再有 `media_type` 字段。媒体通过 `MediaItem` 一对多关联管理。

### 5.2 媒体项 (MediaItem)

| 字段 | 说明 |
|------|------|
| `content_id` | 关联的 ContentItem |
| `media_type` | 媒体类型: image / video / audio |
| `original_url` | 远程 URL |
| `local_path` | 下载后的本地路径 |
| `status` | pending / downloaded / failed |
| `metadata_json` | 类型特定元数据 (如 thumbnail_path、duration 等) |

### 5.3 分析结果结构 (LLM 输出)

**JSON 格式 (标准结构化输出)**:
```json
{
  "summary": "一句话摘要",
  "key_points": ["要点1", "要点2"],
  "entities": {
    "time": ["2026-02-10"],
    "people": ["张三"],
    "locations": ["北京"],
    "organizations": ["公司A"]
  },
  "background": "事件背景",
  "stance": "作者立场分析",
  "evidence": ["佐证1", "佐证2"],
  "sentiment": "positive|neutral|negative",
  "tags": ["科技", "AI"]
}
```

**Markdown / Text 格式**:
对于非结构化输出，系统会将其封装在标准 JSON 容器中：
```json
{
  "content": "# 分析报告\n\n## 摘要\n这里是 Markdown 格式的分析内容...",
  "format": "markdown"
}
```

### 5.4 用户记录 (User Records)

- **日常笔记**: 用户可对内容添加个人笔记
- **用户消息**: 系统通知与推送记录

---

## 6. 文件存储

所有运行时数据存放在项目根目录 `data/`（非 backend/data/），backend 和 worker 共享同一挂载。

| 类型 | 存储路径 | 说明 |
|------|----------|------|
| 媒体文件 | `data/media/{content_id}/` | 按内容 ID 分目录存放视频/图片/音频 |
| 分析报告 | `data/reports/` | LLM 生成的分析报告 |
| 数据库 | PostgreSQL (`allinone` database) | 应用数据 + Procrastinate 任务队列共用 |
| 日志文件 | `data/logs/` | backend.log, worker.log, error.log |
| 数据备份 | `data/backups/` | 数据库自动/手动备份 |

---

## 7. 页面路由结构

| 路径 | 页面 | 核心功能 |
|------|------|----------|
| `/` | 重定向 | → `/feed` |
| `/login` | 登录 | API Key 认证 (可选) |
| `/dashboard` | 仪表盘 | 系统概览、统计、告警 |
| `/feed` | 信息流 | 内容消费、AI 分析阅读 |
| `/favorites` | 收藏 | 收藏内容专属视图 |
| `/sources` | 数据源管理 | CRUD、批量导入导出 |
| `/content` | 内容库 | 表格管理、筛选排序去重 |
| `/pipelines` | 流水线 | 执行记录、流水线模板、提示词配置 |
| `/media` | 媒体管理 | 视频/音频下载与播放 |
| `/finance` | 金融数据 | 宏观经济数据展示 |
| `/settings` | 系统设置 | API Key、代理、账号 |

---

## 8. 版本规划

### v1.0 — MVP (核心采集与分析)
- [x] RSS / RSSHub 数据源采集
- [x] Pipeline 编排与执行引擎
- [x] LLM 内容分析 (摘要、关键点)
- [x] 信息流阅读界面
- [x] Docker 一键部署

### v1.1 — 视频能力 + 媒体管理
- [x] Bilibili / YouTube 视频下载
- [x] 视频字幕提取与分析
- [x] 内嵌视频播放器
- [x] MediaItem 独立媒体管理 (localize_media 取代 download_video)
- [x] 凭证管理 (B站扫码、RSSHub 同步)
- [x] 金融数据源 (AkShare 集成)
- [x] 数据保留策略 (执行记录/采集记录清理)
- [x] 结构化日志系统 (backend.log / worker.log / error.log)
- [x] 批量操作 (源批量删除、一键采集、内容清空)

### v1.2 — 智能调度 + 增强功能
- [x] 智能调度系统 (auto/fixed/manual 三模式, 周期性分析, 热点检测)
- [x] Procrastinate 双队列隔离 (pipeline + scheduled)
- [x] 流水线模板显式步骤 (extract_content 取代自动注入预处理)
- [x] 内容 AI 对话 (chat_history)
- [x] 收藏页面 (/favorites)
- [x] 媒体统一管理页 (/media, 取代 /video-download)
- [x] API Key 认证 + 登录页
- [x] 播客数据源 (podcast.apple)
- [x] 收藏触发媒体下载 (favorite trigger)
- [x] 全量数据导入/导出

### v2.0 — 收藏 2.0：从存储到思考
- [ ] 林迪信号识别 (lindy_score 计算与展示)
- [ ] 收藏时 AI 对质 (追问对话框 + 收藏笔记)
- [ ] 盲区检测与偏见提醒 (立场一致性分析)
- [ ] 收藏主题聚类 (自动聚类 + 手动调整)
- [ ] 间隔重现 (7/30/90/365 天周期 + 认知追踪)
- [ ] 跨内容知识综合 (收藏库级 AI 提问)
- [ ] 邮件/钉钉推送通道

### v1.3 — MCP 数据源管理与收藏读取增强
- [x] MCP 数据源管理工具 (create_source, update_source, delete_source, toggle_source)
- [x] MCP 收藏统计工具 (get_favorites_summary)
- [x] MCP 现有工具修复与增强 (JSONB bug, tool annotations)

### v1.4 — MCP 金融数据工具
- [x] MCP 市场指数快照工具 (get_market_snapshot — A 股六大指数 + 恒生指数)
- [x] MCP 个股行情工具 (get_stock_quote — A/HK/US/crypto 多市场)
- [x] MCP K 线历史数据工具 (get_kline — 日/周/月，支持前后复权)
- [x] MCP 宏观经济指标工具 (get_macro_indicator — CPI/PPI/PMI/GDP/M2/SHIBOR)

### v3.0 — 展望
- [ ] browser-use AI 浏览器操控
- [ ] 知识图谱可视化 (收藏内容关联网络)
- [ ] 认知演变时间线 (可视化个人思维变化)
- [ ] 个人思维模型画像 (基于收藏与笔记的认知特征分析)
- [ ] 多语言翻译 Pipeline

---

## 9. MCP Server 扩展：数据源管理与收藏读取 (v1.3)

### 9.1 需求概要

**用户故事**: 作为 AI 助手（Claude Code / Cursor）用户，我希望通过对话直接管理数据源（"帮我订阅 36kr""把那个失败的源关掉"）和深度了解收藏内容分布，而不用切换到 Web UI。

**核心场景**:
- "帮我添加一个 RSS 订阅 https://36kr.com/feed"
- "把那个连续失败的源禁用掉"
- "删掉 xxx 这个不用的数据源"
- "我最近收藏了哪些内容？按数据源分布如何？"

**痛点**: 当前 MCP 只有 4 个工具（list_content / get_content_detail / get_sources / toggle_favorite），数据源只读，收藏缺乏聚合分析。AI 无法帮用户完成数据源管理这一高频需求。

### 9.2 讨论要点

**工具粒度**: 选择细粒度（每个操作独立工具），理由——不同操作参数差异大，粗粒度工具的条件字段让 LLM 容易幻觉无关参数；MCP tool annotations（destructiveHint）需要按工具粒度标注。

**智能推导 vs 显式参数**: create_source 支持 URL 自动推导 source_type 和模板名匹配，降低用户输入门槛。推导不确定时返回候选供 AI 确认。

**定位方式**: 所有写操作同时支持 source_id 和 source_name（模糊匹配），匹配多个时返回候选列表。

**不做采集触发**: collect_source 需要 Procrastinate 连接初始化，复杂度高且使用频率低，暂不暴露。

**安全性**: MCP 规范中安全确认是 client 端责任（Claude Code 根据 destructiveHint 弹确认），server 通过 tool annotations 声明风险等级。

### 9.3 功能规格

#### 工具清单（扩展后共 9 个）

| 工具 | 类型 | annotations | 说明 |
|------|------|-------------|------|
| `list_content` | 读 | readOnly | 已有，不变 |
| `get_content_detail` | 读 | readOnly | 已有，不变 |
| `get_sources` | 读 | readOnly | 已有，不变 |
| `toggle_favorite` | 写 | destructive=false | 已有，不变 |
| **`create_source`** | 写 | destructive=false | 新增——创建数据源，支持 URL 自动推导类型 |
| **`update_source`** | 写 | destructive=false, idempotent | 新增——修改数据源配置 |
| **`delete_source`** | 写 | destructive=true | 新增——删除数据源（默认保留关联内容） |
| **`toggle_source`** | 写 | destructive=false, idempotent | 新增——启用/禁用数据源 |
| **`get_favorites_summary`** | 读 | readOnly | 新增——收藏统计与分布 |

#### create_source 详细设计

**参数**（扁平化，对 LLM 友好）:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | str | 是 | 数据源名称 |
| url | str | 否 | RSS/网页 URL（标准 RSS 必填） |
| source_type | str | 否 | 类型代码，省略时从 URL 自动推导 |
| rsshub_route | str | 否 | RSSHub 路由（仅 rss.hub 需要） |
| pipeline_template_name | str | 否 | 模板名称（模糊匹配），省略时自动推荐 |
| description | str | 否 | 数据源描述 |
| schedule_interval_minutes | int | 否 | 采集间隔（分钟），默认 auto 模式 |

**智能推导逻辑**:
- 提供 URL 且像标准 RSS → source_type = `rss.standard`
- 提供 rsshub_route → source_type = `rss.hub`
- 未提供 source_type 且无法推导 → 返回错误提示可选类型
- pipeline_template_name 模糊匹配，匹配多个返回候选列表
- 名称唯一性校验、类型合法性校验复用已有逻辑

#### update_source 详细设计

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source_id | str | 否 | 数据源 ID（与 source_name 二选一） |
| source_name | str | 否 | 数据源名称（模糊匹配） |
| name | str | 否 | 新名称 |
| url | str | 否 | 新 URL |
| pipeline_template_name | str | 否 | 新模板名称 |
| schedule_interval_minutes | int | 否 | 新采集间隔 |
| description | str | 否 | 新描述 |

#### delete_source 详细设计

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source_id | str | 否 | 数据源 ID（与 source_name 二选一） |
| source_name | str | 否 | 数据源名称（模糊匹配） |
| cascade | bool | 否 | 是否级联删除关联内容，默认 false（保留内容） |

#### toggle_source 详细设计

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source_id | str | 否 | 数据源 ID（与 source_name 二选一） |
| source_name | str | 否 | 数据源名称（模糊匹配） |
| action | str | 是 | "enable" 或 "disable" |

#### get_favorites_summary 详细设计

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| time_range | str | 否 | "7d/30d/90d/all"，默认 "all" |

**返回**:
```json
{
  "total_favorites": 42,
  "by_source": [{"source_name": "36kr", "count": 15}, ...],
  "by_month": [{"month": "2026-03", "count": 8}, ...],
  "recent": [{"id": "...", "title": "...", "favorited_at": "...", "source_name": "..."}, ...]
}
```

### 9.4 技术设计摘要

**数据访问模式**: 渐进式 Service 层复用——读操作继续直接 DB 查询（当前模式），写操作的校验逻辑（source_type 校验、名称唯一性、RSSHub 路由必填等）从 Router (`sources.py`) 提取到共享函数，MCP 和 Router 共同调用。

**定位辅助函数**: 新增 `_resolve_source(db, source_id, source_name)` 辅助函数，支持 ID 精确匹配或 name 模糊匹配，匹配 0 个返回 not found，匹配多个返回候选列表。

**Bug 修复**: `_extract_analysis` 函数对 JSONB 字段错误使用 `json.loads`，导致 analysis 数据静默丢失，需修复为直接读取 dict。

**Tool Annotations**: 所有工具添加 MCP tool annotations（readOnlyHint / destructiveHint / idempotentHint），便于 client 端做安全确认。

**影响范围**:
- 修改: `backend/mcp_server.py`（主要改动文件）
- 修改: `backend/app/api/routes/sources.py`（提取校验逻辑到共享函数）
- 新增: `backend/app/services/source_service.py`（共享校验函数）
- 不涉及: 数据库迁移、前端改动

### 9.5 实施路径

**Phase 1 (MVP)**:
- 修复 `_extract_analysis` JSONB bug
- 为现有 4 个工具添加 tool annotations
- 提取数据源校验逻辑到 `source_service.py`
- 实现 create_source（含 URL 自动推导）
- 实现 update_source / delete_source / toggle_source（含 name 模糊定位）
- 实现 get_favorites_summary
- 验收标准:
  - AC-1: 可通过 MCP 创建 rss.standard 和 rss.hub 数据源
  - AC-2: 可通过名称模糊匹配定位并修改/删除/启禁数据源
  - AC-3: get_favorites_summary 返回按源分布和按月趋势
  - AC-4: 现有 4 个工具行为不变，analysis 数据正常返回

**Phase 2 (增强)**:
- list_content 增加 favorited_after/favorited_before 时间过滤
- create_source 支持更多类型的智能推导（web.scraper / podcast.apple）
- 错误消息优化，返回更友好的 AI 可读提示

### 9.6 任务拆分

- [x] 后端: 修复 `mcp_server.py` 中 `_extract_analysis` 的 JSONB 读取 bug（`json.loads` → 直接读取 dict）
- [x] 后端: 为现有 4 个 MCP 工具添加 tool annotations（readOnlyHint / destructiveHint）
- [x] 后端: 从 `app/api/routes/sources.py` 提取数据源校验逻辑到 `app/services/source_service.py`（source_type 校验、名称唯一性、RSSHub 路由必填、模板存在性校验），Router 改为调用共享函数
- [x] 后端: 在 `mcp_server.py` 中新增 `_resolve_source` 辅助函数（ID 精确 / name 模糊定位）和 `_resolve_template` 辅助函数（模板名模糊匹配）
- [x] 后端: 实现 `create_source` MCP 工具（扁平参数 + URL 自动推导 source_type + 模板名匹配 + 调用共享校验）
- [x] 后端: 实现 `update_source` / `delete_source` / `toggle_source` 三个 MCP 工具（name 模糊定位 + 调用共享校验）
- [x] 后端: 实现 `get_favorites_summary` MCP 工具（收藏总数 + 按源分布 + 按月趋势 + 最近收藏列表）
- [ ] 后端: 更新 `.mcp.json` 配置，确保新工具在 Claude Code 中可用
