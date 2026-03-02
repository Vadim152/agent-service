"""In-memory state store for run/attempt lifecycle."""
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
    """Thread-safe in-memory store for run control plane."""

    def __init__(self, *, max_jobs: int = 500, max_events_per_job: int = 2_000) -> None:
        self._lock = RLock()
        self._max_runs = max(1, max_jobs)
        self._max_events_per_run = max(1, max_events_per_job)
        self._runs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._events: dict[str, list[StoreEvent]] = {}
        self._next_event_index: dict[str, int] = {}
        self._idempotency_map: dict[str, dict[str, str]] = {}

    def put_job(self, job: dict[str, Any]) -> None:
        with self._lock:
            run_id = str(job["run_id"])
            self._runs[run_id] = job
            self._runs.move_to_end(run_id)
            self._evict_runs_if_needed_locked()

    def get_job(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._runs.get(run_id)
            if not value:
                return None
            return deepcopy(value)

    def patch_job(self, run_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            item = self._runs.get(run_id)
            if not item:
                return None
            item.update(changes)
            item["updated_at"] = utcnow().isoformat()
            self._runs.move_to_end(run_id)
            return deepcopy(item)

    def append_attempt(self, run_id: str, attempt: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            item = self._runs.get(run_id)
            if not item:
                return None
            attempts = item.setdefault("attempts", [])
            attempts.append(attempt)
            item["updated_at"] = utcnow().isoformat()
            self._runs.move_to_end(run_id)
            return deepcopy(attempt)

    def patch_attempt(self, run_id: str, attempt_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            item = self._runs.get(run_id)
            if not item:
                return None
            attempts = item.setdefault("attempts", [])
            for attempt in attempts:
                if attempt.get("attempt_id") == attempt_id:
                    attempt.update(changes)
                    item["updated_at"] = utcnow().isoformat()
                    self._runs.move_to_end(run_id)
                    return deepcopy(attempt)
            return None

    def list_attempts(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            item = self._runs.get(run_id)
            if not item:
                return []
            attempts = item.get("attempts", [])
            return deepcopy(attempts)

    def append_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self._lock:
            events = self._events.setdefault(run_id, [])
            event_index = self._next_event_index.get(run_id, 0)
            events.append(StoreEvent(event_type=event_type, payload=payload, index=event_index))
            self._next_event_index[run_id] = event_index + 1
            if len(events) > self._max_events_per_run:
                del events[: len(events) - self._max_events_per_run]

    def list_events(self, run_id: str, since_index: int = 0) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            events = self._events.get(run_id, [])
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
            next_index = self._next_event_index.get(run_id, 0)
            return result, next_index

    def claim_idempotency_key(
        self,
        key: str,
        *,
        fingerprint: str,
        run_id: str,
    ) -> tuple[bool, str | None]:
        resolved_run_id = str(run_id).strip()
        if not resolved_run_id:
            raise ValueError("run_id is required")
        with self._lock:
            existing = self._idempotency_map.get(key)
            if existing:
                if existing.get("fingerprint") != fingerprint:
                    return False, None
                return False, existing.get("run_id")

            self._idempotency_map[key] = {"fingerprint": fingerprint, "run_id": resolved_run_id}
            return True, None

    def _evict_runs_if_needed_locked(self) -> None:
        while len(self._runs) > self._max_runs:
            stale_run_id, _ = self._runs.popitem(last=False)
            self._events.pop(stale_run_id, None)
            self._next_event_index.pop(stale_run_id, None)
            stale_keys = [
                key for key, data in self._idempotency_map.items() if data.get("run_id") == stale_run_id
            ]
            for key in stale_keys:
                self._idempotency_map.pop(key, None)
