from __future__ import annotations

import asyncio
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes_policy import router as policy_router
from api.routes_sessions import router as sessions_router
from chat.memory_store import ChatMemoryStore
from chat.runtime import ChatAgentRuntime
from infrastructure.run_state_store import RunStateStore
from policy import InMemoryPolicyStore, PolicyService


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wait_until(assertion, timeout_s: float = 4.0) -> None:
    started = time.time()
    while time.time() - started < timeout_s:
        if assertion():
            return
        time.sleep(0.05)
    raise AssertionError("Condition was not met before timeout")


def _bind_policy(chat_runtime: ChatAgentRuntime) -> PolicyService:
    policy_service = PolicyService(
        state_store=chat_runtime.state_store,
        store=InMemoryPolicyStore(),
    )
    chat_runtime.bind_policy_service(policy_service)
    policy_service.bind_decision_executor(
        lambda session_id, run_id, approval_id, decision: chat_runtime.process_tool_decision(
            session_id=session_id,
            run_id=run_id,
            permission_id=approval_id,
            decision=decision,
        )
    )
    policy_service.sync_tools(chat_runtime.describe_registered_tools())
    return policy_service


def _build_app() -> FastAPI:
    app = FastAPI()
    base = Path(tempfile.mkdtemp(prefix="chat-memory-"))
    memory_store = ChatMemoryStore(base)
    chat_runtime = ChatAgentRuntime(memory_store=memory_store)
    app.state.chat_runtime = chat_runtime
    app.state.policy_service = _bind_policy(chat_runtime)
    app.include_router(sessions_router)
    app.include_router(policy_router)
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

    async def execute_run(self, run_id: str) -> None:
        run_record = self.store.get_job(run_id) or {}
        testcase_text = str(run_record.get("test_case_text", "")).upper()
        jira_key = "SCBC-T1" if "SCBC-T1" in testcase_text else None
        self.store.patch_job(
            run_id,
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
                    {"stage": "source_resolve", "status": "raw_text", "details": {"jiraKey": jira_key}},
                    {"stage": "parse", "status": "ok", "details": {}},
                ],
                "fileStatus": None,
            },
        )


class _SupervisorNoResultStub:
    def __init__(self, store: RunStateStore) -> None:
        self.store = store

    async def execute_run(self, run_id: str) -> None:
        self.store.patch_job(
            run_id,
            status="needs_attention",
            finished_at=_utcnow(),
            incident_uri="artifact://incident-json",
            result=None,
        )


def _build_autotest_app(supervisor_cls=_SupervisorStub) -> FastAPI:
    app = FastAPI()
    base = Path(tempfile.mkdtemp(prefix="chat-memory-autotest-"))
    memory_store = ChatMemoryStore(base)
    run_state_store = RunStateStore()
    chat_runtime = ChatAgentRuntime(
        memory_store=memory_store,
        orchestrator=_OrchestratorStub(),
        run_state_store=run_state_store,
        execution_supervisor=supervisor_cls(run_state_store),
    )
    app.state.chat_runtime = chat_runtime
    app.state.policy_service = _bind_policy(chat_runtime)
    app.state.run_state_store = run_state_store
    app.include_router(sessions_router)
    app.include_router(policy_router)
    return app


def _approve_pending_permission(client: TestClient, session_id: str) -> dict[str, object]:
    _wait_until(lambda: len(client.get(f"/sessions/{session_id}/history").json()["pendingPermissions"]) == 1)
    permission = client.get(f"/sessions/{session_id}/history").json()["pendingPermissions"][0]
    response = client.post(
        f"/policy/approvals/{permission['permissionId']}/decision",
        json={"decision": "approve"},
    )
    assert response.status_code == 200
    _wait_until(lambda: len(client.get(f"/sessions/{session_id}/history").json()["pendingPermissions"]) == 0)
    return permission


