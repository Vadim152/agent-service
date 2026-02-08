"""State store for chat sessions, events and pending tool calls."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4

from chat.memory_store import ChatMemoryStore


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatStateStore:
    """Thread-safe in-memory chat state with filesystem snapshots."""

    def __init__(self, memory_store: ChatMemoryStore) -> None:
        self._memory_store = memory_store
        self._lock = RLock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._load_sessions()

    def _load_sessions(self) -> None:
        for session in self._memory_store.load_sessions():
            session_id = str(session.get("session_id", "")).strip()
            if not session_id:
                continue
            session.setdefault("messages", [])
            session.setdefault("events", [])
            session.setdefault("pending_tool_calls", [])
            self._sessions[session_id] = session

    def _persist(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            return
        self._memory_store.save_session(session)

    def create_session(
        self,
        *,
        project_root: str,
        source: str,
        profile: str,
        reuse_existing: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        with self._lock:
            if reuse_existing:
                existing = self.find_latest_session(project_root)
                if existing:
                    return existing, True

            session_id = str(uuid4())
            memory_snapshot = self._memory_store.load_project_memory(project_root)
            payload: dict[str, Any] = {
                "session_id": session_id,
                "project_root": project_root,
                "source": source,
                "profile": profile,
                "status": "active",
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
                "messages": [],
                "events": [],
                "pending_tool_calls": [],
                "memory_snapshot": memory_snapshot,
            }
            self._sessions[session_id] = payload
            self.append_event(session_id, "session.created", {"sessionId": session_id})
            self._persist(session_id)
            return deepcopy(payload), False

    def find_latest_session(self, project_root: str) -> dict[str, Any] | None:
        candidates = [
            value
            for value in self._sessions.values()
            if value.get("project_root") == project_root
        ]
        if not candidates:
            return None
        latest = sorted(candidates, key=lambda item: str(item.get("updated_at", "")), reverse=True)[0]
        return deepcopy(latest)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return deepcopy(session)

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        run_id: str | None = None,
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            payload = {
                "message_id": message_id or str(uuid4()),
                "role": role,
                "content": content,
                "run_id": run_id,
                "metadata": metadata or {},
                "created_at": _utcnow(),
            }
            session["messages"].append(payload)
            session["updated_at"] = _utcnow()
            self._persist(session_id)
            return deepcopy(payload)

    def append_event(self, session_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            index = len(session["events"])
            event = {
                "event_type": event_type,
                "payload": payload,
                "created_at": _utcnow(),
                "index": index,
            }
            session["events"].append(event)
            session["updated_at"] = _utcnow()
            self._persist(session_id)
            return deepcopy(event)

    def list_events(self, session_id: str, since_index: int = 0) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return [], since_index
            events = session.get("events", [])
            selected = events[since_index:]
            return deepcopy(selected), len(events)

    def set_pending_tool_call(
        self,
        session_id: str,
        *,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any],
        risk_level: str,
        requires_confirmation: bool,
    ) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            payload = {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "args": args,
                "risk_level": risk_level,
                "requires_confirmation": requires_confirmation,
                "created_at": _utcnow(),
            }
            pending = session.setdefault("pending_tool_calls", [])
            pending.append(payload)
            session["updated_at"] = _utcnow()
            self._persist(session_id)
            return deepcopy(payload)

    def pop_pending_tool_call(self, session_id: str, tool_call_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            pending = session.setdefault("pending_tool_calls", [])
            for idx, item in enumerate(pending):
                if item.get("tool_call_id") == tool_call_id:
                    value = pending.pop(idx)
                    session["updated_at"] = _utcnow()
                    self._persist(session_id)
                    return deepcopy(value)
            return None

    def get_pending_tool_call(self, session_id: str, tool_call_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            pending = session.setdefault("pending_tool_calls", [])
            for item in pending:
                if item.get("tool_call_id") == tool_call_id:
                    return deepcopy(item)
            return None

    def history(self, session_id: str, *, limit: int = 200) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            payload = deepcopy(session)
            payload["messages"] = payload.get("messages", [])[-limit:]
            payload["events"] = payload.get("events", [])[-limit:]
            project_root = str(payload.get("project_root", ""))
            payload["memory_snapshot"] = self._memory_store.load_project_memory(project_root)
            return payload

    def patch_project_memory(self, project_root: str, **changes: Any) -> dict[str, Any]:
        return self._memory_store.patch_project_memory(project_root, **changes)

