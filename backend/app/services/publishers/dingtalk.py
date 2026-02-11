"""DingTalk 推送 — 钉钉 Webhook 机器人"""

import logging
import httpx

logger = logging.getLogger(__name__)


async def publish_dingtalk(
    content: dict,
    webhook_url: str,
    at_mobiles: list[str] | None = None,
    at_all: bool = False,
) -> dict:
    """通过钉钉 Webhook 机器人推送消息

    Args:
        content: 消息内容，支持 "text" 或 "markdown" 格式
        webhook_url: 钉钉机器人 Webhook URL
        at_mobiles: @的手机号列表
        at_all: 是否 @所有人

    Returns:
        {"status": "sent", "response": dict}
    """
    msg_type = content.get("msg_type", "markdown")  # "text" or "markdown"
    title = content.get("title", "Allin-One 通知")
    text = content.get("text", "")

    # 构建钉钉消息格式
    if msg_type == "markdown":
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": text,
            },
        }
    else:
        payload = {
            "msgtype": "text",
            "text": {
                "content": text,
            },
        }

    # @人员配置
    if at_mobiles or at_all:
        payload["at"] = {
            "atMobiles": at_mobiles or [],
            "isAtAll": at_all,
        }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("errcode") != 0:
                raise Exception(f"DingTalk API error: {result.get('errmsg')}")

            logger.info(f"[dingtalk] Sent message: {title}")
            return {"status": "sent", "response": result}

    except Exception as e:
        logger.error(f"[dingtalk] Failed to send: {e}")
        raise


def format_content_dingtalk(content_item: dict) -> dict:
    """格式化 ContentItem 为钉钉消息

    Args:
        content_item: ContentItem 字典

    Returns:
        {"msg_type": "markdown", "title": str, "text": str}
    """
    title = content_item.get("title", "无标题")
    url = content_item.get("url", "")
    author = content_item.get("author", "")
    summary = content_item.get("processed_content", "")
    analysis = content_item.get("analysis_result", {})

    # 构建 Markdown 格式消息
    markdown_text = f"### {title}\n\n"

    if author:
        markdown_text += f"**作者:** {author}\n\n"

    if url:
        markdown_text += f"**链接:** [{url}]({url})\n\n"

    if summary:
        # 截取前 300 字符
        preview = summary[:300]
        if len(summary) > 300:
            preview += "..."
        markdown_text += f"**摘要:**\n\n{preview}\n\n"

    if analysis:
        # 如果分析结果是字典，提取关键信息
        if isinstance(analysis, dict):
            if "summary" in analysis:
                markdown_text += f"**AI 分析:**\n\n{analysis['summary']}\n\n"
            elif "tags" in analysis:
                tags = ", ".join(analysis.get("tags", []))
                markdown_text += f"**标签:** {tags}\n\n"

    markdown_text += "\n---\n*来自 Allin-One 自动推送*"

    return {
        "msg_type": "markdown",
        "title": title[:64],  # 钉钉标题限制 64 字符
        "text": markdown_text,
    }
