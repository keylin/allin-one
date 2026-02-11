"""Web Scraper 采集器 — 通过 CSS 选择器抓取网页列表"""

import json
import hashlib
import logging
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.content import SourceConfig, ContentItem, ContentStatus, MediaType
from app.services.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class ScraperCollector(BaseCollector):
    """通用网页抓取器，通过 CSS 选择器提取列表项"""

    async def collect(self, source: SourceConfig, db: Session) -> list[ContentItem]:
        """从网页抓取内容列表

        config_json 格式:
        {
            "item_selector": ".article-item",       # 列表项选择器 (必填)
            "title_selector": "h2",                 # 标题选择器 (相对于 item)
            "link_selector": "a",                   # 链接选择器
            "link_attr": "href",                    # 链接属性
            "author_selector": ".author",           # 作者选择器 (可选)
            "use_browserless": false                # 是否强制使用 L2
        }
        """
        if not source.url:
            raise ValueError(f"No URL configured for source '{source.name}'")

        config = json.loads(source.config_json) if source.config_json else {}
        item_selector = config.get("item_selector")
        if not item_selector:
            raise ValueError(f"No item_selector in config for source '{source.name}'")

        # 抓取页面
        html = await self._fetch_page(source.url, config.get("use_browserless", False))

        # 解析提取
        soup = BeautifulSoup(html, "lxml")
        items = soup.select(item_selector)

        new_items = []
        for idx, item_elem in enumerate(items):
            try:
                title, link, author = self._extract_item_data(item_elem, config)
                if not title:
                    continue

                # 生成 external_id
                external_id = hashlib.md5(
                    f"{link or source.url}/{idx}/{title}".encode()
                ).hexdigest()

                content_item = ContentItem(
                    source_id=source.id,
                    title=title[:500],
                    external_id=external_id,
                    url=link if link and link.startswith("http") else self._resolve_url(source.url, link),
                    author=author,
                    status=ContentStatus.PENDING.value,
                    media_type=source.media_type or MediaType.TEXT.value,
                    published_at=None,  # 网页抓取通常无时间戳
                )

                db.add(content_item)
                db.flush()
                new_items.append(content_item)

            except IntegrityError:
                db.rollback()
                # 重复条目，跳过
            except Exception as e:
                logger.warning(f"[ScraperCollector] Failed to parse item: {e}")
                continue

        if new_items:
            db.commit()

        logger.info(f"[ScraperCollector] Collected {len(new_items)} items from {source.name}")
        return new_items

    async def _fetch_page(self, url: str, use_browserless: bool = False) -> str:
        """抓取页面 HTML — L1 HTTP 或 L2 Browserless，失败时抛异常"""
        # L1: 普通 HTTP 请求
        if not use_browserless:
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return resp.text
            except Exception as e:
                logger.warning(f"[ScraperCollector] L1 failed for {url}: {e}, trying L2")

        # L2: Browserless 渲染（失败则抛异常）
        return await self._fetch_with_browserless(url, settings.BROWSERLESS_URL)

    async def _fetch_with_browserless(self, url: str, browserless_url: str) -> str:
        """使用 Browserless 渲染页面"""
        endpoint = f"{browserless_url.rstrip('/')}/content"

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                endpoint,
                json={"url": url},
                params={"waitFor": "networkidle0"},
            )
            resp.raise_for_status()
            return resp.text

    def _extract_item_data(self, item_elem, config: dict) -> tuple[str, str, str | None]:
        """从列表项元素中提取数据

        Returns:
            (title, link, author)
        """
        title_selector = config.get("title_selector", "")
        link_selector = config.get("link_selector", "a")
        link_attr = config.get("link_attr", "href")
        author_selector = config.get("author_selector", "")

        # 提取标题
        title = ""
        if title_selector:
            title_elem = item_elem.select_one(title_selector)
            title = title_elem.get_text(strip=True) if title_elem else ""
        else:
            # 默认使用整个 item 的文本
            title = item_elem.get_text(strip=True)

        # 提取链接
        link = ""
        link_elem = item_elem.select_one(link_selector) if link_selector else item_elem.find("a")
        if link_elem and link_elem.has_attr(link_attr):
            link = link_elem[link_attr]

        # 提取作者 (可选)
        author = None
        if author_selector:
            author_elem = item_elem.select_one(author_selector)
            author = author_elem.get_text(strip=True) if author_elem else None

        return title, link, author

    def _resolve_url(self, base_url: str, relative_url: str | None) -> str | None:
        """解析相对 URL 为绝对 URL"""
        if not relative_url:
            return None

        if relative_url.startswith(("http://", "https://")):
            return relative_url

        from urllib.parse import urljoin
        return urljoin(base_url, relative_url)
