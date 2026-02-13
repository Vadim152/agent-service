from __future__ import annotations

import asyncio
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes_chat import router as chat_router
from chat.memory_store import ChatMemoryStore
from chat.runtime import ChatAgentRuntime
from infrastructure.run_state_store import RunStateStore


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wait_until(assertion, timeout_s: float = 4.0) -> None:
    started = time.time()
    while time.time() - started < timeout_s:
        if assertion():
            return
        time.sleep(0.05)
    raise AssertionError("Condition was not met before timeout")


def _build_app() -> FastAPI:
    app = FastAPI()
    base = Path(tempfile.mkdtemp(prefix="chat-memory-"))
    memory_store = ChatMemoryStore(base)
    app.state.chat_runtime = ChatAgentRuntime(memory_store=memory_store)
    app.include_router(chat_router)
    return app


class _OrchestratorStub:
    def apply_feature(
        self,
        project_root: str,
        target_path: str,
        feature_text: str,
        *,
        overwrite_existing: bool = False,
    ) -> dict[str, object]:
        _ = (feature_text, overwrite_existing)
        return {
            "projectRoot": project_root,
            "targetPath": target_path,
            "status": "created",
            "message": None,
        }


class _SupervisorStub:
    def __init__(self, store: RunStateStore) -> None:
        self.store = store

    async def execute_job(self, job_id: str) -> None:
        self.store.patch_job(
            job_id,
            status="succeeded",
            finished_at=_utcnow(),
            result={
                "featureText": "Feature: Chat generated\n  Scenario: Demo\n    Given step",
                "unmappedSteps": [],
                "unmapped": [],
                "usedSteps": [],
                "buildStage": "feature_built",
                "stepsSummary": {"exact": 1, "fuzzy": 0, "unmatched": 0},
                "meta": {"language": "ru"},
                "pipeline": [
                    {"stage": "source_resolve", "status": "raw_text", "details": {}},
                    {"stage": "parse", "status": "ok", "details": {}},
                ],
                "fileStatus": None,
            },
        )


def _build_autotest_app() -> FastAPI:
    app = FastAPI()
    base = Path(tempfile.mkdtemp(prefix="chat-memory-autotest-"))
    memory_store = ChatMemoryStore(base)
    run_state_store = RunStateStore()
    app.state.chat_runtime = ChatAgentRuntime(
        memory_store=memory_store,
        orchestrator=_OrchestratorStub(),
        run_state_store=run_state_store,
        execution_supervisor=_SupervisorStub(run_state_store),
    )
    app.include_router(chat_router)
    return app


