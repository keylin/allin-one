"""电子书元数据解析服务

支持 EPUB (ebooklib) 和 MOBI (mobi 库) 格式。
提取: 标题、作者、语言、出版商、描述、封面图、目录。
"""

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TocItem:
    title: str
    href: str | None = None
    children: list["TocItem"] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {"title": self.title}
        if self.href:
            d["href"] = self.href
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


@dataclass
class EbookMetadata:
    title: str = "未知书名"
    author: str | None = None
    language: str | None = None
    publisher: str | None = None
    description: str | None = None
    cover_data: bytes | None = None
    cover_ext: str | None = None  # jpg / png
    toc: list[TocItem] = field(default_factory=list)

    def toc_to_list(self) -> list[dict]:
        return [item.to_dict() for item in self.toc]


def parse_epub(file_path: str) -> EbookMetadata:
    """使用 ebooklib 解析 EPUB 元数据"""
    from ebooklib import epub

    book = epub.read_epub(file_path, options={"ignore_ncx": False})
    meta = EbookMetadata()

    # 标题
    titles = book.get_metadata("DC", "title")
    if titles:
        meta.title = titles[0][0]

    # 作者
    creators = book.get_metadata("DC", "creator")
    if creators:
        meta.author = creators[0][0]

    # 语言
    langs = book.get_metadata("DC", "language")
    if langs:
        meta.language = langs[0][0]

    # 出版商
    publishers = book.get_metadata("DC", "publisher")
    if publishers:
        meta.publisher = publishers[0][0]

    # 描述
    descriptions = book.get_metadata("DC", "description")
    if descriptions:
        meta.description = descriptions[0][0]

    # 封面图
    cover_data, cover_ext = _extract_epub_cover(book)
    meta.cover_data = cover_data
    meta.cover_ext = cover_ext

    # 目录
    meta.toc = _parse_epub_toc(book.toc)

    return meta


def _extract_epub_cover(book) -> tuple[bytes | None, str | None]:
    """从 EPUB 中提取封面图"""
    from ebooklib import epub

    # 方法 1: 通过 cover metadata
    cover_id = None
    cover_metas = book.get_metadata("OPF", "cover")
    if cover_metas:
        cover_id = cover_metas[0][1].get("content")

    if cover_id:
        item = book.get_item_with_id(cover_id)
        if item:
            ext = _mime_to_ext(item.media_type)
            return item.get_content(), ext

    # 方法 2: 查找 cover-image 类型的 item
    for item in book.get_items_of_type(epub.EpubImage):
        item_id = getattr(item, "id", "") or ""
        item_name = getattr(item, "file_name", "") or ""
        if "cover" in item_id.lower() or "cover" in item_name.lower():
            ext = _mime_to_ext(item.media_type)
            return item.get_content(), ext

    # 方法 3: 取第一张图片
    images = list(book.get_items_of_type(epub.EpubImage))
    if images:
        ext = _mime_to_ext(images[0].media_type)
        return images[0].get_content(), ext

    return None, None


def _mime_to_ext(mime_type: str | None) -> str:
    """MIME 类型转文件扩展名"""
    mapping = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/svg+xml": "svg",
    }
    return mapping.get(mime_type or "", "jpg")


def _parse_epub_toc(toc_items) -> list[TocItem]:
    """递归解析 ebooklib 的 TOC 结构"""
    from ebooklib import epub

    result = []
    for item in toc_items:
        if isinstance(item, tuple):
            # (Section, [children])
            section, children = item
            toc_item = TocItem(
                title=section.title if hasattr(section, "title") else str(section),
                href=section.href if hasattr(section, "href") else None,
                children=_parse_epub_toc(children),
            )
            result.append(toc_item)
        elif isinstance(item, epub.Link):
            result.append(TocItem(title=item.title, href=item.href))
        else:
            result.append(TocItem(title=str(item)))
    return result


def parse_mobi(file_path: str) -> EbookMetadata:
    """使用 mobi 库解包 MOBI，提取元数据"""
    import mobi

    meta = EbookMetadata()
    tempdir = None

    try:
        tempdir, extracted_path = mobi.extract(file_path)

        # mobi.extract 可能解出 epub 文件
        if extracted_path and extracted_path.endswith(".epub"):
            return parse_epub(extracted_path)

        # 否则从解包目录中提取基本信息
        # mobi 库解包到 tempdir，包含 mobi7/ 或 mobi8/ 子目录
        meta.title = Path(file_path).stem

        # 尝试从 OPF 文件提取元数据
        for opf_file in Path(tempdir).rglob("*.opf"):
            _parse_opf_metadata(opf_file, meta)
            break

        # 尝试提取封面
        for img in Path(tempdir).rglob("cover.*"):
            if img.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif"):
                meta.cover_data = img.read_bytes()
                meta.cover_ext = img.suffix.lstrip(".").replace("jpeg", "jpg")
                break

    except Exception as e:
        logger.warning(f"MOBI parsing partially failed for {file_path}: {e}")
        meta.title = meta.title or Path(file_path).stem
    finally:
        if tempdir and os.path.isdir(tempdir):
            shutil.rmtree(tempdir, ignore_errors=True)

    return meta


def _parse_opf_metadata(opf_path: Path, meta: EbookMetadata):
    """从 OPF XML 中提取元数据"""
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(opf_path)
        root = tree.getroot()

        ns = {
            "dc": "http://purl.org/dc/elements/1.1/",
            "opf": "http://www.idpf.org/2007/opf",
        }

        title_el = root.find(".//dc:title", ns)
        if title_el is not None and title_el.text:
            meta.title = title_el.text

        creator_el = root.find(".//dc:creator", ns)
        if creator_el is not None and creator_el.text:
            meta.author = creator_el.text

        lang_el = root.find(".//dc:language", ns)
        if lang_el is not None and lang_el.text:
            meta.language = lang_el.text

        publisher_el = root.find(".//dc:publisher", ns)
        if publisher_el is not None and publisher_el.text:
            meta.publisher = publisher_el.text

        desc_el = root.find(".//dc:description", ns)
        if desc_el is not None and desc_el.text:
            meta.description = desc_el.text

    except Exception as e:
        logger.debug(f"OPF parsing failed: {e}")


def parse_ebook(file_path: str) -> EbookMetadata:
    """根据扩展名分发到对应解析器"""
    ext = Path(file_path).suffix.lower()
    if ext == ".epub":
        return parse_epub(file_path)
    elif ext in (".mobi", ".azw", ".azw3"):
        return parse_mobi(file_path)
    else:
        raise ValueError(f"不支持的电子书格式: {ext}")


