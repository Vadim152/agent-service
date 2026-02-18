"""Utilities for splitting raw testcase text into atomic executable steps."""
from __future__ import annotations

import json
import re
from typing import Any

from domain.models import TestStep
from infrastructure.llm_client import LLMClient


_TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$")
_INLINE_GHERKIN_SPLIT_RE = re.compile(
    r"\s+(?=(?:Дано|Когда|Тогда|И|Но|Given|When|Then|And|But)\b)"
)
_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_ACTION_HINT_RE = re.compile(
    r"(?iu)\b("
    r"включ\w+|поменя\w+|перевед\w+|осуществ\w+|перейд\w+|"
    r"провер\w+|запомн\w+|увелич\w+|верн\w+|нажм\w+|введ\w+|"
    r"authorize\w*|open\w*|click\w*|check\w*|save\w*"
    r")\b"
)
_NORMALIZATION_SECTION_PREFIX = "__norm__:"


def is_table_row(text: str) -> bool:
    return bool(_TABLE_ROW_RE.match(text or ""))


def build_normalization_section(
    *, normalized_from: str, strategy: str, source_section: str | None = None
) -> str:
    payload = {
        "normalizedFrom": normalized_from,
        "normalizationStrategy": strategy,
    }
    if source_section:
        payload["sourceSection"] = source_section
    return _NORMALIZATION_SECTION_PREFIX + json.dumps(payload, ensure_ascii=False)


def parse_normalization_section(section: str | None) -> dict[str, Any] | None:
    if not section or not section.startswith(_NORMALIZATION_SECTION_PREFIX):
        return None
    raw = section[len(_NORMALIZATION_SECTION_PREFIX) :]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def normalize_source_step_text(
    text: str,
    *,
    source: str = "raw",
    llm_client: LLMClient | None = None,
) -> list[str]:
    chunks, _meta = normalize_source_step_text_with_meta(
        text, source=source, llm_client=llm_client
    )
    return chunks


def normalize_source_step_text_with_meta(
    text: str,
    *,
    source: str = "raw",
    llm_client: LLMClient | None = None,
) -> tuple[list[str], dict[str, Any]]:
    prepared = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not prepared:
        return [], {
            "strategy": "rule",
            "llmFallbackUsed": False,
            "llmFallbackSuccessful": False,
        }

    lines = [line.strip() for line in prepared.split("\n") if line.strip()]
    chunks: list[str] = []
    for line in lines:
        if is_table_row(line):
            chunks.append(line)
            continue

        rule_chunks = _split_rule_based(line)
        if rule_chunks:
            chunks.extend(rule_chunks)
        else:
            chunks.append(line)

    used_llm = False
    llm_success = False
    if llm_client and _needs_llm_fallback(prepared, chunks):
        used_llm = True
        llm_chunks = _split_with_llm(llm_client, prepared)
        if llm_chunks:
            llm_success = True
            chunks = llm_chunks

    deduped = [chunk.strip() for chunk in chunks if chunk and chunk.strip()]
    if not deduped:
        deduped = [prepared]

    strategy = "llm_fallback" if llm_success else "rule"
    return deduped, {
        "strategy": strategy,
        "llmFallbackUsed": used_llm,
        "llmFallbackSuccessful": llm_success,
        "source": source,
    }


def normalize_test_steps(
    steps: list[TestStep],
    *,
    source: str = "raw",
    llm_client: LLMClient | None = None,
) -> tuple[list[TestStep], dict[str, Any]]:
    normalized_steps: list[TestStep] = []
    order = 1
    split_count = 0
    llm_used = False
    llm_success = False

    for step in steps:
        normalized_chunks, meta = normalize_source_step_text_with_meta(
            step.text,
            source=source,
            llm_client=llm_client,
        )
        llm_used = llm_used or bool(meta.get("llmFallbackUsed"))
        llm_success = llm_success or bool(meta.get("llmFallbackSuccessful"))
        changed = len(normalized_chunks) > 1 or (
            len(normalized_chunks) == 1 and normalized_chunks[0] != step.text.strip()
        )
        split_count += max(0, len(normalized_chunks) - 1)

        for chunk in normalized_chunks:
            section = step.section
            if changed:
                section = build_normalization_section(
                    normalized_from=step.text,
                    strategy=str(meta.get("strategy") or "rule"),
                    source_section=step.section,
                )
            normalized_steps.append(TestStep(order=order, text=chunk, section=section))
            order += 1

    report = {
        "inputSteps": len(steps),
        "normalizedSteps": len(normalized_steps),
        "splitCount": split_count,
        "llmFallbackUsed": llm_used,
        "llmFallbackSuccessful": llm_success,
        "source": source,
    }
    return normalized_steps, report


def _split_rule_based(text: str) -> list[str]:
    parts = [text.strip()]

    # Keep explicit Gherkin clauses separate when they were merged into one sentence.
    merged: list[str] = []
    for part in parts:
        chunks = [chunk.strip() for chunk in _INLINE_GHERKIN_SPLIT_RE.split(part) if chunk.strip()]
        merged.extend(chunks or [part])
    parts = merged

    # Aggressive split for non-keyword prose with multiple actions.
    merged = []
    for part in parts:
        comma_chunks = _split_by_comma_if_compound(part)
        for chunk in comma_chunks:
            merged.extend(_split_by_and_if_compound(chunk))
    parts = merged

    return [part for part in parts if part]


def _split_by_comma_if_compound(text: str) -> list[str]:
    if "," not in text or _URL_RE.search(text):
        return [text.strip()]
    candidates = [item.strip() for item in re.split(r"\s*,\s*", text) if item.strip()]
    if len(candidates) < 2:
        return [text.strip()]
    if _action_hints_count(text) < 2:
        return [text.strip()]
    return candidates


def _split_by_and_if_compound(text: str) -> list[str]:
    if not re.search(r"(?iu)\s+и\s+", text):
        return [text.strip()]
    candidates = [item.strip() for item in re.split(r"(?iu)\s+и\s+", text) if item.strip()]
    if len(candidates) < 2:
        return [text.strip()]
    if _action_hints_count(text) < 2:
        return [text.strip()]
    return candidates


def _action_hints_count(text: str) -> int:
    return len(_ACTION_HINT_RE.findall(text))


def _needs_llm_fallback(original_text: str, chunks: list[str]) -> bool:
    if len(chunks) > 1:
        return False
    if is_table_row(original_text):
        return False
    has_many_delimiters = original_text.count(",") >= 2 or original_text.count(";") >= 1
    if not has_many_delimiters and _action_hints_count(original_text) < 2:
        return False
    return len(original_text) >= 140


def _split_with_llm(llm_client: LLMClient, text: str) -> list[str]:
    prompt = (
        "Split one QA testcase step into atomic executable steps. "
        "Return only JSON array of strings without comments.\n"
        f"Step:\n{text}\n"
    )
    try:
        response = llm_client.generate(prompt)
    except Exception:
        return []

    payload = _extract_json_array(response)
    if not payload:
        return []
    return [item.strip() for item in payload if isinstance(item, str) and item.strip()]


def _extract_json_array(text: str | None) -> list[Any]:
    if not text:
        return []
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


__all__ = [
    "build_normalization_section",
    "is_table_row",
    "normalize_source_step_text",
    "normalize_source_step_text_with_meta",
    "normalize_test_steps",
    "parse_normalization_section",
]
