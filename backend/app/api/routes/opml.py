"""OPML 导入/导出路由 — 从 sources.py 提取"""

import json
import logging
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.time import utcnow
from app.models.content import SourceConfig, SourceType
from app.schemas import error_response

logger = logging.getLogger(__name__)
router = APIRouter()

_RSS_TYPES = {"rss.standard", "rss.hub"}


def _resolve_rss_feed_url(source_type: str, url: str | None, config: dict) -> str:
    """临时构造 SourceConfig 对象调用共享工具"""
    from app.services.collectors.utils import resolve_rss_feed_url
    temp_source = SourceConfig(
        id="temp",
        name="temp",
        source_type=source_type,
        url=url,
        config_json=json.dumps(config) if config else None
    )
    return resolve_rss_feed_url(temp_source, settings.RSSHUB_URL)


@router.post("/import")
async def import_opml(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """导入 OPML 文件批量创建 RSS 源"""
    try:
        # 读取文件内容
        content = await file.read()
        xml_text = content.decode("utf-8")

        # 解析 OPML XML
        root = ET.fromstring(xml_text)

        # OPML 格式: <opml><body><outline ... /></body></opml>
        outlines = root.findall(".//outline[@type='rss']") or root.findall(".//outline[@xmlUrl]")

        if not outlines:
            return error_response(400, "未找到有效的 RSS 订阅源")

        created = 0
        skipped = 0
        errors = []

        for outline in outlines:
            try:
                # 提取属性
                title = outline.get("title") or outline.get("text", "Untitled")
                xml_url = outline.get("xmlUrl")
                html_url = outline.get("htmlUrl")
                description = outline.get("description", "")

                if not xml_url:
                    skipped += 1
                    continue

                # 检查是否已存在
                existing = db.query(SourceConfig).filter(SourceConfig.url == xml_url).first()
                if existing:
                    skipped += 1
                    continue

                # 创建数据源
                source = SourceConfig(
                    name=title[:200],
                    source_type=SourceType.RSS_STANDARD.value,
                    url=xml_url,
                    description=description[:500] if description else None,
                    schedule_enabled=True,
                    schedule_mode="auto",  # 智能调度
                    is_active=True,
                )
                db.add(source)
                created += 1

            except Exception as e:
                errors.append(f"{title}: {str(e)}")
                continue

        db.commit()

        logger.info(f"OPML imported: created={created}, skipped={skipped}, errors={len(errors)}")
        return {
            "code": 0,
            "data": {
                "created": created,
                "skipped": skipped,
                "errors": errors,
            },
            "message": f"导入完成: 新增 {created} 个源，跳过 {skipped} 个",
        }

    except ET.ParseError as e:
        return error_response(400, f"OPML 解析失败: {str(e)}")
    except Exception as e:
        return error_response(500, f"导入失败: {str(e)}")


@router.get("/export")
async def export_opml(
    db: Session = Depends(get_db),
):
    """导出 RSS 源为 OPML 文件"""
    sources = db.query(SourceConfig).filter(
        SourceConfig.source_type.in_([
            SourceType.RSS_HUB.value,
            SourceType.RSS_STANDARD.value,
        ])
    ).all()

    # 构建 OPML XML
    opml = ET.Element("opml", version="2.0")

    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = "Allin-One RSS Subscriptions"
    ET.SubElement(head, "dateCreated").text = utcnow().isoformat()

    body = ET.SubElement(opml, "body")

    for source in sources:
        # 解析实际的 Feed URL（而非直接用 source.url）
        try:
            if source.source_type in _RSS_TYPES:
                config = json.loads(source.config_json) if source.config_json else {}
                xml_url = _resolve_rss_feed_url(source.source_type, source.url, config)
            else:
                xml_url = source.url or ""
        except ValueError:
            xml_url = ""  # 配置错误的源，导出空 URL

        outline = ET.SubElement(
            body,
            "outline",
            type="rss",
            text=source.name,
            title=source.name,
            xmlUrl=xml_url,
        )
        if source.description:
            outline.set("description", source.description)

    # 转为 XML 字符串
    xml_string = ET.tostring(opml, encoding="utf-8", method="xml")
    xml_declaration = b'<?xml version="1.0" encoding="UTF-8"?>\n'
    opml_content = xml_declaration + xml_string

    return Response(
        content=opml_content,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="allin-one-feeds-{utcnow().strftime("%Y%m%d")}.opml"'
        },
    )
