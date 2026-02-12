"""应用配置 - 从环境变量加载"""

import logging
from dataclasses import dataclass

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///data/db/allin.db"

    # External Services
    RSSHUB_URL: str = "http://rsshub:1200"
    BROWSERLESS_URL: str = "http://browserless:3000"

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


def get_llm_config() -> LLMConfig:
    """从数据库 system_settings 表读取 LLM 配置"""
    from app.core.database import SessionLocal
    from app.models.system_setting import SystemSetting

    with SessionLocal() as db:
        api_key = db.get(SystemSetting, "llm_api_key")
        base_url = db.get(SystemSetting, "llm_base_url")
        model = db.get(SystemSetting, "llm_model")

    return LLMConfig(
        api_key=api_key.value if api_key and api_key.value else "",
        base_url=base_url.value if base_url and base_url.value else "https://api.deepseek.com/v1",
        model=model.value if model and model.value else "deepseek-chat",
    )
