"""影视资料库服务 — 影片 upsert、用户标记、TMDb 客户端、序列化

影片 = ContentItem（source_type: sync.emby / user.film），元数据与 Emby 观看事实存 raw_data，
用户标记存 watch_records。三层数据的覆盖规则见 docs/design_film_library.md §2。

供 API 路由、Emby Fetcher、MCP server 共用。
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any, Optional

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.content import ContentItem, ContentStatus, SourceConfig, SourceType
from app.models.credential import PlatformCredential
from app.models.film import WatchRecord, WATCH_STATUSES
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

FILM_SOURCE_TYPES = (SourceType.SYNC_EMBY.value, SourceType.USER_FILM.value)
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
    }


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
    data = _tmdb_get(api_key, path, {"append_to_response": "credits,external_ids"})
    credits = data.get("credits") or {}
    if kind == "movie":
        directors = [p["name"] for p in credits.get("crew", []) if p.get("job") == "Director"]
        release = data.get("release_date") or ""
        runtime = data.get("runtime")
        title = data.get("title") or ""
        original_title = data.get("original_title") or ""
    else:
        directors = [p["name"] for p in data.get("created_by", []) if p.get("name")]
        release = data.get("first_air_date") or ""
        runtimes = data.get("episode_run_time") or []
        runtime = runtimes[0] if runtimes else None
        title = data.get("name") or ""
        original_title = data.get("original_name") or ""
    cast = [p["name"] for p in credits.get("cast", [])[:10] if p.get("name")]
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


# ─── Upsert ───────────────────────────────────────────────────────────────────

_META_FIELDS = (
    "kind", "year", "release_date", "original_title", "overview", "genres", "directors",
    "cast", "countries", "runtime_min", "community_rating", "official_rating",
)


def _find_film(db: Session, external_id: str, emby_item_ids: list[str] | None = None) -> ContentItem | None:
    """按 external_id（不限来源）查找影片；找不到再按 raw_data.emby.item_ids 找（Emby 条目后补 TMDb ID 的情形）"""
    base = (
        db.query(ContentItem)
        .join(SourceConfig, ContentItem.source_id == SourceConfig.id)
        .filter(SourceConfig.source_type.in_(FILM_SOURCE_TYPES))
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
            record.watched_at = last.date() if last else None
            record.updated_at = utcnow()
            stats["autofilled"] += 1

        stats["content_ids"].append(content.id)

    source.last_collected_at = utcnow()
    db.commit()
    return stats


def mark_missing_from_emby(db: Session, seen_content_ids: list[str]) -> int:
    """本次同步未出现、但 raw_data.emby.in_library=true 的记录 → in_library=false（记录保留）"""
    query = (
        db.query(ContentItem)
        .join(SourceConfig, ContentItem.source_id == SourceConfig.id)
        .filter(SourceConfig.source_type.in_(FILM_SOURCE_TYPES))
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
            .join(SourceConfig, ContentItem.source_id == SourceConfig.id)
            .filter(SourceConfig.source_type.in_(FILM_SOURCE_TYPES))
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


def apply_record_update(record: WatchRecord, data: dict) -> list[str]:
    """把用户提交的字段写入 record（任何手动修改都把 status_source 置回 manual）。返回错误列表"""
    errors: list[str] = []
    touched = False
    if "status" in data and data["status"] is not None:
        if data["status"] not in WATCH_STATUSES:
            errors.append(f"status 非法: {data['status']}，可选 {list(WATCH_STATUSES)}")
        else:
            record.status = data["status"]
            touched = True
    if "my_rating" in data:
        rating = data["my_rating"]
        if rating is not None and not (1 <= int(rating) <= 10):
            errors.append("my_rating 需在 1~10")
        else:
            record.my_rating = int(rating) if rating is not None else None
            touched = True
    if "watched_at" in data:
        value = data["watched_at"]
        if value in (None, ""):
            record.watched_at = None
        else:
            try:
                record.watched_at = date.fromisoformat(str(value)[:10])
            except ValueError:
                errors.append(f"watched_at 日期格式错误: {value}")
        touched = True
    if "tags" in data and data["tags"] is not None:
        record.tags = [str(t).strip() for t in data["tags"] if str(t).strip()]
        touched = True
    if "comment" in data:
        record.comment = data["comment"] or None
        touched = True
    if touched and not errors:
        record.status_source = "manual"
        record.updated_at = utcnow()
    return errors


# ─── 序列化 ───────────────────────────────────────────────────────────────────

def serialize_film(content: ContentItem, record: WatchRecord | None, *, brief: bool = False) -> dict:
    raw = content.raw_data if isinstance(content.raw_data, dict) else {}
    emby = raw.get("emby") or None
    poster = raw.get("poster") or {}
    has_poster = bool(poster.get("emby_item_id") or poster.get("tmdb_path"))
    parsed = parse_external_id(content.external_id)
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
        "poster_url": f"/api/films/{content.id}/poster" if has_poster else None,
        "sources": raw.get("sources") or ([raw["source"]] if raw.get("source") else []),
        "in_emby": bool(emby and emby.get("in_library")),
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
            "my_rating": record.my_rating if record else None,
            "watched_at": record.watched_at.isoformat() if record and record.watched_at else None,
            "tags": list(record.tags or []) if record else [],
            "comment": record.comment if record else None,
            "status_source": record.status_source if record else "manual",
            "updated_at": record.updated_at.isoformat() if record and record.updated_at else None,
        },
        "is_favorited": content.is_favorited,
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
            "user_note": content.user_note,
        })
    return data
