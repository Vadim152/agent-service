"""Orchestrator facade for steps scan and feature generation workflows."""
from __future__ import annotations

import logging
from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from agents.feature_builder_agent import FeatureBuilderAgent
from agents.repo_scanner_agent import RepoScannerAgent
from agents.step_matcher_agent import StepMatcherAgent
from agents.testcase_parser_agent import TestcaseParserAgent
from infrastructure.embeddings_store import EmbeddingsStore
from infrastructure.fs_repo import FsRepository
from infrastructure.llm_client import LLMClient
from infrastructure.project_learning_store import ProjectLearningStore
from infrastructure.step_index_store import StepIndexStore
from integrations.jira_testcase_normalizer import normalize_jira_testcase_to_text
from integrations.jira_testcase_provider import JiraTestcaseProvider, extract_jira_testcase_key
from self_healing.capabilities import CapabilityRegistry

logger = logging.getLogger(__name__)


class ScanState(TypedDict):
    project_root: str
    result: dict[str, Any]


class FeatureGenerationState(TypedDict, total=False):
    project_root: str
    testcase_text: str
    zephyr_auth: dict[str, Any] | None
    jira_instance: str | None
    target_path: str | None
    create_file: bool
    overwrite_existing: bool
    language: str | None
    resolved_testcase_source: str | None
    resolved_testcase_key: str | None
    scenario: dict[str, Any]
    match_result: dict[str, Any]
    feature: dict[str, Any]
    file_status: dict[str, Any] | None
    pipeline: list[dict[str, Any]]