def test_chat_session_create_and_reuse() -> None:
    client = TestClient(_build_app())

    first = client.post(
        "/sessions",
        json={"projectRoot": "/tmp/project", "source": "test-suite", "profile": "quick"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["reused"] is False

    second = client.post(
        "/sessions",
        json={"projectRoot": "/tmp/project", "source": "test-suite", "profile": "quick"},
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["reused"] is True
    assert second_payload["sessionId"] == first_payload["sessionId"]


def test_list_chat_sessions_for_project() -> None:
    client = TestClient(_build_app())

    assert client.post("/sessions", json={"projectRoot": "/tmp/project-a", "reuseExisting": False}).status_code == 200
    assert client.post("/sessions", json={"projectRoot": "/tmp/project-a", "reuseExisting": False}).status_code == 200
    assert client.post("/sessions", json={"projectRoot": "/tmp/project-b", "reuseExisting": False}).status_code == 200

    listed = client.get("/sessions", params={"projectRoot": "/tmp/project-a", "limit": 10})
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total"] == 2
    assert len(payload["items"]) == 2
    assert all(item["projectRoot"] == "/tmp/project-a" for item in payload["items"])


def test_send_message_and_read_history() -> None:
    client = TestClient(_build_app())
    session = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]

    send = client.post(f"/sessions/{session_id}/messages", json={"content": "hello"})
    assert send.status_code == 200

    def _assistant_replied() -> bool:
        history = client.get(f"/sessions/{session_id}/history").json()
        assistant = [msg for msg in history["messages"] if msg["role"] == "assistant"]
        return len(assistant) > 0

    _wait_until(_assistant_replied)
    history = client.get(f"/sessions/{session_id}/history").json()
    assert len(history["pendingPermissions"]) == 0
    assert any(msg["role"] == "assistant" for msg in history["messages"])


def test_send_message_rejects_when_session_is_busy() -> None:
    app = _build_app()
    client = TestClient(app)
    session = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]
    app.state.chat_runtime.state_store.update_session(
        session_id,
        activity="busy",
        current_action="Processing request",
    )

    response = client.post(f"/sessions/{session_id}/messages", json={"content": "hello again"})
    assert response.status_code == 409
    assert "Session is busy" in response.json()["detail"]


def test_permission_decision_approves_tool_execution() -> None:
    app = _build_app()
    client = TestClient(app)
    session_id = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()["sessionId"]
    client.post(f"/sessions/{session_id}/messages", json={"content": "write login feature"})

    _approve_pending_permission(client, session_id)
    diff = client.get(f"/sessions/{session_id}/diff").json()
    assert diff["summary"]["files"] == 1

    audit_events = asyncio.run(app.state.policy_service.list_audit_events(limit=10))
    event_types = [item["eventType"] for item in audit_events]
    assert "permission.requested" in event_types
    assert "permission.approved" in event_types


def test_permission_decision_via_policy_writes_policy_audit() -> None:
    app = _build_app()
    client = TestClient(app)
    session_id = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()["sessionId"]
    client.post(f"/sessions/{session_id}/messages", json={"content": "write login feature"})

    _approve_pending_permission(client, session_id)

    audit_events = asyncio.run(app.state.policy_service.list_audit_events(limit=10))
    approved = [item for item in audit_events if item["eventType"] == "permission.approved"]
    assert approved


def test_status_and_diff_endpoints_return_control_plane() -> None:
    client = TestClient(_build_app())
    session_id = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()["sessionId"]
    client.post(f"/sessions/{session_id}/messages", json={"content": "write test"})

    _wait_until(lambda: len(client.get(f"/sessions/{session_id}/history").json()["pendingPermissions"]) == 1)

    status_response = client.get(f"/sessions/{session_id}/status")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["pendingPermissionsCount"] == 1
    assert status_payload["risk"]["level"] in {"medium", "high"}
    assert status_payload["lastRetryMessage"] is None
    assert status_payload["lastRetryAttempt"] is None
    assert status_payload["lastRetryAt"] is None

    diff_response = client.get(f"/sessions/{session_id}/diff")
    assert diff_response.status_code == 200
    diff_payload = diff_response.json()
    assert diff_payload["summary"]["files"] >= 0


def test_commands_endpoint_executes_runtime_command() -> None:
    client = TestClient(_build_app())
    session_id = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()["sessionId"]

    response = client.post(f"/sessions/{session_id}/commands", json={"command": "compact"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["command"] == "compact"


def test_commands_endpoint_rejects_unknown_command() -> None:
    client = TestClient(_build_app())
    session_id = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()["sessionId"]

    response = client.post(f"/sessions/{session_id}/commands", json={"command": "unknown"})
    assert response.status_code == 422


def test_status_exposes_retry_metadata_when_present() -> None:
    app = _build_app()
    client = TestClient(app)
    session_id = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()["sessionId"]

    app.state.chat_runtime.state_store.update_session(
        session_id,
        activity="retry",
        current_action="Too Many Requests: Rate limit exceeded (attempt 2)",
        last_retry_message="Too Many Requests: Rate limit exceeded",
        last_retry_attempt=2,
        last_retry_at=_utcnow(),
    )

    response = client.get(f"/sessions/{session_id}/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["activity"] == "retry"
    assert payload["lastRetryMessage"] == "Too Many Requests: Rate limit exceeded"
    assert payload["lastRetryAttempt"] == 2
    assert payload["lastRetryAt"] is not None


def test_chat_stream_supports_from_index() -> None:
    app = _build_app()
    client = TestClient(app)
    session_id = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()["sessionId"]
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
    client = TestClient(_build_autotest_app())
    session_id = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()["sessionId"]

    response = client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "generate feature from this test case"},
    )
    assert response.status_code == 200

    def _has_pending_permission() -> bool:
        history = client.get(f"/sessions/{session_id}/history").json()
        return len(history["pendingPermissions"]) == 1

    _wait_until(_has_pending_permission)
    history = client.get(f"/sessions/{session_id}/history").json()
    assert "feature" in history["messages"][-1]["content"].lower()
    assert "feature" in history["pendingPermissions"][0]["title"].lower()


def test_autotest_without_feature_result_finishes_without_worker_crash() -> None:
    client = TestClient(_build_autotest_app(supervisor_cls=_SupervisorNoResultStub))
    session_id = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()["sessionId"]

    response = client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "generate feature"},
    )
    assert response.status_code == 200

    def _assistant_replied_without_pending() -> bool:
        history = client.get(f"/sessions/{session_id}/history").json()
        assistant = [msg for msg in history["messages"] if msg["role"] == "assistant"]
        return len(assistant) > 0 and len(history["pendingPermissions"]) == 0

    _wait_until(_assistant_replied_without_pending)
    history = client.get(f"/sessions/{session_id}/history").json()
    assert "feature" in history["messages"][-1]["content"].lower()
    event_types = [event["eventType"] for event in history["events"]]
    assert "message.worker_failed" not in event_types

    status_payload = client.get(f"/sessions/{session_id}/status").json()
    assert status_payload["activity"] == "idle"


