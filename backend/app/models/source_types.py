"""数据源类型注册表 —— 关于「源类型」的全部知识只在这里定义一次

2026-09 审计（docs/audit_2026-09_architecture.md §3-C）发现同一份知识散落在后端 12 处以上：
SourceType 枚举、前缀→分类映射、COLLECTOR_MAP、_USER_SUBMISSION_TYPES、仪表盘的非采集名单、
SYNC_FETCHERS、SYNC_PLUGINS、各同步路由自己的合法类型集、FILM_SOURCE_TYPES……其中三份
「不采集的类型」名单互相矛盾，导致采集任务会对同步类数据源执行并写下假的成功记录。

现在的规矩:
  - 新增一种数据源类型 = 在 SOURCE_TYPES 里加一条 SourceTypeSpec，外加它的执行器实现。
  - 其它地方一律用本模块的查询函数，不再各自维护名单、不再按字符串前缀判断。
  - COLLECTOR_MAP / SYNC_FETCHERS 在导入时与本表对账，不一致直接启动失败。

本模块是叶子模块：不依赖 SQLAlchemy 模型，任何地方都可以安全导入。
"""

from dataclasses import dataclass
from enum import Enum


class SourceType(str, Enum):
    """数据源类型 —— 纯粹描述信息来源渠道，两段式命名 {Category}.{Specific}"""
    # RSS 类
    RSS_HUB = "rss.hub"
    RSS_STANDARD = "rss.standard"
    # 数据接口
    API_AKSHARE = "api.akshare"
    # 网页抓取
    WEB_SCRAPER = "web.scraper"
    # 文件
    FILE_UPLOAD = "file.upload"
    # 账号授权
    ACCOUNT_GENERIC = "account.generic"
    # 播客
    PODCAST_APPLE = "podcast.apple"
    # 同步
    SYNC_APPLE_BOOKS = "sync.apple_books"
    SYNC_WECHAT_READ = "sync.wechat_read"
    SYNC_BILIBILI = "sync.bilibili"
    SYNC_KINDLE = "sync.kindle"
    SYNC_SAFARI_BOOKMARKS = "sync.safari_bookmarks"
    SYNC_CHROME_BOOKMARKS = "sync.chrome_bookmarks"
    SYNC_DOUBAN_BOOKS = "sync.douban_books"
    SYNC_DOUBAN_MOVIES = "sync.douban_movies"
    SYNC_ZHIHU = "sync.zhihu"
    SYNC_GITHUB_STARS = "sync.github_stars"
    SYNC_TWITTER = "sync.twitter"
    SYNC_EMBY = "sync.emby"
    # 用户记录
    USER_NOTE = "user.note"
    USER_FILM = "user.film"
    SYSTEM_NOTIFICATION = "system.notification"


class SourceCategory(str, Enum):
    """数据源大类"""
    NETWORK = "network"   # 网络数据 —— 由采集器自动采集，内容会过期、按保留期清理
    USER = "user"         # 用户数据 —— 用户/系统主动提交或同步进来的资料，永不自动清理


class ContentKind(str, Enum):
    """内容的领域身份 —— 「这是什么内容」的唯一判定依据

    写入时确定、之后不变。不要再用 source_type、media_type、raw_data 里的键
    去反推一条内容属于哪个领域（2026-09 审计前有 6 种并存的判定方式）。

    两条主线:
      信息流 (stream)  —— 时效性内容，会过期、可清理: ARTICLE / AUDIO
      资料库 (library) —— 用户的长期资产，永不自动清理: 其余全部
    """
    ARTICLE = "article"      # 信息流条目（RSS / 网页抓取 / 账号采集）
    AUDIO = "audio"          # 播客单集
    VIDEO = "video"          # 视频（平台同步 / 手动下载）
    BOOK = "book"            # 电子书
    FILM = "film"            # 影视（电影 / 剧集）
    BOOKMARK = "bookmark"    # 浏览器书签
    NOTE = "note"            # 用户笔记
    FILE = "file"            # 用户上传 / 目录扫描的文件


class Runner(str, Enum):
    """数据怎么进来 —— 决定这个数据源能被谁驱动"""
    COLLECTOR = "collector"  # 采集器：增量追加，可被调度器/「采集」按钮驱动，产出进流水线
    SYNCER = "syncer"        # 内置同步器：全量对账，由同步面板触发，直接写 READY
    PUSH = "push"            # 外部推送：本机脚本 / Fountain 客户端通过 API 写入
    NONE = "none"            # 无执行器：纯归属容器（手工影片、用户笔记）或尚未实现


