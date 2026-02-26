"""微信读书同步 Fetcher — 笔记本 / 书架 / 标注 / 想法"""

import asyncio
import logging
import urllib.parse
from datetime import datetime, timezone

import httpx

from app.services.sync.base import BaseSyncFetcher, SyncProgress, SyncResult, ProgressCallback
from app.services.sync.upsert import upsert_ebooks

logger = logging.getLogger(__name__)

WEREAD_BASE = "https://weread.qq.com"

# 微信读书 colorStyle → 颜色名
COLOR_MAP = {
    1: "pink",
    2: "purple",
    3: "blue",
    4: "green",
    5: "yellow",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_REQUEST_INTERVAL = 0.2


def _sanitize_cookie(raw: str) -> str:
    """对 cookie 值中的非 ASCII 字符做 URL 编码，确保 HTTP header 合规。"""
    parts = []
    for pair in raw.split("; "):
        if "=" in pair:
            key, value = pair.split("=", 1)
            value = urllib.parse.quote(value, safe="!#$&'()*+,/:;=?@[]~-._")
            parts.append(f"{key}={value}")
        else:
            parts.append(pair)
    return "; ".join(parts)


def _epoch_to_iso(ts: int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None).isoformat()


# ─── 异步 API 调用 ───────────────────────────────────────────────────────────

async def _fetch_notebooks(client: httpx.AsyncClient) -> list[dict]:
    resp = await client.get("/api/user/notebook")
    resp.raise_for_status()
    data = resp.json()
    return data.get("books", [])


async def _fetch_shelf(client: httpx.AsyncClient) -> dict:
    resp = await client.get("/web/shelf/sync")
    resp.raise_for_status()
    return resp.json()


async def _fetch_bookmarks(client: httpx.AsyncClient, book_id: str) -> list[dict]:
    resp = await client.get("/web/book/bookmarklist", params={"bookId": book_id})
    resp.raise_for_status()
    data = resp.json()
    return data.get("updated", [])


async def _fetch_reviews(client: httpx.AsyncClient, book_id: str) -> list[dict]:
    resp = await client.get(
        "/web/review/list",
        params={"bookId": book_id, "listType": "11", "mine": "1", "syncKey": "0"},
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("reviews", [])


async def _fetch_chapter_infos(client: httpx.AsyncClient, book_ids: list[str]) -> dict[str, dict[int, str]]:
    if not book_ids:
        return {}
    resp = await client.post(
        "/web/book/chapterInfos",
        json={"bookIds": book_ids, "synckeys": [0] * len(book_ids), "teenmode": 0},
    )
    resp.raise_for_status()
    result = {}
    for item in resp.json().get("data", []):
        bid = item.get("bookId", "")
        chapters = {}
        for ch in item.get("updated", []):
            chapters[ch["chapterUid"]] = ch.get("title", "")
        result[bid] = chapters
    return result


# ─── Fetcher 实现 ─────────────────────────────────────────────────────────────

class WechatReadFetcher(BaseSyncFetcher):

    async def validate_credential(self, credential_data: str) -> tuple[bool, str]:
        """验证 Cookie — 通过 notebooks 接口

        Returns:
            (valid, reason):
            - (True, "") — 凭证有效
            - (False, "missing_fields") — 缺少 wr_skey 或 wr_vid
            - (False, "expired") — Cookie 已过期
            - (False, "error") — 请求异常
        """
        # 检查关键字段是否存在
        cookie_keys = {
            k.strip(): v.strip()
            for pair in credential_data.split(";")
            if "=" in pair
            for k, v in [pair.split("=", 1)]
        }
        if "wr_skey" not in cookie_keys or "wr_vid" not in cookie_keys:
            return False, "missing_fields"

        headers = {**_HEADERS, "Cookie": _sanitize_cookie(credential_data)}
        try:
            async with httpx.AsyncClient(
                base_url=WEREAD_BASE, headers=headers,
                timeout=15, follow_redirects=True,
            ) as client:
                resp = await client.get("/api/user/notebook")
                if resp.status_code == 401:
                    return False, "expired"
                data = resp.json()
                errcode = data.get("errcode", 0)
                if errcode in (-2012, -2010):
                    return False, "expired"
                if "books" in data:
                    return True, ""
                return False, "expired"
        except Exception:
            return False, "error"

    async def fetch_and_sync(self, db, source, credential_data, options, on_progress=None):
        headers = {**_HEADERS, "Cookie": _sanitize_cookie(credential_data)}

        try:
            async with httpx.AsyncClient(
                base_url=WEREAD_BASE, headers=headers,
                timeout=30, follow_redirects=True,
            ) as client:
                # Phase 1: 获取有笔记的书列表
                if on_progress:
                    await on_progress(SyncProgress(
                        phase="fetching",
                        message="正在获取微信读书笔记列表...",
                    ))

                notebooks = await _fetch_notebooks(client)

                if on_progress:
                    await on_progress(SyncProgress(
                        phase="fetching",
                        message=f"有笔记的书: {len(notebooks)} 本，正在获取书架...",
                    ))

                # Phase 2: 获取书架（含阅读进度）
                shelf_data = await _fetch_shelf(client)
                progress_map = {}
                for bp in shelf_data.get("bookProgress", []):
                    progress_map[str(bp.get("bookId", ""))] = bp

                # Phase 3: 获取章节信息
                book_ids = [str(nb.get("bookId", "")) for nb in notebooks if nb.get("bookId")]

                if on_progress:
                    await on_progress(SyncProgress(
                        phase="fetching",
                        message="正在获取章节信息...",
                    ))

                chapter_map = await _fetch_chapter_infos(client, book_ids)

                # Phase 4: 逐书获取标注
                total_books = len(notebooks)
                books_payload = []

                for idx, nb in enumerate(notebooks):
                    book_id = str(nb.get("bookId", ""))
                    book_info = nb.get("book", {})
                    title = book_info.get("title", "未知书名")
                    author = book_info.get("author", "")

                    if on_progress:
                        await on_progress(SyncProgress(
                            phase="fetching",
                            message=f"获取标注: {title[:30]} ({idx + 1}/{total_books})",
                            current=idx + 1,
                            total=total_books,
                        ))

                    # 分类
                    categories = book_info.get("categories", [])
                    genre = categories[0].get("title", "") if categories else None

                    # 阅读进度
                    bp = progress_map.get(book_id, {})
                    raw_progress = bp.get("progress", 0)
                    reading_progress = raw_progress / 100.0 if raw_progress else 0.0
                    is_finished = raw_progress >= 100 or book_info.get("finishReading", 0) == 1
                    if is_finished:
                        reading_progress = 1.0

                    # 获取划线
                    await asyncio.sleep(_REQUEST_INTERVAL)
                    bookmarks = await _fetch_bookmarks(client, book_id)

                    # 获取想法
                    await asyncio.sleep(_REQUEST_INTERVAL)
                    reviews = await _fetch_reviews(client, book_id)

                    # 跳过无标注的书
                    if not bookmarks and not reviews:
                        continue

                    # 章节映射
                    chapters = chapter_map.get(book_id, {})

                    # 组装标注
                    annotations = []

                    for bm in bookmarks:
                        bm_id = bm.get("bookmarkId", "")
                        if not bm_id:
                            continue
                        color_style = bm.get("colorStyle", 0)
                        color = COLOR_MAP.get(color_style, "yellow")
                        chapter_uid = bm.get("chapterUid")
                        chapter_name = chapters.get(chapter_uid, "") if chapter_uid else None

                        annotations.append({
                            "id": bm_id,
                            "selected_text": bm.get("markText", ""),
                            "note": None,
                            "color": color,
                            "type": "highlight",
                            "chapter": chapter_name,
                            "is_deleted": False,
                            "created_at": _epoch_to_iso(bm.get("createTime")),
                        })

                    for rv in reviews:
                        review = rv.get("review", {})
                        review_id = review.get("reviewId", "")
                        if not review_id:
                            continue
                        if review.get("type", 1) == 4:
                            continue

                        chapter_uid = review.get("chapterUid")
                        chapter_name = chapters.get(chapter_uid, "") if chapter_uid else None

                        annotations.append({
                            "id": review_id,
                            "selected_text": review.get("abstract", ""),
                            "note": review.get("content", ""),
                            "color": "yellow",
                            "type": "note",
                            "chapter": chapter_name or review.get("chapterTitle", ""),
                            "is_deleted": False,
                            "created_at": _epoch_to_iso(review.get("createTime")),
                        })

                    books_payload.append({
                        "asset_id": book_id,
                        "title": title,
                        "author": author,
                        "genre": genre,
                        "is_finished": is_finished,
                        "reading_progress": reading_progress,
                        "annotations": annotations,
                    })

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return SyncResult(success=False, error="Cookie 已过期，请更新凭证")
            return SyncResult(success=False, error=f"微信读书 API 请求失败: {e}")
        except Exception as e:
            return SyncResult(success=False, error=f"获取数据失败: {e}")

        if not books_payload:
            if on_progress:
                await on_progress(SyncProgress(phase="done", message="没有需要同步的数据"))
            return SyncResult(success=True, stats={
                "new_books": 0, "updated_books": 0,
                "new_annotations": 0, "updated_annotations": 0, "deleted_annotations": 0,
            })

        # Phase 5: Upsert to DB
        if on_progress:
            total_ann = sum(len(b["annotations"]) for b in books_payload)
            await on_progress(SyncProgress(
                phase="syncing",
                message=f"正在写入 {len(books_payload)} 本书, {total_ann} 条标注...",
                current=0,
                total=len(books_payload),
            ))

        stats = upsert_ebooks(db, source, books_payload)

        if on_progress:
            await on_progress(SyncProgress(
                phase="done",
                message=(
                    f"同步完成: 新增 {stats['new_books']} 本, "
                    f"更新 {stats['updated_books']} 本, "
                    f"新增 {stats['new_annotations']} 条标注"
                ),
                current=len(books_payload),
                total=len(books_payload),
            ))

        return SyncResult(success=True, stats=stats)

    @staticmethod
    def get_sync_options() -> list[dict]:
        return []
