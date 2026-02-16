"""Pipeline step handlers registry.

All step handler functions are gathered from their individual modules
and exposed via the ``STEP_HANDLERS`` dictionary.
"""

from app.services.pipeline.steps.extract_content import _handle_extract_content
from app.services.pipeline.steps.enrich_content import _handle_enrich_content
from app.services.pipeline.steps.extract_audio import _handle_extract_audio
from app.services.pipeline.steps.transcribe import _handle_transcribe_content
from app.services.pipeline.steps.translate import _handle_translate_content
from app.services.pipeline.steps.analyze import _handle_analyze_content
from app.services.pipeline.steps.publish import _handle_publish_content
from app.services.pipeline.steps.localize_media import _handle_localize_media

# step_type → handler
STEP_HANDLERS = {
    "extract_content": _handle_extract_content,
    "enrich_content": _handle_enrich_content,
    "extract_audio": _handle_extract_audio,
    "transcribe_content": _handle_transcribe_content,
    "translate_content": _handle_translate_content,
    "analyze_content": _handle_analyze_content,
    "publish_content": _handle_publish_content,
    "localize_media": _handle_localize_media,
}