def test_autotest_save_permission_executes_save_tool() -> None:
    client = TestClient(_build_autotest_app())
    session_id = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()["sessionId"]

    client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "generate feature and suggest save"},
    )
    _approve_pending_permission(client, session_id)
    history = client.get(f"/sessions/{session_id}/history").json()
    assert any("feature" in msg["content"].lower() for msg in history["messages"] if msg["role"] == "assistant")


def test_autotest_uses_jira_key_as_default_target_path() -> None:
    client = TestClient(_build_autotest_app())
    session_id = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()["sessionId"]

    response = client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "generate feature for SCBC-T1"},
    )
    assert response.status_code == 200

    _wait_until(lambda: len(client.get(f"/sessions/{session_id}/history").json()["pendingPermissions"]) == 1)
    history = client.get(f"/sessions/{session_id}/history").json()
    pending = history["pendingPermissions"][0]
    assert pending["metadata"]["target_path"] == "src/test/resources/features/SCBC-T1.feature"


def test_chat_autotest_job_inherits_session_zephyr_auth_and_jira_instance() -> None:
    app = _build_autotest_app()
    client = TestClient(app)
    session_id = client.post(
        "/sessions",
        json={
            "projectRoot": "/tmp/project",
            "zephyrAuth": {"authType": "TOKEN", "token": "demo-token"},
            "jiraInstance": "https://jira.sberbank.ru",
        },
    ).json()["sessionId"]

    response = client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "generate feature for SCBC-T3282"},
    )
    assert response.status_code == 200

    def _has_run_with_auth() -> bool:
        runs = getattr(app.state.run_state_store, "_runs", {})
        return any(item.get("zephyr_auth") for item in runs.values())

    _wait_until(_has_run_with_auth)
    runs = getattr(app.state.run_state_store, "_runs", {})
    assert runs
    created_run = next(iter(runs.values()))
    assert created_run["zephyr_auth"] == {
        "authType": "TOKEN",
        "token": "demo-token",
        "login": None,
        "password": None,
    }
    assert created_run["jira_instance"] == "https://jira.sberbank.ru"
