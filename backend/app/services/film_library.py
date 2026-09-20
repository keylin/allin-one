"""影视资料库服务 — 影片 upsert、用户标记、TMDb 客户端、序列化

影片 = ContentItem（source_type: sync.emby / user.film），元数据与 Emby 观看事实存 raw_data，
用户标记存 watch_records。三层数据的覆盖规则见 docs/design_film_library.md §2。

供 API 路由、Emby Fetcher、MCP server 共用。
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import utcnow
from app.models.content import ContentItem, ContentStatus, SourceConfig, SourceType
from app.models.content import ContentKind
from app.models.credential import PlatformCredential
from app.models.film import WatchLog, WatchRecord, WATCH_STATUSES
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

# 影片可以落在这两种数据源下（仅用于建源与归属；「是不是影片」一律看 kind，见 IS_FILM）
FILM_SOURCE_TYPES = (SourceType.SYNC_EMBY.value, SourceType.USER_FILM.value)
# 影片身份判定：不依赖所属数据源，删源/换源都不影响
IS_FILM = ContentItem.kind == ContentKind.FILM.value
KINDS = ("movie", "series")

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"


# ─── 身份键 ───────────────────────────────────────────────────────────────────

def tmdb_external_id(kind: str, tmdb_id: str | int) -> str:
    return f"tmdb:{kind}:{tmdb_id}"


def manual_external_id(title: str, year: int | None) -> str:
    key = f"{title.strip().lower()}|{year or ''}"
    return f"manual:{uuid.uuid5(uuid.NAMESPACE_URL, key).hex}"


def parse_external_id(external_id: str) -> dict:
    """tmdb:movie:603 → {"scheme": "tmdb", "kind": "movie", "id": "603"}"""
    parts = (external_id or "").split(":")
    if len(parts) == 3 and parts[0] == "tmdb":
        return {"scheme": "tmdb", "kind": parts[1], "id": parts[2]}
    if len(parts) == 2:
        return {"scheme": parts[0], "kind": None, "id": parts[1]}
    return {"scheme": None, "kind": None, "id": external_id}


# ─── 源与凭证 ─────────────────────────────────────────────────────────────────

def get_or_create_film_source(db: Session, source_type: str) -> SourceConfig:
    """获取 sync.emby / user.film 的 SourceConfig，不存在则创建"""
    if source_type not in FILM_SOURCE_TYPES:
        raise ValueError(f"不是影视源类型: {source_type}")
    source = db.query(SourceConfig).filter(SourceConfig.source_type == source_type).first()
    if source:
        return source
    name = "Emby" if source_type == SourceType.SYNC_EMBY.value else "手工影片"
    source = SourceConfig(
        id=uuid.uuid4().hex,
        name=name,
        source_type=source_type,
        schedule_enabled=False,
        schedule_mode="manual",
        is_active=True,
    )
    db.add(source)
    db.commit()
    logger.info(f"Created film source: {source.id} ({source_type})")
    return source


def get_emby_connection(db: Session) -> dict | None:
    """读取 sync.emby 源绑定的凭证 → {base_url, api_key, user_id, user_name}；未配置返回 None"""
    from app.core.crypto import decrypt_credential

    source = db.query(SourceConfig).filter(
        SourceConfig.source_type == SourceType.SYNC_EMBY.value,
    ).first()
    if not source or not source.credential_id:
        return None
    cred = db.get(PlatformCredential, source.credential_id)
    if not cred:
        return None
    extra = cred.extra_info if isinstance(cred.extra_info, dict) else {}
    base_url = (extra.get("base_url") or "").rstrip("/")
    if not base_url:
        return None
    return {
        "base_url": base_url,
        "api_key": decrypt_credential(cred.credential_data),
        "user_id": extra.get("user_id"),
        "user_name": extra.get("user_name") or "emby",
        "server_id": extra.get("server_id"),
    }


def emby_item_url(conn: dict | None, item_id: str | None) -> str | None:
    """Emby 网页端条目页直达链接；base_url 是 LAN 地址，浏览器同样可达"""
    if not conn or not item_id:
        return None
    url = f"{conn['base_url']}/web/index.html#!/item?id={item_id}"
    if conn.get("server_id"):
        url += f"&serverId={conn['server_id']}"
    return url


def get_tmdb_api_key(db: Session) -> str:
    from app.core.crypto import decrypt_credential

    row = db.get(SystemSetting, "tmdb_api_key")
    if not row or not row.value:
        return ""
    return decrypt_credential(row.value)


# ─── TMDb 客户端 ──────────────────────────────────────────────────────────────

def _tmdb_get(api_key: str, path: str, params: dict | None = None) -> dict:
    query = {"api_key": api_key, "language": "zh-CN", **(params or {})}
    with httpx.Client(timeout=15) as client:
        resp = client.get(f"{TMDB_API_BASE}{path}", params=query)
        resp.raise_for_status()
        return resp.json()


def tmdb_search(api_key: str, q: str, year: int | None = None, limit: int = 10) -> list[dict]:
    """TMDb multi 搜索 → 候选列表（只保留 movie/tv）"""
    data = _tmdb_get(api_key, "/search/multi", {"query": q, "include_adult": "false", "page": 1})
    results = []
    for item in data.get("results", []):
        media_type = item.get("media_type")
        if media_type not in ("movie", "tv"):
            continue
        kind = "movie" if media_type == "movie" else "series"
        rel = item.get("release_date") or item.get("first_air_date") or ""
        item_year = int(rel[:4]) if rel[:4].isdigit() else None
        if year and item_year and abs(item_year - year) > 1:
            continue
        results.append({
            "tmdb_id": str(item.get("id")),
            "kind": kind,
            "title": item.get("title") or item.get("name") or "",
            "original_title": item.get("original_title") or item.get("original_name") or "",
            "year": item_year,
            "overview": (item.get("overview") or "")[:300],
            "poster_path": item.get("poster_path"),
            "vote_average": item.get("vote_average"),
        })
        if len(results) >= limit:
            break
    return results


def tmdb_details(api_key: str, kind: str, tmdb_id: str | int) -> dict:
    """TMDb 详情 → 规范化影片 dict（见 normalize_film 的字段）"""
    path = f"/movie/{tmdb_id}" if kind == "movie" else f"/tv/{tmdb_id}"
    extra = "credits,external_ids" if kind == "movie" else "credits,aggregate_credits,external_ids"
    data = _tmdb_get(api_key, path, {"append_to_response": extra})
    credits = data.get("credits") or {}
    if kind == "movie":
        directors = [p["name"] for p in credits.get("crew", []) if p.get("job") == "Director"]
        release = data.get("release_date") or ""
        runtime = data.get("runtime")
        title = data.get("title") or ""
        original_title = data.get("original_title") or ""
        cast = [p["name"] for p in credits.get("cast", [])[:10] if p.get("name")]
    else:
        # 剧集：created_by 常为空（尤其国产剧），退到 aggregate_credits 里的导演
        directors = [p["name"] for p in data.get("created_by", []) if p.get("name")]
        if not directors:
            agg = data.get("aggregate_credits") or {}
            seen: list[str] = []
            for p in agg.get("crew", []):
                if any((j.get("job") or "") == "Director" for j in p.get("jobs", [])) and p.get("name") and p["name"] not in seen:
                    seen.append(p["name"])
            directors = seen[:3]
        release = data.get("first_air_date") or ""
        runtimes = data.get("episode_run_time") or []
        runtime = runtimes[0] if runtimes else None
        title = data.get("name") or ""
        original_title = data.get("original_name") or ""
        agg_cast = (data.get("aggregate_credits") or {}).get("cast") or credits.get("cast", [])
        cast = [p["name"] for p in agg_cast[:10] if p.get("name")]
    countries = [c.get("iso_3166_1") for c in data.get("production_countries", []) if c.get("iso_3166_1")]
    if not countries and kind == "series":
        countries = data.get("origin_country") or []
    ext = data.get("external_ids") or {}
    return {
        "external_id": tmdb_external_id(kind, data["id"]),
        "kind": kind,
        "title": title,
        "original_title": original_title,
        "year": int(release[:4]) if release[:4].isdigit() else None,
        "release_date": release or None,
        "overview": data.get("overview") or "",
        "genres": [g["name"] for g in data.get("genres", []) if g.get("name")],
        "directors": directors,
        "cast": cast,
        "countries": countries,
        "runtime_min": runtime,
        "community_rating": data.get("vote_average"),
        "official_rating": None,
        "provider_ids": {
            "tmdb": str(data["id"]),
            "imdb": ext.get("imdb_id") or data.get("imdb_id"),
            "tvdb": str(ext["tvdb_id"]) if ext.get("tvdb_id") else None,
        },
        "poster": {"tmdb_path": data.get("poster_path")},
        "source": "tmdb",
    }


def enrich_film(db: Session, content: ContentItem) -> tuple[bool, str]:
    """为记录补全元数据（TMDb 详情：ID/海报/导演/主演/类型/中文简介）。返回 (changed, reason)"""
    raw = content.raw_data if isinstance(content.raw_data, dict) else {}
    kind = raw.get("kind") or "movie"
    year = raw.get("year")
    tmdb = (raw.get("provider_ids") or {}).get("tmdb")

    api_key = get_tmdb_api_key(db)
    if not api_key:
        return False, "未配置 TMDb API Key（系统设置 · 影视资料库）"
    film: dict | None = None
    try:
        if tmdb:
            film = tmdb_details(api_key, kind, tmdb)
        else:
            hits = tmdb_search(api_key, content.title, year, limit=1)
            if hits:
                film = tmdb_details(api_key, hits[0]["kind"], hits[0]["tmdb_id"])
    except httpx.HTTPError as e:
        return False, f"TMDb 请求失败: {e}"
    if film is None:
        return False, "TMDb 没有搜索结果"

    new_external_id = film.get("external_id")
    if new_external_id and new_external_id != content.external_id:
        other = _find_film(db, new_external_id)
        if other and other.id != content.id:
            return False, f"与已有记录重复: {other.title} ({other.id})"
        content.external_id = new_external_id
        db.flush()
    film["external_id"] = content.external_id
    # 骨架记录的年份/片名以用户输入为准，搜索结果只补缺
    if year:
        film["year"] = year
    film["title"] = content.title
    source = db.get(SourceConfig, content.source_id) if content.source_id else None
    if source is None:
        source = get_or_create_film_source(db, SourceType.USER_FILM.value)
    upsert_films(db, source, [film])
    return True, film.get("source") or "enriched"


def enrichment_state(raw: dict, tmdb_configured: bool) -> str:
    """一条记录的元数据完整度：full / partial / skeleton / failed

    - skeleton：缺 TMDb ID 或海报
    - partial：有 ID/海报但从未拉过 TMDb/Emby 完整详情（历史遗留的 Emby 搜索结果）
    - full：来源含 emby 或 tmdb
    - failed：补全失败过，等单条重试
    """
    if raw.get("enrich_failed"):
        return "failed"
    poster = raw.get("poster") or {}
    has_poster = bool(poster.get("emby_item_id") or poster.get("tmdb_path"))
    has_tmdb = bool((raw.get("provider_ids") or {}).get("tmdb"))
    if not has_poster or not has_tmdb:
        return "skeleton"
    sources = raw.get("sources") or []
    if "emby" in sources or "tmdb" in sources:
        # 已经拉过完整详情；个别字段为空是上游数据本身没有，不再重复补
        return "full"
    return "partial"


def needs_enrichment(raw: dict, tmdb_configured: bool) -> bool:
    if not tmdb_configured:
        return False
    return enrichment_state(raw, tmdb_configured) in ("skeleton", "partial")


def find_unenriched(db: Session, limit: int = 50) -> list[ContentItem]:
    """需要补全的影视记录：骨架 + partial（都靠 TMDb 详情补），按创建时间取前 limit 条"""
    tmdb_configured = bool(get_tmdb_api_key(db))
    rows = (
        db.query(ContentItem)
        .filter(IS_FILM)
        .order_by(ContentItem.created_at.asc())
        .all()
    )
    out = []
    for c in rows:
        raw = c.raw_data if isinstance(c.raw_data, dict) else {}
        if needs_enrichment(raw, tmdb_configured):
            out.append(c)
            if len(out) >= limit:
                break
    return out


# ─── 豆瓣条目解析（只为拼直达链接；软依赖，失败退回搜索页） ─────────────────────

_DOUBAN_SUGGEST = "https://movie.douban.com/j/subject_suggest"
_DOUBAN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://movie.douban.com/",
    "Accept": "application/json",
}


def douban_resolve(title: str, original_title: str | None, year: int | None) -> str | None:
    """用豆瓣的联想接口按片名（其次原名）找条目 id；年份差 >1 不认。找不到返回 None。"""
    def _query(q: str) -> list[dict]:
        with httpx.Client(timeout=15, headers=_DOUBAN_HEADERS) as client:
            resp = client.get(_DOUBAN_SUGGEST, params={"q": q})
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

    def _pick(results: list[dict], q: str) -> str | None:
        cands = []
        for r in results:
            if r.get("type") not in ("movie", "tv", None):
                continue
            ry = r.get("year")
            try:
                ry = int(ry) if ry else None
            except ValueError:
                ry = None
            if year and ry and abs(ry - int(year)) > 1:
                continue
            score = 0
            if (r.get("title") or "").strip() == q.strip() or (r.get("sub_title") or "").strip() == q.strip():
                score += 2
            if year and ry == int(year):
                score += 1
            cands.append((score, r))
        if not cands:
            return None
        cands.sort(key=lambda c: -c[0])
        best = cands[0][1]
        return str(best.get("id")) if best.get("id") else None

    for q in [t for t in (title, original_title) if t]:
        try:
            hit = _pick(_query(q), q)
        except (httpx.HTTPError, ValueError):
            return None
        if hit:
            return hit
    return None


def douban_url_for(raw: dict, title: str) -> str:
    """有豆瓣 id 直达条目页；否则按 IMDb id（豆瓣能索引）或片名+年份进搜索页"""
    pids = raw.get("provider_ids") or {}
    if pids.get("douban"):
        return f"https://movie.douban.com/subject/{pids['douban']}/"
    q = pids.get("imdb") or " ".join(str(x) for x in (title, raw.get("year")) if x)
    from urllib.parse import quote
    return f"https://www.douban.com/search?cat=1002&q={quote(q)}"


class DoubanThrottled(Exception):
    """豆瓣联想接口被限流：对已知存在的片也返回空列表。此时不得把记录标成 douban_failed。"""


def douban_probe() -> bool:
    """探针：查一部必定存在的片，返回空即视为被限流"""
    try:
        with httpx.Client(timeout=15, headers=_DOUBAN_HEADERS) as client:
            resp = client.get(_DOUBAN_SUGGEST, params={"q": "霸王别姬"})
            resp.raise_for_status()
            data = resp.json()
            return isinstance(data, list) and len(data) > 0
    except (httpx.HTTPError, ValueError):
        return False


# ─── Upsert ───────────────────────────────────────────────────────────────────

_META_FIELDS = (
    "kind", "year", "release_date", "original_title", "overview", "genres", "directors",
    "cast", "countries", "runtime_min", "community_rating", "official_rating",
)


def _find_film(db: Session, external_id: str, emby_item_ids: list[str] | None = None) -> ContentItem | None:
    """按 external_id（不限来源）查找影片；找不到再按 raw_data.emby.item_ids 找（Emby 条目后补 TMDb ID 的情形）"""
    base = (
        db.query(ContentItem)
        .filter(IS_FILM)
    )
    content = base.filter(ContentItem.external_id == external_id).first()
    if content or not emby_item_ids:
        return content
    conds = [ContentItem.raw_data["emby"]["item_ids"].contains([iid]) for iid in emby_item_ids]
    return base.filter(or_(*conds)).first()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def upsert_films(db: Session, source: SourceConfig, films: list[dict]) -> dict:
    """批量 upsert 影片。films 元素为规范化 dict：

    {external_id, kind, title, original_title?, year?, release_date?, overview?, genres?, directors?,
     cast?, countries?, runtime_min?, community_rating?, official_rating?, provider_ids?, poster?,
     emby?: {...}, source: "emby"|"tmdb"|"manual"}

    规则：元数据整体覆盖（None 不覆盖）；emby 块整体覆盖；用户标记只填空不覆盖。
    返回 {"new_films", "updated_films", "autofilled", "content_ids": [...]}
    """
    stats = {"new_films": 0, "updated_films": 0, "autofilled": 0, "content_ids": []}
    emby_conn = get_emby_connection(db)   # 海报落盘用（Emby 图走本地，TMDb 图出网一次）

    for film in films:
        external_id = film.get("external_id")
        if not external_id or not film.get("title"):
            continue
        emby_block = film.get("emby")
        emby_item_ids = (emby_block or {}).get("item_ids") or []

        content = _find_film(db, external_id, emby_item_ids)
        is_new = content is None
        if is_new:
            content = ContentItem(
                kind=ContentKind.FILM.value,
                id=uuid.uuid4().hex,
                source_id=source.id,
                external_id=external_id,
                title=film["title"],
                status=ContentStatus.READY.value,
                raw_data={},
            )
            db.add(content)
            stats["new_films"] += 1
        else:
            stats["updated_films"] += 1
            # Emby 条目从 emby:<id> 升级为 tmdb:* 时改写 external_id
            if content.external_id != external_id and external_id.startswith("tmdb:"):
                content.external_id = external_id
            content.title = film["title"] or content.title
            content.updated_at = utcnow()

        raw = dict(content.raw_data) if isinstance(content.raw_data, dict) else {}
        for key in _META_FIELDS:
            value = film.get(key)
            if value is not None and value != [] and value != "":
                raw[key] = value
        if film.get("provider_ids"):
            merged = dict(raw.get("provider_ids") or {})
            merged.update({k: v for k, v in film["provider_ids"].items() if v})
            raw["provider_ids"] = merged
        if film.get("poster"):
            poster = dict(raw.get("poster") or {})
            poster.update({k: v for k, v in film["poster"].items() if v})
            raw["poster"] = poster
            if content.id:
                cache_poster(content.id, poster, emby_conn)
        if emby_block is not None:
            raw["emby"] = emby_block
        src = film.get("source") or "manual"
        sources = list(raw.get("sources") or [])
        if src not in sources:
            sources.append(src)
        raw["sources"] = sources
        raw.setdefault("source", src)
        if src == "emby":
            raw["source"] = "emby"
        content.raw_data = raw

        # 冗余展示字段
        directors = raw.get("directors") or []
        content.author = " / ".join(directors[:3]) if directors else content.author
        tmdb_id = (raw.get("provider_ids") or {}).get("tmdb")
        if tmdb_id:
            slug = "movie" if raw.get("kind") == "movie" else "tv"
            content.url = f"https://www.themoviedb.org/{slug}/{tmdb_id}"
        elif emby_item_ids:
            content.url = f"emby://item/{emby_item_ids[0]}"
        if raw.get("release_date"):
            content.published_at = _parse_dt(raw["release_date"])
        elif raw.get("year") and not content.published_at:
            content.published_at = datetime(int(raw["year"]), 1, 1)

        db.flush()

        # 用户标记：确保存在；Emby played → 只填空
        record = db.query(WatchRecord).filter(WatchRecord.content_id == content.id).first()
        if not record:
            record = WatchRecord(id=uuid.uuid4().hex, content_id=content.id, status="unmarked", tags=[])
            db.add(record)
        if emby_block and emby_block.get("played") and record.status == "unmarked":
            record.status = "watched"
            record.status_source = "emby_autofill"
            last = _parse_dt(emby_block.get("last_played_at"))
            log = ensure_log(db, record)
            log.watched_at = last.date() if last else None
            log.watched_precision = "day" if last else None
            sync_record_from_logs(record)
            record.updated_at = utcnow()
            stats["autofilled"] += 1
        elif (
            emby_block and record.status_source == "emby_autofill"
            and record.watched_at is None and emby_block.get("last_played_at")
        ):
            # 自动填过"看过"但当时没拿到日期：补日期（仍属自动填充，不碰 manual 行）
            last = _parse_dt(emby_block.get("last_played_at"))
            if last:
                log = ensure_log(db, record)
                log.watched_at = last.date()
                log.watched_precision = "day"
                sync_record_from_logs(record)
                record.updated_at = utcnow()

        stats["content_ids"].append(content.id)

    source.last_collected_at = utcnow()
    db.commit()
    return stats


def mark_missing_from_emby(db: Session, seen_content_ids: list[str]) -> int:
    """本次同步未出现、但 raw_data.emby.in_library=true 的记录 → in_library=false（记录保留）"""
    query = (
        db.query(ContentItem)
        .filter(IS_FILM)
        .filter(ContentItem.raw_data["emby"]["in_library"].astext == "true")
    )
    if seen_content_ids:
        query = query.filter(~ContentItem.id.in_(seen_content_ids))
    count = 0
    for content in query.all():
        raw = dict(content.raw_data)
        emby = dict(raw.get("emby") or {})
        emby["in_library"] = False
        raw["emby"] = emby
        content.raw_data = raw
        content.updated_at = utcnow()
        count += 1
    if count:
        db.commit()
    return count


# ─── 手工添加 / 解析 ──────────────────────────────────────────────────────────

def resolve_or_create_film(
    db: Session,
    *,
    tmdb_id: str | None = None,
    kind: str | None = None,
    content_id: str | None = None,
    title: str | None = None,
    year: int | None = None,
) -> tuple[ContentItem | None, str | None]:
    """按 content_id / tmdb_id / 片名+年份 定位影片；不存在则（尽量经 TMDb）创建。返回 (content, error)"""
    if content_id:
        content = db.get(ContentItem, content_id)
        return (content, None) if content else (None, f"content_id 不存在: {content_id}")

    api_key = get_tmdb_api_key(db)

    if tmdb_id:
        kind = kind if kind in KINDS else "movie"
        existing = _find_film(db, tmdb_external_id(kind, tmdb_id))
        if existing:
            return existing, None
        film: dict | None = None
        if api_key:
            try:
                film = tmdb_details(api_key, kind, tmdb_id)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"TMDb details failed for {kind}/{tmdb_id}: {e}")
        if film is None:
            if not title:
                return None, "TMDb 不可用且未提供片名，无法创建"
            film = {
                "external_id": tmdb_external_id(kind, tmdb_id),
                "kind": kind, "title": title, "year": year,
                "provider_ids": {"tmdb": str(tmdb_id)}, "source": "manual",
            }
        source = get_or_create_film_source(db, SourceType.USER_FILM.value)
        stats = upsert_films(db, source, [film])
        return db.get(ContentItem, stats["content_ids"][0]), None

    if title:
        # 先按片名+年份在库内找（不区分来源）
        q = (
            db.query(ContentItem)
            .filter(IS_FILM)
            .filter(ContentItem.title.ilike(title.strip()))
        )
        if year:
            q = q.filter(ContentItem.raw_data["year"].astext == str(year))
        existing = q.first()
        if existing:
            return existing, None
        # TMDb 搜索取首条（年份匹配）
        if api_key:
            try:
                hits = tmdb_search(api_key, title, year, limit=1)
                if hits:
                    return resolve_or_create_film(db, tmdb_id=hits[0]["tmdb_id"], kind=hits[0]["kind"], title=title, year=year)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"TMDb search failed for {title!r}: {e}")
        kind = kind if kind in KINDS else "movie"
        film = {
            "external_id": manual_external_id(title, year),
            "kind": kind, "title": title.strip(), "year": year, "source": "manual",
        }
        source = get_or_create_film_source(db, SourceType.USER_FILM.value)
        stats = upsert_films(db, source, [film])
        return db.get(ContentItem, stats["content_ids"][0]), None

    return None, "需要 content_id、tmdb_id 或 title 之一"


# ─── 用户标记 ─────────────────────────────────────────────────────────────────

def get_or_create_record(db: Session, content_id: str) -> WatchRecord:
    record = db.query(WatchRecord).filter(WatchRecord.content_id == content_id).first()
    if not record:
        record = WatchRecord(id=uuid.uuid4().hex, content_id=content_id, status="unmarked", tags=[])
        db.add(record)
        db.flush()
    return record


def release_watched_at(content: ContentItem | None) -> tuple[date, str] | None:
    """「不记得」的取值：按上映时间近似（precision=release），没有上映信息则 None"""
    if content is None:
        return None
    raw = content.raw_data if isinstance(content.raw_data, dict) else {}
    rel = raw.get("release_date")
    if rel:
        try:
            return date.fromisoformat(str(rel)[:10]), "release"
        except ValueError:
            pass
    if raw.get("year"):
        return date(int(raw["year"]), 1, 1), "release"
    return None


def parse_watched_at(value: str) -> tuple[date, str] | None:
    """看过日期支持三种精度：YYYY → (YYYY-01-01, year)，YYYY-MM → (YYYY-MM-01, month)，YYYY-MM-DD → (date, day)"""
    v = value.strip()
    try:
        if len(v) == 4 and v.isdigit():
            return date(int(v), 1, 1), "year"
        if len(v) == 7 and v[4] == "-":
            return date(int(v[:4]), int(v[5:7]), 1), "month"
        return date.fromisoformat(v[:10]), "day"
    except ValueError:
        return None


def _date_label(watched_at: date | None, precision: str | None) -> str:
    if not watched_at:
        return "时间不详"
    p = precision or "day"
    if p == "release":
        return f"≈{watched_at.year}（上映）"
    if p == "year":
        return str(watched_at.year)
    if p == "month":
        return watched_at.strftime("%Y-%m")
    return watched_at.isoformat()


def watched_label(record: WatchRecord | None) -> str | None:
    """展示用：2019 / 2019-05 / 2019-05-03 / ≈2019（上映）/ 时间不详（仅看过时；取最近一次观看）"""
    if not record or record.status != "watched":
        return None
    return _date_label(record.watched_at, record.watched_precision)


# ─── 观看记录（watch_logs） ─────────────────────────────────────────────────

def _effective_date(log: WatchLog) -> date:
    """用于比较「哪次更近」的有效日期：
    - 没写日期 → 录入那天（刚记的一次视为最新；迁移来的老记录都落在迁移日）
    - 只记年 / 记到月 → 该区间的最后一天（2026-09 → 09-30），封顶到今天
    - 具体日期 / 按上映 → 该日期"""
    today = utcnow().date()
    if not log.watched_at:
        return (log.created_at or utcnow()).date()
    d, p = log.watched_at, log.watched_precision
    if p == "year":
        d = date(d.year, 12, 31)
    elif p == "month":
        d = (date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1))
    return min(d, today)


def _log_sort_key(log: WatchLog):
    # 最近一次 = 有效日期最新；同一天按录入先后
    return (_effective_date(log), log.created_at or datetime.min)


def sorted_logs(record: WatchRecord) -> list[WatchLog]:
    """最近一次在前"""
    return sorted(list(record.logs or []), key=_log_sort_key, reverse=True)


def latest_log(record: WatchRecord) -> WatchLog | None:
    logs = sorted_logs(record)
    return logs[0] if logs else None


def ensure_log(db: Session, record: WatchRecord) -> WatchLog:
    """没有任何观看记录时建一条空的并返回；否则返回最近一次"""
    log = latest_log(record)
    if log is None:
        log = WatchLog(id=uuid.uuid4().hex, record_id=record.id)
        record.logs.append(log)
        db.add(log)
        db.flush()
    return log


def new_log(db: Session, record: WatchRecord) -> WatchLog:
    """主动「再记一次」：默认观看日期 = 记录当天（精度 day），可改。
    与自动建的第一条（打分 / 点看过 → 时间不详）不同：主动新记的一次多半就是刚看完。"""
    log = WatchLog(id=uuid.uuid4().hex, record_id=record.id, watched_at=utcnow().date(), watched_precision="day")
    record.logs.append(log)
    db.add(log)
    db.flush()
    return log


def sync_record_from_logs(record: WatchRecord) -> None:
    """把「最近一次观看」的评分/日期缓存到 watch_records（列表排序、筛选、卡片用）。

    评分取最近一次**打了分**的观看（重看没打分时沿用上一次的分）；日期取最近一次观看。"""
    logs = sorted_logs(record)
    latest = logs[0] if logs else None
    record.watched_at = latest.watched_at if latest else None
    record.watched_precision = latest.watched_precision if latest else None
    rated = next((l for l in logs if l.my_rating is not None), None)
    record.my_rating = rated.my_rating if rated else None


def apply_log_update(log: WatchLog, data: dict, content: ContentItem | None = None) -> list[str]:
    """写一条观看记录：watched_at（YYYY / YYYY-MM / YYYY-MM-DD / release / 空）、my_rating、note"""
    errors: list[str] = []
    if "my_rating" in data:
        rating = data["my_rating"]
        if rating is not None and not (1 <= int(rating) <= 10):
            errors.append("my_rating 需在 1~10")
        else:
            log.my_rating = int(rating) if rating is not None else None
    if "watched_at" in data:
        value = data["watched_at"]
        if value == "release":
            # 详情页主动选「不记得（按上映）」：按上映时间近似，精度标为 release 与手填日期区分
            approx = release_watched_at(content)
            log.watched_at, log.watched_precision = approx if approx else (None, None)
        elif value in (None, ""):
            log.watched_at = None            # 时间不详（空着，以后补）
            log.watched_precision = None
        else:
            parsed = parse_watched_at(str(value))
            if not parsed:
                errors.append(f"watched_at 格式错误: {value}（支持 YYYY / YYYY-MM / YYYY-MM-DD / release）")
            else:
                log.watched_at, log.watched_precision = parsed
    if "note" in data:
        log.note = (data["note"] or "").strip() or None
    if not errors:
        log.updated_at = utcnow()
    return errors


def apply_record_update(db: Session, record: WatchRecord, data: dict, content: ContentItem | None = None) -> list[str]:
    """把用户提交的字段写入 record（任何手动修改都把 status_source 置回 manual）。返回错误列表

    片级字段：status / tags。观看级字段 my_rating / watched_at / comment（=note）落到**最近一次观看**，
    没有观看记录时先建一条；传 rewatch=True 则先新建一条观看再写。
    看过日期：手填 YYYY / YYYY-MM / YYYY-MM-DD 记对应精度；传 "release" = 详情页主动选「不记得（按上映）」；
    传空 = 清空（时间不详）。自动规则从不填日期。"""
    errors: list[str] = []
    touched = False
    if "status" in data and data["status"] is not None:
        if data["status"] not in WATCH_STATUSES:
            errors.append(f"status 非法: {data['status']}，可选 {list(WATCH_STATUSES)}")
        else:
            record.status = data["status"]
            touched = True
    if "tags" in data and data["tags"] is not None:
        record.tags = [str(t).strip() for t in data["tags"] if str(t).strip()]
        touched = True
    log_data = {k: data[k] for k in ("my_rating", "watched_at") if k in data}
    if "comment" in data:
        log_data["note"] = data["comment"]
    if "note" in data:
        log_data["note"] = data["note"]
    if log_data and not errors:
        log = new_log(db, record) if data.get("rewatch") else ensure_log(db, record)
        errors.extend(apply_log_update(log, log_data, content))
        touched = True
    if touched and not errors:
        record.status_source = "manual"
        record.updated_at = utcnow()
        # 评分蕴含看过：打分即记为看过（任何非看过状态，含弃了）；日期空着，留给详情页处理
        if "my_rating" in log_data and "status" not in data and log_data["my_rating"] is not None and record.status != "watched":
            record.status = "watched"
        # 看过必有至少一条观看记录（空的也算：时间不详、没打分）
        if record.status == "watched" and not record.logs:
            ensure_log(db, record)
        sync_record_from_logs(record)
    return errors


def serialize_log(log: WatchLog) -> dict:
    return {
        "id": log.id,
        "watched_at": log.watched_at.isoformat() if log.watched_at else None,
        "watched_precision": log.watched_precision,
        "watched_label": _date_label(log.watched_at, log.watched_precision),
        "my_rating": log.my_rating,
        "note": log.note,
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "updated_at": log.updated_at.isoformat() if log.updated_at else None,
    }


# ─── 海报缓存 ────────────────────────────────────────────────────────────────

def poster_source(poster: dict) -> str:
    """海报来源标识：Emby 图优先，其次 TMDb 路径；用于缓存键与 URL 版本号"""
    if poster.get("emby_item_id"):
        return f"emby:{poster['emby_item_id']}"
    if poster.get("tmdb_path"):
        return f"tmdb:{poster['tmdb_path']}"
    return ""


def poster_version(poster: dict) -> str:
    return hashlib.sha1(poster_source(poster).encode()).hexdigest()[:10]


def poster_cache_dir() -> Path:
    d = Path(settings.DATA_DIR) / "posters"
    d.mkdir(parents=True, exist_ok=True)
    return d


def poster_cache_path(content_id: str, poster: dict) -> Path:
    """一部片一张：来源变了（重新识别 / Emby 换图）版本号跟着变，旧文件自然失效"""
    return poster_cache_dir() / f"{content_id}-{poster_version(poster)}.jpg"


def fetch_poster_bytes(content_id: str, poster: dict, conn: dict | None) -> tuple[bytes, str] | None:
    """Emby Primary 图 → TMDb 海报 → None（同步版，供同步/补全时落盘；页面代理用路由里的异步版）"""
    emby_item = poster.get("emby_item_id")
    if emby_item and conn:
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(
                    f"{conn['base_url']}/emby/Items/{emby_item}/Images/Primary",
                    params={"maxWidth": 400, "quality": 85},
                    headers={"X-Emby-Token": conn["api_key"]},
                )
            if resp.status_code == 200 and resp.content:
                return resp.content, resp.headers.get("content-type", "image/jpeg")
        except httpx.HTTPError as e:
            logger.warning(f"Emby poster fetch failed for {content_id}: {e}")
    tmdb_path = poster.get("tmdb_path")
    if tmdb_path:
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(f"{TMDB_IMAGE_BASE}/w342{tmdb_path}")
            if resp.status_code == 200 and resp.content:
                return resp.content, resp.headers.get("content-type", "image/jpeg")
        except httpx.HTTPError as e:
            logger.warning(f"Poster fetch failed for {content_id}: {e}")
    return None


def write_poster_cache(path: Path, body: bytes) -> None:
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
    except OSError as e:
        logger.warning(f"poster cache write failed for {path.name}: {e}")


def cache_poster(content_id: str, poster: dict, conn: dict | None) -> bool:
    """元数据落库时顺手把海报存下来（已有则跳过），页面不再等首次打开时出网。返回是否命中/写入成功"""
    if not poster_source(poster):
        return False
    path = poster_cache_path(content_id, poster)
    if path.is_file() and path.stat().st_size > 0:
        return True
    fetched = fetch_poster_bytes(content_id, poster, conn)
    if not fetched:
        return False
    write_poster_cache(path, fetched[0])
    return True


# ─── 序列化 ───────────────────────────────────────────────────────────────────

def serialize_film(content: ContentItem, record: WatchRecord | None, *, brief: bool = False, emby_conn: dict | None = None) -> dict:
    """emby_conn：传入 get_emby_connection(db) 的结果时输出 emby_url（在库条目的 Emby 网页直达）"""
    raw = content.raw_data if isinstance(content.raw_data, dict) else {}
    emby = raw.get("emby") or None
    poster = raw.get("poster") or {}
    has_poster = bool(poster.get("emby_item_id") or poster.get("tmdb_path"))
    parsed = parse_external_id(content.external_id)
    logs = sorted_logs(record) if record else []
    latest = logs[0] if logs else None
    data: dict[str, Any] = {
        "content_id": content.id,
        "external_id": content.external_id,
        "tmdb_id": (raw.get("provider_ids") or {}).get("tmdb") or (parsed["id"] if parsed["scheme"] == "tmdb" else None),
        "title": content.title,
        "original_title": raw.get("original_title"),
        "kind": raw.get("kind") or parsed.get("kind") or "movie",
        "year": raw.get("year"),
        "genres": raw.get("genres") or [],
        "directors": raw.get("directors") or [],
        "countries": raw.get("countries") or [],
        "runtime_min": raw.get("runtime_min"),
        "community_rating": raw.get("community_rating"),
        "poster_url": f"/api/films/{content.id}/poster?v={poster_version(poster)}" if has_poster else None,
        "douban_url": douban_url_for(raw, content.title),
        "douban_id": (raw.get("provider_ids") or {}).get("douban"),
        "sources": raw.get("sources") or ([raw["source"]] if raw.get("source") else []),
        "in_emby": bool(emby and emby.get("in_library")),
        "emby_url": emby_item_url(emby_conn, (emby.get("item_ids") or [None])[0]) if emby and emby.get("in_library") else None,
        "emby": None if emby is None else {
            "in_library": bool(emby.get("in_library")),
            "played": bool(emby.get("played")),
            "play_count": emby.get("play_count") or 0,
            "progress": emby.get("progress") or 0,
            "last_played_at": emby.get("last_played_at"),
            "is_favorite": bool(emby.get("is_favorite")),
            "episodes_total": emby.get("episodes_total"),
            "episodes_played": emby.get("episodes_played"),
            "date_created": emby.get("date_created"),
            "last_synced_at": emby.get("last_synced_at"),
        },
        "record": {
            "status": record.status if record else "unmarked",
            # my_rating / watched_at / comment 都是「最近一次观看」的缓存；完整历史见 logs（详情）
            "my_rating": record.my_rating if record else None,
            "watched_at": record.watched_at.isoformat() if record and record.watched_at else None,
            "watched_precision": record.watched_precision if record else None,
            "watched_label": watched_label(record),
            "tags": list(record.tags or []) if record else [],
            "comment": (latest.note if latest else None),
            "log_count": len(logs),
            "status_source": record.status_source if record else "manual",
            "updated_at": record.updated_at.isoformat() if record and record.updated_at else None,
        },
        "is_favorited": content.is_favorited,
        "metadata_state": enrichment_state(raw, False),   # full / partial / skeleton / failed
        "created_at": content.created_at.isoformat() if content.created_at else None,
        "updated_at": content.updated_at.isoformat() if content.updated_at else None,
    }
    if not brief:
        data.update({
            "overview": raw.get("overview"),
            "cast": raw.get("cast") or [],
            "release_date": raw.get("release_date"),
            "official_rating": raw.get("official_rating"),
            "provider_ids": raw.get("provider_ids") or {},
            "url": content.url,
        })
        data["record"]["logs"] = [serialize_log(l) for l in logs]
    return data
