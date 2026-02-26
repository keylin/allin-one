"""同步服务 — Fetcher 注册表 + 共享 upsert 逻辑"""

from app.services.sync.bilibili import BilibiliFetcher
from app.services.sync.wechat_read import WechatReadFetcher

# source_type → Fetcher 类映射
SYNC_FETCHERS: dict[str, type] = {
    "sync.bilibili": BilibiliFetcher,
    "sync.wechat_read": WechatReadFetcher,
}
