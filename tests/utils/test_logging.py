import logging

import pytest

from app.utils import configure_logging, get_logger


def test_configure_logging_sets_root_log_level():
    # 验证日志初始化会设置根 logger 的级别。
    configure_logging("DEBUG")

    assert logging.getLogger().level == logging.DEBUG


def test_get_logger_returns_named_logger():
    # 验证可以按名称获取指定 logger。
    logger = get_logger("app.test")

    assert logger.name == "app.test"


def test_configure_logging_rejects_invalid_level():
    # 验证非法日志级别会被显式拒绝。
    with pytest.raises(ValueError, match="Invalid log level"):
        configure_logging("NOPE")
