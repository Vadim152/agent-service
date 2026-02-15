"""Jira testcase provider with live and local stub modes."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, get_settings

JIRA_TESTCASE_FIELDS = (
    "id,projectId,archived,key,name,objective,majorVersion,latestVersion,precondition,"
    "folder(id,fullName),status,priority,estimatedTime,averageTime,componentId,owner,labels,"
    "customFieldValues,testScript(id,text,steps(index,reflectRef,description,text,expectedResult,"
    "testData,attachments,customFieldValues,id,stepParameters(id,testCaseParameterId,value),"
    "testCase(id,key,name,archived,majorVersion,latestVersion,parameters(id,name,defaultValue,index)))),"
    "testData,parameters(id,name,defaultValue,index),paramType"
)

_JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-[A-Z]*\d+)\b", re.IGNORECASE)
_SPECIAL_STUB_KEY = "SCBC-T1"


def extract_jira_testcase_key(text: str | None) -> str | None:
    if not text:
        return None
    match = _JIRA_KEY_RE.search(text)
    if not match:
        return None
    return match.group(1).upper()


class JiraTestcaseProvider:
    """Loads testcase payload from Jira live API or local stub data."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        stub_payload_path: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.stub_payload_path = (
            stub_payload_path or Path(__file__).resolve().parent / "stubs" / "jira_testcase_SCBC-T1.json"
        )
        self._special_stub_payload: dict[str, Any] | None = None

    @property
    def mode(self) -> str:
        return (self.settings.jira_source_mode or "stub").strip().lower()

    def fetch_testcase(
        self,
        key: str,
        auth: dict[str, Any] | None = None,
        jira_instance: str | None = None,
    ) -> dict[str, Any]:
        if not key:
            raise ValueError("Jira testcase key is empty")

        normalized_key = key.strip().upper()
        if normalized_key == _SPECIAL_STUB_KEY:
            return self._fetch_special_stub(normalized_key)

        if self.mode == "disabled":
            raise RuntimeError("Jira testcase retrieval is disabled")

        return self._fetch_live(normalized_key, auth=auth, jira_instance=jira_instance)

    def _fetch_special_stub(self, key: str) -> dict[str, Any]:
        payload = self._load_special_stub_payload()
        selected = copy.deepcopy(payload)
        selected["key"] = key
        return selected

    def _load_special_stub_payload(self) -> dict[str, Any]:
        if self._special_stub_payload is not None:
            return self._special_stub_payload
        if not self.stub_payload_path.exists():
            raise RuntimeError(f"Jira stub payload file not found: {self.stub_payload_path}")

        raw = self.stub_payload_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError("Jira special stub payload must be a JSON object")

        self._special_stub_payload = parsed
        return parsed

    def _fetch_live(
        self,
        key: str,
        *,
        auth: dict[str, Any] | None,
        jira_instance: str | None,
    ) -> dict[str, Any]:
        base_url = (jira_instance or self.settings.jira_default_instance or "").strip().rstrip("/")
        if not base_url:
            raise RuntimeError("Jira instance URL is not configured")

        headers: dict[str, str] = {}
        auth_tuple: tuple[str, str] | None = None
        if auth:
            auth_type = str(auth.get("authType") or auth.get("auth_type") or "").strip().upper()
            if auth_type == "TOKEN":
                token = str(auth.get("token") or "").strip()
                if not token:
                    raise RuntimeError("Jira TOKEN auth selected but token is empty")
                headers["Authorization"] = f"Bearer {token}"
            elif auth_type == "LOGIN_PASSWORD":
                login = str(auth.get("login") or "").strip()
                password = str(auth.get("password") or "").strip()
                if not login or not password:
                    raise RuntimeError("Jira LOGIN_PASSWORD auth selected but login/password are empty")
                auth_tuple = (login, password)

        url = f"{base_url}/rest/atm/1.0/testcase/{key}"
        timeout = max(1, int(self.settings.jira_request_timeout_s))
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.get(
                    url,
                    params={"fields": JIRA_TESTCASE_FIELDS},
                    headers=headers,
                    auth=auth_tuple,
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Jira request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text.strip()
            if len(detail) > 300:
                detail = detail[:300] + "..."
            raise RuntimeError(
                f"Jira responded with {response.status_code}: {detail or 'empty response'}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Jira returned invalid JSON payload") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("Jira payload is not a JSON object")
        return payload


__all__ = ["JiraTestcaseProvider", "extract_jira_testcase_key", "JIRA_TESTCASE_FIELDS"]
