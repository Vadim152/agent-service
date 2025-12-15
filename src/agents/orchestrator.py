"""Оркестратор агентов, координирующий сценарии работы сервиса."""
from __future__ import annotations

import logging
from typing import Any

from agents.repo_scanner_agent import RepoScannerAgent
from agents.step_matcher_agent import StepMatcherAgent
from agents.testcase_parser_agent import TestcaseParserAgent
from agents.feature_builder_agent import FeatureBuilderAgent
from infrastructure.fs_repo import FsRepository
from infrastructure.embeddings_store import EmbeddingsStore
from infrastructure.llm_client import LLMClient
from infrastructure.step_index_store import StepIndexStore

logger = logging.getLogger(__name__)


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

    def scan_steps(self, project_root: str) -> dict[str, Any]:
        """Сканирует исходники и сохраняет индекс шагов."""

        logger.info("[Orchestrator] Запуск сканирования шагов: %s", project_root)
        result = self.repo_scanner_agent.scan_repository(project_root)
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
        scenario_dict = self.testcase_parser_agent.parse_testcase(testcase_text)
        logger.info(
            "[Orchestrator] Парсинг тесткейса завершён (source=%s)",
            scenario_dict.get("source", "unknown"),
        )
        matched = self.step_matcher_agent.match_testcase_steps(project_root, scenario_dict)
        feature_result = self.feature_builder_agent.build_feature_from_matches(
            scenario_dict, matched.get("matched", []), language=language
        )

        file_status: dict[str, Any] | None = None
        if create_file and target_path:
            feature_text = feature_result.get("featureText", "")
            file_status = self.apply_feature(
                project_root,
                target_path,
                feature_text,
                overwrite_existing=overwrite_existing,
            )

        pipeline = [
            {
                "stage": "parse",
                "status": "ok",
                "details": {
                    "source": scenario_dict.get("source"),
                    "steps": len(scenario_dict.get("steps", [])),
                },
            },
            {
                "stage": "match",
                "status": "ok",
                "details": {
                    "matched": len(matched.get("matched", [])),
                    "unmatched": len(matched.get("unmatched", [])),
                },
            },
            {
                "stage": "feature_build",
                "status": feature_result.get("buildStage") or "ok",
                "details": {
                    "stepsSummary": feature_result.get("stepsSummary"),
                    "language": feature_result.get("meta", {}).get("language"),
                },
            },
        ]

        logger.info(
            "[Orchestrator] Генерация feature завершена. Unmapped: %s",
            len(feature_result.get("unmappedSteps", [])),
        )
        return {
            "projectRoot": project_root,
            "scenario": scenario_dict,
            "matchResult": matched,
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
