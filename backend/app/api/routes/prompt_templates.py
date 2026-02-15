"""Prompt Templates API - 提示词模板管理"""

import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import utcnow
from app.models.prompt_template import PromptTemplate, TemplateType
from app.schemas import PromptTemplateCreate, PromptTemplateUpdate, PromptTemplateResponse, error_response

logger = logging.getLogger(__name__)
router = APIRouter()


def _validate_template_type(template_type: str) -> str | None:
    valid = {e.value for e in TemplateType}
    if template_type not in valid:
        return f"Invalid template_type '{template_type}'. Valid: {sorted(valid)}"
    return None


@router.get("")
async def list_prompt_templates(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    template_type: str | None = Query(None),
    q: str | None = Query(None, description="搜索名称"),
    db: Session = Depends(get_db),
):
    """查询提示词模板列表"""
    query = db.query(PromptTemplate)

    if template_type:
        query = query.filter(PromptTemplate.template_type == template_type)
    if q:
        query = query.filter(PromptTemplate.name.ilike(f"%{q}%"))

    total = query.count()
    templates = (
        query.order_by(PromptTemplate.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "code": 0,
        "data": [PromptTemplateResponse.model_validate(t).model_dump() for t in templates],
        "total": total,
        "page": page,
        "page_size": page_size,
        "message": "ok",
    }


@router.get("/{template_id}")
async def get_prompt_template(template_id: str, db: Session = Depends(get_db)):
    """获取单个提示词模板"""
    tpl = db.get(PromptTemplate, template_id)
    if not tpl:
        return error_response(404, "Prompt template not found")
    return {"code": 0, "data": PromptTemplateResponse.model_validate(tpl).model_dump(), "message": "ok"}


@router.post("")
async def create_prompt_template(body: PromptTemplateCreate, db: Session = Depends(get_db)):
    """创建提示词模板"""
    err = _validate_template_type(body.template_type)
    if err:
        return error_response(400, err)

    tpl = PromptTemplate(**body.model_dump())
    db.add(tpl)
    db.commit()
    db.refresh(tpl)

    logger.info(f"Prompt template created: {tpl.id} ({tpl.name}, type={tpl.template_type})")
    return {"code": 0, "data": PromptTemplateResponse.model_validate(tpl).model_dump(), "message": "ok"}


@router.put("/{template_id}")
async def update_prompt_template(template_id: str, body: PromptTemplateUpdate, db: Session = Depends(get_db)):
    """更新提示词模板"""
    tpl = db.get(PromptTemplate, template_id)
    if not tpl:
        return error_response(404, "Prompt template not found")

    update_data = body.model_dump(exclude_unset=True)

    if "template_type" in update_data:
        err = _validate_template_type(update_data["template_type"])
        if err:
            return error_response(400, err)

    for key, value in update_data.items():
        setattr(tpl, key, value)

    tpl.updated_at = utcnow()
    db.commit()
    db.refresh(tpl)

    return {"code": 0, "data": PromptTemplateResponse.model_validate(tpl).model_dump(), "message": "ok"}


@router.delete("/{template_id}")
async def delete_prompt_template(template_id: str, db: Session = Depends(get_db)):
    """删除提示词模板"""
    tpl = db.get(PromptTemplate, template_id)
    if not tpl:
        return error_response(404, "Prompt template not found")

    db.delete(tpl)
    db.commit()

    logger.info(f"Prompt template deleted: {template_id}")
    return {"code": 0, "data": None, "message": "ok"}
