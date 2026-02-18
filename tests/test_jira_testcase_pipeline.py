from __future__ import annotations

from typing import Any

import pytest

import integrations.jira_testcase_provider as jira_provider_module
from agents.orchestrator import Orchestrator
from app.config import Settings
from integrations.jira_testcase_normalizer import normalize_jira_testcase, normalize_jira_testcase_to_text
from integrations.jira_testcase_provider import JiraTestcaseProvider, extract_jira_testcase_key


class _RepoScannerStub:
    def scan_repository(self, _project_root: str) -> dict[str, Any]:
        return {}


class _ParserStub:
    def __init__(self, *, tags: list[str] | None = None) -> None:
        self.received_text: str | None = None
        self.tags = list(tags or [])

    def parse_testcase(self, testcase_text: str) -> dict[str, Any]:
        self.received_text = testcase_text
        return {
            "name": "Resolved scenario",
            "description": None,
            "preconditions": [],
            "steps": [{"order": 1, "text": "step one"}],
            "expected_result": None,
            "tags": list(self.tags),
            "normalization": {
                "inputSteps": 1,
                "normalizedSteps": 1,
                "splitCount": 0,
                "llmFallbackUsed": False,
            },
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
    assert extract_jira_testcase_key("please generate autotest for scbc-t1") == "SCBC-T1"
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

    assert "[Android] Demo testcase" in normalized
    assert "Toggle enabled" not in normalized
    assert "1. First action" in normalized
    assert "2. Second action" in normalized
    assert "3. Third action" in normalized
    assert "<strong>" not in normalized


def test_normalize_jira_testcase_keeps_precondition_only_in_report() -> None:
    payload = {
        "name": "[Android] Demo testcase",
        "precondition": "<strong>Toggle enabled</strong><br/>Client prepared",
        "testScript": {"steps": [{"index": 0, "description": "Authorize"}]},
    }

    normalized, report = normalize_jira_testcase(payload)

    assert "Toggle enabled" not in normalized
    assert report["preconditionText"] == "Toggle enabled\nClient prepared"


def test_normalize_jira_testcase_uses_key_as_name_for_special_stub() -> None:
    payload = {
        "key": "SCBC-T1",
        "name": "[Android] Jira sourced testcase",
        "testScript": {"steps": [{"index": 0, "description": "one"}]},
    }

    normalized = normalize_jira_testcase_to_text(payload)
    assert "SCBC-T1" in normalized


def test_normalize_jira_testcase_splits_compound_gherkin_block() -> None:
    payload = {
        "name": "[Android] Split block testcase",
        "testScript": {
            "steps": [
                {
                    "index": 0,
                    "description": "<pre>Дано подготовим среду И авторизуемся клиентом И запомним сессию</pre>",
                }
            ]
        },
    }

    normalized, report = normalize_jira_testcase(payload)

    assert "1. Дано подготовим среду" in normalized
    assert "2. И авторизуемся клиентом" in normalized
    assert "3. И запомним сессию" in normalized
    assert report["inputSteps"] == 1
    assert report["normalizedSteps"] == 3
    assert report["splitCount"] == 2


def test_orchestrator_resolves_jira_key_before_parse() -> None:
    payload = {
        "name": "[Android] Jira sourced testcase",
        "precondition": "Client has active card",
        "testScript": {
            "steps": [
                {"index": 0, "description": "Authorize", "expectedResult": "Home screen is opened"}
            ]
        },
    }
    parser = _ParserStub()
    jira_provider = _JiraProviderStub(payload)
    orchestrator = _make_orchestrator(parser=parser, jira_provider=jira_provider)

    result = orchestrator.generate_feature(
        project_root="C:/tmp/project",
        testcase_text="create autotest for SCBC-T1",
    )

    assert jira_provider.last_key == "SCBC-T1"
    assert parser.received_text is not None
    assert "Jira sourced testcase" in parser.received_text
    assert "Client has active card" not in parser.received_text
    assert result["pipeline"][0]["stage"] == "source_resolve"
    assert result["pipeline"][0]["status"] == "jira_stub_fixed"
    assert result["pipeline"][0]["details"]["jiraKey"] == "SCBC-T1"
    assert result["pipeline"][1]["stage"] == "normalization"
    assert result["pipeline"][1]["details"]["inputSteps"] == 1
    assert result["scenario"]["tags"] == ["TmsLink=SCBC-T1"]
    assert result["scenario"]["description"] is None


def test_orchestrator_adds_non_scbc_jira_key_to_scenario_tags() -> None:
    payload = {
        "name": "[Android] Jira sourced testcase",
        "testScript": {"steps": [{"index": 0, "description": "Authorize"}]},
    }
    parser = _ParserStub()
    jira_provider = _JiraProviderStub(payload)
    orchestrator = _make_orchestrator(parser=parser, jira_provider=jira_provider)

    result = orchestrator.generate_feature(
        project_root="C:/tmp/project",
        testcase_text="create autotest for ABCD-42",
    )

    assert jira_provider.last_key == "ABCD-42"
    assert result["pipeline"][0]["status"] == "jira_live"
    assert result["scenario"]["tags"] == ["TmsLink=ABCD-42"]


def test_orchestrator_replaces_existing_scenario_tags_with_tmslink() -> None:
    payload = {
        "name": "[Android] Jira sourced testcase",
        "testScript": {"steps": [{"index": 0, "description": "Authorize"}]},
    }
    parser = _ParserStub(tags=["smoke", "scbc-t1"])
    jira_provider = _JiraProviderStub(payload)
    orchestrator = _make_orchestrator(parser=parser, jira_provider=jira_provider)

    result = orchestrator.generate_feature(
        project_root="C:/tmp/project",
        testcase_text="create autotest for SCBC-T1",
    )

    assert result["scenario"]["tags"] == ["TmsLink=SCBC-T1"]


def test_orchestrator_fails_fast_when_jira_fetch_fails() -> None:
    parser = _ParserStub()
    orchestrator = _make_orchestrator(parser=parser, jira_provider=_JiraProviderFailureStub())

    with pytest.raises(RuntimeError, match="Jira testcase key detected but retrieval failed"):
        orchestrator.generate_feature(
            project_root="C:/tmp/project",
            testcase_text="create autotest for SCBC-T1",
        )


def test_jira_provider_returns_special_stub_payload_for_scbc_key(tmp_path) -> None:
    stub_payload = """
    {
      "key": "SCBC-T1",
      "name": "Case one",
      "testScript": {"steps": [{"index": 0, "description": "step"}]}
    }
    """
    stub_path = tmp_path / "jira_stub_special.json"
    stub_path.write_text(stub_payload, encoding="utf-8")

    provider = JiraTestcaseProvider(
        settings=Settings(jira_source_mode="stub"),
        stub_payload_path=stub_path,
    )
    result = provider.fetch_testcase("SCBC-T1")
    assert result["key"] == "SCBC-T1"
    assert result["name"] == "Case one"


def test_jira_provider_non_special_key_uses_live_fetch_even_when_mode_is_stub(monkeypatch) -> None:
    provider = JiraTestcaseProvider(settings=Settings(jira_source_mode="stub"))

    def _fake_fetch_live(
        key: str,
        *,
        auth: dict[str, Any] | None,
        jira_instance: str | None,
    ) -> dict[str, Any]:
        assert key == "SCBC-T9999"
        assert auth is None
        assert jira_instance is None
        return {"key": key, "name": "live"}

    monkeypatch.setattr(provider, "_fetch_live", _fake_fetch_live)
    result = provider.fetch_testcase("scbc-t9999")
    assert result["key"] == "SCBC-T9999"
    assert result["name"] == "live"


def test_jira_provider_disabled_mode_raises_for_non_special_key() -> None:
    provider = JiraTestcaseProvider(settings=Settings(jira_source_mode="disabled"))
    with pytest.raises(RuntimeError, match="disabled"):
        provider.fetch_testcase("SCBC-T9999")


def test_jira_provider_live_client_uses_verify_false_when_disabled(monkeypatch) -> None:
    provider = JiraTestcaseProvider(
        settings=Settings(
            jira_source_mode="live",
            jira_verify_ssl=False,
        )
    )
    captured: dict[str, Any] = {}

    class _ResponseStub:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"key": "SCBC-T9999", "testScript": {"steps": [{"index": 0, "description": "step"}]}}

    class _ClientStub:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["client_kwargs"] = kwargs

        def __enter__(self) -> "_ClientStub":
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:
            return None

        def get(self, *args: Any, **kwargs: Any) -> _ResponseStub:
            captured["get_kwargs"] = kwargs
            return _ResponseStub()

    monkeypatch.setattr(jira_provider_module.httpx, "Client", _ClientStub)
    provider.fetch_testcase("SCBC-T9999")
    assert captured["client_kwargs"]["verify"] is False


def test_jira_provider_live_client_uses_ca_bundle_when_configured(monkeypatch) -> None:
    provider = JiraTestcaseProvider(
        settings=Settings(
            jira_source_mode="live",
            jira_verify_ssl=True,
            jira_ca_bundle_file="C:/certs/jira-ca.pem",
        )
    )
    captured: dict[str, Any] = {}

    class _ResponseStub:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"key": "SCBC-T9999", "testScript": {"steps": [{"index": 0, "description": "step"}]}}

    class _ClientStub:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["client_kwargs"] = kwargs

        def __enter__(self) -> "_ClientStub":
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:
            return None

        def get(self, *args: Any, **kwargs: Any) -> _ResponseStub:
            captured["get_kwargs"] = kwargs
            return _ResponseStub()

    monkeypatch.setattr(jira_provider_module.httpx, "Client", _ClientStub)
    provider.fetch_testcase("SCBC-T9999")
    assert captured["client_kwargs"]["verify"] == "C:/certs/jira-ca.pem"
