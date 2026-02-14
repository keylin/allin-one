# 后端开发规范

## 架构分层

```
FastAPI Router → Service Layer → Pipeline Engine / Collectors
     ↓               ↓                    ↓
Pydantic Schema   SQLAlchemy ORM    Procrastinate Tasks
```

- **Router** (`app/api/routes/`): 薄 HTTP 层，Pydantic 校验入参，`Depends(get_db)` 注入数据库
- **Service** (`app/services/`): 业务逻辑，分为 pipeline/、collectors/、analyzers/、publishers/
- **Models** (`app/models/`): SQLAlchemy ORM，所有表用 UUID 字符串主键 (`uuid.uuid4().hex`)
- **Tasks** (`app/tasks/`): Procrastinate 异步任务，`pipeline_tasks.py` 分发步骤处理器

## ORM 模型注册

`app/models/__init__.py` 统一导入所有 ORM 模型类。
Procrastinate worker 等非 FastAPI 入口必须在使用 ORM 前执行 `import app.models`，
确保 SQLAlchemy 的 relationship() 字符串引用能正确解析。

## 数据库约定

- **PostgreSQL** 为主数据库，单一 PG 实例单一 database (`allinone`)
- Procrastinate 任务队列使用同一 PG database（自动创建 `procrastinate_*` 表）
- 主键: `Column(String, primary_key=True, default=lambda: uuid.uuid4().hex)`
- 时间戳: 一律 **naive UTC** (`datetime.now(timezone.utc).replace(tzinfo=None)`)，禁止带时区信息的 datetime（PG `TIMESTAMP WITHOUT TIME ZONE` 会做时区转换导致双重偏移）
- 枚举: 使用 `str, Enum` 子类，存储 `.value` 字符串到 DB
- 迁移: 必须通过 `alembic revision --autogenerate`，禁止手写 SQL
- JSON 字段当前存储为 `Column(Text)` + `json.loads`/`json.dumps`（后续可迁移到 JSONB）
- `database.py` 保留 SQLite fallback（用于本地测试），通过 `DATABASE_URL` 前缀自动切换
- LLM 配置: 存储在 `system_settings` 表（非环境变量），通过 `get_llm_config()` 读取
- 数据目录: `data/` 在项目根目录（非 backend/data/），backend 和 worker 共享

## API 响应格式

所有端点必须返回:
```python
{"code": 0, "data": <结果>, "message": "ok"}              # 成功
{"code": <错误码>, "data": None, "message": "错误信息"}     # 失败
```

分页列表:
```python
{"code": 0, "data": [...], "total": N, "page": P, "page_size": S, "message": "ok"}
```

## API 路由模式

所有路由文件遵循此模式（参考 `app/api/routes/sources.py`）:
```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db

router = APIRouter()

@router.get("/")
async def list_things(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    ...
```

## Pydantic Schema 约定

Schema 放在 `app/schemas/`，每个资源一个文件:
```python
class SourceCreate(BaseModel):       # 创建请求体
    name: str
    source_type: str
    url: Optional[str] = None

class SourceResponse(BaseModel):     # 响应模型
    id: str
    name: str
    class Config:
        from_attributes = True       # ORM 模式
```

## 枚举定义

枚举值以代码为准，不要凭记忆：
- `app/models/content.py` — SourceType, MediaType (仅用于 MediaItem: image/video/audio), ContentStatus (含 ready)
- `app/models/pipeline.py` — StepType (含 localize_media), PipelineStatus, StepStatus, TriggerSource
- `app/models/prompt_template.py` — TemplateType

注意: ContentItem 和 SourceConfig 不再有 `media_type` 字段。媒体类型通过 `MediaItem` 一对多关联管理。

## 日志配置

`app/core/logging_config.py` 统一配置结构化日志:
- 调用 `setup_logging("backend")` 或 `setup_logging("worker")` 初始化
- 文件日志写入 `data/logs/` (WARNING+)，错误汇总到 `error.log` (ERROR+)
- 控制台同步输出 INFO+ 级别
