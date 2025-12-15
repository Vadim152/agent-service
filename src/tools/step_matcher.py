"""Сопоставление шагов тесткейса с известными cucumber-определениями."""
from __future__ import annotations

import difflib
import re
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
        project_root: str | None = None,
    ) -> list[MatchedStep]:
        """Сопоставляет список шагов тесткейса с существующими cucumber-шагами."""

        matches: list[MatchedStep] = []
        for test_step in test_steps:
            best_def, score = self._find_best_match(
                test_step.text, step_definitions, project_root=project_root
            )
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
        self,
        test_text: str,
        step_definitions: Iterable[StepDefinition],
        project_root: str | None = None,
    ) -> tuple[StepDefinition | None, float]:
        """Находит наиболее похожее определение шага с учётом эмбеддингов и LLM."""

        normalized_test = self._normalize(test_text)
        candidates = list(step_definitions)
        embedding_scores: dict[str, float] = {}

        if self.embeddings_store and project_root:
            try:
                if hasattr(self.embeddings_store, "get_top_k"):
                    embedded = self.embeddings_store.get_top_k(
                        project_root, normalized_test, top_k=5
                    )
                else:
                    embedded = [
                        (definition, 0.0)
                        for definition in self.embeddings_store.search_similar(
                            project_root, normalized_test, top_k=5
                        )
                    ]
                if embedded:
                    candidates = [definition for definition, _ in embedded]
                    embedding_scores = {definition.id: score for definition, score in embedded}
            except Exception:
                candidates = list(step_definitions)

        if not candidates:
            return None, 0.0

        best_def: StepDefinition | None = None
        best_score = 0.0
        similarity_scores: dict[str, float] = {}

        for definition in candidates:
            candidate_text = self._normalize(definition.pattern)
            score = difflib.SequenceMatcher(None, normalized_test, candidate_text).ratio()
            similarity_scores[definition.id] = score
            combined = self._combine_score(score, embedding_scores.get(definition.id))
            if combined > best_score:
                best_score = combined
                best_def = definition

        if self.llm_client and best_def:
            best_def, best_score = self._rerank_with_llm(
                test_text,
                candidates,
                similarity_scores,
                embedding_scores,
                best_def,
                best_score,
            )

        return best_def, best_score

    @staticmethod
    def _normalize(text: str) -> str:
        """Нормализует текст для сравнения."""

        return " ".join(text.lower().strip().split())

    @staticmethod
    def _derive_status(score: float) -> MatchStatus:
        """Определяет статус сопоставления на основе комбинированного скоринга."""

        if score >= 0.8:
            return MatchStatus.EXACT
        if score >= 0.5:
            return MatchStatus.FUZZY
        return MatchStatus.UNMATCHED

    def _build_gherkin_line(self, definition: StepDefinition, test_step: TestStep) -> str:
        """Формирует строку Gherkin для найденного определения с подстановкой параметров."""

        if not definition:
            return ""

        keyword = (
            definition.keyword.value
            if isinstance(definition.keyword, StepKeyword)
            else str(definition.keyword)
        )
        pattern = definition.pattern
        regex = definition.regex or pattern

        filled_pattern = pattern
        try:
            match = re.search(regex, test_step.text)
        except re.error:
            match = None

        if match:
            groups = match.groups()
            placeholders = re.findall(r"\{[^}]+\}", pattern)

            if groups and placeholders:
                for placeholder, value in zip(placeholders, groups):
                    filled_pattern = filled_pattern.replace(placeholder, value, 1)
            elif groups:
                filled_pattern = " ".join([pattern] + list(groups))

        return f"{keyword} {filled_pattern}"

    def _combine_score(
        self,
        sequence_score: float,
        embedding_score: float | None = None,
        llm_confirmed: bool = False,
    ) -> float:
        """Объединяет метрики строкового сходства, эмбеддингов и LLM в итоговый confidence."""

        weights: list[tuple[float, float]] = [(sequence_score, 0.6)]
        if embedding_score is not None:
            weights.append((embedding_score, 0.25))
        if llm_confirmed:
            weights.append((1.0, 0.15))

        total_weight = sum(weight for _, weight in weights)
        if total_weight == 0:
            return 0.0

        return sum(score * weight for score, weight in weights) / total_weight

    def _rerank_with_llm(
        self,
        test_text: str,
        candidates: list[StepDefinition],
        similarity_scores: dict[str, float],
        embedding_scores: dict[str, float],
        current_best: StepDefinition,
        current_score: float,
    ) -> tuple[StepDefinition, float]:
        """Использует LLM для подтверждения/выбора лучшего кандидата."""

        short_list = sorted(
            candidates,
            key=lambda c: self._combine_score(
                similarity_scores.get(c.id, 0.0), embedding_scores.get(c.id)
            ),
            reverse=True,
        )[:3]

        prompt = self._build_llm_prompt(test_text, short_list)
        response = self.llm_client.generate(prompt)
        chosen = self._extract_llm_choice(response, short_list)

        if not chosen:
            return current_best, current_score

        if chosen.id == current_best.id:
            boosted = self._combine_score(
                similarity_scores.get(chosen.id, 0.0),
                embedding_scores.get(chosen.id),
                llm_confirmed=True,
            )
            return chosen, boosted

        combined = self._combine_score(
            similarity_scores.get(chosen.id, 0.0),
            embedding_scores.get(chosen.id),
            llm_confirmed=True,
        )
        return chosen, combined

    @staticmethod
    def _build_llm_prompt(test_text: str, candidates: list[StepDefinition]) -> str:
        """Готовит промпт для выбора лучшего шага."""

        lines = [
            "Выбери лучший cucumber-шаг, который соответствует тестовому шагу.",
            "Ответь только идентификатором кандидата (например, C1).",
            f"Тестовый шаг: {test_text}",
            "Кандидаты:",
        ]
        for idx, candidate in enumerate(candidates, start=1):
            keyword = candidate.keyword.value if isinstance(candidate.keyword, StepKeyword) else str(candidate.keyword)
            lines.append(f"C{idx}: [{keyword}] {candidate.pattern}")

        return "\n".join(lines)

    @staticmethod
    def _extract_llm_choice(
        response: str | None, candidates: list[StepDefinition]
    ) -> StepDefinition | None:
        """Извлекает выбор LLM из ответа."""

        if not response:
            return None

        lookup = {f"C{idx}": candidate for idx, candidate in enumerate(candidates, start=1)}
        for token, candidate in lookup.items():
            if token in response:
                return candidate

        lowered_response = response.casefold()
        for candidate in candidates:
            if candidate.pattern.casefold() in lowered_response:
                return candidate

        return None
