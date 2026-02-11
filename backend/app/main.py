"""Allin-One: 个人信息聚合与智能分析平台"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.api.routes import dashboard, sources, content, pipelines, templates, video, system_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # Startup
    init_db()
    
    # 写入内置流水线模版
    from app.core.database import SessionLocal
    from app.services.pipeline.orchestrator import seed_builtin_templates
    with SessionLocal() as db:
        seed_builtin_templates(db)
    
    # 启动定时调度器
    if settings.SCHEDULER_ENABLED:
        from app.tasks.scheduled_tasks import start_scheduler
        start_scheduler()
    
    yield
    
    # Shutdown
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routes
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"])
app.include_router(content.router, prefix="/api/content", tags=["content"])
app.include_router(pipelines.router, prefix="/api/pipelines", tags=["pipelines"])
app.include_router(templates.router, prefix="/api/pipeline-templates", tags=["pipeline-templates"])
app.include_router(video.router, prefix="/api/video", tags=["video"])
app.include_router(system_settings.router, prefix="/api/settings", tags=["settings"])

# Static files (Vue frontend)
app.mount("/", StaticFiles(directory="static", html=True), name="static")


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}
