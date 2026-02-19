"""Allin-One: 个人信息聚合与智能分析平台"""

import logging
import mimetypes
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# 注册 PWA 相关 MIME 类型（Python mimetypes 默认不识别）
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("application/javascript", ".js", strict=True)

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.auth import APIKeyMiddleware
from app.core.database import init_db
from app.api.routes import dashboard, sources, content, pipelines, templates, video, audio, system_settings, prompt_templates, finance, credentials, opml, bilibili_auth

setup_logging("backend")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # Startup
    logger.info("Starting Allin-One ...")
    init_db()

    # 写入内置流水线模板
    from app.core.database import SessionLocal
    from app.services.pipeline.orchestrator import seed_builtin_templates
    with SessionLocal() as db:
        seed_builtin_templates(db)

    # 初始化 Procrastinate schema (首次运行自动创建 procrastinate_* 表)
    from app.tasks.procrastinate_app import proc_app
    await proc_app.open_async()
    try:
        await proc_app.schema_manager.apply_schema_async()
    except Exception:
        logger.debug("Procrastinate schema already exists, skipping")

    logger.info("Allin-One started")
    yield

    # Shutdown
    logger.info("Shutting down Allin-One ...")
    await proc_app.close_async()


app = FastAPI(
    title="Allin-One",
    description="个人信息聚合与智能分析平台",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Key 认证
app.add_middleware(APIKeyMiddleware)

# ---- 全局异常处理器 ----

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"{request.method} {request.url.path} -> {exc.status_code} {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "data": None, "message": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception(f"{request.method} {request.url.path} -> 500 {exc}")
    return JSONResponse(
        status_code=500,
        content={"code": 500, "data": None, "message": "Internal server error"},
    )


# Health check (必须在 Static mount 之前注册)
@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}

# API Routes
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"])
app.include_router(content.router, prefix="/api/content", tags=["content"])
app.include_router(pipelines.router, prefix="/api/pipelines", tags=["pipelines"])
app.include_router(templates.router, prefix="/api/pipeline-templates", tags=["pipeline-templates"])
app.include_router(video.router, prefix="/api/video", tags=["video"])
app.include_router(audio.router, prefix="/api/audio", tags=["audio"])
app.include_router(system_settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(prompt_templates.router, prefix="/api/prompt-templates", tags=["prompt-templates"])
app.include_router(finance.router, prefix="/api/finance", tags=["finance"])
app.include_router(credentials.router, prefix="/api/credentials", tags=["credentials"])
app.include_router(opml.router, prefix="/api/sources", tags=["sources"])
app.include_router(bilibili_auth.router, prefix="/api/credentials/bilibili", tags=["credentials"])

# ---- 通用媒体文件服务 ----

@app.get("/api/media/{content_id}/{file_path:path}", tags=["media"])
async def serve_media(content_id: str, file_path: str):
    """从 MEDIA_DIR/{content_id}/ 读取媒体文件"""
    import mimetypes
    from fastapi.responses import FileResponse

    full_path = os.path.join(settings.MEDIA_DIR, content_id, file_path)
    # 安全检查: 不能跳出 MEDIA_DIR
    real_path = os.path.realpath(full_path)
    real_media_dir = os.path.realpath(settings.MEDIA_DIR)
    if not real_path.startswith(real_media_dir):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.isfile(real_path):
        raise HTTPException(status_code=404, detail="File not found")

    mime_type, _ = mimetypes.guess_type(real_path)
    return FileResponse(real_path, media_type=mime_type or "application/octet-stream")

# Static files (Vue frontend) — 必须最后注册，catch-all 会拦截未匹配路由
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
