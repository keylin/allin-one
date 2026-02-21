"""Ebook API — 电子书上传、书架、阅读进度、批注、书签"""

import hashlib
import json
import logging
import mimetypes
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import desc, asc
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.time import utcnow
from app.models.content import ContentItem, ContentStatus, MediaItem
from app.models.ebook import ReadingProgress, BookAnnotation, BookBookmark
from app.schemas import error_response
from app.schemas.ebook import (
    ReadingProgressUpdate,
    AnnotationCreate, AnnotationUpdate,
    BookmarkCreate,
)
from app.services.ebook_parser import parse_ebook, EbookMetadata

logger = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_EXTENSIONS = {".epub", ".mobi", ".azw", ".azw3"}
MAX_EBOOK_SIZE = 200 * 1024 * 1024  # 200 MB


def _safe_media_path(rel_or_abs: str) -> Path:
    """验证路径在 MEDIA_DIR 范围内，防止路径遍历攻击。"""
    media_root = Path(settings.MEDIA_DIR).resolve()
    # 兼容已有的绝对路径和新的相对路径
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = media_root / p
    real = p.resolve()
    if not str(real).startswith(str(media_root) + os.sep) and real != media_root:
        raise HTTPException(status_code=403, detail="非法路径")
    return real


# ─── Upload ──────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_ebook(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传电子书文件，解析元数据，创建 ContentItem + MediaItem"""
    filename = file.filename or "unnamed"
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return error_response(400, f"不支持的文件格式: {ext}，支持: {', '.join(SUPPORTED_EXTENSIONS)}")

    # 生成 content_id 并保存文件（流式写入 + 大小限制）
    content_id = uuid.uuid4().hex
    media_dir = Path(settings.MEDIA_DIR) / content_id
    media_dir.mkdir(parents=True, exist_ok=True)

    book_filename = f"book{ext}"
    book_path = media_dir / book_filename

    file_size = 0
    file_hash = hashlib.sha256()
    try:
        with open(book_path, "wb") as f:
            while chunk := await file.read(65536):
                file_size += len(chunk)
                if file_size > MAX_EBOOK_SIZE:
                    f.close()
                    shutil.rmtree(media_dir, ignore_errors=True)
                    return error_response(413, f"文件过大，最大支持 {MAX_EBOOK_SIZE // 1024 // 1024} MB")
                file_hash.update(chunk)
                f.write(chunk)
    except Exception:
        shutil.rmtree(media_dir, ignore_errors=True)
        raise

    if file_size == 0:
        shutil.rmtree(media_dir, ignore_errors=True)
        return error_response(400, "文件为空")

    # 解析元数据 (foliate-js 前端原生支持 EPUB/MOBI，无需转换)
    try:
        metadata = parse_ebook(str(book_path))
    except Exception as e:
        logger.warning(f"Ebook metadata parsing failed: {e}")
        metadata = EbookMetadata(title=Path(filename).stem)

    # 保存封面（存相对路径）
    cover_rel = None
    if metadata.cover_data:
        cover_ext = metadata.cover_ext or "jpg"
        cover_file = media_dir / f"cover.{cover_ext}"
        cover_file.write_bytes(metadata.cover_data)
        cover_rel = f"{content_id}/cover.{cover_ext}"

    # 创建 ContentItem（使用文件内容 hash 去重）
    external_id = file_hash.hexdigest()[:32]
    raw_data = json.dumps({
        "format": ext.lstrip("."),
        "filename": filename,
        "file_size": file_size,
        "language": metadata.language,
        "publisher": metadata.publisher,
        "description": metadata.description,
        "toc": metadata.toc_to_list(),
    }, ensure_ascii=False)

    content = ContentItem(
        id=content_id,
        title=metadata.title,
        author=metadata.author,
        external_id=external_id,
        raw_data=raw_data,
        status=ContentStatus.READY.value,
    )
    db.add(content)
    db.flush()

    # 创建 MediaItem
    media_metadata = {
        "format": ext.lstrip("."),
        "file_size": file_size,
        "original_filename": filename,
    }
    if cover_rel:
        media_metadata["cover_path"] = cover_rel
    if metadata.language:
        media_metadata["language"] = metadata.language

    media_item = MediaItem(
        content_id=content_id,
        media_type="ebook",
        original_url=f"file://{filename}",
        local_path=str(book_path),
        filename=book_filename,
        status="downloaded",
        metadata_json=json.dumps(media_metadata, ensure_ascii=False),
    )
    db.add(media_item)

    # 初始化阅读进度
    progress = ReadingProgress(content_id=content_id)
    db.add(progress)

    try:
        db.commit()
    except Exception:
        shutil.rmtree(media_dir, ignore_errors=True)
        raise

    logger.info(f"Ebook uploaded: {metadata.title} ({ext}) content_id={content_id}")

    return {
        "code": 0,
        "data": {
            "content_id": content_id,
            "title": metadata.title,
            "author": metadata.author,
            "format": ext.lstrip("."),
            "cover_url": f"/api/ebook/{content_id}/cover" if cover_rel else None,
        },
        "message": "上传成功",
    }


