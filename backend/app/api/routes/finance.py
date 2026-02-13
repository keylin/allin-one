"""Finance API — 金融数据查询与可视化

直接查询 FinanceDataPoint 列式表，无需 JSON 解析。
"""

import json
import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.core.database import get_db
from app.models.content import SourceConfig
from app.models.finance import FinanceDataPoint
from app.services.collectors.akshare_presets import FINANCE_PRESETS

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/presets")
async def get_presets():
    """返回金融指标预设库"""
    return {"code": 0, "data": FINANCE_PRESETS, "message": "ok"}


@router.get("/sources")
async def list_finance_sources(db: Session = Depends(get_db)):
    """列出所有 AkShare 数据源, 附带分类、最新值、数据点计数"""
    sources = (
        db.query(SourceConfig)
        .filter(SourceConfig.source_type == "api.akshare")
        .order_by(SourceConfig.created_at.desc())
        .all()
    )

    result = []
    for src in sources:
        config = json.loads(src.config_json) if src.config_json else {}
        category = config.get("category", "unknown")

        content_count = (
            db.query(func.count(FinanceDataPoint.id))
            .filter(FinanceDataPoint.source_id == src.id)
            .scalar()
        )

        latest = (
            db.query(FinanceDataPoint)
            .filter(FinanceDataPoint.source_id == src.id)
            .order_by(desc(FinanceDataPoint.published_at))
            .first()
        )

        latest_value = None
        latest_date = None
        if latest:
            latest_date = latest.date_key
            if latest.value is not None:
                latest_value = latest.value
            elif latest.close is not None:
                latest_value = latest.close
            elif latest.unit_nav is not None:
                latest_value = latest.unit_nav

        result.append({
            "id": src.id,
            "name": src.name,
            "indicator": config.get("indicator"),
            "category": category,
            "is_active": src.is_active,
            "schedule_interval": src.schedule_interval,
            "content_count": content_count,
            "latest_value": latest_value,
            "latest_date": latest_date,
            "last_collected_at": src.last_collected_at.isoformat() if src.last_collected_at else None,
        })

    return {"code": 0, "data": result, "message": "ok"}


@router.get("/summary")
async def get_finance_summary(db: Session = Depends(get_db)):
    """所有活跃金融源的最新值概览 (Dashboard / Summary Cards)"""
    sources = (
        db.query(SourceConfig)
        .filter(SourceConfig.source_type == "api.akshare", SourceConfig.is_active == True)
        .all()
    )

    summaries = []
    for src in sources:
        config = json.loads(src.config_json) if src.config_json else {}
        category = config.get("category", "unknown")

        recent = (
            db.query(FinanceDataPoint)
            .filter(FinanceDataPoint.source_id == src.id)
            .order_by(desc(FinanceDataPoint.published_at))
            .limit(2)
            .all()
        )

        if not recent:
            continue

        def _extract_value(point: FinanceDataPoint) -> float | None:
            if point.value is not None:
                return point.value
            if point.close is not None:
                return point.close
            if point.unit_nav is not None:
                return point.unit_nav
            return None

        current_val = _extract_value(recent[0])
        current_date = recent[0].date_key
        prev_val = _extract_value(recent[1]) if len(recent) > 1 else None

        change = None
        if current_val is not None and prev_val is not None and prev_val != 0:
            change = round(current_val - prev_val, 4)

        summaries.append({
            "source_id": src.id,
            "name": src.name,
            "category": category,
            "indicator": config.get("indicator"),
            "value": current_val,
            "date": current_date,
            "change": change,
        })

    return {"code": 0, "data": summaries, "message": "ok"}


@router.get("/timeseries/{source_id}")
async def get_timeseries(
    source_id: str,
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """提取时间序列数据供图表渲染"""
    source = db.get(SourceConfig, source_id)
    if not source:
        return {"code": 404, "data": None, "message": "Source not found"}

    config = json.loads(source.config_json) if source.config_json else {}
    category = config.get("category", "unknown")

    query = (
        db.query(FinanceDataPoint)
        .filter(FinanceDataPoint.source_id == source_id)
    )

    if start_date:
        query = query.filter(FinanceDataPoint.published_at >= start_date)
    if end_date:
        query = query.filter(FinanceDataPoint.published_at <= end_date)

    points = (
        query.order_by(FinanceDataPoint.published_at.asc())
        .limit(limit)
        .all()
    )

    series = []
    for pt in points:
        if not pt.date_key:
            continue

        point = {"date": pt.date_key}

        if pt.open is not None or pt.close is not None:
            point["open"] = pt.open
            point["high"] = pt.high
            point["low"] = pt.low
            point["close"] = pt.close
            point["volume"] = pt.volume
        elif pt.unit_nav is not None:
            point["unit_nav"] = pt.unit_nav
            point["cumulative_nav"] = pt.cumulative_nav
        else:
            point["value"] = pt.value

        if pt.alert_json:
            try:
                point["alert"] = json.loads(pt.alert_json)
            except json.JSONDecodeError:
                pass

        if pt.analysis_result:
            point["analysis_id"] = pt.id

        series.append(point)

    return {
        "code": 0,
        "data": {
            "source_name": source.name,
            "category": category,
            "indicator": config.get("indicator"),
            "series": series,
        },
        "message": "ok",
    }
