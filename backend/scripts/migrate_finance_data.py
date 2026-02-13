#!/usr/bin/env python3
"""一次性迁移脚本: 将 ContentItem(media_type='data') 迁移到 FinanceDataPoint

使用方法:
    cd backend
    .venv/bin/python scripts/migrate_finance_data.py [--dry-run] [--keep-old]

选项:
    --dry-run   仅统计，不执行写入和删除
    --keep-old  迁移后保留旧 ContentItem 行（不删除）
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# 确保可以 import app
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401 — 注册所有 ORM 模型
from app.core.database import SessionLocal
from app.models.content import ContentItem
from app.models.finance import FinanceDataPoint
from app.models.pipeline import PipelineExecution, PipelineStep

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def _parse_datetime(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def migrate(dry_run: bool = False, keep_old: bool = False):
    db = SessionLocal()
    try:
        items = (
            db.query(ContentItem)
            .filter(ContentItem.media_type == "data")
            .all()
        )
        logger.info(f"Found {len(items)} ContentItem(media_type='data') rows to migrate")

        if not items:
            logger.info("Nothing to migrate.")
            return

        migrated = 0
        skipped = 0
        errors = 0

        for item in items:
            try:
                raw = json.loads(item.raw_data) if item.raw_data else {}
            except json.JSONDecodeError:
                logger.warning(f"  Skip {item.id}: invalid JSON in raw_data")
                errors += 1
                continue

            date_key = raw.get("_date")
            if not date_key:
                logger.warning(f"  Skip {item.id}: no _date in raw_data")
                skipped += 1
                continue

            # 检查是否已迁移
            exists = (
                db.query(FinanceDataPoint.id)
                .filter(
                    FinanceDataPoint.source_id == item.source_id,
                    FinanceDataPoint.date_key == date_key,
                )
                .first()
            )
            if exists:
                skipped += 1
                continue

            category = raw.get("_category", "unknown")
            published_at = _parse_datetime(date_key) or item.published_at

            point = FinanceDataPoint(
                source_id=item.source_id,
                category=category,
                date_key=date_key,
                published_at=published_at,
                collected_at=item.collected_at,
                analysis_result=item.analysis_result,
            )

            # 按数据类型填充数值列
            ohlcv = raw.get("_ohlcv")
            nav = raw.get("_nav")
            if ohlcv and isinstance(ohlcv, dict):
                point.open = _safe_float(ohlcv.get("open"))
                point.high = _safe_float(ohlcv.get("high"))
                point.low = _safe_float(ohlcv.get("low"))
                point.close = _safe_float(ohlcv.get("close"))
                point.volume = _safe_float(ohlcv.get("volume"))
            elif nav and isinstance(nav, dict):
                point.unit_nav = _safe_float(nav.get("unit_nav"))
                point.cumulative_nav = _safe_float(nav.get("cumulative_nav"))
            elif "_value" in raw:
                point.value = _safe_float(raw["_value"])

            # 告警
            alert = raw.get("_alert")
            if alert:
                point.alert_json = json.dumps(alert, ensure_ascii=False)

            if not dry_run:
                db.add(point)
            migrated += 1

        if not dry_run and migrated:
            db.flush()

        logger.info(f"Migrated: {migrated}, Skipped (dup/no-date): {skipped}, Errors: {errors}")

        # 删除旧数据（无论是否有新迁移，只要有旧行就清理）
        if not dry_run and not keep_old:
            item_ids = [item.id for item in items]

            # 删除关联的 PipelineStep → PipelineExecution
            exec_ids = [
                eid for (eid,) in db.query(PipelineExecution.id)
                .filter(PipelineExecution.content_id.in_(item_ids))
                .all()
            ]
            if exec_ids:
                step_del = (
                    db.query(PipelineStep)
                    .filter(PipelineStep.pipeline_id.in_(exec_ids))
                    .delete(synchronize_session=False)
                )
                exec_del = (
                    db.query(PipelineExecution)
                    .filter(PipelineExecution.id.in_(exec_ids))
                    .delete(synchronize_session=False)
                )
                logger.info(f"Deleted {step_del} pipeline steps, {exec_del} pipeline executions")

            content_del = (
                db.query(ContentItem)
                .filter(ContentItem.id.in_(item_ids))
                .delete(synchronize_session=False)
            )
            logger.info(f"Deleted {content_del} old ContentItem rows")

        if not dry_run:
            db.commit()
            logger.info("Migration committed successfully.")
        else:
            logger.info("Dry run complete. No changes made.")

    except Exception:
        db.rollback()
        logger.exception("Migration failed, rolled back.")
        raise
    finally:
        db.close()


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate finance ContentItems to FinanceDataPoint")
    parser.add_argument("--dry-run", action="store_true", help="Only count, don't write")
    parser.add_argument("--keep-old", action="store_true", help="Don't delete old ContentItem rows")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run, keep_old=args.keep_old)
