"""Orchestrator facade for steps scan and feature generation workflows."""
from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from agents.feature_builder_agent import FeatureBuilderAgent
from agents.repo_scanner_agent import RepoScannerAgent
from agents.step_matcher_agent import StepMatcherAgent
from agents.testcase_parser_agent import TestcaseParserAgent
from domain.enums import MatchStatus, StepIntentType, StepKeyword
from infrastructure.embeddings_store import EmbeddingsStore
from infrastructure.fs_repo import FsRepository
from infrastructure.llm_client import LLMClient
from infrastructure.preview_plan_store import PreviewPlanStore
from infrastructure.scenario_index_store import ScenarioIndexStore
from infrastructure.step_index_store import StepIndexStore
from integrations.jira_testcase_normalizer import normalize_jira_testcase
from integrations.jira_testcase_provider import JiraTestcaseProvider, extract_jira_testcase_key
from memory.service import MemoryService
from self_healing.capabilities import CapabilityRegistry
from tools.generation_quality import evaluate_generation_quality, normalize_quality_policy
from tools.scenario_catalog import match_fragments

logger = logging.getLogger(__name__)


class ScanState(TypedDict):
    project_root: str
    additional_roots: list[str]
    provided_steps: list[Any]
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
    quality_policy: str
    explicit_quality_policy: bool
    explicit_language: bool
    explicit_target_path: bool
    plan_id: str | None
    selected_scenario_id: str | None
    binding_overrides: list[dict[str, Any]]
    template_steps: list[str]
    applied_rule_ids: list[str]
    applied_template_ids: list[str]
    resolved_testcase_source: str | None
    resolved_testcase_key: str | None
    normalization_report: dict[str, Any] | None
    scenario: dict[str, Any]
    match_result: dict[str, Any]
    feature: dict[str, Any]
    quality_report: dict[str, Any]
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
        scenario_index_store: ScenarioIndexStore | None = None,
        preview_plan_store: PreviewPlanStore | None = None,
        project_learning_store: MemoryService | None = None,
        llm_client: LLMClient | None = None,
        jira_testcase_provider: JiraTestcaseProvider | None = None,
    ) -> None:
        self.repo_scanner_agent = repo_scanner_agent
        self.testcase_parser_agent = testcase_parser_agent
        self.step_matcher_agent = step_matcher_agent
        self.feature_builder_agent = feature_builder_agent
        self.step_index_store = step_index_store
        self.embeddings_store = embeddings_store
        self.scenario_index_store = scenario_index_store
        self.preview_plan_store = preview_plan_store
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
        self.capability_registry.register("preview_generation_plan", self.preview_generation_plan)
        self.capability_registry.register("compose_autotest", self.compose_autotest)
        self.capability_registry.register("explain_unmapped", self.explain_unmapped)
        self.capability_registry.register("apply_feature", self.apply_feature)
        self.capability_registry.register("review_and_apply_feature", self.review_and_apply_feature)
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
        graph.add_node("resolve_memory_preferences", self._resolve_memory_preferences_node())
        graph.add_node("parse_testcase", self._parse_testcase_node())
        graph.add_node("inject_template_steps", self._inject_template_steps_node())
        graph.add_node("match_steps", self._match_steps_node())
        graph.add_node("build_feature", self._build_feature_node())
        graph.add_node("assemble_pipeline", self._assemble_pipeline_node())
        graph.add_node("evaluate_quality", self._evaluate_quality_node())
        graph.add_node("apply_feature", self._apply_feature_node())
        graph.add_node("skip_apply", self._skip_apply_node())
        graph.set_entry_point("resolve_testcase_source")
        graph.add_edge("resolve_testcase_source", "resolve_memory_preferences")
        graph.add_edge("resolve_memory_preferences", "parse_testcase")
        graph.add_edge("parse_testcase", "inject_template_steps")
        graph.add_edge("inject_template_steps", "match_steps")
        graph.add_edge("match_steps", "build_feature")
        graph.add_edge("build_feature", "assemble_pipeline")
        graph.add_edge("assemble_pipeline", "evaluate_quality")
        graph.add_conditional_edges(
            "evaluate_quality",
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
                    "normalization_report": None,
                }

            try:
                payload = self.jira_testcase_provider.fetch_testcase(
                    key,
                    auth=state.get("zephyr_auth"),
                    jira_instance=state.get("jira_instance"),
                )
                normalized, normalization_report = normalize_jira_testcase(
                    payload,
                    llm_client=None,
                )
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
                "normalization_report": normalization_report,
            }

        return _node

    def _scan_repository_node(self) -> Callable[[ScanState], dict[str, Any]]:
        def _node(state: ScanState) -> dict[str, Any]:
            try:
                result = self.repo_scanner_agent.scan_repository(
                    state["project_root"],
                    additional_roots=state.get("additional_roots", []),
                    provided_steps=state.get("provided_steps", []),
                )
            except TypeError:
                result = self.repo_scanner_agent.scan_repository(state["project_root"])
            return {"result": result}

        return _node

    def _parse_testcase_node(self) -> Callable[[FeatureGenerationState], dict[str, Any]]:
        def _node(state: FeatureGenerationState) -> dict[str, Any]:
            scenario_dict = self.testcase_parser_agent.parse_testcase(state["testcase_text"])
            resolved_key = state.get("resolved_testcase_key")
            if resolved_key:
                scenario_dict["tags"] = [f"TmsLink={str(resolved_key).strip()}"]
            return {"scenario": scenario_dict}

        return _node

    def _resolve_memory_preferences_node(self) -> Callable[[FeatureGenerationState], dict[str, Any]]:
        def _node(state: FeatureGenerationState) -> dict[str, Any]:
            if not self.project_learning_store:
                return {
                    "template_steps": [],
                    "applied_rule_ids": [],
                    "applied_template_ids": [],
                }
            resolved_key = state.get("resolved_testcase_key")
            resolved = self.project_learning_store.resolve_generation_preferences(
                project_root=state["project_root"],
                text=state.get("testcase_text", ""),
                jira_key=str(resolved_key).strip() if resolved_key else None,
                language=state.get("language"),
                quality_policy=state.get("quality_policy"),
            )
            updated: dict[str, Any] = {
                "template_steps": list(resolved.get("templateSteps", [])),
                "applied_rule_ids": list(resolved.get("appliedRuleIds", [])),
                "applied_template_ids": list(resolved.get("appliedTemplateIds", [])),
            }
            if not bool(state.get("explicit_quality_policy", False)) and resolved.get("qualityPolicy"):
                updated["quality_policy"] = resolved.get("qualityPolicy")
            if not bool(state.get("explicit_language", False)) and resolved.get("language"):
                updated["language"] = resolved.get("language")
            if not bool(state.get("explicit_target_path", False)) and resolved.get("targetPath"):
                updated["target_path"] = resolved.get("targetPath")
            return updated

        return _node

    def _inject_template_steps_node(self) -> Callable[[FeatureGenerationState], dict[str, Any]]:
        def _node(state: FeatureGenerationState) -> dict[str, Any]:
            template_steps = [str(item).strip() for item in state.get("template_steps", []) if str(item).strip()]
            if not template_steps:
                return {"template_steps": []}
            scenario = dict(state.get("scenario", {}))
            original_steps = list(scenario.get("steps", []))
            injected = [{"order": idx + 1, "text": step, "section": "template"} for idx, step in enumerate(template_steps)]
            merged = injected + [
                {
                    "order": len(injected) + idx + 1,
                    "text": str(item.get("text", "")),
                    "section": item.get("section"),
                }
                for idx, item in enumerate(original_steps)
                if isinstance(item, dict) and str(item.get("text", "")).strip()
            ]
            scenario["steps"] = merged
            return {"scenario": scenario}

        return _node

    def _match_steps_node(self) -> Callable[[FeatureGenerationState], dict[str, Any]]:
        def _node(state: FeatureGenerationState) -> dict[str, Any]:
            matched = self.step_matcher_agent.match_testcase_steps(
                state["project_root"], state["scenario"]
            )
            if state.get("binding_overrides"):
                matched = self._apply_binding_overrides_to_match_result(
                    state["project_root"],
                    matched,
                    list(state.get("binding_overrides", [])),
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
            normalization_details = self._compose_normalization_details(
                state.get("normalization_report"),
                state.get("scenario", {}).get("normalization"),
            )
            pipeline = [
                {
                    "stage": "source_resolve",
                    "status": state.get("resolved_testcase_source") or "raw_text",
                    "details": {
                        "jiraKey": state.get("resolved_testcase_key"),
                    },
                },
                {
                    "stage": "normalization",
                    "status": "ok",
                    "details": normalization_details,
                },
                {
                    "stage": "parse",
                    "status": "ok",
                    "details": {
                        "source": state.get("scenario", {}).get("source"),
                        "llmParseUsed": bool(
                            state.get("scenario", {})
                            .get("normalization", {})
                            .get("llmParseUsed")
                        ),
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
                        "exactDefinitionMatches": int(
                            state.get("match_result", {}).get("exactDefinitionMatches", 0)
                        ),
                        "sourceTextFallbackUsed": int(
                            state.get("match_result", {}).get("sourceTextFallbackUsed", 0)
                        ),
                        "llmRerankedCount": int(
                            state.get("match_result", {}).get("llmRerankedCount", 0)
                        ),
                        "ambiguousCount": int(
                            state.get("match_result", {}).get("ambiguousCount", 0)
                        ),
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
                {
                    "stage": "memory_rules",
                    "status": "ok",
                    "details": {
                        "appliedRuleIds": list(state.get("applied_rule_ids", [])),
                        "appliedTemplateIds": list(state.get("applied_template_ids", [])),
                        "templateStepsAdded": len(state.get("template_steps", [])),
                    },
                },
                {
                    "stage": "parameter_fill",
                    "status": "ok",
                    "details": state.get("feature", {}).get("parameterFillSummary", {}),
                },
            ]
            return {"pipeline": pipeline}

        return _node

    @staticmethod
    def _compose_normalization_details(
        source_report: dict[str, Any] | None,
        parser_report: dict[str, Any] | None,
    ) -> dict[str, Any]:
        source_report = source_report or {}
        parser_report = parser_report or {}
        input_steps = source_report.get("inputSteps")
        if input_steps is None:
            input_steps = parser_report.get("inputSteps", 0)
        normalized_steps = parser_report.get("normalizedSteps")
        if normalized_steps is None:
            normalized_steps = source_report.get("normalizedSteps", 0)

        split_count = int(source_report.get("splitCount", 0)) + int(
            parser_report.get("splitCount", 0)
        )
        llm_fallback_used = bool(source_report.get("llmFallbackUsed")) or bool(
            parser_report.get("llmFallbackUsed")
        )
        details = {
            "inputSteps": input_steps,
            "normalizedSteps": normalized_steps,
            "splitCount": split_count,
            "llmFallbackUsed": llm_fallback_used,
            "llmParseUsed": bool(parser_report.get("llmParseUsed")),
        }
        return details

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

    def _skip_apply_node(self) -> Callable[[FeatureGenerationState], dict[str, Any]]:
        def _node(state: FeatureGenerationState) -> dict[str, Any]:
            if not (state.get("create_file") and state.get("target_path")):
                return {"file_status": None}
            quality = state.get("quality_report") or state.get("feature", {}).get("quality") or {}
            if bool(quality.get("passed", False)):
                return {"file_status": None}
            return {
                "file_status": {
                    "projectRoot": state.get("project_root"),
                    "targetPath": state.get("target_path"),
                    "status": "skipped_quality_gate",
                    "message": "Quality gate failed; feature was not written to disk",
                }
            }

        return _node

    def _evaluate_quality_node(self) -> Callable[[FeatureGenerationState], dict[str, Any]]:
        def _node(state: FeatureGenerationState) -> dict[str, Any]:
            feature_payload = dict(state.get("feature", {}))
            quality_report = evaluate_generation_quality(
                feature_payload=feature_payload,
                match_result=state.get("match_result", {}),
                scenario=state.get("scenario", {}),
                policy=state.get("quality_policy", "strict"),
            )
            feature_payload["quality"] = quality_report
            pipeline = list(state.get("pipeline", []))
            pipeline.append(
                {
                    "stage": "quality_gate",
                    "status": "passed" if quality_report.get("passed") else "failed",
                    "details": {
                        "policy": quality_report.get("policy"),
                        "score": quality_report.get("score"),
                        "failures": [
                            item.get("code")
                            for item in quality_report.get("failures", [])
                            if isinstance(item, dict)
                        ],
                    },
                }
            )
            return {
                "feature": feature_payload,
                "quality_report": quality_report,
                "pipeline": pipeline,
            }

        return _node

    @staticmethod
    def _should_apply_feature(state: FeatureGenerationState) -> str:
        quality = state.get("quality_report") or state.get("feature", {}).get("quality") or {}
        if (
            state.get("create_file")
            and state.get("target_path")
            and bool(quality.get("passed", False))
        ):
            return "apply_feature"
        return "skip_apply"

    def scan_steps(
        self,
        project_root: str,
        additional_roots: list[str] | None = None,
        provided_steps: list[Any] | None = None,
    ) -> dict[str, Any]:
        logger.info("[Orchestrator] Start steps scan: %s", project_root)
        state = self._scan_graph.invoke(
            {
                "project_root": project_root,
                "additional_roots": list(additional_roots or []),
                "provided_steps": list(provided_steps or []),
            }
        )
        result = state["result"]
        logger.info("[Orchestrator] Steps scan done: %s", result)
        return result

    def find_steps(
        self,
        project_root: str,
        query: str,
        *,
        top_k: int = 5,
        debug: bool = False,
    ) -> dict[str, Any]:
        candidates = self.embeddings_store.get_top_k(project_root, query, top_k=top_k)
        payload = {
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
        if debug:
            payload["debug"] = {
                "candidateCount": len(candidates),
                "topK": top_k,
            }
        return payload

    def preview_generation_plan(
        self,
        *,
        project_root: str,
        testcase_text: str,
        language: str | None = None,
        quality_policy: str | None = None,
        selected_scenario_id: str | None = None,
        binding_overrides: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        resolved = self._resolve_memory_preferences_for_preview(
            project_root=project_root,
            testcase_text=testcase_text,
            language=language,
            quality_policy=quality_policy,
        )
        scenario = self.testcase_parser_agent.parse_testcase(testcase_text)
        scenario = self._inject_template_steps_into_scenario(
            scenario,
            list(resolved.get("templateSteps", [])),
        )
        similar_scenarios = self._retrieve_similar_scenarios(
            project_root,
            scenario,
            selected_scenario_id=selected_scenario_id,
        )
        generation_plan = self._build_generation_plan(
            project_root,
            scenario,
            similar_scenarios=similar_scenarios,
            selected_scenario_id=selected_scenario_id,
            binding_overrides=binding_overrides or [],
        )
        match_result = self.step_matcher_agent.match_testcase_steps(project_root, scenario)
        if binding_overrides:
            match_result = self._apply_binding_overrides_to_match_result(
                project_root,
                match_result,
                binding_overrides,
            )
        feature = self.feature_builder_agent.build_feature_from_matches(
            scenario,
            match_result.get("matched", []),
            language=language,
        )
        quality = evaluate_generation_quality(
            feature_payload=feature,
            match_result=match_result,
            scenario=scenario,
            policy=quality_policy,
        )
        feature["quality"] = quality
        generation_plan["draftFeatureText"] = feature.get("featureText", "")
        generation_plan["warnings"] = list(
            dict.fromkeys(
                list(generation_plan.get("warnings", []))
                + [
                    str(item.get("code"))
                    for item in quality.get("warnings", [])
                    if isinstance(item, dict) and item.get("code")
                ]
            )
        )
        generation_plan["confidence"] = round(
            self._average(
                [
                    float(item.get("selectedConfidence") or 0.0)
                    for item in generation_plan.get("items", [])
                    if isinstance(item, dict)
                ]
            ),
            4,
        )
        stored_payload = {
            "projectRoot": project_root,
            "testcaseText": testcase_text,
            "language": language,
            "qualityPolicy": normalize_quality_policy(quality_policy),
            "selectedScenarioId": generation_plan.get("selectedScenarioId"),
            "bindingOverrides": list(binding_overrides or []),
            "scenario": scenario,
            "similarScenarios": similar_scenarios,
            "generationPlan": generation_plan,
            "matchResult": match_result,
            "feature": feature,
        }
        if self.preview_plan_store:
            stored_payload = self.preview_plan_store.create_plan(stored_payload)
        generation_plan["planId"] = stored_payload.get("planId")
        return {
            "planId": stored_payload.get("planId"),
            "canonicalTestCase": scenario.get("canonical"),
            "similarScenarios": similar_scenarios,
            "generationPlan": generation_plan,
            "draftFeatureText": feature.get("featureText", ""),
            "quality": quality,
            "warnings": generation_plan.get("warnings", []),
            "memoryPreview": resolved,
        }

    def review_and_apply_feature(
        self,
        *,
        project_root: str,
        plan_id: str | None,
        target_path: str,
        original_feature_text: str,
        edited_feature_text: str,
        overwrite_existing: bool = False,
        selected_scenario_id: str | None = None,
        accepted_step_ids: list[str] | None = None,
        rejected_step_ids: list[str] | None = None,
        binding_overrides: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        stored_plan = self.preview_plan_store.get_plan(plan_id) if (self.preview_plan_store and plan_id) else None
        scenario = stored_plan.get("scenario") if isinstance(stored_plan, dict) else {}
        match_result = stored_plan.get("matchResult") if isinstance(stored_plan, dict) else {}
        quality = evaluate_generation_quality(
            feature_payload={"featureText": edited_feature_text},
            match_result=match_result if isinstance(match_result, dict) else {},
            scenario=scenario if isinstance(scenario, dict) else {},
            policy=(stored_plan or {}).get("qualityPolicy"),
        )
        rewrite_rules = self._derive_rewrite_rules(original_feature_text, edited_feature_text)
        alias_candidates = self._derive_alias_candidates(
            scenario=scenario if isinstance(scenario, dict) else {},
            match_result=match_result if isinstance(match_result, dict) else {},
            binding_overrides=binding_overrides or [],
        )
        learning_snapshot = None
        if self.project_learning_store and hasattr(self.project_learning_store, "record_generation_review"):
            learning_snapshot = self.project_learning_store.record_generation_review(
                project_root=project_root,
                plan_id=plan_id,
                selected_scenario_id=selected_scenario_id or (stored_plan or {}).get("selectedScenarioId"),
                accepted_step_ids=accepted_step_ids or [],
                rejected_step_ids=rejected_step_ids or [],
                step_overrides=binding_overrides or [],
                alias_candidates=alias_candidates,
                rewrite_rules=rewrite_rules,
                review_meta={
                    "qualityPassed": bool(quality.get("passed")),
                    "qualityScore": quality.get("score"),
                },
            )
        file_status = self.apply_feature(
            project_root,
            target_path,
            edited_feature_text,
            overwrite_existing=overwrite_existing,
        )
        return {
            "planId": plan_id,
            "quality": quality,
            "fileStatus": file_status,
            "learning": {
                "rewriteRulesSaved": len(rewrite_rules),
                "aliasCandidatesSaved": len(alias_candidates),
                "selectedScenarioId": selected_scenario_id or (stored_plan or {}).get("selectedScenarioId"),
                "memoryUpdatedAt": learning_snapshot.get("updatedAt") if isinstance(learning_snapshot, dict) else None,
            },
        }

    def _resolve_memory_preferences_for_preview(
        self,
        *,
        project_root: str,
        testcase_text: str,
        language: str | None,
        quality_policy: str | None,
    ) -> dict[str, Any]:
        if not self.project_learning_store:
            return {
                "qualityPolicy": normalize_quality_policy(quality_policy),
                "language": language,
                "targetPath": None,
                "appliedRuleIds": [],
                "appliedTemplateIds": [],
                "templateSteps": [],
            }
        return self.project_learning_store.resolve_generation_preferences(
            project_root=project_root,
            text=testcase_text,
            jira_key=None,
            language=language,
            quality_policy=normalize_quality_policy(quality_policy),
        )

    @staticmethod
    def _inject_template_steps_into_scenario(
        scenario: dict[str, Any],
        template_steps: list[str],
    ) -> dict[str, Any]:
        if not template_steps:
            return scenario
        updated = dict(scenario)
        original_steps = list(updated.get("steps", []))
        injected = [
            {
                "order": index + 1,
                "text": text,
                "section": "template",
                "intent_type": StepIntentType.SETUP.value,
                "source_text": text,
            }
            for index, text in enumerate(template_steps)
            if str(text).strip()
        ]
        merged = injected + [
            {
                **item,
                "order": len(injected) + index + 1,
            }
            for index, item in enumerate(original_steps)
            if isinstance(item, dict) and str(item.get("text", "")).strip()
        ]
        updated["steps"] = merged
        return updated

    def _retrieve_similar_scenarios(
        self,
        project_root: str,
        scenario: dict[str, Any],
        *,
        selected_scenario_id: str | None = None,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        canonical = scenario.get("canonical") if isinstance(scenario, dict) else {}
        query_fragments = [
            str(canonical.get("title") or scenario.get("name") or "").strip(),
            *[
                str(item.get("text", "")).strip()
                for item in canonical.get("actions", [])
                if isinstance(item, dict)
            ],
            *[
                str(item.get("text", "")).strip()
                for item in canonical.get("expected_results", [])
                if isinstance(item, dict)
            ],
        ]
        query = "\n".join(fragment for fragment in query_fragments if fragment)
        scored = self.embeddings_store.get_top_k_scenarios(project_root, query, top_k=max(3, top_k))
        if not scored and self.scenario_index_store:
            fallback = self.scenario_index_store.load_scenarios(project_root)
            scored = [(item, 0.0) for item in fallback[:top_k]]
        preferences = (
            self.project_learning_store.get_scenario_preferences(project_root)
            if self.project_learning_store and hasattr(self.project_learning_store, "get_scenario_preferences")
            else {}
        )
        items: list[dict[str, Any]] = []
        for entry, score in scored[:top_k]:
            final_score = round(float(score) + float(preferences.get(entry.id, 0.0)), 4)
            items.append(
                {
                    "scenarioId": entry.id,
                    "name": entry.name,
                    "featurePath": entry.feature_path,
                    "score": final_score,
                    "matchedFragments": match_fragments(query_fragments, entry),
                    "backgroundSteps": list(entry.background_steps),
                    "steps": list(entry.steps),
                    "recommended": False,
                }
            )
        items.sort(
            key=lambda item: (
                item["scenarioId"] != selected_scenario_id if selected_scenario_id else False,
                -float(item.get("score", 0.0)),
                item.get("name", ""),
            )
        )
        if items:
            if selected_scenario_id:
                for item in items:
                    item["recommended"] = item.get("scenarioId") == selected_scenario_id
            else:
                items[0]["recommended"] = True
        return items[:top_k]

    def _build_generation_plan(
        self,
        project_root: str,
        scenario: dict[str, Any],
        *,
        similar_scenarios: list[dict[str, Any]],
        selected_scenario_id: str | None,
        binding_overrides: list[dict[str, Any]],
    ) -> dict[str, Any]:
        selected_id = selected_scenario_id or next(
            (item.get("scenarioId") for item in similar_scenarios if item.get("recommended")),
            None,
        )
        selected_scenario = next(
            (item for item in similar_scenarios if item.get("scenarioId") == selected_id),
            None,
        )
        items: list[dict[str, Any]] = []
        warnings: list[str] = []
        override_map = {
            (int(item.get("order")) if item.get("order") is not None else None): str(item.get("stepId"))
            for item in binding_overrides
            if isinstance(item, dict) and item.get("stepId")
        }
        for raw_step in scenario.get("steps", []):
            if not isinstance(raw_step, dict):
                continue
            text = str(raw_step.get("text", "")).strip()
            if not text:
                continue
            order = int(raw_step.get("order") or len(items) + 1)
            intent_value = raw_step.get("intent_type") or StepIntentType.ACTION.value
            try:
                intent_type = StepIntentType(intent_value)
            except ValueError:
                intent_type = StepIntentType.ACTION
            candidates = self.embeddings_store.get_top_k(project_root, text, top_k=3)
            binding_candidates = [
                self._build_binding_candidate(step_definition, score)
                for step_definition, score in candidates
            ]
            selected_step_id = override_map.get(order) or next(
                (
                    candidate["stepId"]
                    for candidate in binding_candidates
                    if candidate["status"] != MatchStatus.UNMATCHED.value
                ),
                None,
            )
            selected_confidence = next(
                (
                    candidate["confidence"]
                    for candidate in binding_candidates
                    if candidate["stepId"] == selected_step_id
                ),
                0.0,
            )
            if not binding_candidates or all(
                candidate["status"] == MatchStatus.UNMATCHED.value for candidate in binding_candidates
            ):
                warnings.append(f"unmatched:{order}")
            elif any(candidate["status"] == MatchStatus.FUZZY.value for candidate in binding_candidates[:1]):
                warnings.append(f"weak:{order}")
            items.append(
                {
                    "order": order,
                    "text": text,
                    "intentType": intent_type.value,
                    "section": str(raw_step.get("section") or "step"),
                    "keyword": self._keyword_for_intent(intent_type).value,
                    "bindingCandidates": binding_candidates,
                    "selectedStepId": selected_step_id,
                    "selectedConfidence": selected_confidence,
                    "warning": None,
                }
            )
        return {
            "planId": None,
            "source": "retrieval_driven",
            "recommendedScenarioId": selected_id,
            "selectedScenarioId": selected_id,
            "candidateBackground": list((selected_scenario or {}).get("backgroundSteps") or []),
            "items": items,
            "warnings": list(dict.fromkeys(warnings)),
            "confidence": 0.0,
            "draftFeatureText": "",
        }

    def _build_binding_candidate(self, step_definition, score: float) -> dict[str, Any]:
        if score >= self.step_matcher_agent.matcher.config.threshold_exact:
            status = MatchStatus.EXACT
        elif score >= self.step_matcher_agent.matcher.config.threshold_fuzzy:
            status = MatchStatus.FUZZY
        else:
            status = MatchStatus.UNMATCHED
        return {
            "stepId": step_definition.id,
            "stepText": step_definition.pattern,
            "status": status.value,
            "confidence": round(float(score), 4),
            "reason": step_definition.summary or step_definition.doc_summary,
            "source": "step_catalog",
        }

    def _apply_binding_overrides_to_match_result(
        self,
        project_root: str,
        match_result: dict[str, Any],
        binding_overrides: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not binding_overrides:
            return match_result
        definitions = {item.id: item for item in self.step_index_store.load_steps(project_root)}
        matched = [dict(item) for item in match_result.get("matched", []) if isinstance(item, dict)]
        for override in binding_overrides:
            if not isinstance(override, dict):
                continue
            step_id = str(override.get("stepId") or "").strip()
            if not step_id or step_id not in definitions:
                continue
            target_order = override.get("order")
            target_text = str(override.get("text") or "").strip()
            replacement = definitions[step_id]
            for entry in matched:
                test_step = entry.get("test_step") or {}
                same_order = target_order is not None and int(test_step.get("order") or -1) == int(target_order)
                same_text = target_text and str(test_step.get("text") or "").strip() == target_text
                if not same_order and not same_text:
                    continue
                entry["status"] = MatchStatus.EXACT.value
                entry["confidence"] = max(float(entry.get("confidence") or 0.0), 0.9)
                entry["step_definition"] = self._serialize_step_definition_payload(replacement)
                entry["resolved_step_text"] = replacement.pattern
                notes = dict(entry.get("notes") or {})
                notes["bindingOverride"] = True
                notes["bindingOverrideSource"] = "preview_plan"
                entry["notes"] = notes
                break
        updated = dict(match_result)
        updated["matched"] = matched
        updated["unmatched"] = [
            str((item.get("test_step") or {}).get("text") or "")
            for item in matched
            if str(item.get("status") or "").casefold() == MatchStatus.UNMATCHED.value
        ]
        return updated

    @staticmethod
    def _serialize_step_definition_payload(definition) -> dict[str, Any]:
        implementation = definition.implementation
        return {
            "id": definition.id,
            "keyword": definition.keyword.value,
            "pattern": definition.pattern,
            "regex": definition.regex,
            "code_ref": definition.code_ref,
            "pattern_type": definition.pattern_type.value,
            "parameters": [
                {
                    "name": param.name,
                    "type": param.type,
                    "placeholder": param.placeholder,
                }
                for param in definition.parameters
            ],
            "tags": list(definition.tags),
            "language": definition.language,
            "implementation": {
                "file": implementation.file,
                "line": implementation.line,
                "class_name": implementation.class_name,
                "method_name": implementation.method_name,
            }
            if implementation
            else None,
            "summary": definition.summary,
            "examples": list(definition.examples),
            "step_type": definition.step_type.value if definition.step_type else None,
            "usage_count": definition.usage_count,
            "linked_scenario_ids": list(definition.linked_scenario_ids),
            "sample_scenario_refs": list(definition.sample_scenario_refs),
            "aliases": list(definition.aliases),
            "domain": definition.domain,
        }

    @staticmethod
    def _keyword_for_intent(intent_type: StepIntentType) -> StepKeyword:
        if intent_type is StepIntentType.SETUP:
            return StepKeyword.GIVEN
        if intent_type is StepIntentType.ASSERTION:
            return StepKeyword.THEN
        return StepKeyword.WHEN

    @staticmethod
    def _derive_rewrite_rules(original_feature_text: str, edited_feature_text: str) -> list[dict[str, Any]]:
        original_steps = Orchestrator._extract_gherkin_steps(original_feature_text)
        edited_steps = Orchestrator._extract_gherkin_steps(edited_feature_text)
        matcher = difflib.SequenceMatcher(a=original_steps, b=edited_steps)
        rules: list[dict[str, Any]] = []
        for opcode, a0, a1, b0, b1 in matcher.get_opcodes():
            if opcode == "equal":
                continue
            before = original_steps[a0:a1]
            after = edited_steps[b0:b1]
            if before and after:
                rules.append({"from": before, "to": after, "source": "review_apply"})
        return rules

    @staticmethod
    def _derive_alias_candidates(
        *,
        scenario: dict[str, Any],
        match_result: dict[str, Any],
        binding_overrides: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        overrides_by_order = {
            int(item.get("order")): str(item.get("stepId"))
            for item in binding_overrides
            if isinstance(item, dict) and item.get("stepId") and item.get("order") is not None
        }
        result: list[dict[str, Any]] = []
        for item in match_result.get("matched", []):
            if not isinstance(item, dict):
                continue
            test_step = item.get("test_step") or {}
            order = int(test_step.get("order") or -1)
            step_id = overrides_by_order.get(order)
            if not step_id:
                step_definition = item.get("step_definition") or {}
                step_id = str(step_definition.get("id") or "").strip()
            alias = str(test_step.get("text") or "").strip()
            if step_id and alias:
                result.append({"stepId": step_id, "alias": alias})
        return result

    @staticmethod
    def _extract_gherkin_steps(text: str) -> list[str]:
        result: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.casefold().startswith(
                ("given ", "when ", "then ", "and ", "but ", "дано ", "когда ", "тогда ", "и ", "но ")
            ):
                result.append(stripped)
        return result

    @staticmethod
    def _average(values: list[float]) -> float:
        filtered = [value for value in values if value is not None]
        if not filtered:
            return 0.0
        return sum(filtered) / len(filtered)

    def compose_autotest(
        self,
        project_root: str,
        testcase_text: str,
        *,
        language: str | None = None,
        quality_policy: str | None = None,
    ) -> dict[str, Any]:
        return self.generate_feature(
            project_root=project_root,
            testcase_text=testcase_text,
            target_path=None,
            create_file=False,
            overwrite_existing=False,
            language=language,
            quality_policy=quality_policy,
            explicit_quality_policy=quality_policy is not None,
            explicit_language=language is not None,
            explicit_target_path=False,
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
        quality_policy: str | None = None,
        explicit_quality_policy: bool = False,
        explicit_language: bool = False,
        explicit_target_path: bool = False,
        plan_id: str | None = None,
        selected_scenario_id: str | None = None,
        binding_overrides: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        logger.info("[Orchestrator] Generate feature for project %s", project_root)
        stored_plan = self.preview_plan_store.get_plan(plan_id) if (self.preview_plan_store and plan_id) else None
        effective_testcase_text = testcase_text or (stored_plan or {}).get("testcaseText") or ""
        effective_binding_overrides = list(binding_overrides or (stored_plan or {}).get("bindingOverrides") or [])
        effective_selected_scenario_id = selected_scenario_id or (stored_plan or {}).get("selectedScenarioId")
        state = self._feature_graph.invoke(
            {
                "project_root": project_root,
                "testcase_text": effective_testcase_text,
                "zephyr_auth": zephyr_auth,
                "jira_instance": jira_instance,
                "target_path": target_path,
                "create_file": create_file,
                "overwrite_existing": overwrite_existing,
                "language": language,
                "quality_policy": normalize_quality_policy(quality_policy),
                "explicit_quality_policy": explicit_quality_policy,
                "explicit_language": explicit_language,
                "explicit_target_path": explicit_target_path,
                "plan_id": plan_id,
                "selected_scenario_id": effective_selected_scenario_id,
                "binding_overrides": effective_binding_overrides,
            }
        )
        scenario_dict = state.get("scenario", {})
        match_result = state.get("match_result", {})
        feature_result = state.get("feature", {})
        pipeline = state.get("pipeline", [])
        file_status = state.get("file_status")
        if stored_plan:
            feature_meta = dict(feature_result.get("meta") or {})
            feature_meta["planId"] = plan_id
            feature_meta["selectedScenarioId"] = effective_selected_scenario_id
            feature_meta["candidateBackground"] = (
                ((stored_plan.get("generationPlan") or {}).get("candidateBackground")) or []
            )
            feature_result["meta"] = feature_meta
            retrieval_stage = {
                "stage": "scenario_retrieval",
                "status": "ok",
                "details": {
                    "selectedScenarioId": effective_selected_scenario_id,
                    "candidateCount": len((stored_plan.get("similarScenarios") or [])),
                },
            }
            planning_stage = {
                "stage": "generation_plan",
                "status": "ok",
                "details": {
                    "planId": plan_id,
                    "bindingOverrides": len(effective_binding_overrides),
                },
            }
            pipeline = pipeline[:3] + [retrieval_stage, planning_stage] + pipeline[3:]

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
        project_root_path = Path(project_root).expanduser().resolve()
        candidate_path = Path(target_path).expanduser()
        resolved_path = (
            candidate_path.resolve()
            if candidate_path.is_absolute()
            else (project_root_path / candidate_path).resolve()
        )
        try:
            normalized_path = resolved_path.relative_to(project_root_path).as_posix()
        except ValueError:
            return {
                "projectRoot": project_root,
                "targetPath": target_path,
                "status": "rejected_outside_project",
                "message": "Target path is outside project root",
            }
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
