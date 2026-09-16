"""Emby 媒体库同步 Fetcher — 只读拉取电影/剧集 + 观看状态，写入影视资料库

只调用 GET 接口。绝不调用 DELETE /Items/{id}（会连同磁盘文件一起删除）。
本期一律全量拉取（库存量级几十条），增量水位留作后续。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

import httpx

from app.core.time import utcnow
from app.models.credential import PlatformCredential
from app.services.film_library import mark_missing_from_emby, tmdb_external_id, upsert_films
from app.services.sync.base import BaseSyncFetcher, SyncProgress, SyncResult

logger = logging.getLogger(__name__)

_ITEM_FIELDS = ",".join([
    "ProviderIds", "Genres", "People", "Overview", "ProductionYear", "PremiereDate",
    "RunTimeTicks", "CommunityRating", "OfficialRating", "ProductionLocations",
    "DateCreated", "OriginalTitle", "UserData", "ImageTags",
])
_PAGE_SIZE = 200
_TICKS_PER_SECOND = 10_000_000


def _headers(api_key: str) -> dict:
    return {"X-Emby-Token": api_key, "Accept": "application/json"}


async def emby_system_info(base_url: str, api_key: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{base_url}/emby/System/Info", headers=_headers(api_key))
        resp.raise_for_status()
        return resp.json()


async def emby_resolve_user_id(base_url: str, api_key: str, user_name: str) -> str | None:
    """按用户名找 Emby 用户 Id（服务器级 key 可列出用户）"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{base_url}/emby/Users", headers=_headers(api_key))
        resp.raise_for_status()
        users = resp.json() or []
    for u in users:
        if (u.get("Name") or "").lower() == user_name.lower():
            return u.get("Id")
    return None


def _normalize_item(item: dict, synced_at: str) -> dict:
    """Emby Item → 规范化影片 dict（upsert_films 的输入格式）"""
    kind = "series" if item.get("Type") == "Series" else "movie"
    provider = item.get("ProviderIds") or {}
    # Emby 的 ProviderIds 键名大小写不固定（Tmdb / TMDB / tmdb）
    pids = {k.lower(): str(v) for k, v in provider.items() if v}
    tmdb = pids.get("tmdb")
    imdb = pids.get("imdb")
    tvdb = pids.get("tvdb")
    item_id = str(item.get("Id"))
    external_id = tmdb_external_id(kind, tmdb) if tmdb else f"emby:{item_id}"

    people = item.get("People") or []
    directors = [p["Name"] for p in people if p.get("Type") == "Director" and p.get("Name")]
    cast = [p["Name"] for p in people if p.get("Type") == "Actor" and p.get("Name")][:10]

    ticks = item.get("RunTimeTicks") or 0
    runtime_min = int(ticks / _TICKS_PER_SECOND / 60) if ticks else None
    ud = item.get("UserData") or {}
    pos_ticks = ud.get("PlaybackPositionTicks") or 0
    progress = round(pos_ticks / ticks, 2) if ticks and pos_ticks else 0.0
    premiere = item.get("PremiereDate") or ""

    emby_block = {
        "item_ids": [item_id],
        "in_library": True,
        "date_created": item.get("DateCreated"),
        "played": bool(ud.get("Played")),
        "play_count": int(ud.get("PlayCount") or 0),
        "playback_position_ticks": pos_ticks,
        "progress": progress,
        "last_played_at": ud.get("LastPlayedDate"),
        "is_favorite": bool(ud.get("IsFavorite")),
        "last_synced_at": synced_at,
    }
    if kind == "series":
        emby_block["episodes_total"] = None   # 由 _attach_episode_counts 填
        emby_block["episodes_played"] = None

    return {
        "external_id": external_id,
        "kind": kind,
        "title": item.get("Name") or "",
        "original_title": item.get("OriginalTitle") or None,
        "year": item.get("ProductionYear"),
        "release_date": premiere[:10] if premiere else None,
        "overview": item.get("Overview") or None,
        "genres": item.get("Genres") or [],
        "directors": directors,
        "cast": cast,
        "countries": item.get("ProductionLocations") or [],
        "runtime_min": runtime_min,
        "community_rating": item.get("CommunityRating"),
        "official_rating": item.get("OfficialRating") or None,
        "provider_ids": {"tmdb": tmdb, "imdb": imdb, "tvdb": tvdb},
        "poster": {"emby_item_id": item_id} if (item.get("ImageTags") or {}).get("Primary") else {},
        "emby": emby_block,
        "source": "emby",
    }


