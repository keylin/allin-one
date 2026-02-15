"""统一时间工具 — naive UTC

PostgreSQL 使用 TIMESTAMP WITHOUT TIME ZONE 列类型。
如果写入带 tzinfo 的 datetime，PG 会按 server timezone 做转换，
读出后再 .replace(tzinfo=UTC) 就会产生双重偏移。

规则: 全项目只用 naive UTC datetime，统一调用 utcnow()。
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """返回当前 UTC 时间（naive，不带 tzinfo）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)