@dataclass(frozen=True)
class SyncPanel:
    """同步管理面板上的展示信息（有这个才会出现在 /api/sync/status）"""
    name: str
    domain: str              # ebook / video / film —— 面板分组，也是各领域 setup/推送端点的校验依据
    description: str
    sync_mode: str           # internal（Worker 内置同步器）/ script（本机脚本）


@dataclass(frozen=True)
class SourceTypeSpec:
    type: SourceType
    label: str
    category: SourceCategory
    runner: Runner
    kind: ContentKind                 # 该类型数据源产出内容的默认领域
    schedulable: bool = False         # 能否进定时调度（仅对 COLLECTOR 有意义）
    credential_required: bool = False
    accepts_push: bool = False        # 是否同时接受外部推送 API 写入
    domain: str | None = None         # 推送/初始化端点所属领域: ebook / video / bookmark / film
    panel: SyncPanel | None = None
    # 内置同步型：每隔多少分钟自动同步一次。None = 只能手动触发。
    # 只给本机/内网、只读、开销小的来源开（Emby）；远端平台（B站、微信读书）有风控与限流，保持手动
    auto_sync_minutes: int | None = None
    implemented: bool = True          # False = 只占了枚举值，没有任何实现，不允许建源


_N, _U = SourceCategory.NETWORK, SourceCategory.USER
_K = ContentKind

SOURCE_TYPES: dict[str, SourceTypeSpec] = {s.type.value: s for s in [
    # ---- 采集型 ----
    SourceTypeSpec(SourceType.RSS_HUB, "RSSHub", _N, Runner.COLLECTOR, _K.ARTICLE, schedulable=True),
    SourceTypeSpec(SourceType.RSS_STANDARD, "RSS/Atom", _N, Runner.COLLECTOR, _K.ARTICLE, schedulable=True),
    SourceTypeSpec(SourceType.PODCAST_APPLE, "Apple Podcasts", _N, Runner.COLLECTOR, _K.AUDIO, schedulable=True),
    SourceTypeSpec(SourceType.WEB_SCRAPER, "网页抓取", _N, Runner.COLLECTOR, _K.ARTICLE, schedulable=True),
    SourceTypeSpec(SourceType.API_AKSHARE, "AkShare", _N, Runner.COLLECTOR, _K.ARTICLE, schedulable=True),
    SourceTypeSpec(SourceType.ACCOUNT_GENERIC, "通用账号", _N, Runner.COLLECTOR, _K.ARTICLE, schedulable=True),
    # 目录扫描：有采集器，但只能手动触发
    SourceTypeSpec(SourceType.FILE_UPLOAD, "文件上传", _U, Runner.COLLECTOR, _K.FILE),

    # ---- 内置同步型 ----
    SourceTypeSpec(
        SourceType.SYNC_WECHAT_READ, "微信读书", _U, Runner.SYNCER, _K.BOOK,
        credential_required=True, accepts_push=True, domain="ebook",
        panel=SyncPanel("微信读书", "ebook", "从微信读书同步书籍与标注", "internal"),
    ),
    SourceTypeSpec(
        SourceType.SYNC_BILIBILI, "Bilibili", _U, Runner.SYNCER, _K.VIDEO,
        credential_required=True, accepts_push=True, domain="video",
        panel=SyncPanel("Bilibili", "video", "从 B站同步收藏/历史/动态视频", "internal"),
    ),
    SourceTypeSpec(
        SourceType.SYNC_EMBY, "Emby", _U, Runner.SYNCER, _K.FILM,
        credential_required=True, domain="film", auto_sync_minutes=30,
        panel=SyncPanel("Emby", "film", "从 Emby 媒体库同步电影/剧集与观看状态到影视资料库（只读，每 30 分钟自动同步）", "internal"),
    ),

    # ---- 外部推送型 ----
    SourceTypeSpec(
        SourceType.SYNC_APPLE_BOOKS, "Apple Books", _U, Runner.PUSH, _K.BOOK,
        accepts_push=True, domain="ebook",
        panel=SyncPanel("Apple Books", "ebook", "从 macOS Apple Books 同步书籍与标注", "script"),
    ),
    SourceTypeSpec(SourceType.SYNC_KINDLE, "Kindle", _U, Runner.PUSH, _K.BOOK, accepts_push=True, domain="ebook"),
    SourceTypeSpec(SourceType.SYNC_SAFARI_BOOKMARKS, "Safari 书签", _U, Runner.PUSH, _K.BOOKMARK,
                   accepts_push=True, domain="bookmark"),
    SourceTypeSpec(SourceType.SYNC_CHROME_BOOKMARKS, "Chrome 书签", _U, Runner.PUSH, _K.BOOKMARK,
                   accepts_push=True, domain="bookmark"),

    # ---- 无执行器：纯归属容器 ----
    SourceTypeSpec(SourceType.USER_NOTE, "用户笔记", _U, Runner.NONE, _K.NOTE),
    SourceTypeSpec(SourceType.USER_FILM, "手工影片", _U, Runner.NONE, _K.FILM, domain="film"),
    SourceTypeSpec(SourceType.SYSTEM_NOTIFICATION, "系统消息", _U, Runner.NONE, _K.NOTE),

    # ---- 只占了枚举值、尚无任何实现 ----
    SourceTypeSpec(SourceType.SYNC_DOUBAN_BOOKS, "豆瓣书单", _U, Runner.NONE, _K.BOOK, domain="ebook", implemented=False),
    SourceTypeSpec(SourceType.SYNC_DOUBAN_MOVIES, "豆瓣影单", _U, Runner.NONE, _K.FILM, domain="film", implemented=False),
    SourceTypeSpec(SourceType.SYNC_ZHIHU, "知乎收藏", _U, Runner.NONE, _K.ARTICLE, implemented=False),
    SourceTypeSpec(SourceType.SYNC_GITHUB_STARS, "GitHub Star", _U, Runner.NONE, _K.BOOKMARK, implemented=False),
    SourceTypeSpec(SourceType.SYNC_TWITTER, "Twitter/X", _U, Runner.NONE, _K.ARTICLE, implemented=False),
]}

