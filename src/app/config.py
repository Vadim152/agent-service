"""Модуль конфигурации приложения."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(ENV_PATH, override=False)


class Settings(BaseSettings):
    """Основные настройки приложения."""

    model_config = SettingsConfigDict(env_prefix="AGENT_SERVICE_", env_file=ENV_PATH, case_sensitive=False)

    app_name: str = Field(default="agent-service", description="Название сервиса")
    api_prefix: str = Field(default="/api/v1", description="Префикс для HTTP API")
    host: str = Field(default="0.0.0.0", description="Хост для запуска приложения")
    port: int = Field(default=8000, description="Порт для запуска приложения")
    steps_index_dir: Path = Field(default=ROOT_DIR / ".agent" / "steps_index", description="Путь к индексу шагов")

    llm_endpoint: str | None = Field(default=None, description="Endpoint LLM сервиса")
    llm_api_key: str | None = Field(default=None, description="API ключ для LLM")
    llm_model: str | None = Field(default=None, description="Идентификатор модели LLM")
    llm_api_version: str | None = Field(default=None, description="Версия API LLM")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Получить настройки приложения с кешированием."""

    settings = Settings()
    logging.getLogger(__name__).debug("Config loaded: %s", settings.model_dump())
    return settings
