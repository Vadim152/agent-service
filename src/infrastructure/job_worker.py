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
    """Consumes runs from queue and executes them through ExecutionSupervisor."""

    def __init__(self, *, queue: JobQueue, supervisor: Any, run_state_store: Any, concurrency: int = 1) -> None:
        self._queue = queue
        self._supervisor = supervisor
        self._run_state_store = run_state_store
        self._concurrency = max(1, int(concurrency))

    async def run_forever(self, *, poll_timeout_s: float = 1.0, sleep_when_idle_s: float = 0.1) -> None:
        consumers = [
            asyncio.create_task(
                self._consume_loop(poll_timeout_s=poll_timeout_s, sleep_when_idle_s=sleep_when_idle_s)
            )
            for _ in range(self._concurrency)
        ]
        try:
            await asyncio.gather(*consumers)
        finally:
            for task in consumers:
                task.cancel()

    async def _consume_loop(self, *, poll_timeout_s: float, sleep_when_idle_s: float) -> None:
        while True:
            lease = await asyncio.to_thread(self._queue.receive, poll_timeout_s)
            if lease is None:
                await asyncio.sleep(max(0.0, sleep_when_idle_s))
                continue
            envelope = lease.envelope
            run_id = envelope.run_id
            if not run_id:
                lease.reject(requeue=False)
                continue
            try:
                self._run_state_store.append_event(
                    run_id,
                    "run.worker_claimed",
                    {"runId": run_id, "source": envelope.source},
                )
                execute = getattr(self._supervisor, "execute_run", None) or self._supervisor.execute_job
                await execute(run_id)
                lease.ack()
            except Exception as exc:
                logger.warning("Execution worker failed (run_id=%s): %s", run_id, exc)
                self._run_state_store.patch_job(
                    run_id,
                    status="needs_attention",
                    finished_at=_utcnow(),
                    incident_uri=None,
                )
                self._run_state_store.append_event(
                    run_id,
                    "run.worker_failed",
                    {"runId": run_id, "status": "needs_attention", "message": str(exc)},
                )
                lease.reject(requeue=False)
