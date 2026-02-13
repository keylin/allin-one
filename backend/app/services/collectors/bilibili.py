"""B站账号采集器 — 通过 Cookie 抓取用户动态/收藏"""

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

# B站 API 端点
_API_DYNAMIC = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all"
_API_FAVORITES = "https://api.bilibili.com/x/v3/fav/resource/list"
_API_HISTORY = "https://api.bilibili.com/x/web-interface/history/cursor"


class BilibiliCollector(BaseCollector):
    """B站账号采集器，通过 Cookie 获取用户动态/收藏/历史

    config_json 格式:
    {
        "cookie": "SESSDATA=xxx; bili_jct=xxx",     # B站 Cookie (必填)
        "type": "dynamic",                           # dynamic / favorites / history
        "media_id": "12345",                         # 收藏夹 ID (type=favorites 时必填)
        "max_items": 20                              # 最大条目数 (可选)
    }
    """

    async def collect(self, source: SourceConfig, db: Session) -> list[ContentItem]:
        config = json.loads(source.config_json) if source.config_json else {}

        # 优先从 credential 读取
        cookie = None
        if source.credential_id and source.credential:
            cred = source.credential
            if cred.status == "active":
                cookie = cred.credential_data

        # 回退到 config_json.cookie（向后兼容）
        if not cookie:
            cookie = config.get("cookie")

        if not cookie:
            raise ValueError(f"No cookie for source '{source.name}'")

        collect_type = config.get("type", "dynamic")
        max_items = config.get("max_items", 20)

        logger.info(f"[BilibiliCollector] Fetching {source.name}: type={collect_type}")

        headers = {
            "Cookie": cookie,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com/",
        }

        if collect_type == "dynamic":
            entries = await self._fetch_dynamic(headers, max_items)
        elif collect_type == "favorites":
            media_id = config.get("media_id")
            if not media_id:
                raise ValueError("media_id required for favorites type")
            entries = await self._fetch_favorites(headers, media_id, max_items)
        elif collect_type == "history":
            entries = await self._fetch_history(headers, max_items)
        else:
            raise ValueError(f"Unknown collect type: {collect_type}")

        new_items = []
        for entry in entries:
            item = ContentItem(
                source_id=source.id,
                title=entry["title"][:500],
                external_id=entry["external_id"],
                url=entry.get("url"),
                author=entry.get("author"),
                raw_data=json.dumps(entry.get("raw", {}), ensure_ascii=False),
                status=ContentStatus.PENDING.value,
                media_type=entry.get("media_type", MediaType.VIDEO.value),
                published_at=entry.get("published_at"),
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

        logger.info(f"[BilibiliCollector] {source.name}: {len(new_items)} new / {len(entries)} total")
        return new_items

    async def _fetch_dynamic(self, headers: dict, max_items: int) -> list[dict]:
        """获取用户动态"""
        entries = []
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            resp = await client.get(_API_DYNAMIC, params={"type": "all"})
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                raise ValueError(f"B站 API 错误: {data.get('message')}")

            items = data.get("data", {}).get("items", [])
            for item in items[:max_items]:
                modules = item.get("modules", {})
                author_info = modules.get("module_author", {})
                dynamic_info = modules.get("module_dynamic", {})
                major = dynamic_info.get("major") or {}

                # 提取标题和链接
                title = ""
                url = ""
                media_type = MediaType.TEXT.value
                major_type = major.get("type", "")
                author_name = author_info.get("name", "")

                if major_type == "MAJOR_TYPE_ARCHIVE":
                    archive = major.get("archive", {})
                    title = archive.get("title", "")
                    url = f"https://www.bilibili.com/video/{archive.get('bvid', '')}"
                    media_type = MediaType.VIDEO.value
                elif major_type == "MAJOR_TYPE_ARTICLE":
                    article = major.get("article", {})
                    title = article.get("title", "")
                    url = f"https://www.bilibili.com/read/cv{article.get('id', '')}"
                elif major_type == "MAJOR_TYPE_DRAW":
                    # 图片动态: 优先取文字描述，否则用作者名
                    desc = dynamic_info.get("desc")
                    desc_text = desc.get("text", "").strip() if desc else ""
                    title = desc_text[:200] if desc_text else f"{author_name}的图片动态"
                    url = f"https://t.bilibili.com/{item.get('id_str', '')}"
                    media_type = MediaType.IMAGE.value
                elif major_type == "MAJOR_TYPE_LIVE_RCMD":
                    live = major.get("live_rcmd", {})
                    try:
                        live_info = json.loads(live.get("content", "{}"))
                        live_play = live_info.get("live_play_info", {})
                        title = live_play.get("title", "")
                    except (json.JSONDecodeError, TypeError):
                        pass
                    if not title:
                        title = f"{author_name}的直播"
                    url = f"https://t.bilibili.com/{item.get('id_str', '')}"
                else:
                    # 纯文字/转发等
                    desc = dynamic_info.get("desc")
                    desc_text = desc.get("text", "").strip() if desc else ""
                    title = desc_text[:200] if desc_text else f"{author_name}的动态"
                    url = f"https://t.bilibili.com/{item.get('id_str', '')}"

                if not title:
                    continue

                entries.append({
                    "title": title,
                    "external_id": hashlib.md5(f"bili_dynamic:{item.get('id_str', '')}".encode()).hexdigest(),
                    "url": url,
                    "author": author_info.get("name"),
                    "media_type": media_type,
                    "published_at": datetime.fromtimestamp(
                        author_info.get("pub_ts", 0), tz=timezone.utc
                    ) if author_info.get("pub_ts") else None,
                    "raw": item,
                })

        return entries

    async def _fetch_favorites(self, headers: dict, media_id: str, max_items: int) -> list[dict]:
        """获取收藏夹内容"""
        entries = []
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            resp = await client.get(_API_FAVORITES, params={
                "media_id": media_id,
                "ps": min(max_items, 20),
                "pn": 1,
                "order": "mtime",
            })
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                raise ValueError(f"B站 API 错误: {data.get('message')}")

            medias = data.get("data", {}).get("medias") or []
            for media in medias[:max_items]:
                entries.append({
                    "title": media.get("title", ""),
                    "external_id": hashlib.md5(f"bili_fav:{media.get('id', '')}".encode()).hexdigest(),
                    "url": f"https://www.bilibili.com/video/{media.get('bvid', '')}",
                    "author": media.get("upper", {}).get("name"),
                    "media_type": MediaType.VIDEO.value,
                    "published_at": datetime.fromtimestamp(
                        media.get("ctime", 0), tz=timezone.utc
                    ) if media.get("ctime") else None,
                    "raw": media,
                })

        return entries

    async def _fetch_history(self, headers: dict, max_items: int) -> list[dict]:
        """获取观看历史"""
        entries = []
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            resp = await client.get(_API_HISTORY, params={"ps": min(max_items, 20)})
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                raise ValueError(f"B站 API 错误: {data.get('message')}")

            items = data.get("data", {}).get("list", [])
            for item in items[:max_items]:
                entries.append({
                    "title": item.get("title", ""),
                    "external_id": hashlib.md5(f"bili_history:{item.get('kid', '')}".encode()).hexdigest(),
                    "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}",
                    "author": item.get("author_name"),
                    "media_type": MediaType.VIDEO.value,
                    "published_at": datetime.fromtimestamp(
                        item.get("view_at", 0), tz=timezone.utc
                    ) if item.get("view_at") else None,
                    "raw": item,
                })

        return entries
