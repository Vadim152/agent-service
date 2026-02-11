"""In-memory state store for job/run/attempt lifecycle."""
from __future__ import annotations

from collections import OrderedDict
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
    index: int
    created_at: datetime = field(default_factory=utcnow)


class RunStateStore:
    """Thread-safe in-memory store for Job API control plane."""

    def __init__(self, *, max_jobs: int = 500, max_events_per_job: int = 2_000) -> None:
        self._lock = RLock()
        self._max_jobs = max(1, max_jobs)
        self._max_events_per_job = max(1, max_events_per_job)
        self._jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._events: dict[str, list[StoreEvent]] = {}
        self._next_event_index: dict[str, int] = {}

    def put_job(self, job: dict[str, Any]) -> None:
        with self._lock:
            job_id = str(job["job_id"])
            self._jobs[job_id] = job
            self._jobs.move_to_end(job_id)
            self._evict_jobs_if_needed_locked()

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
            self._jobs.move_to_end(job_id)
            return deepcopy(item)

    def append_attempt(self, job_id: str, attempt: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            item = self._jobs.get(job_id)
            if not item:
                return None
            attempts = item.setdefault("attempts", [])
            attempts.append(attempt)
            item["updated_at"] = utcnow().isoformat()
            self._jobs.move_to_end(job_id)
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
                    self._jobs.move_to_end(job_id)
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
            events = self._events.setdefault(job_id, [])
            event_index = self._next_event_index.get(job_id, 0)
            events.append(StoreEvent(event_type=event_type, payload=payload, index=event_index))
            self._next_event_index[job_id] = event_index + 1
            if len(events) > self._max_events_per_job:
                del events[: len(events) - self._max_events_per_job]

    def list_events(self, job_id: str, since_index: int = 0) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            events = self._events.get(job_id, [])
            floor_index = max(0, since_index)
            selected = [event for event in events if event.index >= floor_index]
            result = [
                {
                    "event_type": event.event_type,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat(),
                    "index": event.index,
                }
                for event in selected
            ]
            next_index = self._next_event_index.get(job_id, 0)
            return result, next_index

    def _evict_jobs_if_needed_locked(self) -> None:
        while len(self._jobs) > self._max_jobs:
            stale_job_id, _ = self._jobs.popitem(last=False)
            self._events.pop(stale_job_id, None)
            self._next_event_index.pop(stale_job_id, None)
