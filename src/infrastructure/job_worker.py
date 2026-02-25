"""Execution-plane queue worker."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from infrastructure.job_queue import JobQueue


logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobQueueWorker:
    """Consumes jobs from queue and executes them through ExecutionSupervisor."""

    def __init__(self, *, queue: JobQueue, supervisor: Any, run_state_store: Any) -> None:
        self._queue = queue
        self._supervisor = supervisor
        self._run_state_store = run_state_store

    async def run_forever(self, *, poll_timeout_s: float = 1.0, sleep_when_idle_s: float = 0.1) -> None:
        while True:
            envelope = await asyncio.to_thread(self._queue.dequeue, poll_timeout_s)
            if envelope is None:
                await asyncio.sleep(max(0.0, sleep_when_idle_s))
                continue
            job_id = envelope.job_id
            if not job_id:
                continue
            try:
                self._run_state_store.append_event(
                    job_id,
                    "job.worker_claimed",
                    {"jobId": job_id, "source": envelope.source},
                )
                await self._supervisor.execute_job(job_id)
            except Exception as exc:
                logger.warning("Execution worker failed (job_id=%s): %s", job_id, exc)
                self._run_state_store.patch_job(
                    job_id,
                    status="needs_attention",
                    finished_at=_utcnow(),
                    incident_uri=None,
                )
                self._run_state_store.append_event(
                    job_id,
                    "job.worker_failed",
                    {"jobId": job_id, "status": "needs_attention", "message": str(exc)},
                )

