"""日志工具模块。

提供统一的日志配置和获取接口，基于 Python 标准库 logging 模块。
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


# 默认日志格式
DEFAULT_FORMAT = (
    "[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s"
)
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 日志文件配置
DEFAULT_LOG_DIR = Path("logs")
DEFAULT_LOG_FILE = "launcher.log"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10MB
DEFAULT_BACKUP_COUNT = 5

_loggers: dict[str, logging.Logger] = {}
_initialized: bool = False


def setup_logging(
    log_dir: Optional[Path] = None,
    log_file: str = DEFAULT_LOG_FILE,
    log_level: int = logging.DEBUG,
    console_level: int = logging.INFO,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> None:
    """初始化全局日志配置。

    Args:
        log_dir: 日志文件目录，默认为当前工作目录下的 logs/
        log_file: 日志文件名
        log_level: 文件日志级别
        console_level: 控制台日志级别
        max_bytes: 单个日志文件最大大小
        backup_count: 保留的日志备份数量
    """
    global _initialized

    if _initialized:
        return

    if log_dir is None:
        log_dir = DEFAULT_LOG_DIR

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / log_file

    # 根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 清除已有的 handler（避免重复添加）
    root_logger.handlers.clear()

    # 文件 handler：按大小轮转
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(DEFAULT_FORMAT, DEFAULT_DATE_FORMAT))
    root_logger.addHandler(file_handler)

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter(DEFAULT_FORMAT, DEFAULT_DATE_FORMAT))
    root_logger.addHandler(console_handler)

    _initialized = True

    root_logger.info("日志系统初始化完成，日志文件: %s", log_path)


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的 logger 实例。

    如果日志系统尚未初始化，会自动以默认配置初始化。

    Args:
        name: logger 名称，通常使用 __name__

    Returns:
        logging.Logger 实例
    """
    if name in _loggers:
        return _loggers[name]

    if not _initialized:
        setup_logging()

    logger = logging.getLogger(name)
    _loggers[name] = logger
    return logger


def reset_logging() -> None:
    """重置日志系统（主要用于测试）。"""
    global _initialized
    _loggers.clear()
    logging.getLogger().handlers.clear()
    _initialized = False