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
class AdapterEvent:
    event_type: str
    payload: dict[str, Any]
    index: int
    created_at: datetime = field(default_factory=utcnow)


class OpenCodeAdapterStateStore:
    def __init__(self, *, max_events_per_run: int = 5_000) -> None:
        self._lock = RLock()
        self._max_events_per_run = max(1, max_events_per_run)
        self._runs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._events: dict[str, list[AdapterEvent]] = {}
        self._next_event_index: dict[str, int] = {}
        self._session_map: dict[str, dict[str, Any]] = {}

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            run_id = str(payload["backend_run_id"])
            self._runs[run_id] = deepcopy(payload)
            self._runs.move_to_end(run_id)
            return deepcopy(self._runs[run_id])

    def get_run(self, backend_run_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._runs.get(backend_run_id)
            return deepcopy(item) if item else None

    def patch_run(self, backend_run_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            item = self._runs.get(backend_run_id)
            if not item:
                return None
            item.update(changes)
            item["updated_at"] = utcnow().isoformat()
            self._runs.move_to_end(backend_run_id)
            return deepcopy(item)

    def append_event(self, backend_run_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            index = self._next_event_index.get(backend_run_id, 0)
            event = AdapterEvent(event_type=event_type, payload=deepcopy(payload), index=index)
            events = self._events.setdefault(backend_run_id, [])
            events.append(event)
            self._next_event_index[backend_run_id] = index + 1
            if len(events) > self._max_events_per_run:
                del events[: len(events) - self._max_events_per_run]
            return {
                "event_type": event.event_type,
                "payload": deepcopy(event.payload),
                "created_at": event.created_at.isoformat(),
                "index": event.index,
            }

    def list_events(self, backend_run_id: str, after: int = 0) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            floor = max(0, int(after))
            events = [
                {
                    "event_type": event.event_type,
                    "payload": deepcopy(event.payload),
                    "created_at": event.created_at.isoformat(),
                    "index": event.index,
                }
                for event in self._events.get(backend_run_id, [])
                if event.index >= floor
            ]
            return events, self._next_event_index.get(backend_run_id, 0)

    def set_session_mapping(
        self,
        *,
        external_session_id: str,
        backend_session_id: str,
        project_root: str,
        last_backend_run_id: str,
    ) -> None:
        with self._lock:
            self._session_map[external_session_id] = {
                "external_session_id": external_session_id,
                "backend_session_id": backend_session_id,
                "project_root": project_root,
                "last_backend_run_id": last_backend_run_id,
                "updated_at": utcnow().isoformat(),
            }

    def get_session_mapping(self, external_session_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._session_map.get(external_session_id)
            return deepcopy(item) if item else None