def test_chat_session_create_and_reuse() -> None:
    app = _build_app()
    client = TestClient(app)

    first = client.post(
        "/chat/sessions",
        json={"projectRoot": "/tmp/project", "source": "test-suite", "profile": "quick"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["reused"] is False

    second = client.post(
        "/chat/sessions",
        json={"projectRoot": "/tmp/project", "source": "test-suite", "profile": "quick"},
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["reused"] is True
    assert second_payload["sessionId"] == first_payload["sessionId"]


def test_list_chat_sessions_for_project() -> None:
    app = _build_app()
    client = TestClient(app)

    assert client.post("/chat/sessions", json={"projectRoot": "/tmp/project-a", "reuseExisting": False}).status_code == 200
    assert client.post("/chat/sessions", json={"projectRoot": "/tmp/project-a", "reuseExisting": False}).status_code == 200
    assert client.post("/chat/sessions", json={"projectRoot": "/tmp/project-b", "reuseExisting": False}).status_code == 200

    listed = client.get("/chat/sessions", params={"projectRoot": "/tmp/project-a", "limit": 10})
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total"] == 2
    assert len(payload["items"]) == 2
    assert all(item["projectRoot"] == "/tmp/project-a" for item in payload["items"])


def test_send_message_and_read_history() -> None:
    app = _build_app()
    client = TestClient(app)

    session = client.post("/chat/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]

    send = client.post(f"/chat/sessions/{session_id}/messages", json={"content": "hello"})
    assert send.status_code == 200

    def _assistant_replied() -> bool:
        history = client.get(f"/chat/sessions/{session_id}/history").json()
        assistant = [msg for msg in history["messages"] if msg["role"] == "assistant"]
        return len(assistant) > 0

    _wait_until(_assistant_replied)

    history = client.get(f"/chat/sessions/{session_id}/history").json()
    assert len(history["pendingPermissions"]) == 0
    assert any(msg["role"] == "assistant" for msg in history["messages"])


def test_send_message_rejects_when_session_is_busy() -> None:
    app = _build_app()
    client = TestClient(app)

    session = client.post("/chat/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]
    app.state.chat_runtime.state_store.update_session(
        session_id,
        activity="busy",
        current_action="Processing request",
    )

    response = client.post(f"/chat/sessions/{session_id}/messages", json={"content": "hello again"})
    assert response.status_code == 409
    assert "Session is busy" in response.json()["detail"]


def test_permission_decision_approves_tool_execution() -> None:
    app = _build_app()
    client = TestClient(app)

    session = client.post("/chat/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]
    client.post(f"/chat/sessions/{session_id}/messages", json={"content": "write login feature"})

    _wait_until(lambda: len(client.get(f"/chat/sessions/{session_id}/history").json()["pendingPermissions"]) == 1)
    pending = client.get(f"/chat/sessions/{session_id}/history").json()["pendingPermissions"][0]

    decision = client.post(
        f"/chat/sessions/{session_id}/tool-decisions",
        json={"permissionId": pending["permissionId"], "decision": "approve_once"},
    )
    assert decision.status_code == 200

    _wait_until(lambda: len(client.get(f"/chat/sessions/{session_id}/history").json()["pendingPermissions"]) == 0)
    diff = client.get(f"/chat/sessions/{session_id}/diff").json()
    assert diff["summary"]["files"] == 1


def test_status_and_diff_endpoints_return_control_plane() -> None:
    app = _build_app()
    client = TestClient(app)
    session = client.post("/chat/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]
    client.post(f"/chat/sessions/{session_id}/messages", json={"content": "write test"})

    _wait_until(lambda: len(client.get(f"/chat/sessions/{session_id}/history").json()["pendingPermissions"]) == 1)

    status_response = client.get(f"/chat/sessions/{session_id}/status")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["pendingPermissionsCount"] == 1
    assert status_payload["risk"]["level"] in {"medium", "high"}
    assert status_payload["lastRetryMessage"] is None
    assert status_payload["lastRetryAttempt"] is None
    assert status_payload["lastRetryAt"] is None

    diff_response = client.get(f"/chat/sessions/{session_id}/diff")
    assert diff_response.status_code == 200
    diff_payload = diff_response.json()
    assert diff_payload["summary"]["files"] >= 0


def test_commands_endpoint_executes_runtime_command() -> None:
    app = _build_app()
    client = TestClient(app)
    session = client.post("/chat/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]

    response = client.post(f"/chat/sessions/{session_id}/commands", json={"command": "compact"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["command"] == "compact"


def test_commands_endpoint_rejects_unknown_command() -> None:
    app = _build_app()
    client = TestClient(app)
    session = client.post("/chat/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]

    response = client.post(f"/chat/sessions/{session_id}/commands", json={"command": "unknown"})
    assert response.status_code == 422


def test_status_exposes_retry_metadata_when_present() -> None:
    app = _build_app()
    client = TestClient(app)
    session = client.post("/chat/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]

    app.state.chat_runtime.state_store.update_session(
        session_id,
        activity="retry",
        current_action="Too Many Requests: Rate limit exceeded (attempt 2)",
        last_retry_message="Too Many Requests: Rate limit exceeded",
        last_retry_attempt=2,
        last_retry_at=_utcnow(),
    )

    response = client.get(f"/chat/sessions/{session_id}/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["activity"] == "retry"
    assert payload["lastRetryMessage"] == "Too Many Requests: Rate limit exceeded"
    assert payload["lastRetryAttempt"] == 2
    assert payload["lastRetryAt"] is not None


def test_chat_stream_supports_from_index() -> None:
    app = _build_app()
    client = TestClient(app)
    session = client.post("/chat/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]
    app.state.chat_runtime.state_store.append_event(session_id, "event.zero", {"v": 0})
    app.state.chat_runtime.state_store.append_event(session_id, "event.one", {"v": 1})

    async def _collect_first_chunk() -> bytes:
        stream = app.state.chat_runtime.stream_events(session_id=session_id, from_index=2)
        try:
            return await asyncio.wait_for(anext(stream), timeout=2.0)
        finally:
            await stream.aclose()

    chunk = asyncio.run(_collect_first_chunk()).decode("utf-8")
    data_line = next(line for line in chunk.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line[len("data: ") :])
    assert payload["index"] == 2
    assert payload["eventType"] == "event.one"


def test_autotest_natural_message_creates_preview_and_pending_save() -> None:
    app = _build_autotest_app()
    client = TestClient(app)
    session = client.post("/chat/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"content": "Сгенерируй автотест по этому тесткейсу"},
    )
    assert response.status_code == 200

    def _has_pending_permission() -> bool:
        history = client.get(f"/chat/sessions/{session_id}/history").json()
        return len(history["pendingPermissions"]) == 1

    _wait_until(_has_pending_permission)
    history = client.get(f"/chat/sessions/{session_id}/history").json()
    assert "Autotest preview is ready." in history["messages"][-1]["content"]
    assert history["pendingPermissions"][0]["title"] == "Save generated feature file"


def test_autotest_save_permission_executes_save_tool() -> None:
    app = _build_autotest_app()
    client = TestClient(app)
    session = client.post("/chat/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]

    client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"content": "Сгенерируй автотест и предложи сохранить"},
    )
    _wait_until(lambda: len(client.get(f"/chat/sessions/{session_id}/history").json()["pendingPermissions"]) == 1)
    permission = client.get(f"/chat/sessions/{session_id}/history").json()["pendingPermissions"][0]

    decision = client.post(
        f"/chat/sessions/{session_id}/tool-decisions",
        json={"permissionId": permission["permissionId"], "decision": "approve_once"},
    )
    assert decision.status_code == 200
    _wait_until(lambda: len(client.get(f"/chat/sessions/{session_id}/history").json()["pendingPermissions"]) == 0)
    history = client.get(f"/chat/sessions/{session_id}/history").json()
    assert any("Feature file created" in msg["content"] for msg in history["messages"] if msg["role"] == "assistant")

