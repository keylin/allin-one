"""Webhook 推送"""

import json
import logging

import httpx

logger = logging.getLogger(__name__)


async def publish_webhook(payload: dict, webhook_url: str) -> dict:
    """POST JSON 到 webhook URL

    Args:
        payload: 推送内容
        webhook_url: 目标 URL

    Returns:
        {"status": "published", "status_code": int}
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            logger.info(f"[webhook] Published to {webhook_url}: {resp.status_code}")
            return {"status": "published", "status_code": resp.status_code}
    except Exception as e:
        logger.error(f"[webhook] Failed to publish to {webhook_url}: {e}")
        raise
