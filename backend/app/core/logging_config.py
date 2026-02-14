"""统一日志配置 — 按进程分文件记录异常，汇总 ERROR 日志"""

import logging
import os
from logging.handlers import RotatingFileHandler

_INITIALIZED = False

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

MAX_BYTES = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5


def setup_logging(process_name: str = "backend") -> None:
    """配置根 logger：控制台 + 进程日志文件 (WARNING+) + 错误汇总文件 (ERROR+)

    Args:
        process_name: 进程标识，决定日志文件名 (backend / worker)
    """
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    from app.core.config import settings

    log_dir = settings.LOG_DIR
    os.makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # 由各 handler 自行过滤级别

    # Console handler — 级别由 LOG_LEVEL 环境变量控制
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    console.setFormatter(formatter)
    root.addHandler(console)

    # 进程日志 handler — WARNING+
    process_handler = RotatingFileHandler(
        os.path.join(log_dir, f"{process_name}.log"),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    process_handler.setLevel(logging.WARNING)
    process_handler.setFormatter(formatter)
    root.addHandler(process_handler)

    # 错误汇总 handler — ERROR+
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, "error.log"),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root.addHandler(error_handler)
