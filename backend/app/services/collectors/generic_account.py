"""通用账号采集器 — 通过 HTTP API 抓取任意平台数据"""

import json
import hashlib
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.content import SourceConfig, ContentItem, ContentStatus, MediaType
from app.services.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class GenericAccountCollector(BaseCollector):
    """通用账号采集器，通过配置化 HTTP API 抓取数据

    config_json 格式:
    {
        "api_url": "https://api.example.com/posts",  # API 地址 (必填)
        "method": "GET",                               # HTTP 方法 (默认 GET)
        "headers": {"Authorization": "Bearer xxx"},    # 请求头 (可选)
        "params": {"page": 1, "limit": 20},           # 查询参数 (可选)
        "body": {},                                    # 请求体 (POST 时使用)
        "items_path": "data.items",                    # 数据列表的 JSON Path (必填)
        "title_field": "title",                        # 标题字段 (默认 title)
        "url_field": "url",                            # 链接字段 (默认 url)
        "id_field": "id",                              # ID 字段 (默认 id)
        "author_field": "author",                      # 作者字段 (可选)
        "time_field": "created_at",                    # 时间字段 (可选)
        "time_format": "timestamp"                     # 时间格式: timestamp / iso (可选)
    }
    """

    async def collect(self, source: SourceConfig, db: Session) -> list[ContentItem]:
        config = json.loads(source.config_json) if source.config_json else {}
        api_url = config.get("api_url") or source.url
        if not api_url:
            raise ValueError(f"No api_url in config for source '{source.name}'")

        method = config.get("method", "GET").upper()
        headers = config.get("headers", {})
        params = config.get("params", {})
        body = config.get("body")
        items_path = config.get("items_path", "data")

        logger.info(f"[GenericAccountCollector] Fetching {source.name}: {api_url}")

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            if method == "POST":
                resp = await client.post(api_url, headers=headers, params=params, json=body)
            else:
                resp = await client.get(api_url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        # 通过 JSON Path 提取列表
        items = self._extract_path(data, items_path)
        if not isinstance(items, list):
            logger.warning(f"[GenericAccountCollector] items_path '{items_path}' did not yield a list")
            return []

        # 字段映射
        title_field = config.get("title_field", "title")
        url_field = config.get("url_field", "url")
        id_field = config.get("id_field", "id")
        author_field = config.get("author_field")
        time_field = config.get("time_field")
        time_format = config.get("time_format", "iso")

        new_items = []
        for entry in items:
            title = str(entry.get(title_field, ""))
            if not title:
                continue

            # 外部 ID
            raw_id = str(entry.get(id_field, ""))
            if raw_id:
                external_id = hashlib.md5(f"{source.id}:{raw_id}".encode()).hexdigest()
            else:
                external_id = hashlib.md5(json.dumps(entry, sort_keys=True, default=str).encode()).hexdigest()

            # 发布时间
            published_at = None
            if time_field and entry.get(time_field):
                published_at = self._parse_time(entry[time_field], time_format)

            item = ContentItem(
                source_id=source.id,
                title=title[:500],
                external_id=external_id,
                url=entry.get(url_field),
                author=entry.get(author_field) if author_field else None,
                raw_data=json.dumps(entry, ensure_ascii=False, default=str),
                status=ContentStatus.PENDING.value,
                media_type=source.media_type or MediaType.TEXT.value,
                published_at=published_at,
            )
            db.add(item)
            try:
                db.flush()
                new_items.append(item)
            except IntegrityError:
                db.rollback()

        if new_items:
            db.commit()

        logger.info(f"[GenericAccountCollector] {source.name}: {len(new_items)} new / {len(items)} total")
        return new_items

    def _extract_path(self, data: dict, path: str):
        """通过点分路径提取嵌套字典值，如 'data.items'"""
        current = data
        for key in path.split("."):
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return None
        return current

    def _parse_time(self, value, fmt: str) -> datetime | None:
        """解析时间值"""
        try:
            if fmt == "timestamp":
                ts = int(value)
                if ts > 1e12:  # 毫秒时间戳
                    ts = ts / 1000
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            else:
                # ISO 格式
                if isinstance(value, str):
                    return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            pass
        return None