# ─── List ────────────────────────────────────────────────────────────────────

@router.get("/list")
async def list_ebooks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    sort_by: str = Query("updated_at", description="排序: updated_at / title / created_at"),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
):
    """书架列表"""
    query = (
        db.query(ContentItem, MediaItem, ReadingProgress)
        .join(MediaItem, MediaItem.content_id == ContentItem.id)
        .outerjoin(ReadingProgress, ReadingProgress.content_id == ContentItem.id)
        .filter(MediaItem.media_type == "ebook")
    )

    if search:
        like = f"%{search}%"
        query = query.filter(
            (ContentItem.title.ilike(like)) | (ContentItem.author.ilike(like))
        )

    total = query.count()

    # 排序
    sort_map = {
        "title": ContentItem.title,
        "created_at": ContentItem.created_at,
    }
    if sort_by == "updated_at":
        sort_column = ReadingProgress.updated_at
    else:
        sort_column = sort_map.get(sort_by, ContentItem.created_at)

    order_expr = desc(sort_column).nulls_last() if sort_order == "desc" else asc(sort_column).nulls_last()
    query = query.order_by(order_expr).offset((page - 1) * page_size).limit(page_size)

    data = []
    for content, media, progress in query.all():
        meta = {}
        if media.metadata_json:
            try:
                meta = json.loads(media.metadata_json)
            except (json.JSONDecodeError, TypeError):
                pass

        cover_path_val = meta.get("cover_path")
        has_cover = False
        if cover_path_val:
            try:
                has_cover = _safe_media_path(cover_path_val).is_file()
            except Exception:
                pass

        data.append({
            "content_id": content.id,
            "title": content.title,
            "author": content.author,
            "format": meta.get("format", "epub"),
            "file_size": meta.get("file_size"),
            "cover_url": f"/api/ebook/{content.id}/cover" if has_cover else None,
            "progress": progress.progress if progress else 0,
            "section_title": progress.section_title if progress else None,
            "last_read_at": progress.updated_at.isoformat() if progress and progress.updated_at else None,
            "created_at": content.created_at.isoformat() if content.created_at else None,
        })

    return {
        "code": 0,
        "data": data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "message": "ok",
    }


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

    return {
        "code": 0,
        "data": {
            "content_id": content.id,
            "title": content.title,
            "author": content.author,
            "format": meta.get("format", "epub"),
            "file_size": meta.get("file_size"),
            "cover_url": f"/api/ebook/{content.id}/cover" if has_cover else None,
            "language": raw.get("language"),
            "publisher": raw.get("publisher"),
            "description": raw.get("description"),
            "toc": raw.get("toc", []),
            "progress": {
                "cfi": progress.cfi if progress else None,
                "progress": progress.progress if progress else 0,
                "section_index": progress.section_index if progress else 0,
                "section_title": progress.section_title if progress else None,
                "updated_at": progress.updated_at.isoformat() if progress and progress.updated_at else None,
            },
            "created_at": content.created_at.isoformat() if content.created_at else None,
        },
        "message": "ok",
    }


