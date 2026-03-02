from __future__ import annotations

import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes_policy import router as policy_router
from api.routes_runs import router as runs_router
from api.routes_sessions import router as sessions_router
from chat.memory_store import ChatMemoryStore
from chat.runtime import ChatAgentRuntime
from infrastructure.artifact_index_store import InMemoryArtifactIndexStore
from infrastructure.artifact_store import ArtifactStore
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


class _OrchestratorStub:
    def apply_feature(
        self,
        project_root: str,
        target_path: str,
        feature_text: str,
        *,
        overwrite_existing: bool = False,
    ) -> dict[str, object]:
        _ = feature_text
        return {
            "projectRoot": project_root,
            "targetPath": target_path,
            "status": "overwritten" if overwrite_existing else "created",
            "message": None,
        }


class _SupervisorStub:
    def __init__(self, store: RunStateStore) -> None:
        self.store = store

    async def execute_run(self, run_id: str) -> None:
        run_record = self.store.get_job(run_id) or {}
        text = str(run_record.get("test_case_text", ""))
        match = re.search(r"([A-Z][A-Z0-9]+-[A-Z]*\d+)", text.upper())
        jira_key = match.group(1) if match else None
        self.store.patch_job(
            run_id,
            status="succeeded",
            finished_at=_utcnow(),
            result={
                "featureText": f"Feature: {jira_key or 'generated'}\n  Scenario: Demo\n    Given step",
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
        self.store.append_event(run_id, "run.finished", {"runId": run_id, "status": "succeeded"})


def _build_app() -> FastAPI:
    app = FastAPI()
    base = Path(tempfile.mkdtemp(prefix="runs-sessions-policy-"))
    memory_store = ChatMemoryStore(base)
    run_state_store = RunStateStore()
    artifact_store = ArtifactStore(base / "artifacts", index_store=InMemoryArtifactIndexStore())
    app.state.run_state_store = run_state_store
    app.state.artifact_store = artifact_store
    app.state.execution_supervisor = _SupervisorStub(run_state_store)
    chat_runtime = ChatAgentRuntime(
        memory_store=memory_store,
        orchestrator=_OrchestratorStub(),
        run_state_store=run_state_store,
        execution_supervisor=app.state.execution_supervisor,
    )
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
    app.state.chat_runtime = chat_runtime
    app.state.policy_service = policy_service
    app.include_router(runs_router)
    app.include_router(sessions_router)
    app.include_router(policy_router)
    return app


def test_sessions_message_preserves_free_text_autotest_flow() -> None:
    app = _build_app()
    client = TestClient(app)

    session = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]

    response = client.post(f"/sessions/{session_id}/messages", json={"content": "создай автотест SCBC-T123"})
    assert response.status_code == 200

    def _approval_ready() -> bool:
        approvals = client.get("/policy/approvals").json()
        return approvals["total"] == 1

    _wait_until(_approval_ready)
    approvals = client.get("/policy/approvals").json()
    approval = approvals["items"][0]
    assert approval["toolName"] == "save_generated_feature"
    assert approval["metadata"]["target_path"] == "src/test/resources/features/SCBC-T123.feature"

    decision = client.post(f"/policy/approvals/{approval['approvalId']}/decision", json={"decision": "approve"})
    assert decision.status_code == 200

    _wait_until(lambda: client.get("/policy/approvals").json()["total"] == 0)
    history = client.get(f"/sessions/{session_id}/history").json()
    assert any("feature" in item["content"].lower() for item in history["messages"] if item["role"] == "assistant")


def test_create_run_for_testgen_and_fetch_result() -> None:
    app = _build_app()
    client = TestClient(app)

    response = client.post(
        "/runs",
        json={
            "projectRoot": "/tmp/project",
            "plugin": "testgen",
            "input": {"testCaseText": "создай автотест SCBC-T999"},
            "source": "test-suite",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["plugin"] == "testgen"
    run_id = payload["runId"]

    _wait_until(lambda: client.get(f"/runs/{run_id}").json()["status"] == "succeeded")
    result = client.get(f"/runs/{run_id}/result")
    assert result.status_code == 200
    result_payload = result.json()
    assert result_payload["runId"] == run_id
    assert result_payload["plugin"] == "testgen"
    assert result_payload["output"]["featureText"].startswith("Feature: SCBC-T999")


def test_policy_tools_endpoint_lists_runtime_tools() -> None:
    app = _build_app()
    client = TestClient(app)

    response = client.get("/policy/tools")
    assert response.status_code == 200
    payload = response.json()
    tool_names = {item["name"] for item in payload["items"]}
    assert "compose_feature_patch" in tool_names
    assert "save_generated_feature" in tool_names


def test_policy_audit_endpoint_uses_persistent_policy_store() -> None:
    app = _build_app()
    client = TestClient(app)

    session = client.post("/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]

    response = client.post(f"/sessions/{session_id}/messages", json={"content": "generate autotest SCBC-T555"})
    assert response.status_code == 200

    _wait_until(lambda: client.get("/policy/approvals").json()["total"] == 1)
    approval = client.get("/policy/approvals").json()["items"][0]
    decision = client.post(f"/policy/approvals/{approval['approvalId']}/decision", json={"decision": "approve"})
    assert decision.status_code == 200

    audit_response = client.get("/policy/audit", params={"limit": 20})
    assert audit_response.status_code == 200
    event_types = [item["eventType"] for item in audit_response.json()["items"]]
    assert "permission.requested" in event_types
    assert "permission.approved" in event_types
    assert "autotest.saved" in event_types


def test_run_artifacts_endpoint_resolves_metadata_and_content() -> None:
    app = _build_app()
    client = TestClient(app)

    artifact = app.state.artifact_store.publish_text(
        name="stdout.log",
        content="artifact-body",
        media_type="text/plain",
        connector_source="execution.artifacts",
        run_id="run-artifacts",
        attempt_id="attempt-1",
    )
    app.state.run_state_store.put_job(
        {
            "run_id": "run-artifacts",
            "plugin": "testgen",
            "status": "succeeded",
            "started_at": _utcnow(),
            "finished_at": _utcnow(),
            "updated_at": _utcnow(),
            "attempts": [
                {
                    "attempt_id": "attempt-1",
                    "status": "succeeded",
                    "started_at": _utcnow(),
                    "finished_at": _utcnow(),
                    "artifacts": {"stdout": artifact["uri"]},
                }
            ],
            "result": {"featureText": "Feature: demo", "unmappedSteps": [], "usedSteps": [], "buildStage": "ok"},
        }
    )

    response = client.get("/runs/run-artifacts/artifacts")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["artifactId"] == artifact["artifactId"]
    assert payload["items"][0]["storageBackend"] == "local"
    assert payload["items"][0]["content"] == "artifact-body"
    assert payload["items"][0]["signedUrl"] is None


def test_run_artifact_content_endpoint_returns_downloadable_payload() -> None:
    app = _build_app()
    client = TestClient(app)

    artifact = app.state.artifact_store.publish_text(
        name="stdout.log",
        content="artifact-body",
        media_type="text/plain",
        connector_source="execution.artifacts",
        run_id="run-artifacts-content",
        attempt_id="attempt-1",
    )
    app.state.run_state_store.put_job(
        {
            "run_id": "run-artifacts-content",
            "plugin": "testgen",
            "status": "succeeded",
            "started_at": _utcnow(),
            "finished_at": _utcnow(),
            "updated_at": _utcnow(),
            "attempts": [
                {
                    "attempt_id": "attempt-1",
                    "status": "succeeded",
                    "started_at": _utcnow(),
                    "finished_at": _utcnow(),
                    "artifacts": {"stdout": artifact["uri"]},
                }
            ],
            "result": {"featureText": "Feature: demo", "unmappedSteps": [], "usedSteps": [], "buildStage": "ok"},
        }
    )

    response = client.get(f"/runs/run-artifacts-content/artifacts/{artifact['artifactId']}/content")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "inline" in response.headers["content-disposition"]
    assert response.text == "artifact-body"

    download = client.get(f"/runs/run-artifacts-content/artifacts/{artifact['artifactId']}/content?download=true")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