assert set(SOURCE_TYPES) == {t.value for t in SourceType}, "SOURCE_TYPES 必须覆盖 SourceType 的每一个值"


# ============ 查询函数 ============

def get_spec(source_type: str | None) -> SourceTypeSpec | None:
    return SOURCE_TYPES.get(source_type or "")


def get_source_category(source_type: str) -> SourceCategory:
    """未登记的类型按网络数据处理（与历史行为一致）"""
    spec = get_spec(source_type)
    return spec.category if spec else SourceCategory.NETWORK


def default_kind_for_source_type(source_type: str | None) -> ContentKind:
    spec = get_spec(source_type)
    return spec.kind if spec else ContentKind.ARTICLE


def is_collectable(source_type: str | None) -> bool:
    """能不能对它执行「采集」—— 调度器、采集按钮、采集任务共用这一个判定"""
    spec = get_spec(source_type)
    return bool(spec and spec.runner == Runner.COLLECTOR)


def is_schedulable(source_type: str | None) -> bool:
    spec = get_spec(source_type)
    return bool(spec and spec.runner == Runner.COLLECTOR and spec.schedulable)


def types_with_runner(runner: Runner) -> set[str]:
    return {t for t, s in SOURCE_TYPES.items() if s.runner == runner}


def push_types_for_domain(domain: str) -> set[str]:
    """某领域的推送/初始化端点允许的类型（已实现且接受推送）"""
    return {t for t, s in SOURCE_TYPES.items() if s.domain == domain and s.accepts_push and s.implemented}


def auto_sync_specs() -> list[SourceTypeSpec]:
    return [s for s in SOURCE_TYPES.values() if s.runner == Runner.SYNCER and s.auto_sync_minutes]


def sync_panel_plugins() -> list[dict]:
    """同步管理面板的插件清单（/api/sync/status 用），顺序即展示顺序"""
    order = {"ebook": 0, "video": 1, "film": 2}
    specs = [s for s in SOURCE_TYPES.values() if s.panel]
    specs.sort(key=lambda s: (order.get(s.panel.domain, 9), 0 if s.panel.sync_mode == "script" else 1))
    return [
        {
            "source_type": s.type.value,
            "name": s.panel.name,
            "category": s.panel.domain,
            "description": s.panel.description,
            "credential_required": s.credential_required,
            "sync_mode": s.panel.sync_mode,
        }
        for s in specs
    ]
