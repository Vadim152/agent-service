"""Агент для сканирования репозитория и обновления индекса шагов."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from autogen import AssistantAgent

from domain.models import StepDefinition
from infrastructure.embeddings_store import EmbeddingsStore
from infrastructure.fs_repo import FsRepository
from infrastructure.llm_client import LLMClient
from infrastructure.step_index_store import StepIndexStore
from tools.step_extractor import StepExtractor

logger = logging.getLogger(__name__)


class RepoScannerAgent:
    """Инкапсулирует сканирование исходников и обновление индекса шагов."""

    def __init__(
        self,
        step_index_store: StepIndexStore,
        embeddings_store: EmbeddingsStore,
        llm_client: LLMClient | None = None,
        file_patterns: list[str] | None = None,
    ) -> None:
        self.step_index_store = step_index_store
        self.embeddings_store = embeddings_store
        self.llm_client = llm_client
        self.file_patterns = file_patterns or [
            "**/*Steps.java",
            "**/*Steps.kt",
            "**/*Steps.groovy",
            "**/*Steps.py",
        ]
        self.assistant = AssistantAgent(
            name="repo_scanner",
            system_message=(
                "Ты агент, который сканирует исходный код тестового проекта и обновляет индекс"
                " cucumber-шагов. Используй предоставленные инструменты для чтения файлов"
                " и формирования индекса."
            ),
        )
        self.assistant.register_function({
            "scan_repository": self.scan_repository,
        })

    def scan_repository(self, project_root: str) -> dict[str, Any]:
        """Проходит по репозиторию, извлекает шаги и обновляет хранилища."""

        logger.info("[RepoScannerAgent] Начало сканирования: %s", project_root)
        repository = FsRepository(project_root)
        extractor = StepExtractor(repository, self.file_patterns)
        steps: list[StepDefinition] = extractor.extract_steps()
        logger.debug("[RepoScannerAgent] Найдено шагов: %s", len(steps))

        self.step_index_store.save_steps(project_root, steps)
        self.embeddings_store.index_steps(project_root, steps)

        updated_at = datetime.now(tz=timezone.utc).isoformat()
        result = {
            "projectRoot": project_root,
            "stepsCount": len(steps),
            "updatedAt": updated_at,
        }
        logger.info(
            "[RepoScannerAgent] Завершено сканирование %s. Шагов: %s", project_root, len(steps)
        )
        return result


__all__ = ["RepoScannerAgent"]
