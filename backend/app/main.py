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
from app.api.routes import dashboard, sources, content, pipelines, templates, video, audio, media, ebook, system_settings, prompt_templates, finance, credentials, opml, export as export_router, bilibili_auth

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
    except Exception as e:
        logger.debug(f"Procrastinate schema apply skipped: {e}")

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
    """综合健康检查 — DB / RSSHub / Browserless"""
    import httpx
    from sqlalchemy import text
    from app.core.database import SessionLocal

    checks = {}

    # Database
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # RSSHub
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.RSSHUB_URL}/")
            checks["rsshub"] = "ok" if resp.status_code < 500 else f"status {resp.status_code}"
    except Exception as e:
        checks["rsshub"] = f"unreachable: {type(e).__name__}"

    # Browserless
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.BROWSERLESS_URL}/pressure")
            checks["browserless"] = "ok" if resp.status_code < 500 else f"status {resp.status_code}"
    except Exception as e:
        checks["browserless"] = f"unreachable: {type(e).__name__}"

    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ok" if all_ok else "degraded", "checks": checks}

# API Routes
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(export_router.router, prefix="/api/sources", tags=["sources"])
app.include_router(opml.router, prefix="/api/sources", tags=["sources"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"])
app.include_router(content.router, prefix="/api/content", tags=["content"])
app.include_router(pipelines.router, prefix="/api/pipelines", tags=["pipelines"])
app.include_router(templates.router, prefix="/api/pipeline-templates", tags=["pipeline-templates"])
app.include_router(video.router, prefix="/api/video", tags=["video"])
app.include_router(audio.router, prefix="/api/audio", tags=["audio"])
app.include_router(media.router, prefix="/api/media", tags=["media"])
app.include_router(ebook.router, prefix="/api/ebook", tags=["ebook"])
app.include_router(system_settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(prompt_templates.router, prefix="/api/prompt-templates", tags=["prompt-templates"])
app.include_router(finance.router, prefix="/api/finance", tags=["finance"])
app.include_router(credentials.router, prefix="/api/credentials", tags=["credentials"])
app.include_router(bilibili_auth.router, prefix="/api/credentials/bilibili", tags=["credentials"])

# Static files (Vue frontend) — 必须最后注册，catch-all 会拦截未匹配路由
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
