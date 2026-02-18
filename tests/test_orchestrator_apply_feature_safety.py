from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.orchestrator import Orchestrator


class _RepoScannerStub:
    def scan_repository(self, _project_root: str) -> dict[str, Any]:
        return {}


class _ParserStub:
    def parse_testcase(self, _testcase_text: str) -> dict[str, Any]:
        return {"name": "n", "steps": []}


class _StepMatcherStub:
    def match_testcase_steps(self, _project_root: str, _scenario: dict[str, Any]) -> dict[str, Any]:
        return {"matched": [], "unmatched": [], "needsScan": False, "indexStatus": "ready"}


class _FeatureBuilderStub:
    def build_feature_from_matches(
        self,
        _scenario_dict: dict[str, Any],
        _matched_steps_dicts: list[dict[str, Any]],
        language: str | None = None,  # noqa: ARG002
    ) -> dict[str, Any]:
        return {"featureText": "Feature: generated\n", "unmappedSteps": []}


class _StepIndexStub:
    pass


class _EmbeddingsStub:
    def get_top_k(self, _project_root: str, _query: str, *, top_k: int = 5):  # noqa: ARG002
        return []


def _make_orchestrator() -> Orchestrator:
    return Orchestrator(
        repo_scanner_agent=_RepoScannerStub(),
        testcase_parser_agent=_ParserStub(),
        step_matcher_agent=_StepMatcherStub(),
        feature_builder_agent=_FeatureBuilderStub(),
        step_index_store=_StepIndexStub(),
        embeddings_store=_EmbeddingsStub(),
    )


def test_apply_feature_rejects_path_outside_project_root(tmp_path) -> None:
    orchestrator = _make_orchestrator()
    project_root = tmp_path / "project"
    project_root.mkdir()

    outside_path = project_root.parent / "outside.feature"
    result = orchestrator.apply_feature(
        project_root=str(project_root),
        target_path=str(outside_path),
        feature_text="Feature: blocked\n",
        overwrite_existing=False,
    )

    assert result["status"] == "rejected_outside_project"
    assert not outside_path.exists()


def test_apply_feature_writes_inside_project_root(tmp_path) -> None:
    orchestrator = _make_orchestrator()
    project_root = tmp_path / "project"
    project_root.mkdir()

    result = orchestrator.apply_feature(
        project_root=str(project_root),
        target_path="features/new.feature",
        feature_text="Feature: ok\n",
        overwrite_existing=False,
    )

    target_path = project_root / Path(result["targetPath"])
    assert result["status"] == "created"
    assert target_path.exists()
    assert target_path.read_text(encoding="utf-8") == "Feature: ok\n"

