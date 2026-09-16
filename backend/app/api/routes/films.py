"""影视资料库 API — 列表/详情/手工添加/标记/海报代理/TMDb 搜索/统计"""

import logging
from typing import Optional

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import asc, desc, func, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import utcnow
from app.models.content import ContentItem, SourceConfig, SourceType
from app.models.film import WatchRecord, WATCH_STATUSES
from app.schemas import error_response
from app.schemas.film import (
    BatchRecordRequest,
    FilmCreate,
    FilmNoteUpdate,
    WatchRecordUpdate,
)
from app.services.film_library import (
    FILM_SOURCE_TYPES,
    KINDS,
    TMDB_IMAGE_BASE,
    apply_record_update,
    enrich_film,
    enrichment_state,
    douban_probe,
    find_douban_missing,
    find_unenriched,
    resolve_douban_for,
    get_emby_connection,
    get_or_create_film_source,
    get_or_create_record,
    get_tmdb_api_key,
    resolve_or_create_film,
    serialize_film,
    tmdb_search,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _base_query(db: Session):
    return (
        db.query(ContentItem, WatchRecord)
        .join(SourceConfig, ContentItem.source_id == SourceConfig.id)
        .outerjoin(WatchRecord, WatchRecord.content_id == ContentItem.id)
        .filter(SourceConfig.source_type.in_(FILM_SOURCE_TYPES))
    )


# ─── 同步源初始化（供 SyncView「初始化」按钮） ─────────────────────────────────

@router.post("/sync/setup")
def setup_film_sync(db: Session = Depends(get_db)):
    source = get_or_create_film_source(db, SourceType.SYNC_EMBY.value)
    return {"code": 0, "data": {"source_id": source.id}, "message": "Emby 同步源已就绪"}


# ─── 统计 / 筛选项 ────────────────────────────────────────────────────────────

@router.get("/stats")
def film_stats(db: Session = Depends(get_db)):
    """按状态/类型/是否在 Emby 计数 + 可用的类型和年代筛选项"""
    rows = _base_query(db).all()
    by_status = {s: 0 for s in WATCH_STATUSES}
    by_kind = {k: 0 for k in KINDS}
    in_emby = 0
    genres: dict[str, int] = {}
    tags: dict[str, int] = {}
    years: set[int] = set()
    unenriched = 0
    partial = 0
    enrich_failed = 0
    douban_missing = 0
    tmdb_configured = bool(get_tmdb_api_key(db))
    for content, record in rows:
        for t in (record.tags if record and record.tags else []):
            tags[t] = tags.get(t, 0) + 1
        by_status[(record.status if record else "unmarked")] = by_status.get(record.status if record else "unmarked", 0) + 1
        raw = content.raw_data if isinstance(content.raw_data, dict) else {}
        kind = raw.get("kind") or "movie"
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if (raw.get("emby") or {}).get("in_library"):
            in_emby += 1
        for g in raw.get("genres") or []:
            genres[g] = genres.get(g, 0) + 1
        if raw.get("year"):
            years.add(int(raw["year"]))
        if not (raw.get("provider_ids") or {}).get("douban") and not raw.get("douban_failed"):
            douban_missing += 1
        state = enrichment_state(raw, tmdb_configured)
        if state == "failed":
            enrich_failed += 1
        elif state == "skeleton":
            unenriched += 1
        elif state == "partial":
            partial += 1
            if tmdb_configured:
                unenriched += 1
    return {
        "code": 0,
        "data": {
            "total": len(rows),
            "by_status": by_status,
            "by_kind": by_kind,
            "in_emby": in_emby,
            "genres": [g for g, _ in sorted(genres.items(), key=lambda kv: (-kv[1], kv[0]))],
            "tags": [t for t, _ in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))],
            "years": sorted(years, reverse=True),
            "unenriched": unenriched + douban_missing,   # 「补全元数据」可处理的记录数（TMDb 缺失 + 豆瓣直链缺失）
            "tmdb_missing": unenriched,
            "douban_missing": douban_missing,
            "partial": partial,                # 有 ID/海报但缺导演/类型/简介的记录数（需 TMDb key）
            "enrich_failed": enrich_failed,    # 补全失败过、等单条重试的记录数
            "tmdb_configured": tmdb_configured,
            "emby_configured": get_emby_connection(db) is not None,
        },
        "message": "ok",
    }


# ─── TMDb 搜索 ────────────────────────────────────────────────────────────────

