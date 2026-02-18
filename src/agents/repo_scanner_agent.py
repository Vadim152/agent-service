"""Agent for repository scan and step index updates."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZipFile

from domain.enums import StepPatternType
from domain.models import StepDefinition, StepImplementation
from infrastructure.embeddings_store import EmbeddingsStore
from infrastructure.fs_repo import FsRepository
from infrastructure.llm_client import LLMClient
from infrastructure.step_index_store import StepIndexStore
from tools.cucumber_expression import cucumber_expression_to_regex
from tools.step_extractor import StepExtractor

logger = logging.getLogger(__name__)


class RepoScannerAgent:
    """Encapsulates source scan and step index refresh."""

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
            "**/*StepDefinitions.java",
            "**/*StepDefinitions.kt",
            "**/*StepDefinitions.groovy",
            "**/*StepDefinitions.py",
            "**/*StepDefinition.java",
            "**/*StepDefinition.kt",
            "**/*StepDefinition.groovy",
            "**/*StepDefinition.py",
        ]

    def scan_repository(
        self,
        project_root: str,
        additional_roots: list[str] | None = None,
    ) -> dict[str, Any]:
        """Scans one project and optional dependency roots, then rebuilds index."""

        logger.info("[RepoScannerAgent] Scan started: %s", project_root)
        roots = self._build_scan_roots(project_root, additional_roots)
        steps: list[StepDefinition] = []
        for root in roots:
            steps.extend(self._extract_steps_from_root(project_root, root))
        steps = self._deduplicate_steps(steps)

        logger.debug("[RepoScannerAgent] Steps found: %s", len(steps))

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
            "sampleSteps": steps[:50],
        }
        logger.info("[RepoScannerAgent] Scan completed %s. Steps: %s", project_root, len(steps))
        return result

    def _build_scan_roots(self, project_root: str, additional_roots: list[str] | None) -> list[str]:
        primary = Path(project_root).expanduser().resolve()
        ordered_unique: dict[str, None] = {str(primary): None}
        for item in additional_roots or []:
            value = str(item).strip()
            if not value:
                continue
            candidate = Path(value).expanduser().resolve()
            ordered_unique[str(candidate)] = None
        return list(ordered_unique.keys())

    def _extract_steps_from_root(self, project_root: str, root: str) -> list[StepDefinition]:
        root_path = Path(root).expanduser().resolve()
        project_path = Path(project_root).expanduser().resolve()
        is_primary_root = root_path == project_path

        if root_path.is_dir():
            extractor = StepExtractor(FsRepository(str(root_path)), self.file_patterns)
            steps = extractor.extract_steps()
            if not is_primary_root:
                self._prefix_external_steps(steps, str(root_path))
            return steps

        if root_path.is_file() and root_path.suffix.lower() == ".jar":
            steps = self._extract_steps_from_archive(root_path)
            self._prefix_external_steps(steps, str(root_path))
            return steps

        logger.debug("[RepoScannerAgent] Skip unsupported scan root: %s", root)
        return []

    def _extract_steps_from_archive(self, archive_path: Path) -> list[StepDefinition]:
        steps: list[StepDefinition] = []
        with ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                relative_path = entry.filename
                if not self._matches_pattern(relative_path):
                    continue

                try:
                    content = archive.read(entry).decode("utf-8", errors="replace")
                except Exception:
                    logger.debug(
                        "[RepoScannerAgent] Failed reading archive entry %s from %s",
                        relative_path,
                        archive_path,
                    )
                    continue

                annotations = list(StepExtractor._iter_annotations(content.splitlines()))
                for annotation in annotations:
                    pattern_type = StepExtractor._detect_pattern_type(annotation.pattern)
                    regex = (
                        cucumber_expression_to_regex(annotation.pattern)
                        if pattern_type is StepPatternType.CUCUMBER_EXPRESSION
                        else annotation.pattern
                    )
                    step_id = f"{relative_path}:{annotation.line_number}"
                    steps.append(
                        StepDefinition(
                            id=step_id,
                            keyword=annotation.keyword,
                            pattern=annotation.pattern,
                            regex=regex,
                            code_ref=step_id,
                            pattern_type=pattern_type,
                            parameters=StepExtractor._extract_parameters(
                                annotation.pattern,
                                pattern_type,
                                annotation.method_parameters,
                            ),
                            tags=[],
                            language=None,
                            implementation=StepImplementation(
                                file=f"{archive_path.name}!/{relative_path}",
                                line=annotation.line_number,
                                class_name=annotation.class_name,
                                method_name=annotation.method_name,
                            ),
                        )
                    )
        return steps

    def _matches_pattern(self, relative_path: str) -> bool:
        normalized = relative_path.replace("\\", "/")
        pure = PurePosixPath(normalized)
        return any(pure.match(pattern) for pattern in self.file_patterns)

    @staticmethod
    def _prefix_external_steps(steps: list[StepDefinition], source_root: str) -> None:
        source_hash = hashlib.sha1(source_root.encode("utf-8")).hexdigest()[:10]
        prefix = f"dep[{source_hash}]"
        for step in steps:
            step.id = f"{prefix}:{step.id}"
            step.code_ref = f"{prefix}:{step.code_ref}"
            if step.implementation and step.implementation.file:
                step.implementation.file = f"{prefix}:{step.implementation.file}"

    @staticmethod
    def _deduplicate_steps(steps: list[StepDefinition]) -> list[StepDefinition]:
        deduped: list[StepDefinition] = []
        seen: set[tuple[str, str, str, int | None, str | None]] = set()
        for step in steps:
            impl = step.implementation
            signature = (
                step.keyword.value,
                step.pattern,
                impl.file if impl else "",
                impl.line if impl else None,
                impl.method_name if impl else None,
            )
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(step)
        return deduped

    def _enrich_step_with_llm(self, step: StepDefinition) -> None:
        """Adds compact summary/examples with LLM where available."""

        summary_prompt = (
            "Сформулируй краткое назначение cucumber-шага на основе аннотации."
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
        except Exception as exc:  # pragma: no cover
            logger.warning("[RepoScannerAgent] Failed to fetch summary from LLM: %s", exc)

        try:
            raw_examples = self.llm_client.generate(examples_prompt)
            parsed_examples = self._parse_examples(raw_examples)
            if parsed_examples:
                step.examples = parsed_examples
        except Exception as exc:  # pragma: no cover
            logger.warning("[RepoScannerAgent] Failed to fetch examples from LLM: %s", exc)

    @staticmethod
    def _parse_examples(raw: str) -> list[str]:
        """Extracts examples from LLM output."""

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

