---
name: new-api
description: 引导创建新的 API 端点，包含 Pydantic schema 和标准响应格式
argument-hint: <资源名> (如 sources, content, pipelines, settings)
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# 创建 / 实现 API 端点

你正在为以下资源创建或实现 API 端点: **$ARGUMENTS**

## 开始之前

阅读现有模式和 API 规范:
1. `backend/app/api/routes/sources.py` — 现有路由结构
2. `backend/app/api/routes/content.py` — 查询参数模式
3. `backend/app/main.py` — 路由注册方式
4. `backend/app/core/database.py` — `get_db` 依赖注入
5. `docs/system_design.md` 第 6 节 — 完整 API 规范
6. `backend/app/models/` — 该资源对应的 SQLAlchemy 模型

在 `docs/system_design.md` 中查找该端点是否已定义。以规范文档为权威参考。

## API 设计规则（必须遵守）

- RESTful 风格: 资源名用复数名词 (`/api/sources`, `/api/content`)
- 统一响应: `{"code": 0, "data": <结果>, "message": "ok"}`
- 分页参数: `page`（默认 1）, `page_size`（默认 20, 最大 100）
- 错误响应: 合适的 HTTP 状态码 + `{"code": <业务码>, "data": null, "message": "..."}`
- 异步处理器: 使用 `async def`
- 数据库会话: 通过 `Depends(get_db)` 注入

## 第 1 步: 创建 Pydantic Schema

创建 `backend/app/schemas/$ARGUMENTS.py`:

```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ${Resource}Create(BaseModel):
    """创建请求体"""
    name: str
    # ... 从模型中提取必填字段


class ${Resource}Update(BaseModel):
    """更新请求体 - 所有字段可选"""
    name: Optional[str] = None
    # ... 可选字段


class ${Resource}Response(BaseModel):
    """响应模型"""
    id: str
    name: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True  # ORM 模式
```

如果 `backend/app/schemas/__init__.py` 存在，记得导出。

## 第 2 步: 实现路由 Handler

在 `backend/app/api/routes/$ARGUMENTS.py` 中实现 CRUD 操作:

```python
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db

router = APIRouter()


@router.get("/")
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Model)
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "code": 0,
        "data": [ItemResponse.model_validate(i).model_dump() for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "message": "ok",
    }


@router.get("/{item_id}")
async def get_item(item_id: str, db: Session = Depends(get_db)):
    item = db.query(Model).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="未找到")
    return {"code": 0, "data": ItemResponse.model_validate(item).model_dump(), "message": "ok"}


@router.post("/")
async def create_item(body: ItemCreate, db: Session = Depends(get_db)):
    item = Model(**body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"code": 0, "data": ItemResponse.model_validate(item).model_dump(), "message": "ok"}


@router.put("/{item_id}")
async def update_item(item_id: str, body: ItemUpdate, db: Session = Depends(get_db)):
    item = db.query(Model).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="未找到")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    return {"code": 0, "data": ItemResponse.model_validate(item).model_dump(), "message": "ok"}


@router.delete("/{item_id}")
async def delete_item(item_id: str, db: Session = Depends(get_db)):
    item = db.query(Model).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="未找到")
    db.delete(item)
    db.commit()
    return {"code": 0, "data": None, "message": "ok"}
```

## 第 3 步: 注册路由（如果是新路由）

在 `backend/app/main.py` 中添加:
```python
from app.api.routes import $ARGUMENTS
app.include_router($ARGUMENTS.router, prefix="/api/$ARGUMENTS", tags=["$ARGUMENTS"])
```

## 完整 API 清单（来自 system_design.md）

```
仪表盘:    GET /api/dashboard/stats
数据源:    GET/POST /api/sources, GET/PUT/DELETE /api/sources/{id}
           POST /api/sources/{id}/collect, GET /api/sources/{id}/history
           POST /api/sources/import, GET /api/sources/export
内容:      GET/DELETE /api/content, GET /api/content/{id}
           POST /api/content/{id}/analyze, POST /api/content/{id}/favorite
           PATCH /api/content/{id}/note
流水线:    GET /api/pipelines, GET /api/pipelines/{id}
           POST /api/pipelines/{id}/retry, POST /api/pipelines/{id}/cancel
           POST /api/pipelines/manual
模板:      GET/POST /api/pipeline-templates, PUT/DELETE /api/pipeline-templates/{id}
提示词:    GET/POST /api/prompt-templates, PUT/DELETE /api/prompt-templates/{id}
设置:      GET/PUT /api/settings, GET/PUT /api/settings/{key}
视频:      POST /api/video/download, GET /api/video/downloads, GET /api/video/{id}/stream
```
