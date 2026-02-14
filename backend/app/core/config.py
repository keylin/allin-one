"""应用配置 - 从环境变量加载"""

import logging
from dataclasses import dataclass

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://allinone:allinone@localhost:5432/allinone"

    # External Services
    RSSHUB_URL: str = "http://rsshub:1200"
    BROWSERLESS_URL: str = "http://browserless:3000"

    # Miniflux
    MINIFLUX_URL: str = "http://miniflux:8080"
    MINIFLUX_API_KEY: str = ""

    # Security
    API_KEY: str = ""
    CORS_ORIGINS: str = "*"

    # Application
    APP_PORT: int = 8000
    WORKER_CONCURRENCY: int = 4
    LOG_LEVEL: str = "INFO"
    SCHEDULER_ENABLED: bool = True

    # File Storage
    DATA_DIR: str = "data"
    MEDIA_DIR: str = "data/media"
    REPORTS_DIR: str = "data/reports"
    LOG_DIR: str = "data/logs"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str


def get_llm_config(db=None) -> LLMConfig:
    """从数据库 system_settings 表读取 LLM 配置

    Args:
        db: 可选的数据库会话，传入时复用已有连接避免额外开销
    """
    from app.models.system_setting import SystemSetting

    def _read(session):
        api_key = session.get(SystemSetting, "llm_api_key")
        base_url = session.get(SystemSetting, "llm_base_url")
        model = session.get(SystemSetting, "llm_model")
        return api_key, base_url, model

    if db:
        api_key, base_url, model = _read(db)
    else:
        from app.core.database import SessionLocal
        with SessionLocal() as session:
            api_key, base_url, model = _read(session)

    key = api_key.value if api_key and api_key.value else ""
    if not key:
        raise ValueError("LLM API Key 未配置，请在系统设置中填写")

    return LLMConfig(
        api_key=key,
        base_url=base_url.value if base_url and base_url.value else "https://api.deepseek.com/v1",
        model=model.value if model and model.value else "deepseek-chat",
    )
