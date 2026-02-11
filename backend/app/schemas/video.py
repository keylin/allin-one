"""Video 请求/响应模型"""

from typing import Optional
from pydantic import BaseModel


class VideoDownloadRequest(BaseModel):
    url: str
    source_id: Optional[str] = None
