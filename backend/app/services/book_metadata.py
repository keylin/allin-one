"""Google Books API 在线元数据搜索服务"""

import logging
import re
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


def _clean_author(author: str) -> str:
    """清洗作者字符串：去国籍标记、角色后缀、规范化中间点、去单字母缩写"""
    # 去掉 [美] / （英） / (日) / 【德】 等国籍标记
    author = re.sub(r"[\[【（(][^)\]】）]{1,4}[\]】）)]", "", author)
    # 去掉末尾的 著/编/译/主编/编著 等角色后缀
    author = re.sub(r"[著编译]+$", "", author.strip())
    # 中间点统一替换为空格
    author = re.sub(r"[·．‧•]", " ", author)
    # 去掉单字母缩写 如 j. / J. / m.
    author = re.sub(r"\b[a-zA-Z]\.\s*", "", author)
    # 合并多余空格
    return re.sub(r"\s+", " ", author).strip()


def _has_cjk(text: str) -> bool:
    """检测文本是否包含中日韩字符"""
    return bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))


def _build_structured_query(
    title: str = "",
    author: str = "",
    isbn: str = "",
) -> str:
    """构建 Google Books 结构化查询（intitle:/inauthor:/isbn:）"""
    # ISBN 最优先
    isbn_clean = re.sub(r"[^0-9Xx]", "", isbn)
    if len(isbn_clean) in (10, 13):
        return f"isbn:{isbn_clean}"

    parts = []
    if title.strip():
        parts.append(f"intitle:{title.strip()}")
    if author.strip():
        cleaned = _clean_author(author)
        if cleaned:
            parts.append(f"inauthor:{cleaned}")
    return " ".join(parts)


async def search_google_books_structured(
    title: str = "",
    author: str = "",
    isbn: str = "",
    max_results: int = 5,
) -> list[BookMetadataResult]:
    """结构化搜索：用 intitle:/inauthor:/isbn: 构建查询后委托给 search_google_books"""
    query = _build_structured_query(title, author, isbn)
    if not query:
        return []
    return await search_google_books(query, max_results=max_results)


async def search_google_books(
    query: str,
    max_results: int = 5,
    lang_restrict: str = "",
) -> list[BookMetadataResult]:
    """调用 Google Books API 搜索书籍元数据"""
    if not query.strip():
        return []

    params: dict = {
        "q": query,
        "maxResults": min(max_results, 10),
        "printType": "books",
    }

    # 自动语言限制：查询含 CJK 字符且未显式指定时，限定中文结果
    effective_lang = lang_restrict
    if not effective_lang and _has_cjk(query):
        effective_lang = "zh"
    if effective_lang:
        params["langRestrict"] = effective_lang

    logger.debug("Google Books search: %s", params)

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
