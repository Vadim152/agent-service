"""Агент для сканирования репозитория и обновления индекса шагов."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

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

    def scan_repository(self, project_root: str) -> dict[str, Any]:
        """Проходит по репозиторию, извлекает шаги и обновляет хранилища."""

        logger.info("[RepoScannerAgent] Начало сканирования: %s", project_root)
        repository = FsRepository(project_root)
        extractor = StepExtractor(repository, self.file_patterns)
        steps: list[StepDefinition] = extractor.extract_steps()
        logger.debug("[RepoScannerAgent] Найдено шагов: %s", len(steps))

        if self.llm_client:
            for step in steps:
                self._enrich_step_with_llm(step)

        self.step_index_store.save_steps(project_root, steps)
        self.embeddings_store.index_steps(project_root, steps)

        updated_at = datetime.now(tz=timezone.utc).isoformat()
        result = {
            "projectRoot": project_root,
            "stepsCount": len(steps),
            "updatedAt": updated_at,
            # Небольшая выборка шагов для мгновенного отображения в UI без
            # повторного чтения с диска
            "sampleSteps": steps[:50],
        }
        logger.info(
            "[RepoScannerAgent] Завершено сканирование %s. Шагов: %s", project_root, len(steps)
        )
        return result

    def _enrich_step_with_llm(self, step: StepDefinition) -> None:
        """Добавляет краткое описание и примеры Gherkin с помощью LLM."""

        summary_prompt = (
            "Сформулируй краткое назначение cucumber-шагa на основе аннотации."
            " Верни одно предложение без лишних слов.\n"
            f"Ключевое слово: {step.keyword.value}.\n"
            f"Паттерн шага: {step.pattern}.\n"
            f"Тип паттерна: {step.pattern_type.value}.\n"
            f"Параметры: {', '.join(param.name for param in step.parameters) or 'нет'}."
        )

        examples_prompt = (
            "Приведи 2-3 строки Gherkin, подходящие под аннотацию шага"
            " (без номеров и лишних комментариев)."
            f" Используй язык шага: {step.language or 'как в исходнике'}.\n"
            f"Ключевое слово: {step.keyword.value}. Паттерн: {step.pattern}."
        )

        try:
            raw_summary = self.llm_client.generate(summary_prompt)
            step.summary = (raw_summary or "").strip() or step.summary
            step.doc_summary = step.summary
        except Exception as exc:  # pragma: no cover - защитный код
            logger.warning("[RepoScannerAgent] Не удалось получить summary от LLM: %s", exc)

        try:
            raw_examples = self.llm_client.generate(examples_prompt)
            parsed_examples = self._parse_examples(raw_examples)
            if parsed_examples:
                step.examples = parsed_examples
        except Exception as exc:  # pragma: no cover - защитный код
            logger.warning("[RepoScannerAgent] Не удалось получить examples от LLM: %s", exc)

    @staticmethod
    def _parse_examples(raw: str) -> list[str]:
        """Извлекает строки примеров из ответа LLM."""

        if not raw:
            return []

        cleaned = raw.replace("\r", "\n")
        lines = [line.strip(" -•\t") for line in cleaned.splitlines()]
        examples = [line for line in lines if line]

        if len(examples) == 1:
            try:
                data = json.loads(examples[0])
                if isinstance(data, list):
                    return [str(item).strip() for item in data if str(item).strip()]
            except json.JSONDecodeError:
                pass

        return examples


__all__ = ["RepoScannerAgent"]
