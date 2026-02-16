"""SchedulingService 主类 — 自适应采集间隔计算"""

import logging
from datetime import timedelta
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.services.scheduling.config import SchedulingConfig, load_config
from app.services.scheduling.hotspot import detect_hotspot_level
from app.services.scheduling.periodicity import analyze_periodicity, predict_next_window
from app.services.scheduling.helpers import (
    apply_backoff,
    calculate_backoff_interval,
    calculate_activity_score,
    calculate_success_rate,
    calculate_trend_score,
    smooth_change,
)

logger = logging.getLogger(__name__)


class SchedulingService:
    """智能调度服务"""

    # 静态方法代理：保持向后兼容的 API
    load_config = staticmethod(load_config)
    detect_hotspot_level = staticmethod(detect_hotspot_level)
    analyze_periodicity = staticmethod(analyze_periodicity)
    predict_next_window = staticmethod(predict_next_window)

    # 私有辅助函数也暴露为静态方法（向后兼容）
    _apply_backoff = staticmethod(apply_backoff)
    _calculate_backoff_interval = staticmethod(calculate_backoff_interval)
    _calculate_activity_score = staticmethod(calculate_activity_score)
    _calculate_success_rate = staticmethod(calculate_success_rate)
    _calculate_trend_score = staticmethod(calculate_trend_score)
    _smooth_change = staticmethod(smooth_change)

    @staticmethod
    def calculate_next_interval(source, db: Session) -> int:
        """计算下次采集间隔（秒）

        Args:
            source: SourceConfig 实例
            db: 数据库会话

        Returns:
            下次采集间隔（秒）
        """
        from app.models.content import CollectionRecord

        config = load_config(db)

        # 1. 固定模式：直接返回用户设置的间隔
        if source.schedule_mode == "fixed" and source.schedule_interval_override:
            return source.schedule_interval_override

        # 2. 手动模式：返回最大间隔（实际上不会自动采集）
        if source.schedule_mode == "manual":
            return config.max_interval

        # 3. 自动模式（智能调度）
        # 获取最近N次采集记录
        recent_records = db.query(CollectionRecord).filter(
            CollectionRecord.source_id == source.id,
            CollectionRecord.status.in_(["completed", "failed"])
        ).order_by(desc(CollectionRecord.started_at)).limit(config.lookback_window).all()

        # 新源处理：少于3条记录时使用基础间隔
        if len(recent_records) < 3:
            interval = apply_backoff(config.base_interval, source.consecutive_failures, config)
            logger.debug(f"Source {source.id} ({source.name}): new source, using base interval {interval}s")
            return interval

        # 失败退避优先（优先级最高）
        if source.consecutive_failures > 0:
            # 查询最近一次失败记录，提取错误类型
            latest_failure = db.query(CollectionRecord).filter(
                CollectionRecord.source_id == source.id,
                CollectionRecord.status == "failed"
            ).order_by(desc(CollectionRecord.started_at)).first()

            error_type = "unknown"
            if latest_failure and latest_failure.error_message:
                # 从 error_message 前缀提取错误类型
                msg = latest_failure.error_message
                if msg.startswith("[TRANSIENT]"):
                    error_type = "transient"
                elif msg.startswith("[PERMANENT]"):
                    error_type = "permanent"

            # 使用新的分级退避算法
            interval = calculate_backoff_interval(
                source.consecutive_failures,
                error_type,
                config
            )
            logger.debug(
                f"Source {source.id} ({source.name}): backoff mode, "
                f"error_type={error_type}, interval={interval}s (failures={source.consecutive_failures})"
            )
            return interval

        # ✨ 热点检测（优先级高于常规评分）
        if config.hotspot_enabled:
            hotspot_level = detect_hotspot_level(source, recent_records, config)
            if hotspot_level:
                # 应用分级因子
                factor_map = {
                    "extreme": config.hotspot_extreme_factor,    # 0.1
                    "high": config.hotspot_high_factor,          # 0.2
                    "instant": config.hotspot_instant_factor,    # 0.3
                }
                hotspot_factor = factor_map[hotspot_level]

                # 可靠性因子仍然生效（避免对不稳定源过度提权）
                success_rate = calculate_success_rate(recent_records)
                if success_rate < 0.5:
                    reliability_factor = 1.5
                elif success_rate >= 0.9:
                    reliability_factor = 0.9
                else:
                    reliability_factor = 1.0

                raw_interval = config.base_interval * hotspot_factor * reliability_factor

                # 边界约束
                final_interval = max(config.min_interval, min(raw_interval, config.max_interval))

                # 缓存热点状态
                source.hotspot_level = hotspot_level
                source.hotspot_detected_at = utcnow()

                logger.info(
                    f"Hotspot {hotspot_level}: {source.name}, "
                    f"factor={hotspot_factor}, interval={int(final_interval)}s"
                )
                return int(final_interval)
            else:
                # 退出热点模式，清理缓存
                if source.hotspot_level:
                    source.hotspot_level = None
                    source.hotspot_detected_at = None
                    logger.info(f"Hotspot exit: {source.name}")

        # 计算多维度评分
        activity_score = calculate_activity_score(recent_records, config)
        success_rate = calculate_success_rate(recent_records)
        trend_score = calculate_trend_score(recent_records)

        # 分段映射：活跃度因子
        if activity_score >= config.activity_high:
            activity_factor = 0.5  # 高活跃：缩短到50%
        elif activity_score >= config.activity_medium:
            activity_factor = 0.75  # 中活跃：缩短到75%
        elif activity_score < config.activity_low:
            activity_factor = 1.5  # 低活跃：延长到150%
        else:
            activity_factor = 1.0  # 正常

        # 可靠性因子
        if success_rate < 0.5:
            reliability_factor = 1.5  # 低成功率：延长间隔
        elif success_rate >= 0.9:
            reliability_factor = 0.9  # 高成功率：略微缩短
        else:
            reliability_factor = 1.0  # 正常

        # 趋势因子
        if trend_score > 0.3:
            trend_factor = 0.8  # 上升趋势：提权
        elif trend_score < -0.3:
            trend_factor = 1.2  # 下降趋势：降权
        else:
            trend_factor = 1.0  # 正常

        # 综合计算
        raw_interval = config.base_interval * activity_factor * reliability_factor * trend_factor

        # ✨ 时间窗口提权
        window_boost_applied = False
        if config.window_boost_enabled and source.periodicity_data:
            window = predict_next_window(source, utcnow())
            if window and window[0] <= utcnow() <= window[1]:
                raw_interval *= window[2]
                window_boost_applied = True
                logger.debug(f"Window boost: {source.name}, factor={window[2]}")

        # 边界约束
        final_interval = max(config.min_interval, min(raw_interval, config.max_interval))

        # 平滑处理：单次调整幅度不超过±50%
        if source.calculated_interval and source.calculated_interval > 0:
            final_interval = smooth_change(
                final_interval,
                source.calculated_interval,
                max_change_ratio=0.5
            )

        logger.debug(
            f"Source {source.id} ({source.name}): "
            f"activity={activity_score:.2f} (factor={activity_factor:.2f}), "
            f"success={success_rate:.2f} (factor={reliability_factor:.2f}), "
            f"trend={trend_score:.2f} (factor={trend_factor:.2f}), "
            f"window_boost={window_boost_applied}, "
            f"interval={int(final_interval)}s"
        )

        return int(final_interval)

    @staticmethod
    def should_collect_now(source, now=None) -> bool:
        """判断数据源是否应该在当前时刻采集

        Args:
            source: SourceConfig 实例
            now: 当前时间（可选，默认使用 utcnow()）

        Returns:
            是否应该采集
        """
        if now is None:
            now = utcnow()

        # 未启用或未激活
        if not source.is_active or not source.schedule_enabled:
            return False

        # 手动模式：不自动采集
        if source.schedule_mode == "manual":
            return False

        # 从未采集过：立即采集
        if source.next_collection_at is None:
            return True

        # 检查是否到达下次采集时间
        return now >= source.next_collection_at

    @staticmethod
    def update_next_collection_time(source, db: Session) -> None:
        """采集完成后更新下次采集时间

        Args:
            source: SourceConfig 实例（需要已经更新 consecutive_failures）
            db: 数据库会话
        """
        now = utcnow()

        # 计算下次采集间隔
        interval = SchedulingService.calculate_next_interval(source, db)

        # 更新数据库
        source.calculated_interval = interval
        source.next_collection_at = now + timedelta(seconds=interval)

        logger.info(
            f"Updated schedule for {source.name}: "
            f"next_at={source.next_collection_at.isoformat()}, "
            f"interval={interval}s, "
            f"mode={source.schedule_mode}"
        )
