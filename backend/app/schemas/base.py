"""基础响应模型"""

from typing import Any, Optional
from pydantic import BaseModel


class APIResponse(BaseModel):
    code: int = 0
    data: Any = None
    message: str = "ok"


class PaginatedResponse(APIResponse):
    total: int = 0
    page: int = 1
    page_size: int = 20


def error_response(code: int, message: str) -> dict:
    return {"code": code, "data": None, "message": message}
