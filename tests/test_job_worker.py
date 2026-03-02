from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from infrastructure.job_queue import JobEnvelope, LocalJobQueue
from infrastructure.job_worker import JobQueueWorker
from infrastructure.run_state_store import RunStateStore


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_job(run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "status": "queued",
        "started_at": _utcnow(),
        "updated_at": _utcnow(),
        "attempts": [],
        "result": None,
    }


def test_job_worker_processes_local_queue_items() -> None:
    queue = LocalJobQueue()
    store = RunStateStore()
    store.put_job(_new_job("j1"))
    queue.enqueue(JobEnvelope(run_id="j1", source="runs", enqueued_at=_utcnow()))
    seen: list[str] = []
    stop = asyncio.Event()

    class _Supervisor:
        async def execute_run(self, run_id: str) -> None:
            seen.append(run_id)
            stop.set()

    worker = JobQueueWorker(queue=queue, supervisor=_Supervisor(), run_state_store=store)

    async def _run() -> None:
        task = asyncio.create_task(worker.run_forever(poll_timeout_s=0.01, sleep_when_idle_s=0.01))
        await asyncio.wait_for(stop.wait(), timeout=1.0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())

    assert seen == ["j1"]
    events, _ = store.list_events("j1", since_index=0)
    assert [event["event_type"] for event in events][-1] == "run.worker_claimed"


def test_job_worker_marks_failed_jobs_without_requeue() -> None:
    queue = LocalJobQueue()
    store = RunStateStore()
    store.put_job(_new_job("j2"))
    queue.enqueue(JobEnvelope(run_id="j2", source="runs", enqueued_at=_utcnow()))
    stop = asyncio.Event()

    class _Supervisor:
        async def execute_run(self, run_id: str) -> None:
            stop.set()
            raise RuntimeError(f"boom:{run_id}")

    worker = JobQueueWorker(queue=queue, supervisor=_Supervisor(), run_state_store=store)

    async def _run() -> None:
        task = asyncio.create_task(worker.run_forever(poll_timeout_s=0.01, sleep_when_idle_s=0.01))
        await asyncio.wait_for(stop.wait(), timeout=1.0)
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())

    run_record = store.get_job("j2")
    assert run_record is not None
    assert run_record["status"] == "needs_attention"
    events, _ = store.list_events("j2", since_index=0)
    assert [event["event_type"] for event in events][-1] == "run.worker_failed"
