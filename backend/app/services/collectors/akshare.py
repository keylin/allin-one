"""AkShare 采集器 — 金融宏观数据"""

import json
import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.content import SourceConfig, ContentItem, ContentStatus, MediaType
from app.services.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class AkShareCollector(BaseCollector):
    """AkShare 金融数据采集器

    config_json 格式:
    {
        "indicator": "macro_china_cpi",     # AkShare 接口名 (必填)
        "params": {},                        # 接口参数 (可选)
        "title_field": "date",              # 用作标题的字段 (可选)
        "id_fields": ["date"]               # 用于去重的字段 (可选)
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
        title_field = config.get("title_field", "")
        id_fields = config.get("id_fields", [])

        logger.info(f"[AkShareCollector] Fetching {source.name}: {indicator}")

        # 调用 akshare 接口
        func = getattr(ak, indicator, None)
        if not func:
            raise ValueError(f"Unknown akshare indicator: {indicator}")

        df = func(**params)
        if df is None or df.empty:
            logger.info(f"[AkShareCollector] {source.name}: no data returned")
            return []

        new_items = []
        for _, row in df.iterrows():
            row_dict = {k: str(v) for k, v in row.to_dict().items()}

            # 生成标题
            if title_field and title_field in row_dict:
                title = f"{indicator} - {row_dict[title_field]}"
            else:
                title = f"{indicator} - {row.name}" if hasattr(row, 'name') else indicator

            # 生成外部 ID
            if id_fields:
                id_str = "|".join(str(row_dict.get(f, "")) for f in id_fields)
            else:
                id_str = json.dumps(row_dict, sort_keys=True)
            external_id = hashlib.md5(f"{indicator}:{id_str}".encode()).hexdigest()

            item = ContentItem(
                source_id=source.id,
                title=title[:500],
                external_id=external_id,
                raw_data=json.dumps(row_dict, ensure_ascii=False),
                status=ContentStatus.PENDING.value,
                media_type=MediaType.TEXT.value,
            )
            try:
                with db.begin_nested():
                    db.add(item)
                    db.flush()
                new_items.append(item)
            except IntegrityError:
                pass  # SAVEPOINT 已自动回滚，外层事务不受影响

        if new_items:
            db.commit()

        logger.info(f"[AkShareCollector] {source.name}: {len(new_items)} new / {len(df)} total rows")
        return new_items
