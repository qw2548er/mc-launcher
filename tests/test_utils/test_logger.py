"""日志模块单元测试。"""

import logging
import os
import tempfile
from pathlib import Path

import pytest

from src.utils.logger import get_logger, reset_logging, setup_logging


class TestLogger:
    """日志工具测试。"""

    def test_setup_logging_creates_log_file(self):
        """测试初始化日志系统会创建日志文件。"""
        reset_logging()
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            setup_logging(log_dir=log_dir, log_file="test.log")

            log_path = log_dir / "test.log"
            assert log_path.exists(), "日志文件应被创建"

    def test_get_logger_returns_logger(self):
        """测试 get_logger 返回 Logger 实例。"""
        reset_logging()
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

    def test_get_logger_caches(self):
        """测试相同名称的 logger 会被缓存。"""
        reset_logging()
        logger1 = get_logger("test_cache")
        logger2 = get_logger("test_cache")
        assert logger1 is logger2, "相同名称的 logger 应被缓存"

    def test_get_logger_auto_initializes(self):
        """测试未初始化时自动初始化。"""
        reset_logging()
        logger = get_logger("auto_init")
        assert logger is not None

    def test_setup_logging_idempotent(self):
        """测试重复初始化不会重复添加 handler。"""
        reset_logging()
        setup_logging()
        handler_count = len(logging.getLogger().handlers)
        setup_logging()
        assert len(logging.getLogger().handlers) == handler_count