"""时区工具函数 - 用于统计 API 的时区边界计算

核心原理：
- 数据库存储的时间戳是 UTC naive datetime（不带时区信息）
- 容器运行时区通过 Docker Compose 的 TZ 环境变量指定（默认 Asia/Shanghai）
- 本模块将容器时区的日期边界转换为 UTC 边界，用于数据库查询

示例（容器 TZ=Asia/Shanghai）：
    >>> get_local_day_boundaries("2026-02-16")
    (datetime(2026, 2, 15, 16, 0, 0), datetime(2026, 2, 16, 16, 0, 0))
    # 上海时间 2026-02-16 00:00 ~ 2026-02-17 00:00
    # = UTC 2026-02-15 16:00 ~ 2026-02-16 16:00
"""

import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from functools import lru_cache


@lru_cache(maxsize=1)
def get_container_timezone() -> ZoneInfo:
    """获取容器配置的时区对象（从 TZ 环境变量）

    Returns:
        ZoneInfo: 时区对象，默认 Asia/Shanghai

    Examples:
        >>> tz = get_container_timezone()
        >>> str(tz)
        'Asia/Shanghai'
    """
    tz_name = os.environ.get('TZ', 'Asia/Shanghai')
    try:
        return ZoneInfo(tz_name)
    except Exception:
        # 回退到 UTC（如果时区名称无效）
        return ZoneInfo('UTC')


def get_local_day_boundaries(date_str: str = None) -> tuple[datetime, datetime]:
    """计算容器时区下的日期边界（返回 UTC naive datetime）

    用途：为统计 API 提供正确的时区边界，解决"今日"统计与用户本地时间不符的问题

    Args:
        date_str: 日期字符串 YYYY-MM-DD，默认今天（容器本地时间）

    Returns:
        (day_start_utc, day_end_utc) — UTC naive datetime，可直接用于数据库查询

    Raises:
        ValueError: 如果 date_str 格式错误

    Examples:
        >>> # 容器 TZ=Asia/Shanghai，查询 2026-02-16 的边界
        >>> start, end = get_local_day_boundaries("2026-02-16")
        >>> print(start, end)
        2026-02-15 16:00:00 2026-02-16 16:00:00

        >>> # 查询今天的边界（默认参数）
        >>> start, end = get_local_day_boundaries()
        >>> # 假设容器本地时间是 2026-02-16 09:00（UTC 01:00）
        >>> print(start)
        2026-02-15 16:00:00  # 今天 00:00 对应的 UTC 时间

    技术细节：
        - 使用 datetime.now() 获取容器本地时间（自动应用 TZ 环境变量）
        - 使用 zoneinfo.ZoneInfo 处理时区转换（Python 3.9+ 标准库）
        - 自动处理 DST（夏令时）边界情况
        - 返回 naive datetime（符合项目规范，数据库存储格式）
    """
    tz = get_container_timezone()

    # 解析目标日期（使用本地时间）
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid date format: {date_str}, expected YYYY-MM-DD")
    else:
        # 使用容器本地时间的今天
        target_date = datetime.now()

    # 构造本地时间的日期边界（当天 00:00 ~ 次日 00:00）
    day_start_local = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_local = day_start_local + timedelta(days=1)

    # 添加时区信息（标记为本地时区的时间）
    day_start_aware = day_start_local.replace(tzinfo=tz)
    day_end_aware = day_end_local.replace(tzinfo=tz)

    # 转为 UTC 并去除时区信息（用于数据库查询）
    day_start_utc = day_start_aware.astimezone(timezone.utc).replace(tzinfo=None)
    day_end_utc = day_end_aware.astimezone(timezone.utc).replace(tzinfo=None)

    return day_start_utc, day_end_utc


def get_local_today() -> str:
    """获取容器本地时区的今天日期字符串

    Returns:
        str: 'YYYY-MM-DD' 格式的日期字符串
    """
    return datetime.now().strftime("%Y-%m-%d")


def get_local_date_offset(days: int) -> str:
    """获取容器本地时区的偏移日期字符串

    Args:
        days: 偏移天数，负数表示过去

    Returns:
        str: 'YYYY-MM-DD' 格式的日期字符串
    """
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def get_local_date_range(days: int) -> list[str]:
    """获取容器本地时区的日期范围列表（从 days-1 天前到今天）

    Args:
        days: 天数范围

    Returns:
        list[str]: 'YYYY-MM-DD' 格式的日期字符串列表
    """
    return [
        (datetime.now() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        for i in range(days)
    ]


def get_container_timezone_name() -> str:
    """获取容器时区名称（供日志/调试使用）

    Returns:
        str: 时区名称，例如 'Asia/Shanghai'
    """
    tz = get_container_timezone()
    return str(tz)
