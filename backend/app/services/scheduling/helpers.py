"""调度辅助计算函数"""

import logging

from app.services.scheduling.config import SchedulingConfig

logger = logging.getLogger(__name__)


def apply_backoff(base_interval: int, consecutive_failures: int, config: SchedulingConfig) -> int:
    """应用退避策略：2^n 指数延长（遗留方法，保留向后兼容）"""
    if consecutive_failures <= 0:
        return base_interval

    backoff_interval = base_interval * (2 ** consecutive_failures)
    return min(backoff_interval, config.max_interval)


def calculate_backoff_interval(consecutive_failures: int, error_type: str, config: SchedulingConfig) -> int:
    """根据错误类型计算退避间隔

    Args:
        consecutive_failures: 连续失败次数
        error_type: 错误类型 ("transient", "permanent", 或其他)
        config: 调度配置

    Returns:
        下次采集间隔（秒）
    """
    if consecutive_failures <= 0:
        return config.base_interval

    # 暂时性错误：快速重试
    if error_type == "transient":
        # 解析固定间隔序列
        try:
            intervals = [int(x) for x in config.retry_transient_intervals.split(",")]
        except (ValueError, AttributeError):
            intervals = [300, 900, 1800, 3600]  # 默认：5min,15min,30min,1h

        max_failures = config.retry_transient_max_failures

        # 前 N 次使用固定间隔
        if consecutive_failures <= len(intervals):
            interval = intervals[consecutive_failures - 1]
        elif consecutive_failures <= max_failures:
            # 最后一个固定间隔之后，继续使用最后一个值
            interval = intervals[-1]
        else:
            # 超过阈值，进入指数退避
            failures_beyond = consecutive_failures - max_failures
            base = config.backoff_base_interval
            interval = base * (2 ** failures_beyond)

        return min(interval, config.backoff_max_interval)

    # 持续性错误：立即激进退避
    elif error_type == "permanent":
        if not config.backoff_permanent_enabled:
            # 禁用持续性错误退避，使用标准策略
            return apply_backoff(config.base_interval, consecutive_failures, config)

        base = config.backoff_base_interval
        interval = base * (2 ** consecutive_failures)
        return min(interval, config.backoff_max_interval)

    # 未知类型：使用标准指数退避（兜底）
    else:
        return apply_backoff(config.base_interval, consecutive_failures, config)


def calculate_activity_score(records: list, config: SchedulingConfig) -> float:
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


def calculate_success_rate(records: list) -> float:
    """计算成功率：completed 占比"""
    if not records:
        return 1.0  # 无历史时假设成功

    completed = sum(1 for r in records if r.status == "completed")
    return completed / len(records)


def calculate_trend_score(records: list) -> float:
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


def smooth_change(new_value: float, old_value: float, max_change_ratio: float = 0.5) -> float:
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
