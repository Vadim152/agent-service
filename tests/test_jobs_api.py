from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes_jobs import router as jobs_router
from infrastructure.run_state_store import RunStateStore


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class _NoopSupervisor:
    async def execute_job(self, job_id: str) -> None:  # pragma: no cover - execution is not relevant for API schema checks
        _ = job_id


def _build_app() -> tuple[FastAPI, RunStateStore]:
    app = FastAPI()
    store = RunStateStore()
    app.state.run_state_store = store
    app.state.execution_supervisor = _NoopSupervisor()
    app.include_router(jobs_router)
    return app, store


def test_create_job_initializes_result_and_attempts() -> None:
    app, store = _build_app()
    client = TestClient(app)

    response = client.post(
        "/jobs",
        json={
            "projectRoot": "/tmp/project",
            "testCaseText": "Given something",
            "jiraInstance": "https://jira.sberbank.ru",
            "zephyrAuth": {"authType": "TOKEN", "token": "secret"},
            "source": "test-suite",
            "profile": "quick",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    item = store.get_job(payload["jobId"])
    assert item is not None
    assert item["jira_instance"] == "https://jira.sberbank.ru"
    assert item["zephyr_auth"] == {"authType": "TOKEN", "token": "secret", "login": None, "password": None}
    assert item["result"] is None
    assert item["attempts"] == []


def test_get_job_attempts_returns_attempt_payload() -> None:
    app, store = _build_app()
    client = TestClient(app)

    store.put_job(
        {
            "job_id": "j1",
            "run_id": "r1",
            "status": "running",
            "source": "test-suite",
            "started_at": _utcnow(),
            "updated_at": _utcnow(),
            "attempts": [
                {
                    "attempt_id": "a1",
                    "status": "failed",
                    "started_at": _utcnow(),
                    "finished_at": _utcnow(),
                    "classification": {"category": "infra", "confidence": 0.8, "signals": [], "summary": "infra"},
                    "artifacts": {"featureResult": "/tmp/result.json"},
                }
            ],
            "result": None,
        }
    )

    response = client.get("/jobs/j1/attempts")
    assert response.status_code == 200
    payload = response.json()
    assert payload["jobId"] == "j1"
    assert payload["runId"] == "r1"
    assert len(payload["attempts"]) == 1
    assert payload["attempts"][0]["attemptId"] == "a1"
    assert payload["attempts"][0]["status"] == "failed"


def test_get_job_result_returns_ready_payload() -> None:
    app, store = _build_app()
    client = TestClient(app)

    store.put_job(
        {
            "job_id": "j2",
            "run_id": "r2",
            "status": "succeeded",
            "source": "test-suite",
            "incident_uri": None,
            "started_at": _utcnow(),
            "finished_at": _utcnow(),
            "updated_at": _utcnow(),
            "attempts": [],
            "result": {
                "featureText": "Feature: sample",
                "unmappedSteps": [],
                "unmapped": [],
                "usedSteps": [],
                "buildStage": "ok",
                "stepsSummary": {"exact": 1, "fuzzy": 0, "unmatched": 0},
                "meta": {"language": "en"},
                "pipeline": [],
                "fileStatus": None,
            },
        }
    )

    response = client.get("/jobs/j2/result")
    assert response.status_code == 200
    payload = response.json()
    assert payload["jobId"] == "j2"
    assert payload["status"] == "succeeded"
    assert payload["feature"]["featureText"] == "Feature: sample"
    assert payload["feature"]["stepsSummary"]["exact"] == 1


def test_get_job_result_returns_409_when_not_ready() -> None:
    app, store = _build_app()
    client = TestClient(app)

    store.put_job(
        {
            "job_id": "j3",
            "status": "running",
            "started_at": _utcnow(),
            "updated_at": _utcnow(),
            "attempts": [],
            "result": None,
        }
    )
    response = client.get("/jobs/j3/result")
    assert response.status_code == 409


def test_cancel_job_marks_job_as_cancelling() -> None:
    app, store = _build_app()
    client = TestClient(app)
    store.put_job(
        {
            "job_id": "j4",
            "status": "running",
            "started_at": _utcnow(),
            "updated_at": _utcnow(),
            "attempts": [],
            "result": None,
        }
    )

    response = client.post("/jobs/j4/cancel")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "cancelling"
    assert payload["cancelRequested"] is True
    item = store.get_job("j4")
    assert item is not None
    assert item["cancel_requested"] is True
    assert item["status"] == "cancelling"


def test_job_events_store_supports_from_index() -> None:
    _, store = _build_app()
    store.put_job(
        {
            "job_id": "j5",
            "status": "running",
            "started_at": _utcnow(),
            "updated_at": _utcnow(),
            "attempts": [],
            "result": None,
        }
    )
    store.append_event("j5", "event.zero", {"v": 0})
    store.append_event("j5", "event.one", {"v": 1})
    events, next_index = store.list_events("j5", since_index=1)
    assert next_index == 2
    assert len(events) == 1
    assert events[0]["index"] == 1
    assert events[0]["event_type"] == "event.one"