class Orchestrator:
    """Coordinates domain agents and exposes capability-style methods."""

    def __init__(
        self,
        repo_scanner_agent: RepoScannerAgent,
        testcase_parser_agent: TestcaseParserAgent,
        step_matcher_agent: StepMatcherAgent,
        feature_builder_agent: FeatureBuilderAgent,
        step_index_store: StepIndexStore,
        embeddings_store: EmbeddingsStore,
        project_learning_store: ProjectLearningStore | None = None,
        llm_client: LLMClient | None = None,
        jira_testcase_provider: JiraTestcaseProvider | None = None,
    ) -> None:
        self.repo_scanner_agent = repo_scanner_agent
        self.testcase_parser_agent = testcase_parser_agent
        self.step_matcher_agent = step_matcher_agent
        self.feature_builder_agent = feature_builder_agent
        self.step_index_store = step_index_store
        self.embeddings_store = embeddings_store
        self.project_learning_store = project_learning_store
        self.llm_client = llm_client
        self.jira_testcase_provider = jira_testcase_provider or JiraTestcaseProvider()

        self.capability_registry = CapabilityRegistry()
        self._register_default_capabilities()
        self._scan_graph = self._build_scan_graph()
        self._feature_graph = self._build_feature_graph()

    def _register_default_capabilities(self) -> None:
        self.capability_registry.register("scan_steps", self.scan_steps)
        self.capability_registry.register("find_steps", self.find_steps)
        self.capability_registry.register("parse_testcase", self.testcase_parser_agent.parse_testcase)
        self.capability_registry.register("match_steps", self.step_matcher_agent.match_testcase_steps)
        self.capability_registry.register("build_feature", self.feature_builder_agent.build_feature_from_matches)
        self.capability_registry.register("compose_autotest", self.compose_autotest)
        self.capability_registry.register("explain_unmapped", self.explain_unmapped)
        self.capability_registry.register("apply_feature", self.apply_feature)
        self.capability_registry.register("run_test_execution", self.generate_feature)
        self.capability_registry.register("collect_run_artifacts", lambda *_args, **_kwargs: {})
        self.capability_registry.register("classify_failure", lambda *_args, **_kwargs: {})
        self.capability_registry.register("apply_remediation", lambda *_args, **_kwargs: {})
        self.capability_registry.register("rerun_with_strategy", self.generate_feature)
        self.capability_registry.register("incident_report_builder", lambda *_args, **_kwargs: {})

    def _build_scan_graph(self):
        graph = StateGraph(ScanState)
        graph.add_node("scan_repository", self._scan_repository_node())
        graph.set_entry_point("scan_repository")
        graph.add_edge("scan_repository", END)
        return graph.compile()

    def _build_feature_graph(self):
        graph = StateGraph(FeatureGenerationState)
        graph.add_node("resolve_testcase_source", self._resolve_testcase_source_node())
        graph.add_node("parse_testcase", self._parse_testcase_node())
        graph.add_node("match_steps", self._match_steps_node())
        graph.add_node("build_feature", self._build_feature_node())
        graph.add_node("assemble_pipeline", self._assemble_pipeline_node())
        graph.add_node("apply_feature", self._apply_feature_node())
        graph.add_node("skip_apply", lambda _: {"file_status": None})
        graph.set_entry_point("resolve_testcase_source")
        graph.add_edge("resolve_testcase_source", "parse_testcase")
        graph.add_edge("parse_testcase", "match_steps")
        graph.add_edge("match_steps", "build_feature")
        graph.add_edge("build_feature", "assemble_pipeline")
        graph.add_conditional_edges(
            "assemble_pipeline",
            self._should_apply_feature,
            {"apply_feature": "apply_feature", "skip_apply": "skip_apply"},
        )
        graph.add_edge("apply_feature", END)
        graph.add_edge("skip_apply", END)
        return graph.compile()

    def _resolve_testcase_source_node(self) -> Callable[[FeatureGenerationState], dict[str, Any]]:
        def _node(state: FeatureGenerationState) -> dict[str, Any]:
            raw_text = state.get("testcase_text", "")
            key = extract_jira_testcase_key(raw_text)
            if not key:
                return {
                    "resolved_testcase_source": "raw_text",
                    "resolved_testcase_key": None,
                }

            try:
                payload = self.jira_testcase_provider.fetch_testcase(
                    key,
                    auth=state.get("zephyr_auth"),
                    jira_instance=state.get("jira_instance"),
                )
                normalized = normalize_jira_testcase_to_text(payload)
                if not normalized.strip():
                    raise RuntimeError(f"normalized testcase is empty for {key}")
            except Exception as exc:
                raise RuntimeError(
                    f"Jira testcase key detected but retrieval failed: {exc}"
                ) from exc

            source = "jira_stub_fixed" if key.upper() == "SCBC-T1" else "jira_live"
            logger.info("[Orchestrator] Resolved testcase key %s from %s", key, source)
            return {
                "testcase_text": normalized,
                "resolved_testcase_source": source,
                "resolved_testcase_key": key,
            }

        return _node

    def _scan_repository_node(self) -> Callable[[ScanState], dict[str, Any]]:
        def _node(state: ScanState) -> dict[str, Any]:
            result = self.repo_scanner_agent.scan_repository(state["project_root"])
            return {"result": result}

        return _node

    def _parse_testcase_node(self) -> Callable[[FeatureGenerationState], dict[str, Any]]:
        def _node(state: FeatureGenerationState) -> dict[str, Any]:
            scenario_dict = self.testcase_parser_agent.parse_testcase(state["testcase_text"])
            resolved_key = state.get("resolved_testcase_key")
            if resolved_key:
                scenario_dict["tags"] = self._merge_scenario_tags(
                    scenario_dict.get("tags"),
                    resolved_key,
                )
            return {"scenario": scenario_dict}

        return _node

    @staticmethod
    def _merge_scenario_tags(existing_tags: Any, testcase_key: str) -> list[str]:
        tags: list[str] = []
        if isinstance(existing_tags, list):
            tags = [str(tag).strip() for tag in existing_tags if str(tag).strip()]
        elif isinstance(existing_tags, (tuple, set)):
            tags = [str(tag).strip() for tag in existing_tags if str(tag).strip()]
        elif existing_tags:
            value = str(existing_tags).strip()
            if value:
                tags = [value]

        key_value = str(testcase_key).strip()
        if key_value:
            tags.append(key_value)

        deduped: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            marker = tag.upper()
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(tag)
        return deduped

    def _match_steps_node(self) -> Callable[[FeatureGenerationState], dict[str, Any]]:
        def _node(state: FeatureGenerationState) -> dict[str, Any]:
            matched = self.step_matcher_agent.match_testcase_steps(
                state["project_root"], state["scenario"]
            )
            return {"match_result": matched}

        return _node

    def _build_feature_node(self) -> Callable[[FeatureGenerationState], dict[str, Any]]:
        def _node(state: FeatureGenerationState) -> dict[str, Any]:
            feature_result = self.feature_builder_agent.build_feature_from_matches(
                state["scenario"],
                state.get("match_result", {}).get("matched", []),
                language=state.get("language"),
            )
            return {"feature": feature_result}

        return _node

    def _assemble_pipeline_node(self) -> Callable[[FeatureGenerationState], dict[str, Any]]:
        def _node(state: FeatureGenerationState) -> dict[str, Any]:
            pipeline = [
                {
                    "stage": "source_resolve",
                    "status": state.get("resolved_testcase_source") or "raw_text",
                    "details": {
                        "jiraKey": state.get("resolved_testcase_key"),
                    },
                },
                {
                    "stage": "parse",
                    "status": "ok",
                    "details": {
                        "source": state.get("scenario", {}).get("source"),
                        "steps": len(state.get("scenario", {}).get("steps", [])),
                    },
                },
                {
                    "stage": "match",
                    "status": "needs_scan"
                    if state.get("match_result", {}).get("needsScan")
                    else "ok",
                    "details": {
                        "matched": len(state.get("match_result", {}).get("matched", [])),
                        "unmatched": len(state.get("match_result", {}).get("unmatched", [])),
                        "indexStatus": state.get("match_result", {}).get("indexStatus", "unknown"),
                    },
                },
                {
                    "stage": "feature_build",
                    "status": state.get("feature", {}).get("buildStage") or "ok",
                    "details": {
                        "stepsSummary": state.get("feature", {}).get("stepsSummary"),
                        "language": state.get("feature", {}).get("meta", {}).get("language"),
                    },
                },
            ]
            return {"pipeline": pipeline}

        return _node

    def _apply_feature_node(self) -> Callable[[FeatureGenerationState], dict[str, Any]]:
        def _node(state: FeatureGenerationState) -> dict[str, Any]:
            file_status: dict[str, Any] | None = None
            if state.get("target_path"):
                feature_text = state.get("feature", {}).get("featureText", "")
                file_status = self.apply_feature(
                    state["project_root"],
                    state["target_path"],
                    feature_text,
                    overwrite_existing=state.get("overwrite_existing", False),
                )
            return {"file_status": file_status}

        return _node

    @staticmethod
    def _should_apply_feature(state: FeatureGenerationState) -> str:
        if state.get("create_file") and state.get("target_path"):
            return "apply_feature"
        return "skip_apply"

    def scan_steps(self, project_root: str) -> dict[str, Any]:
        logger.info("[Orchestrator] Start steps scan: %s", project_root)
        state = self._scan_graph.invoke({"project_root": project_root})
        result = state["result"]
        logger.info("[Orchestrator] Steps scan done: %s", result)
        return result

    def find_steps(self, project_root: str, query: str, *, top_k: int = 5) -> dict[str, Any]:
        candidates = self.embeddings_store.get_top_k(project_root, query, top_k=top_k)
        return {
            "projectRoot": project_root,
            "query": query,
            "items": [
                {
                    "step": item.pattern,
                    "stepId": item.id,
                    "keyword": item.keyword.value,
                    "score": score,
                    "codeRef": item.code_ref,
                }
                for item, score in candidates
            ],
        }

    def compose_autotest(
        self,
        project_root: str,
        testcase_text: str,
        *,
        language: str | None = None,
    ) -> dict[str, Any]:
        return self.generate_feature(
            project_root=project_root,
            testcase_text=testcase_text,
            target_path=None,
            create_file=False,
            overwrite_existing=False,
            language=language,
        )

    @staticmethod
    def explain_unmapped(match_result: dict[str, Any]) -> dict[str, Any]:
        unmatched = list(match_result.get("unmatched", []))
        return {
            "count": len(unmatched),
            "items": [
                {
                    "step": text,
                    "reason": "no indexed step matched with acceptable confidence",
                }
                for text in unmatched
            ],
        }

    def generate_feature(
        self,
        project_root: str,
        testcase_text: str,
        target_path: str | None = None,
        *,
        create_file: bool = False,
        overwrite_existing: bool = False,
        language: str | None = None,
        zephyr_auth: dict[str, Any] | None = None,
        jira_instance: str | None = None,
    ) -> dict[str, Any]:
        logger.info("[Orchestrator] Generate feature for project %s", project_root)
        state = self._feature_graph.invoke(
            {
                "project_root": project_root,
                "testcase_text": testcase_text,
                "zephyr_auth": zephyr_auth,
                "jira_instance": jira_instance,
                "target_path": target_path,
                "create_file": create_file,
                "overwrite_existing": overwrite_existing,
                "language": language,
            }
        )
        scenario_dict = state.get("scenario", {})
        match_result = state.get("match_result", {})
        feature_result = state.get("feature", {})
        pipeline = state.get("pipeline", [])
        file_status = state.get("file_status")

        logger.info(
            "[Orchestrator] Feature generation done. Unmapped=%s",
            len(feature_result.get("unmappedSteps", [])),
        )
        return {
            "projectRoot": project_root,
            "scenario": scenario_dict,
            "matchResult": match_result,
            "feature": feature_result,
            "pipeline": pipeline,
            "fileStatus": file_status,
        }

    def apply_feature(
        self,
        project_root: str,
        target_path: str,
        feature_text: str,
        *,
        overwrite_existing: bool = False,
    ) -> dict[str, Any]:
        logger.info("[Orchestrator] Persist feature %s in %s", target_path, project_root)
        fs_repo = FsRepository(project_root)
        normalized_path = target_path.lstrip("/")
        exists = fs_repo.exists(normalized_path)

        if exists and not overwrite_existing:
            return {
                "projectRoot": project_root,
                "targetPath": target_path,
                "status": "skipped",
                "message": "File already exists and overwrite is disabled",
            }

        fs_repo.write_text_file(normalized_path, feature_text, create_dirs=True)
        status = "overwritten" if exists else "created"
        return {
            "projectRoot": project_root,
            "targetPath": normalized_path,
            "status": status,
            "message": None,
        }


__all__ = ["Orchestrator"]
