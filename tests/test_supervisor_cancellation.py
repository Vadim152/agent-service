from __future__ import annotations

import asyncio
from pathlib import Path

from infrastructure.artifact_store import ArtifactStore
from infrastructure.run_state_store import RunStateStore
from self_healing.supervisor import ExecutionSupervisor


class _CancellingOrchestrator:
    def __init__(self, store: RunStateStore, job_id: str) -> None:
        self._store = store
        self._job_id = job_id

    def generate_feature(self, *_args, **_kwargs):
        self._store.patch_job(self._job_id, status="cancelling", cancel_requested=True)
        return {
            "feature": {"featureText": "Feature: demo", "unmappedSteps": []},
            "matchResult": {"matched": [], "unmatched": []},
        }


def test_supervisor_respects_cancel_requested_after_attempt(tmp_path: Path) -> None:
    store = RunStateStore()
    job_id = "job-cancel-mid-flight"
    store.put_job(
        {
            "job_id": job_id,
            "status": "queued",
            "cancel_requested": False,
            "project_root": "/tmp/project",
            "test_case_text": "Given user is logged in",
            "target_path": None,
            "create_file": False,
            "overwrite_existing": False,
            "language": None,
            "profile": "quick",
            "source": "tests",
            "started_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "attempts": [],
            "result": None,
        }
    )

    supervisor = ExecutionSupervisor(
        orchestrator=_CancellingOrchestrator(store, job_id),
        run_state_store=store,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
    )

    asyncio.run(supervisor.execute_job(job_id))

    item = store.get_job(job_id)
    assert item is not None
    assert item["status"] == "cancelled"
    assert item["result"] is None

    events, _ = store.list_events(job_id)
    event_types = [event["event_type"] for event in events]
    assert "attempt.cancelled" in event_types
    assert "job.cancelled" in event_types
