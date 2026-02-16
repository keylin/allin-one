"""周期性分析与时间窗口预测"""

import json
import logging
from collections import Counter
from datetime import timedelta
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.services.scheduling.config import SchedulingConfig, load_config

logger = logging.getLogger(__name__)


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

    config = load_config(db)

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
