"""Allin-One: 个人信息聚合与智能分析平台"""

import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.auth import APIKeyMiddleware
from app.core.database import init_db
from app.api.routes import dashboard, sources, content, pipelines, templates, video, system_settings, prompt_templates, finance, credentials

# 配置根 logger，使 app.* 的日志正确输出到控制台
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

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

    # 启动定时调度器
    if settings.SCHEDULER_ENABLED:
        from app.tasks.scheduled_tasks import start_scheduler
        start_scheduler()
    else:
        logger.info("Scheduler disabled by config")

    logger.info("Allin-One started")
    yield

    # Shutdown
    logger.info("Shutting down Allin-One ...")
    if settings.SCHEDULER_ENABLED:
        from app.tasks.scheduled_tasks import stop_scheduler
        stop_scheduler()


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
app.include_router(system_settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(prompt_templates.router, prefix="/api/prompt-templates", tags=["prompt-templates"])
app.include_router(finance.router, prefix="/api/finance", tags=["finance"])
app.include_router(credentials.router, prefix="/api/credentials", tags=["credentials"])

# Static files (Vue frontend) — 必须最后注册，catch-all 会拦截未匹配路由
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
