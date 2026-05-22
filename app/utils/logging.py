import logging


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """配置应用日志。

    Args:
        level: 日志级别名称，例如 ``DEBUG``、``INFO`` 或 ``WARNING``。

    Raises:
        ValueError: 当 ``level`` 不是合法 Python 日志级别时抛出。
    """

    log_level = _parse_log_level(level)
    logging.basicConfig(level=log_level, format=LOG_FORMAT, force=True)


def get_logger(name: str) -> logging.Logger:
    """返回指定名称的模块 logger。

    Args:
        name: Logger 名称。调用方通常传入 ``__name__``。

    Returns:
        标准库 logging 提供的指定名称 logger。
    """

    return logging.getLogger(name)


def _parse_log_level(level: str) -> int:
    normalized_level = level.upper()
    log_level = getattr(logging, normalized_level, None)

    if not isinstance(log_level, int):
        raise ValueError(f"Invalid log level: {level}")

    return log_level
