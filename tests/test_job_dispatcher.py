from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from infrastructure.job_dispatcher import LocalJobExecutionDispatcher, QueueJobExecutionDispatcher
from infrastructure.job_queue import LocalJobQueue
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


def test_queue_dispatcher_enqueues_run_and_appends_event() -> None:
    queue = LocalJobQueue()
    dispatcher = QueueJobExecutionDispatcher(queue=queue)
    store = RunStateStore()
    store.put_job(_new_job("j1"))

    dispatcher.dispatch(
        run_id="j1",
        source="runs",
        supervisor=None,
        run_state_store=store,
        task_registry=None,
        on_error=None,
    )

    lease = queue.receive(timeout_s=0.01)
    assert lease is not None
    assert lease.envelope.run_id == "j1"
    lease.ack()
    events, _ = store.list_events("j1", since_index=0)
    assert events
    assert events[-1]["event_type"] == "run.dispatched"


def test_local_dispatcher_executes_supervisor_in_background() -> None:
    dispatcher = LocalJobExecutionDispatcher()
    store = RunStateStore()
    store.put_job(_new_job("j2"))
    call = {"run_id": None}
    done = asyncio.Event()

    class _Supervisor:
        async def execute_run(self, run_id: str) -> None:
            call["run_id"] = run_id
            done.set()

    async def _run() -> None:
        dispatcher.dispatch(
            run_id="j2",
            source="runs",
            supervisor=_Supervisor(),
            run_state_store=store,
            task_registry=None,
            on_error=None,
        )
        await asyncio.wait_for(done.wait(), timeout=1.0)

    asyncio.run(_run())
    assert call["run_id"] == "j2"
