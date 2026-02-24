"""Google Books API 在线元数据搜索服务"""

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

GOOGLE_BOOKS_API = "https://www.googleapis.com/books/v1/volumes"


@dataclass
class BookMetadataResult:
    title: str = ""
    author: str = ""
    isbn_10: str = ""
    isbn_13: str = ""
    publisher: str = ""
    publish_date: str = ""
    language: str = ""
    page_count: int = 0
    subjects: list[str] = field(default_factory=list)
    description: str = ""
    cover_url: str = ""


def _parse_volume(item: dict) -> BookMetadataResult:
    """解析 Google Books API 单条 volumeInfo"""
    info = item.get("volumeInfo", {})

    isbn_10 = ""
    isbn_13 = ""
    for ident in info.get("industryIdentifiers", []):
        if ident.get("type") == "ISBN_10":
            isbn_10 = ident.get("identifier", "")
        elif ident.get("type") == "ISBN_13":
            isbn_13 = ident.get("identifier", "")

    cover_url = ""
    image_links = info.get("imageLinks", {})
    cover_url = image_links.get("thumbnail", image_links.get("smallThumbnail", ""))

    return BookMetadataResult(
        title=info.get("title", ""),
        author=", ".join(info.get("authors", [])),
        isbn_10=isbn_10,
        isbn_13=isbn_13,
        publisher=info.get("publisher", ""),
        publish_date=info.get("publishedDate", ""),
        language=info.get("language", ""),
        page_count=info.get("pageCount", 0) or 0,
        subjects=info.get("categories", []),
        description=info.get("description", ""),
        cover_url=cover_url,
    )


async def search_google_books(query: str, max_results: int = 5) -> list[BookMetadataResult]:
    """调用 Google Books API 搜索书籍元数据"""
    if not query.strip():
        return []

    params = {
        "q": query,
        "maxResults": min(max_results, 10),
        "printType": "books",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(GOOGLE_BOOKS_API, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.warning(f"Google Books API error: {e}")
        return []

    items = data.get("items", [])
    return [_parse_volume(item) for item in items]