@router.get("/search")
def search_films(
    q: str = Query(..., min_length=1),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    api_key = get_tmdb_api_key(db)
    if not api_key:
        return error_response(400, "未配置 TMDb API Key，请在系统设置中填写")
    try:
        results = tmdb_search(api_key, q, year)
    except httpx.HTTPError as e:
        return error_response(502, f"TMDb 请求失败: {e}")
    for r in results:
        r["poster_url"] = f"{TMDB_IMAGE_BASE}/w185{r['poster_path']}" if r.get("poster_path") else None
    return {"code": 0, "data": results, "message": "ok"}


# ─── 列表 ─────────────────────────────────────────────────────────────────────

@router.get("")
def list_films(
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=500),
    q: Optional[str] = Query(None, description="标题/原名/导演模糊搜索"),
    status: Optional[str] = Query(None, description="标记状态，逗号分隔多选"),
    kind: Optional[str] = Query(None, description="movie / series"),
    genre: Optional[str] = Query(None),
    year_from: Optional[int] = Query(None),
    year_to: Optional[int] = Query(None),
    in_emby: Optional[bool] = Query(None),
    min_rating: Optional[int] = Query(None, ge=1, le=10, description="我的评分下限"),
    sort: str = Query("updated_at", description="updated_at / year / title / my_rating / last_played / community_rating"),
    order: str = Query("desc"),
    db: Session = Depends(get_db),
):
    query = _base_query(db)

    if q:
        like = f"%{_escape_like(q.strip())}%"
        query = query.filter(or_(
            ContentItem.title.ilike(like),
            ContentItem.author.ilike(like),
            ContentItem.raw_data["original_title"].astext.ilike(like),
        ))
    if status:
        wanted = [s for s in status.split(",") if s in WATCH_STATUSES]
        if wanted:
            if "unmarked" in wanted:
                query = query.filter(or_(WatchRecord.status.in_(wanted), WatchRecord.id.is_(None)))
            else:
                query = query.filter(WatchRecord.status.in_(wanted))
    if kind in KINDS:
        query = query.filter(ContentItem.raw_data["kind"].astext == kind)
    if genre:
        query = query.filter(ContentItem.raw_data["genres"].contains([genre]))
    if year_from is not None:
        query = query.filter(ContentItem.raw_data["year"].astext.cast(sa.Integer) >= year_from)
    if year_to is not None:
        query = query.filter(ContentItem.raw_data["year"].astext.cast(sa.Integer) <= year_to)
    if in_emby is True:
        query = query.filter(ContentItem.raw_data["emby"]["in_library"].astext == "true")
    elif in_emby is False:
        query = query.filter(or_(
            ContentItem.raw_data["emby"]["in_library"].astext.is_(None),
            ContentItem.raw_data["emby"]["in_library"].astext != "true",
        ))
    if min_rating is not None:
        query = query.filter(WatchRecord.my_rating >= min_rating)

    total = query.count()

    sort_map = {
        "updated_at": func.coalesce(WatchRecord.updated_at, ContentItem.updated_at),
        "year": ContentItem.raw_data["year"].astext.cast(sa.Integer),
        "title": ContentItem.title,
        "my_rating": WatchRecord.my_rating,
        "last_played": ContentItem.raw_data["emby"]["last_played_at"].astext,
        "community_rating": ContentItem.raw_data["community_rating"].astext.cast(sa.Float),
        "created_at": ContentItem.created_at,
    }
    col = sort_map.get(sort, sort_map["updated_at"])
    expr = desc(col).nulls_last() if order != "asc" else asc(col).nulls_last()
    rows = query.order_by(expr, ContentItem.title.asc()).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "code": 0,
        "data": [serialize_film(c, r, brief=True) for c, r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "message": "ok",
    }


# ─── 手工添加 ─────────────────────────────────────────────────────────────────

@router.post("")
def create_film(body: FilmCreate, db: Session = Depends(get_db)):
    if not body.tmdb_id and not body.title:
        return error_response(400, "需要 tmdb_id 或 title")
    content, err = resolve_or_create_film(
        db, tmdb_id=body.tmdb_id, kind=body.kind, title=body.title, year=body.year,
    )
    if err or not content:
        return error_response(400, err or "创建失败")
    record = get_or_create_record(db, content.id)
    update = {k: v for k, v in body.model_dump().items() if k in ("status", "my_rating", "watched_at", "comment") and v is not None}
    if update:
        errors = apply_record_update(record, update, content)
        if errors:
            db.rollback()
            return error_response(400, "; ".join(errors))
    db.commit()
    db.refresh(content)
    return {"code": 0, "data": serialize_film(content, record), "message": "已添加"}


