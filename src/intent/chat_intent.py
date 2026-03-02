"""Parse free-text session messages into structured execution intents."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


_JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-[A-Z]*\d+)\b")


class SessionIntent(BaseModel):
    kind: Literal["conversation", "run_trigger", "command"] = "conversation"
    plugin: str | None = None
    confidence: float = 0.0
    jira_key: str | None = Field(default=None, alias="jiraKey")
    target_path: str | None = Field(default=None, alias="targetPath")
    language: str | None = None
    overwrite_existing: bool = Field(default=False, alias="overwriteExisting")
    normalized_input: dict[str, Any] = Field(default_factory=dict, alias="normalizedInput")

    def should_start_run(self) -> bool:
        return self.kind == "run_trigger" and bool(self.plugin)


class ChatIntentParser:
    """Heuristic parser for the current session UX."""

    _autotest_tokens = (
        "автотест",
        "auto test",
        "autotest",
        "test case",
        "testcase",
        "тесткейс",
        "feature",
        "gherkin",
        "generate feature",
        "generate test",
        "создай автотест",
        "сгенерируй автотест",
    )

    _run_verbs = (
        "создай",
        "сгенерируй",
        "generate",
        "build",
        "make",
    )

    _target_path_patterns = (
        r"targetpath\s*[=:]\s*([^\s,;]+)",
        r"path\s*[=:]\s*([^\s,;]+\.feature)",
        r"([^\s,;]+\.feature)",
    )

    def parse(self, content: str) -> SessionIntent:
        raw = str(content or "").strip()
        lowered = raw.lower()
        if not raw:
            return SessionIntent()

        jira_key = self._extract_jira_key(raw)
        target_path = self._extract_target_path(raw)
        language = self._extract_language(lowered)
        overwrite_existing = "overwrite=true" in lowered or "перезапис" in lowered

        token_hits = sum(1 for token in self._autotest_tokens if token in lowered)
        verb_hits = sum(1 for token in self._run_verbs if token in lowered)
        confidence = 0.0
        if token_hits:
            confidence += 0.45
        if verb_hits:
            confidence += 0.2
        if jira_key:
            confidence += 0.25
        if target_path:
            confidence += 0.1
        confidence = min(confidence, 0.99)

        if token_hits:
            normalized_input: dict[str, Any] = {
                "testCaseText": raw,
                "targetPath": target_path,
                "language": language,
                "overwriteExisting": overwrite_existing,
            }
            if jira_key:
                normalized_input["jiraKey"] = jira_key
            return SessionIntent(
                kind="run_trigger",
                plugin="testgen",
                confidence=confidence,
                jiraKey=jira_key,
                targetPath=target_path,
                language=language,
                overwriteExisting=overwrite_existing,
                normalizedInput=normalized_input,
            )

        return SessionIntent(confidence=confidence)

    @staticmethod
    def _extract_jira_key(content: str) -> str | None:
        match = _JIRA_KEY_RE.search(content.upper())
        if not match:
            return None
        return match.group(1).strip().upper()

    def _extract_target_path(self, content: str) -> str | None:
        for pattern in self._target_path_patterns:
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = match.group(1).strip()
            if candidate:
                return candidate
        return None

    @staticmethod
    def _extract_language(lowered: str) -> str | None:
        if "language=en" in lowered or "gherkin en" in lowered or "на англий" in lowered:
            return "en"
        if "language=ru" in lowered or "gherkin ru" in lowered or "на русском" in lowered:
            return "ru"
        return None
