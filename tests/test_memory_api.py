from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes_memory import router as memory_router
from infrastructure.project_learning_store import ProjectLearningStore


def test_memory_feedback_updates_step_boost(tmp_path) -> None:
    app = FastAPI()
    learning_store = ProjectLearningStore(tmp_path / "learning")
    app.state.orchestrator = SimpleNamespace(project_learning_store=learning_store)
    app.include_router(memory_router)
    client = TestClient(app)

    response = client.post(
        "/memory/feedback",
        json={
            "projectRoot": "/tmp/project",
            "stepId": "step-1",
            "accepted": True,
            "note": "Good mapping",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projectRoot"] == "/tmp/project"
    assert payload["stepBoosts"]["step-1"] > 0.0
    assert payload["feedbackCount"] == 1

