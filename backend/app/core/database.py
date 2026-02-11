"""数据库连接与会话管理"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# 启用 WAL 模式以支持并发读写
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """SQLite 连接时启用 WAL 和外键约束"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """初始化数据库表 (包含 CollectionRecord 等新增表)"""
    import app.models.content  # noqa: F401 (SourceConfig, ContentItem, CollectionRecord)
    import app.models.pipeline  # noqa: F401 (PipelineTemplate, PipelineExecution, PipelineStep)
    import app.models.prompt_template  # noqa: F401
    import app.models.system_setting  # noqa: F401
    Base.metadata.create_all(bind=engine)


def get_db():
    """获取数据库会话 (FastAPI 依赖注入)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
