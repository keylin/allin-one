"""智能调度服务 — 基于历史数据的自适应采集间隔计算

核心算法：多维度自适应调度
- 新增率（Activity Score）：最近N次采集的平均 items_new，时间衰减权重
- 成功率（Reliability Score）：窗口内的 completed 占比
- 趋势分析（Trend Score）：items_new 时间序列线性回归斜率
- 退避策略：连续失败时指数延长间隔（优先级最高）

边界约束：
- min_interval: 最小采集间隔（默认300秒，防止过度抓取）
- max_interval: 最大采集间隔（默认86400秒，确保每天至少检查一次）
- base_interval: 基础间隔（默认3600秒，用于新源和中等活跃源）
"""

import logging
import json
from datetime import timedelta
from typing import Optional
from dataclasses import dataclass
from collections import Counter

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.time import utcnow

logger = logging.getLogger(__name__)


@dataclass
class SchedulingConfig:
    """调度配置参数"""
    min_interval: int = 300           # 5分钟
    max_interval: int = 86400         # 24小时
    base_interval: int = 3600         # 1小时
    lookback_window: int = 10         # 统计最近N次采集
    activity_high: float = 5.0        # 高活跃阈值
    activity_medium: float = 2.0      # 中活跃阈值
    activity_low: float = 0.5         # 低活跃阈值

    # 热点提权（激进响应机制）
    hotspot_enabled: bool = True
    hotspot_instant_factor: float = 0.3
    hotspot_high_factor: float = 0.2
    hotspot_extreme_factor: float = 0.1
    hotspot_instant_threshold: int = 5
    hotspot_high_threshold: int = 8
    hotspot_extreme_threshold: int = 10
    hotspot_surge_multiplier_2x: float = 2.0
    hotspot_surge_multiplier_3x: float = 3.0
    hotspot_history_days: int = 7
    max_hotspot_sources: int = 5

    # 周期性识别
    periodicity_enabled: bool = True
    periodicity_min_samples: int = 14
    periodicity_confidence_threshold: float = 0.7

    # 时间窗口提权
    window_boost_enabled: bool = True
    window_boost_hourly_factor: float = 0.4
    window_boost_weekly_factor: float = 0.6


