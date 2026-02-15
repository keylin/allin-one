"""采集服务 — 调度分发"""

import logging

import httpx
from sqlalchemy.orm import Session
from app.core.time import utcnow
from app.models.content import SourceConfig, ContentItem, CollectionRecord
from app.services.collectors.rss import RSSCollector
from app.services.collectors.web_scraper import ScraperCollector
from app.services.collectors.akshare import AkShareCollector
from app.services.collectors.file_upload import FileUploadCollector
from app.services.collectors.bilibili import BilibiliCollector
from app.services.collectors.generic_account import GenericAccountCollector

logger = logging.getLogger(__name__)


def classify_error(exception: Exception) -> str:
    """根据异常类型分类错误为暂时性或持续性

    Args:
        exception: 采集过程中捕获的异常

    Returns:
        "transient" 表示暂时性错误（应快速重试）
        "permanent" 表示持续性错误（应立即退避）
    """
    # HTTP 状态错误
    if isinstance(exception, httpx.HTTPStatusError):
        status_code = exception.response.status_code

        # 暂时性：服务端临时错误、限流、超时
        if status_code in (408, 429, 502, 503, 504) or status_code >= 500:
            return "transient"

        # 持续性：客户端错误（资源不存在、权限拒绝等）
        if status_code in (400, 401, 403, 404, 410):
            return "permanent"

    # 网络连接错误（暂时性）
    if isinstance(exception, (httpx.ConnectError, httpx.TimeoutException)):
        return "transient"

    # 数据库并发冲突（暂时性）
    from sqlalchemy.exc import OperationalError
    if isinstance(exception, OperationalError):
        return "transient"

    # 解析错误（持续性：feed 格式问题不会自愈）
    if isinstance(exception, (ValueError, KeyError)):
        return "permanent"

    # 配置/代码错误（持续性）
    if isinstance(exception, (AttributeError, TypeError)):
        return "permanent"

    # 未知错误默认为暂时性（保守策略）
    return "transient"


_rss_collector = RSSCollector()
_scraper_collector = ScraperCollector()
_akshare_collector = AkShareCollector()
_file_upload_collector = FileUploadCollector()
_bilibili_collector = BilibiliCollector()
_generic_account_collector = GenericAccountCollector()

COLLECTOR_MAP = {
    "rss.hub": _rss_collector,
    "rss.standard": _rss_collector,
    "web.scraper": _scraper_collector,
    "api.akshare": _akshare_collector,
    "file.upload": _file_upload_collector,
    "account.bilibili": _bilibili_collector,
    "account.generic": _generic_account_collector,
}

_UNIMPLEMENTED_TYPES = {
    "user.note", "system.notification",
}


async def collect_with_retry(collector, source: SourceConfig, db: Session, config: dict) -> list[ContentItem]:
    """采集层立即重试包装

    Args:
        collector: 采集器实例
        source: 数据源配置
        db: 数据库会话
        config: 重试配置字典 {enabled, max_attempts, delays}

    Returns:
        新采集的 ContentItem 列表

    Raises:
        捕获的最后一次异常（重试耗尽或持续性错误）
    """
    if not config.get("enabled", True):
        # 采集层重试禁用，直接调用
        return await collector.collect(source, db)

    max_attempts = config.get("max_attempts", 3)
    delays = config.get("delays", [30, 60])  # 默认 30s, 60s

    last_exception = None

    for attempt in range(max_attempts):
        try:
            return await collector.collect(source, db)
        except Exception as e:
            last_exception = e
            error_type = classify_error(e)

            # 持续性错误：立即抛出，不重试
            if error_type == "permanent":
                logger.info(
                    f"[retry] {source.name}: PERMANENT error, no retry. "
                    f"{type(e).__name__}: {str(e)[:200]}"
                )
                raise

            # 暂时性错误：记录并准备重试
            if attempt < max_attempts - 1:
                delay = delays[attempt] if attempt < len(delays) else delays[-1]
                logger.info(
                    f"[retry] {source.name}: TRANSIENT error (attempt {attempt + 1}/{max_attempts}), "
                    f"retrying in {delay}s. {type(e).__name__}: {str(e)[:200]}"
                )

                import asyncio
                await asyncio.sleep(delay)
            else:
                # 重试耗尽
                logger.warning(
                    f"[retry] {source.name}: TRANSIENT error, max retries exhausted. "
                    f"{type(e).__name__}: {str(e)[:200]}"
                )

    # 所有重试都失败，抛出最后一次异常
    raise last_exception


