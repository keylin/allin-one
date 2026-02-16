"""调度配置数据类 + 从 SystemSettings 加载"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

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

    # 采集层立即重试配置
    retry_in_collector_enabled: bool = True
    retry_in_collector_max_attempts: int = 3
    retry_in_collector_delays: str = "30,60"

    # 调度层快速重试配置（暂时性错误）
    retry_transient_intervals: str = "300,900,1800,3600"  # 5min,15min,30min,1h
    retry_transient_max_failures: int = 4

    # 退避策略配置
    backoff_permanent_enabled: bool = True
    backoff_base_interval: int = 3600  # 1小时
    backoff_max_interval: int = 86400  # 24小时


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

    def get_str(key: str, default: str) -> str:
        setting = db.get(SystemSetting, key)
        return setting.value if setting and setting.value else default

    return SchedulingConfig(
        min_interval=get_int("schedule_min_interval", 300),
        max_interval=get_int("schedule_max_interval", 86400),
        base_interval=get_int("schedule_base_interval", 3600),
        lookback_window=get_int("schedule_lookback_window", 10),
        activity_high=get_float("schedule_activity_high", 5.0),
        activity_medium=get_float("schedule_activity_medium", 2.0),
        activity_low=get_float("schedule_activity_low", 0.5),

        # 热点提权
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

        # 周期性识别
        periodicity_enabled=get_bool("periodicity_enabled", True),
        periodicity_min_samples=get_int("periodicity_min_samples", 14),
        periodicity_confidence_threshold=get_float("periodicity_confidence_threshold", 0.7),

        # 时间窗口提权
        window_boost_enabled=get_bool("window_boost_enabled", True),
        window_boost_hourly_factor=get_float("window_boost_hourly_factor", 0.4),
        window_boost_weekly_factor=get_float("window_boost_weekly_factor", 0.6),

        # 采集层立即重试配置
        retry_in_collector_enabled=get_bool("retry_in_collector_enabled", True),
        retry_in_collector_max_attempts=get_int("retry_in_collector_max_attempts", 3),
        retry_in_collector_delays=get_str("retry_in_collector_delays", "30,60"),

        # 调度层快速重试配置（暂时性错误）
        retry_transient_intervals=get_str("retry_transient_intervals", "300,900,1800,3600"),
        retry_transient_max_failures=get_int("retry_transient_max_failures", 4),

        # 退避策略配置
        backoff_permanent_enabled=get_bool("backoff_permanent_enabled", True),
        backoff_base_interval=get_int("backoff_base_interval", 3600),
        backoff_max_interval=get_int("backoff_max_interval", 86400),
    )
