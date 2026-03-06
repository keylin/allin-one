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
- 时间戳: 一律 **naive UTC**，统一调用 `from app.core.time import utcnow`，禁止直接使用 `datetime.now(timezone.utc)`

### 时间戳陷阱 — 必读

**绝对禁止**: `datetime.now(timezone.utc)` 直接写入数据库或与数据库读出的值比较。

**原因**: PG 列类型是 `TIMESTAMP WITHOUT TIME ZONE`。当写入带 `tzinfo` 的 datetime 时，PG 会按 server timezone 做 UTC→本地转换后存储。读出时又被当作 UTC，导致双重偏移（曾导致定时采集延迟 8 小时的线上事故）。

**正确做法**:
```python
from app.core.time import utcnow

now = utcnow()                    # 返回 naive UTC datetime
item.updated_at = utcnow()        # 写入数据库
if now > item.last_at + delta:    # 与数据库值比较（都是 naive UTC）
```

**禁止写法**:
```python
datetime.now(timezone.utc)                          # 带 tzinfo，写入 PG 会被转换
datetime.now(timezone.utc).replace(tzinfo=None)     # 正确但啰嗦，用 utcnow() 代替
some_dt.replace(tzinfo=timezone.utc)                # 给 naive datetime 加时区标记，与 PG 值混用会出错
```
- 枚举: 使用 `str, Enum` 子类，存储 `.value` 字符串到 DB
- 迁移: 必须通过 `alembic revision --autogenerate`，禁止手写 SQL
- JSONB 字段（`raw_data`、`analysis_result`、`metadata_json`、`periodicity_data`、`config_json`、`chat_history`、`extra_info`、`steps_config`、`step_config`、`input_data`、`output_data`、`options_json` 等）已迁移为 `Column(JSONB)`，直接作为 Python dict/list 读写，禁止再用 `json.loads`/`json.dumps`:
  ```python
  raw = item.raw_data if isinstance(item.raw_data, dict) else {}   # 安全读取
  item.raw_data = {"key": "value"}                                  # 直接赋值 dict
  query.filter(col["arr"].contains([val]))   # JSONB 数组 @> 包含查询（精确成员匹配）
  query.filter(col["key"].astext == val)     # JSONB 键等值查询（标量）
  # ❌ json.loads(item.raw_data)            — 旧 Text 模式，已废弃
  # ❌ cast(col, JSONB)["key"].astext       — 字段已是 JSONB，无需 cast
  ```
- 仍为 Text 的字段（`system_settings.value`、`processed_content` 等）继续用 `json.loads`/`json.dumps`
- `database.py` 保留 SQLite fallback（用于本地测试），通过 `DATABASE_URL` 前缀自动切换
- LLM 配置: 存储在 `system_settings` 表（非环境变量），通过 `get_llm_config()` 读取
- 凭证加解密: `platform_credentials.credential_data` 使用 `app.core.crypto` 的 `encrypt_credential()` / `decrypt_credential()` 加解密，写入时必须 encrypt，读取时必须 decrypt。未配置 `CREDENTIAL_ENCRYPTION_KEY` 时透传原文
- FK 策略: 子表强依赖父表用 `ON DELETE CASCADE` (media_items, pipeline_steps, collection_records, finance_data_points)；可选引用用 `ON DELETE SET NULL` (pipeline_executions.source_id/template_id, source_configs.pipeline_template_id/credential_id)
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
- `app/models/content.py` — SourceType, MediaType (仅用于 MediaItem: image/video/audio/ebook), ContentStatus (含 ready)
- `app/models/pipeline.py` — StepType (含 localize_media), PipelineStatus, StepStatus, TriggerSource
- `app/models/prompt_template.py` — TemplateType

注意: ContentItem 和 SourceConfig 不再有 `media_type` 字段。媒体类型通过 `MediaItem` 一对多关联管理。

## 日志配置

`app/core/logging_config.py` 统一配置结构化日志:
- 调用 `setup_logging("backend")` 或 `setup_logging("worker")` 初始化
- 文件日志写入 `data/logs/` (WARNING+)，错误汇总到 `error.log` (ERROR+)
- 控制台同步输出 INFO+ 级别
