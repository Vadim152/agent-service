"""Dispatch job execution either locally or through a queue."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from infrastructure.job_queue import JobEnvelope, JobQueue


logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


ErrorHandler = Callable[[BaseException], None]


class JobExecutionDispatcher:
    def dispatch(
        self,
        *,
        job_id: str,
        source: str,
        supervisor: Any,
        run_state_store: Any,
        task_registry: Any | None,
        on_error: ErrorHandler | None = None,
    ) -> None:
        raise NotImplementedError


class LocalJobExecutionDispatcher(JobExecutionDispatcher):
    """Runs supervisor in the current process as a detached task."""

    def dispatch(
        self,
        *,
        job_id: str,
        source: str,
        supervisor: Any,
        run_state_store: Any,
        task_registry: Any | None,
        on_error: ErrorHandler | None = None,
    ) -> None:
        _ = run_state_store

        async def _worker() -> None:
            await supervisor.execute_job(job_id)

        if task_registry is None:
            task = asyncio.create_task(_worker())
            if on_error:
                task.add_done_callback(lambda done: _handle_task_failure(done, on_error))
            return
        task_registry.create_task(
            _worker(),
            source=source,
            metadata={"jobId": job_id},
            on_error=on_error,
        )


class QueueJobExecutionDispatcher(JobExecutionDispatcher):
    """Enqueues jobs for external execution workers."""

    def __init__(self, *, queue: JobQueue) -> None:
        self._queue = queue

    def dispatch(
        self,
        *,
        job_id: str,
        source: str,
        supervisor: Any,
        run_state_store: Any,
        task_registry: Any | None,
        on_error: ErrorHandler | None = None,
    ) -> None:
        _ = (supervisor, task_registry)
        try:
            self._queue.enqueue(JobEnvelope(job_id=job_id, source=source, enqueued_at=_utcnow()))
            run_state_store.append_event(
                job_id,
                "job.dispatched",
                {"jobId": job_id, "backend": "queue", "source": source},
            )
        except Exception as exc:
            logger.warning("Queue dispatch failed (job_id=%s): %s", job_id, exc)
            if on_error:
                on_error(exc)
            else:
                raise


@dataclass
class DispatchComponents:
    dispatcher: JobExecutionDispatcher
    queue: JobQueue | None = None


def _handle_task_failure(task: asyncio.Task[Any], on_error: ErrorHandler) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    except Exception as read_exc:  # pragma: no cover - defensive
        on_error(read_exc)
        return
    if exc:
        on_error(exc)

