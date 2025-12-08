"""Сопоставление шагов тесткейса с известными cucumber-определениями."""
from __future__ import annotations

import difflib
from typing import Iterable

from domain.enums import MatchStatus, StepKeyword
from domain.models import MatchedStep, StepDefinition, TestStep
from infrastructure.embeddings_store import EmbeddingsStore
from infrastructure.llm_client import LLMClient


class StepMatcher:
    """Базовый матчер шагов с возможностью расширения через LLM и эмбеддинги."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        embeddings_store: EmbeddingsStore | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.embeddings_store = embeddings_store

    def match_steps(
        self,
        test_steps: list[TestStep],
        step_definitions: list[StepDefinition],
    ) -> list[MatchedStep]:
        """Сопоставляет список шагов тесткейса с существующими cucumber-шагами."""

        matches: list[MatchedStep] = []
        for test_step in test_steps:
            best_def, score = self._find_best_match(test_step.text, step_definitions)
            status = self._derive_status(score)
            gherkin_line: str | None = None
            notes: dict[str, str] | None = None

            if status is MatchStatus.UNMATCHED:
                notes = {
                    "reason": "no_definition_found",
                    "original_text": test_step.text,
                    "closest_pattern": best_def.pattern if best_def else None,
                    "confidence": f"{score:.2f}",
                }
            else:
                gherkin_line = self._build_gherkin_line(best_def, test_step)

            matches.append(
                MatchedStep(
                    test_step=test_step,
                    status=status,
                    step_definition=best_def if status is not MatchStatus.UNMATCHED else None,
                    confidence=score if best_def else None,
                    generated_gherkin_line=gherkin_line,
                    notes=notes,
                )
            )
        return matches

    def _find_best_match(
        self, test_text: str, step_definitions: Iterable[StepDefinition]
    ) -> tuple[StepDefinition | None, float]:
        """Находит наиболее похожее определение шага по простому сходству строк."""

        best_def: StepDefinition | None = None
        best_score = 0.0
        normalized_test = self._normalize(test_text)

        for definition in step_definitions:
            candidate_text = self._normalize(definition.pattern)
            score = difflib.SequenceMatcher(None, normalized_test, candidate_text).ratio()
            if score > best_score:
                best_score = score
                best_def = definition

        return best_def, best_score

    @staticmethod
    def _normalize(text: str) -> str:
        """Нормализует текст для сравнения."""

        return " ".join(text.lower().strip().split())

    @staticmethod
    def _derive_status(score: float) -> MatchStatus:
        """Определяет статус сопоставления на основе порогов сходства."""

        if score >= 0.9:
            return MatchStatus.EXACT
        if score >= 0.6:
            return MatchStatus.FUZZY
        return MatchStatus.UNMATCHED

    def _build_gherkin_line(self, definition: StepDefinition, test_step: TestStep) -> str:
        """Формирует строку Gherkin для найденного определения."""

        keyword = definition.keyword.value if isinstance(definition.keyword, StepKeyword) else str(definition.keyword)
        return f"{keyword} {definition.pattern}" if definition else ""
