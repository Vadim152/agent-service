"""Абстракция векторного хранилища для шагов.

EmbeddingsStore будет отвечать за построение и поиск по эмбеддинговому индексу
для cucumber-шагов. Текущая реализация оставлена в виде заглушек, чтобы позднее
подключить конкретный движок (faiss/chroma/qdrant и т.д.).
"""

from __future__ import annotations

import os
import json
import hashlib
import math
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, List

# Disable Chroma telemetry to avoid outbound calls and keep usage local-only.
os.environ.setdefault(
    "CHROMA_TELEMETRY_IMPL", "chromadb.telemetry.impl.noop.NoopTelemetry"
)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb

from domain.enums import ScenarioType, StepIntentType, StepKeyword, StepPatternType
from domain.models import ScenarioCatalogEntry, StepDefinition, StepImplementation, StepParameter
from tools.cucumber_expression import cucumber_expression_to_regex


class EmbeddingsStore:
    """Слой работы с векторным хранилищем."""

    def __init__(self, persist_directory: str | Path = ".chroma") -> None:
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_directory))
        self._embedding_function = _LocalEmbeddingFunction()
        self._closed = False

    def close(self) -> None:
        """Releases underlying Chroma resources (important for Windows file locks)."""

        if self._closed:
            return
        self._closed = True
        try:
            system = getattr(self._client, "_system", None)
            if system is not None and hasattr(system, "stop"):
                system.stop()
        except Exception:
            pass
        try:
            if hasattr(self._client, "clear_system_cache"):
                self._client.clear_system_cache()
        except Exception:
            pass

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        self.close()

    def _project_collection_name(self, project_root: str, prefix: str = "steps") -> str:
        project_hash = hashlib.sha1(project_root.encode("utf-8")).hexdigest()
        return f"{prefix}_{project_hash}"

    def _get_collection(self, project_root: str, prefix: str = "steps"):
        name = self._project_collection_name(project_root, prefix=prefix)
        return self._client.get_or_create_collection(
            name=name,
            metadata={"project_root": project_root, "prefix": prefix},
            embedding_function=self._embedding_function,
        )

    def _collection_exists(self, project_root: str, prefix: str = "steps") -> bool:
        name = self._project_collection_name(project_root, prefix=prefix)
        return any(collection.name == name for collection in self._client.list_collections())

    def _build_document(self, step: StepDefinition) -> str:
        parts = [step.keyword.value, step.pattern]
        if step.regex:
            parts.append(step.regex)
        if step.parameters:
            parts.extend(
                f"{param.name}:{param.type or ''}:{param.placeholder or ''}"
                for param in step.parameters
            )
        if step.tags:
            parts.extend(step.tags)
        parts.append(step.code_ref)
        parts.append(step.pattern_type.value)
        if step.summary:
            parts.append(step.summary)
        if step.examples:
            parts.extend(step.examples)
        if step.language:
            parts.append(step.language)
        if step.step_type:
            parts.append(step.step_type.value)
        if step.aliases:
            parts.extend(step.aliases)
        if step.domain:
            parts.append(step.domain)
        return " \n".join(parts)

    @staticmethod
    def _build_scenario_document(scenario: ScenarioCatalogEntry) -> str:
        parts = [
            scenario.name,
            scenario.feature_path,
            scenario.scenario_name,
        ]
        if scenario.description:
            parts.append(scenario.description)
        if scenario.tags:
            parts.extend(scenario.tags)
        parts.extend(scenario.background_steps)
        parts.extend(scenario.steps)
        if scenario.document:
            parts.append(scenario.document)
        return " \n".join(part for part in parts if part)

    def _step_from_metadata(self, metadata: dict) -> StepDefinition:
        pattern = metadata["pattern"]
        pattern_type = StepPatternType(
            metadata.get("pattern_type", StepPatternType.CUCUMBER_EXPRESSION.value)
        )
        regex = metadata.get("regex") or None
        if not regex:
            regex = (
                cucumber_expression_to_regex(pattern)
                if pattern_type is StepPatternType.CUCUMBER_EXPRESSION
                else pattern
            )
        return StepDefinition(
            id=metadata["id"],
            keyword=StepKeyword(metadata["keyword"]),
            pattern=pattern,
            regex=regex,
            code_ref=metadata["code_ref"],
            pattern_type=pattern_type,
            parameters=[
                StepParameter(**item)
                for item in self._decode_parameter_details(metadata)
            ],
            tags=(metadata.get("tags") or "").split(",") if metadata.get("tags") else [],
            language=metadata.get("language") or None,
            implementation=StepImplementation(
                file=metadata.get("file"),
                line=int(metadata["line"]) if metadata.get("line") else None,
                class_name=metadata.get("class_name"),
                method_name=metadata.get("method_name"),
            ),
            summary=metadata.get("summary") or None,
            examples=[ex for ex in (metadata.get("examples") or "").split("\n") if ex],
            step_type=StepIntentType(metadata["step_type"]) if metadata.get("step_type") else None,
            usage_count=int(metadata.get("usage_count") or 0),
            linked_scenario_ids=[
                item for item in (metadata.get("linked_scenario_ids") or "").split(",") if item
            ],
            sample_scenario_refs=[
                item for item in (metadata.get("sample_scenario_refs") or "").split("\n") if item
            ],
            aliases=[item for item in (metadata.get("aliases") or "").split("\n") if item],
            domain=metadata.get("domain") or None,
        )

    @staticmethod
    def _scenario_from_metadata(metadata: dict) -> ScenarioCatalogEntry:
        return ScenarioCatalogEntry(
            id=str(metadata.get("id", "")),
            name=str(metadata.get("name", "")),
            feature_path=str(metadata.get("feature_path", "")),
            scenario_name=str(metadata.get("scenario_name", "")),
            tags=[item for item in (metadata.get("tags") or "").split(",") if item],
            background_steps=[
                item for item in (metadata.get("background_steps") or "").split("\n") if item
            ],
            steps=[item for item in (metadata.get("steps") or "").split("\n") if item],
            scenario_type=ScenarioType(
                metadata.get("scenario_type", ScenarioType.STANDARD.value)
            ),
            document=metadata.get("document") or None,
            description=metadata.get("description") or None,
        )

    def index_steps(self, project_root: str, steps: list[StepDefinition]) -> None:
        """Построить или обновить индекс эмбеддингов для проекта."""
        if not steps:
            return None

        collection = self._get_collection(project_root, prefix="steps")
        documents = [self._build_document(step) for step in steps]
        metadata = [
            {
                "id": step.id,
                "keyword": step.keyword.value,
                "pattern": step.pattern,
                "regex": step.regex or "",
                "code_ref": step.code_ref,
                "pattern_type": step.pattern_type.value,
                "parameters": ",".join(param.name for param in step.parameters),
                "parameter_details": json.dumps(
                    [
                        {
                            "name": param.name,
                            "type": param.type,
                            "placeholder": param.placeholder,
                        }
                        for param in step.parameters
                    ],
                    ensure_ascii=False,
                ),
                "tags": ",".join(step.tags),
                "language": step.language or "",
                "file": step.implementation.file if step.implementation else "",
                "line": step.implementation.line if step.implementation else "",
                "class_name": step.implementation.class_name if step.implementation else "",
                "method_name": step.implementation.method_name if step.implementation else "",
                "summary": step.summary or "",
                "examples": "\n".join(step.examples),
                "step_type": step.step_type.value if step.step_type else "",
                "usage_count": int(step.usage_count or 0),
                "linked_scenario_ids": ",".join(step.linked_scenario_ids),
                "sample_scenario_refs": "\n".join(step.sample_scenario_refs),
                "aliases": "\n".join(step.aliases),
                "domain": step.domain or "",
            }
            for step in steps
        ]
        ids = [
            f"{self._project_collection_name(project_root, prefix='steps')}:{step.id}"
            for step in steps
        ]

        collection.upsert(ids=ids, documents=documents, metadatas=metadata)

        return None

    def index_scenarios(self, project_root: str, scenarios: list[ScenarioCatalogEntry]) -> None:
        if not scenarios:
            return None

        collection = self._get_collection(project_root, prefix="scenarios")
        documents = [self._build_scenario_document(scenario) for scenario in scenarios]
        metadata = [
            {
                "id": scenario.id,
                "name": scenario.name,
                "feature_path": scenario.feature_path,
                "scenario_name": scenario.scenario_name,
                "tags": ",".join(scenario.tags),
                "background_steps": "\n".join(scenario.background_steps),
                "steps": "\n".join(scenario.steps),
                "scenario_type": scenario.scenario_type.value,
                "document": scenario.document or "",
                "description": scenario.description or "",
            }
            for scenario in scenarios
        ]
        ids = [
            f"{self._project_collection_name(project_root, prefix='scenarios')}:{scenario.id}"
            for scenario in scenarios
        ]
        collection.upsert(ids=ids, documents=documents, metadatas=metadata)
        return None

    @staticmethod
    def _decode_parameter_details(metadata: dict) -> list[dict[str, str | None]]:
        raw = metadata.get("parameter_details")
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                result = []
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip()
                    if not name:
                        continue
                    result.append(
                        {
                            "name": name,
                            "type": item.get("type"),
                            "placeholder": item.get("placeholder"),
                        }
                    )
                if result:
                    return result

        return [
            {"name": name, "type": None, "placeholder": None}
            for name in (metadata.get("parameters") or "").split(",")
            if name
        ]

    def search_similar(self, project_root: str, query: str, top_k: int = 5) -> List[StepDefinition]:
        """Возвращает наиболее похожие шаги по текстовому запросу."""
        return [definition for definition, _ in self.get_top_k(project_root, query, top_k=top_k)]

    def get_top_k(
        self, project_root: str, query: str, top_k: int = 5
    ) -> list[tuple[StepDefinition, float]]:
        """Возвращает список наиболее похожих шагов с оценкой близости."""
        if top_k <= 0:
            return []

        if not self._collection_exists(project_root, prefix="steps"):
            return []

        collection = self._get_collection(project_root, prefix="steps")
        results = collection.query(query_texts=[query], n_results=top_k, include=["metadatas", "distances"])

        metadatas: list[list[dict]] | None = results.get("metadatas")
        distances: list[list[float]] | None = results.get("distances")
        if not metadatas or not metadatas[0]:
            return []

        definitions = [self._step_from_metadata(metadata) for metadata in metadatas[0]]

        scores: list[float] = []
        if distances and distances[0]:
            for distance in distances[0]:
                similarity = 1 / (1 + distance) if distance is not None else 0.0
                scores.append(similarity)
        else:
            scores = [0.0 for _ in definitions]

        return list(zip(definitions, scores))

    def get_top_k_scenarios(
        self, project_root: str, query: str, top_k: int = 3
    ) -> list[tuple[ScenarioCatalogEntry, float]]:
        if top_k <= 0:
            return []

        if not self._collection_exists(project_root, prefix="scenarios"):
            return []

        collection = self._get_collection(project_root, prefix="scenarios")
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            include=["metadatas", "distances"],
        )
        metadatas: list[list[dict]] | None = results.get("metadatas")
        distances: list[list[float]] | None = results.get("distances")
        if not metadatas or not metadatas[0]:
            return []

        scenarios = [self._scenario_from_metadata(metadata) for metadata in metadatas[0]]
        scores: list[float] = []
        if distances and distances[0]:
            for distance in distances[0]:
                similarity = 1 / (1 + distance) if distance is not None else 0.0
                scores.append(similarity)
        else:
            scores = [0.0 for _ in scenarios]

        return list(zip(scenarios, scores))

    def clear(self, project_root: str) -> None:
        """Очищает индекс эмбеддингов для указанного проекта."""
        for prefix in ("steps", "scenarios"):
            name = self._project_collection_name(project_root, prefix=prefix)
            if self._collection_exists(project_root, prefix=prefix):
                self._client.delete_collection(name)

        return None


class _LocalEmbeddingFunction:
    """Простая детерминированная функция эмбеддингов без внешних моделей."""

    def __init__(self, dimension: int = 64) -> None:
        self.dimension = dimension

    def __call__(self, input: Iterable[str]) -> list[list[float]]:
        return [self._embed(text) for text in input]

    def _embed(self, text: str) -> list[float]:
        tokens = _tokenize(text)
        counts = Counter(tokens)
        vector = [0.0 for _ in range(self.dimension)]
        for token, count in counts.items():
            token_hash = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
            idx = token_hash % self.dimension
            vector[idx] += float(count)

        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"\w+", text.lower())
    return tokens
