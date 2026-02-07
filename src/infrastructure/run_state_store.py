"""In-memory хранилище состояний job/run/attempt для self-healing цикла."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class StoreEvent:
    event_type: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=utcnow)


class RunStateStore:
    """Потокобезопасное in-memory хранилище для Job API control-plane."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[StoreEvent]] = defaultdict(list)

    def put_job(self, job: dict[str, Any]) -> None:
        with self._lock:
            self._jobs[job["job_id"]] = job

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._jobs.get(job_id)
            if not value:
                return None
            return deepcopy(value)

    def patch_job(self, job_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            item = self._jobs.get(job_id)
            if not item:
                return None
            item.update(changes)
            item["updated_at"] = utcnow().isoformat()
            return deepcopy(item)

    def append_attempt(self, job_id: str, attempt: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            item = self._jobs.get(job_id)
            if not item:
                return None
            attempts = item.setdefault("attempts", [])
            attempts.append(attempt)
            item["updated_at"] = utcnow().isoformat()
            return deepcopy(attempt)

    def patch_attempt(self, job_id: str, attempt_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            item = self._jobs.get(job_id)
            if not item:
                return None
            attempts = item.setdefault("attempts", [])
            for attempt in attempts:
                if attempt.get("attempt_id") == attempt_id:
                    attempt.update(changes)
                    item["updated_at"] = utcnow().isoformat()
                    return deepcopy(attempt)
            return None

    def list_attempts(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            item = self._jobs.get(job_id)
            if not item:
                return []
            attempts = item.get("attempts", [])
            return deepcopy(attempts)

    def append_event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._events[job_id].append(StoreEvent(event_type=event_type, payload=payload))

    def list_events(self, job_id: str, since_index: int = 0) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            events = self._events.get(job_id, [])
            selected = events[since_index:]
            result = [
                {
                    "event_type": event.event_type,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat(),
                    "index": since_index + idx,
                }
                for idx, event in enumerate(selected)
            ]
            return result, len(events)
