"""Logging helpers shared by scheduling services."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from server.common.timezone import get_timezone


class TimezoneFormatter(logging.Formatter):
    """Logging formatter that respects configured timezone."""

    def converter(self, timestamp: float):
        return datetime.fromtimestamp(timestamp, get_timezone()).timetuple()


def setup_logger(
    name: str = "service",
    log_file: str | None = None,
    history_log_file: str | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Create a console/file logger with timezone-aware timestamps."""

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    logger.handlers.clear()

    formatter = TimezoneFormatter(
        "%(asctime)s | %(name)-15s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if history_log_file:
        history_path = Path(history_log_file)
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_handler = logging.FileHandler(history_log_file, mode="a")
        history_handler.setLevel(level)
        history_handler.setFormatter(formatter)
        logger.addHandler(history_handler)

    return logger


__all__ = ["TimezoneFormatter", "setup_logger"]
