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

    def as_text(self, language: str | None = None) -> str:
        """Возвращает строковое представление ключевого слова."""

        if language and language.casefold() == "ru":
            localized = {
                StepKeyword.GIVEN: "Дано",
                StepKeyword.WHEN: "Когда",
                StepKeyword.THEN: "Тогда",
                StepKeyword.AND: "И",
                StepKeyword.BUT: "Но",
            }
            return localized[self]
        return self.value

    @classmethod
    def _alias_map(cls) -> dict[str, "StepKeyword"]:
        """Возвращает соответствие всех поддерживаемых написаний к каноническим ключевым словам."""

        aliases: dict[str, StepKeyword] = {kw.value.casefold(): kw for kw in cls}
        aliases.update(
            {
                # Русские варианты Given
                "дано": cls.GIVEN,
                "пусть": cls.GIVEN,
                "допустим": cls.GIVEN,
                # Русские варианты When
                "когда": cls.WHEN,
                "если": cls.WHEN,
                # Русские варианты Then
                "тогда": cls.THEN,
                "то": cls.THEN,
                # Русские варианты And
                "и": cls.AND,
                # Русские варианты But
                "но": cls.BUT,
                "а": cls.BUT,
            }
        )
        return aliases

    @classmethod
    def from_string(cls, keyword: str) -> "StepKeyword":
        """Преобразует строку с ключевым словом шага в каноническое перечисление.

        Поддерживаются английские и русские варианты Gherkin. Регистр не имеет значения.
        """

        normalized = keyword.strip().casefold()
        if not normalized:
            raise ValueError("Keyword cannot be empty")

        try:
            return cls._alias_map()[normalized]
        except KeyError as error:
            raise ValueError(f"Unsupported step keyword: {keyword}") from error

    @classmethod
    def supported_keywords(cls) -> set[str]:
        """Возвращает множество всех поддерживаемых написаний ключевых слов."""

        return set(cls._alias_map().keys())


class MatchStatus(str, Enum):
    """Статусы сопоставления шага тесткейса с cucumber-описанием."""

    EXACT = "exact"
    FUZZY = "fuzzy"
    UNMATCHED = "unmatched"

    @property
    def requires_manual_review(self) -> bool:
        """Показывает, требуется ли ручная проверка человека."""
        return self is not MatchStatus.EXACT


class StepPatternType(str, Enum):
    """Тип паттерна шага (регулярка или выражение Cucumber)."""

    CUCUMBER_EXPRESSION = "cucumberExpression"
    REGULAR_EXPRESSION = "regularExpression"
