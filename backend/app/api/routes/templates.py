"""Templates API - 流水线模板管理"""

import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.pipeline import PipelineTemplate
from app.schemas import PipelineTemplateResponse, PipelineTemplateCreate, PipelineTemplateUpdate, error_response
from app.services.pipeline.registry import STEP_DEFINITIONS

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def list_templates(db: Session = Depends(get_db)):
    """获取所有活跃模板列表（供下拉选择）"""
    templates = db.query(PipelineTemplate).filter(PipelineTemplate.is_active == True).all()
    return {
        "code": 0,
        "data": [PipelineTemplateResponse.model_validate(t).model_dump() for t in templates],
        "message": "ok",
    }


@router.get("/step-definitions")
async def get_step_definitions():
    """获取所有步骤类型定义（供前端可视化编辑器使用）"""
    result = {}
    for key, defn in STEP_DEFINITIONS.items():
        result[key] = {
            "step_type": defn.step_type,
            "display_name": defn.display_name,
            "description": defn.description,
            "is_critical_default": defn.is_critical_default,
            "config_schema": defn.config_schema,
        }
    return {"code": 0, "data": result, "message": "ok"}


@router.get("/{template_id}")
async def get_template(template_id: str, db: Session = Depends(get_db)):
    """获取单个模板详情"""
    tpl = db.get(PipelineTemplate, template_id)
    if not tpl:
        return error_response(404, "Template not found")
    return {"code": 0, "data": PipelineTemplateResponse.model_validate(tpl).model_dump(), "message": "ok"}


@router.post("")
async def create_template(body: PipelineTemplateCreate, db: Session = Depends(get_db)):
    """创建流水线模板"""
    # 校验 steps_config 是合法 JSON
    try:
        steps = json.loads(body.steps_config)
        if not isinstance(steps, list):
            return error_response(400, "steps_config must be a JSON array")
    except json.JSONDecodeError:
        return error_response(400, "steps_config is not valid JSON")

    # 检查名称是否重复
    existing = db.query(PipelineTemplate).filter(PipelineTemplate.name == body.name).first()
    if existing:
        return error_response(400, f"Template name '{body.name}' already exists")

    tpl = PipelineTemplate(
        name=body.name,
        description=body.description,
        steps_config=body.steps_config,
        is_builtin=False,
        is_active=body.is_active,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)

    logger.info(f"Pipeline template created: {tpl.id} ({tpl.name})")
    return {"code": 0, "data": PipelineTemplateResponse.model_validate(tpl).model_dump(), "message": "ok"}


@router.put("/{template_id}")
async def update_template(template_id: str, body: PipelineTemplateUpdate, db: Session = Depends(get_db)):
    """更新流水线模板"""
    tpl = db.get(PipelineTemplate, template_id)
    if not tpl:
        return error_response(404, "Template not found")

    if tpl.is_builtin:
        # 内置模板只允许修改 is_active
        update_data = body.model_dump(exclude_unset=True)
        allowed = {"is_active"}
        if set(update_data.keys()) - allowed:
            return error_response(400, "内置模板只能修改启用状态")

    update_data = body.model_dump(exclude_unset=True)

    # 校验 steps_config
    if "steps_config" in update_data:
        try:
            steps = json.loads(update_data["steps_config"])
            if not isinstance(steps, list):
                return error_response(400, "steps_config must be a JSON array")
        except json.JSONDecodeError:
            return error_response(400, "steps_config is not valid JSON")

    for key, value in update_data.items():
        setattr(tpl, key, value)

    tpl.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(tpl)

    return {"code": 0, "data": PipelineTemplateResponse.model_validate(tpl).model_dump(), "message": "ok"}


@router.delete("/{template_id}")
async def delete_template(template_id: str, db: Session = Depends(get_db)):
    """删除流水线模板（内置不可删）"""
    tpl = db.get(PipelineTemplate, template_id)
    if not tpl:
        return error_response(404, "Template not found")

    if tpl.is_builtin:
        return error_response(400, "内置模板不可删除")

    db.delete(tpl)
    db.commit()

    logger.info(f"Pipeline template deleted: {template_id}")
    return {"code": 0, "data": None, "message": "ok"}
