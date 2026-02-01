"""Оркестратор агентов, координирующий сценарии работы сервиса."""
from __future__ import annotations

import logging
from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from agents.repo_scanner_agent import RepoScannerAgent
from agents.step_matcher_agent import StepMatcherAgent
from agents.testcase_parser_agent import TestcaseParserAgent
from agents.feature_builder_agent import FeatureBuilderAgent
from infrastructure.fs_repo import FsRepository
from infrastructure.embeddings_store import EmbeddingsStore
from infrastructure.llm_client import LLMClient
from infrastructure.step_index_store import StepIndexStore

logger = logging.getLogger(__name__)


class ScanState(TypedDict):
    project_root: str
    result: dict[str, Any]


class FeatureGenerationState(TypedDict, total=False):
    project_root: str
    testcase_text: str
    target_path: str | None
    create_file: bool
    overwrite_existing: bool
    language: str | None
    scenario: dict[str, Any]
    match_result: dict[str, Any]
    feature: dict[str, Any]
    file_status: dict[str, Any] | None
    pipeline: list[dict[str, Any]]


class Orchestrator:
    """Фасад для HTTP-слоя, вызывающий доменные агенты в нужной последовательности."""

    def __init__(
        self,
        repo_scanner_agent: RepoScannerAgent,
        testcase_parser_agent: TestcaseParserAgent,
        step_matcher_agent: StepMatcherAgent,
        feature_builder_agent: FeatureBuilderAgent,
        step_index_store: StepIndexStore,
        embeddings_store: EmbeddingsStore,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.repo_scanner_agent = repo_scanner_agent
        self.testcase_parser_agent = testcase_parser_agent
        self.step_matcher_agent = step_matcher_agent
        self.feature_builder_agent = feature_builder_agent
        self.step_index_store = step_index_store
        self.embeddings_store = embeddings_store
        self.llm_client = llm_client
        self._scan_graph = self._build_scan_graph()
        self._feature_graph = self._build_feature_graph()

    def _build_scan_graph(self):
        graph = StateGraph(ScanState)
        graph.add_node("scan_repository", self._scan_repository_node())
        graph.set_entry_point("scan_repository")
        graph.add_edge("scan_repository", END)
        return graph.compile()

    def _build_feature_graph(self):
        graph = StateGraph(FeatureGenerationState)
        graph.add_node("parse_testcase", self._parse_testcase_node())
        graph.add_node("match_steps", self._match_steps_node())
        graph.add_node("build_feature", self._build_feature_node())
        graph.add_node("assemble_pipeline", self._assemble_pipeline_node())
        graph.add_node("apply_feature", self._apply_feature_node())
        graph.add_node("skip_apply", lambda _: {})
        graph.set_entry_point("parse_testcase")
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

    def _scan_repository_node(self) -> Callable[[ScanState], dict[str, Any]]:
        def _node(state: ScanState) -> dict[str, Any]:
            result = self.repo_scanner_agent.scan_repository(state["project_root"])
            return {"result": result}

        return _node

    def _parse_testcase_node(self) -> Callable[[FeatureGenerationState], dict[str, Any]]:
        def _node(state: FeatureGenerationState) -> dict[str, Any]:
            scenario_dict = self.testcase_parser_agent.parse_testcase(state["testcase_text"])
            return {"scenario": scenario_dict}

        return _node

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
                    "stage": "parse",
                    "status": "ok",
                    "details": {
                        "source": state.get("scenario", {}).get("source"),
                        "steps": len(state.get("scenario", {}).get("steps", [])),
                    },
                },
                {
                    "stage": "match",
                    "status": "ok",
                    "details": {
                        "matched": len(state.get("match_result", {}).get("matched", [])),
                        "unmatched": len(state.get("match_result", {}).get("unmatched", [])),
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
        """Сканирует исходники и сохраняет индекс шагов."""

        logger.info("[Orchestrator] Запуск сканирования шагов: %s", project_root)
        state = self._scan_graph.invoke({"project_root": project_root})
        result = state["result"]
        logger.info("[Orchestrator] Сканирование завершено: %s", result)
        return result

    def generate_feature(
        self,
        project_root: str,
        testcase_text: str,
        target_path: str | None = None,
        *,
        create_file: bool = False,
        overwrite_existing: bool = False,
        language: str | None = None,
    ) -> dict[str, Any]:
        """Полный цикл: парсинг тесткейса, матчинг и генерация feature."""

        logger.info("[Orchestrator] Генерация feature для проекта %s", project_root)
        state = self._feature_graph.invoke(
            {
                "project_root": project_root,
                "testcase_text": testcase_text,
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
            "[Orchestrator] Генерация feature завершена. Unmapped: %s",
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
        self, project_root: str, target_path: str, feature_text: str, *, overwrite_existing: bool = False
    ) -> dict[str, Any]:
        """Сохраняет сгенерированный .feature файл в репозитории."""

        logger.info(
            "[Orchestrator] Сохранение feature %s в проекте %s", target_path, project_root
        )
        fs_repo = FsRepository(project_root)
        normalized_path = target_path.lstrip("/")
        exists = fs_repo.exists(normalized_path)

        if exists and not overwrite_existing:
            logger.info(
                "[Orchestrator] Файл %s уже существует, пропускаем запись", target_path
            )
            return {
                "projectRoot": project_root,
                "targetPath": target_path,
                "status": "skipped",
                "message": "Файл уже существует, перезапись отключена",
            }

        fs_repo.write_text_file(normalized_path, feature_text, create_dirs=True)
        status = "overwritten" if exists else "created"
        logger.info(
            "[Orchestrator] Feature %s %s", target_path, "перезаписан" if exists else "создан"
        )
        return {
            "projectRoot": project_root,
            "targetPath": normalized_path,
            "status": status,
            "message": None,
        }


__all__ = ["Orchestrator"]
