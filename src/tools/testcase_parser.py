"""Heuristic parser that converts testcase text into a canonical Scenario model."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable

from domain.enums import ScenarioType, StepIntentType
from domain.models import CanonicalStep, CanonicalTestCase, Scenario, TestStep
from infrastructure.llm_client import LLMClient


logger = logging.getLogger(__name__)


class TestCaseParser:
    """Parses raw testcase text into Scenario and TestStep objects."""

    __test__ = False

    STEP_PATTERNS = (
        re.compile(r"^\s*\d+[.)]\s*(?P<text>.+)$"),
        re.compile(r"^\s*(Шаг|Step)\s*\d*[:\.-]?\s*(?P<text>.+)$", re.IGNORECASE),
        re.compile(
            r"^\s*(Дано|Когда|Тогда|И|Но|Given|When|Then|And|But)\b\s*(?P<text>.+)$",
            re.IGNORECASE,
        ),
        re.compile(r"^\s*[-*]\s*(?P<text>.+)$"),
    )
    SECTION_PATTERNS: dict[str, re.Pattern[str]] = {
        "preconditions": re.compile(
            r"^\s*(предусловия|preconditions|prerequisites?|setup)\s*[:\-]?\s*(?P<rest>.*)$",
            re.IGNORECASE,
        ),
        "actions": re.compile(
            r"^\s*(шаги|steps|actions?)\s*[:\-]?\s*(?P<rest>.*)$",
            re.IGNORECASE,
        ),
        "expected_results": re.compile(
            r"^\s*(ожида(емый|емые)\s+результат(ы)?|expected\s+results?)\s*[:\-]?\s*(?P<rest>.*)$",
            re.IGNORECASE,
        ),
        "test_data": re.compile(
            r"^\s*(тестовые\s+данные|test\s+data)\s*[:\-]?\s*(?P<rest>.*)$",
            re.IGNORECASE,
        ),
    }
    TITLE_PATTERN = re.compile(r"^\s*(Сценарий|Scenario|Название|Title)\s*[:\-]?\s*(?P<name>.+)$", re.IGNORECASE)
    ASSERTION_HINT_RE = re.compile(
        r"(?iu)\b(провер|убед|ожид|должен|should|verify|assert|displayed|shown|visible|error)\w*\b"
    )
    NAVIGATION_HINT_RE = re.compile(
        r"(?iu)\b(откры|перей|перейти|навигац|open|navigate|go to|redirect)\w*\b"
    )
    TEST_DATA_HINT_RE = re.compile(
        r"(?iu)\b(данн|значени|value|payload|json|таблиц|table)\w*\b"
    )
    TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$")
    TAG_RE = re.compile(r"^\s*@(?P<tags>.+)$")

    def parse(self, raw_text: str) -> Scenario:
        lines = [line.rstrip() for line in raw_text.splitlines() if line.strip()]
        title = self._extract_name(lines)
        structured = self._extract_structured_content(lines, title=title)
        canonical = self._build_canonical_testcase(title=title, structured=structured, source="heuristic")
        return self._scenario_from_canonical(canonical)

    def parse_with_llm(self, raw_text: str, llm_client: LLMClient) -> Scenario:
        prompt = (
            "Extract a structured QA testcase from the input text.\n"
            "Return strict JSON with fields:\n"
            "title (string), preconditions (string[]), actions (string[]), "
            "expected_results (string[]), test_data (string[]), tags (string[]), "
            "scenario_type (string|null).\n"
            "Return JSON only.\n"
            f"Testcase text:\n{raw_text}\n"
        )

        llm_response = llm_client.generate(prompt)
        logger.debug("[TestCaseParser] LLM response: %s", llm_response)

        payload = self._extract_json(llm_response)
        canonical = CanonicalTestCase(
            title=str(payload.get("title") or payload.get("name") or "Без названия"),
            preconditions=self._canonicalize_steps(
                self._to_text_list(payload.get("preconditions", [])),
                section="preconditions",
                source="llm",
            ),
            actions=self._canonicalize_steps(
                self._to_text_list(payload.get("actions", payload.get("steps", []))),
                section="actions",
                source="llm",
            ),
            expected_results=self._canonicalize_steps(
                self._to_text_list(
                    payload.get("expected_results", payload.get("expectedResult", payload.get("expected_result", [])))
                ),
                section="expected_results",
                source="llm",
            ),
            test_data=self._to_text_list(payload.get("test_data", payload.get("testData", []))),
            tags=self._to_text_list(payload.get("tags", [])),
            scenario_type=self._coerce_scenario_type(payload.get("scenario_type")),
            source="llm",
        )
        return self._scenario_from_canonical(canonical)

    def _extract_name(self, lines: list[str]) -> str | None:
        for line in lines:
            match = self.TITLE_PATTERN.match(line)
            if match:
                return match.group("name").strip()
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if self._extract_step_text(stripped):
                continue
            if self._is_table_row(stripped):
                continue
            if self.TAG_RE.match(stripped):
                continue
            section, _ = self._detect_section_header(stripped)
            if section:
                continue
            return stripped
        return None

    def _extract_structured_content(self, lines: list[str], *, title: str | None) -> dict[str, Any]:
        buckets: dict[str, list[str]] = {
            "preconditions": [],
            "actions": [],
            "expected_results": [],
            "test_data": [],
            "tags": [],
        }
        current_section: str | None = None

        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if title and index == 0 and stripped == title.strip():
                continue

            title_match = self.TITLE_PATTERN.match(stripped)
            if title_match:
                continue

            tag_match = self.TAG_RE.match(stripped)
            if tag_match:
                tags = [
                    item.strip().lstrip("@")
                    for item in tag_match.group("tags").split("@")
                    if item.strip()
                ]
                buckets["tags"].extend(tags)
                continue

            matched_section, remainder = self._detect_section_header(stripped)
            if matched_section is not None:
                current_section = matched_section
                if remainder:
                    self._append_to_bucket(
                        buckets,
                        matched_section,
                        self._normalize_inline_item(remainder),
                    )
                continue

            normalized = self._normalize_inline_item(stripped)
            if not normalized:
                continue
            target_section = self._resolve_section(normalized, current_section)
            self._append_to_bucket(buckets, target_section, normalized)

        return buckets

    def _detect_section_header(self, line: str) -> tuple[str | None, str]:
        for section, pattern in self.SECTION_PATTERNS.items():
            match = pattern.match(line)
            if match:
                return section, (match.group("rest") or "").strip()
        return None, ""

    def _normalize_inline_item(self, text: str) -> str:
        extracted = self._extract_step_text(text)
        if extracted:
            return extracted
        if self._is_table_row(text):
            return self._normalize_table_row(text)
        return text.strip()

    def _resolve_section(self, text: str, current_section: str | None) -> str:
        if current_section == "test_data":
            return "test_data"
        if current_section == "expected_results":
            return "expected_results"
        if current_section == "preconditions":
            return "preconditions"
        if current_section == "actions":
            if self._is_assertion(text):
                return "expected_results"
            if self._is_test_data(text):
                return "test_data"
            return "actions"

        lowered = text.casefold()
        if lowered.startswith(("тогда ", "then ")):
            return "expected_results"
        if lowered.startswith(("дано ", "given ")):
            return "preconditions"
        if self._is_assertion(text):
            return "expected_results"
        if self._is_test_data(text):
            return "test_data"
        return "actions"

    def _build_canonical_testcase(
        self,
        *,
        title: str | None,
        structured: dict[str, Any],
        source: str,
    ) -> CanonicalTestCase:
        preconditions = self._canonicalize_steps(
            structured.get("preconditions", []),
            section="preconditions",
            source=source,
        )
        actions = self._canonicalize_steps(
            structured.get("actions", []),
            section="actions",
            source=source,
        )
        expected_results = self._canonicalize_steps(
            structured.get("expected_results", []),
            section="expected_results",
            source=source,
        )
        return CanonicalTestCase(
            title=(title or "Без названия").strip(),
            preconditions=preconditions,
            actions=actions,
            expected_results=expected_results,
            test_data=[str(item).strip() for item in structured.get("test_data", []) if str(item).strip()],
            tags=[str(item).strip() for item in structured.get("tags", []) if str(item).strip()],
            scenario_type=self._infer_scenario_type(
                title or "",
                [step.text for step in actions + expected_results],
            ),
            source=source,
        )

    def _canonicalize_steps(
        self,
        items: list[str],
        *,
        section: str,
        source: str,
    ) -> list[CanonicalStep]:
        result: list[CanonicalStep] = []
        for index, raw in enumerate(items, start=1):
            text = str(raw).strip()
            if not text:
                continue
            result.append(
                CanonicalStep(
                    order=index,
                    text=text,
                    intent_type=self._infer_intent_type(text, section=section),
                    source=source,
                    origin=section,
                    normalized_from=text,
                )
            )
        return result

    def _scenario_from_canonical(self, canonical: CanonicalTestCase) -> Scenario:
        preconditions = self._to_test_steps(canonical.preconditions, section="precondition")
        combined = self._to_test_steps(canonical.preconditions, section="precondition")
        combined.extend(self._to_test_steps(canonical.actions, section="step", start_order=len(combined) + 1))
        combined.extend(
            self._to_test_steps(
                canonical.expected_results,
                section="expected_result",
                start_order=len(combined) + 1,
            )
        )
        expected_result = "; ".join(step.text for step in canonical.expected_results) or None
        return Scenario(
            name=canonical.title or "Без названия",
            description=None,
            preconditions=preconditions,
            steps=combined,
            expected_result=expected_result,
            tags=list(canonical.tags),
            test_data=list(canonical.test_data),
            scenario_type=canonical.scenario_type,
            canonical={
                "title": canonical.title,
                "preconditions": [self._serialize_canonical_step(step) for step in canonical.preconditions],
                "actions": [self._serialize_canonical_step(step) for step in canonical.actions],
                "expected_results": [
                    self._serialize_canonical_step(step) for step in canonical.expected_results
                ],
                "test_data": list(canonical.test_data),
                "tags": list(canonical.tags),
                "scenario_type": canonical.scenario_type.value,
                "source": canonical.source,
            },
        )

    def _to_test_steps(
        self,
        steps: list[CanonicalStep],
        *,
        section: str,
        start_order: int = 1,
    ) -> list[TestStep]:
        result: list[TestStep] = []
        for index, step in enumerate(steps, start=start_order):
            result.append(
                TestStep(
                    order=index,
                    text=step.text,
                    section=section,
                    intent_type=step.intent_type,
                    source_text=step.normalized_from or step.text,
                )
            )
        return result

    @staticmethod
    def _serialize_canonical_step(step: CanonicalStep) -> dict[str, Any]:
        return {
            "order": step.order,
            "text": step.text,
            "intent_type": step.intent_type.value,
            "source": step.source,
            "origin": step.origin,
            "confidence": step.confidence,
            "normalized_from": step.normalized_from,
            "metadata": dict(step.metadata),
        }

    def _infer_intent_type(self, text: str, *, section: str) -> StepIntentType:
        if section == "preconditions":
            return StepIntentType.SETUP
        if section == "expected_results":
            return StepIntentType.ASSERTION
        if section == "test_data":
            return StepIntentType.TEST_DATA
        if self._is_assertion(text):
            return StepIntentType.ASSERTION
        if self._is_navigation(text):
            return StepIntentType.NAVIGATION
        return StepIntentType.ACTION

    def _infer_scenario_type(self, title: str, steps: list[str]) -> ScenarioType:
        text = " ".join([title, *steps]).casefold()
        if any(token in text for token in ("invalid", "error", "ошиб", "некоррект", "валидац")):
            return ScenarioType.VALIDATION
        if any(token in text for token in ("negative", "негатив", "denied", "forbidden")):
            return ScenarioType.NEGATIVE
        if any(token in text for token in ("navigate", "open", "screen", "перей", "откры")):
            return ScenarioType.NAVIGATION
        if any(token in text for token in ("create", "update", "delete", "crud", "созда", "удал", "измен")):
            return ScenarioType.CRUD
        return ScenarioType.STANDARD

    def _extract_step_text(self, line: str) -> str | None:
        for pattern in self.STEP_PATTERNS:
            match = pattern.match(line)
            if match:
                return match.group("text").strip()
        return None

    def _is_assertion(self, text: str) -> bool:
        lowered = text.casefold()
        return lowered.startswith(("тогда ", "then ")) or bool(self.ASSERTION_HINT_RE.search(text))

    def _is_navigation(self, text: str) -> bool:
        return bool(self.NAVIGATION_HINT_RE.search(text))

    def _is_test_data(self, text: str) -> bool:
        return self._is_table_row(text) or bool(self.TEST_DATA_HINT_RE.search(text))

    def _is_table_row(self, line: str) -> bool:
        return bool(self.TABLE_ROW_RE.match(line))

    def _normalize_table_row(self, line: str) -> str:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        return " | ".join(cells)

    def _extract_json(self, text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        raise ValueError("LLM did not return valid JSON for testcase parsing")

    def _to_text_list(self, items: Any) -> list[str]:
        if items is None:
            return []
        if isinstance(items, str):
            prepared = items.strip()
            return [prepared] if prepared else []
        if not isinstance(items, Iterable):
            prepared = str(items).strip()
            return [prepared] if prepared else []

        result: list[str] = []
        for item in items:
            if isinstance(item, dict):
                value = item.get("text") or item.get("step") or item.get("value")
            else:
                value = item
            prepared = str(value).strip() if value is not None else ""
            if prepared:
                result.append(prepared)
        return result

    def _coerce_scenario_type(self, value: Any) -> ScenarioType:
        if value:
            try:
                return ScenarioType(str(value).strip().lower())
            except ValueError:
                pass
        return ScenarioType.STANDARD

    @staticmethod
    def _append_to_bucket(buckets: dict[str, list[str]], bucket: str, value: str) -> None:
        prepared = str(value).strip()
        if prepared:
            buckets[bucket].append(prepared)


__all__ = ["TestCaseParser"]
