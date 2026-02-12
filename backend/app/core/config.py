"""应用配置 - 从环境变量加载"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///data/db/allin.db"
    
    # LLM (支持 OpenAI 兼容接口: deepseek / qwen / openai / siliconflow 等)
    LLM_PROVIDER: str = "deepseek"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-chat"
    
    # External Services
    RSSHUB_URL: str = "http://rsshub:1200"
    BROWSERLESS_URL: str = "http://browserless:3000"
    
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


settings = Settings()