def _merge_duplicates(films: list[dict]) -> list[dict]:
    """同一 external_id 的多个 Emby 条目（两块盘各一份）合并为一条"""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for f in films:
        grouped[f["external_id"]].append(f)
    merged: list[dict] = []
    for external_id, group in grouped.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        primary = max(group, key=lambda f: (bool(f.get("overview")), len(f.get("directors") or [])))
        emby = dict(primary["emby"])
        emby["item_ids"] = sorted({iid for f in group for iid in f["emby"]["item_ids"]})
        emby["play_count"] = sum(f["emby"]["play_count"] for f in group)
        emby["played"] = any(f["emby"]["played"] for f in group)
        emby["is_favorite"] = any(f["emby"]["is_favorite"] for f in group)
        emby["progress"] = max(f["emby"]["progress"] for f in group)
        emby["playback_position_ticks"] = max(f["emby"]["playback_position_ticks"] for f in group)
        emby["last_played_at"] = max((f["emby"]["last_played_at"] or "" for f in group)) or None
        emby["date_created"] = min((f["emby"]["date_created"] or "~" for f in group)).replace("~", "") or None
        primary = dict(primary)
        primary["emby"] = emby
        merged.append(primary)
    return merged


class EmbyFetcher(BaseSyncFetcher):

    async def validate_credential(self, credential_data: str) -> tuple[bool, str]:
        # 基类签名只有 key；base_url 在凭证 extra_info 里，完整验证走 credentials 路由的 _validate_credential
        return (True, "") if credential_data.strip() else (False, "missing_fields")

    async def fetch_and_sync(self, db, source, credential_data, options, on_progress=None):
        cred: PlatformCredential | None = source.credential
        extra = cred.extra_info if cred and isinstance(cred.extra_info, dict) else {}
        base_url = (extra.get("base_url") or "").rstrip("/")
        if not base_url:
            return SyncResult(success=False, error="凭证缺少 base_url，请在平台凭证里重新保存 Emby 凭证")
        api_key = credential_data.strip()
        user_id = extra.get("user_id")
        user_name = extra.get("user_name") or "emby"

        if on_progress:
            await on_progress(SyncProgress(phase="fetching", message="正在连接 Emby..."))

        try:
            if not user_id:
                user_id = await emby_resolve_user_id(base_url, api_key, user_name)
                if not user_id:
                    return SyncResult(success=False, error=f"Emby 中找不到用户 {user_name}")
                extra = {**extra, "user_id": user_id}
                cred.extra_info = extra
                db.commit()

            items = await self._fetch_all_items(base_url, api_key, user_id, on_progress)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return SyncResult(success=False, error="Emby API key 无效或已失效")
            return SyncResult(success=False, error=f"Emby API 请求失败: {e}")
        except Exception as e:  # noqa: BLE001
            return SyncResult(success=False, error=f"获取 Emby 数据失败: {e}")

        synced_at = utcnow().isoformat()
        films = [_normalize_item(it, synced_at) for it in items]

        # 剧集：统计已看集数
        series = [f for f in films if f["kind"] == "series"]
        if series and on_progress:
            await on_progress(SyncProgress(phase="fetching", message=f"正在统计 {len(series)} 部剧集的观看进度..."))
        for f in series:
            try:
                total, played = await self._episode_counts(base_url, api_key, user_id, f["emby"]["item_ids"][0])
                f["emby"]["episodes_total"] = total
                f["emby"]["episodes_played"] = played
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Emby episode count failed for {f['title']}: {e}")

        films = _merge_duplicates(films)
        total = len(films)
        if total == 0:
            mark_missing_from_emby(db, [])
            if on_progress:
                await on_progress(SyncProgress(phase="done", message="Emby 库为空"))
            return SyncResult(success=True, stats={"new_films": 0, "updated_films": 0, "removed_from_emby": 0})

        new_total = updated_total = autofilled_total = 0
        seen_ids: list[str] = []
        batch_size = 50
        for i in range(0, total, batch_size):
            batch = films[i:i + batch_size]
            if on_progress:
                await on_progress(SyncProgress(
                    phase="syncing",
                    message=f"正在写入影片 ({min(i + batch_size, total)}/{total})...",
                    current=min(i + batch_size, total), total=total,
                ))
            stats = upsert_films(db, source, batch)
            new_total += stats["new_films"]
            updated_total += stats["updated_films"]
            autofilled_total += stats["autofilled"]
            seen_ids.extend(stats["content_ids"])

        removed = mark_missing_from_emby(db, seen_ids)

        result_stats = {
            "new_films": new_total,
            "updated_films": updated_total,
            "autofilled": autofilled_total,
            "removed_from_emby": removed,
            "message": f"同步完成: 新增 {new_total}, 更新 {updated_total}, 自动标记看过 {autofilled_total}, 已不在 Emby {removed}",
        }
        if on_progress:
            await on_progress(SyncProgress(phase="done", message=result_stats["message"], current=total, total=total))
        return SyncResult(success=True, stats=result_stats)

    async def _fetch_all_items(self, base_url, api_key, user_id, on_progress=None) -> list[dict]:
        """分页列出 Movie/Series，再逐条补全 UserData。

        列表接口返回的 UserData 是精简版（缺 LastPlayedDate、PlayCount 不准，2026-09-16 实测），
        单条接口 /Users/{uid}/Items/{id} 才是完整的，所以每条再查一次（本机调用，几十条秒级完成）。
        """
        items: list[dict] = []
        start = 0
        async with httpx.AsyncClient(timeout=60, headers=_headers(api_key)) as client:
            while True:
                resp = await client.get(
                    f"{base_url}/emby/Users/{user_id}/Items",
                    params={
                        "IncludeItemTypes": "Movie,Series",
                        "Recursive": "true",
                        "Fields": _ITEM_FIELDS,
                        "StartIndex": start,
                        "Limit": _PAGE_SIZE,
                        "SortBy": "SortName",
                    },
                )
                resp.raise_for_status()
                data = resp.json() or {}
                page = data.get("Items") or []
                items.extend(page)
                total = data.get("TotalRecordCount") or len(items)
                if on_progress:
                    await on_progress(SyncProgress(
                        phase="fetching", message=f"正在拉取 Emby 库存 ({len(items)}/{total})...",
                        current=len(items), total=total,
                    ))
                start += len(page)
                if not page or start >= total:
                    break

            # 逐条补全 UserData（限并发 8）
            sem = asyncio.Semaphore(8)

            async def _enrich(item: dict):
                async with sem:
                    try:
                        resp = await client.get(f"{base_url}/emby/Users/{user_id}/Items/{item['Id']}")
                        resp.raise_for_status()
                        full = resp.json() or {}
                        if isinstance(full.get("UserData"), dict):
                            item["UserData"] = full["UserData"]
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"Emby UserData enrich failed for {item.get('Name')}: {e}")

            if on_progress:
                await on_progress(SyncProgress(phase="fetching", message=f"正在补全 {len(items)} 条观看记录...", current=0, total=len(items)))
            await asyncio.gather(*(_enrich(it) for it in items))
        return items

    async def _episode_counts(self, base_url, api_key, user_id, series_id) -> tuple[int, int]:
        async with httpx.AsyncClient(timeout=30, headers=_headers(api_key)) as client:
            resp = await client.get(
                f"{base_url}/emby/Shows/{series_id}/Episodes",
                params={"UserId": user_id, "Fields": "UserData", "Limit": 2000},
            )
            resp.raise_for_status()
            eps = (resp.json() or {}).get("Items") or []
        played = sum(1 for e in eps if (e.get("UserData") or {}).get("Played"))
        return len(eps), played

    @staticmethod
    def get_sync_options() -> list[dict]:
        return []
