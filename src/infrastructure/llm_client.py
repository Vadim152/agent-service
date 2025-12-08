"""Клиент для работы с LLM-провайдером.

LLMClient инкапсулирует операции получения эмбеддингов и генерации текста.
Сейчас это каркас с минимальными сигнатурами, которые будут реализованы позже
через конкретный SDK (Azure OpenAI, OpenAI, Microsoft Agent Framework и т.п.).
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, List


class LLMClient:
    """Унифицированный интерфейс для вызовов LLM."""

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        client: Any | None = None,
        allow_fallback: bool = True,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model_name = model_name
        self.client = client
        self.allow_fallback = allow_fallback

    def _ensure_credentials(self) -> None:
        if self.allow_fallback:
            return
        if not self.api_key and not self.client:
            raise RuntimeError("Не заданы учетные данные для LLM провайдера")

    def _fallback_embedding(self, text: str, size: int = 8) -> List[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        for idx in range(size):
            chunk = digest[idx * 4 : (idx + 1) * 4]
            values.append(int.from_bytes(chunk, byteorder="big") / 2**32)
        return values

    def _fallback_generation(self, prompt: str) -> str:
        seed = int.from_bytes(hashlib.sha256(prompt.encode("utf-8")).digest()[:4], "big")
        random.seed(seed)
        suffix = random.choice(["Ответ", "Результат", "Сообщение"])
        return f"{prompt.strip()} :: {suffix}"

    def embed_text(self, text: str) -> List[float]:
        """Возвращает эмбеддинг для одного текста."""

        if self.client:
            return self.client.embed_text(text)

        self._ensure_credentials()
        return self._fallback_embedding(text)

    def embed_texts(self, texts: list[str]) -> List[List[float]]:
        """Возвращает эмбеддинги для списка текстов."""

        if self.client:
            return self.client.embed_texts(texts)

        self._ensure_credentials()
        return [self._fallback_embedding(text) for text in texts]

    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Генерация текста по заданному промпту."""

        if self.client:
            return self.client.generate(prompt, **kwargs)

        self._ensure_credentials()
        return self._fallback_generation(prompt)

