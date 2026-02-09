from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes_chat import router as chat_router
from chat.runtime import ChatAgentRuntime
from infrastructure.opencode_sidecar_client import OpencodeSidecarError


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wait_until(assertion, timeout_s: float = 4.0) -> None:
    started = time.time()
    while time.time() - started < timeout_s:
        if assertion():
            return
        time.sleep(0.05)
    raise AssertionError("Condition was not met before timeout")


class _FakeSidecarClient:
    def __init__(self) -> None:
        self.sessions_by_id: dict[str, dict[str, Any]] = {}
        self.sessions_by_root: dict[str, str] = {}
        self.permission_decisions: list[dict[str, str]] = []
        self._session_seq = 0

    async def create_session(
        self,
        *,
        project_root: str,
        source: str,
        profile: str,
        reuse_existing: bool,
    ) -> dict[str, Any]:
        existing = self.sessions_by_root.get(project_root)
        if reuse_existing and existing:
            session = self.sessions_by_id[existing]
            return {
                "sessionId": session["sessionId"],
                "createdAt": session["createdAt"],
                "reused": True,
                "projectRoot": session["projectRoot"],
                "source": session["source"],
                "profile": session["profile"],
            }

        self._session_seq += 1
        session_id = f"session-{self._session_seq}"
        session = {
            "sessionId": session_id,
            "createdAt": _utcnow(),
            "projectRoot": project_root,
            "source": source,
            "profile": profile,
            "messages": [],
            "events": [],
            "pendingPermissions": [],
            "updatedAt": _utcnow(),
        }
        self.sessions_by_id[session_id] = session
        self.sessions_by_root[project_root] = session_id
        return {
            "sessionId": session_id,
            "createdAt": session["createdAt"],
            "reused": False,
            "projectRoot": project_root,
            "source": source,
            "profile": profile,
        }

    async def prompt_async(
        self,
        *,
        session_id: str,
        message_id: str,
        content: str,
    ) -> dict[str, Any]:
        session = self.sessions_by_id[session_id]
        session["messages"].append(
            {
                "messageId": message_id,
                "role": "user",
                "content": content,
                "runId": None,
                "metadata": {},
                "createdAt": _utcnow(),
            }
        )
        session["messages"].append(
            {
                "messageId": f"assistant-{message_id}",
                "role": "assistant",
                "content": f"echo: {content}",
                "runId": None,
                "metadata": {},
                "createdAt": _utcnow(),
            }
        )
        session["pendingPermissions"] = [
            {
                "permissionId": "perm-1",
                "title": "Approve write action",
                "kind": "bash",
                "callId": "call-1",
                "messageId": f"assistant-{message_id}",
                "metadata": {"risk": "high"},
                "createdAt": _utcnow(),
            }
        ]
        session["updatedAt"] = _utcnow()
        return {"sessionId": session_id, "accepted": True}

    async def reply_permission(
        self,
        *,
        session_id: str,
        permission_id: str,
        response: str,
    ) -> dict[str, Any]:
        session = self.sessions_by_id[session_id]
        session["pendingPermissions"] = [
            item
            for item in session["pendingPermissions"]
            if item.get("permissionId") != permission_id
        ]
        session["updatedAt"] = _utcnow()
        self.permission_decisions.append(
            {
                "sessionId": session_id,
                "permissionId": permission_id,
                "response": response,
            }
        )
        return {"accepted": True}

    async def get_history(self, *, session_id: str, limit: int = 200) -> dict[str, Any]:
        session = self.sessions_by_id.get(session_id)
        if not session:
            raise OpencodeSidecarError("Session not found", status_code=404)
        return {
            "sessionId": session_id,
            "projectRoot": session["projectRoot"],
            "source": session["source"],
            "profile": session["profile"],
            "status": "active",
            "messages": session["messages"][-limit:],
            "events": session["events"][-limit:],
            "pendingPermissions": session["pendingPermissions"],
            "updatedAt": session["updatedAt"],
        }

    async def stream_events(self, *, session_id: str, from_index: int = 0):
        _ = from_index
        if session_id not in self.sessions_by_id:
            raise OpencodeSidecarError("Session not found", status_code=404)
        payload = (
            'event: message.final\n'
            'data: {"eventType":"message.final","payload":{"sessionId":"%s"},"createdAt":"%s","index":0}\n\n'
            % (session_id, _utcnow())
        )
        yield payload.encode("utf-8")
        await asyncio.sleep(0)


def _build_app() -> tuple[FastAPI, _FakeSidecarClient]:
    app = FastAPI()
    sidecar = _FakeSidecarClient()
    app.state.chat_runtime = ChatAgentRuntime(sidecar_client=sidecar)
    app.include_router(chat_router)
    return app, sidecar


def test_chat_session_create_and_reuse() -> None:
    app, _ = _build_app()
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


def test_send_message_and_read_history() -> None:
    app, _ = _build_app()
    client = TestClient(app)

    session = client.post("/chat/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]

    send = client.post(f"/chat/sessions/{session_id}/messages", json={"content": "hello"})
    assert send.status_code == 200

    def _assistant_replied() -> bool:
        history = client.get(f"/chat/sessions/{session_id}/history").json()
        assistant = [msg for msg in history["messages"] if msg["role"] == "assistant"]
        return any("echo: hello" in msg["content"] for msg in assistant)

    _wait_until(_assistant_replied)

    history = client.get(f"/chat/sessions/{session_id}/history").json()
    assert len(history["pendingPermissions"]) == 1
    assert history["pendingPermissions"][0]["permissionId"] == "perm-1"


def test_permission_decision_maps_to_sidecar_response() -> None:
    app, sidecar = _build_app()
    client = TestClient(app)

    session = client.post("/chat/sessions", json={"projectRoot": "/tmp/project"}).json()
    session_id = session["sessionId"]
    client.post(f"/chat/sessions/{session_id}/messages", json={"content": "do write"})

    _wait_until(
        lambda: len(client.get(f"/chat/sessions/{session_id}/history").json()["pendingPermissions"]) == 1
    )

    decision = client.post(
        f"/chat/sessions/{session_id}/tool-decisions",
        json={"permissionId": "perm-1", "decision": "approve_once"},
    )
    assert decision.status_code == 200

    _wait_until(lambda: len(sidecar.permission_decisions) == 1)
    assert sidecar.permission_decisions[0]["response"] == "once"
