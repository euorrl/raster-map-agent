import logging


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(level: str = "INFO") -> None:
    log_level = _parse_log_level(level)
    logging.basicConfig(level=log_level, format=LOG_FORMAT, force=True)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def _parse_log_level(level: str) -> int:
    normalized_level = level.upper()
    log_level = getattr(logging, normalized_level, None)

    if not isinstance(log_level, int):
        raise ValueError(f"Invalid log level: {level}")

    return log_level
