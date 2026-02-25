#!/usr/bin/env python3
"""Apple Books → Allin-One 同步脚本

从 macOS Apple Books 本地 SQLite 读取书籍元数据、阅读进度、高亮和笔记，
推送到 Allin-One 后端 API。

依赖（独立于 backend requirements）:
  pip install py-apple-books httpx

用法:
  python scripts/apple-books-sync.py --api-url http://localhost:8000
  python scripts/apple-books-sync.py --api-url http://localhost:8000 --full
  python scripts/apple-books-sync.py --api-url http://localhost:8000 --api-key YOUR_KEY
"""

import argparse
import sys
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    print("错误: 请安装 httpx — pip install httpx")
    sys.exit(1)

try:
    from apple_books import AppleBooks
except ImportError:
    print("错误: 请安装 py-apple-books — pip install py-apple-books")
    sys.exit(1)


# Apple Books 颜色枚举 → 我们的颜色
COLOR_MAP = {
    0: "yellow",   # Underline (default)
    1: "green",
    2: "blue",
    3: "yellow",
    4: "pink",
    5: "purple",
}

# Apple Books annotation style → type
STYLE_MAP = {
    0: "highlight",  # underline
    1: "highlight",  # highlight
    2: "note",       # note
}


def get_headers(api_key: str | None) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def setup_source(api_url: str, api_key: str | None) -> str:
    """调用 setup API 获取或创建 source_id"""
    resp = httpx.post(
        f"{api_url}/api/ebook/sync/setup",
        headers=get_headers(api_key),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != 0:
        print(f"Setup 失败: {data['message']}")
        sys.exit(1)
    return data["data"]["source_id"]


def get_sync_status(api_url: str, api_key: str | None, source_id: str | None = None) -> dict:
    """获取同步状态（传 source_id 获取本源精确时间，避免多平台并存时聚合时间戳干扰增量过滤）"""
    params = {"source_id": source_id} if source_id else {}
    resp = httpx.get(
        f"{api_url}/api/ebook/sync/status",
        headers=get_headers(api_key),
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", {})


def sync_books(api_url: str, api_key: str | None, source_id: str, books_payload: list) -> dict:
    """推送同步数据"""
    resp = httpx.post(
        f"{api_url}/api/ebook/sync",
        json={"source_id": source_id, "books": books_payload},
        headers=get_headers(api_key),
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != 0:
        print(f"同步失败: {data['message']}")
        sys.exit(1)
    return data["data"]


def dt_to_iso(dt) -> str | None:
    """datetime → ISO 字符串"""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=None).isoformat()
    return str(dt)


def main():
    parser = argparse.ArgumentParser(description="Apple Books → Allin-One 同步")
    parser.add_argument("--api-url", required=True, help="后端 API 地址 (如 http://localhost:8000)")
    parser.add_argument("--api-key", default=None, help="API Key (可选)")
    parser.add_argument("--full", action="store_true", help="强制全量同步")
    parser.add_argument("--dry-run", action="store_true", help="仅打印将要同步的数据")
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/")

    # 1. Setup source
    print("正在设置同步源...")
    source_id = setup_source(api_url, args.api_key)
    print(f"  source_id: {source_id}")

    # 2. Get last sync time for incremental sync
    last_sync_at = None
    if not args.full:
        status = get_sync_status(api_url, args.api_key, source_id=source_id)
        if status.get("last_sync_at"):
            last_sync_at = datetime.fromisoformat(status["last_sync_at"])
            print(f"  上次同步: {last_sync_at.isoformat()}")
        else:
            print("  首次同步，将进行全量同步")

    # 3. Read Apple Books data
    print("正在读取 Apple Books 数据...")
    ab = AppleBooks()
    all_books = ab.list_books()
    print(f"  Apple Books 中共 {len(all_books)} 本书")

    # 4. Build payload
    books_payload = []
    for book in all_books:
        # Get annotations for this book
        try:
            book_annotations = [a for a in ab.list_annotations() if a.book and a.book.id == book.id]
        except Exception:
            book_annotations = []

        # Incremental filter: skip books with no recent changes
        if last_sync_at and not args.full:
            book_modified = False
            # Check if any annotation was modified after last_sync_at
            for ann in book_annotations:
                ann_modified = getattr(ann, "modification_date", None) or getattr(ann, "created", None)
                if ann_modified and ann_modified.replace(tzinfo=None) > last_sync_at:
                    book_modified = True
                    break
            if not book_modified:
                continue

        # Map annotations
        annotations = []
        for ann in book_annotations:
            ann_id = getattr(ann, "id", None)
            if not ann_id:
                continue

            color_val = getattr(ann, "color", None)
            if isinstance(color_val, int):
                color = COLOR_MAP.get(color_val, "yellow")
            elif isinstance(color_val, str):
                color = color_val.lower() if color_val.lower() in COLOR_MAP.values() else "yellow"
            else:
                color = "yellow"

            style_val = getattr(ann, "style", None)
            ann_type = STYLE_MAP.get(style_val, "highlight") if isinstance(style_val, int) else "highlight"

            is_deleted = getattr(ann, "is_deleted", False) or False

            annotations.append({
                "id": str(ann_id),
                "selected_text": getattr(ann, "selected_text", None) or getattr(ann, "representative_text", None),
                "note": getattr(ann, "note", None),
                "color": color,
                "type": ann_type,
                "chapter": getattr(ann, "chapter", None),
                "location": getattr(ann, "location", None),
                "is_deleted": is_deleted,
                "created_at": dt_to_iso(getattr(ann, "created", None) or getattr(ann, "creation_date", None)),
                "modified_at": dt_to_iso(getattr(ann, "modification_date", None)),
            })

        # Reading progress
        progress = 0.0
        is_finished = getattr(book, "is_finished", False) or False
        if is_finished:
            progress = 1.0
        else:
            raw_progress = getattr(book, "reading_progress", None)
            if raw_progress is not None:
                try:
                    progress = float(raw_progress)
                except (ValueError, TypeError):
                    pass

        book_entry = {
            "asset_id": str(book.id),
            "title": getattr(book, "title", "未知书名") or "未知书名",
            "author": getattr(book, "author", None),
            "genre": getattr(book, "genre", None),
            "page_count": getattr(book, "page_count", None),
            "is_finished": is_finished,
            "reading_progress": progress,
            "annotations": annotations,
        }
        books_payload.append(book_entry)

    print(f"  将同步 {len(books_payload)} 本书")
    total_annotations = sum(len(b["annotations"]) for b in books_payload)
    print(f"  共 {total_annotations} 条标注")

    if not books_payload:
        print("没有需要同步的数据")
        return

    if args.dry_run:
        import json
        print("\n--- Dry Run 数据 ---")
        for b in books_payload:
            print(f"  [{b['asset_id'][:8]}] {b['title']} — {b['author']} — {len(b['annotations'])} 条标注 — 进度 {b['reading_progress']:.0%}")
        return

    # 5. Push to API
    print("正在推送到 Allin-One...")
    result = sync_books(api_url, args.api_key, source_id, books_payload)
    print(f"  同步完成:")
    print(f"    新增书籍: {result.get('new_books', 0)}")
    print(f"    更新书籍: {result.get('updated_books', 0)}")
    print(f"    新增标注: {result.get('new_annotations', 0)}")
    print(f"    更新标注: {result.get('updated_annotations', 0)}")
    print(f"    删除标注: {result.get('deleted_annotations', 0)}")


if __name__ == "__main__":
    main()
