"""Email 推送 — SMTP 邮件发送"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

logger = logging.getLogger(__name__)


async def publish_email(
    content: dict,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    to_emails: list[str],
    from_email: str | None = None,
    from_name: str | None = None,
    use_ssl: bool = True,
) -> dict:
    """通过 SMTP 发送邮件

    Args:
        content: 内容字典，至少包含 "subject" 和 "body"
        smtp_host: SMTP 服务器地址
        smtp_port: SMTP 端口（通常 465 for SSL, 587 for TLS）
        smtp_user: SMTP 用户名
        smtp_password: SMTP 密码
        to_emails: 收件人邮箱列表
        from_email: 发件人邮箱（默认使用 smtp_user）
        from_name: 发件人名称
        use_ssl: 是否使用 SSL（默认 True，端口 465）

    Returns:
        {"status": "sent", "recipients": list[str]}
    """
    if not to_emails:
        raise ValueError("No recipients specified")

    subject = content.get("subject", "Allin-One 通知")
    body = content.get("body", "")
    content_type = content.get("content_type", "html")  # "html" or "plain"

    # 构建邮件
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = ", ".join(to_emails)

    # 发件人
    sender_email = from_email or smtp_user
    if from_name:
        msg["From"] = formataddr((from_name, sender_email))
    else:
        msg["From"] = sender_email

    # 邮件正文
    if content_type == "html":
        part = MIMEText(body, "html", "utf-8")
    else:
        part = MIMEText(body, "plain", "utf-8")

    msg.attach(part)

    try:
        # 连接 SMTP 服务器
        if use_ssl:
            # SSL 连接（端口 465）
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        else:
            # TLS 连接（端口 587）
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            server.starttls()

        # 登录
        server.login(smtp_user, smtp_password)

        # 发送邮件
        server.sendmail(sender_email, to_emails, msg.as_string())
        server.quit()

        logger.info(f"[email] Sent to {len(to_emails)} recipients: {subject}")
        return {"status": "sent", "recipients": to_emails}

    except Exception as e:
        logger.error(f"[email] Failed to send: {e}")
        raise


def format_content_email(content_item: dict) -> dict:
    """格式化 ContentItem 为邮件内容

    Args:
        content_item: ContentItem 字典

    Returns:
        {"subject": str, "body": str, "content_type": "html"}
    """
    title = content_item.get("title", "无标题")
    url = content_item.get("url", "")
    author = content_item.get("author", "")
    summary = content_item.get("processed_content", "")
    analysis = content_item.get("analysis_result", {})

    # 构建 HTML 邮件模板
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }}
            .header {{
                border-bottom: 3px solid #6366f1;
                padding-bottom: 15px;
                margin-bottom: 20px;
            }}
            .title {{
                font-size: 24px;
                font-weight: bold;
                color: #1e293b;
                margin: 0;
            }}
            .meta {{
                color: #64748b;
                font-size: 14px;
                margin-top: 8px;
            }}
            .content {{
                background: #f8fafc;
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
            }}
            .analysis {{
                background: #eff6ff;
                border-left: 4px solid #3b82f6;
                padding: 15px;
                margin: 20px 0;
            }}
            .footer {{
                text-align: center;
                color: #94a3b8;
                font-size: 12px;
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #e2e8f0;
            }}
            a {{
                color: #6366f1;
                text-decoration: none;
            }}
            a:hover {{
                text-decoration: underline;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1 class="title">{title}</h1>
            <div class="meta">
                {f'作者: {author} | ' if author else ''}
                <a href="{url}">查看原文</a>
            </div>
        </div>

        {f'<div class="content">{summary[:500]}...</div>' if summary else ''}

        {f'<div class="analysis"><strong>AI 分析:</strong><br>{str(analysis)}</div>' if analysis else ''}

        <div class="footer">
            由 Allin-One 自动推送
        </div>
    </body>
    </html>
    """

    return {
        "subject": f"[Allin-One] {title}",
        "body": html_body.strip(),
        "content_type": "html",
    }
