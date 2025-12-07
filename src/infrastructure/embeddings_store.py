"""Абстракция векторного хранилища для шагов.

EmbeddingsStore будет отвечать за построение и поиск по эмбеддинговому индексу
для cucumber-шагов. Текущая реализация оставлена в виде заглушек, чтобы позднее
подключить конкретный движок (faiss/chroma/qdrant и т.д.).
"""

from __future__ import annotations

from typing import List

from domain.models import StepDefinition


class EmbeddingsStore:
    """Слой работы с векторным хранилищем."""

    def index_steps(self, project_root: str, steps: list[StepDefinition]) -> None:
        """Построить или обновить индекс эмбеддингов для проекта."""

        # TODO: интегрировать конкретный движок векторного поиска
        return None

    def search_similar(self, project_root: str, query: str, top_k: int = 5) -> List[StepDefinition]:
        """Возвращает наиболее похожие шаги по текстовому запросу."""

        # TODO: добавить семантический поиск по эмбеддингам
        return []

    def clear(self, project_root: str) -> None:
        """Очищает индекс эмбеддингов для указанного проекта."""

        # TODO: реализовать удаление данных из выбранного хранилища
        return None

