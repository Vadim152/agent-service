
"""Step matching between testcase steps and indexed cucumber definitions."""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from domain.enums import MatchStatus, StepKeyword
from domain.models import MatchedStep, StepDefinition, TestStep
from infrastructure.embeddings_store import EmbeddingsStore
from infrastructure.llm_client import LLMClient


@dataclass(slots=True)
class StepMatcherConfig:
    retrieval_top_k: int = 50
    candidate_pool: int = 30
    threshold_exact: float = 0.8
    threshold_fuzzy: float = 0.5
    min_seq_for_exact: float = 0.72
    ambiguity_gap: float = 0.08
    llm_min_score: float = 0.45
    llm_max_score: float = 0.82
    llm_shortlist: int = 5
    llm_min_confidence: float = 0.7
    sequence_weight: float = 0.45
    embedding_weight: float = 0.30
    parameter_fit_weight: float = 0.20
    literal_overlap_weight: float = 0.05
    llm_confirm_weight: float = 0.15
    ranking_version: str = "v2"


class StepMatcher:
    """Step matcher with deterministic ranking and ambiguity-gated LLM rerank."""

    _LEADING_GHERKIN_KEYWORD_RE = re.compile(
        r"^\s*(?P<keyword>Дано|Когда|Тогда|И|Но|Given|When|Then|And|But)\b\s*(?P<text>.+)$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        embeddings_store: EmbeddingsStore | None = None,
        config: StepMatcherConfig | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.embeddings_store = embeddings_store
        self.config = config or StepMatcherConfig()

    def match_steps(
        self,
        test_steps: list[TestStep],
        step_definitions: list[StepDefinition],
        project_root: str | None = None,
        step_boosts: dict[str, float] | None = None,
    ) -> list[MatchedStep]:
        """Matches testcase steps to indexed definitions."""

        matches: list[MatchedStep] = []
        for test_step in test_steps:
            (
                input_leading_keyword,
                match_text,
                input_normalized_for_match,
            ) = self._split_leading_gherkin_keyword(test_step.text)
            (
                best_def,
                score,
                confidence_sources,
                llm_reranked,
                exact_definition_match,
                ranking_meta,
            ) = self._find_best_match(
                match_text,
                step_definitions,
                project_root=project_root,
                step_boosts=step_boosts,
                input_leading_keyword=input_leading_keyword,
            )
            status = self._derive_status(
                score,
                sequence_score=confidence_sources.get("sequence", 0.0),
                parameter_fit=confidence_sources.get("parameter_fit", 0.0),
                definition=best_def,
            )
            resolved_step_text: str | None = None
            matched_parameters: list[dict[str, Any]] = []
            parameter_fill_meta: dict[str, Any] | None = None
            notes: dict[str, Any] = {
                "confidence_sources": confidence_sources,
                "final_score": score,
                "exact_definition_match": exact_definition_match,
                "ranking_version": self.config.ranking_version,
                "candidate_pool_size": ranking_meta.get("candidate_pool_size", 0),
                "ambiguity_gap": ranking_meta.get("ambiguity_gap"),
            }
            if input_leading_keyword:
                notes["inputLeadingKeyword"] = input_leading_keyword
            if input_normalized_for_match:
                notes["inputTextNormalizedForMatch"] = True

            if llm_reranked:
                notes["llm_reranked"] = True
                if ranking_meta.get("llm_choice_confidence") is not None:
                    notes["llm_choice_confidence"] = ranking_meta["llm_choice_confidence"]
                if ranking_meta.get("llm_choice_reason"):
                    notes["llm_choice_reason"] = ranking_meta["llm_choice_reason"]

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
                    ) = self._resolve_step_text(
                        best_def,
                        match_text,
                        original_text=test_step.text,
                    )
                    notes["parameter_fill"] = parameter_fill_meta
                    if self._is_strict_resolution_failed(best_def, parameter_fill_meta):
                        status = MatchStatus.UNMATCHED
                        notes.update(
                            {
                                "reason": "parameter_resolution_failed",
                                "original_text": test_step.text,
                                "closest_pattern": best_def.pattern,
                                "confidence": f"{score:.2f}",
                            }
                        )
                        resolved_step_text = None
                        matched_parameters = []

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
        input_leading_keyword: str | None = None,
    ) -> tuple[StepDefinition | None, float, dict[str, float], bool, bool, dict[str, Any]]:
        """Finds the best step definition with semantic + deterministic ranking."""

        normalized_test = self._normalize(test_text)
        all_candidates = list(step_definitions)
        embedding_scores: dict[str, float] = {}
        parameter_fit_scores: dict[str, float] = {}
        literal_overlap_scores: dict[str, float] = {}
        step_boosts = step_boosts or {}
        ranking_meta: dict[str, Any] = {
            "candidate_pool_size": 0,
            "ambiguity_gap": None,
            "llm_choice_confidence": None,
            "llm_choice_reason": None,
        }

        candidates = list(all_candidates)
        if self.embeddings_store and project_root:
            try:
                if hasattr(self.embeddings_store, "get_top_k"):
                    embedded = self.embeddings_store.get_top_k(
                        project_root,
                        normalized_test,
                        top_k=max(1, self.config.retrieval_top_k),
                    )
                else:
                    embedded = [
                        (definition, 0.0)
                        for definition in self.embeddings_store.search_similar(
                            project_root,
                            normalized_test,
                            top_k=max(1, self.config.retrieval_top_k),
                        )
                    ]
                if embedded:
                    embedding_scores = {definition.id: score for definition, score in embedded}
                    candidates = [definition for definition, _ in embedded]
            except Exception:
                candidates = list(all_candidates)

        candidates = self._prefilter_candidates(candidates, input_leading_keyword)
        ranking_meta["candidate_pool_size"] = len(candidates)
        if not candidates:
            return None, 0.0, {
                "sequence": 0.0,
                "embedding": 0.0,
                "parameter_fit": 0.0,
                "llm": 0.0,
            }, False, False, ranking_meta
        if len(candidates) > self.config.candidate_pool:
            candidates = candidates[: self.config.candidate_pool]
            ranking_meta["candidate_pool_size"] = len(candidates)

        best_def: StepDefinition | None = None
        best_score = 0.0
        best_rank = (-1.0, -1.0, -1.0, -1.0, -1.0)
        similarity_scores: dict[str, float] = {}
        exact_definition_match = False
        ranking_rows: list[tuple[StepDefinition, float]] = []

        for definition in candidates:
            candidate_text = self._normalize(definition.pattern)
            sequence_score = difflib.SequenceMatcher(None, normalized_test, candidate_text).ratio()
            similarity_scores[definition.id] = sequence_score
            parameter_fit = self._estimate_parameter_fit(definition, test_text)
            parameter_fit_scores[definition.id] = parameter_fit
            literal_overlap = self._literal_overlap_score(normalized_test, candidate_text)
            literal_overlap_scores[definition.id] = literal_overlap
            embedding_score = embedding_scores.get(definition.id)
            learned_boost = step_boosts.get(definition.id, 0.0)
            boost_allowed = parameter_fit > 0.0
            exact_match = 1.0 if candidate_text == normalized_test else 0.0
            combined = self._combine_score(
                sequence_score,
                embedding_score,
                boost=learned_boost if boost_allowed else None,
                parameter_fit=parameter_fit,
                literal_overlap=literal_overlap,
            )
            ranking_rows.append((definition, combined))
            rank = (
                exact_match,
                literal_overlap,
                combined,
                sequence_score,
                parameter_fit,
            )
            if rank > best_rank or (rank == best_rank and combined > best_score):
                best_rank = rank
                best_score = combined
                best_def = definition

        ranking_rows.sort(key=lambda item: item[1], reverse=True)
        if len(ranking_rows) >= 2:
            ranking_meta["ambiguity_gap"] = max(0.0, ranking_rows[0][1] - ranking_rows[1][1])
        else:
            ranking_meta["ambiguity_gap"] = 1.0

        llm_reranked = False
        exact_definition_match = best_rank[0] > 0.0
        should_call_llm = (
            self.llm_client is not None
            and best_def is not None
            and not exact_definition_match
            and ranking_meta["ambiguity_gap"] is not None
            and float(ranking_meta["ambiguity_gap"]) < self.config.ambiguity_gap
            and self.config.llm_min_score <= best_score <= self.config.llm_max_score
        )
        if should_call_llm:
            best_def, best_score, llm_reranked, llm_meta = self._rerank_with_llm(
                test_text=test_text,
                ranked_candidates=ranking_rows,
                similarity_scores=similarity_scores,
                embedding_scores=embedding_scores,
                parameter_fit_scores=parameter_fit_scores,
                literal_overlap_scores=literal_overlap_scores,
                current_best=best_def,
                current_score=best_score,
            )
            ranking_meta.update(llm_meta)

        sequence_score = similarity_scores.get(best_def.id, 0.0) if best_def else 0.0
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

        return best_def, best_score, confidence_sources, llm_reranked, exact_definition_match, ranking_meta

    def _prefilter_candidates(
        self,
        candidates: list[StepDefinition],
        input_leading_keyword: str | None,
    ) -> list[StepDefinition]:
        canonical = self._canonicalize_input_keyword(input_leading_keyword)
        if canonical is None or canonical in {StepKeyword.AND, StepKeyword.BUT}:
            return self._dedupe_candidates(candidates)
        allowed = {canonical, StepKeyword.AND, StepKeyword.BUT}
        filtered = [definition for definition in candidates if definition.keyword in allowed]
        return self._dedupe_candidates(filtered or candidates)

    @staticmethod
    def _dedupe_candidates(candidates: list[StepDefinition]) -> list[StepDefinition]:
        seen: set[tuple[str, str]] = set()
        result: list[StepDefinition] = []
        for definition in candidates:
            marker = (definition.keyword.value, " ".join(definition.pattern.casefold().split()))
            if marker in seen:
                continue
            seen.add(marker)
            result.append(definition)
        return result

    @staticmethod
    def _canonicalize_input_keyword(keyword: str | None) -> StepKeyword | None:
        if not keyword:
            return None
        normalized = keyword.strip().casefold()
        mapping = {
            "given": StepKeyword.GIVEN,
            "дано": StepKeyword.GIVEN,
            "when": StepKeyword.WHEN,
            "когда": StepKeyword.WHEN,
            "then": StepKeyword.THEN,
            "тогда": StepKeyword.THEN,
            "and": StepKeyword.AND,
            "и": StepKeyword.AND,
            "but": StepKeyword.BUT,
            "но": StepKeyword.BUT,
        }
        return mapping.get(normalized)

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().strip().split())

    def _derive_status(
        self,
        score: float,
        *,
        sequence_score: float,
        parameter_fit: float,
        definition: StepDefinition | None,
    ) -> MatchStatus:
        if score >= self.config.threshold_exact:
            if sequence_score < self.config.min_seq_for_exact:
                return MatchStatus.FUZZY if score >= self.config.threshold_fuzzy else MatchStatus.UNMATCHED
            if definition and self._requires_full_parameter_fit(definition) and parameter_fit < 1.0:
                return MatchStatus.FUZZY if score >= self.config.threshold_fuzzy else MatchStatus.UNMATCHED
            return MatchStatus.EXACT
        if score >= self.config.threshold_fuzzy:
            return MatchStatus.FUZZY
        return MatchStatus.UNMATCHED

    @staticmethod
    def _requires_full_parameter_fit(definition: StepDefinition) -> bool:
        has_placeholders = bool(re.search(r"\{[^}]+\}", definition.pattern))
        is_regex_pattern = definition.pattern_type.value == "regularExpression"
        return has_placeholders or is_regex_pattern

    def _build_gherkin_line(self, definition: StepDefinition, test_step: TestStep) -> str:
        if not definition:
            return ""

        _, match_text, _ = self._split_leading_gherkin_keyword(test_step.text)
        resolved, _, _ = self._resolve_step_text(
            definition,
            match_text,
            original_text=test_step.text,
        )
        return resolved or definition.pattern

    def _combine_score(
        self,
        sequence_score: float,
        embedding_score: float | None = None,
        llm_confirmed: bool = False,
        boost: float | None = None,
        parameter_fit: float | None = None,
        literal_overlap: float | None = None,
    ) -> float:
        weights: list[tuple[float, float]] = [(sequence_score, self.config.sequence_weight)]
        if embedding_score is not None:
            weights.append((embedding_score, self.config.embedding_weight))
        if parameter_fit is not None:
            weights.append((parameter_fit, self.config.parameter_fit_weight))
        if literal_overlap is not None:
            weights.append((literal_overlap, self.config.literal_overlap_weight))
        if llm_confirmed:
            weights.append((1.0, self.config.llm_confirm_weight))

        total_weight = sum(weight for _, weight in weights)
        if total_weight == 0:
            return 0.0

        combined = sum(score * weight for score, weight in weights) / total_weight
        if boost is not None:
            combined += boost
        return max(0.0, min(1.0, combined))

    def _rerank_with_llm(
        self,
        *,
        test_text: str,
        ranked_candidates: list[tuple[StepDefinition, float]],
        similarity_scores: dict[str, float],
        embedding_scores: dict[str, float],
        parameter_fit_scores: dict[str, float],
        literal_overlap_scores: dict[str, float],
        current_best: StepDefinition,
        current_score: float,
    ) -> tuple[StepDefinition, float, bool, dict[str, Any]]:
        short_list = [definition for definition, _ in ranked_candidates[: max(1, self.config.llm_shortlist)]]
        prompt = self._build_llm_prompt(test_text, short_list)
        response = self.llm_client.generate(prompt)
        chosen, confidence, reason = self._extract_llm_choice(response, short_list)

        llm_meta = {
            "llm_choice_confidence": confidence,
            "llm_choice_reason": reason,
        }
        if not chosen:
            return current_best, current_score, False, llm_meta
        if confidence < self.config.llm_min_confidence:
            return current_best, current_score, False, llm_meta

        combined = self._combine_score(
            similarity_scores.get(chosen.id, 0.0),
            embedding_scores.get(chosen.id),
            llm_confirmed=True,
            parameter_fit=parameter_fit_scores.get(chosen.id),
            literal_overlap=literal_overlap_scores.get(chosen.id),
        )
        return chosen, combined, True, llm_meta
    def _estimate_parameter_fit(self, definition: StepDefinition, test_text: str) -> float:
        placeholders = self._extract_placeholders(definition.pattern)
        if not placeholders and definition.pattern_type.value != "regularExpression":
            return 1.0

        _, _, meta = self._resolve_step_text(definition, test_text)
        status = str((meta or {}).get("status", "none")).casefold()
        if status == "full":
            return 1.0
        if status == "partial":
            return 0.5
        return 0.0

    def _resolve_step_text(
        self,
        definition: StepDefinition,
        test_text: str,
        *,
        original_text: str | None = None,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        pattern = definition.pattern
        placeholders = self._extract_placeholders(pattern)
        sources: list[str] = []
        best_partial: tuple[str, list[dict[str, Any]], dict[str, Any]] | None = None

        regex_attempt = self._resolve_with_regex(definition, test_text, placeholders)
        if not regex_attempt and original_text and original_text.strip() != test_text.strip():
            regex_attempt = self._resolve_with_regex(
                definition,
                original_text,
                placeholders,
                source="regex_original_text",
            )
        if regex_attempt:
            resolved, params, status, source = regex_attempt
            meta = self._build_fill_meta(
                status=status,
                source=source,
                source_chain=[source],
                placeholders=placeholders,
                matched_parameters=params,
            )
            if status == "full":
                return resolved, params, meta
            best_partial = (resolved, params, meta)
            sources.append("regex_strict")

        if not placeholders and definition.pattern_type.value != "regularExpression":
            return pattern, [], self._build_fill_meta(
                status="full",
                source="definition_pattern",
                source_chain=["definition_pattern"],
                placeholders=placeholders,
                matched_parameters=[],
            )

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

    def _resolve_with_regex(
        self,
        definition: StepDefinition,
        test_text: str,
        placeholders: list[str],
        *,
        source: str = "regex_strict",
    ) -> tuple[str, list[dict[str, Any]], str, str] | None:
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
                definition, placeholders, groups, source=source
            )
            return test_text.strip(), params, "full", source

        if not placeholders:
            return definition.pattern, [], "full", source

        resolved = self._replace_placeholders(definition.pattern, groups)
        params = self._build_parameter_payload(
            definition, placeholders, groups, source=source
        )
        status = "full" if not self._has_placeholders(resolved) else "partial"
        return resolved, params, status, source

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
    def _literal_overlap_score(left: str, right: str) -> float:
        left_tokens = [token for token in left.split() if token]
        right_tokens = [token for token in right.split() if token]
        if not left_tokens or not right_tokens:
            return 0.0
        intersection = len(set(left_tokens) & set(right_tokens))
        union = len(set(left_tokens) | set(right_tokens))
        if union == 0:
            return 0.0
        return intersection / union

    def _split_leading_gherkin_keyword(self, text: str) -> tuple[str | None, str, bool]:
        source_text = (text or "").strip()
        if not source_text:
            return None, source_text, False
        match = self._LEADING_GHERKIN_KEYWORD_RE.match(source_text)
        if not match:
            return None, source_text, False
        keyword = self._clean_value(match.group("keyword"))
        remainder = self._clean_value(match.group("text"))
        if not remainder:
            return None, source_text, False
        return keyword, remainder, True

    def _is_strict_resolution_failed(
        self,
        definition: StepDefinition,
        parameter_fill_meta: dict[str, Any] | None,
    ) -> bool:
        has_placeholders = bool(self._extract_placeholders(definition.pattern))
        is_regex_pattern = definition.pattern_type.value == "regularExpression"
        if not has_placeholders and not is_regex_pattern:
            return False
        status = str((parameter_fill_meta or {}).get("status") or "").casefold()
        return status != "full"

    @staticmethod
    def _clean_value(value: Any) -> str:
        cleaned = "" if value is None else str(value).strip()
        if len(cleaned) >= 2:
            wrappers = {("\"", "\""), ("'", "'"), ("«", "»")}
            for left, right in wrappers:
                if cleaned.startswith(left) and cleaned.endswith(right):
                    cleaned = cleaned[1:-1].strip()
        return cleaned

    @staticmethod
    def _build_llm_prompt(test_text: str, candidates: list[StepDefinition]) -> str:
        lines = [
            "Выбери лучший cucumber-шаг, который соответствует тестовому шагу.",
            'Ответь JSON-объектом: {"choice":"C1","confidence":0.0-1.0,"reason":"..."}',
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
    ) -> tuple[StepDefinition | None, float, str | None]:
        if not response:
            return None, 0.0, None

        lookup = {f"C{idx}": candidate for idx, candidate in enumerate(candidates, start=1)}
        confidence = 0.0
        reason: str | None = None
        stripped = response.strip()

        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                raw_choice = str(parsed.get("choice", "")).strip().upper()
                raw_confidence = parsed.get("confidence")
                if raw_choice in lookup:
                    try:
                        confidence = float(raw_confidence)
                    except (TypeError, ValueError):
                        confidence = 0.0
                    confidence = max(0.0, min(1.0, confidence))
                    reason_raw = parsed.get("reason")
                    reason = str(reason_raw).strip() if reason_raw else None
                    return lookup[raw_choice], confidence, reason
        except json.JSONDecodeError:
            pass

        for token, candidate in lookup.items():
            if token in response:
                return candidate, 1.0, "legacy_token"

        lowered_response = response.casefold()
        for candidate in candidates:
            if candidate.pattern.casefold() in lowered_response:
                return candidate, 0.8, "pattern_match"

        return None, 0.0, None
