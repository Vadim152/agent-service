"""Normalize Jira/Zephyr testcase payload into parser-friendly plain text."""
from __future__ import annotations

import html
import re
from typing import Any

from infrastructure.llm_client import LLMClient
from tools.testcase_step_normalizer import is_table_row, normalize_source_step_text_with_meta


_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_SPACE_RE = re.compile(r"[ \t]+")
_SPECIAL_SCENARIO_NAME_KEY = "SCBC-T1"


def _clean_html_text(value: Any) -> str:
    if value is None:
        return ""

    raw = str(value)
    with_breaks = _BR_RE.sub("\n", raw).replace("</li>", "; ")
    no_tags = _TAG_RE.sub(" ", with_breaks)
    unescaped = html.unescape(no_tags)
    lines = []
    for line in unescaped.splitlines():
        normalized = _SPACE_RE.sub(" ", line).strip()
        if normalized:
            lines.append(normalized)
    return "\n".join(lines)


def _sorted_steps(test_script: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = test_script.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("Jira testcase payload is invalid: missing testScript.steps")

    def _sort_key(item: dict[str, Any]) -> tuple[int, int]:
        index = item.get("index")
        if isinstance(index, int):
            return index, 0
        if isinstance(index, str) and index.isdigit():
            return int(index), 0
        return 10_000_000, 1

    return sorted((step for step in raw_steps if isinstance(step, dict)), key=_sort_key)


def normalize_jira_testcase(
    payload: dict[str, Any],
    *,
    llm_client: LLMClient | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build parser-friendly testcase text and normalization metadata from Jira payload."""
    if not isinstance(payload, dict):
        raise ValueError("Jira testcase payload must be a JSON object")

    payload_key = _clean_html_text(payload.get("key")).upper()
    name = _clean_html_text(payload.get("name")) or payload_key or "Без названия"
    if payload_key == _SPECIAL_SCENARIO_NAME_KEY:
        name = _SPECIAL_SCENARIO_NAME_KEY

    precondition = _clean_html_text(payload.get("precondition"))
    test_script = payload.get("testScript")
    if not isinstance(test_script, dict):
        raise ValueError("Jira testcase payload is invalid: missing testScript object")

    steps = _sorted_steps(test_script)

    lines: list[str] = [f"Сценарий: {name}"]
    lines.append("")
    action_number = 1
    normalized_actions = 0
    llm_fallback_used = False
    llm_fallback_successful = False

    for step in steps:
        description = _clean_html_text(step.get("description")) or f"Шаг {action_number}"
        normalized_chunks, meta = normalize_source_step_text_with_meta(
            description,
            source="jira",
            llm_client=llm_client,
        )
        llm_fallback_used = llm_fallback_used or bool(meta.get("llmFallbackUsed"))
        llm_fallback_successful = llm_fallback_successful or bool(meta.get("llmFallbackSuccessful"))

        for chunk in normalized_chunks:
            if is_table_row(chunk):
                lines.append(chunk)
                normalized_actions += 1
                continue
            lines.append(f"{action_number}. {chunk}")
            action_number += 1
            normalized_actions += 1

        expected = _clean_html_text(step.get("expectedResult"))
        if expected:
            lines.append(f"Ожидаемый результат: {expected}")

        test_data = _clean_html_text(step.get("testData"))
        if test_data:
            lines.append(f"Тестовые данные: {test_data}")

        lines.append("")

    text = "\n".join(lines).strip()
    report = {
        "inputSteps": len(steps),
        "normalizedSteps": normalized_actions,
        "splitCount": max(0, normalized_actions - len(steps)),
        "llmFallbackUsed": llm_fallback_used,
        "llmFallbackSuccessful": llm_fallback_successful,
        "source": "jira",
        "preconditionText": precondition,
    }
    return text, report


def normalize_jira_testcase_to_text(
    payload: dict[str, Any],
    *,
    llm_client: LLMClient | None = None,
) -> str:
    text, _report = normalize_jira_testcase(payload, llm_client=llm_client)
    return text


__all__ = ["normalize_jira_testcase", "normalize_jira_testcase_to_text"]
