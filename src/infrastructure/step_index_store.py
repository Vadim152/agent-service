"""Хранилище индекса шагов Cucumber.

StepIndexStore отвечает за сохранение и загрузку индекса шагов из проекта.
Текущая реализация использует JSON-файл в каталоге индекса, но интерфейс
оставлен абстрактным, чтобы в будущем перейти на SQLite или другое хранилище
без изменения вызывающего кода.
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from domain.enums import StepKeyword
from domain.models import StepDefinition


class StepIndexStore:
    """Хранение индекса шагов в файловой системе (формат JSON)."""

    def __init__(self, index_dir: str) -> None:
        self._index_dir = Path(index_dir).expanduser().resolve()
        self._index_dir.mkdir(parents=True, exist_ok=True)

    def save_steps(self, project_root: str, steps: list[StepDefinition]) -> None:
        """Сохраняет список шагов для конкретного проекта."""

        target_dir = self._project_dir(project_root)
        target_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.utcnow().isoformat(),
            "steps": [self._serialize_step(step) for step in steps],
        }
        (target_dir / "steps.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load_steps(self, project_root: str) -> list[StepDefinition]:
        """Загружает сохранённые шаги. Возвращает пустой список, если данных нет."""

        steps_file = self._project_dir(project_root) / "steps.json"
        if not steps_file.exists():
            return []

        data = json.loads(steps_file.read_text(encoding="utf-8"))
        return [self._deserialize_step(entry) for entry in data.get("steps", [])]

    def get_last_updated_at(self, project_root: str) -> datetime | None:
        """Возвращает время последнего обновления индекса либо None."""

        steps_file = self._project_dir(project_root) / "steps.json"
        if not steps_file.exists():
            return None

        try:
            data = json.loads(steps_file.read_text(encoding="utf-8"))
            timestamp = data.get("updated_at")
            if timestamp:
                return datetime.fromisoformat(timestamp)
        except (ValueError, json.JSONDecodeError):
            return None

        return datetime.fromtimestamp(steps_file.stat().st_mtime)

    def clear(self, project_root: str) -> None:
        """Удаляет сохранённый индекс для указанного проекта, если он существует."""

        target_dir = self._project_dir(project_root)
        if target_dir.exists():
            steps_file = target_dir / "steps.json"
            if steps_file.exists():
                steps_file.unlink()
            try:
                target_dir.rmdir()
            except OSError:
                # Папка может содержать другие файлы; удаляем только steps.json
                pass

    def _project_dir(self, project_root: str) -> Path:
        """Возвращает путь к директории индекса для проекта.

        Используется хэшированный ключ, чтобы избежать проблем с именами директорий
        и коллизиями путей.
        """

        project_key = hashlib.sha1(Path(project_root).resolve().as_posix().encode()).hexdigest()
        return self._index_dir / project_key

    @staticmethod
    def _serialize_step(step: StepDefinition) -> dict[str, Any]:
        data = asdict(step)
        data["keyword"] = step.keyword.value
        return data

    @staticmethod
    def _deserialize_step(data: dict[str, Any]) -> StepDefinition:
        return StepDefinition(
            id=data.get("id", ""),
            keyword=StepKeyword(data.get("keyword", StepKeyword.GIVEN.value)),
            pattern=data.get("pattern", ""),
            regex=data.get("regex"),
            code_ref=data.get("code_ref", ""),
            parameters=list(data.get("parameters", []) or []),
            tags=list(data.get("tags", []) or []),
            language=data.get("language"),
        )

