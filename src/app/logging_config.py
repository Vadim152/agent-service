"""Настройка логирования для приложения."""
from __future__ import annotations

import logging
from logging import Logger

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_LEVEL = logging.INFO


def init_logging() -> None:
    """Инициализировать логирование для приложения и Uvicorn."""

    logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, handlers=[logging.StreamHandler()])
    logging.getLogger("uvicorn").setLevel(LOG_LEVEL)
    logging.getLogger("uvicorn.error").setLevel(LOG_LEVEL)
    logging.getLogger("uvicorn.access").setLevel(LOG_LEVEL)


def get_logger(name: str) -> Logger:
    """Получить настроенный логгер по имени."""

    return logging.getLogger(name)
