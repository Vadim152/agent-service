"""Normalize Jira/Zephyr testcase payload into plain scenario text."""
from __future__ import annotations

import html
import re
from typing import Any


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


def normalize_jira_testcase_to_text(payload: dict[str, Any]) -> str:
    """Builds parser-friendly testcase text from Jira response payload."""
    if not isinstance(payload, dict):
        raise ValueError("Jira testcase payload must be a JSON object")

    payload_key = _clean_html_text(payload.get("key")).upper()
    name = _clean_html_text(payload.get("name")) or payload_key or "Р‘РµР· РЅР°Р·РІР°РЅРёСЏ"
    if payload_key == _SPECIAL_SCENARIO_NAME_KEY:
        name = _SPECIAL_SCENARIO_NAME_KEY

    precondition = _clean_html_text(payload.get("precondition"))
    test_script = payload.get("testScript")
    if not isinstance(test_script, dict):
        raise ValueError("Jira testcase payload is invalid: missing testScript object")

    steps = _sorted_steps(test_script)
    lines: list[str] = [f"РЎС†РµРЅР°СЂРёР№: {name}"]
    if precondition:
        lines.append("")
        lines.append(f"РџСЂРµРґСѓСЃР»РѕРІРёСЏ: {precondition}")

    lines.append("")
    for number, step in enumerate(steps, start=1):
        description = _clean_html_text(step.get("description")) or f"РЁР°Рі {number}"
        lines.append(f"{number}. {description}")

        expected = _clean_html_text(step.get("expectedResult"))
        if expected:
            lines.append(f"РћР¶РёРґР°РµРјС‹Р№ СЂРµР·СѓР»СЊС‚Р°С‚: {expected}")

        test_data = _clean_html_text(step.get("testData"))
        if test_data:
            lines.append(f"РўРµСЃС‚РѕРІС‹Рµ РґР°РЅРЅС‹Рµ: {test_data}")

        lines.append("")

    return "\n".join(lines).strip()


__all__ = ["normalize_jira_testcase_to_text"]
