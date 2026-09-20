"""同步服务 — Fetcher 注册表 + 共享 upsert 逻辑"""

from app.services.sync.bilibili import BilibiliFetcher
from app.services.sync.emby import EmbyFetcher
from app.services.sync.wechat_read import WechatReadFetcher

# source_type → Fetcher 类映射
SYNC_FETCHERS: dict[str, type] = {
    "sync.bilibili": BilibiliFetcher,
    "sync.wechat_read": WechatReadFetcher,
    "sync.emby": EmbyFetcher,
}

# 与源类型注册表对账：内置同步器清单必须恰好等于 runner=syncer 的类型
from app.models.source_types import Runner, types_with_runner  # noqa: E402

assert set(SYNC_FETCHERS) == types_with_runner(Runner.SYNCER), (
    f"SYNC_FETCHERS 与源类型注册表不一致: {set(SYNC_FETCHERS) ^ types_with_runner(Runner.SYNCER)}"
)
