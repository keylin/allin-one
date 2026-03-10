"""数据源业务逻辑共享函数

供 Router (app/api/routes/sources.py) 和 MCP server (mcp_server.py) 共同调用。
不依赖 FastAPI，保持纯 SQLAlchemy。
"""

from sqlalchemy.orm import Session

from app.models.content import SourceConfig, SourceType, SourceCategory, get_source_category  # noqa: F401
from app.models.pipeline import PipelineTemplate


def validate_source_type(source_type: str) -> str | None:
    """校验 source_type，返回错误信息或 None"""
    valid = {e.value for e in SourceType}
    if source_type not in valid:
        return f"Invalid source_type '{source_type}'. Valid values: {sorted(valid)}"
    return None


def validate_source_config(source_type: str, url: str | None, config_json: dict | None) -> str | None:
    """校验各类型数据源的必填配置，返回错误信息或 None"""
    config = config_json if isinstance(config_json, dict) else {}
    if source_type == "rss.hub":
        if not config.get("rsshub_route"):
            return "RSSHub 数据源必须在配置中提供 rsshub_route 字段"
    elif source_type == "rss.standard":
        if not url:
            return "RSS/Atom 数据源必须提供 url 字段"
    elif source_type == "podcast.apple":
        if not config.get("apple_podcast_url") and not config.get("podcast_id"):
            return "Apple Podcasts 数据源必须提供 apple_podcast_url 或 podcast_id"
    return None


def validate_template_exists(pipeline_template_id: str | None, db: Session) -> str | None:
    """校验 pipeline_template_id 是否存在，返回错误信息或 None"""
    if not pipeline_template_id:
        return None
    tpl = db.get(PipelineTemplate, pipeline_template_id)
    if not tpl:
        return f"Pipeline template '{pipeline_template_id}' not found"
    return None


def validate_source_name_unique(name: str, db: Session, exclude_id: str | None = None) -> str | None:
    """校验数据源名称唯一性，返回错误信息或 None"""
    query = db.query(SourceConfig).filter(SourceConfig.name == name.strip())
    if exclude_id:
        query = query.filter(SourceConfig.id != exclude_id)
    existing = query.first()
    if existing:
        return f"数据源「{name}」已存在，请使用不同名称"
    return None
