"""数据库连接与会话管理"""

import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

logger = logging.getLogger(__name__)

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
    """初始化数据库表

    注意：数据库迁移现已通过 Alembic 管理。
    在生产环境中，请使用 `alembic upgrade head` 来创建和更新表。
    此函数保留仅用于快速开发/测试场景。
    """
    import app.models  # noqa: F401 — 确保所有 ORM 模型注册

    # 开发环境下的快速初始化（不推荐生产使用）
    # 生产环境应使用: alembic upgrade head
    Base.metadata.create_all(bind=engine)
    logger.info(f"Database initialized: {settings.DATABASE_URL}")


def get_db():
    """获取数据库会话 (FastAPI 依赖注入)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
