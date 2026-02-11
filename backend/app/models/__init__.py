"""ORM 模型汇总 — 确保所有模型在 mapper 配置前完成注册"""

from app.models.content import SourceConfig, ContentItem, CollectionRecord  # noqa: F401
from app.models.pipeline import PipelineTemplate, PipelineExecution, PipelineStep  # noqa: F401
from app.models.prompt_template import PromptTemplate  # noqa: F401
from app.models.system_setting import SystemSetting  # noqa: F401
