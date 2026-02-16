"""热点检测逻辑"""

import logging
from typing import Optional

from app.services.scheduling.config import SchedulingConfig

logger = logging.getLogger(__name__)


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
