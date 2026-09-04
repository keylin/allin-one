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
    # crawl4ai 用 connect_over_cdp，需 v2 的 CDP 端点 /chromium（非 Playwright 协议端点 /chromium/playwright）
    CRAWL4AI_CDP_URL: str = "ws://browserless:3000/chromium"
    # Browserless v2 鉴权 token；留空则不带 token（兼容旧 v1 / 本地无鉴权）
    BROWSERLESS_TOKEN: str = ""

    # Security
    API_KEY: str = ""
    CORS_ORIGINS: str = "*"
    CREDENTIAL_ENCRYPTION_KEY: str = ""  # Fernet key for credential encryption

    # Database Pool
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5

    # Financial Data（蚂蚁 financial-data API，MCP 金融工具主数据源）
    # key 留空时自动全量降级到 akshare/雪球，功能不受影响
    FINANCIAL_DATA_ENABLED: bool = True
    FINANCIAL_DATA_API_KEY: str = ""
    FINANCIAL_DATA_BASE_URL: str = "https://dfdatamcpnexus-prod.antgroup-inc.cn"
    FINANCIAL_DATA_API_VERSION: str = "1.6.0"
    FINANCIAL_DATA_TIMEOUT: float = 8.0
    FINANCIAL_DATA_MAX_RETRIES: int = 2
    # 工具级开关，逗号分隔: snapshot,quote,kline,macro；"all" 或空 = 全开
    FINANCIAL_DATA_TOOLS: str = "all"

    # Application
    LOG_LEVEL: str = "INFO"

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


def browserless_params() -> dict | None:
    """Browserless v2 REST 调用的鉴权查询参；token 为空时返回 None（不带鉴权）"""
    return {"token": settings.BROWSERLESS_TOKEN} if settings.BROWSERLESS_TOKEN else None


def crawl4ai_cdp_url() -> str:
    """返回带 token 的 Crawl4AI CDP WebSocket 地址；token 为空时返回原始地址"""
    url = settings.CRAWL4AI_CDP_URL
    if settings.BROWSERLESS_TOKEN:
        url += ("&" if "?" in url else "?") + f"token={settings.BROWSERLESS_TOKEN}"
    return url


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

    from app.core.crypto import decrypt_credential
    key = decrypt_credential(api_key.value) if api_key and api_key.value else ""
    if not key:
        raise ValueError("LLM API Key 未配置，请在系统设置中填写")

    return LLMConfig(
        api_key=key,
        base_url=base_url.value if base_url and base_url.value else "https://api.deepseek.com/v1",
        model=model.value if model and model.value else "deepseek-chat",
    )
