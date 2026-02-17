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

from domain.enums import StepKeyword, StepPatternType
from domain.models import StepDefinition, StepImplementation, StepParameter
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

    def _project_collection_name(self, project_root: str) -> str:
        project_hash = hashlib.sha1(project_root.encode("utf-8")).hexdigest()
        return f"steps_{project_hash}"

    def _get_collection(self, project_root: str):
        name = self._project_collection_name(project_root)
        return self._client.get_or_create_collection(
            name=name,
            metadata={"project_root": project_root},
            embedding_function=self._embedding_function,
        )

    def _collection_exists(self, project_root: str) -> bool:
        name = self._project_collection_name(project_root)
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
        return " \n".join(parts)

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
        )

    def index_steps(self, project_root: str, steps: list[StepDefinition]) -> None:
        """Построить или обновить индекс эмбеддингов для проекта."""
        if not steps:
            return None

        collection = self._get_collection(project_root)
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
            }
            for step in steps
        ]
        ids = [f"{self._project_collection_name(project_root)}:{step.id}" for step in steps]

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

        if not self._collection_exists(project_root):
            return []

        collection = self._get_collection(project_root)
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

    def clear(self, project_root: str) -> None:
        """Очищает индекс эмбеддингов для указанного проекта."""
        name = self._project_collection_name(project_root)
        if self._collection_exists(project_root):
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
