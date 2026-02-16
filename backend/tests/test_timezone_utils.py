"""时区工具函数单元测试

验证不同时区的日期边界计算是否正确
"""

import os
import pytest
from datetime import datetime
from unittest.mock import patch

from app.core.timezone_utils import (
    get_container_timezone,
    get_local_day_boundaries,
    get_container_timezone_name,
)


class TestContainerTimezone:
    """测试容器时区获取"""

    def test_default_timezone_shanghai(self):
        """默认时区应为 Asia/Shanghai"""
        with patch.dict(os.environ, {}, clear=True):
            tz = get_container_timezone()
            assert str(tz) == "Asia/Shanghai"

    def test_custom_timezone_from_env(self):
        """应正确读取 TZ 环境变量"""
        with patch.dict(os.environ, {"TZ": "America/New_York"}):
            # 清除缓存以重新读取环境变量
            get_container_timezone.cache_clear()
            tz = get_container_timezone()
            assert str(tz) == "America/New_York"
            get_container_timezone.cache_clear()

    def test_invalid_timezone_fallback_to_utc(self):
        """无效时区应回退到 UTC"""
        with patch.dict(os.environ, {"TZ": "Invalid/Timezone"}):
            get_container_timezone.cache_clear()
            tz = get_container_timezone()
            assert str(tz) == "UTC"
            get_container_timezone.cache_clear()

    def test_timezone_name_function(self):
        """测试时区名称获取函数"""
        with patch.dict(os.environ, {"TZ": "Asia/Shanghai"}):
            get_container_timezone.cache_clear()
            name = get_container_timezone_name()
            assert name == "Asia/Shanghai"
            get_container_timezone.cache_clear()


