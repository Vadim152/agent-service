from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chat.memory_store import ChatMemoryStore
from chat.postgres_state_store import PostgresChatStateStore
from chat.runtime import ChatAgentRuntime
from infrastructure.run_state_store import RunStateStore


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.now(timezone.utc)


class _FakePostgresDb:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.messages: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.event_cursors: dict[str, int] = {}
        self.approvals: dict[str, dict[str, Any]] = {}


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

        if sql.startswith("CREATE TABLE IF NOT EXISTS") or sql.startswith("CREATE INDEX IF NOT EXISTS") or sql.startswith("ALTER TABLE cp_sessions ADD COLUMN IF NOT EXISTS runtime"):
            return

        if sql.startswith("INSERT INTO cp_sessions "):
            if len(args) == 7:
                session_id, project_root, source, profile, runtime, status, payload_raw = args
            else:
                session_id, project_root, source, profile, status, payload_raw = args
                runtime = "chat"
            now = datetime.now(timezone.utc)
            self._db.sessions[str(session_id)] = {
                "session_id": str(session_id),
                "project_root": str(project_root),
                "source": str(source),
                "profile": str(profile),
                "runtime": str(runtime),
                "status": str(status),
                "payload": json.loads(str(payload_raw)),
                "created_at": now,
                "updated_at": now,
            }
            return

        if sql.startswith("SELECT session_id, project_root, source, profile, runtime, status, payload, created_at, updated_at FROM cp_sessions WHERE session_id ="):
            session = self._db.sessions.get(str(args[0]))
            if session:
                self._results = [
                    (
                        session["session_id"],
                        session["project_root"],
                        session["source"],
                        session["profile"],
                        session["runtime"],
                        session["status"],
                        session["payload"],
                        session["created_at"],
                        session["updated_at"],
                    )
                ]
            return

        if sql.startswith("SELECT session_id FROM cp_sessions WHERE project_root =") and "LIMIT 1" in sql:
            project_root = str(args[0])
            runtime = str(args[1]) if len(args) > 1 else None
            rows = [
                row
                for row in self._db.sessions.values()
                if row["project_root"] == project_root and (runtime is None or row["runtime"] == runtime)
            ]
            rows.sort(key=lambda row: row["updated_at"], reverse=True)
            if rows:
                self._results = [(rows[0]["session_id"],)]
            return

        if sql.startswith("SELECT session_id FROM cp_sessions WHERE project_root =") and "LIMIT %s" in sql:
            project_root = str(args[0])
            if len(args) == 3:
                runtime = str(args[1])
                limit = int(args[2])
            else:
                runtime = None
                limit = int(args[1])
            rows = [
                row
                for row in self._db.sessions.values()
                if row["project_root"] == project_root and (runtime is None or row["runtime"] == runtime)
            ]
            rows.sort(key=lambda row: row["updated_at"], reverse=True)
            self._results = [(row["session_id"],) for row in rows[:limit]]
            return

        if sql.startswith("SELECT session_id FROM cp_sessions WHERE project_root =") and "LIMIT %s" not in sql:
            project_root = str(args[0])
            rows = [row for row in self._db.sessions.values() if row["project_root"] == project_root]
            rows.sort(key=lambda row: row["updated_at"], reverse=True)
            self._results = [(row["session_id"],) for row in rows]
            return

        if sql.startswith("SELECT session_id FROM cp_sessions ORDER BY updated_at DESC LIMIT %s"):
            limit = int(args[0])
            rows = sorted(self._db.sessions.values(), key=lambda row: row["updated_at"], reverse=True)
            self._results = [(row["session_id"],) for row in rows[:limit]]
            return

        if sql.startswith("UPDATE cp_sessions SET project_root ="):
            project_root, source, profile, runtime, status, payload_raw, session_id = args
            row = self._db.sessions.get(str(session_id))
            if row:
                row.update(
                    {
                        "project_root": str(project_root),
                        "source": str(source),
                        "profile": str(profile),
                        "runtime": str(runtime),
                        "status": str(status),
                        "payload": json.loads(str(payload_raw)),
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
            return

        if sql.startswith("UPDATE cp_sessions SET updated_at = NOW() WHERE session_id ="):
            row = self._db.sessions.get(str(args[0]))
            if row:
                row["updated_at"] = datetime.now(timezone.utc)
            return

        if sql.startswith("DELETE FROM cp_sessions WHERE session_id ="):
            self._db.sessions.pop(str(args[0]), None)
            return

        if sql.startswith("INSERT INTO cp_session_messages "):
            session_id, message_id, created_at, payload_raw = args
            self._db.messages.append(
                {
                    "session_id": str(session_id),
                    "message_id": str(message_id),
                    "created_at": _to_datetime(created_at),
                    "payload": json.loads(str(payload_raw)),
                }
            )
            return

        if sql.startswith("SELECT payload FROM cp_session_messages WHERE session_id ="):
            session_id = str(args[0])
            rows = [row for row in self._db.messages if row["session_id"] == session_id]
            rows.sort(key=lambda row: row["created_at"])
            self._results = [(row["payload"],) for row in rows]
            return

        if sql.startswith("DELETE FROM cp_session_messages WHERE session_id ="):
            session_id = str(args[0])
            self._db.messages = [row for row in self._db.messages if row["session_id"] != session_id]
            return

        if sql.startswith("SELECT idx, event_type, payload, created_at FROM cp_session_events WHERE session_id =") and "AND idx >=" not in sql:
            session_id = str(args[0])
            rows = [row for row in self._db.events if row["session_id"] == session_id]
            rows.sort(key=lambda row: row["idx"])
            self._results = [
                (row["idx"], row["event_type"], row["payload"], row["created_at"])
                for row in rows
            ]
            return

        if sql.startswith("SELECT idx, event_type, payload, created_at FROM cp_session_events WHERE session_id =") and "AND idx >=" in sql:
            session_id = str(args[0])
            floor = int(args[1])
            rows = [row for row in self._db.events if row["session_id"] == session_id and row["idx"] >= floor]
            rows.sort(key=lambda row: row["idx"])
            self._results = [
                (row["idx"], row["event_type"], row["payload"], row["created_at"])
                for row in rows
            ]
            return

        if sql.startswith("INSERT INTO cp_session_events "):
            session_id, idx, event_type, created_at, payload_raw = args
            self._db.events.append(
                {
                    "session_id": str(session_id),
                    "idx": int(idx),
                    "event_type": str(event_type),
                    "created_at": _to_datetime(created_at),
                    "payload": json.loads(str(payload_raw)),
                }
            )
            return

        if sql.startswith("DELETE FROM cp_session_events WHERE session_id ="):
            session_id = str(args[0])
            self._db.events = [row for row in self._db.events if row["session_id"] != session_id]
            return

        if sql.startswith("SELECT next_idx FROM cp_session_event_cursor WHERE session_id =") and "FOR UPDATE" in sql:
            next_idx = self._db.event_cursors.get(str(args[0]))
            if next_idx is not None:
                self._results = [(next_idx,)]
            return

        if sql.startswith("SELECT next_idx FROM cp_session_event_cursor WHERE session_id ="):
            next_idx = self._db.event_cursors.get(str(args[0]))
            if next_idx is not None:
                self._results = [(next_idx,)]
            return

        if sql.startswith("INSERT INTO cp_session_event_cursor "):
            session_id, next_idx = args
            self._db.event_cursors[str(session_id)] = int(next_idx)
            return

        if sql.startswith("UPDATE cp_session_event_cursor SET next_idx ="):
            next_idx, session_id = args
            self._db.event_cursors[str(session_id)] = int(next_idx)
            return

        if sql.startswith("DELETE FROM cp_session_event_cursor WHERE session_id ="):
            self._db.event_cursors.pop(str(args[0]), None)
            return

        if sql.startswith("INSERT INTO cp_approval_requests "):
            approval_id, session_id, tool_name, created_at, payload_raw = args
            self._db.approvals[str(approval_id)] = {
                "approval_id": str(approval_id),
                "session_id": str(session_id),
                "tool_name": str(tool_name),
                "created_at": _to_datetime(created_at),
                "payload": json.loads(str(payload_raw)),
            }
            return

        if sql.startswith("SELECT session_id, payload FROM cp_approval_requests WHERE session_id ="):
            session_id = str(args[0])
            rows = [row for row in self._db.approvals.values() if row["session_id"] == session_id]
            rows.sort(key=lambda row: row["created_at"])
            self._results = [(row["session_id"], row["payload"]) for row in rows]
            return

        if sql.startswith("SELECT session_id, payload FROM cp_approval_requests ORDER BY created_at ASC"):
            rows = sorted(self._db.approvals.values(), key=lambda row: row["created_at"])
            self._results = [(row["session_id"], row["payload"]) for row in rows]
            return

        if sql.startswith("SELECT payload FROM cp_approval_requests WHERE approval_id ="):
            approval_id, session_id = args
            row = self._db.approvals.get(str(approval_id))
            if row and row["session_id"] == str(session_id):
                self._results = [(row["payload"],)]
            return

        if sql.startswith("SELECT session_id, payload FROM cp_approval_requests WHERE approval_id ="):
            row = self._db.approvals.get(str(args[0]))
            if row:
                self._results = [(row["session_id"], row["payload"])]
            return

        if sql.startswith("DELETE FROM cp_approval_requests WHERE approval_id =") and "AND session_id =" in sql:
            approval_id, session_id = args
            row = self._db.approvals.get(str(approval_id))
            if row and row["session_id"] == str(session_id):
                self._db.approvals.pop(str(approval_id), None)
            return

        if sql.startswith("DELETE FROM cp_approval_requests WHERE session_id ="):
            session_id = str(args[0])
            self._db.approvals = {
                key: row for key, row in self._db.approvals.items() if row["session_id"] != session_id
            }
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


class _OrchestratorStub:
    def apply_feature(
        self,
        project_root: str,
        target_path: str,
        feature_text: str,
        *,
        overwrite_existing: bool = False,
    ) -> dict[str, object]:
        _ = (project_root, feature_text)
        return {
            "targetPath": target_path,
            "status": "overwritten" if overwrite_existing else "created",
            "message": None,
        }


class _SupervisorStub:
    def __init__(self, store: RunStateStore) -> None:
        self.store = store

    async def execute_run(self, run_id: str) -> None:
        self.store.patch_job(
            run_id,
            status="succeeded",
            finished_at=_utcnow(),
            result={
                "featureText": "Feature: SCBC-T123\n  Scenario: Demo\n    Given step",
                "unmappedSteps": [],
                "unmapped": [],
                "usedSteps": [],
                "buildStage": "feature_built",
                "stepsSummary": {"exact": 1, "fuzzy": 0, "unmatched": 0},
                "meta": {"language": "ru"},
                "pipeline": [
                    {"stage": "source_resolve", "status": "raw_text", "details": {"jiraKey": "SCBC-T123"}},
                    {"stage": "parse", "status": "ok", "details": {}},
                ],
                "fileStatus": None,
            },
        )


def test_postgres_chat_state_store_round_trip(monkeypatch, tmp_path: Path) -> None:
    db = _FakePostgresDb()
    monkeypatch.setattr(PostgresChatStateStore, "_load_psycopg", staticmethod(lambda: _FakePsycopg(db)))
    memory_store = ChatMemoryStore(tmp_path / "chat-memory")
    store = PostgresChatStateStore(memory_store, dsn="postgresql://local/test")

    session, reused = store.create_session(
        project_root="/tmp/project",
        source="test-suite",
        profile="quick",
        reuse_existing=False,
    )
    assert reused is False

    session_id = session["session_id"]
    store.update_session(session_id, activity="busy", current_action="Processing request")
    store.append_message(session_id, role="user", content="hello", run_id="run-1", message_id="msg-1")
    store.append_event(session_id, "message.received", {"sessionId": session_id, "runId": "run-1"})
    store.set_pending_tool_call(
        session_id,
        tool_call_id="approval-1",
        tool_name="save_generated_feature",
        args={"target_path": "src/test/resources/features/SCBC-T123.feature"},
        risk_level="high",
        requires_confirmation=True,
    )

    history = store.history(session_id, limit=50)
    assert history is not None
    assert history["activity"] == "busy"
    assert history["messages"][-1]["content"] == "hello"
    assert history["pending_tool_calls"][0]["tool_call_id"] == "approval-1"

    events, next_index = store.list_events(session_id, since_index=1)
    assert [event["event_type"] for event in events] == ["message.received"]
    assert next_index == 2

    reloaded = PostgresChatStateStore(memory_store, dsn="postgresql://local/test")
    loaded = reloaded.get_session(session_id)
    assert loaded is not None
    assert loaded["activity"] == "busy"
    assert loaded["pending_tool_calls"][0]["tool_name"] == "save_generated_feature"


def test_chat_runtime_uses_postgres_chat_state_store_for_free_text_autotest(monkeypatch, tmp_path: Path) -> None:
    db = _FakePostgresDb()
    monkeypatch.setattr(PostgresChatStateStore, "_load_psycopg", staticmethod(lambda: _FakePsycopg(db)))
    memory_store = ChatMemoryStore(tmp_path / "chat-memory-runtime")
    state_store = PostgresChatStateStore(memory_store, dsn="postgresql://local/test")
    run_state_store = RunStateStore()
    runtime = ChatAgentRuntime(
        memory_store=memory_store,
        state_store=state_store,
        orchestrator=_OrchestratorStub(),
        run_state_store=run_state_store,
        execution_supervisor=_SupervisorStub(run_state_store),
    )

    async def _scenario() -> None:
        created = await runtime.create_session(
            project_root="/tmp/project",
            source="ide-plugin",
            profile="quick",
            reuse_existing=False,
        )
        session_id = str(created["sessionId"])
        await runtime.process_message(
            session_id=session_id,
            run_id="session-run-1",
            message_id="msg-1",
            content="создай автотест SCBC-T123",
        )
        history = await runtime.get_history(session_id=session_id)
        assert len(history["pendingPermissions"]) == 1
        assert history["pendingPermissions"][0]["metadata"]["target_path"] == "src/test/resources/features/SCBC-T123.feature"

    asyncio.run(_scenario())
