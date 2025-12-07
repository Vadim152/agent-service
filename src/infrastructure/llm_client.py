"""Клиент для работы с LLM-провайдером.

LLMClient инкапсулирует операции получения эмбеддингов и генерации текста.
Сейчас это каркас с минимальными сигнатурами, которые будут реализованы позже
через конкретный SDK (Azure OpenAI, OpenAI, Microsoft Agent Framework и т.п.).
"""

from __future__ import annotations

from typing import Any, List


class LLMClient:
    """Унифицированный интерфейс для вызовов LLM."""

    def __init__(self, endpoint: str | None = None, api_key: str | None = None, model_name: str | None = None) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model_name = model_name

    def embed_text(self, text: str) -> List[float]:
        """Возвращает эмбеддинг для одного текста."""

        raise NotImplementedError("embed_text нужно реализовать под выбранного провайдера")

    def embed_texts(self, texts: list[str]) -> List[List[float]]:
        """Возвращает эмбеддинги для списка текстов."""

        raise NotImplementedError("embed_texts нужно реализовать под выбранного провайдера")

    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Генерация текста по заданному промпту."""

        raise NotImplementedError("generate нужно реализовать под выбранного провайдера")

