"""Persistent project-level feedback and ranking boosts for step matching."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_key(project_root: str) -> str:
    normalized = Path(project_root).expanduser().resolve().as_posix().lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


class ProjectLearningStore:
    """Stores lightweight project memory used for retrieval ranking feedback."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, project_root: str) -> Path:
        return self._base_dir / f"{_project_key(project_root)}.json"

    def load(self, project_root: str) -> dict[str, Any]:
        path = self._path(project_root)
        if not path.exists():
            return {
                "projectRoot": project_root,
                "updatedAt": None,
                "stepBoosts": {},
                "feedback": [],
                "preferences": {},
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("projectRoot", project_root)
        payload.setdefault("updatedAt", None)
        payload.setdefault("stepBoosts", {})
        payload.setdefault("feedback", [])
        payload.setdefault("preferences", {})
        return payload

    def save(self, project_root: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload)
        data["projectRoot"] = project_root
        data["updatedAt"] = _utcnow()
        path = self._path(project_root)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    def patch(self, project_root: str, **changes: Any) -> dict[str, Any]:
        payload = self.load(project_root)
        for key, value in changes.items():
            if value is None:
                continue
            payload[key] = value
        return self.save(project_root, payload)

    def get_step_boosts(self, project_root: str) -> dict[str, float]:
        payload = self.load(project_root)
        boosts = payload.get("stepBoosts", {})
        if not isinstance(boosts, dict):
            return {}
        result: dict[str, float] = {}
        for key, value in boosts.items():
            try:
                result[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        return result

    def record_feedback(
        self,
        *,
        project_root: str,
        step_id: str,
        accepted: bool,
        note: str | None = None,
        preference_key: str | None = None,
        preference_value: Any = None,
    ) -> dict[str, Any]:
        payload = self.load(project_root)
        boosts = payload.setdefault("stepBoosts", {})
        current = float(boosts.get(step_id, 0.0))
        delta = 0.05 if accepted else -0.05
        next_value = max(-0.5, min(0.5, current + delta))
        boosts[step_id] = round(next_value, 4)

        feedback = payload.setdefault("feedback", [])
        feedback.append(
            {
                "stepId": step_id,
                "accepted": accepted,
                "delta": delta,
                "note": note,
                "createdAt": _utcnow(),
            }
        )
        if len(feedback) > 300:
            payload["feedback"] = feedback[-300:]

        if preference_key:
            prefs = payload.setdefault("preferences", {})
            prefs[preference_key] = preference_value

        return self.save(project_root, payload)