async def collect_source_with_retry(source: SourceConfig, db: Session) -> list[ContentItem]:
    """带重试机制的数据源采集（对外接口）

    创建 CollectionRecord，调用采集器，更新记录状态。
    失败时不设置 error_message（由调度层统一设置错误类型前缀）。

    Args:
        source: 数据源配置
        db: 数据库会话

    Returns:
        新采集的 ContentItem 列表

    Raises:
        采集失败时抛出异常（调度层负责捕获和处理）
    """
    from app.models.system_setting import SystemSetting

    # 加载重试配置
    def get_setting(key: str, default: str) -> str:
        setting = db.get(SystemSetting, key)
        return setting.value if setting and setting.value else default

    retry_config = {
        "enabled": get_setting("retry_in_collector_enabled", "true").lower() in ("true", "1", "yes"),
        "max_attempts": int(get_setting("retry_in_collector_max_attempts", "3")),
        "delays": [int(d) for d in get_setting("retry_in_collector_delays", "30,60").split(",")],
    }

    # 创建采集记录
    record = CollectionRecord(
        source_id=source.id,
        status="running",
    )
    db.add(record)
    db.flush()

    try:
        collector = COLLECTOR_MAP.get(source.source_type)

        if not collector:
            if source.source_type in _UNIMPLEMENTED_TYPES:
                logger.warning(f"[collect] Collector not implemented for {source.source_type}, skipping")
            else:
                logger.error(f"[collect] Unknown source_type: {source.source_type}")
            record.status = "completed"
            record.items_found = 0
            record.items_new = 0
            record.completed_at = utcnow()
            db.commit()
            return []

        # 调用带重试的采集
        new_items = await collect_with_retry(collector, source, db, retry_config)

        # 成功：更新记录
        record.status = "completed"
        record.items_found = len(new_items)
        record.items_new = len(new_items)
        record.completed_at = utcnow()
        db.commit()

        logger.info(f"[collect] {source.name}: found {len(new_items)} new items")
        return new_items

    except Exception as e:
        # 失败：更新记录状态，但不设置 error_message
        # error_message 由调度层统一设置（带错误类型前缀）
        record.status = "failed"
        record.completed_at = utcnow()
        db.commit()

        # 根据错误类型选择日志级别
        if isinstance(e, (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)):
            logger.warning(f"[collect] {source.name}: {type(e).__name__}: {str(e) or repr(e)}")
        else:
            logger.exception(f"[collect] Failed for {source.name}: {e}")
        raise


async def collect_source(source: SourceConfig, db: Session) -> list[ContentItem]:
    """按 source_type 选择 collector 执行采集，创建 CollectionRecord"""
    record = CollectionRecord(
        source_id=source.id,
        status="running",
    )
    db.add(record)
    db.flush()

    try:
        collector = COLLECTOR_MAP.get(source.source_type)

        if not collector:
            if source.source_type in _UNIMPLEMENTED_TYPES:
                logger.warning(f"[collect] Collector not implemented for {source.source_type}, skipping")
            else:
                logger.error(f"[collect] Unknown source_type: {source.source_type}")
            record.status = "completed"
            record.items_found = 0
            record.items_new = 0
            record.completed_at = utcnow()
            db.commit()
            return []

        new_items = await collector.collect(source, db)

        record.status = "completed"
        record.items_found = len(new_items)
        record.items_new = len(new_items)
        record.completed_at = utcnow()
        db.commit()

        logger.info(f"[collect] {source.name}: found {len(new_items)} new items")
        return new_items

    except Exception as e:
        record.status = "failed"
        record.error_message = str(e)[:500]
        record.completed_at = utcnow()
        db.commit()

        # 暂时性网络/上游错误只记 WARNING，不打堆栈
        if isinstance(e, (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)):
            logger.warning(f"[collect] {source.name}: {type(e).__name__}: {str(e) or repr(e)}")
        else:
            logger.exception(f"[collect] Failed for {source.name}: {e}")
        raise
