"""In-memory registry for background asyncio tasks."""
from __future__ import annotations

import asyncio
import logging
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Awaitable, Callable


logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskRegistry:
    """Tracks lifecycle of detached background tasks."""

    def __init__(self, max_entries: int = 512) -> None:
        self._lock = RLock()
        self._max_entries = max(32, max_entries)
        self._tasks: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []

    def create_task(
        self,
        coroutine: Awaitable[Any],
        *,
        source: str,
        metadata: dict[str, Any] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
    ) -> str:
        """Schedule a task and register it for monitoring."""

        task_id = str(uuid.uuid4())
        task = asyncio.create_task(coroutine)
        entry = {
            "task_id": task_id,
            "source": source,
            "status": "running",
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
            "metadata": dict(metadata or {}),
            "error": None,
        }
        with self._lock:
            self._tasks[task_id] = entry
            self._order.append(task_id)
            self._trim_locked()

        def _done(done_task: asyncio.Task[Any]) -> None:
            try:
                exc = done_task.exception()
            except asyncio.CancelledError:
                exc = None
                status = "cancelled"
            except Exception as read_exc:  # pragma: no cover - defensive read branch
                exc = read_exc
                status = "failed"
            else:
                status = "failed" if exc else "completed"

            error_text = str(exc) if exc else None
            with self._lock:
                item = self._tasks.get(task_id)
                if item is not None:
                    item["status"] = status
                    item["updated_at"] = _utcnow()
                    item["error"] = error_text

            if exc is not None:
                logger.warning("Background task failed (source=%s, task_id=%s): %s", source, task_id, exc)
                if on_error is not None:
                    try:
                        on_error(exc)
                    except Exception as callback_exc:  # pragma: no cover - defensive callback branch
                        logger.warning(
                            "Task registry error callback failed (source=%s, task_id=%s): %s",
                            source,
                            task_id,
                            callback_exc,
                        )

        task.add_done_callback(_done)
        return task_id

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._tasks.get(task_id)
            return deepcopy(item) if item else None

    def list_tasks(self, *, source: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, self._max_entries))
        with self._lock:
            ids = list(reversed(self._order))
            items: list[dict[str, Any]] = []
            for task_id in ids:
                item = self._tasks.get(task_id)
                if not item:
                    continue
                if source and item.get("source") != source:
                    continue
                items.append(deepcopy(item))
                if len(items) >= bounded:
                    break
            return items

    def _trim_locked(self) -> None:
        while len(self._order) > self._max_entries:
            stale_id = self._order.pop(0)
            self._tasks.pop(stale_id, None)
