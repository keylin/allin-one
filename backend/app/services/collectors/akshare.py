"""AkShare 采集器 — 金融宏观数据

写入 FinanceDataPoint 独立表（列式存储），不再产出 ContentItem。
collect() 返回空列表，避免触发 Pipeline。
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.content import SourceConfig, ContentItem
from app.models.finance import FinanceDataPoint
from app.services.collectors.base import BaseCollector
from app.services.collectors.akshare_presets import get_category_for_indicator

logger = logging.getLogger(__name__)


_DATE_FORMATS = (
    "%Y-%m-%d", "%Y%m%d", "%Y-%m", "%Y/%m/%d",
    "%Y年%m月份", "%Y年%m月",  # "2025年12月份", "2025年12月"
)


def _parse_date(val) -> str | None:
    """尝试从各种格式解析日期字符串，统一输出 YYYY-MM-DD 或 YYYY-MM"""
    if val is None or str(val).strip() in ("", "nan", "NaT"):
        return None
    if isinstance(val, pd.Timestamp):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            # 仅年月的格式输出 YYYY-MM，完整日期输出 YYYY-MM-DD
            if fmt in ("%Y-%m", "%Y年%m月份", "%Y年%m月"):
                return dt.strftime("%Y-%m")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def _parse_datetime(date_str: str | None) -> datetime | None:
    """将日期字符串解析为 UTC datetime"""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _safe_float(val) -> float | None:
    """安全转 float"""
    if val is None:
        return None
    try:
        f = float(val)
        return f if pd.notna(f) else None
    except (ValueError, TypeError):
        return None


def _check_alerts(alerts: list[dict], values: dict) -> dict | None:
    """检查阈值告警, 返回第一个触发的告警"""
    for alert in alerts:
        field = alert.get("field", "value")
        operator = alert.get("operator", ">")
        threshold = alert.get("threshold")
        if threshold is None:
            continue
        val = values.get(field)
        if val is None:
            continue
        try:
            val = float(val)
            threshold = float(threshold)
        except (ValueError, TypeError):
            continue
        triggered = False
        if operator == ">" and val > threshold:
            triggered = True
        elif operator == ">=" and val >= threshold:
            triggered = True
        elif operator == "<" and val < threshold:
            triggered = True
        elif operator == "<=" and val <= threshold:
            triggered = True
        elif operator == "==" and val == threshold:
            triggered = True
        if triggered:
            return {"label": alert.get("label", ""), "value": val, "threshold": threshold, "operator": operator}
    return None


class AkShareCollector(BaseCollector):
    """AkShare 金融数据采集器

    config_json 格式:
    {
        "indicator": "macro_china_cpi",     # AkShare 接口名 (必填)
        "params": {},                        # 接口参数 (可选)
        "category": "macro",                 # 分类 (可选, 自动推断)
        "date_field": "日期",                # 日期字段
        "value_field": "全国居民消费价格指数", # 主要数值字段 (宏观用)
        "ohlcv_fields": {},                  # OHLCV 映射 (股票/ETF 用)
        "nav_fields": {},                    # 净值映射 (基金用)
        "max_history": 120,                  # 首次采集最大行数
        "alerts": []                         # 阈值告警规则
    }
    """

    async def collect(self, source: SourceConfig, db: Session) -> list[ContentItem]:
        try:
            import akshare as ak
        except ImportError:
            logger.error("[AkShareCollector] akshare not installed, run: pip install akshare")
            raise ValueError("akshare library not installed")

        config = json.loads(source.config_json) if source.config_json else {}
        indicator = config.get("indicator")
        if not indicator:
            raise ValueError(f"No indicator in config for source '{source.name}'")

        params = config.get("params", {})
        date_field = config.get("date_field", "")
        value_field = config.get("value_field", "")
        ohlcv_fields = config.get("ohlcv_fields", {})
        nav_fields = config.get("nav_fields", {})
        max_history = config.get("max_history", 120)
        alerts = config.get("alerts", [])
        category = config.get("category") or get_category_for_indicator(indicator)

        logger.info(f"[AkShareCollector] Fetching {source.name}: {indicator}")

        func = getattr(ak, indicator, None)
        if not func:
            raise ValueError(f"Unknown akshare indicator: {indicator}")

        clean_params = {k: v for k, v in params.items() if v != ""}
        df = await asyncio.to_thread(func, **clean_params)

        if df is None or df.empty:
            logger.info(f"[AkShareCollector] {source.name}: no data returned")
            return []

        # 首次采集量控制
        is_first_collect = source.last_collected_at is None
        if is_first_collect and len(df) > max_history:
            logger.info(f"[AkShareCollector] First collect, truncating {len(df)} -> {max_history} rows")
            df = df.tail(max_history)

        total_rows = len(df)
        new_count = 0

        for _, row in df.iterrows():
            row_dict = {}
            for k, v in row.to_dict().items():
                if isinstance(v, pd.Timestamp):
                    row_dict[k] = v.strftime("%Y-%m-%d")
                elif pd.notna(v):
                    row_dict[k] = str(v)
                else:
                    row_dict[k] = None

            # 解析 date_key
            date_key = _parse_date(row_dict.get(date_field)) if date_field else None
            if not date_key:
                continue  # 无日期的行跳过

            published_at = _parse_datetime(date_key)

            # 构建 FinanceDataPoint
            point = FinanceDataPoint(
                source_id=source.id,
                category=category or "unknown",
                date_key=date_key,
                published_at=published_at,
            )

            # 按类型填充数值列
            if ohlcv_fields:
                point.open = _safe_float(row_dict.get(ohlcv_fields.get("open")))
                point.high = _safe_float(row_dict.get(ohlcv_fields.get("high")))
                point.low = _safe_float(row_dict.get(ohlcv_fields.get("low")))
                point.close = _safe_float(row_dict.get(ohlcv_fields.get("close")))
                point.volume = _safe_float(row_dict.get(ohlcv_fields.get("volume")))
            elif nav_fields:
                point.unit_nav = _safe_float(row_dict.get(nav_fields.get("unit_nav")))
                point.cumulative_nav = _safe_float(row_dict.get(nav_fields.get("cumulative_nav")))
            elif value_field:
                point.value = _safe_float(row_dict.get(value_field))

            # 阈值告警
            if alerts:
                check_values = {
                    "value": point.value,
                    "open": point.open, "high": point.high,
                    "low": point.low, "close": point.close,
                    "volume": point.volume,
                    "unit_nav": point.unit_nav, "cumulative_nav": point.cumulative_nav,
                }
                alert_result = _check_alerts(alerts, check_values)
                if alert_result:
                    point.alert_json = json.dumps(alert_result, ensure_ascii=False)

            try:
                with db.begin_nested():
                    db.add(point)
                    db.flush()
                new_count += 1
            except IntegrityError:
                pass  # (source_id, date_key) 去重

        if new_count:
            db.commit()

        logger.info(
            f"[AkShareCollector] {source.name}: {new_count} new / {total_rows} total rows"
        )

        # 返回空列表: 不产出 ContentItem，不触发 Pipeline
        return []
