from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app.tool_host as tool_host_app
from infrastructure.artifact_index_store import InMemoryArtifactIndexStore
from infrastructure.artifact_store import ArtifactStore


class _StubOrchestrator:
    def apply_feature(
        self,
        project_root: str,
        target_path: str,
        feature_text: str,
        *,
        overwrite_existing: bool = False,
    ) -> dict[str, object]:
        target = Path(project_root) / target_path
        target.parent.mkdir(parents=True, exist_ok=True)
        status = "overwritten" if target.exists() and overwrite_existing else "created"
        if target.exists() and not overwrite_existing:
            status = "skipped"
        else:
            target.write_text(feature_text, encoding="utf-8")
        return {
            "projectRoot": project_root,
            "targetPath": target_path,
            "status": status,
            "message": None,
        }


class _PolicyStoreStub:
    def __init__(self) -> None:
        self.pending = {
            "approval-1": {
                "approval_id": "approval-1",
                "session_id": "session-1",
                "tool_name": "save_generated_feature",
            }
        }
        self.audit_events: list[dict[str, object]] = []

    def get_pending_approval(self, approval_id: str) -> dict[str, object] | None:
        return self.pending.get(approval_id)

    def append_audit_event(self, *, session_id: str, event_type: str, payload: dict[str, object], created_at=None):
        self.audit_events.append(
            {
                "sessionId": session_id,
                "eventType": event_type,
                "payload": dict(payload),
            }
        )
        return self.audit_events[-1]


def test_tool_host_registry_and_repo_read(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(tool_host_app, "create_orchestrator", lambda settings: _StubOrchestrator())
    monkeypatch.setattr(tool_host_app, "create_policy_store", lambda settings: _PolicyStoreStub())
    monkeypatch.setattr(
        tool_host_app,
        "create_artifact_store",
        lambda settings: ArtifactStore(tmp_path / "artifacts", index_store=InMemoryArtifactIndexStore()),
    )
    demo_file = tmp_path / "features" / "demo.feature"
    demo_file.parent.mkdir(parents=True, exist_ok=True)
    demo_file.write_text("Feature: demo", encoding="utf-8")

    with TestClient(tool_host_app.app) as client:
        registry = client.get("/internal/tools/registry")
        assert registry.status_code == 200
        tool_names = {item["name"] for item in registry.json()["items"]}
        assert {
            "repo.read",
            "artifacts.put",
            "artifacts.get",
            "patch.propose",
            "patch.apply",
            "save_generated_feature",
        } <= tool_names

        repo_read = client.post(
            "/internal/tools/repo/read",
            json={"projectRoot": str(tmp_path), "path": "features/demo.feature", "includeContent": True},
        )
        assert repo_read.status_code == 200
        payload = repo_read.json()
        assert payload["exists"] is True
        assert payload["isFile"] is True
        assert payload["content"] == "Feature: demo"


def test_tool_host_patch_propose_and_apply(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(tool_host_app, "create_orchestrator", lambda settings: _StubOrchestrator())
    policy_store = _PolicyStoreStub()
    monkeypatch.setattr(tool_host_app, "create_policy_store", lambda settings: policy_store)
    monkeypatch.setattr(
        tool_host_app,
        "create_artifact_store",
        lambda settings: ArtifactStore(tmp_path / "artifacts", index_store=InMemoryArtifactIndexStore()),
    )
    target = tmp_path / "features" / "demo.feature"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("Feature: old", encoding="utf-8")

    with TestClient(tool_host_app.app) as client:
        propose = client.post(
            "/internal/tools/patch/propose",
            json={
                "projectRoot": str(tmp_path),
                "targetPath": "features/demo.feature",
                "featureText": "Feature: new\n  Scenario: demo",
            },
        )
        assert propose.status_code == 200
        proposed = propose.json()
        assert proposed["diff"]["files"][0]["before"] == "Feature: old"
        assert proposed["diff"]["files"][0]["after"].startswith("Feature: new")

        missing_approval = client.post(
            "/internal/tools/patch/apply",
            json={
                "projectRoot": str(tmp_path),
                "targetPath": "features/demo.feature",
                "featureText": "Feature: new\n  Scenario: demo",
                "overwriteExisting": True,
            },
        )
        assert missing_approval.status_code == 403

        apply_response = client.post(
            "/internal/tools/patch/apply",
            json={
                "projectRoot": str(tmp_path),
                "targetPath": "features/demo.feature",
                "featureText": "Feature: new\n  Scenario: demo",
                "overwriteExisting": True,
                "approvalId": "approval-1",
            },
        )
        assert apply_response.status_code == 200
        applied = apply_response.json()
        assert applied["status"] == "overwritten"
        assert applied["approvalId"] == "approval-1"
        event_types = [item["eventType"] for item in policy_store.audit_events]
        assert "patch.apply.started" in event_types
        assert "patch.applied" in event_types
        assert (tmp_path / "features" / "demo.feature").read_text(encoding="utf-8").startswith("Feature: new")

        legacy_alias = client.post(
            "/internal/tools/save-feature",
            json={
                "projectRoot": str(tmp_path),
                "targetPath": "features/alias.feature",
                "featureText": "Feature: alias",
                "overwriteExisting": False,
            },
        )
        assert legacy_alias.status_code == 200
        assert legacy_alias.json()["status"] == "created"


def test_tool_host_artifacts_put_and_get(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(tool_host_app, "create_orchestrator", lambda settings: _StubOrchestrator())
    monkeypatch.setattr(tool_host_app, "create_policy_store", lambda settings: _PolicyStoreStub())
    monkeypatch.setattr(
        tool_host_app,
        "create_artifact_store",
        lambda settings: ArtifactStore(tmp_path / "artifacts", index_store=InMemoryArtifactIndexStore()),
    )

    with TestClient(tool_host_app.app) as client:
        put_response = client.post(
            "/internal/tools/artifacts/put",
            json={
                "runId": "run-1",
                "attemptId": "attempt-1",
                "name": "stdout.log",
                "content": "ok",
                "mediaType": "text/plain",
            },
        )
        assert put_response.status_code == 200
        created = put_response.json()
        assert created["uri"].startswith("artifact://")
        assert created["runId"] == "run-1"

        get_response = client.post(
            "/internal/tools/artifacts/get",
            json={"artifactId": created["artifactId"]},
        )
        assert get_response.status_code == 200
        loaded = get_response.json()
        assert loaded["content"] == "ok"
        assert loaded["artifactId"] == created["artifactId"]
