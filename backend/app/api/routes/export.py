"""JSON 全量数据源导出/导入

支持所有类型数据源（非仅 RSS），用于系统备份与迁移。
去重策略：有 url 的源按 source_type+url，无 url 的按 source_type+name。
"""

import json
import logging

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import utcnow
from app.models.content import SourceConfig
from app.schemas import error_response

logger = logging.getLogger(__name__)
router = APIRouter()

# 导出的用户配置字段（不含运行时状态字段）
_EXPORT_FIELDS = [
    "name", "source_type", "url", "description",
    "schedule_enabled", "schedule_mode", "schedule_interval_override",
    "pipeline_template_id", "config_json", "credential_id",
    "auto_cleanup_enabled", "retention_days", "is_active",
]


def _source_to_dict(source: SourceConfig) -> dict:
    return {field: getattr(source, field) for field in _EXPORT_FIELDS}


@router.get("/export/full")
async def export_full(db: Session = Depends(get_db)):
    """导出所有类型数据源为 JSON 备份文件"""
    sources = db.query(SourceConfig).order_by(SourceConfig.created_at).all()

    data = {
        "version": "1.0",
        "exported_at": utcnow().isoformat(),
        "total": len(sources),
        "sources": [_source_to_dict(s) for s in sources],
    }

    content = json.dumps(data, ensure_ascii=False, indent=2)
    filename = f'allin-one-sources-{utcnow().strftime("%Y%m%d")}.json'

    return Response(
        content=content.encode("utf-8"),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@router.post("/import/full")
async def import_full(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """从 JSON 备份文件导入数据源（自动跳过已存在的源）"""
    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))

        if not isinstance(data, dict) or "sources" not in data:
            return error_response(400, "无效的备份文件格式：缺少 sources 字段")

        sources_data = data["sources"]
        if not isinstance(sources_data, list):
            return error_response(400, "无效的备份文件格式：sources 必须是数组")

        # 预检所有引用的 pipeline_template_id，一次查询
        from app.models.pipeline import PipelineTemplate
        template_ids = {
            item.get("pipeline_template_id")
            for item in sources_data
            if item.get("pipeline_template_id")
        }
        existing_templates: set[str] = set()
        if template_ids:
            rows = db.query(PipelineTemplate.id).filter(
                PipelineTemplate.id.in_(template_ids)
            ).all()
            existing_templates = {r[0] for r in rows}

        created = 0
        skipped = 0
        warnings: list[str] = []
        errors: list[str] = []

        for item in sources_data:
            name = item.get("name", "")
            try:
                source_type = item.get("source_type")
                url = item.get("url")

                if not source_type:
                    errors.append(f"跳过无效条目：缺少 source_type (name={name})")
                    continue

                # 去重检查
                if url:
                    existing = db.query(SourceConfig).filter(
                        SourceConfig.source_type == source_type,
                        SourceConfig.url == url,
                    ).first()
                else:
                    existing = db.query(SourceConfig).filter(
                        SourceConfig.source_type == source_type,
                        SourceConfig.name == name,
                    ).first()

                if existing:
                    skipped += 1
                    continue

                # 验证 pipeline_template_id
                pipeline_template_id = item.get("pipeline_template_id")
                if pipeline_template_id and pipeline_template_id not in existing_templates:
                    warnings.append(
                        f"流水线模板 {pipeline_template_id} 不存在，已置为空 (source: {name})"
                    )
                    pipeline_template_id = None

                source = SourceConfig(
                    name=(name or "")[:200],
                    source_type=source_type,
                    url=url,
                    description=item.get("description"),
                    schedule_enabled=item.get("schedule_enabled", True),
                    schedule_mode=item.get("schedule_mode", "auto"),
                    schedule_interval_override=item.get("schedule_interval_override"),
                    pipeline_template_id=pipeline_template_id,
                    config_json=item.get("config_json"),
                    credential_id=item.get("credential_id"),
                    auto_cleanup_enabled=item.get("auto_cleanup_enabled", False),
                    retention_days=item.get("retention_days"),
                    is_active=item.get("is_active", True),
                )
                db.add(source)
                created += 1

            except Exception as e:
                errors.append(f"{name}: {str(e)}")
                continue

        db.commit()

        logger.info(
            f"JSON import: created={created}, skipped={skipped}, "
            f"warnings={len(warnings)}, errors={len(errors)}"
        )
        return {
            "code": 0,
            "data": {
                "created": created,
                "skipped": skipped,
                "warnings": warnings,
                "errors": errors,
            },
            "message": f"导入完成：新增 {created} 个源，跳过 {skipped} 个重复",
        }

    except json.JSONDecodeError as e:
        return error_response(400, f"JSON 解析失败: {str(e)}")
    except Exception as e:
        logger.exception("JSON import failed")
        return error_response(500, f"导入失败: {str(e)}")