# ─── 批量标记（推荐闭环） ─────────────────────────────────────────────────────

@router.post("/records/batch")
def batch_records(body: BatchRecordRequest, db: Session = Depends(get_db)):
    results = []
    for item in body.items:
        content, err = resolve_or_create_film(
            db, content_id=item.content_id, tmdb_id=item.tmdb_id, kind=item.kind, title=item.title, year=item.year,
        )
        if err or not content:
            results.append({"ok": False, "error": err or "定位失败", "input": item.model_dump(exclude_none=True)})
            continue
        record = get_or_create_record(db, content.id)
        update = {
            "status": item.status,
            **({"my_rating": item.my_rating} if item.my_rating is not None else {}),
            **({"watched_at": item.watched_at} if item.watched_at is not None else {}),
            **({"comment": item.comment} if item.comment is not None else {}),
            **({"tags": item.tags} if item.tags is not None else {}),
        }
        errors = apply_record_update(record, update, content)
        if errors:
            results.append({"ok": False, "error": "; ".join(errors), "content_id": content.id, "title": content.title})
            continue
        db.commit()
        results.append({"ok": True, "content_id": content.id, "title": content.title, "status": record.status})
    ok = sum(1 for r in results if r["ok"])
    return {"code": 0, "data": results, "message": f"已处理 {ok}/{len(results)}"}


# ─── 元数据补全（TMDb 详情） ─────────────────────────────────────────────────

@router.post("/enrich-missing")
def enrich_missing(limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_db)):
    """用 TMDb 详情补全记录元数据，每次最多 limit 条；返回 remaining 供前端循环"""
    import time as _time
    tmdb_ok = bool(get_tmdb_api_key(db))
    targets = find_unenriched(db, limit) if tmdb_ok else []
    results = []
    if not targets:
        # 第二阶段：豆瓣直链（软依赖）。先探针：被限流就整批中止、不标记；每条 2s，单批最多 20 条
        douban_targets = find_douban_missing(db, min(limit, 20))
        if douban_targets and not douban_probe():
            remaining = len(find_douban_missing(db, 1000))
            return {"code": 0, "data": {"processed": 0, "ok": 0, "remaining": remaining, "phase": "douban", "throttled": True, "results": []},
                    "message": f"豆瓣接口当前限流（对已知影片也返回空），剩余 {remaining} 条稍后再试"}
        for i, content in enumerate(douban_targets):
            try:
                ok, reason = resolve_douban_for(db, content)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                ok, reason = False, str(e)
            results.append({"content_id": content.id, "title": content.title, "ok": ok, "reason": reason, "phase": "douban"})
            # 连续 3 条空结果 → 复查探针，被限流则停止并撤销这几条的失败标记
            if i >= 2 and all(not r["ok"] for r in results[-3:]) and not douban_probe():
                for r in results[-3:]:
                    c = db.get(ContentItem, r["content_id"])
                    if c and isinstance(c.raw_data, dict) and c.raw_data.get("douban_failed"):
                        rd = dict(c.raw_data); rd.pop("douban_failed", None); c.raw_data = rd
                db.commit()
                results = results[:-3]
                remaining = len(find_douban_missing(db, 1000))
                ok_n = sum(1 for r in results if r["ok"])
                return {"code": 0, "data": {"processed": len(results), "ok": ok_n, "remaining": remaining, "phase": "douban", "throttled": True, "results": results},
                        "message": f"豆瓣直链 {ok_n}/{len(results)}，随后被限流，剩余 {remaining} 条稍后再试"}
            _time.sleep(2)
        remaining = len(find_douban_missing(db, 1000)) + (len(find_unenriched(db, 1000)) if tmdb_ok else 0)
        ok = sum(1 for r in results if r["ok"])
        return {"code": 0, "data": {"processed": len(results), "ok": ok, "remaining": remaining, "phase": "douban", "results": results},
                "message": f"豆瓣直链 {ok}/{len(results)}，剩余 {remaining}"}
    for content in targets:
        try:
            changed, reason = enrich_film(db, content)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            changed, reason = False, str(e)
        if not changed:
            # 标记失败，避免每次都重试同一批；用户可在详情里单条重试
            raw = dict(content.raw_data or {})
            raw["enrich_failed"] = reason
            content.raw_data = raw
            db.commit()
        results.append({"content_id": content.id, "title": content.title, "ok": changed, "reason": reason})
    remaining = len(find_unenriched(db, 1000)) + len(find_douban_missing(db, 1000))
    ok = sum(1 for r in results if r["ok"])
    return {"code": 0, "data": {"processed": len(results), "ok": ok, "remaining": remaining, "phase": "tmdb", "results": results},
            "message": f"补全 {ok}/{len(results)}，剩余 {remaining}"}