class SchedulingService:
    """智能调度服务"""

    @staticmethod
    def load_config(db: Session) -> SchedulingConfig:
        """从 SystemSettings 加载调度配置"""
        from app.models.system_setting import SystemSetting

        def get_int(key: str, default: int) -> int:
            setting = db.get(SystemSetting, key)
            if setting and setting.value:
                try:
                    return int(setting.value)
                except ValueError:
                    logger.warning(f"Invalid setting {key}={setting.value}, using default {default}")
            return default

        def get_float(key: str, default: float) -> float:
            setting = db.get(SystemSetting, key)
            if setting and setting.value:
                try:
                    return float(setting.value)
                except ValueError:
                    logger.warning(f"Invalid setting {key}={setting.value}, using default {default}")
            return default

        def get_bool(key: str, default: bool) -> bool:
            setting = db.get(SystemSetting, key)
            if setting and setting.value:
                return setting.value.lower() in ('true', '1', 'yes')
            return default

        return SchedulingConfig(
            min_interval=get_int("schedule_min_interval", 300),
            max_interval=get_int("schedule_max_interval", 86400),
            base_interval=get_int("schedule_base_interval", 3600),
            lookback_window=get_int("schedule_lookback_window", 10),
            activity_high=get_float("schedule_activity_high", 5.0),
            activity_medium=get_float("schedule_activity_medium", 2.0),
            activity_low=get_float("schedule_activity_low", 0.5),

            # 热点提权（新增）
            hotspot_enabled=get_bool("hotspot_enabled", True),
            hotspot_instant_factor=get_float("hotspot_instant_factor", 0.3),
            hotspot_high_factor=get_float("hotspot_high_factor", 0.2),
            hotspot_extreme_factor=get_float("hotspot_extreme_factor", 0.1),
            hotspot_instant_threshold=get_int("hotspot_instant_threshold", 5),
            hotspot_high_threshold=get_int("hotspot_high_threshold", 8),
            hotspot_extreme_threshold=get_int("hotspot_extreme_threshold", 10),
            hotspot_surge_multiplier_2x=get_float("hotspot_surge_multiplier_2x", 2.0),
            hotspot_surge_multiplier_3x=get_float("hotspot_surge_multiplier_3x", 3.0),
            hotspot_history_days=get_int("hotspot_history_days", 7),
            max_hotspot_sources=get_int("max_hotspot_sources", 5),

            # 周期性识别（新增）
            periodicity_enabled=get_bool("periodicity_enabled", True),
            periodicity_min_samples=get_int("periodicity_min_samples", 14),
            periodicity_confidence_threshold=get_float("periodicity_confidence_threshold", 0.7),

            # 时间窗口提权（新增）
            window_boost_enabled=get_bool("window_boost_enabled", True),
            window_boost_hourly_factor=get_float("window_boost_hourly_factor", 0.4),
            window_boost_weekly_factor=get_float("window_boost_weekly_factor", 0.6),
        )

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

        config = SchedulingService.load_config(db)

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
            interval = SchedulingService._apply_backoff(config.base_interval, source.consecutive_failures, config)
            logger.debug(f"Source {source.id} ({source.name}): new source, using base interval {interval}s")
            return interval

        # 失败退避优先（优先级最高）
        if source.consecutive_failures > 0:
            interval = SchedulingService._apply_backoff(config.base_interval, source.consecutive_failures, config)
            logger.debug(f"Source {source.id} ({source.name}): backoff mode, interval={interval}s (failures={source.consecutive_failures})")
            return interval

        # ✨ 热点检测（优先级高于常规评分）
        if config.hotspot_enabled:
            hotspot_level = SchedulingService.detect_hotspot_level(source, recent_records, config)
            if hotspot_level:
                # 应用分级因子
                factor_map = {
                    "extreme": config.hotspot_extreme_factor,    # 0.1
                    "high": config.hotspot_high_factor,          # 0.2
                    "instant": config.hotspot_instant_factor,    # 0.3
                }
                hotspot_factor = factor_map[hotspot_level]

                # 可靠性因子仍然生效（避免对不稳定源过度提权）
                success_rate = SchedulingService._calculate_success_rate(recent_records)
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
        activity_score = SchedulingService._calculate_activity_score(recent_records, config)
        success_rate = SchedulingService._calculate_success_rate(recent_records)
        trend_score = SchedulingService._calculate_trend_score(recent_records)

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
            window = SchedulingService.predict_next_window(source, utcnow())
            if window and window[0] <= utcnow() <= window[1]:
                raw_interval *= window[2]
                window_boost_applied = True
                logger.debug(f"Window boost: {source.name}, factor={window[2]}")

        # 边界约束
        final_interval = max(config.min_interval, min(raw_interval, config.max_interval))

        # 平滑处理：单次调整幅度不超过±50%
        if source.calculated_interval and source.calculated_interval > 0:
            final_interval = SchedulingService._smooth_change(
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

    # ========== 辅助函数 ==========

    @staticmethod
    def _apply_backoff(base_interval: int, consecutive_failures: int, config: SchedulingConfig) -> int:
        """应用退避策略：2^n 指数延长"""
        if consecutive_failures <= 0:
            return base_interval

        backoff_interval = base_interval * (2 ** consecutive_failures)
        return min(backoff_interval, config.max_interval)

    @staticmethod
    def detect_hotspot_level(source, recent_records: list, config: SchedulingConfig) -> Optional[str]:
        """检测热点等级 — 激进提权 + 温和降级

        策略：
        - 首次触发直接到对应等级（极端响应）
        - 内容量足够时保持等级
        - 内容量下降时温和降级（不会因单次波动退出）
        - 失败或连续2次空内容立即退出

        Args:
            source: SourceConfig 实例
            recent_records: 最近N次 CollectionRecord（已按 started_at DESC 排序）
            config: 调度配置

        Returns:
            "extreme" | "high" | "instant" | None
        """
        if not recent_records:
            return None

        # 获取最新采集记录
        latest = recent_records[0]
        if latest.status != "completed":
            # 失败时立即退出热点模式
            return None

        current_level = source.hotspot_level
        items = latest.items_new

        # === 计算历史均值（用于相对突增判定） ===
        completed = [r for r in recent_records[1:] if r.status == "completed"][:config.hotspot_history_days]
        avg_items = 0.0
        if len(completed) >= 3:
            avg_items = sum(r.items_new for r in completed) / len(completed)

        # === 特殊退出：连续2次为0 ===
        if items == 0:
            prev = next((r for r in recent_records[1:] if r.status == "completed"), None)
            if prev and prev.items_new == 0:
                return None  # 连续2次空内容，退出热点

        # === 激进提权：首次触发直接到对应等级 ===
        if current_level is None:
            # 优先级从高到低判定
            if items >= config.hotspot_extreme_threshold:  # 默认10
                return "extreme"  # 直接极端！

            elif items >= config.hotspot_high_threshold:  # 默认8
                return "high"  # 直接高度！

            elif avg_items > 0 and items >= avg_items * config.hotspot_surge_multiplier_3x and items >= 8:
                return "high"  # 相对突增3倍 → 高度

            elif items >= config.hotspot_instant_threshold:  # 默认5
                return "instant"  # 即时

            elif avg_items > 0 and items >= avg_items * config.hotspot_surge_multiplier_2x and items >= 5:
                return "instant"  # 相对突增2倍 → 即时

            else:
                return None  # 未达到任何提权阈值

        # === 已在热点模式，检查保持、升级或降级 ===

        if current_level == "extreme":
            # 保持：items_new ≥ 10
            if items >= 10:
                return "extreme"
            # 温和降级：8-9
            elif items >= 8:
                return "high"
            # 跨级降级：5-7
            elif items >= 5:
                return "instant"
            # 快速降级：< 5（但不直接退出）
            else:
                return "instant"

        elif current_level == "high":
            # 尝试升级到 extreme
            if items >= 10:
                return "extreme"
            # 保持：items_new ≥ 8
            elif items >= 8:
                return "high"
            # 温和降级：5-7
            elif items >= 5:
                return "instant"
            # 退出热点：< 5
            else:
                return None

        else:  # current_level == "instant"
            # 尝试升级
            if items >= 10:
                return "extreme"
            elif items >= 8:
                return "high"
            # 保持：items_new ≥ 5
            elif items >= 5:
                return "instant"
            # 退出热点：< 5
            else:
                return None

    @staticmethod
    def analyze_periodicity(source, db: Session) -> dict:
        """分析数据源的更新周期性模式

        通过统计成功采集记录的时间分布，识别 hourly/daily/weekly 更新模式

        Args:
            source: SourceConfig 实例
            db: 数据库会话

        Returns:
            {
                "pattern_type": "hourly" | "daily" | "weekly" | "none",
                "peak_hours": [9, 10],        # hourly 模式时存在
                "peak_days": [0, 1],          # weekly 模式时存在（0=周一）
                "confidence": 0.85,
                "window_minutes": 60,         # 窗口宽度
            }
        """
        from app.models.content import CollectionRecord

        config = SchedulingService.load_config(db)

        # 1. 查询成功记录（items_new > 0）
        records = db.query(CollectionRecord).filter(
            CollectionRecord.source_id == source.id,
            CollectionRecord.status == "completed",
            CollectionRecord.items_new > 0
        ).order_by(desc(CollectionRecord.started_at)).limit(100).all()

        if len(records) < config.periodicity_min_samples:
            return {
                "pattern_type": "none",
                "confidence": 0.0,
                "window_minutes": 0
            }

        # 2. 提取时间特征
        hours = []
        weekdays = []
        for record in records:
            if record.started_at:
                hours.append(record.started_at.hour)
                weekdays.append(record.started_at.weekday())

        # 3. 统计分布
        hour_dist = Counter(hours)
        weekday_dist = Counter(weekdays)

        total_records = len(records)

        # 4. 识别 hourly 模式（某小时占比 > 40%）
        if hour_dist:
            max_hour_count = max(hour_dist.values())
            max_hour_ratio = max_hour_count / total_records

            if max_hour_ratio > 0.4:
                # 找出高峰小时（占比超过20%）
                peak_hours = sorted([h for h, count in hour_dist.items() if count / total_records > 0.2])

                # 计算置信度（基于最高峰值占比）
                confidence = min(max_hour_ratio, 0.95)

                return {
                    "pattern_type": "hourly",
                    "peak_hours": peak_hours,
                    "confidence": round(confidence, 2),
                    "window_minutes": 60
                }

        # 5. 识别 weekly 模式（某星期占比 > 50%）
        if weekday_dist:
            max_weekday_count = max(weekday_dist.values())
            max_weekday_ratio = max_weekday_count / total_records

            if max_weekday_ratio > 0.5:
                # 找出高峰日（占比超过30%）
                peak_days = sorted([d for d, count in weekday_dist.items() if count / total_records > 0.3])

                # 计算置信度
                confidence = min(max_weekday_ratio, 0.95)

                return {
                    "pattern_type": "weekly",
                    "peak_days": peak_days,
                    "confidence": round(confidence, 2),
                    "window_minutes": 1440  # 全天
                }

        # 6. 识别 daily 模式（分布相对均匀）
        # 如果小时分布和星期分布都比较均匀，但有规律地每天至少1次
        hour_variety = len(hour_dist)
        if hour_variety >= 8:  # 至少8个不同小时有记录
            return {
                "pattern_type": "daily",
                "confidence": 0.7,
                "window_minutes": 360  # 6小时窗口
            }

        # 7. 无显著规律
        return {
            "pattern_type": "none",
            "confidence": 0.0,
            "window_minutes": 0
        }

    @staticmethod
    def predict_next_window(source, now) -> Optional[tuple]:
        """预测下一个更新时间窗口

        Args:
            source: SourceConfig 实例
            now: 当前时间（naive UTC datetime）

        Returns:
            (window_start, window_end, boost_factor) 或 None
        """
        if not source.periodicity_data:
            return None

        try:
            periodicity = json.loads(source.periodicity_data)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Invalid periodicity_data for {source.name}")
            return None

        pattern_type = periodicity.get("pattern_type")
        if pattern_type == "none":
            return None

        config = SchedulingConfig()  # 使用默认值，或从外部传入

        # hourly 模式
        if pattern_type == "hourly":
            peak_hours = periodicity.get("peak_hours", [])
            if not peak_hours:
                return None

            # 找到下一个 peak_hour
            current_hour = now.hour
            next_peak_hour = None

            for hour in sorted(peak_hours):
                if hour > current_hour:
                    next_peak_hour = hour
                    break

            # 如果今天没有了，取明天的第一个
            if next_peak_hour is None:
                next_peak_hour = peak_hours[0]
                # 窗口在明天
                window_start = now.replace(hour=next_peak_hour, minute=0, second=0, microsecond=0) + timedelta(days=1)
            else:
                window_start = now.replace(hour=next_peak_hour, minute=0, second=0, microsecond=0)

            # 窗口: [peak_hour - 30min, peak_hour + 60min]
            window_start = window_start - timedelta(minutes=30)
            window_end = window_start + timedelta(minutes=90)  # 90分钟窗口

            return (window_start, window_end, config.window_boost_hourly_factor)

        # weekly 模式
        elif pattern_type == "weekly":
            peak_days = periodicity.get("peak_days", [])
            if not peak_days:
                return None

            # 找到下一个 peak_day
            current_weekday = now.weekday()
            next_peak_day = None

            for day in sorted(peak_days):
                if day > current_weekday:
                    next_peak_day = day
                    break

            # 如果本周没有了，取下周的第一个
            if next_peak_day is None:
                next_peak_day = peak_days[0]
                days_ahead = (7 - current_weekday) + next_peak_day
            else:
                days_ahead = next_peak_day - current_weekday

            # 窗口：整个peak_day
            window_start = (now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
            window_end = window_start + timedelta(hours=24)

            return (window_start, window_end, config.window_boost_weekly_factor)

        # daily 模式：不应用时间窗口提权
        else:
            return None

    @staticmethod
    def _calculate_activity_score(records: list, config: SchedulingConfig) -> float:
        """计算活跃度评分：加权平均 items_new

        最近3次占70%，其余占30%（时间衰减）
        """
        if not records:
            return 0.0

        # 只统计成功的采集
        completed_records = [r for r in records if r.status == "completed"]
        if not completed_records:
            return 0.0

        total = len(completed_records)

        # 最近3次
        recent_3 = completed_records[:min(3, total)]
        recent_avg = sum(r.items_new for r in recent_3) / len(recent_3)

        # 其余
        if total > 3:
            older = completed_records[3:]
            older_avg = sum(r.items_new for r in older) / len(older)
            # 加权平均：70% 最近 + 30% 历史
            return recent_avg * 0.7 + older_avg * 0.3
        else:
            return recent_avg

    @staticmethod
    def _calculate_success_rate(records: list) -> float:
        """计算成功率：completed 占比"""
        if not records:
            return 1.0  # 无历史时假设成功

        completed = sum(1 for r in records if r.status == "completed")
        return completed / len(records)

    @staticmethod
    def _calculate_trend_score(records: list) -> float:
        """计算趋势评分：items_new 线性回归斜率

        返回归一化斜率：
        - 正值表示上升趋势
        - 负值表示下降趋势
        - 接近0表示平稳
        """
        if len(records) < 3:
            return 0.0

        # 只统计成功的采集
        completed_records = [r for r in records if r.status == "completed"]
        if len(completed_records) < 3:
            return 0.0

        # 按时间顺序（最旧的在前）
        sorted_records = sorted(completed_records, key=lambda r: r.started_at)

        # 简单线性回归：y = ax + b
        n = len(sorted_records)
        x_values = list(range(n))  # 时间序号：0, 1, 2, ...
        y_values = [r.items_new for r in sorted_records]

        x_mean = sum(x_values) / n
        y_mean = sum(y_values) / n

        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
        denominator = sum((x - x_mean) ** 2 for x in x_values)

        if denominator == 0:
            return 0.0

        slope = numerator / denominator

        # 归一化：除以 y_mean，避免绝对值影响
        if y_mean > 0:
            normalized_slope = slope / y_mean
        else:
            normalized_slope = 0.0

        # 限制范围 [-1, 1]
        return max(-1.0, min(1.0, normalized_slope))

    @staticmethod
    def _smooth_change(new_value: float, old_value: float, max_change_ratio: float = 0.5) -> float:
        """平滑调整：单次变化幅度不超过 max_change_ratio

        Args:
            new_value: 新计算的值
            old_value: 旧值
            max_change_ratio: 最大变化比例（0.5 = ±50%）

        Returns:
            平滑后的值
        """
        if old_value <= 0:
            return new_value

        change_ratio = (new_value - old_value) / old_value

        if change_ratio > max_change_ratio:
            return old_value * (1 + max_change_ratio)
        elif change_ratio < -max_change_ratio:
            return old_value * (1 - max_change_ratio)
        else:
            return new_value
