"""Pipeline step: publish_content — 消息推送"""

import json
import logging

from app.services.pipeline.steps._helpers import _run_async

logger = logging.getLogger(__name__)


def _handle_publish_content(context: dict) -> dict:
    """消息推送"""
    config = context["step_config"]
    channel = config.get("channel", "none")
    if channel == "none":
        return {"status": "skipped", "reason": "channel=none"}

    content_id = context["content_id"]
    logger.info(f"[publish_content] channel={channel}, content={content_id}")

    if channel == "webhook":
        from app.core.database import SessionLocal
        from app.models.content import ContentItem, SourceConfig
        from app.models.system_setting import SystemSetting
        from app.services.publishers.webhook import publish_webhook

        with SessionLocal() as db:
            content = db.get(ContentItem, content_id)
            if not content:
                raise ValueError(f"Content not found: {content_id}")

            source = db.get(SourceConfig, content.source_id)
            setting = db.get(SystemSetting, "notify_webhook")
            webhook_url = setting.value if setting else None

            # 在 session 内提取所有字段，避免 session 关闭后 DetachedInstanceError
            payload = {
                "title": content.title,
                "url": content.url,
                "summary": (content.processed_content or "")[:500],
                "analysis_result": json.loads(content.analysis_result) if content.analysis_result else None,
                "source_name": source.name if source else None,
            }

        if not webhook_url:
            return {"status": "skipped", "reason": "no webhook URL configured"}

        result = _run_async(publish_webhook(payload, webhook_url))
        return result

    if channel == "email":
        from app.core.database import SessionLocal
        from app.models.content import ContentItem, SourceConfig
        from app.models.system_setting import SystemSetting
        from app.services.publishers.email import publish_email, format_content_email

        with SessionLocal() as db:
            content = db.get(ContentItem, content_id)
            if not content:
                raise ValueError(f"Content not found: {content_id}")

            source = db.get(SourceConfig, content.source_id)

            # 读取 SMTP 配置
            smtp_host = db.get(SystemSetting, "smtp_host")
            smtp_port = db.get(SystemSetting, "smtp_port")
            smtp_user = db.get(SystemSetting, "smtp_user")
            smtp_password = db.get(SystemSetting, "smtp_password")
            notify_email = db.get(SystemSetting, "notify_email")

            if not all([smtp_host, smtp_user, smtp_password, notify_email]):
                return {"status": "skipped", "reason": "SMTP not configured"}

            # 在 session 内提取所有字段
            email_data = {
                "title": content.title,
                "url": content.url,
                "author": content.author,
                "processed_content": content.processed_content,
                "analysis_result": json.loads(content.analysis_result) if content.analysis_result else None,
            }
            smtp_host_val = smtp_host.value
            smtp_port_val = int(smtp_port.value) if smtp_port else 465
            smtp_user_val = smtp_user.value
            smtp_password_val = smtp_password.value
            to_emails = [e.strip() for e in notify_email.value.split(",") if e.strip()]

        email_content = format_content_email(email_data)

        result = _run_async(publish_email(
            content=email_content,
            smtp_host=smtp_host_val,
            smtp_port=smtp_port_val,
            smtp_user=smtp_user_val,
            smtp_password=smtp_password_val,
            to_emails=to_emails,
        ))
        return result

    if channel == "dingtalk":
        from app.core.database import SessionLocal
        from app.models.content import ContentItem, SourceConfig
        from app.models.system_setting import SystemSetting
        from app.services.publishers.dingtalk import publish_dingtalk, format_content_dingtalk

        with SessionLocal() as db:
            content = db.get(ContentItem, content_id)
            if not content:
                raise ValueError(f"Content not found: {content_id}")

            source = db.get(SourceConfig, content.source_id)
            setting = db.get(SystemSetting, "notify_dingtalk_webhook")
            dingtalk_url = setting.value if setting else None

            # 在 session 内提取所有字段
            dingtalk_data = {
                "title": content.title,
                "url": content.url,
                "author": content.author,
                "processed_content": content.processed_content,
                "analysis_result": json.loads(content.analysis_result) if content.analysis_result else None,
            }

        if not dingtalk_url:
            return {"status": "skipped", "reason": "DingTalk webhook not configured"}

        dingtalk_content = format_content_dingtalk(dingtalk_data)

        result = _run_async(publish_dingtalk(
            content=dingtalk_content,
            webhook_url=dingtalk_url,
        ))
        return result

    logger.warning(f"[publish_content] Channel '{channel}' not implemented")
    return {"status": "skipped", "reason": f"channel '{channel}' not implemented"}