@router.post("/{content_id}/enrich")
def enrich_one(content_id: str, db: Session = Depends(get_db)):
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    raw = dict(content.raw_data or {})
    raw.pop("enrich_failed", None)
    raw.pop("douban_failed", None)
    content.raw_data = raw
    try:
        changed, reason = enrich_film(db, content)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return error_response(502, f"补全失败: {e}")
    if not changed and reason.startswith("未配置"):
        db.commit()
        return error_response(400, reason)
    try:
        douban_ok, douban_reason = resolve_douban_for(db, content, mark_failed=douban_probe())
    except Exception as e:  # noqa: BLE001
        douban_ok, douban_reason = False, str(e)
    if not changed and not douban_ok:
        db.commit()
        return error_response(404, f"补全失败: {reason}；豆瓣：{douban_reason}")
    reason = f"{reason}{'，豆瓣直链已解析' if douban_ok else ''}"
    db.refresh(content)
    record = db.query(WatchRecord).filter(WatchRecord.content_id == content.id).first()
    return {"code": 0, "data": serialize_film(content, record), "message": f"已补全（{reason}）"}


# ─── 详情 / 标记 / 长评 ───────────────────────────────────────────────────────

@router.get("/{content_id}")
def get_film(content_id: str, db: Session = Depends(get_db)):
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    return {"code": 0, "data": serialize_film(content, record), "message": "ok"}


@router.put("/{content_id}/record")
def update_record(content_id: str, body: WatchRecordUpdate, db: Session = Depends(get_db)):
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    if not record:
        record = get_or_create_record(db, content.id)
    errors = apply_record_update(record, body.model_dump(exclude_unset=True), content)
    if errors:
        db.rollback()
        return error_response(400, "; ".join(errors))
    db.commit()
    return {"code": 0, "data": serialize_film(content, record), "message": "已保存"}


@router.put("/{content_id}/note")
def update_note(content_id: str, body: FilmNoteUpdate, db: Session = Depends(get_db)):
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    content.user_note = body.user_note or None
    content.updated_at = utcnow()
    db.commit()
    return {"code": 0, "data": serialize_film(content, record), "message": "已保存"}


@router.delete("/{content_id}")
def delete_film(content_id: str, db: Session = Depends(get_db)):
    """删除资料库记录（只删 allin-one 的记录，绝不触碰 Emby）"""
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, _ = row
    db.delete(content)
    db.commit()
    return {"code": 0, "data": None, "message": "已删除"}


# ─── 海报代理 ─────────────────────────────────────────────────────────────────

_POSTER_HEADERS = {"Cache-Control": "public, max-age=86400"}


@router.get("/{content_id}/poster")
def film_poster(content_id: str, db: Session = Depends(get_db)):
    """Emby Primary 图 → TMDb 海报 → 404。不向前端暴露 Emby key。"""
    content = db.get(ContentItem, content_id)
    if not content:
        return Response(status_code=404)
    raw = content.raw_data if isinstance(content.raw_data, dict) else {}
    poster = raw.get("poster") or {}

    emby_item = poster.get("emby_item_id")
    conn = get_emby_connection(db) if emby_item else None
    if emby_item and conn:
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(
                    f"{conn['base_url']}/emby/Items/{emby_item}/Images/Primary",
                    params={"maxWidth": 400, "quality": 85},
                    headers={"X-Emby-Token": conn["api_key"]},
                )
            if resp.status_code == 200 and resp.content:
                return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/jpeg"), headers=_POSTER_HEADERS)
        except httpx.HTTPError as e:
            logger.warning(f"Emby poster fetch failed for {content_id}: {e}")

    tmdb_path = poster.get("tmdb_path")
    if tmdb_path:
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(f"{TMDB_IMAGE_BASE}/w342{tmdb_path}")
            if resp.status_code == 200 and resp.content:
                return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/jpeg"), headers=_POSTER_HEADERS)
        except httpx.HTTPError as e:
            logger.warning(f"Poster fetch failed for {content_id}: {e}")

    return Response(status_code=404)
