"""Templates API - 流水线模板管理"""

import json
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import utcnow
from app.models.content import SourceConfig
from app.models.pipeline import PipelineTemplate, PipelineExecution
from app.schemas import PipelineTemplateResponse, PipelineTemplateCreate, PipelineTemplateUpdate, error_response
from app.services.pipeline.registry import STEP_DEFINITIONS

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
def list_templates(db: Session = Depends(get_db)):
    """获取所有活跃模板列表（供下拉选择）"""
    templates = db.query(PipelineTemplate).filter(PipelineTemplate.is_active == True).all()
    return {
        "code": 0,
        "data": [PipelineTemplateResponse.model_validate(t).model_dump() for t in templates],
        "message": "ok",
    }


@router.get("/step-definitions")
def get_step_definitions():
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
def get_template(template_id: str, db: Session = Depends(get_db)):
    """获取单个模板详情"""
    tpl = db.get(PipelineTemplate, template_id)
    if not tpl:
        return error_response(404, "Template not found")
    return {"code": 0, "data": PipelineTemplateResponse.model_validate(tpl).model_dump(), "message": "ok"}


@router.post("")
def create_template(body: PipelineTemplateCreate, db: Session = Depends(get_db)):
    """创建流水线模板"""
    # 校验 steps_config 是合法 JSON 数组（兼容前端传 JSON 字符串或 list）
    if isinstance(body.steps_config, list):
        steps = body.steps_config
    else:
        try:
            steps = json.loads(body.steps_config)
        except (json.JSONDecodeError, TypeError):
            return error_response(400, "steps_config is not valid JSON")
    if not isinstance(steps, list):
        return error_response(400, "steps_config must be a JSON array")

    # 检查名称是否重复
    existing = db.query(PipelineTemplate).filter(PipelineTemplate.name == body.name).first()
    if existing:
        return error_response(400, f"Template name '{body.name}' already exists")

    tpl = PipelineTemplate(
        name=body.name,
        description=body.description,
        steps_config=steps,
        is_builtin=False,
        is_active=body.is_active,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)

    logger.info(f"Pipeline template created: {tpl.id} ({tpl.name})")
    return {"code": 0, "data": PipelineTemplateResponse.model_validate(tpl).model_dump(), "message": "ok"}


@router.put("/{template_id}")
def update_template(template_id: str, body: PipelineTemplateUpdate, db: Session = Depends(get_db)):
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

    # 校验 steps_config（兼容前端传 JSON 字符串或 list）
    if "steps_config" in update_data:
        raw = update_data["steps_config"]
        if isinstance(raw, list):
            steps = raw
        else:
            try:
                steps = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return error_response(400, "steps_config is not valid JSON")
        if not isinstance(steps, list):
            return error_response(400, "steps_config must be a JSON array")
        update_data["steps_config"] = steps

    for key, value in update_data.items():
        setattr(tpl, key, value)

    tpl.updated_at = utcnow()
    db.commit()
    db.refresh(tpl)

    return {"code": 0, "data": PipelineTemplateResponse.model_validate(tpl).model_dump(), "message": "ok"}


@router.delete("/{template_id}")
def delete_template(template_id: str, db: Session = Depends(get_db)):
    """删除流水线模板（内置不可删）"""
    tpl = db.get(PipelineTemplate, template_id)
    if not tpl:
        return error_response(404, "Template not found")

    if tpl.is_builtin:
        return error_response(400, "内置模板不可删除")

    # 清除引用该模板的数据源绑定
    db.query(SourceConfig).filter(
        SourceConfig.pipeline_template_id == template_id,
    ).update({"pipeline_template_id": None})

    # 清除引用该模板的执行记录 FK（历史记录保留，仅解除 FK）
    db.query(PipelineExecution).filter(
        PipelineExecution.template_id == template_id,
    ).update({"template_id": None})

    db.delete(tpl)
    db.commit()

    logger.info(f"Pipeline template deleted: {template_id}")
    return {"code": 0, "data": None, "message": "ok"}
