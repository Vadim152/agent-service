"""Перечисления, описывающие основные типы доменной модели."""
from __future__ import annotations

from enum import Enum


class StepKeyword(str, Enum):
    """Ключевые слова Gherkin/Cucumber для шагов сценария."""

    GIVEN = "Given"
    WHEN = "When"
    THEN = "Then"
    AND = "And"
    BUT = "But"

    def as_text(self) -> str:
        """Возвращает строковое представление ключевого слова."""
        return self.value


class MatchStatus(str, Enum):
    """Статусы сопоставления шага тесткейса с cucumber-описанием."""

    EXACT = "exact"
    FUZZY = "fuzzy"
    UNMATCHED = "unmatched"

    @property
    def requires_manual_review(self) -> bool:
        """Показывает, требуется ли ручная проверка человека."""
        return self is not MatchStatus.EXACT