class TestLocalDayBoundaries:
    """测试日期边界计算"""

    def test_shanghai_boundary(self):
        """测试上海时区边界计算（UTC+8）"""
        with patch.dict(os.environ, {"TZ": "Asia/Shanghai"}):
            get_container_timezone.cache_clear()
            start, end = get_local_day_boundaries("2026-02-16")

            # 上海时间 2026-02-16 00:00 = UTC 2026-02-15 16:00
            assert start == datetime(2026, 2, 15, 16, 0, 0)
            # 上海时间 2026-02-17 00:00 = UTC 2026-02-16 16:00
            assert end == datetime(2026, 2, 16, 16, 0, 0)
            get_container_timezone.cache_clear()

    def test_newyork_winter(self):
        """测试纽约冬季时区边界（EST, UTC-5）"""
        with patch.dict(os.environ, {"TZ": "America/New_York"}):
            get_container_timezone.cache_clear()
            start, end = get_local_day_boundaries("2026-02-16")

            # 纽约冬季时间 2026-02-16 00:00 = UTC 2026-02-16 05:00
            assert start == datetime(2026, 2, 16, 5, 0, 0)
            # 纽约冬季时间 2026-02-17 00:00 = UTC 2026-02-17 05:00
            assert end == datetime(2026, 2, 17, 5, 0, 0)
            get_container_timezone.cache_clear()

    def test_newyork_summer_dst(self):
        """测试纽约夏季 DST 边界（EDT, UTC-4）"""
        with patch.dict(os.environ, {"TZ": "America/New_York"}):
            get_container_timezone.cache_clear()
            # 2026年7月是夏令时
            start, end = get_local_day_boundaries("2026-07-15")

            # 纽约夏季时间 2026-07-15 00:00 = UTC 2026-07-15 04:00
            assert start == datetime(2026, 7, 15, 4, 0, 0)
            assert end == datetime(2026, 7, 16, 4, 0, 0)
            get_container_timezone.cache_clear()

    def test_utc_boundary(self):
        """测试 UTC 时区边界"""
        with patch.dict(os.environ, {"TZ": "UTC"}):
            get_container_timezone.cache_clear()
            start, end = get_local_day_boundaries("2026-02-16")

            # UTC 2026-02-16 00:00 = UTC 2026-02-16 00:00
            assert start == datetime(2026, 2, 16, 0, 0, 0)
            assert end == datetime(2026, 2, 17, 0, 0, 0)
            get_container_timezone.cache_clear()

    def test_tokyo_boundary(self):
        """测试东京时区边界（UTC+9）"""
        with patch.dict(os.environ, {"TZ": "Asia/Tokyo"}):
            get_container_timezone.cache_clear()
            start, end = get_local_day_boundaries("2026-02-16")

            # 东京时间 2026-02-16 00:00 = UTC 2026-02-15 15:00
            assert start == datetime(2026, 2, 15, 15, 0, 0)
            assert end == datetime(2026, 2, 16, 15, 0, 0)
            get_container_timezone.cache_clear()

    def test_london_winter(self):
        """测试伦敦冬季边界（GMT, UTC+0）"""
        with patch.dict(os.environ, {"TZ": "Europe/London"}):
            get_container_timezone.cache_clear()
            start, end = get_local_day_boundaries("2026-02-16")

            # 伦敦冬季时间 2026-02-16 00:00 = UTC 2026-02-16 00:00
            assert start == datetime(2026, 2, 16, 0, 0, 0)
            assert end == datetime(2026, 2, 17, 0, 0, 0)
            get_container_timezone.cache_clear()

    def test_london_summer_bst(self):
        """测试伦敦夏季 BST 边界（UTC+1）"""
        with patch.dict(os.environ, {"TZ": "Europe/London"}):
            get_container_timezone.cache_clear()
            # 2026年7月是夏令时
            start, end = get_local_day_boundaries("2026-07-15")

            # 伦敦夏季时间 2026-07-15 00:00 = UTC 2026-07-14 23:00
            assert start == datetime(2026, 7, 14, 23, 0, 0)
            assert end == datetime(2026, 7, 15, 23, 0, 0)
            get_container_timezone.cache_clear()

    def test_invalid_date_format(self):
        """测试无效日期格式应抛出异常"""
        with pytest.raises(ValueError, match="Invalid date format"):
            get_local_day_boundaries("2026/02/16")

        with pytest.raises(ValueError, match="Invalid date format"):
            get_local_day_boundaries("16-02-2026")

        with pytest.raises(ValueError, match="Invalid date format"):
            get_local_day_boundaries("not-a-date")

    def test_default_to_today(self):
        """测试默认使用今天（不指定日期）"""
        with patch.dict(os.environ, {"TZ": "Asia/Shanghai"}):
            get_container_timezone.cache_clear()
            start, end = get_local_day_boundaries()

            # 验证返回的是 naive datetime
            assert start.tzinfo is None
            assert end.tzinfo is None

            # 验证时间跨度为 24 小时
            assert (end - start).total_seconds() == 86400
            get_container_timezone.cache_clear()

    def test_returns_naive_datetime(self):
        """测试返回的是 naive datetime（符合项目规范）"""
        with patch.dict(os.environ, {"TZ": "Asia/Shanghai"}):
            get_container_timezone.cache_clear()
            start, end = get_local_day_boundaries("2026-02-16")

            # 必须是 naive datetime（不带时区信息）
            assert start.tzinfo is None
            assert end.tzinfo is None
            get_container_timezone.cache_clear()

    def test_boundary_is_24_hours(self):
        """测试日期边界跨度为 24 小时"""
        with patch.dict(os.environ, {"TZ": "Asia/Shanghai"}):
            get_container_timezone.cache_clear()
            start, end = get_local_day_boundaries("2026-02-16")

            # 验证时间跨度为 24 小时
            delta = end - start
            assert delta.total_seconds() == 86400  # 24 * 3600
            get_container_timezone.cache_clear()


class TestEdgeCases:
    """测试边界情况"""

    def test_leap_year_feb_29(self):
        """测试闰年 2 月 29 日"""
        with patch.dict(os.environ, {"TZ": "Asia/Shanghai"}):
            get_container_timezone.cache_clear()
            # 2024 是闰年
            start, end = get_local_day_boundaries("2024-02-29")

            assert start == datetime(2024, 2, 28, 16, 0, 0)
            assert end == datetime(2024, 2, 29, 16, 0, 0)
            get_container_timezone.cache_clear()

    def test_year_boundary(self):
        """测试跨年边界"""
        with patch.dict(os.environ, {"TZ": "Asia/Shanghai"}):
            get_container_timezone.cache_clear()
            start, end = get_local_day_boundaries("2026-01-01")

            # 上海时间 2026-01-01 00:00 = UTC 2025-12-31 16:00
            assert start == datetime(2025, 12, 31, 16, 0, 0)
            assert end == datetime(2026, 1, 1, 16, 0, 0)
            get_container_timezone.cache_clear()

    def test_month_boundary(self):
        """测试跨月边界"""
        with patch.dict(os.environ, {"TZ": "Asia/Shanghai"}):
            get_container_timezone.cache_clear()
            start, end = get_local_day_boundaries("2026-03-01")

            # 上海时间 2026-03-01 00:00 = UTC 2026-02-28 16:00
            assert start == datetime(2026, 2, 28, 16, 0, 0)
            assert end == datetime(2026, 3, 1, 16, 0, 0)
            get_container_timezone.cache_clear()
