"""媒体类型检测 — 供 collector 和 localize_media 共用

检测来源:
1. URL 模式匹配 (bilibili/youtube/b23.tv)
2. RSS enclosures (type 字段)
3. RSS media:content (medium/type 字段)
"""

import re
from dataclasses import dataclass

VIDEO_URL_PATTERNS = [
    r'bilibili\.com/video/',
    r'youtube\.com/watch',
    r'youtu\.be/',
    r'b23\.tv/',
]

_VIDEO_URL_RE = re.compile('|'.join(VIDEO_URL_PATTERNS))


@dataclass
class DetectedMedia:
    media_type: str         # "video" / "image" / "audio"
    original_url: str
    detection_source: str   # "url_pattern" / "enclosure" / "media_content"


def url_matches_video_pattern(url: str) -> bool:
    """URL 是否匹配已知视频平台模式"""
    return bool(url and _VIDEO_URL_RE.search(url))


def detect_media_from_url(url: str) -> list[DetectedMedia]:
    """通过 URL 模式匹配检测视频"""
    if url_matches_video_pattern(url):
        return [DetectedMedia(media_type="video", original_url=url, detection_source="url_pattern")]
    return []


def detect_media_from_raw_data(raw_dict: dict) -> list[DetectedMedia]:
    """从 RSS raw_data 的 enclosures 和 media_content 检测媒体"""
    results: list[DetectedMedia] = []
    seen_urls: set[str] = set()

    # enclosures: [{"href": "...", "type": "video/mp4", ...}]
    for enc in raw_dict.get("enclosures") or []:
        href = enc.get("href")
        if not href or href in seen_urls:
            continue
        enc_type = (enc.get("type") or "").lower()
        if enc_type.startswith("video/"):
            results.append(DetectedMedia(media_type="video", original_url=href, detection_source="enclosure"))
            seen_urls.add(href)
        elif enc_type.startswith("audio/"):
            results.append(DetectedMedia(media_type="audio", original_url=href, detection_source="enclosure"))
            seen_urls.add(href)

    # media_content: [{"url": "...", "medium": "video", "type": "video/mp4"}]
    for mc in raw_dict.get("media_content") or []:
        mc_url = mc.get("url")
        if not mc_url or mc_url in seen_urls:
            continue
        medium = (mc.get("medium") or "").lower()
        mc_type = (mc.get("type") or "").lower()
        if medium == "video" or mc_type.startswith("video/"):
            results.append(DetectedMedia(media_type="video", original_url=mc_url, detection_source="media_content"))
            seen_urls.add(mc_url)
        elif medium == "audio" or mc_type.startswith("audio/"):
            results.append(DetectedMedia(media_type="audio", original_url=mc_url, detection_source="media_content"))
            seen_urls.add(mc_url)

    return results


def detect_media_for_content(url: str | None, raw_dict: dict | None) -> list[DetectedMedia]:
    """合并 URL 模式 + raw_data 检测，去重"""
    results: list[DetectedMedia] = []
    seen_urls: set[str] = set()

    if url:
        for det in detect_media_from_url(url):
            if det.original_url not in seen_urls:
                results.append(det)
                seen_urls.add(det.original_url)

    if raw_dict:
        for det in detect_media_from_raw_data(raw_dict):
            if det.original_url not in seen_urls:
                results.append(det)
                seen_urls.add(det.original_url)

    return results
