#!/usr/bin/env python3
"""B站视频同步脚本 — 收藏夹 / 历史记录 / 动态 → Allin-One 视频同步 API

依赖: pip install httpx

用法:
  # 收藏夹全量导入（自动翻页）
  python scripts/bilibili-sync.py \
    --api-url http://localhost:8000 \
    --cookie "SESSDATA=xxx; bili_jct=xxx" \
    --type favorites --media-id 12345

  # 观看历史
  python scripts/bilibili-sync.py --api-url ... --cookie ... --type history

  # 关注动态
  python scripts/bilibili-sync.py --api-url ... --cookie ... --type dynamic

  # 增量（默认）/ 全量 / 预览
  --full       # 跳过增量过滤，同步全部
  --dry-run    # 仅打印，不写入
  --max-items  # 限制条目数（默认无限制）
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import httpx

# ─── B站 API 端点 ─────────────────────────────────────────────────────────────

_API_DYNAMIC = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all"
_API_FAVORITES = "https://api.bilibili.com/x/v3/fav/resource/list"
_API_HISTORY = "https://api.bilibili.com/x/web-interface/history/cursor"

_HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com/",
}

_PAGE_SIZE = 20
_REQUEST_INTERVAL = 0.5  # 请求间隔（秒），避免被限流


# ─── B站 API 数据获取 ─────────────────────────────────────────────────────────

def _make_headers(cookie: str) -> dict:
    return {**_HEADERS_BASE, "Cookie": cookie}


def fetch_favorites(cookie: str, media_id: str, max_items: int | None = None) -> list[dict]:
    """获取收藏夹全部内容（自动翻页）"""
    headers = _make_headers(cookie)
    videos = []
    page = 1

    with httpx.Client(timeout=30, headers=headers) as client:
        while True:
            resp = client.get(_API_FAVORITES, params={
                "media_id": media_id,
                "ps": _PAGE_SIZE,
                "pn": page,
                "order": "mtime",
            })
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                print(f"[ERROR] B站 API 错误: {data.get('message')}", file=sys.stderr)
                break

            page_data = data.get("data", {})
            medias = page_data.get("medias") or []
            if not medias:
                break

            for m in medias:
                bvid = m.get("bvid", "")
                if not bvid:
                    continue

                videos.append({
                    "bvid": bvid,
                    "title": m.get("title", ""),
                    "author": m.get("upper", {}).get("name"),
                    "url": f"https://www.bilibili.com/video/{bvid}",
                    "duration": m.get("duration"),
                    "cover_url": m.get("cover"),
                    "published_at": _epoch_to_iso(m.get("pubtime") or m.get("ctime")),
                    "is_favorited": True,
                    "extra": {
                        "fav_time": m.get("fav_time"),
                        "play": m.get("cnt_info", {}).get("play"),
                        "danmaku": m.get("cnt_info", {}).get("danmaku"),
                        "collect": m.get("cnt_info", {}).get("collect"),
                    },
                })

                if max_items and len(videos) >= max_items:
                    return videos

            has_more = page_data.get("has_more", False)
            if not has_more:
                break

            page += 1
            print(f"  翻页: 第 {page} 页 (已获取 {len(videos)} 条)")
            time.sleep(_REQUEST_INTERVAL)

    return videos


def fetch_history(cookie: str, max_items: int | None = None) -> list[dict]:
    """获取观看历史（自动翻页，通过 cursor）"""
    headers = _make_headers(cookie)
    videos = []
    cursor_max = 0
    cursor_view_at = 0

    with httpx.Client(timeout=30, headers=headers) as client:
        while True:
            params = {"ps": _PAGE_SIZE, "type": "archive"}
            if cursor_max > 0:
                params["max"] = cursor_max
                params["view_at"] = cursor_view_at

            resp = client.get(_API_HISTORY, params=params)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                print(f"[ERROR] B站 API 错误: {data.get('message')}", file=sys.stderr)
                break

            page_data = data.get("data", {})
            items = page_data.get("list") or []
            if not items:
                break

            for item in items:
                bvid = item.get("history", {}).get("bvid", "") or item.get("bvid", "")
                if not bvid:
                    continue

                videos.append({
                    "bvid": bvid,
                    "title": item.get("title", ""),
                    "author": item.get("author_name"),
                    "url": f"https://www.bilibili.com/video/{bvid}",
                    "duration": item.get("duration"),
                    "cover_url": item.get("cover"),
                    "published_at": _epoch_to_iso(item.get("view_at")),
                    "playback_position": item.get("progress", 0),
                    "extra": {
                        "view_at": item.get("view_at"),
                        "tag_name": item.get("tag_name"),
                    },
                })

                if max_items and len(videos) >= max_items:
                    return videos

            cursor = page_data.get("cursor", {})
            cursor_max = cursor.get("max", 0)
            cursor_view_at = cursor.get("view_at", 0)
            if cursor_max == 0:
                break

            print(f"  翻页: 已获取 {len(videos)} 条")
            time.sleep(_REQUEST_INTERVAL)

    return videos


def fetch_dynamic(cookie: str, max_items: int | None = None) -> list[dict]:
    """获取关注动态中的视频"""
    headers = _make_headers(cookie)
    videos = []
    offset = ""

    with httpx.Client(timeout=30, headers=headers) as client:
        while True:
            params = {"type": "video"}
            if offset:
                params["offset"] = offset

            resp = client.get(_API_DYNAMIC, params=params)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                print(f"[ERROR] B站 API 错误: {data.get('message')}", file=sys.stderr)
                break

            page_data = data.get("data", {})
            items = page_data.get("items") or []
            if not items:
                break

            for item in items:
                modules = item.get("modules", {})
                dynamic = modules.get("module_dynamic", {})
                major = dynamic.get("major") or {}
                author_info = modules.get("module_author", {})

                if major.get("type") != "MAJOR_TYPE_ARCHIVE":
                    continue

                archive = major.get("archive", {})
                bvid = archive.get("bvid", "")
                if not bvid:
                    continue

                # 解析时长字符串 "MM:SS" 或 "HH:MM:SS"
                duration_str = archive.get("duration_text", "")
                duration = _parse_duration(duration_str)

                videos.append({
                    "bvid": bvid,
                    "title": archive.get("title", ""),
                    "author": author_info.get("name"),
                    "url": f"https://www.bilibili.com/video/{bvid}",
                    "duration": duration,
                    "cover_url": archive.get("cover"),
                    "published_at": _epoch_to_iso(author_info.get("pub_ts")),
                    "extra": {
                        "play": archive.get("stat", {}).get("play"),
                        "danmaku": archive.get("stat", {}).get("danmaku"),
                        "desc": archive.get("desc"),
                    },
                })

                if max_items and len(videos) >= max_items:
                    return videos

            offset = page_data.get("offset", "")
            has_more = page_data.get("has_more", False)
            if not has_more or not offset:
                break

            print(f"  翻页: 已获取 {len(videos)} 条")
            time.sleep(_REQUEST_INTERVAL)

    return videos


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _epoch_to_iso(ts) -> str | None:
    """Unix 时间戳 → ISO 格式字符串"""
    if not ts or ts == 0:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


def _parse_duration(s: str) -> int | None:
    """解析 B站时长字符串，如 '12:34' → 754, '1:02:03' → 3723"""
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        return None
    return None


# ─── Allin-One API 交互 ──────────────────────────────────────────────────────

def setup_source(api_url: str, api_key: str | None = None) -> str:
    """POST /api/video/sync/setup → 返回 source_id"""
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    with httpx.Client(timeout=10, headers=headers) as client:
        resp = client.post(
            f"{api_url}/api/video/sync/setup",
            params={"source_type": "sync.bilibili"},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            print(f"[ERROR] Setup 失败: {data.get('message')}", file=sys.stderr)
            sys.exit(1)
        source_id = data["data"]["source_id"]
        print(f"[OK] source_id = {source_id} ({data.get('message')})")
        return source_id


def get_sync_status(api_url: str, source_id: str, api_key: str | None = None) -> dict:
    """GET /api/video/sync/status → 返回同步状态"""
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    with httpx.Client(timeout=10, headers=headers) as client:
        resp = client.get(
            f"{api_url}/api/video/sync/status",
            params={"source_id": source_id},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {})


def push_videos(api_url: str, source_id: str, videos: list[dict], api_key: str | None = None) -> dict:
    """POST /api/video/sync → 推送视频数据"""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    payload = {
        "source_id": source_id,
        "videos": videos,
    }

    with httpx.Client(timeout=60, headers=headers) as client:
        resp = client.post(
            f"{api_url}/api/video/sync",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            print(f"[ERROR] 同步失败: {data.get('message')}", file=sys.stderr)
            sys.exit(1)
        return data.get("data", {})


# ─── 增量过滤 ─────────────────────────────────────────────────────────────────

def filter_incremental(videos: list[dict], last_sync_at: str | None) -> list[dict]:
    """过滤出 last_sync_at 之后的视频"""
    if not last_sync_at:
        return videos

    try:
        cutoff = datetime.fromisoformat(last_sync_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return videos

    filtered = []
    for v in videos:
        pub = v.get("published_at")
        if not pub:
            filtered.append(v)
            continue
        try:
            pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            if pub_dt > cutoff:
                filtered.append(v)
        except (ValueError, AttributeError):
            filtered.append(v)

    return filtered


# ─── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="B站视频同步到 Allin-One")
    parser.add_argument("--api-url", required=True, help="Allin-One API 地址 (如 http://localhost:8000)")
    parser.add_argument("--api-key", default=None, help="API Key (如果启用了认证)")
    parser.add_argument("--cookie", required=True, help="B站 Cookie (SESSDATA=xxx; bili_jct=xxx)")
    parser.add_argument("--type", choices=["favorites", "history", "dynamic"], default="favorites", help="采集类型")
    parser.add_argument("--media-id", default=None, help="收藏夹 media_id (type=favorites 时必填)")
    parser.add_argument("--full", action="store_true", help="全量同步（跳过增量过滤）")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不写入")
    parser.add_argument("--max-items", type=int, default=None, help="最大条目数")
    parser.add_argument("--batch-size", type=int, default=50, help="每批推送数量")

    args = parser.parse_args()

    if args.type == "favorites" and not args.media_id:
        print("[ERROR] --media-id 是收藏夹模式的必填参数", file=sys.stderr)
        sys.exit(1)

    # 1. Setup source
    type_labels = {"favorites": "收藏夹", "history": "历史记录", "dynamic": "动态"}
    print(f"\n=== B站{type_labels[args.type]}同步 ===\n")
    source_id = setup_source(args.api_url, args.api_key)

    # 2. Get sync status (for incremental)
    status = get_sync_status(args.api_url, source_id, args.api_key)
    last_sync_at = status.get("last_sync_at")
    total_existing = status.get("total_videos", 0)
    print(f"[INFO] 已有 {total_existing} 条视频, 上次同步: {last_sync_at or '从未'}")

    # 3. Fetch from B站
    print(f"\n[FETCH] 开始获取B站数据 (type={args.type})...")
    if args.type == "favorites":
        videos = fetch_favorites(args.cookie, args.media_id, args.max_items)
    elif args.type == "history":
        videos = fetch_history(args.cookie, args.max_items)
    elif args.type == "dynamic":
        videos = fetch_dynamic(args.cookie, args.max_items)
    else:
        videos = []

    print(f"[FETCH] 获取到 {len(videos)} 条视频")

    if not videos:
        print("[DONE] 没有新数据")
        return

    # 4. Incremental filter
    if not args.full and last_sync_at:
        original_count = len(videos)
        videos = filter_incremental(videos, last_sync_at)
        print(f"[FILTER] 增量过滤: {original_count} → {len(videos)} 条")

    if not videos:
        print("[DONE] 没有新数据需要同步")
        return

    # 5. Dry run
    if args.dry_run:
        print(f"\n[DRY-RUN] 以下 {len(videos)} 条视频将被同步:\n")
        for i, v in enumerate(videos[:20], 1):
            print(f"  {i}. [{v['bvid']}] {v['title']}")
            if v.get("author"):
                print(f"     作者: {v['author']}")
        if len(videos) > 20:
            print(f"  ... 共 {len(videos)} 条")
        return

    # 6. Push in batches
    total_new = 0
    total_updated = 0

    for i in range(0, len(videos), args.batch_size):
        batch = videos[i:i + args.batch_size]
        batch_num = i // args.batch_size + 1
        print(f"\n[SYNC] 推送第 {batch_num} 批 ({len(batch)} 条)...")

        result = push_videos(args.api_url, source_id, batch, args.api_key)
        new = result.get("new_videos", 0)
        updated = result.get("updated_videos", 0)
        total_new += new
        total_updated += updated
        print(f"  → 新增 {new}, 更新 {updated}")

        if i + args.batch_size < len(videos):
            time.sleep(0.2)

    print(f"\n[DONE] 同步完成: 新增 {total_new}, 更新 {total_updated}")


if __name__ == "__main__":
    main()
