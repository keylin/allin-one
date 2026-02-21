"""全局常量 — 消除 magic strings"""

from enum import Enum


# ---- 任务队列 ----

class QueueName:
    PIPELINE = "pipeline"
    SCHEDULED = "scheduled"


# ---- 采集记录状态 (CollectionRecord.status) ----

class CollectionStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ---- 媒体项状态 (MediaItem.status) ----

class MediaStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADED = "downloaded"
    FAILED = "failed"


# ---- 文件扩展名分类 ----

VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv"})
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg"})
