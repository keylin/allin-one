import json
import logging
from typing import Any, Dict, Union

from openai import AsyncOpenAI
from app.core.config import settings
from app.models.prompt_template import PromptTemplate, OutputFormat

logger = logging.getLogger(__name__)

class LLMAnalyzer:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL
        )
        self.model = settings.LLM_MODEL

    async def analyze(self, content: str, prompt_template: PromptTemplate) -> Dict[str, Any]:
        """
        执行 LLM 分析

        :param content: 需要分析的文本内容
        :param prompt_template: 提示词模版对象
        :return: 分析结果字典
        """
        messages = [
            {"role": "system", "content": prompt_template.system_prompt or "You are a helpful assistant."},
            {"role": "user", "content": prompt_template.user_prompt.format(content=content)}
        ]

        # 确定响应格式
        output_format = prompt_template.output_format or OutputFormat.JSON.value
        response_format = None

        if output_format == OutputFormat.JSON.value:
            response_format = {"type": "json_object"}

        try:
            logger.info(f"Calling LLM ({self.model}) with format: {output_format}")
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format=response_format
            )

            result_text = response.choices[0].message.content
            usage = response.usage
            if usage:
                logger.info(
                    f"LLM usage: prompt={usage.prompt_tokens} completion={usage.completion_tokens} total={usage.total_tokens}"
                )

            # 根据格式处理返回结果
            if output_format == OutputFormat.JSON.value:
                try:
                    return json.loads(result_text)
                except json.JSONDecodeError:
                    logger.error(f"Failed to decode JSON from LLM response: {result_text}")
                    return {"error": "Invalid JSON response", "raw_content": result_text}
            else:
                # Markdown 或 Text 格式，封装为标准字典返回
                return {
                    "content": result_text,
                    "format": output_format
                }

        except Exception as e:
            logger.exception(f"LLM analysis failed: {e}")
            return {"error": str(e)}