@router.delete("/{content_id}")
async def delete_ebook(content_id: str, db: Session = Depends(get_db)):
    """删除电子书: 文件 + DB 记录"""
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

    # 清理磁盘
    media_dir = Path(settings.MEDIA_DIR) / content_id
    if media_dir.is_dir():
        shutil.rmtree(media_dir, ignore_errors=True)

    logger.info(f"Deleted ebook content_id={content_id}")
    return {"code": 0, "data": {"deleted": 1}, "message": "ok"}


# ─── File / Cover ────────────────────────────────────────────────────────────

@router.get("/{content_id}/file")
async def get_ebook_file(content_id: str, db: Session = Depends(get_db)):
    """返回电子书原始文件 (供 foliate-js 加载)"""
    media = db.query(MediaItem).filter(
        MediaItem.content_id == content_id,
        MediaItem.media_type == "ebook",
        MediaItem.status == "downloaded",
    ).first()

    if not media or not media.local_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="电子书文件未找到")

    safe_path = _safe_media_path(media.local_path)
    if not safe_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="电子书文件未找到")

    mime_map = {
        ".epub": "application/epub+zip",
        ".mobi": "application/x-mobipocket-ebook",
        ".azw": "application/x-mobipocket-ebook",
        ".azw3": "application/x-mobipocket-ebook",
    }
    ext = safe_path.suffix.lower()
    mime_type = mime_map.get(ext, "application/octet-stream")

    # ETag for conditional requests (avoid re-downloading unchanged files)
    mtime = int(safe_path.stat().st_mtime)
    etag = hashlib.md5(f"{content_id}:{mtime}".encode()).hexdigest()

    return FileResponse(
        str(safe_path),
        media_type=mime_type,
        filename=safe_path.name,
        headers={
            "ETag": f'"{etag}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


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


# ─── Reading Progress ────────────────────────────────────────────────────────

@router.get("/{content_id}/progress")
async def get_reading_progress(content_id: str, db: Session = Depends(get_db)):
    """获取阅读进度"""
    progress = db.query(ReadingProgress).filter(
        ReadingProgress.content_id == content_id
    ).first()

    if not progress:
        return {
            "code": 0,
            "data": {"cfi": None, "progress": 0, "section_index": 0, "section_title": None, "updated_at": None},
            "message": "ok",
        }

    return {
        "code": 0,
        "data": {
            "cfi": progress.cfi,
            "progress": progress.progress,
            "section_index": progress.section_index,
            "section_title": progress.section_title,
            "updated_at": progress.updated_at.isoformat() if progress.updated_at else None,
        },
        "message": "ok",
    }


@router.put("/{content_id}/progress")
async def update_reading_progress(
    content_id: str,
    body: ReadingProgressUpdate,
    db: Session = Depends(get_db),
):
    """更新阅读进度"""
    progress = db.query(ReadingProgress).filter(
        ReadingProgress.content_id == content_id
    ).first()

    if not progress:
        progress = ReadingProgress(content_id=content_id)
        db.add(progress)

    if body.cfi is not None:
        progress.cfi = body.cfi
    progress.progress = max(0.0, min(1.0, body.progress))
    if body.section_index is not None:
        progress.section_index = body.section_index
    if body.section_title is not None:
        progress.section_title = body.section_title
    progress.updated_at = utcnow()

    db.commit()

    return {
        "code": 0,
        "data": {
            "cfi": progress.cfi,
            "progress": progress.progress,
            "section_index": progress.section_index,
            "section_title": progress.section_title,
        },
        "message": "ok",
    }


# ─── Annotations (Phase 2) ──────────────────────────────────────────────────

@router.get("/{content_id}/annotations")
async def list_annotations(content_id: str, db: Session = Depends(get_db)):
    """获取全部批注"""
    items = db.query(BookAnnotation).filter(
        BookAnnotation.content_id == content_id
    ).order_by(BookAnnotation.created_at).all()

    return {
        "code": 0,
        "data": [
            {
                "id": a.id,
                "cfi_range": a.cfi_range,
                "section_index": a.section_index,
                "type": a.type,
                "color": a.color,
                "selected_text": a.selected_text,
                "note": a.note,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in items
        ],
        "message": "ok",
    }


@router.post("/{content_id}/annotations")
async def create_annotation(
    content_id: str,
    body: AnnotationCreate,
    db: Session = Depends(get_db),
):
    """新增批注"""
    annotation = BookAnnotation(
        content_id=content_id,
        cfi_range=body.cfi_range,
        section_index=body.section_index,
        type=body.type,
        color=body.color,
        selected_text=body.selected_text,
        note=body.note,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)

    return {
        "code": 0,
        "data": {"id": annotation.id},
        "message": "ok",
    }


@router.put("/{content_id}/annotations/{annotation_id}")
async def update_annotation(
    content_id: str,
    annotation_id: str,
    body: AnnotationUpdate,
    db: Session = Depends(get_db),
):
    """修改批注"""
    annotation = db.get(BookAnnotation, annotation_id)
    if not annotation or annotation.content_id != content_id:
        return error_response(404, "批注不存在")

    if body.color is not None:
        annotation.color = body.color
    if body.note is not None:
        annotation.note = body.note
    annotation.updated_at = utcnow()

    db.commit()
    return {"code": 0, "data": {"id": annotation.id}, "message": "ok"}


@router.delete("/{content_id}/annotations/{annotation_id}")
async def delete_annotation(
    content_id: str,
    annotation_id: str,
    db: Session = Depends(get_db),
):
    """删除批注"""
    deleted = db.query(BookAnnotation).filter(
        BookAnnotation.id == annotation_id,
        BookAnnotation.content_id == content_id,
    ).delete(synchronize_session=False)
    db.commit()

    if not deleted:
        return error_response(404, "批注不存在")
    return {"code": 0, "data": {"deleted": 1}, "message": "ok"}


# ─── Bookmarks (Phase 2) ────────────────────────────────────────────────────

@router.get("/{content_id}/bookmarks")
async def list_bookmarks(content_id: str, db: Session = Depends(get_db)):
    """获取全部书签"""
    items = db.query(BookBookmark).filter(
        BookBookmark.content_id == content_id
    ).order_by(BookBookmark.created_at).all()

    return {
        "code": 0,
        "data": [
            {
                "id": b.id,
                "cfi": b.cfi,
                "title": b.title,
                "section_title": b.section_title,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
            for b in items
        ],
        "message": "ok",
    }


@router.post("/{content_id}/bookmarks")
async def create_bookmark(
    content_id: str,
    body: BookmarkCreate,
    db: Session = Depends(get_db),
):
    """新增书签"""
    bookmark = BookBookmark(
        content_id=content_id,
        cfi=body.cfi,
        title=body.title,
        section_title=body.section_title,
    )
    db.add(bookmark)
    db.commit()
    db.refresh(bookmark)

    return {"code": 0, "data": {"id": bookmark.id}, "message": "ok"}


@router.delete("/{content_id}/bookmarks/{bookmark_id}")
async def delete_bookmark(
    content_id: str,
    bookmark_id: str,
    db: Session = Depends(get_db),
):
    """删除书签"""
    deleted = db.query(BookBookmark).filter(
        BookBookmark.id == bookmark_id,
        BookBookmark.content_id == content_id,
    ).delete(synchronize_session=False)
    db.commit()

    if not deleted:
        return error_response(404, "书签不存在")
    return {"code": 0, "data": {"deleted": 1}, "message": "ok"}
