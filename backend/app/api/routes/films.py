"""影视资料库 API — 列表/详情/手工添加/标记/海报代理/TMDb 搜索/统计"""

import logging
import re
from typing import Optional

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy import asc, desc, func, or_
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.time import utcnow
from app.models.content import ContentItem, SourceConfig, SourceType
from app.models.film import WatchRecord, WATCH_STATUSES
from app.schemas import error_response
from app.schemas.film import (
    BatchRecordRequest,
    DoubanLinkRequest,
    FilmMetaUpdate,
    FilmRelinkRequest,
    FilmCreate,
    WatchLogUpdate,
    WatchRecordUpdate,
)
from app.services.film_library import (
    FILM_SOURCE_TYPES,
    KINDS,
    TMDB_IMAGE_BASE,
    apply_log_update,
    apply_record_update,
    enrich_film,
    enrichment_state,
    douban_probe,
    douban_resolve,
    find_unenriched,
    get_emby_connection,
    get_or_create_film_source,
    get_or_create_record,
    get_tmdb_api_key,
    new_log,
    poster_cache_path,
    write_poster_cache,
    resolve_or_create_film,
    serialize_film,
    sync_record_from_logs,
    tmdb_details,
    tmdb_external_id,
    tmdb_search,
    upsert_films,
    _find_film,
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
        .options(selectinload(WatchRecord.logs))   # 序列化要取最近一次观看，避免逐行查
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
        if not (raw.get("provider_ids") or {}).get("douban"):
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
            "unenriched": unenriched,          # 「补全元数据」可处理的记录数（TMDb 详情缺失）
            "douban_missing": douban_missing,  # 尚无豆瓣直达链接的记录数（详情页手动解析）
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
    # 「弃了」在任何排序下都沉底（片间相对顺序不变）
    dropped_last = sa.case((WatchRecord.status == "dropped", 1), else_=0)
    rows = query.order_by(dropped_last, expr, ContentItem.title.asc()).offset((page - 1) * page_size).limit(page_size).all()

    emby_conn = get_emby_connection(db)
    return {
        "code": 0,
        "data": [serialize_film(c, r, brief=True, emby_conn=emby_conn) for c, r in rows],
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
        errors = apply_record_update(db, record, update, content)
        if errors:
            db.rollback()
            return error_response(400, "; ".join(errors))
    db.commit()
    db.refresh(content)
    return {"code": 0, "data": serialize_film(content, record, emby_conn=get_emby_connection(db)), "message": "已添加"}


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
        errors = apply_record_update(db, record, update, content)
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
    if not get_tmdb_api_key(db):
        return error_response(400, "未配置 TMDb API Key，请在系统设置 · 影视资料库中填写")
    targets = find_unenriched(db, limit)
    results = []
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
    remaining = len(find_unenriched(db, 1000))
    ok = sum(1 for r in results if r["ok"])
    return {"code": 0, "data": {"processed": len(results), "ok": ok, "remaining": remaining, "results": results},
            "message": f"补全 {ok}/{len(results)}，剩余 {remaining}"}


@router.post("/{content_id}/enrich")
def enrich_one(content_id: str, db: Session = Depends(get_db)):
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    raw = dict(content.raw_data or {})
    raw.pop("enrich_failed", None)
    content.raw_data = raw
    try:
        changed, reason = enrich_film(db, content)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return error_response(502, f"补全失败: {e}")
    if not changed:
        db.commit()
        return error_response(400 if reason.startswith("未配置") else 404, f"补全失败: {reason}")
    db.refresh(content)
    record = db.query(WatchRecord).filter(WatchRecord.content_id == content.id).first()
    return {"code": 0, "data": serialize_film(content, record, emby_conn=get_emby_connection(db)), "message": f"已补全（{reason}）"}


# ─── 修正元数据 / 重新识别 ───────────────────────────────────────────────────

@router.put("/{content_id}/meta")
def update_meta(content_id: str, body: FilmMetaUpdate, db: Session = Depends(get_db)):
    """改片名/年份/类型；没有 TMDb ID 的记录改完顺手按新片名再搜一次"""
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    raw = dict(content.raw_data or {})
    if body.title and body.title.strip():
        content.title = body.title.strip()
    if body.year is not None:
        raw["year"] = int(body.year)
        raw.pop("release_date", None) if raw.get("release_date", "")[:4] != str(body.year) else None
    if body.kind in KINDS:
        raw["kind"] = body.kind
    raw.pop("enrich_failed", None)
    content.raw_data = raw
    content.updated_at = utcnow()
    db.commit()
    note = "已保存"
    if not (raw.get("provider_ids") or {}).get("tmdb") and get_tmdb_api_key(db):
        try:
            changed, reason = enrich_film(db, content)
            note = "已保存并识别" if changed else f"已保存（TMDb 仍未匹配：{reason}）"
        except Exception as e:  # noqa: BLE001
            db.rollback()
            note = f"已保存（识别失败：{e}）"
    db.refresh(content)
    record = db.query(WatchRecord).filter(WatchRecord.content_id == content.id).first()
    return {"code": 0, "data": serialize_film(content, record, emby_conn=get_emby_connection(db)), "message": note}


@router.post("/{content_id}/relink")
def relink_film(content_id: str, body: FilmRelinkRequest, db: Session = Depends(get_db)):
    """重新识别：改关联到指定 TMDb 条目。元数据、海报、片名整体替换；watch_records 与 Emby 事实保留"""
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    api_key = get_tmdb_api_key(db)
    if not api_key:
        return error_response(400, "未配置 TMDb API Key")
    kind = body.kind if body.kind in KINDS else "movie"
    new_ext = tmdb_external_id(kind, body.tmdb_id)
    other = _find_film(db, new_ext)
    if other and other.id != content.id:
        return error_response(409, f"该 TMDb 条目已对应库里的「{other.title}」，请改在那条上标记")
    try:
        film = tmdb_details(api_key, kind, body.tmdb_id)
    except httpx.HTTPError as e:
        return error_response(502, f"TMDb 请求失败: {e}")
    raw = dict(content.raw_data or {})
    emby_block = raw.get("emby")
    # 清掉旧元数据，只保留 Emby 事实与来源
    raw = {k: v for k, v in raw.items() if k in ("emby", "sources")}
    raw.pop("enrich_failed", None)
    content.raw_data = raw
    content.external_id = new_ext
    db.flush()
    source = db.get(SourceConfig, content.source_id)
    if emby_block is not None:
        film["emby"] = emby_block
    upsert_films(db, source, [film])   # title 用 TMDb 的
    db.refresh(content)
    record = db.query(WatchRecord).filter(WatchRecord.content_id == content.id).first()
    return {"code": 0, "data": serialize_film(content, record, emby_conn=get_emby_connection(db)), "message": f"已重新识别为「{content.title}」"}


# ─── 豆瓣直达（详情页手动触发，一次生效永久保存） ────────────────────────────

@router.post("/{content_id}/douban")
def set_douban(content_id: str, body: DoubanLinkRequest = DoubanLinkRequest(), db: Session = Depends(get_db)):
    """解析或手填豆瓣条目：body.url/douban_id 为空时按片名自动解析；限流或没匹配都不做持久标记，可随时重试"""
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    raw = dict(content.raw_data or {})
    pids = dict(raw.get("provider_ids") or {})

    douban_id = None
    if body.douban_id:
        douban_id = body.douban_id.strip()
    elif body.url:
        m = re.search(r"subject/(\d+)", body.url)
        if not m:
            return error_response(400, "豆瓣链接格式不对，应包含 /subject/<数字>/")
        douban_id = m.group(1)
    if douban_id and not douban_id.isdigit():
        return error_response(400, "豆瓣 id 应为数字")

    if not douban_id:
        if not douban_probe():
            return error_response(503, "豆瓣接口当前限流，稍后再试；也可以把豆瓣条目链接粘进来")
        douban_id = douban_resolve(content.title, raw.get("original_title"), raw.get("year"))
        if not douban_id:
            return error_response(404, "豆瓣没有匹配到条目，可以把豆瓣条目链接粘进来")

    pids["douban"] = douban_id
    raw["provider_ids"] = pids
    raw.pop("douban_failed", None)
    content.raw_data = raw
    content.updated_at = utcnow()
    db.commit()
    return {"code": 0, "data": serialize_film(content, record, emby_conn=get_emby_connection(db)), "message": "豆瓣直达已保存"}


@router.delete("/{content_id}/douban")
def clear_douban(content_id: str, db: Session = Depends(get_db)):
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    raw = dict(content.raw_data or {})
    pids = dict(raw.get("provider_ids") or {})
    pids.pop("douban", None)
    raw["provider_ids"] = pids
    content.raw_data = raw
    db.commit()
    return {"code": 0, "data": serialize_film(content, record, emby_conn=get_emby_connection(db)), "message": "已清除豆瓣直达"}


# ─── 详情 / 标记 / 长评 ───────────────────────────────────────────────────────

@router.get("/{content_id}")
def get_film(content_id: str, db: Session = Depends(get_db)):
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    return {"code": 0, "data": serialize_film(content, record, emby_conn=get_emby_connection(db)), "message": "ok"}


@router.put("/{content_id}/record")
def update_record(content_id: str, body: WatchRecordUpdate, db: Session = Depends(get_db)):
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    if not record:
        record = get_or_create_record(db, content.id)
    errors = apply_record_update(db, record, body.model_dump(exclude_unset=True), content)
    if errors:
        db.rollback()
        return error_response(400, "; ".join(errors))
    db.commit()
    return {"code": 0, "data": serialize_film(content, record, emby_conn=get_emby_connection(db)), "message": "已保存"}


# ─── 观看记录（一部片多次观看） ────────────────────────────────────────────

@router.post("/{content_id}/logs")
def add_log(content_id: str, body: WatchLogUpdate, db: Session = Depends(get_db)):
    """再记一次观看：新建一条观看记录（默认日期 = 今天，可改；片自动置为看过）"""
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    if not record:
        record = get_or_create_record(db, content.id)
    log = new_log(db, record)   # flush 后 created_at 才有值，「最近一次」比较依赖它
    errors = apply_log_update(log, body.model_dump(exclude_unset=True), content)
    if errors:
        db.rollback()
        return error_response(400, "; ".join(errors))
    if record.status != "watched":
        record.status = "watched"
    record.status_source = "manual"
    record.updated_at = utcnow()
    sync_record_from_logs(record)
    db.commit()
    return {"code": 0, "data": serialize_film(content, record, emby_conn=get_emby_connection(db)), "message": "已记一次观看"}


@router.put("/{content_id}/logs/{log_id}")
def update_log(content_id: str, log_id: str, body: WatchLogUpdate, db: Session = Depends(get_db)):
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    log = next((l for l in (record.logs if record else []) if l.id == log_id), None)
    if not log:
        return error_response(404, "观看记录不存在")
    errors = apply_log_update(log, body.model_dump(exclude_unset=True), content)
    if errors:
        db.rollback()
        return error_response(400, "; ".join(errors))
    record.status_source = "manual"
    record.updated_at = utcnow()
    sync_record_from_logs(record)
    db.commit()
    return {"code": 0, "data": serialize_film(content, record, emby_conn=get_emby_connection(db)), "message": "已保存"}


@router.delete("/{content_id}/logs/{log_id}")
def delete_log(content_id: str, log_id: str, db: Session = Depends(get_db)):
    """删一条观看记录；删到零条时片的状态保持不变（看过与否由用户决定）"""
    row = _base_query(db).filter(ContentItem.id == content_id).first()
    if not row:
        return error_response(404, "影片不存在")
    content, record = row
    log = next((l for l in (record.logs if record else []) if l.id == log_id), None)
    if not log:
        return error_response(404, "观看记录不存在")
    record.logs.remove(log)
    db.delete(log)
    db.flush()
    record.status_source = "manual"
    record.updated_at = utcnow()
    sync_record_from_logs(record)
    db.commit()
    return {"code": 0, "data": serialize_film(content, record, emby_conn=get_emby_connection(db)), "message": "已删除该次观看"}


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

# 海报 URL 带版本号（来源哈希），内容不变则永久可缓存；来源变了 URL 也变
_POSTER_HEADERS = {"Cache-Control": "public, max-age=2592000, immutable"}


async def _fetch_poster_bytes(content_id: str, poster: dict, conn: dict | None) -> tuple[bytes, str] | None:
    """Emby Primary 图 → TMDb 海报 → None。异步拉取，不占线程池"""
    emby_item = poster.get("emby_item_id")
    if emby_item and conn:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
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
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(f"{TMDB_IMAGE_BASE}/w342{tmdb_path}")
            if resp.status_code == 200 and resp.content:
                return resp.content, resp.headers.get("content-type", "image/jpeg")
        except httpx.HTTPError as e:
            logger.warning(f"Poster fetch failed for {content_id}: {e}")
    return None


@router.get("/{content_id}/poster")
async def film_poster(content_id: str, db: Session = Depends(get_db)):
    """海报：磁盘缓存命中直接回文件；未命中异步拉 Emby / TMDb 一次后落盘。不向前端暴露 Emby key。

    之前每次请求都现拉外网（约 1s/张，同步阻塞线程池），一页 60 张把整个后端拖死，移动端表现为点开影视库卡住。"""
    content = db.get(ContentItem, content_id)
    if not content:
        return Response(status_code=404)
    raw = content.raw_data if isinstance(content.raw_data, dict) else {}
    poster = raw.get("poster") or {}
    if not (poster.get("emby_item_id") or poster.get("tmdb_path")):
        return Response(status_code=404)

    path = poster_cache_path(content_id, poster)
    if path.is_file() and path.stat().st_size > 0:
        return FileResponse(path, media_type="image/jpeg", headers=_POSTER_HEADERS)

    conn = get_emby_connection(db) if poster.get("emby_item_id") else None
    fetched = await _fetch_poster_bytes(content_id, poster, conn)
    if not fetched:
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    body, media_type = fetched
    write_poster_cache(path, body)
    return Response(content=body, media_type=media_type, headers=_POSTER_HEADERS)
