#!/usr/bin/env python3
"""时区功能验证脚本 - 手动测试时区边界计算

运行方式:
  cd /path/to/allin-one
  python3 scripts/verify/timezone/verify_timezone.py

或者:
  cd backend
  python3 ../scripts/verify/timezone/verify_timezone.py
"""

import os
import sys
from datetime import datetime

# 添加 backend 目录到 Python 路径
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))
backend_dir = os.path.join(project_root, 'backend')
sys.path.insert(0, backend_dir)

from app.core.timezone_utils import get_local_day_boundaries, get_container_timezone_name


def test_case(name: str, tz: str, date: str, expected_start: str, expected_end: str):
    """运行单个测试用例

    Args:
        name: 测试用例名称
        tz: 时区名称
        date: 测试日期 YYYY-MM-DD
        expected_start: 期望的起始时间 YYYY-MM-DD HH:MM:SS
        expected_end: 期望的结束时间 YYYY-MM-DD HH:MM:SS
    """
    # 设置时区环境变量
    original_tz = os.environ.get('TZ')
    os.environ['TZ'] = tz

    # 清除缓存
    from app.core.timezone_utils import get_container_timezone
    get_container_timezone.cache_clear()

    try:
        start, end = get_local_day_boundaries(date)

        # 解析期望值
        exp_start = datetime.strptime(expected_start, "%Y-%m-%d %H:%M:%S")
        exp_end = datetime.strptime(expected_end, "%Y-%m-%d %H:%M:%S")

        # 验证结果
        start_ok = start == exp_start
        end_ok = end == exp_end

        status = "✅ PASS" if (start_ok and end_ok) else "❌ FAIL"
        print(f"{status} | {name}")
        print(f"  时区: {tz}")
        print(f"  输入日期: {date}")
        print(f"  起始时间: {start} {'✅' if start_ok else f'❌ 期望 {exp_start}'}")
        print(f"  结束时间: {end} {'✅' if end_ok else f'❌ 期望 {exp_end}'}")
        print()

        return start_ok and end_ok

    finally:
        # 恢复原始时区
        if original_tz:
            os.environ['TZ'] = original_tz
        else:
            os.environ.pop('TZ', None)
        get_container_timezone.cache_clear()


def main():
    """运行所有测试用例"""
    print("=" * 70)
    print("时区功能验证")
    print("=" * 70)
    print()

    # 获取当前容器时区
    current_tz = get_container_timezone_name()
    print(f"📍 当前容器时区: {current_tz}")
    print()

    test_results = []

    # 测试 1: 上海时区（UTC+8）
    test_results.append(test_case(
        name="上海时区 (UTC+8)",
        tz="Asia/Shanghai",
        date="2026-02-16",
        expected_start="2026-02-15 16:00:00",
        expected_end="2026-02-16 16:00:00"
    ))

    # 测试 2: 纽约冬季（EST, UTC-5）
    test_results.append(test_case(
        name="纽约冬季 (EST, UTC-5)",
        tz="America/New_York",
        date="2026-02-16",
        expected_start="2026-02-16 05:00:00",
        expected_end="2026-02-17 05:00:00"
    ))

    # 测试 3: 纽约夏季 DST（EDT, UTC-4）
    test_results.append(test_case(
        name="纽约夏季 DST (EDT, UTC-4)",
        tz="America/New_York",
        date="2026-07-15",
        expected_start="2026-07-15 04:00:00",
        expected_end="2026-07-16 04:00:00"
    ))

    # 测试 4: UTC 时区
    test_results.append(test_case(
        name="UTC 时区",
        tz="UTC",
        date="2026-02-16",
        expected_start="2026-02-16 00:00:00",
        expected_end="2026-02-17 00:00:00"
    ))

    # 测试 5: 东京时区（UTC+9）
    test_results.append(test_case(
        name="东京时区 (UTC+9)",
        tz="Asia/Tokyo",
        date="2026-02-16",
        expected_start="2026-02-15 15:00:00",
        expected_end="2026-02-16 15:00:00"
    ))

    # 测试 6: 伦敦夏季 BST（UTC+1）
    test_results.append(test_case(
        name="伦敦夏季 BST (UTC+1)",
        tz="Europe/London",
        date="2026-07-15",
        expected_start="2026-07-14 23:00:00",
        expected_end="2026-07-15 23:00:00"
    ))

    # 测试 7: 跨年边界（上海时区）
    test_results.append(test_case(
        name="跨年边界 (上海时区)",
        tz="Asia/Shanghai",
        date="2026-01-01",
        expected_start="2025-12-31 16:00:00",
        expected_end="2026-01-01 16:00:00"
    ))

    # 测试 8: 闰年 2 月 29 日（上海时区）
    test_results.append(test_case(
        name="闰年 2 月 29 日 (上海时区)",
        tz="Asia/Shanghai",
        date="2024-02-29",
        expected_start="2024-02-28 16:00:00",
        expected_end="2024-02-29 16:00:00"
    ))

    # 测试总结
    print("=" * 70)
    passed = sum(test_results)
    total = len(test_results)
    print(f"测试结果: {passed}/{total} 通过")
    print("=" * 70)

    # 如果所有测试通过，返回 0，否则返回 1
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
