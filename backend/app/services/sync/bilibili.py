"""B站同步 Fetcher — 收藏夹 / 历史记录 / 动态"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app.services.sync.base import BaseSyncFetcher, SyncProgress, SyncResult, ProgressCallback
from app.services.sync.upsert import upsert_videos

logger = logging.getLogger(__name__)

# ─── B站 API 端点 ─────────────────────────────────────────────────────────────

_API_DYNAMIC = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all"
_API_FAVORITES = "https://api.bilibili.com/x/v3/fav/resource/list"
_API_HISTORY = "https://api.bilibili.com/x/web-interface/history/cursor"
_API_NOTEBOOK = "https://api.bilibili.com/x/v1/medialist/gateway/base/created"

_HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com/",
}

_PAGE_SIZE = 20
_REQUEST_INTERVAL = 0.5


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def _epoch_to_iso(ts) -> str | None:
    if not ts or ts == 0:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


def _parse_duration(s: str) -> int | None:
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        return None
    return None


# ─── 异步抓取函数 ────────────────────────────────────────────────────────────

async def _fetch_favorites(client: httpx.AsyncClient, media_id: str, max_items: int | None = None) -> list[dict]:
    videos = []
    page = 1

    while True:
        resp = await client.get(_API_FAVORITES, params={
            "media_id": media_id,
            "ps": _PAGE_SIZE,
            "pn": page,
            "order": "mtime",
        })
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            logger.error(f"B站 API 错误: {data.get('message')}")
            break

        page_data = data.get("data", {})
        medias = page_data.get("medias") or []
        if not medias:
            break

        for m in medias:
            bvid = m.get("bvid", "")
            if not bvid:
                continue

            videos.append({
                "bvid": bvid,
                "title": m.get("title", ""),
                "author": m.get("upper", {}).get("name"),
                "url": f"https://www.bilibili.com/video/{bvid}",
                "duration": m.get("duration"),
                "cover_url": m.get("cover"),
                "published_at": _epoch_to_iso(m.get("pubtime") or m.get("ctime")),
                "is_favorited": True,
                "extra": {
                    "fav_time": m.get("fav_time"),
                    "play": m.get("cnt_info", {}).get("play"),
                    "danmaku": m.get("cnt_info", {}).get("danmaku"),
                    "collect": m.get("cnt_info", {}).get("collect"),
                },
            })

            if max_items and len(videos) >= max_items:
                return videos

        has_more = page_data.get("has_more", False)
        if not has_more:
            break

        page += 1
        await asyncio.sleep(_REQUEST_INTERVAL)

    return videos


async def _fetch_history(client: httpx.AsyncClient, max_items: int | None = None) -> list[dict]:
    videos = []
    cursor_max = 0
    cursor_view_at = 0

    while True:
        params = {"ps": _PAGE_SIZE, "type": "archive"}
        if cursor_max > 0:
            params["max"] = cursor_max
            params["view_at"] = cursor_view_at

        resp = await client.get(_API_HISTORY, params=params)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            logger.error(f"B站 API 错误: {data.get('message')}")
            break

        page_data = data.get("data", {})
        items = page_data.get("list") or []
        if not items:
            break

        for item in items:
            bvid = item.get("history", {}).get("bvid", "") or item.get("bvid", "")
            if not bvid:
                continue

            videos.append({
                "bvid": bvid,
                "title": item.get("title", ""),
                "author": item.get("author_name"),
                "url": f"https://www.bilibili.com/video/{bvid}",
                "duration": item.get("duration"),
                "cover_url": item.get("cover"),
                "published_at": _epoch_to_iso(item.get("view_at")),
                "playback_position": item.get("progress", 0),
                "extra": {
                    "view_at": item.get("view_at"),
                    "tag_name": item.get("tag_name"),
                },
            })

            if max_items and len(videos) >= max_items:
                return videos

        cursor = page_data.get("cursor", {})
        cursor_max = cursor.get("max", 0)
        cursor_view_at = cursor.get("view_at", 0)
        if cursor_max == 0:
            break

        await asyncio.sleep(_REQUEST_INTERVAL)

    return videos


async def _fetch_dynamic(client: httpx.AsyncClient, max_items: int | None = None) -> list[dict]:
    videos = []
    offset = ""

    while True:
        params = {"type": "video"}
        if offset:
            params["offset"] = offset

        resp = await client.get(_API_DYNAMIC, params=params)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            logger.error(f"B站 API 错误: {data.get('message')}")
            break

        page_data = data.get("data", {})
        items = page_data.get("items") or []
        if not items:
            break

        for item in items:
            modules = item.get("modules", {})
            dynamic = modules.get("module_dynamic", {})
            major = dynamic.get("major") or {}
            author_info = modules.get("module_author", {})

            if major.get("type") != "MAJOR_TYPE_ARCHIVE":
                continue

            archive = major.get("archive", {})
            bvid = archive.get("bvid", "")
            if not bvid:
                continue

            duration_str = archive.get("duration_text", "")
            duration = _parse_duration(duration_str)

            videos.append({
                "bvid": bvid,
                "title": archive.get("title", ""),
                "author": author_info.get("name"),
                "url": f"https://www.bilibili.com/video/{bvid}",
                "duration": duration,
                "cover_url": archive.get("cover"),
                "published_at": _epoch_to_iso(author_info.get("pub_ts")),
                "extra": {
                    "play": archive.get("stat", {}).get("play"),
                    "danmaku": archive.get("stat", {}).get("danmaku"),
                    "desc": archive.get("desc"),
                },
            })

            if max_items and len(videos) >= max_items:
                return videos

        offset = page_data.get("offset", "")
        has_more = page_data.get("has_more", False)
        if not has_more or not offset:
            break

        await asyncio.sleep(_REQUEST_INTERVAL)

    return videos


# ─── Fetcher 实现 ─────────────────────────────────────────────────────────────

class BilibiliFetcher(BaseSyncFetcher):

    async def validate_credential(self, credential_data: str) -> tuple[bool, str]:
        """验证 Cookie 是否有效（通过收藏夹列表接口）"""
        headers = {**_HEADERS_BASE, "Cookie": credential_data}
        try:
            async with httpx.AsyncClient(timeout=15, headers=headers) as client:
                resp = await client.get(
                    _API_NOTEBOOK,
                    params={"up_mid": "0", "type": "0", "pn": "1", "ps": "1"},
                )
                data = resp.json()
                if data.get("code") == 0:
                    return True, ""
                return False, "expired"
        except Exception:
            return False, "error"

    async def fetch_and_sync(self, db, source, credential_data, options, on_progress=None):
        sync_type = options.get("sync_type", "favorites")
        media_id = options.get("media_id", "")
        max_items = options.get("max_items")

        type_labels = {"favorites": "收藏夹", "history": "历史记录", "dynamic": "动态"}
        label = type_labels.get(sync_type, sync_type)

        if sync_type == "favorites" and not media_id:
            return SyncResult(success=False, error="收藏夹模式需要提供 media_id")

        # Phase 1: Fetch from B站
        if on_progress:
            await on_progress(SyncProgress(
                phase="fetching",
                message=f"正在从B站获取{label}数据...",
            ))

        headers = {**_HEADERS_BASE, "Cookie": credential_data}
        try:
            async with httpx.AsyncClient(timeout=30, headers=headers) as client:
                if sync_type == "favorites":
                    videos = await _fetch_favorites(client, media_id, max_items)
                elif sync_type == "history":
                    videos = await _fetch_history(client, max_items)
                elif sync_type == "dynamic":
                    videos = await _fetch_dynamic(client, max_items)
                else:
                    return SyncResult(success=False, error=f"不支持的同步类型: {sync_type}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return SyncResult(success=False, error="Cookie 已过期，请更新凭证")
            return SyncResult(success=False, error=f"B站 API 请求失败: {e}")
        except Exception as e:
            return SyncResult(success=False, error=f"获取数据失败: {e}")

        if not videos:
            if on_progress:
                await on_progress(SyncProgress(
                    phase="done",
                    message="没有新数据",
                ))
            return SyncResult(success=True, stats={"new_videos": 0, "updated_videos": 0})

        # Phase 2: Upsert to DB (in batches)
        total = len(videos)
        batch_size = 50
        total_new = 0
        total_updated = 0

        for i in range(0, total, batch_size):
            batch = videos[i:i + batch_size]
            if on_progress:
                await on_progress(SyncProgress(
                    phase="syncing",
                    message=f"正在写入数据 ({min(i + batch_size, total)}/{total})...",
                    current=min(i + batch_size, total),
                    total=total,
                ))

            stats = upsert_videos(db, source, batch)
            total_new += stats["new_videos"]
            total_updated += stats["updated_videos"]

        result_stats = {"new_videos": total_new, "updated_videos": total_updated}

        if on_progress:
            await on_progress(SyncProgress(
                phase="done",
                message=f"同步完成: 新增 {total_new}, 更新 {total_updated}",
                current=total,
                total=total,
            ))

        return SyncResult(success=True, stats=result_stats)

    @staticmethod
    def get_sync_options() -> list[dict]:
        return [
            {
                "key": "sync_type",
                "label": "同步类型",
                "type": "select",
                "options": [
                    {"value": "favorites", "label": "收藏夹"},
                    {"value": "history", "label": "历史记录"},
                    {"value": "dynamic", "label": "动态"},
                ],
                "default": "favorites",
            },
            {
                "key": "media_id",
                "label": "收藏夹 ID",
                "type": "text",
                "placeholder": "收藏夹 media_id (收藏夹模式必填)",
                "depends_on": {"sync_type": "favorites"},
            },
        ]
