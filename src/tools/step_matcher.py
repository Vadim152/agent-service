"""Сопоставление шагов тесткейса с известными cucumber-определениями."""
from __future__ import annotations

import difflib
import re
from typing import Any, Iterable

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
        step_boosts: dict[str, float] | None = None,
    ) -> list[MatchedStep]:
        """Сопоставляет список шагов тесткейса с существующими cucumber-шагами."""

        matches: list[MatchedStep] = []
        for test_step in test_steps:
            best_def, score, confidence_sources, llm_reranked = self._find_best_match(
                test_step.text,
                step_definitions,
                project_root=project_root,
                step_boosts=step_boosts,
            )
            status = self._derive_status(score)
            resolved_step_text: str | None = None
            matched_parameters: list[dict[str, Any]] = []
            parameter_fill_meta: dict[str, Any] | None = None
            notes: dict[str, Any] = {
                "confidence_sources": confidence_sources,
                "final_score": score,
            }

            if llm_reranked:
                notes["llm_reranked"] = True

            if status is MatchStatus.UNMATCHED:
                notes.update(
                    {
                        "reason": "no_definition_found",
                        "original_text": test_step.text,
                        "closest_pattern": best_def.pattern if best_def else None,
                        "confidence": f"{score:.2f}",
                    }
                )
            else:
                if best_def:
                    (
                        resolved_step_text,
                        matched_parameters,
                        parameter_fill_meta,
                    ) = self._resolve_step_text(best_def, test_step.text)
                    notes["parameter_fill"] = parameter_fill_meta

            matches.append(
                MatchedStep(
                    test_step=test_step,
                    status=status,
                    step_definition=best_def if status is not MatchStatus.UNMATCHED else None,
                    confidence=score if best_def else None,
                    generated_gherkin_line=None,
                    resolved_step_text=resolved_step_text,
                    matched_parameters=matched_parameters,
                    parameter_fill_meta=parameter_fill_meta,
                    notes=notes,
                )
            )
        return matches

    def _find_best_match(
        self,
        test_text: str,
        step_definitions: Iterable[StepDefinition],
        project_root: str | None = None,
        step_boosts: dict[str, float] | None = None,
    ) -> tuple[StepDefinition | None, float, dict[str, float], bool]:
        """Находит наиболее похожее определение шага с учётом эмбеддингов и LLM."""

        normalized_test = self._normalize(test_text)
        candidates = list(step_definitions)
        embedding_scores: dict[str, float] = {}
        parameter_fit_scores: dict[str, float] = {}
        step_boosts = step_boosts or {}

        if self.embeddings_store and project_root:
            try:
                if hasattr(self.embeddings_store, "get_top_k"):
                    embedded = self.embeddings_store.get_top_k(
                        project_root, normalized_test, top_k=20
                    )
                else:
                    embedded = [
                        (definition, 0.0)
                        for definition in self.embeddings_store.search_similar(
                            project_root, normalized_test, top_k=20
                        )
                    ]
                if embedded:
                    embedding_scores = {definition.id: score for definition, score in embedded}
            except Exception:
                candidates = list(step_definitions)

        if not candidates:
            return None, 0.0, {
                "sequence": 0.0,
                "embedding": 0.0,
                "llm": 0.0,
            }, False

        best_def: StepDefinition | None = None
        best_score = 0.0
        similarity_scores: dict[str, float] = {}

        for definition in candidates:
            candidate_text = self._normalize(definition.pattern)
            score = difflib.SequenceMatcher(None, normalized_test, candidate_text).ratio()
            similarity_scores[definition.id] = score
            parameter_fit = self._estimate_parameter_fit(definition, test_text)
            parameter_fit_scores[definition.id] = parameter_fit
            combined = self._combine_score(
                score,
                embedding_scores.get(definition.id),
                boost=step_boosts.get(definition.id),
                parameter_fit=parameter_fit,
            )
            if combined > best_score:
                best_score = combined
                best_def = definition

        llm_reranked = False
        if self.llm_client and best_def:
            best_def, best_score, llm_reranked = self._rerank_with_llm(
                test_text,
                candidates,
                similarity_scores,
                embedding_scores,
                parameter_fit_scores,
                best_def,
                best_score,
            )

        sequence_score = (
            similarity_scores.get(best_def.id, 0.0) if best_def else 0.0
        )
        embedding_score = embedding_scores.get(best_def.id, 0.0) if best_def else 0.0
        learned_boost = step_boosts.get(best_def.id, 0.0) if best_def else 0.0
        parameter_fit = parameter_fit_scores.get(best_def.id, 0.0) if best_def else 0.0
        confidence_sources = {
            "sequence": sequence_score,
            "embedding": embedding_score,
            "parameter_fit": parameter_fit,
            "llm": 1.0 if llm_reranked else 0.0,
        }
        if abs(learned_boost) > 1e-9:
            confidence_sources["learned_boost"] = learned_boost

        return best_def, best_score, confidence_sources, llm_reranked

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
        """Формирует шаблон шага с подстановкой параметров без ключевого слова."""

        if not definition:
            return ""

        resolved, _, _ = self._resolve_step_text(definition, test_step.text)
        return resolved or definition.pattern

    def _combine_score(
        self,
        sequence_score: float,
        embedding_score: float | None = None,
        llm_confirmed: bool = False,
        boost: float | None = None,
        parameter_fit: float | None = None,
    ) -> float:
        """Объединяет метрики строкового сходства, эмбеддингов и LLM в итоговый confidence."""

        weights: list[tuple[float, float]] = [(sequence_score, 0.6)]
        if embedding_score is not None:
            weights.append((embedding_score, 0.25))
        if parameter_fit is not None:
            weights.append((parameter_fit, 0.15))
        if llm_confirmed:
            weights.append((1.0, 0.15))

        total_weight = sum(weight for _, weight in weights)
        if total_weight == 0:
            return 0.0

        combined = sum(score * weight for score, weight in weights) / total_weight
        if boost is not None:
            combined += boost
        return max(0.0, min(1.0, combined))

    def _rerank_with_llm(
        self,
        test_text: str,
        candidates: list[StepDefinition],
        similarity_scores: dict[str, float],
        embedding_scores: dict[str, float],
        parameter_fit_scores: dict[str, float],
        current_best: StepDefinition,
        current_score: float,
    ) -> tuple[StepDefinition, float, bool]:
        """Использует LLM для подтверждения/выбора лучшего кандидата."""

        short_list = sorted(
            candidates,
            key=lambda c: self._combine_score(
                similarity_scores.get(c.id, 0.0),
                embedding_scores.get(c.id),
                parameter_fit=parameter_fit_scores.get(c.id),
            ),
            reverse=True,
        )[:3]

        prompt = self._build_llm_prompt(test_text, short_list)
        response = self.llm_client.generate(prompt)
        chosen = self._extract_llm_choice(response, short_list)
        llm_reranked = bool(chosen)

        if not chosen:
            return current_best, current_score, False

        if chosen.id == current_best.id:
            boosted = self._combine_score(
                similarity_scores.get(chosen.id, 0.0),
                embedding_scores.get(chosen.id),
                llm_confirmed=True,
                parameter_fit=parameter_fit_scores.get(chosen.id),
            )
            return chosen, boosted, llm_reranked

        combined = self._combine_score(
            similarity_scores.get(chosen.id, 0.0),
            embedding_scores.get(chosen.id),
            llm_confirmed=True,
            parameter_fit=parameter_fit_scores.get(chosen.id),
        )
        return chosen, combined, llm_reranked

    def _estimate_parameter_fit(self, definition: StepDefinition, test_text: str) -> float:
        placeholders = self._extract_placeholders(definition.pattern)
        if not placeholders:
            return 1.0

        _, _, meta = self._resolve_step_text(definition, test_text, allow_fallback=False)
        status = str((meta or {}).get("status", "none")).casefold()
        if status == "full":
            return 1.0
        if status == "partial":
            return 0.5
        return 0.0

    def _resolve_step_text(
        self, definition: StepDefinition, test_text: str, *, allow_fallback: bool = True
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        pattern = definition.pattern
        placeholders = self._extract_placeholders(pattern)
        sources: list[str] = []
        best_partial: tuple[str, list[dict[str, Any]], dict[str, Any]] | None = None

        regex_attempt = self._resolve_with_regex(definition, test_text, placeholders)
        if regex_attempt:
            resolved, params, status = regex_attempt
            meta = self._build_fill_meta(
                status=status,
                source="regex_strict",
                source_chain=["regex_strict"],
                placeholders=placeholders,
                matched_parameters=params,
            )
            if status == "full":
                return resolved, params, meta
            best_partial = (resolved, params, meta)
            sources.append("regex_strict")

        if placeholders:
            values = self._extract_values_by_literal_alignment(pattern, test_text)
            if values:
                resolved = self._replace_placeholders(pattern, values)
                params = self._build_parameter_payload(
                    definition, placeholders, values, source="cucumber_alignment"
                )
                status = "full" if not self._has_placeholders(resolved) else "partial"
                meta = self._build_fill_meta(
                    status=status,
                    source="cucumber_alignment",
                    source_chain=sources + ["cucumber_alignment"],
                    placeholders=placeholders,
                    matched_parameters=params,
                )
                if status == "full":
                    return resolved, params, meta
                best_partial = best_partial or (resolved, params, meta)
                sources.append("cucumber_alignment")

            values = self._extract_values_from_quotes(test_text, placeholders)
            if values:
                resolved = self._replace_placeholders(pattern, values)
                params = self._build_parameter_payload(
                    definition, placeholders, values, source="quoted_values"
                )
                status = "full" if not self._has_placeholders(resolved) else "partial"
                meta = self._build_fill_meta(
                    status=status,
                    source="quoted_values",
                    source_chain=sources + ["quoted_values"],
                    placeholders=placeholders,
                    matched_parameters=params,
                )
                if status == "full":
                    return resolved, params, meta
                best_partial = best_partial or (resolved, params, meta)
                sources.append("quoted_values")

        if not allow_fallback:
            if best_partial:
                return best_partial
            return pattern, [], self._build_fill_meta(
                status="none",
                source="none",
                source_chain=sources,
                placeholders=placeholders,
                matched_parameters=[],
                reason="no_parameter_extraction",
            )

        if best_partial:
            _, _, partial_meta = best_partial
            fallback_meta = self._build_fill_meta(
                status="fallback",
                source="source_text_fallback",
                source_chain=list(partial_meta.get("sourceChain", [])) + ["source_text_fallback"],
                placeholders=placeholders,
                matched_parameters=[],
                reason="partial_parameter_extraction_fallback",
            )
            return test_text.strip(), [], fallback_meta

        fallback_meta = self._build_fill_meta(
            status="fallback",
            source="source_text_fallback",
            source_chain=sources + ["source_text_fallback"],
            placeholders=placeholders,
            matched_parameters=[],
            reason="no_parameter_extraction",
        )
        return test_text.strip(), [], fallback_meta

    def _resolve_with_regex(
        self,
        definition: StepDefinition,
        test_text: str,
        placeholders: list[str],
    ) -> tuple[str, list[dict[str, Any]], str] | None:
        regex = definition.regex
        if not regex:
            return None
        try:
            match = re.search(regex, test_text)
        except re.error:
            return None
        if not match:
            return None

        groups = [self._clean_value(value) for value in match.groups()]
        if definition.pattern_type.value == "regularExpression":
            params = self._build_parameter_payload(
                definition, placeholders, groups, source="regex_strict"
            )
            return test_text.strip(), params, "full"

        if not placeholders:
            return definition.pattern, [], "full"

        resolved = self._replace_placeholders(definition.pattern, groups)
        params = self._build_parameter_payload(
            definition, placeholders, groups, source="regex_strict"
        )
        status = "full" if not self._has_placeholders(resolved) else "partial"
        return resolved, params, status

    @staticmethod
    def _extract_placeholders(pattern: str) -> list[str]:
        return re.findall(r"\{[^}]+\}", pattern)

    @staticmethod
    def _has_placeholders(text: str) -> bool:
        return bool(re.search(r"\{[^}]+\}", text))

    def _replace_placeholders(self, pattern: str, values: list[str]) -> str:
        filled = pattern
        for placeholder, value in zip(self._extract_placeholders(pattern), values):
            filled = filled.replace(placeholder, self._clean_value(value), 1)
        return filled

    def _build_parameter_payload(
        self,
        definition: StepDefinition,
        placeholders: list[str],
        values: list[str],
        *,
        source: str,
    ) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        max_len = max(len(placeholders), len(values), len(definition.parameters))
        for idx in range(max_len):
            param_def = definition.parameters[idx] if idx < len(definition.parameters) else None
            placeholder = (
                placeholders[idx]
                if idx < len(placeholders)
                else (param_def.placeholder if param_def else None)
            )
            value = self._clean_value(values[idx]) if idx < len(values) else None
            name = param_def.name if param_def else f"arg{idx + 1}"
            payload.append(
                {
                    "name": name,
                    "type": param_def.type if param_def else None,
                    "placeholder": placeholder,
                    "value": value,
                    "source": source,
                }
            )
        return payload

    def _build_fill_meta(
        self,
        *,
        status: str,
        source: str,
        source_chain: list[str],
        placeholders: list[str],
        matched_parameters: list[dict[str, Any]],
        reason: str | None = None,
    ) -> dict[str, Any]:
        filled_placeholders = {
            str(param.get("placeholder"))
            for param in matched_parameters
            if param.get("placeholder") and param.get("value") not in (None, "")
        }
        missing = [placeholder for placeholder in placeholders if placeholder not in filled_placeholders]
        meta: dict[str, Any] = {
            "status": status,
            "source": source,
            "sourceChain": source_chain,
            "missingPlaceholders": missing,
        }
        if reason:
            meta["reason"] = reason
        return meta

    def _extract_values_by_literal_alignment(self, pattern: str, text: str) -> list[str]:
        placeholders = self._extract_placeholders(pattern)
        if not placeholders:
            return []

        literals = re.split(r"\{[^}]+\}", pattern)
        if len(literals) != len(placeholders) + 1:
            return []

        lowered_text = text.casefold()
        cursor = 0
        values: list[str] = []

        for idx in range(len(placeholders)):
            left = literals[idx]
            right = literals[idx + 1]

            if left:
                left_pos = lowered_text.find(left.casefold(), cursor)
                if left_pos < 0:
                    return []
                cursor = left_pos + len(left)

            if right:
                right_pos = lowered_text.find(right.casefold(), cursor)
                if right_pos < 0:
                    return []
                raw_value = text[cursor:right_pos]
                cursor = right_pos
            else:
                raw_value = text[cursor:]
                cursor = len(text)

            cleaned = self._clean_value(raw_value)
            if not cleaned:
                return []
            values.append(cleaned)

        return values

    def _extract_values_from_quotes(self, text: str, placeholders: list[str]) -> list[str]:
        if not placeholders:
            return []

        quoted_values = [
            self._clean_value(match.group(1) or match.group(2) or match.group(3))
            for match in re.finditer(r'"([^"]+)"|\'([^\']+)\'|«([^»]+)»', text)
        ]
        numeric_values = re.findall(r"-?\d+(?:[.,]\d+)?", text)

        result: list[str] = []
        quoted_idx = 0
        numeric_idx = 0
        for placeholder in placeholders:
            placeholder_type = placeholder.strip("{} ").casefold()
            if placeholder_type in {"int", "integer", "float", "double", "byte", "short", "long", "bigdecimal"}:
                if numeric_idx < len(numeric_values):
                    result.append(self._clean_value(numeric_values[numeric_idx]))
                    numeric_idx += 1
                    continue
            if quoted_idx < len(quoted_values):
                result.append(self._clean_value(quoted_values[quoted_idx]))
                quoted_idx += 1
                continue
            break
        return result

    @staticmethod
    def _clean_value(value: Any) -> str:
        cleaned = "" if value is None else str(value).strip()
        if len(cleaned) >= 2:
            wrappers = {('"', '"'), ("'", "'"), ("«", "»")}
            for left, right in wrappers:
                if cleaned.startswith(left) and cleaned.endswith(right):
                    cleaned = cleaned[1:-1].strip()
        return cleaned

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
