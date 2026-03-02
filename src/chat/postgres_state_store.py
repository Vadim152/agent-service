"""Postgres-backed chat state store for sessions, events, and approvals."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4

from chat.memory_store import ChatMemoryStore


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresChatStateStore:
    """Thread-safe Postgres implementation compatible with ChatStateStore."""

    def __init__(
        self,
        memory_store: ChatMemoryStore,
        *,
        dsn: str,
        max_sessions_per_project: int = 100,
        max_messages_per_session: int = 400,
        max_events_per_session: int = 2_000,
    ) -> None:
        self._memory_store = memory_store
        self._dsn = dsn
        self._lock = RLock()
        self._max_sessions_per_project = max(10, max_sessions_per_project)
        self._max_messages_per_session = max(20, max_messages_per_session)
        self._max_events_per_session = max(50, max_events_per_session)
        self._ensure_schema()

    @staticmethod
    def _load_psycopg():
        try:
            import psycopg  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "Postgres chat backend requires 'psycopg' package. Install dependency and retry."
            ) from exc
        return psycopg

    def _connect(self):
        psycopg = self._load_psycopg()
        return psycopg.connect(self._dsn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cp_sessions (
                        session_id TEXT PRIMARY KEY,
                        project_root TEXT NOT NULL,
                        source TEXT NOT NULL,
                        profile TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cp_session_messages (
                        session_id TEXT NOT NULL,
                        message_id TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        payload JSONB NOT NULL,
                        PRIMARY KEY (session_id, message_id)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cp_session_events (
                        session_id TEXT NOT NULL,
                        idx INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        payload JSONB NOT NULL,
                        PRIMARY KEY (session_id, idx)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cp_session_event_cursor (
                        session_id TEXT PRIMARY KEY,
                        next_idx INTEGER NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cp_approval_requests (
                        approval_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        payload JSONB NOT NULL
                    )
                    """
                )
            conn.commit()

    @staticmethod
    def _dumps(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _loads(payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            loaded = json.loads(payload)
            return loaded if isinstance(loaded, dict) else {}
        return {}

    @staticmethod
    def _isoformat(value: Any) -> str:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _touch_session(self, conn: Any, session_id: str) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cp_sessions
                SET updated_at = NOW()
                WHERE session_id = %s
                """,
                (session_id,),
            )

    def _fetch_session_row(self, conn: Any, session_id: str) -> tuple[Any, ...] | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT session_id, project_root, source, profile, status, payload, created_at, updated_at
                FROM cp_sessions
                WHERE session_id = %s
                """,
                (session_id,),
            )
            return cur.fetchone()

    def _row_to_session(self, row: tuple[Any, ...]) -> dict[str, Any]:
        payload = self._loads(row[5])
        payload["session_id"] = str(row[0])
        payload["project_root"] = str(row[1])
        payload["source"] = str(row[2])
        payload["profile"] = str(row[3])
        payload["status"] = str(row[4])
        payload["created_at"] = self._isoformat(row[6])
        payload["updated_at"] = self._isoformat(row[7])
        return payload

    def _load_messages(self, conn: Any, session_id: str, *, trim: bool = True) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT payload
                FROM cp_session_messages
                WHERE session_id = %s
                ORDER BY created_at ASC
                """,
                (session_id,),
            )
            rows = cur.fetchall()
        messages = [self._loads(row[0]) for row in rows]
        if trim and len(messages) > self._max_messages_per_session:
            messages = messages[-self._max_messages_per_session :]
        return messages

    def _load_events(self, conn: Any, session_id: str, *, trim: bool = True) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT idx, event_type, payload, created_at
                FROM cp_session_events
                WHERE session_id = %s
                ORDER BY idx ASC
                """,
                (session_id,),
            )
            rows = cur.fetchall()
        events = [
            {
                "event_type": str(row[1]),
                "payload": self._loads(row[2]).get("payload", {}),
                "created_at": self._isoformat(row[3]),
                "index": int(row[0]),
            }
            for row in rows
        ]
        if trim and len(events) > self._max_events_per_session:
            events = events[-self._max_events_per_session :]
        return events

    def _load_pending_tool_calls(
        self,
        conn: Any,
        *,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            if session_id is None:
                cur.execute(
                    """
                    SELECT session_id, payload
                    FROM cp_approval_requests
                    ORDER BY created_at ASC
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT session_id, payload
                    FROM cp_approval_requests
                    WHERE session_id = %s
                    ORDER BY created_at ASC
                    """,
                    (session_id,),
                )
            rows = cur.fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            payload = self._loads(row[1])
            payload["session_id"] = str(row[0])
            items.append(payload)
        return items

    def _hydrate_session(self, conn: Any, session_id: str) -> dict[str, Any] | None:
        row = self._fetch_session_row(conn, session_id)
        if not row:
            return None
        payload = self._row_to_session(row)
        payload["messages"] = self._load_messages(conn, session_id)
        payload["events"] = self._load_events(conn, session_id)
        payload["pending_tool_calls"] = self._load_pending_tool_calls(conn, session_id=session_id)
        payload["next_event_index"] = max((int(event.get("index", 0)) for event in payload["events"]), default=-1) + 1
        return payload

    def _replace_messages(self, conn: Any, session_id: str, messages: list[dict[str, Any]]) -> None:
        trimmed = deepcopy(messages[-self._max_messages_per_session :])
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cp_session_messages WHERE session_id = %s", (session_id,))
            for message in trimmed:
                cur.execute(
                    """
                    INSERT INTO cp_session_messages (session_id, message_id, created_at, payload)
                    VALUES (%s, %s, %s, %s::jsonb)
                    """,
                    (
                        session_id,
                        str(message.get("message_id", uuid4())),
                        str(message.get("created_at", _utcnow())),
                        self._dumps(message),
                    ),
                )

    def _replace_events(self, conn: Any, session_id: str, events: list[dict[str, Any]]) -> None:
        trimmed = deepcopy(events[-self._max_events_per_session :])
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cp_session_events WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM cp_session_event_cursor WHERE session_id = %s", (session_id,))
            next_idx = 0
            for event in trimmed:
                idx = int(event.get("index", next_idx))
                next_idx = max(next_idx, idx + 1)
                cur.execute(
                    """
                    INSERT INTO cp_session_events (session_id, idx, event_type, created_at, payload)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        session_id,
                        idx,
                        str(event.get("event_type", "")),
                        str(event.get("created_at", _utcnow())),
                        self._dumps(
                            {
                                "payload": event.get("payload", {}),
                                "created_at": event.get("created_at", _utcnow()),
                            }
                        ),
                    ),
                )
            cur.execute(
                """
                INSERT INTO cp_session_event_cursor (session_id, next_idx)
                VALUES (%s, %s)
                """,
                (session_id, next_idx),
            )

    def _replace_pending_tool_calls(self, conn: Any, session_id: str, items: list[dict[str, Any]]) -> None:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cp_approval_requests WHERE session_id = %s", (session_id,))
            for item in deepcopy(items):
                cur.execute(
                    """
                    INSERT INTO cp_approval_requests (approval_id, session_id, tool_name, created_at, payload)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        str(item.get("tool_call_id", uuid4())),
                        session_id,
                        str(item.get("tool_name", "")),
                        str(item.get("created_at", _utcnow())),
                        self._dumps(item),
                    ),
                )

    def _append_event_locked(
        self,
        conn: Any,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT next_idx
                FROM cp_session_event_cursor
                WHERE session_id = %s
                FOR UPDATE
                """,
                (session_id,),
            )
            row = cur.fetchone()
            idx = int(row[0]) if row else 0
            created_at = _utcnow()
            cur.execute(
                """
                INSERT INTO cp_session_events (session_id, idx, event_type, created_at, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (
                    session_id,
                    idx,
                    event_type,
                    created_at,
                    self._dumps({"payload": payload, "created_at": created_at}),
                ),
            )
            if row:
                cur.execute(
                    """
                    UPDATE cp_session_event_cursor
                    SET next_idx = %s
                    WHERE session_id = %s
                    """,
                    (idx + 1, session_id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO cp_session_event_cursor (session_id, next_idx)
                    VALUES (%s, %s)
                    """,
                    (session_id, idx + 1),
                )
        self._touch_session(conn, session_id)
        self._trim_events_locked(conn, session_id)
        return {"event_type": event_type, "payload": deepcopy(payload), "created_at": created_at, "index": idx}

    def _delete_session_locked(self, conn: Any, session_id: str) -> None:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cp_session_messages WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM cp_session_events WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM cp_session_event_cursor WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM cp_approval_requests WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM cp_sessions WHERE session_id = %s", (session_id,))

    def _enforce_project_session_limit_locked(self, conn: Any, project_root: str) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT session_id
                FROM cp_sessions
                WHERE project_root = %s
                ORDER BY updated_at DESC
                """,
                (project_root,),
            )
            rows = cur.fetchall()
        stale_rows = rows[self._max_sessions_per_project :]
        for row in stale_rows:
            self._delete_session_locked(conn, str(row[0]))

    def create_session(
        self,
        *,
        project_root: str,
        source: str,
        profile: str,
        reuse_existing: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        with self._lock, self._connect() as conn:
            if reuse_existing:
                existing = self._find_latest_session_locked(conn, project_root)
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
                "next_event_index": 0,
                "memory_snapshot": memory_snapshot,
            }
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cp_sessions (session_id, project_root, source, profile, status, payload)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (session_id, project_root, source, profile, "active", self._dumps(payload)),
                )
                cur.execute(
                    """
                    INSERT INTO cp_session_event_cursor (session_id, next_idx)
                    VALUES (%s, %s)
                    """,
                    (session_id, 0),
                )
            self._append_event_locked(conn, session_id, "session.created", {"sessionId": session_id})
            self._enforce_project_session_limit_locked(conn, project_root)
            conn.commit()
            created = self._hydrate_session(conn, session_id)
            return deepcopy(created or payload), False

    def _find_latest_session_locked(self, conn: Any, project_root: str) -> dict[str, Any] | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT session_id
                FROM cp_sessions
                WHERE project_root = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (project_root,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return self._hydrate_session(conn, str(row[0]))

    def find_latest_session(self, project_root: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            payload = self._find_latest_session_locked(conn, project_root)
            return deepcopy(payload) if payload else None

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            payload = self._hydrate_session(conn, session_id)
            return deepcopy(payload) if payload else None

    def list_sessions(self, project_root: str, *, limit: int = 50) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 200))
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_id
                    FROM cp_sessions
                    WHERE project_root = %s
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (project_root, bounded),
                )
                rows = cur.fetchall()
            return [deepcopy(self._hydrate_session(conn, str(row[0]))) for row in rows if row]

    def list_all_sessions(self, *, limit: int = 200) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 500))
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_id
                    FROM cp_sessions
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (bounded,),
                )
                rows = cur.fetchall()
            return [deepcopy(self._hydrate_session(conn, str(row[0]))) for row in rows if row]

    def update_session(self, session_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = self._fetch_session_row(conn, session_id)
            if not row:
                return None
            payload = self._row_to_session(row)
            messages = changes.pop("messages", None)
            events = changes.pop("events", None)
            pending_tool_calls = changes.pop("pending_tool_calls", None)
            payload.update(changes)
            project_root = str(payload.get("project_root", row[1]))
            source = str(payload.get("source", row[2]))
            profile = str(payload.get("profile", row[3]))
            status = str(payload.get("status", row[4]))
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE cp_sessions
                    SET project_root = %s,
                        source = %s,
                        profile = %s,
                        status = %s,
                        payload = %s::jsonb,
                        updated_at = NOW()
                    WHERE session_id = %s
                    """,
                    (project_root, source, profile, status, self._dumps(payload), session_id),
                )
            if messages is not None:
                self._replace_messages(conn, session_id, list(messages))
            if events is not None:
                self._replace_events(conn, session_id, list(events))
            if pending_tool_calls is not None:
                self._replace_pending_tool_calls(conn, session_id, list(pending_tool_calls))
            conn.commit()
            updated = self._hydrate_session(conn, session_id)
            return deepcopy(updated) if updated else None

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
        payload = {
            "message_id": message_id or str(uuid4()),
            "role": role,
            "content": content,
            "run_id": run_id,
            "metadata": metadata or {},
            "created_at": _utcnow(),
        }
        with self._lock, self._connect() as conn:
            if not self._fetch_session_row(conn, session_id):
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cp_session_messages (session_id, message_id, created_at, payload)
                    VALUES (%s, %s, %s, %s::jsonb)
                    """,
                    (session_id, payload["message_id"], payload["created_at"], self._dumps(payload)),
                )
            self._touch_session(conn, session_id)
            self._trim_messages_locked(conn, session_id)
            conn.commit()
            return deepcopy(payload)

    def _trim_messages_locked(self, conn: Any, session_id: str) -> None:
        messages = self._load_messages(conn, session_id, trim=False)
        if len(messages) <= self._max_messages_per_session:
            return
        self._replace_messages(conn, session_id, messages[-self._max_messages_per_session :])

    def append_event(self, session_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            if not self._fetch_session_row(conn, session_id):
                return None
            event = self._append_event_locked(conn, session_id, event_type, payload)
            conn.commit()
            return event

    def _trim_events_locked(self, conn: Any, session_id: str) -> None:
        events = self._load_events(conn, session_id, trim=False)
        if len(events) <= self._max_events_per_session:
            return
        self._replace_events(conn, session_id, events[-self._max_events_per_session :])

    def list_events(self, session_id: str, since_index: int = 0) -> tuple[list[dict[str, Any]], int]:
        floor_index = max(0, since_index)
        with self._lock, self._connect() as conn:
            if not self._fetch_session_row(conn, session_id):
                return [], since_index
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT idx, event_type, payload, created_at
                    FROM cp_session_events
                    WHERE session_id = %s AND idx >= %s
                    ORDER BY idx ASC
                    """,
                    (session_id, floor_index),
                )
                rows = cur.fetchall()
                cur.execute(
                    """
                    SELECT next_idx
                    FROM cp_session_event_cursor
                    WHERE session_id = %s
                    """,
                    (session_id,),
                )
                cursor_row = cur.fetchone()
            events = [
                {
                    "event_type": str(row[1]),
                    "payload": self._loads(row[2]).get("payload", {}),
                    "created_at": self._isoformat(row[3]),
                    "index": int(row[0]),
                }
                for row in rows
            ]
            next_index = int(cursor_row[0]) if cursor_row else 0
            return deepcopy(events), next_index

    def set_pending_tool_call(
        self,
        session_id: str,
        *,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any],
        risk_level: str,
        requires_confirmation: bool,
        title: str | None = None,
        kind: str = "tool",
        message_id: str | None = None,
    ) -> dict[str, Any] | None:
        payload = {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "args": args,
            "risk_level": risk_level,
            "requires_confirmation": requires_confirmation,
            "title": title or tool_name,
            "kind": kind,
            "message_id": message_id,
            "created_at": _utcnow(),
        }
        with self._lock, self._connect() as conn:
            if not self._fetch_session_row(conn, session_id):
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cp_approval_requests (approval_id, session_id, tool_name, created_at, payload)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (tool_call_id, session_id, tool_name, payload["created_at"], self._dumps(payload)),
                )
            self._touch_session(conn, session_id)
            conn.commit()
            return deepcopy(payload)

    def pop_pending_tool_call(self, session_id: str, tool_call_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            if not self._fetch_session_row(conn, session_id):
                return None
            pending = self.get_pending_tool_call(session_id, tool_call_id)
            if not pending:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM cp_approval_requests
                    WHERE approval_id = %s AND session_id = %s
                    """,
                    (tool_call_id, session_id),
                )
            self._touch_session(conn, session_id)
            conn.commit()
            return deepcopy(pending)

    def get_pending_tool_call(self, session_id: str, tool_call_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload
                    FROM cp_approval_requests
                    WHERE approval_id = %s AND session_id = %s
                    """,
                    (tool_call_id, session_id),
                )
                row = cur.fetchone()
            if not row:
                return None
            return deepcopy(self._loads(row[0]))

    def list_pending_tool_calls(self, *, session_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            return deepcopy(self._load_pending_tool_calls(conn, session_id=session_id))

    def find_pending_tool_call(self, tool_call_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_id, payload
                    FROM cp_approval_requests
                    WHERE approval_id = %s
                    """,
                    (tool_call_id,),
                )
                row = cur.fetchone()
            if not row:
                return None
            payload = self._loads(row[1])
            payload["session_id"] = str(row[0])
            return deepcopy(payload)

    def history(self, session_id: str, *, limit: int = 200) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            session = self._hydrate_session(conn, session_id)
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
