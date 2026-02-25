from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from infrastructure.job_dispatcher import LocalJobExecutionDispatcher, QueueJobExecutionDispatcher
from infrastructure.job_queue import LocalJobQueue
from infrastructure.run_state_store import RunStateStore


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_job(job_id: str) -> dict[str, object]:
    return {
        "job_id": job_id,
        "status": "queued",
        "started_at": _utcnow(),
        "updated_at": _utcnow(),
        "attempts": [],
        "result": None,
    }


def test_queue_dispatcher_enqueues_job_and_appends_event() -> None:
    queue = LocalJobQueue()
    dispatcher = QueueJobExecutionDispatcher(queue=queue)
    store = RunStateStore()
    store.put_job(_new_job("j1"))

    dispatcher.dispatch(
        job_id="j1",
        source="jobs",
        supervisor=None,
        run_state_store=store,
        task_registry=None,
        on_error=None,
    )

    envelope = queue.dequeue(timeout_s=0.01)
    assert envelope is not None
    assert envelope.job_id == "j1"
    events, _ = store.list_events("j1", since_index=0)
    assert events
    assert events[-1]["event_type"] == "job.dispatched"


def test_local_dispatcher_executes_supervisor_in_background() -> None:
    dispatcher = LocalJobExecutionDispatcher()
    store = RunStateStore()
    store.put_job(_new_job("j2"))
    call = {"job_id": None}
    done = asyncio.Event()

    class _Supervisor:
        async def execute_job(self, job_id: str) -> None:
            call["job_id"] = job_id
            done.set()

    async def _run() -> None:
        dispatcher.dispatch(
            job_id="j2",
            source="jobs",
            supervisor=_Supervisor(),
            run_state_store=store,
            task_registry=None,
            on_error=None,
        )
        await asyncio.wait_for(done.wait(), timeout=1.0)

    asyncio.run(_run())
    assert call["job_id"] == "j2"

