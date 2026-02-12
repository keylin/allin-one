"""日报/周报/月报生成任务"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


async def generate_daily_report():
    """每日摘要报告 — 汇总过去 24h 的内容与分析结果"""
    from app.core.database import SessionLocal
    from app.models.content import ContentItem, SourceConfig

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    with SessionLocal() as db:
        items = db.query(ContentItem).filter(
            ContentItem.collected_at >= since,
        ).order_by(ContentItem.collected_at.desc()).all()

        if not items:
            logger.info("[daily_report] No new content in the last 24h, skipping")
            return

        # 按来源分组
        source_ids = {item.source_id for item in items}
        sources = {s.id: s for s in db.query(SourceConfig).filter(SourceConfig.id.in_(source_ids)).all()}

        # 构建摘要素材
        source_groups = {}
        for item in items:
            source_name = sources.get(item.source_id, None)
            source_name = source_name.name if source_name else "未知来源"
            if source_name not in source_groups:
                source_groups[source_name] = []
            source_groups[source_name].append({
                "title": item.title,
                "url": item.url,
                "status": item.status,
                "has_analysis": bool(item.analysis_result),
            })

    # 构建报告内容
    report_lines = [
        f"# 日报 — {now.strftime('%Y-%m-%d')}",
        "",
        f"**统计**: 过去 24 小时共采集 **{len(items)}** 条内容，来自 **{len(source_groups)}** 个数据源。",
        "",
    ]

    for source_name, entries in source_groups.items():
        analyzed = sum(1 for e in entries if e["has_analysis"])
        report_lines.append(f"## {source_name} ({len(entries)} 条, {analyzed} 条已分析)")
        report_lines.append("")
        for entry in entries[:10]:  # 每源最多展示 10 条
            status_mark = "+" if entry["has_analysis"] else "-"
            report_lines.append(f"  {status_mark} {entry['title']}")
        if len(entries) > 10:
            report_lines.append(f"  ... 等共 {len(entries)} 条")
        report_lines.append("")

    report_md = "\n".join(report_lines)

    # 如果配置了 LLM，生成 AI 摘要
    if settings.LLM_API_KEY:
        try:
            summary = await _generate_ai_summary(report_md, "daily")
            report_md += "\n---\n\n## AI 总结\n\n" + summary
        except Exception as e:
            logger.warning(f"[daily_report] AI summary failed: {e}")

    # 保存报告文件
    _save_report(report_md, "daily", now)

    # 推送通知
    await _push_report(report_md, f"Allin-One 日报 {now.strftime('%Y-%m-%d')}")

    logger.info(f"[daily_report] Generated: {len(items)} items from {len(source_groups)} sources")


async def generate_weekly_report():
    """每周摘要报告"""
    from app.core.database import SessionLocal
    from app.models.content import ContentItem, SourceConfig

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)

    with SessionLocal() as db:
        items = db.query(ContentItem).filter(
            ContentItem.collected_at >= since,
        ).order_by(ContentItem.collected_at.desc()).all()

        if not items:
            logger.info("[weekly_report] No content in the last week, skipping")
            return

        source_ids = {item.source_id for item in items}
        sources = {s.id: s for s in db.query(SourceConfig).filter(SourceConfig.id.in_(source_ids)).all()}

        # 按天统计
        daily_counts = {}
        for item in items:
            day = item.collected_at.strftime("%Y-%m-%d") if item.collected_at else "unknown"
            daily_counts[day] = daily_counts.get(day, 0) + 1

    report_lines = [
        f"# 周报 — {(now - timedelta(days=7)).strftime('%m/%d')} ~ {now.strftime('%m/%d')}",
        "",
        f"**统计**: 本周共采集 **{len(items)}** 条内容，来自 **{len(source_ids)}** 个数据源。",
        "",
        "## 每日采集量",
        "",
    ]

    for day in sorted(daily_counts.keys()):
        report_lines.append(f"  - {day}: {daily_counts[day]} 条")

    report_lines.append("")
    report_md = "\n".join(report_lines)

    if settings.LLM_API_KEY:
        try:
            summary = await _generate_ai_summary(report_md, "weekly")
            report_md += "\n---\n\n## AI 总结\n\n" + summary
        except Exception as e:
            logger.warning(f"[weekly_report] AI summary failed: {e}")

    _save_report(report_md, "weekly", now)
    await _push_report(report_md, f"Allin-One 周报 {now.strftime('%Y-%m-%d')}")

    logger.info(f"[weekly_report] Generated: {len(items)} items over 7 days")


async def _generate_ai_summary(report_content: str, report_type: str) -> str:
    """使用 LLM 生成报告摘要"""
    client = AsyncOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
    )

    prompt_map = {
        "daily": "请对以下日报内容进行简要总结，提炼今日最重要的信息和趋势，200字以内：",
        "weekly": "请对以下周报内容进行总结，分析本周信息趋势和重点，300字以内：",
    }

    response = await client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": "你是一个信息聚合平台的智能助手，负责生成简洁的报告摘要。"},
            {"role": "user", "content": f"{prompt_map.get(report_type, prompt_map['daily'])}\n\n{report_content[:3000]}"},
        ],
    )

    return response.choices[0].message.content


def _save_report(content: str, report_type: str, timestamp: datetime):
    """将报告保存到文件"""
    reports_dir = settings.REPORTS_DIR
    os.makedirs(reports_dir, exist_ok=True)

    filename = f"{report_type}_{timestamp.strftime('%Y%m%d_%H%M%S')}.md"
    filepath = os.path.join(reports_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"[report] Saved to {filepath}")


async def _push_report(content: str, title: str):
    """通过已配置的渠道推送报告"""
    from app.core.database import SessionLocal
    from app.models.system_setting import SystemSetting

    with SessionLocal() as db:
        # Webhook 推送
        webhook_setting = db.get(SystemSetting, "notify_webhook")
        if webhook_setting and webhook_setting.value:
            try:
                from app.services.publishers.webhook import publish_webhook
                await publish_webhook(
                    {"title": title, "content": content[:2000]},
                    webhook_setting.value,
                )
            except Exception as e:
                logger.warning(f"[report] Webhook push failed: {e}")

        # 钉钉推送
        dingtalk_setting = db.get(SystemSetting, "notify_dingtalk_webhook")
        if dingtalk_setting and dingtalk_setting.value:
            try:
                from app.services.publishers.dingtalk import publish_dingtalk
                await publish_dingtalk(
                    {"msg_type": "markdown", "title": title, "text": content[:2000]},
                    dingtalk_setting.value,
                )
            except Exception as e:
                logger.warning(f"[report] DingTalk push failed: {e}")

        # 邮件推送
        smtp_host = db.get(SystemSetting, "smtp_host")
        smtp_user = db.get(SystemSetting, "smtp_user")
        smtp_password = db.get(SystemSetting, "smtp_password")
        notify_email = db.get(SystemSetting, "notify_email")

        if all([smtp_host, smtp_user, smtp_password, notify_email]):
            try:
                from app.services.publishers.email import publish_email
                smtp_port = db.get(SystemSetting, "smtp_port")
                to_emails = [e.strip() for e in notify_email.value.split(",") if e.strip()]
                await publish_email(
                    content={"subject": f"[Allin-One] {title}", "body": content, "content_type": "plain"},
                    smtp_host=smtp_host.value,
                    smtp_port=int(smtp_port.value) if smtp_port else 465,
                    smtp_user=smtp_user.value,
                    smtp_password=smtp_password.value,
                    to_emails=to_emails,
                )
            except Exception as e:
                logger.warning(f"[report] Email push failed: {e}")
