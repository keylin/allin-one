#!/usr/bin/env python3
"""微信读书 → Allin-One 同步脚本

从微信读书 Web API 读取书籍元数据、阅读进度、划线标注，
推送到 Allin-One 后端 API。

依赖（独立于 backend requirements）:
  pip install httpx

用法:
  # 从参数传 Cookie
  python scripts/wechat-read-sync.py \
    --api-url http://localhost:8000 \
    --cookie "wr_vid=xxx; wr_skey=xxx; ..."

  # 从环境变量读 Cookie
  export WEREAD_COOKIE="wr_vid=xxx; wr_skey=xxx; ..."
  python scripts/wechat-read-sync.py --api-url http://localhost:8000

  # 全量同步
  python scripts/wechat-read-sync.py --api-url http://localhost:8000 --full

  # 预览模式（不实际写入）
  python scripts/wechat-read-sync.py --api-url http://localhost:8000 --dry-run

Cookie 获取方式:
  1. 浏览器登录 https://weread.qq.com
  2. F12 打开开发者工具 → Network 标签
  3. 刷新页面，找到任意 weread.qq.com 请求
  4. 复制 Request Headers 中的 Cookie 值

注意：Cookie 有效期约 1.5 小时（wr_skey 5400秒）。
      如果提示过期，请重新登录 weread.qq.com 获取。
      不要使用 Console 的 document.cookie，它无法获取 httpOnly 的 wr_skey。
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    print("错误: 请安装 httpx — pip install httpx")
    sys.exit(1)


WEREAD_BASE = "https://weread.qq.com"
SOURCE_TYPE = "sync.wechat_read"

# 微信读书 colorStyle → 颜色名
COLOR_MAP = {
    1: "pink",
    2: "purple",
    3: "blue",
    4: "green",
    5: "yellow",
}

WEREAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


# ─── Allin-One API helpers ─────────────────────────────────────────────────────

def get_headers(api_key: str | None) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def setup_source(api_url: str, api_key: str | None) -> str:
    """调用 setup API 获取或创建 source_id"""
    resp = httpx.post(
        f"{api_url}/api/ebook/sync/setup",
        params={"source_type": SOURCE_TYPE},
        headers=get_headers(api_key),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != 0:
        print(f"Setup 失败: {data['message']}")
        sys.exit(1)
    return data["data"]["source_id"]


def get_sync_status(api_url: str, api_key: str | None, source_id: str) -> dict:
    """获取同步状态"""
    resp = httpx.get(
        f"{api_url}/api/ebook/sync/status",
        params={"source_id": source_id},
        headers=get_headers(api_key),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", {})


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


# ─── 微信读书 API helpers ──────────────────────────────────────────────────────

def weread_client(cookie: str) -> httpx.Client:
    """创建微信读书 HTTP 客户端"""
    headers = {**WEREAD_HEADERS, "Cookie": cookie}
    return httpx.Client(base_url=WEREAD_BASE, headers=headers, timeout=30, follow_redirects=True)


def validate_cookie(client: httpx.Client) -> bool:
    """验证 Cookie 是否有效（通过 notebooks 接口）"""
    resp = client.get("/api/user/notebook")
    if resp.status_code == 401:
        return False
    data = resp.json()
    errcode = data.get("errcode", 0)
    if errcode in (-2012, -2010):
        return False
    return "books" in data


def fetch_notebooks(client: httpx.Client) -> list[dict]:
    """获取有笔记/划线的书列表"""
    resp = client.get("/api/user/notebook")
    resp.raise_for_status()
    data = resp.json()
    return data.get("books", [])


def fetch_shelf(client: httpx.Client) -> dict:
    """获取书架数据（含阅读进度）"""
    resp = client.get("/web/shelf/sync")
    resp.raise_for_status()
    return resp.json()


def fetch_bookmarks(client: httpx.Client, book_id: str) -> list[dict]:
    """获取某本书的划线/标注"""
    resp = client.get("/web/book/bookmarklist", params={"bookId": book_id})
    resp.raise_for_status()
    data = resp.json()
    return data.get("updated", [])


def fetch_reviews(client: httpx.Client, book_id: str) -> list[dict]:
    """获取某本书的想法/笔记（用户自己写的评注）"""
    resp = client.get(
        "/web/review/list",
        params={"bookId": book_id, "listType": "11", "mine": "1", "syncKey": "0"},
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("reviews", [])


def fetch_chapter_infos(client: httpx.Client, book_ids: list[str]) -> dict[str, dict[int, str]]:
    """批量获取章节信息，返回 {bookId: {chapterUid: title}}"""
    if not book_ids:
        return {}
    resp = client.post(
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


def epoch_to_iso(ts: int | None) -> str | None:
    """Unix 时间戳 → ISO 字符串（naive UTC）"""
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None).isoformat()


# ─── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="微信读书 → Allin-One 同步")
    parser.add_argument("--api-url", required=True, help="后端 API 地址 (如 http://localhost:8000)")
    parser.add_argument("--api-key", default=None, help="API Key (可选)")
    parser.add_argument("--cookie", default=None, help="微信读书 Cookie (也可通过 WEREAD_COOKIE 环境变量设置)")
    parser.add_argument("--full", action="store_true", help="强制全量同步")
    parser.add_argument("--dry-run", action="store_true", help="仅打印将要同步的数据，不实际写入")
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/")
    cookie = args.cookie or os.environ.get("WEREAD_COOKIE", "")
    if not cookie:
        print("错误: 请通过 --cookie 参数或 WEREAD_COOKIE 环境变量提供微信读书 Cookie")
        print("获取方式: 浏览器登录 weread.qq.com → F12 → Network → 复制 Cookie")
        sys.exit(1)

    # 1. 验证微信读书 Cookie
    print("正在验证微信读书 Cookie...")
    client = weread_client(cookie)
    if not validate_cookie(client):
        print("错误: Cookie 无效或已过期，请重新获取")
        print("获取方式: 浏览器登录 weread.qq.com → F12 → Network → 复制 Cookie")
        sys.exit(1)
    print("  Cookie 验证通过")

    # 2. Setup source
    print("正在设置同步源...")
    source_id = setup_source(api_url, args.api_key)
    print(f"  source_id: {source_id}")

    # 3. 获取上次同步状态（用于增量过滤）
    last_sync_at = None
    last_total_annotations = 0
    if not args.full:
        status = get_sync_status(api_url, args.api_key, source_id)
        if status.get("last_sync_at"):
            last_sync_at = status["last_sync_at"]
            last_total_annotations = status.get("total_annotations", 0)
            print(f"  上次同步: {last_sync_at}")
            print(f"  已有标注: {last_total_annotations} 条")
        else:
            print("  首次同步，将进行全量同步")

    # 4. 获取微信读书数据
    print("正在获取微信读书数据...")

    # 获取有笔记的书列表
    notebooks = fetch_notebooks(client)
    print(f"  有笔记的书: {len(notebooks)} 本")

    # 获取书架（含进度）
    shelf_data = fetch_shelf(client)
    # 构建进度映射: bookId → {progress, readingTime, ...}
    progress_map = {}
    for bp in shelf_data.get("bookProgress", []):
        progress_map[str(bp.get("bookId", ""))] = bp

    # 获取章节信息（批量）
    book_ids = [str(nb.get("bookId", "")) for nb in notebooks if nb.get("bookId")]
    print(f"  正在获取章节信息...")
    chapter_map = fetch_chapter_infos(client, book_ids)

    # 5. 构建同步数据
    books_payload = []
    skipped = 0

    for nb in notebooks:
        book_id = str(nb.get("bookId", ""))
        book_info = nb.get("book", {})
        note_count = nb.get("noteCount", 0)

        title = book_info.get("title", "未知书名")
        author = book_info.get("author", "")

        # 提取分类
        categories = book_info.get("categories", [])
        genre = categories[0].get("title", "") if categories else None

        # 阅读进度
        bp = progress_map.get(book_id, {})
        raw_progress = bp.get("progress", 0)
        reading_progress = raw_progress / 100.0 if raw_progress else 0.0

        # 是否读完：进度 100 或 finishReading 标记
        is_finished = raw_progress >= 100 or book_info.get("finishReading", 0) == 1
        if is_finished:
            reading_progress = 1.0

        # 获取划线
        time.sleep(0.2)  # 避免请求过快
        bookmarks = fetch_bookmarks(client, book_id)

        # 获取想法/笔记
        time.sleep(0.2)
        reviews = fetch_reviews(client, book_id)

        # 增量过滤：对比 noteCount，如果没有新标注且不是首次同步则跳过
        # 注意：noteCount 包含划线和想法，是微信读书提供的计数
        if last_sync_at and not args.full:
            # 简单策略：如果该书的划线+想法数量没变化就跳过
            current_count = len(bookmarks) + len(reviews)
            if current_count == 0:
                skipped += 1
                continue

        # 章节名映射
        chapters = chapter_map.get(book_id, {})

        # 组装标注
        annotations = []

        # 划线 → annotations
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
                "created_at": epoch_to_iso(bm.get("createTime")),
            })

        # 想法 → annotations（type=note）
        for rv in reviews:
            review = rv.get("review", {})
            review_id = review.get("reviewId", "")
            if not review_id:
                continue

            # type=1 是关联段落的想法，type=4 是书评（跳过书评）
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
                "created_at": epoch_to_iso(review.get("createTime")),
            })

        book_entry = {
            "asset_id": book_id,
            "title": title,
            "author": author,
            "genre": genre,
            "is_finished": is_finished,
            "reading_progress": reading_progress,
            "annotations": annotations,
        }
        books_payload.append(book_entry)

    print(f"  将同步 {len(books_payload)} 本书 (跳过 {skipped} 本无变化)")
    total_annotations = sum(len(b["annotations"]) for b in books_payload)
    print(f"  共 {total_annotations} 条标注")

    if not books_payload:
        print("没有需要同步的数据")
        return

    # 6. Dry run 或实际推送
    if args.dry_run:
        print("\n--- Dry Run 数据 ---")
        for b in books_payload:
            ann_count = len(b["annotations"])
            progress_pct = b["reading_progress"]
            finished = " [已读完]" if b["is_finished"] else ""
            print(f"  [{b['asset_id']:>12}] {b['title']} — {b['author']} — {ann_count} 条标注 — 进度 {progress_pct:.0%}{finished}")
            for ann in b["annotations"][:3]:  # 最多展示 3 条
                text = (ann["selected_text"] or "")[:60]
                note_tag = " [想法]" if ann["type"] == "note" else ""
                print(f"    • {text}...{note_tag}")
            if ann_count > 3:
                print(f"    ... 还有 {ann_count - 3} 条")
        return

    print("正在推送到 Allin-One...")
    result = sync_books(api_url, args.api_key, source_id, books_payload)
    print("  同步完成:")
    print(f"    新增书籍: {result.get('new_books', 0)}")
    print(f"    更新书籍: {result.get('updated_books', 0)}")
    print(f"    新增标注: {result.get('new_annotations', 0)}")
    print(f"    更新标注: {result.get('updated_annotations', 0)}")
    print(f"    删除标注: {result.get('deleted_annotations', 0)}")


if __name__ == "__main__":
    main()
