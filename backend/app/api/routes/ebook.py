"""Ebook API — 书架管理、标注 CRUD、元数据编辑"""

import json
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import desc, asc, func, or_, case
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.time import utcnow
from app.models.content import ContentItem, ContentStatus, MediaItem
from app.models.ebook import ReadingProgress, BookAnnotation, BookBookmark
from app.schemas import error_response
from app.schemas.ebook import (
    AnnotationCreate,
    AnnotationUpdate,
    EbookMetadataUpdate,
    BookSearchResult,
    MetadataApplyRequest,
)
from app.services.book_metadata import search_google_books, search_google_books_structured

logger = logging.getLogger(__name__)
router = APIRouter()


def _escape_like(s: str) -> str:
    """转义 LIKE 通配符，防止用户输入 % 或 _ 构造非预期匹配。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _safe_media_path(rel_or_abs: str) -> Path:
    """验证路径在 MEDIA_DIR 范围内，防止路径遍历攻击。"""
    media_root = Path(settings.MEDIA_DIR).resolve()
    # 兼容已有的绝对路径和新的相对路径
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = media_root / p
    real = p.resolve()
    try:
        real.relative_to(media_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="非法路径")
    return real


# ─── List ────────────────────────────────────────────────────────────────────

@router.get("/list")
async def list_ebooks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    source: Optional[str] = Query(None, description="按来源平台筛选: apple_books / wechat_read / kindle"),
    author: Optional[str] = Query(None, description="按作者筛选"),
    category: Optional[str] = Query(None, description="按分类筛选"),
    sort_by: str = Query("updated_at", description="排序: updated_at / title / created_at"),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
):
    """书架列表"""
    ann_count_sq = (
        db.query(
            BookAnnotation.content_id,
            func.count(BookAnnotation.id).label("ann_count"),
        )
        .group_by(BookAnnotation.content_id)
        .subquery()
    )

    query = (
        db.query(ContentItem, MediaItem, ReadingProgress, ann_count_sq.c.ann_count)
        .join(MediaItem, MediaItem.content_id == ContentItem.id)
        .outerjoin(ReadingProgress, ReadingProgress.content_id == ContentItem.id)
        .outerjoin(ann_count_sq, ann_count_sq.c.content_id == ContentItem.id)
        .filter(MediaItem.media_type == "ebook")
    )

    if search:
        like = f"%{_escape_like(search)}%"
        query = query.filter(
            (ContentItem.title.ilike(like)) | (ContentItem.author.ilike(like))
        )

    if source:
        query = query.filter(ContentItem.raw_data.ilike(f'%"source": "{_escape_like(source)}"%'))

    if author:
        query = query.filter(ContentItem.author == author)

    if category:
        # raw_data 是 Text 列存 JSON，用 LIKE 匹配 subjects 数组中的值
        query = query.filter(ContentItem.raw_data.ilike(f'%"{category}"%'))

    total = query.count()

    # 排序
    sort_map = {
        "title": ContentItem.title,
        "created_at": ContentItem.created_at,
        "annotation_count": ann_count_sq.c.ann_count,
    }
    if sort_by == "updated_at":
        sort_column = func.coalesce(ReadingProgress.updated_at, ContentItem.created_at)
    else:
        sort_column = sort_map.get(sort_by, ContentItem.created_at)

    order_expr = desc(sort_column).nulls_last() if sort_order == "desc" else asc(sort_column).nulls_last()
    query = query.order_by(order_expr).offset((page - 1) * page_size).limit(page_size)

    data = []
    for content, media, progress, ann_count in query.all():
        meta = {}
        if media.metadata_json:
            try:
                meta = json.loads(media.metadata_json)
            except (json.JSONDecodeError, TypeError):
                pass

        raw = {}
        if content.raw_data:
            try:
                raw = json.loads(content.raw_data)
            except (json.JSONDecodeError, TypeError):
                pass

        # 信任 DB 中的 cover_path（上传时已验证），列表接口不做磁盘 I/O
        has_cover = bool(meta.get("cover_path"))
        cover_url = f"/api/ebook/{content.id}/cover" if has_cover else meta.get("cover_url")

        data.append({
            "content_id": content.id,
            "title": content.title,
            "author": content.author,
            "format": meta.get("format", "epub"),
            "file_size": meta.get("file_size"),
            "cover_url": cover_url,
            "subjects": raw.get("subjects", []),
            "progress": progress.progress if progress else 0,
            "section_title": progress.section_title if progress else None,
            "last_read_at": progress.updated_at.isoformat() if progress and progress.updated_at else None,
            "created_at": content.created_at.isoformat() if content.created_at else None,
            "source": raw.get("source"),  # 平台标识: apple_books / wechat_read 等
            "external_id": content.external_id,
            "media_status": media.status,
            "annotation_count": ann_count or 0,
        })

    return {
        "code": 0,
        "data": data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "message": "ok",
    }


# ─── Cross-book Annotations ──────────────────────────────────────────────────

# 注意: 此路由必须在 /{content_id} 之前定义，否则会被参数路由拦截
@router.get("/annotations/recent")
async def list_recent_annotations(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """跨书最近标注"""
    rows = (
        db.query(BookAnnotation, ContentItem, MediaItem)
        .join(ContentItem, ContentItem.id == BookAnnotation.content_id)
        .join(MediaItem, (MediaItem.content_id == ContentItem.id) & (MediaItem.media_type == "ebook"))
        .order_by(desc(BookAnnotation.created_at))
        .limit(limit)
        .all()
    )

    data = []
    for ann, content, media in rows:
        meta = {}
        if media.metadata_json:
            try:
                meta = json.loads(media.metadata_json)
            except (json.JSONDecodeError, TypeError):
                pass

        # 信任 DB 中的 cover_path（上传时已验证），列表接口不做磁盘 I/O
        has_cover = bool(meta.get("cover_path"))
        cover_url = f"/api/ebook/{content.id}/cover" if has_cover else meta.get("cover_url")

        data.append({
            "id": ann.id,
            "content_id": content.id,
            "book_title": content.title,
            "book_author": content.author,
            "cover_url": cover_url,
            "cfi_range": ann.cfi_range,
            "section_index": ann.section_index,
            "location": ann.location,
            "type": ann.type,
            "color": ann.color,
            "selected_text": ann.selected_text,
            "note": ann.note,
            "created_at": ann.created_at.isoformat() if ann.created_at else None,
            "updated_at": ann.updated_at.isoformat() if ann.updated_at else None,
        })

    return {"code": 0, "data": data, "message": "ok"}


@router.get("/annotations")
async def list_all_annotations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    content_id: Optional[str] = Query(None, description="按书筛选"),
    color: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query("created_at", description="created_at / updated_at"),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
):
    """跨书标注搜索"""
    query = (
        db.query(BookAnnotation, ContentItem, MediaItem)
        .join(ContentItem, ContentItem.id == BookAnnotation.content_id)
        .join(MediaItem, (MediaItem.content_id == ContentItem.id) & (MediaItem.media_type == "ebook"))
    )

    if content_id:
        query = query.filter(BookAnnotation.content_id == content_id)
    if color:
        query = query.filter(BookAnnotation.color == color)
    if type:
        query = query.filter(BookAnnotation.type == type)
    if search:
        like = f"%{_escape_like(search)}%"
        query = query.filter(
            or_(
                BookAnnotation.selected_text.ilike(like),
                BookAnnotation.note.ilike(like),
            )
        )

    total = query.count()

    sort_col = BookAnnotation.updated_at if sort_by == "updated_at" else BookAnnotation.created_at
    order_expr = desc(sort_col) if sort_order == "desc" else asc(sort_col)
    query = query.order_by(order_expr).offset((page - 1) * page_size).limit(page_size)

    data = []
    for ann, content, media in query.all():
        meta = {}
        if media.metadata_json:
            try:
                meta = json.loads(media.metadata_json)
            except (json.JSONDecodeError, TypeError):
                pass
        has_cover = bool(meta.get("cover_path"))
        cover_url = f"/api/ebook/{content.id}/cover" if has_cover else meta.get("cover_url")

        data.append({
            "id": ann.id,
            "content_id": content.id,
            "book_title": content.title,
            "book_author": content.author,
            "cover_url": cover_url,
            "location": ann.location,
            "type": ann.type,
            "color": ann.color,
            "selected_text": ann.selected_text,
            "note": ann.note,
            "created_at": ann.created_at.isoformat() if ann.created_at else None,
            "updated_at": ann.updated_at.isoformat() if ann.updated_at else None,
        })

    return {
        "code": 0,
        "data": data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "message": "ok",
    }


# ─── Filters ──────────────────────────────────────────────────────────────────

@router.get("/filters")
async def get_ebook_filters(db: Session = Depends(get_db)):
    """获取筛选选项：distinct 作者列表 + 汇总分类列表"""
    rows = (
        db.query(ContentItem.author, ContentItem.raw_data)
        .join(MediaItem, MediaItem.content_id == ContentItem.id)
        .filter(MediaItem.media_type == "ebook")
        .all()
    )

    authors = set()
    categories = set()
    sources = set()
    for author_val, raw_data in rows:
        if author_val:
            authors.add(author_val)
        if raw_data:
            try:
                raw = json.loads(raw_data)
                for s in raw.get("subjects", []):
                    if s:
                        categories.add(s)
                if raw.get("source"):
                    sources.add(raw["source"])
            except (json.JSONDecodeError, TypeError):
                pass

    return {
        "code": 0,
        "data": {
            "authors": sorted(authors),
            "categories": sorted(categories),
            "sources": sorted(sources),
        },
        "message": "ok",
    }


# ─── Metadata ──────────────────────────────────────────────────────────────────

@router.put("/{content_id}/metadata")
async def update_ebook_metadata(
    content_id: str,
    body: EbookMetadataUpdate,
    db: Session = Depends(get_db),
):
    """手动编辑元数据"""
    content = db.get(ContentItem, content_id)
    if not content:
        return error_response(404, "电子书不存在")

    if body.title is not None:
        content.title = body.title
    if body.author is not None:
        content.author = body.author

    raw = {}
    if content.raw_data:
        try:
            raw = json.loads(content.raw_data)
        except (json.JSONDecodeError, TypeError):
            pass

    field_map = {
        "description": body.description,
        "isbn": body.isbn,
        "publisher": body.publisher,
        "language": body.language,
        "subjects": body.subjects,
        "publish_date": body.publish_date,
        "series": body.series,
        "page_count": body.page_count,
    }
    for key, val in field_map.items():
        if val is not None:
            raw[key] = val

    raw["metadata_source"] = "manual"
    content.raw_data = json.dumps(raw, ensure_ascii=False)
    content.updated_at = utcnow()
    db.commit()

    return {"code": 0, "data": {"content_id": content_id}, "message": "ok"}


@router.get("/{content_id}/metadata/search")
async def search_book_metadata(
    content_id: str,
    query: Optional[str] = Query(None, description="自定义搜索词（freeform）"),
    title: Optional[str] = Query(None, description="书名（结构化搜索）"),
    author: Optional[str] = Query(None, description="作者（结构化搜索）"),
    isbn: Optional[str] = Query(None, description="ISBN（结构化搜索）"),
    db: Session = Depends(get_db),
):
    """在线搜索书籍元数据（Google Books API）

    三种模式：
    - 有 query：用户手动输入，走 freeform 搜索（自动 langRestrict）
    - 有 title/author/isbn：前端发送结构化字段，走 intitle:/inauthor:/isbn:
    - 都没有：从 DB 的 content.title/author/isbn 自动填充，走结构化搜索
    """
    content = db.get(ContentItem, content_id)
    if not content:
        return error_response(404, "电子书不存在")

    if query:
        # 用户手动输入的 freeform 搜索
        results = await search_google_books(query, max_results=5)
    elif title or author or isbn:
        # 前端传入结构化字段
        results = await search_google_books_structured(
            title=title or "", author=author or "", isbn=isbn or "",
        )
    else:
        # 从 DB 自动填充结构化搜索
        raw = {}
        if content.raw_data:
            try:
                raw = json.loads(content.raw_data)
            except (json.JSONDecodeError, TypeError):
                pass
        db_isbn = raw.get("isbn", "")
        db_title = content.title or ""
        db_author = content.author or ""
        if not db_title and not db_author and not db_isbn:
            return {"code": 0, "data": [], "message": "ok"}
        results = await search_google_books_structured(
            title=db_title, author=db_author, isbn=db_isbn,
        )

    # 获取当前书的 ISBN 用于标记"已应用"
    current_isbn = None
    if content.raw_data:
        try:
            current_isbn = json.loads(content.raw_data).get("isbn")
        except (json.JSONDecodeError, TypeError):
            pass

    data = []
    for r in results:
        item = BookSearchResult(
            title=r.title,
            author=r.author,
            isbn_10=r.isbn_10,
            isbn_13=r.isbn_13,
            publisher=r.publisher,
            publish_date=r.publish_date,
            language=r.language,
            page_count=r.page_count,
            subjects=r.subjects,
            description=r.description,
            cover_url=r.cover_url,
        ).model_dump()
        # 标记当前已应用的结果
        if current_isbn and (r.isbn_13 == current_isbn or r.isbn_10 == current_isbn):
            item["is_current"] = True
        else:
            item["is_current"] = False
        data.append(item)

    return {
        "code": 0,
        "data": data,
        "message": "ok",
    }


@router.post("/{content_id}/metadata/apply")
async def apply_book_metadata(
    content_id: str,
    body: MetadataApplyRequest,
    db: Session = Depends(get_db),
):
    """将选中的在线搜索结果应用到书籍"""
    content = db.get(ContentItem, content_id)
    if not content:
        return error_response(404, "电子书不存在")

    if body.title:
        content.title = body.title
    if body.author:
        content.author = body.author

    raw = {}
    if content.raw_data:
        try:
            raw = json.loads(content.raw_data)
        except (json.JSONDecodeError, TypeError):
            pass

    if body.description:
        raw["description"] = body.description
    if body.publisher:
        raw["publisher"] = body.publisher
    if body.language:
        raw["language"] = body.language
    if body.publish_date:
        raw["publish_date"] = body.publish_date
    if body.page_count:
        raw["page_count"] = body.page_count
    if body.subjects:
        existing = set(raw.get("subjects", []))
        existing.update(body.subjects)
        raw["subjects"] = sorted(existing)

    isbn = body.isbn_13 or body.isbn_10
    if isbn:
        raw["isbn"] = isbn

    raw["metadata_source"] = "google_books"
    content.raw_data = json.dumps(raw, ensure_ascii=False)
    content.updated_at = utcnow()
    db.commit()

    return {"code": 0, "data": {"content_id": content_id}, "message": "ok"}


# ─── Detail / Delete ────────────────────────────────────────────────────────

@router.get("/{content_id}")
async def get_ebook_detail(content_id: str, db: Session = Depends(get_db)):
    """电子书详情"""
    content = db.get(ContentItem, content_id)
    if not content:
        return error_response(404, "电子书不存在")

    media = db.query(MediaItem).filter(
        MediaItem.content_id == content_id,
        MediaItem.media_type == "ebook",
    ).first()
    if not media:
        return error_response(404, "电子书文件不存在")

    progress = db.query(ReadingProgress).filter(
        ReadingProgress.content_id == content_id
    ).first()

    meta = {}
    if media.metadata_json:
        try:
            meta = json.loads(media.metadata_json)
        except (json.JSONDecodeError, TypeError):
            pass

    raw = {}
    if content.raw_data:
        try:
            raw = json.loads(content.raw_data)
        except (json.JSONDecodeError, TypeError):
            pass

    cover_path_val = meta.get("cover_path")
    has_cover = False
    if cover_path_val:
        try:
            has_cover = _safe_media_path(cover_path_val).is_file()
        except Exception:
            pass

    cover_url = f"/api/ebook/{content.id}/cover" if has_cover else meta.get("cover_url")

    return {
        "code": 0,
        "data": {
            "content_id": content.id,
            "title": content.title,
            "author": content.author,
            "format": meta.get("format", "epub"),
            "file_size": meta.get("file_size"),
            "cover_url": cover_url,
            "language": raw.get("language"),
            "publisher": raw.get("publisher"),
            "description": raw.get("description"),
            "isbn": raw.get("isbn"),
            "subjects": raw.get("subjects", []),
            "publish_date": raw.get("publish_date"),
            "series": raw.get("series"),
            "page_count": raw.get("page_count"),
            "metadata_source": raw.get("metadata_source"),
            "toc": raw.get("toc", []),
            "progress": {
                "cfi": progress.cfi if progress else None,
                "progress": progress.progress if progress else 0,
                "section_index": progress.section_index if progress else 0,
                "section_title": progress.section_title if progress else None,
                "updated_at": progress.updated_at.isoformat() if progress and progress.updated_at else None,
            },
            "created_at": content.created_at.isoformat() if content.created_at else None,
            "source": raw.get("source"),
            "external_id": content.external_id,
            "media_status": media.status,
        },
        "message": "ok",
    }


@router.delete("/{content_id}")
async def delete_ebook(content_id: str, db: Session = Depends(get_db)):
    """删除电子书: 文件 + DB 记录"""
    import shutil

    content = db.get(ContentItem, content_id)
    if not content:
        return error_response(404, "电子书不存在")

    # 删除关联数据
    db.query(BookAnnotation).filter(BookAnnotation.content_id == content_id).delete(synchronize_session=False)
    db.query(BookBookmark).filter(BookBookmark.content_id == content_id).delete(synchronize_session=False)
    db.query(ReadingProgress).filter(ReadingProgress.content_id == content_id).delete(synchronize_session=False)
    db.query(MediaItem).filter(MediaItem.content_id == content_id).delete(synchronize_session=False)
    db.query(ContentItem).filter(ContentItem.id == content_id).delete(synchronize_session=False)
    db.commit()

    # 清理磁盘（DB 已删除，文件清理失败只记日志，不影响响应）
    media_dir = Path(settings.MEDIA_DIR) / content_id
    if media_dir.is_dir():
        try:
            shutil.rmtree(media_dir)
        except OSError as e:
            logger.warning(f"Orphan files left at {media_dir}: {e}")

    logger.info(f"Deleted ebook content_id={content_id}")
    return {"code": 0, "data": {"deleted": 1}, "message": "ok"}


# ─── Cover ────────────────────────────────────────────────────────────────────

@router.get("/{content_id}/cover")
async def get_ebook_cover(content_id: str, db: Session = Depends(get_db)):
    """返回封面图"""
    media = db.query(MediaItem).filter(
        MediaItem.content_id == content_id,
        MediaItem.media_type == "ebook",
    ).first()

    if media and media.metadata_json:
        try:
            meta = json.loads(media.metadata_json)
            cover_path_val = meta.get("cover_path")
            if cover_path_val:
                safe_cover = _safe_media_path(cover_path_val)
                if safe_cover.is_file():
                    mime, _ = mimetypes.guess_type(str(safe_cover))
                    return FileResponse(
                        str(safe_cover),
                        media_type=mime or "image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"},
                    )
        except (json.JSONDecodeError, TypeError):
            pass

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="封面未找到")


# ─── Annotations ─────────────────────────────────────────────────────────────

def _annotation_dict(a: BookAnnotation) -> dict:
    return {
        "id": a.id,
        "cfi_range": a.cfi_range,
        "section_index": a.section_index,
        "location": a.location,
        "type": a.type,
        "color": a.color,
        "selected_text": a.selected_text,
        "note": a.note,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


@router.get("/{content_id}/annotations")
async def list_annotations(
    content_id: str,
    color: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    group_by_chapter: bool = Query(False),
    db: Session = Depends(get_db),
):
    """获取标注，支持筛选/搜索/章节分组"""
    query = db.query(BookAnnotation).filter(
        BookAnnotation.content_id == content_id
    )

    if color:
        query = query.filter(BookAnnotation.color == color)
    if type:
        query = query.filter(BookAnnotation.type == type)
    if search:
        like = f"%{_escape_like(search)}%"
        query = query.filter(
            or_(
                BookAnnotation.selected_text.ilike(like),
                BookAnnotation.note.ilike(like),
            )
        )

    items = query.order_by(BookAnnotation.created_at).all()

    if not group_by_chapter:
        return {
            "code": 0,
            "data": [_annotation_dict(a) for a in items],
            "message": "ok",
        }

    # 按 location 分组
    groups: dict[Optional[str], list] = {}
    for a in items:
        key = a.location
        groups.setdefault(key, []).append(_annotation_dict(a))

    chapters = []
    for chapter, anns in groups.items():
        if chapter is not None:
            chapters.append({"chapter": chapter, "count": len(anns), "annotations": anns})

    # None 组排最后
    if None in groups:
        anns = groups[None]
        chapters.append({"chapter": None, "count": len(anns), "annotations": anns})

    return {
        "code": 0,
        "data": {"chapters": chapters, "total": len(items)},
        "message": "ok",
    }


@router.post("/{content_id}/annotations")
async def create_annotation(
    content_id: str,
    body: AnnotationCreate,
    db: Session = Depends(get_db),
):
    """创建标注"""
    content = db.get(ContentItem, content_id)
    if not content:
        return error_response(404, "电子书不存在")

    now = utcnow()
    ann = BookAnnotation(
        id=uuid.uuid4().hex,
        content_id=content_id,
        external_id=None,
        cfi_range=body.cfi_range,
        section_index=body.section_index,
        location=body.location,
        type=body.type,
        color=body.color,
        selected_text=body.selected_text,
        note=body.note,
        created_at=now,
        updated_at=now,
    )
    db.add(ann)
    db.commit()

    return {"code": 0, "data": _annotation_dict(ann), "message": "ok"}


@router.put("/{content_id}/annotations/{ann_id}")
async def update_annotation(
    content_id: str,
    ann_id: str,
    body: AnnotationUpdate,
    db: Session = Depends(get_db),
):
    """更新标注"""
    ann = db.get(BookAnnotation, ann_id)
    if not ann or ann.content_id != content_id:
        return error_response(404, "标注不存在")

    if body.type is not None:
        ann.type = body.type
    if body.color is not None:
        ann.color = body.color
    if body.note is not None:
        ann.note = body.note
    ann.updated_at = utcnow()
    db.commit()

    return {"code": 0, "data": _annotation_dict(ann), "message": "ok"}


@router.delete("/{content_id}/annotations/{ann_id}")
async def delete_annotation(
    content_id: str,
    ann_id: str,
    db: Session = Depends(get_db),
):
    """删除标注"""
    ann = db.get(BookAnnotation, ann_id)
    if not ann or ann.content_id != content_id:
        return error_response(404, "标注不存在")

    db.delete(ann)
    db.commit()

    return {"code": 0, "data": {"deleted": 1}, "message": "ok"}
