"""Persistent storage for policy tools, decisions, and audit events."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Protocol


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PolicyStore(Protocol):
    def upsert_tool(self, tool: dict[str, Any]) -> None: ...

    def list_tools(self) -> list[dict[str, Any]]: ...

    def list_pending_approvals(self) -> list[dict[str, Any]]: ...

    def get_pending_approval(self, approval_id: str) -> dict[str, Any] | None: ...

    def append_approval_decision(self, decision: dict[str, Any]) -> dict[str, Any]: ...

    def append_audit_event(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str | None = None,
    ) -> dict[str, Any]: ...

    def list_audit_events(self, *, limit: int = 100) -> list[dict[str, Any]]: ...


class InMemoryPolicyStore:
    """In-memory policy store for local mode and tests."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._tools: dict[str, dict[str, Any]] = {}
        self._approval_decisions: list[dict[str, Any]] = []
        self._audit_events: list[dict[str, Any]] = []
        self._next_audit_index = 0

    def upsert_tool(self, tool: dict[str, Any]) -> None:
        name = str(tool.get("name", "")).strip()
        if not name:
            return
        with self._lock:
            payload = deepcopy(tool)
            payload["updatedAt"] = _utcnow()
            self._tools[name] = payload

    def list_tools(self) -> list[dict[str, Any]]:
        with self._lock:
            items = [deepcopy(item) for item in self._tools.values()]
        items.sort(key=lambda item: str(item.get("name", "")))
        return items

    def list_pending_approvals(self) -> list[dict[str, Any]]:
        return []

    def get_pending_approval(self, approval_id: str) -> dict[str, Any] | None:
        _ = approval_id
        return None

    def append_approval_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        payload = deepcopy(decision)
        payload.setdefault("createdAt", _utcnow())
        with self._lock:
            self._approval_decisions.append(payload)
        return deepcopy(payload)

    def append_audit_event(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            event = {
                "sessionId": session_id,
                "eventType": event_type,
                "payload": deepcopy(payload),
                "createdAt": created_at or _utcnow(),
                "index": self._next_audit_index,
            }
            self._next_audit_index += 1
            self._audit_events.append(event)
        return deepcopy(event)

    def list_audit_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 500))
        with self._lock:
            items = [deepcopy(item) for item in self._audit_events]
        items.sort(key=lambda item: (str(item.get("createdAt", "")), int(item.get("index", 0))), reverse=True)
        return items[:bounded]


class PostgresPolicyStore:
    """Postgres-backed policy store for tools, decisions, and audit events."""

    def __init__(self, *, dsn: str) -> None:
        self._dsn = dsn
        self._lock = RLock()
        self._ensure_schema()

    @staticmethod
    def _load_psycopg():
        try:
            import psycopg  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "Postgres policy backend requires 'psycopg' package. Install dependency and retry."
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
                    CREATE TABLE IF NOT EXISTS cp_tools (
                        name TEXT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cp_approval_decisions (
                        decision_id TEXT PRIMARY KEY,
                        approval_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        accepted BOOLEAN NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        payload JSONB NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cp_audit_events (
                        idx BIGSERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
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

    def upsert_tool(self, tool: dict[str, Any]) -> None:
        name = str(tool.get("name", "")).strip()
        if not name:
            return
        payload = deepcopy(tool)
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cp_tools (name, payload, updated_at)
                    VALUES (%s, %s::jsonb, NOW())
                    ON CONFLICT (name)
                    DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                    """,
                    (name, self._dumps(payload)),
                )
            conn.commit()

    def list_tools(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload
                    FROM cp_tools
                    ORDER BY name ASC
                    """
                )
                rows = cur.fetchall()
        return [deepcopy(self._loads(row[0])) for row in rows]

    def list_pending_approvals(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_id, payload
                    FROM cp_approval_requests
                    ORDER BY created_at ASC
                    """
                )
                rows = cur.fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            payload = self._loads(row[1])
            payload["session_id"] = str(row[0])
            items.append(payload)
        return items

    def get_pending_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_id, payload
                    FROM cp_approval_requests
                    WHERE approval_id = %s
                    """,
                    (approval_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        payload = self._loads(row[1])
        payload["session_id"] = str(row[0])
        return payload

    def append_approval_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        payload = deepcopy(decision)
        created_at = str(payload.get("createdAt") or _utcnow())
        payload["createdAt"] = created_at
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cp_approval_decisions (
                        decision_id,
                        approval_id,
                        session_id,
                        run_id,
                        tool_name,
                        decision,
                        accepted,
                        created_at,
                        payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        str(payload.get("decisionId", "")),
                        str(payload.get("approvalId", "")),
                        str(payload.get("sessionId", "")),
                        str(payload.get("runId", "")),
                        str(payload.get("toolName", "")),
                        str(payload.get("decision", "")),
                        bool(payload.get("accepted", True)),
                        created_at,
                        self._dumps(payload),
                    ),
                )
            conn.commit()
        return deepcopy(payload)

    def append_audit_event(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str | None = None,
    ) -> dict[str, Any]:
        timestamp = created_at or _utcnow()
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cp_audit_events (session_id, event_type, created_at, payload)
                    VALUES (%s, %s, %s, %s::jsonb)
                    RETURNING idx, created_at
                    """,
                    (session_id, event_type, timestamp, self._dumps(payload)),
                )
                row = cur.fetchone()
            conn.commit()
        return {
            "sessionId": session_id,
            "eventType": event_type,
            "payload": deepcopy(payload),
            "createdAt": self._isoformat(row[1]) if row else timestamp,
            "index": int(row[0]) if row else 0,
        }

    def list_audit_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 500))
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT idx, session_id, event_type, created_at, payload
                    FROM cp_audit_events
                    ORDER BY idx DESC
                    LIMIT %s
                    """,
                    (bounded,),
                )
                rows = cur.fetchall()
        return [
            {
                "sessionId": str(row[1]),
                "eventType": str(row[2]),
                "payload": self._loads(row[4]),
                "createdAt": self._isoformat(row[3]),
                "index": int(row[0]),
            }
            for row in rows
        ]
