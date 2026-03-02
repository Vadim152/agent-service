from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from policy import PolicyService
from policy.store import PostgresPolicyStore


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.now(timezone.utc)


class _StateStoreStub:
    def list_pending_tool_calls(self) -> list[dict[str, Any]]:
        return []

    def find_pending_tool_call(self, tool_call_id: str) -> dict[str, Any] | None:
        _ = tool_call_id
        return None


class _FakePostgresDb:
    def __init__(self) -> None:
        self.tools: dict[str, dict[str, Any]] = {}
        self.approvals: dict[str, dict[str, Any]] = {}
        self.decisions: list[dict[str, Any]] = []
        self.audit_events: list[dict[str, Any]] = []
        self.next_audit_idx = 1


class _FakeCursor:
    def __init__(self, db: _FakePostgresDb) -> None:
        self._db = db
        self._results: list[tuple[Any, ...]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = (exc_type, exc, tb)

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        sql = " ".join(query.split())
        args = params or ()
        self._results = []

        if sql.startswith("CREATE TABLE IF NOT EXISTS"):
            return

        if sql.startswith("INSERT INTO cp_tools "):
            name, payload_raw = args
            self._db.tools[str(name)] = json.loads(str(payload_raw))
            return

        if sql.startswith("SELECT payload FROM cp_tools ORDER BY name ASC"):
            rows = [(self._db.tools[name],) for name in sorted(self._db.tools)]
            self._results = rows
            return

        if sql.startswith("SELECT session_id, payload FROM cp_approval_requests ORDER BY created_at ASC"):
            rows = sorted(self._db.approvals.values(), key=lambda row: row["created_at"])
            self._results = [(row["session_id"], row["payload"]) for row in rows]
            return

        if sql.startswith("SELECT session_id, payload FROM cp_approval_requests WHERE approval_id ="):
            row = self._db.approvals.get(str(args[0]))
            if row:
                self._results = [(row["session_id"], row["payload"])]
            return

        if sql.startswith("INSERT INTO cp_approval_decisions "):
            (
                decision_id,
                approval_id,
                session_id,
                run_id,
                tool_name,
                decision,
                accepted,
                created_at,
                payload_raw,
            ) = args
            self._db.decisions.append(
                {
                    "decision_id": str(decision_id),
                    "approval_id": str(approval_id),
                    "session_id": str(session_id),
                    "run_id": str(run_id),
                    "tool_name": str(tool_name),
                    "decision": str(decision),
                    "accepted": bool(accepted),
                    "created_at": _to_datetime(created_at),
                    "payload": json.loads(str(payload_raw)),
                }
            )
            return

        if sql.startswith("INSERT INTO cp_audit_events "):
            session_id, event_type, created_at, payload_raw = args
            idx = self._db.next_audit_idx
            self._db.next_audit_idx += 1
            row = {
                "idx": idx,
                "session_id": str(session_id),
                "event_type": str(event_type),
                "created_at": _to_datetime(created_at),
                "payload": json.loads(str(payload_raw)),
            }
            self._db.audit_events.append(row)
            self._results = [(idx, row["created_at"])]
            return

        if sql.startswith("SELECT idx, session_id, event_type, created_at, payload FROM cp_audit_events ORDER BY idx DESC LIMIT %s"):
            limit = int(args[0])
            rows = sorted(self._db.audit_events, key=lambda row: row["idx"], reverse=True)[:limit]
            self._results = [
                (row["idx"], row["session_id"], row["event_type"], row["created_at"], row["payload"])
                for row in rows
            ]
            return

        raise AssertionError(f"Unsupported SQL in fake cursor: {sql}")

    def fetchone(self) -> tuple[Any, ...] | None:
        if not self._results:
            return None
        return self._results.pop(0)

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows = list(self._results)
        self._results = []
        return rows


class _FakeConnection:
    def __init__(self, db: _FakePostgresDb) -> None:
        self._db = db

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = (exc_type, exc, tb)

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._db)

    def commit(self) -> None:
        return None


class _FakePsycopg:
    def __init__(self, db: _FakePostgresDb) -> None:
        self._db = db

    def connect(self, dsn: str) -> _FakeConnection:
        _ = dsn
        return _FakeConnection(self._db)


def test_postgres_policy_store_persists_tools_approvals_and_audit(monkeypatch) -> None:
    db = _FakePostgresDb()
    monkeypatch.setattr(PostgresPolicyStore, "_load_psycopg", staticmethod(lambda: _FakePsycopg(db)))
    store = PostgresPolicyStore(dsn="postgresql://local/test")

    db.approvals["approval-1"] = {
        "session_id": "session-1",
        "created_at": datetime.now(timezone.utc),
        "payload": {
            "tool_call_id": "approval-1",
            "tool_name": "save_generated_feature",
            "title": "save_generated_feature",
            "kind": "tool",
            "risk_level": "high",
            "requires_confirmation": True,
            "args": {"target_path": "src/test/resources/features/SCBC-T123.feature"},
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    store.upsert_tool({"name": "save_generated_feature", "riskLevel": "high", "enabled": True})
    tools = store.list_tools()
    assert tools[0]["name"] == "save_generated_feature"

    pending = store.list_pending_approvals()
    assert pending[0]["tool_call_id"] == "approval-1"
    assert store.get_pending_approval("approval-1") is not None

    decision = store.append_approval_decision(
        {
            "decisionId": "decision-1",
            "approvalId": "approval-1",
            "sessionId": "session-1",
            "runId": "run-1",
            "toolName": "save_generated_feature",
            "decision": "approve",
            "accepted": True,
        }
    )
    assert decision["decisionId"] == "decision-1"
    assert db.decisions[0]["approval_id"] == "approval-1"

    event = store.append_audit_event(
        session_id="session-1",
        event_type="permission.approved",
        payload={"sessionId": "session-1", "permissionId": "approval-1", "runId": "run-1"},
    )
    assert event["eventType"] == "permission.approved"
    audit = store.list_audit_events(limit=10)
    assert audit[0]["eventType"] == "permission.approved"


def test_policy_service_prefers_postgres_pending_approvals(monkeypatch) -> None:
    db = _FakePostgresDb()
    monkeypatch.setattr(PostgresPolicyStore, "_load_psycopg", staticmethod(lambda: _FakePsycopg(db)))
    store = PostgresPolicyStore(dsn="postgresql://local/test")
    db.approvals["approval-2"] = {
        "session_id": "session-2",
        "created_at": datetime.now(timezone.utc),
        "payload": {
            "tool_call_id": "approval-2",
            "tool_name": "patch.apply",
            "title": "patch.apply",
            "kind": "tool",
            "risk_level": "high",
            "requires_confirmation": True,
            "args": {"path": "src/app/main.py"},
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    service = PolicyService(state_store=_StateStoreStub(), store=store)

    pending = asyncio.run(service.list_pending_approvals())
    assert len(pending) == 1
    assert pending[0]["approvalId"] == "approval-2"
    loaded = asyncio.run(service.get_pending_approval("approval-2"))
    assert loaded is not None
    assert loaded["toolName"] == "patch.apply"
