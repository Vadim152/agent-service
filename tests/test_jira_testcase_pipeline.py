from __future__ import annotations

from typing import Any

import pytest

from agents.orchestrator import Orchestrator
from app.config import Settings
from integrations.jira_testcase_normalizer import normalize_jira_testcase_to_text
from integrations.jira_testcase_provider import JiraTestcaseProvider, extract_jira_testcase_key


class _RepoScannerStub:
    def scan_repository(self, _project_root: str) -> dict[str, Any]:
        return {}


class _ParserStub:
    def __init__(self) -> None:
        self.received_text: str | None = None

    def parse_testcase(self, testcase_text: str) -> dict[str, Any]:
        self.received_text = testcase_text
        return {
            "name": "Resolved scenario",
            "description": None,
            "preconditions": [],
            "steps": [{"order": 1, "text": "step one"}],
            "expected_result": None,
            "tags": [],
        }


class _StepMatcherStub:
    def match_testcase_steps(self, _project_root: str, _scenario: dict[str, Any]) -> dict[str, Any]:
        return {"matched": [], "unmatched": [], "needsScan": False, "indexStatus": "ready"}


class _FeatureBuilderStub:
    def build_feature_from_matches(
        self,
        _scenario_dict: dict[str, Any],
        _matched_steps_dicts: list[dict[str, Any]],
        language: str | None = None,
    ) -> dict[str, Any]:
        return {
            "featureText": "Feature: resolved\n",
            "unmappedSteps": [],
            "buildStage": "feature_built",
            "stepsSummary": {"exact": 0, "fuzzy": 0, "unmatched": 0},
            "meta": {"language": language or "ru"},
        }


class _StepIndexStub:
    pass


class _EmbeddingsStub:
    def get_top_k(self, _project_root: str, _query: str, *, top_k: int = 5):  # noqa: ARG002
        return []


class _JiraProviderStub:
    mode = "stub"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.last_key: str | None = None

    def fetch_testcase(
        self,
        key: str,
        auth: dict[str, Any] | None = None,  # noqa: ARG002
        jira_instance: str | None = None,  # noqa: ARG002
    ) -> dict[str, Any]:
        self.last_key = key
        return self.payload


class _JiraProviderFailureStub:
    mode = "stub"

    def fetch_testcase(
        self,
        key: str,  # noqa: ARG002
        auth: dict[str, Any] | None = None,  # noqa: ARG002
        jira_instance: str | None = None,  # noqa: ARG002
    ) -> dict[str, Any]:
        raise RuntimeError("stub fetch failed")


def _make_orchestrator(*, parser: _ParserStub, jira_provider: Any) -> Orchestrator:
    return Orchestrator(
        repo_scanner_agent=_RepoScannerStub(),
        testcase_parser_agent=parser,
        step_matcher_agent=_StepMatcherStub(),
        feature_builder_agent=_FeatureBuilderStub(),
        step_index_store=_StepIndexStub(),
        embeddings_store=_EmbeddingsStub(),
        jira_testcase_provider=jira_provider,
    )


def test_extract_jira_testcase_key_from_free_form_text() -> None:
    assert extract_jira_testcase_key("создай мне автотест по scbc-t3282") == "SCBC-T3282"
    assert extract_jira_testcase_key("plain text without key") is None


def test_normalize_jira_testcase_sorts_steps_and_strips_html() -> None:
    payload = {
        "name": "[Android] Demo testcase",
        "precondition": "<strong>Toggle enabled</strong><br/>Client prepared",
        "testScript": {
            "steps": [
                {"index": 2, "description": "Third action", "expectedResult": "<b>Third expected</b>"},
                {"index": 0, "description": "First action", "expectedResult": "First expected"},
                {"index": 1, "description": "Second action", "expectedResult": "Second expected"},
            ]
        },
    }

    normalized = normalize_jira_testcase_to_text(payload)

    assert "Сценарий: [Android] Demo testcase" in normalized
    assert "Предусловия: Toggle enabled" in normalized
    assert "1. First action" in normalized
    assert "2. Second action" in normalized
    assert "3. Third action" in normalized
    assert "<strong>" not in normalized


def test_orchestrator_resolves_jira_key_before_parse() -> None:
    payload = {
        "name": "[Android] Jira sourced testcase",
        "precondition": "Client has active card",
        "testScript": {
            "steps": [
                {"index": 0, "description": "Авторизоваться", "expectedResult": "Открыт главный экран"}
            ]
        },
    }
    parser = _ParserStub()
    jira_provider = _JiraProviderStub(payload)
    orchestrator = _make_orchestrator(parser=parser, jira_provider=jira_provider)

    result = orchestrator.generate_feature(
        project_root="C:/tmp/project",
        testcase_text="создай мне автотест по SCBC-T3282",
    )

    assert jira_provider.last_key == "SCBC-T3282"
    assert parser.received_text is not None
    assert "Сценарий: [Android] Jira sourced testcase" in parser.received_text
    assert result["pipeline"][0]["stage"] == "source_resolve"
    assert result["pipeline"][0]["status"] == "jira_stub"
    assert result["pipeline"][0]["details"]["jiraKey"] == "SCBC-T3282"


def test_orchestrator_fails_fast_when_jira_fetch_fails() -> None:
    parser = _ParserStub()
    orchestrator = _make_orchestrator(parser=parser, jira_provider=_JiraProviderFailureStub())

    with pytest.raises(RuntimeError, match="Jira testcase key detected but retrieval failed"):
        orchestrator.generate_feature(
            project_root="C:/tmp/project",
            testcase_text="создай мне автотест по SCBC-T3282",
        )


def test_jira_provider_stub_overrides_key_with_requested_one(tmp_path) -> None:
    stub_payload = """
    [
      {
        "key": "SCBC-T0001",
        "name": "Case one",
        "testScript": {"steps": [{"index": 0, "description": "step"}]}
      }
    ]
    """
    stub_path = tmp_path / "jira_stub.json"
    stub_path.write_text(stub_payload, encoding="utf-8")

    provider = JiraTestcaseProvider(
        settings=Settings(jira_source_mode="stub"),
        stub_payload_path=stub_path,
    )
    result = provider.fetch_testcase("SCBC-T3282")
    assert result["key"] == "SCBC-T3282"


def test_jira_provider_disabled_mode_raises() -> None:
    provider = JiraTestcaseProvider(settings=Settings(jira_source_mode="disabled"))
    with pytest.raises(RuntimeError, match="disabled"):
        provider.fetch_testcase("SCBC-T3282")
