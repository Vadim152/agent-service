from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Iterator

from opencode_adapter_app.process_supervisor import OpenCodeProcessSupervisor
from opencode_adapter_app.state_store import OpenCodeAdapterStateStore, utcnow


@dataclass
class _FakeSettings:
    runner_type: str = "opencode"
    inline_artifact_max_bytes: int = 64 * 1024
    default_agent: str = "agent"
    agent_map: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.agent_map is None:
            self.agent_map = {}

    def resolve_forced_model(self) -> str | None:
        return None


class _FakeHeadlessServer:
    def __init__(self, *, retry_succeeds: bool) -> None:
        self.retry_succeeds = retry_succeeds
        self.ensure_started_calls = 0
        self.restart_calls = 0
        self.refresh_calls = 0
        self.session_counter = 0
        self.message_calls = 0

    def ensure_started(self, *, project_root: str | None = None) -> str:
        _ = project_root
        self.ensure_started_calls += 1
        return "http://fake"

    def restart(self, *, project_root: str | None = None) -> str:
        _ = project_root
        self.restart_calls += 1
        return "http://fake"

    def refresh_gigachat_access_token(self) -> str:
        self.refresh_calls += 1
        return "token-refreshed"

    def stream_events(self, *, directory: str, stop_event: Event) -> Iterator[dict[str, Any]]:
        _ = directory
        _ = stop_event
        return iter(())

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
        timeout_s: float = 30.0,
    ) -> Any:
        _ = params
        _ = json_payload
        _ = timeout_s
        if method == "POST" and path == "/session":
            self.session_counter += 1
            return {"id": f"ses-{self.session_counter}"}
        if method == "POST" and path.startswith("/session/") and path.endswith("/message"):
            self.message_calls += 1
            if self.message_calls == 1:
                return _token_expired_response()
            if self.retry_succeeds:
                return {
                    "info": {"role": "assistant", "id": "msg-1"},
                    "parts": [{"type": "text", "text": "hello"}],
                }
            return _token_expired_response()
        raise AssertionError(f"Unexpected call: {method} {path}")


def _token_expired_response() -> dict[str, Any]:
    return {
        "info": {
            "role": "assistant",
            "error": {
                "name": "APIError",
                "data": {
                    "message": "Unauthorized: Token has expired",
                    "statusCode": 401,
                    "responseBody": '{"status":401,"message":"Token has expired"}',
                },
            },
        },
        "parts": [],
    }


def _build_run(tmp_path: Path, backend_run_id: str = "oc-1") -> dict[str, Any]:
    project_root = tmp_path / "project"
    work_dir = tmp_path / "work"
    project_root.mkdir()
    work_dir.mkdir()
    now = utcnow().isoformat()
    return {
        "backend_run_id": backend_run_id,
        "external_run_id": "run-1",
        "external_session_id": "ext-session-1",
        "backend_session_id": None,
        "project_root": str(project_root),
        "prompt": "hello",
        "source": "ide-plugin",
        "profile": "agent",
        "config_profile": "default",
        "status": "queued",
        "current_action": "Queued",
        "result": None,
        "output": None,
        "artifacts": [],
        "pending_approvals": [],
        "cancel_requested": False,
        "exit_code": None,
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "updated_at": now,
        "work_dir": str(work_dir),
    }


def test_server_backed_run_refreshes_token_and_retries_once(tmp_path: Path) -> None:
    state_store = OpenCodeAdapterStateStore()
    headless = _FakeHeadlessServer(retry_succeeds=True)
    supervisor = OpenCodeProcessSupervisor(
        settings=_FakeSettings(),
        state_store=state_store,
        headless_server=headless,
    )
    run = _build_run(tmp_path, backend_run_id="oc-1")
    state_store.create_run(run)

    supervisor._run_server_backed(run)

    payload = state_store.get_run("oc-1")
    assert payload is not None
    assert payload["status"] == "succeeded"
    assert payload["backend_session_id"] == "ses-2"
    assert headless.refresh_calls == 1
    assert headless.restart_calls == 1

    events, _ = state_store.list_events("oc-1", after=0)
    event_types = [item["event_type"] for item in events]
    assert "run.retrying" in event_types
    assert "run.finished" in event_types


def test_server_backed_run_fails_when_retry_still_token_expired(tmp_path: Path) -> None:
    state_store = OpenCodeAdapterStateStore()
    headless = _FakeHeadlessServer(retry_succeeds=False)
    supervisor = OpenCodeProcessSupervisor(
        settings=_FakeSettings(),
        state_store=state_store,
        headless_server=headless,
    )
    run = _build_run(tmp_path, backend_run_id="oc-2")
    state_store.create_run(run)

    supervisor._run_server_backed(run)

    payload = state_store.get_run("oc-2")
    assert payload is not None
    assert payload["status"] == "failed"
    assert "Token has expired" in str(payload.get("current_action", ""))
    assert headless.refresh_calls == 1
    assert headless.restart_calls == 1
