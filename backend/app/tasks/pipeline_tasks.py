"""Pipeline 异步任务

每个步骤处理函数接收 context, 其中:
- content_id: 必有, 被处理的 ContentItem
- content_url: 内容原始链接
- step_config: 该步骤的操作配置
- previous_steps: 之前步骤的输出

注意: 没有 fetch_content 处理函数。
数据抓取由 CollectionService + 定时器完成, 不是流水线步骤。
"""

import logging
from app.tasks.huey_instance import huey
from app.services.pipeline.executor import PipelineExecutor

logger = logging.getLogger(__name__)
executor = PipelineExecutor()


@huey.task(retries=3, retry_delay=30)
def execute_pipeline_step(execution_id: str, step_index: int):
    """通用步骤执行入口 — 根据 step_type 分派"""
    from app.core.database import SessionLocal
    from app.models.pipeline import PipelineStep

    with SessionLocal() as db:
        step = db.query(PipelineStep).filter(
            PipelineStep.pipeline_id == execution_id,
            PipelineStep.step_index == step_index,
        ).first()
        if not step:
            logger.error(f"Step not found: execution={execution_id}, index={step_index}")
            return
        step_type = step.step_type

    executor.mark_step_running(execution_id, step_index)

    try:
        context = executor.get_step_context(execution_id, step_index)

        handler = STEP_HANDLERS.get(step_type)
        if not handler:
            raise ValueError(f"Unknown step_type: {step_type}")

        result = handler(context)

        executor.complete_step(execution_id, step_index, output_data=result)
        executor.advance_pipeline(execution_id)

    except Exception as e:
        logger.exception(f"Step {step_type} failed: {e}")
        executor.fail_step(execution_id, step_index, str(e))
        executor.advance_pipeline(execution_id)


# ============ 步骤处理函数 ============
# 所有函数的输入都是已存在的 ContentItem, 通过 context 获取


def _handle_enrich_content(context: dict) -> dict:
    """抓取全文 — 三级递进策略"""
    config = context["step_config"]
    scrape_level = config.get("scrape_level", "auto")
    url = context["content_url"]
    logger.info(f"[enrich_content] level={scrape_level}, url={url}")
    # TODO: ContentEnricher.enrich(url, level) → 更新 content.processed_content
    return {"status": "enriched", "scrape_level_used": scrape_level}


def _handle_download_video(context: dict) -> dict:
    """下载视频 — yt-dlp"""
    config = context["step_config"]
    platform = config.get("platform", "auto")
    quality = config.get("quality", "1080p")
    url = context["content_url"]
    logger.info(f"[download_video] platform={platform}, quality={quality}, url={url}")
    # TODO: yt-dlp 下载, 返回文件路径
    return {"status": "downloaded", "platform": platform, "file_path": ""}


def _handle_extract_audio(context: dict) -> dict:
    """音频提取"""
    video_path = context["previous_steps"].get("download_video", {}).get("file_path", "")
    logger.info(f"[extract_audio] from={video_path}")
    # TODO: ffmpeg 提取音频
    return {"status": "extracted", "audio_path": ""}


def _handle_transcribe_content(context: dict) -> dict:
    """语音转文字"""
    logger.info(f"[transcribe_content] content={context['content_id']}")
    # TODO: Whisper / ASR, 优先读取字幕文件, 无字幕则 ASR
    return {"status": "transcribed", "text": ""}


def _handle_translate_content(context: dict) -> dict:
    """文章翻译"""
    config = context["step_config"]
    target_lang = config.get("target_language", "zh")
    logger.info(f"[translate_content] target={target_lang}, content={context['content_id']}")
    # TODO: LLM 翻译 → 更新 content.processed_content
    return {"status": "translated", "target_language": target_lang}


def _handle_analyze_content(context: dict) -> dict:
    """模型分析"""
    config = context["step_config"]
    model = config.get("model")
    prompt_template_id = config.get("prompt_template_id")
    logger.info(f"[analyze_content] model={model}, prompt={prompt_template_id}")
    # TODO: LLMAnalyzer.analyze() → 更新 content.analysis_result
    return {"status": "analyzed"}


def _handle_publish_content(context: dict) -> dict:
    """消息推送"""
    config = context["step_config"]
    channel = config.get("channel", "none")
    if channel == "none":
        return {"status": "skipped", "reason": "channel=none"}
    logger.info(f"[publish_content] channel={channel}, content={context['content_id']}")
    # TODO: Publisher.publish()
    return {"status": "published", "channel": channel}


# step_type → handler
STEP_HANDLERS = {
    "enrich_content": _handle_enrich_content,
    "download_video": _handle_download_video,
    "extract_audio": _handle_extract_audio,
    "transcribe_content": _handle_transcribe_content,
    "translate_content": _handle_translate_content,
    "analyze_content": _handle_analyze_content,
    "publish_content": _handle_publish_content,
}
