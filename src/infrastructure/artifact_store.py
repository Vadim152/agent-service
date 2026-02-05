"""Локальное файловое хранилище артефактов job/run/attempt."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ArtifactStore:
    """Хранит stdout/stderr/json и другие артефакты, отдавая ссылки на файлы."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _job_dir(self, job_id: str, run_id: str, attempt_id: str) -> Path:
        target = self._base_dir / job_id / run_id / attempt_id
        target.mkdir(parents=True, exist_ok=True)
        return target

    def write_text(
        self, *, job_id: str, run_id: str, attempt_id: str, name: str, content: str
    ) -> str:
        path = self._job_dir(job_id, run_id, attempt_id) / name
        path.write_text(content, encoding="utf-8")
        return str(path)

    def write_json(
        self, *, job_id: str, run_id: str, attempt_id: str, name: str, payload: dict[str, Any]
    ) -> str:
        path = self._job_dir(job_id, run_id, attempt_id) / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def write_incident(self, job_id: str, payload: dict[str, Any]) -> str:
        target = self._base_dir / job_id
        target.mkdir(parents=True, exist_ok=True)
        stamp = _utcnow().strftime("%Y%m%d-%H%M%S")
        path = target / f"incident-{stamp}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
