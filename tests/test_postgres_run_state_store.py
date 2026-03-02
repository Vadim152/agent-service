from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from infrastructure.postgres_run_state_store import PostgresRunStateStore


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
        self.runs: dict[str, dict[str, Any]] = {}
        self.attempts: dict[tuple[str, str], dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.event_cursors: dict[str, int] = {}
        self.idempotency: dict[str, dict[str, Any]] = {}


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

        if sql.startswith("INSERT INTO cp_runs "):
            (
                run_id,
                plugin,
                status,
                source,
                session_id,
                project_root,
                profile,
                priority,
                test_case_text,
                target_path,
                create_file,
                overwrite_existing,
                language,
                quality_policy,
                quality_policy_explicit,
                zephyr_auth_raw,
                jira_instance,
                cancel_requested,
                cancel_requested_at,
                execution_id,
                incident_uri,
                input_raw,
                result_raw,
                payload_raw,
                started_at,
                finished_at,
                updated_at,
            ) = args
            self._db.runs[str(run_id)] = {
                "run_id": str(run_id),
                "plugin": str(plugin),
                "status": str(status),
                "source": source,
                "session_id": session_id,
                "project_root": project_root,
                "profile": profile,
                "priority": priority,
                "test_case_text": test_case_text,
                "target_path": target_path,
                "create_file": bool(create_file),
                "overwrite_existing": bool(overwrite_existing),
                "language": language,
                "quality_policy": quality_policy,
                "quality_policy_explicit": bool(quality_policy_explicit),
                "zephyr_auth": json.loads(str(zephyr_auth_raw)),
                "jira_instance": jira_instance,
                "cancel_requested": bool(cancel_requested),
                "cancel_requested_at": _to_datetime(cancel_requested_at) if cancel_requested_at else None,
                "execution_id": execution_id,
                "incident_uri": incident_uri,
                "input": json.loads(str(input_raw)),
                "result": json.loads(str(result_raw)),
                "payload": json.loads(str(payload_raw)),
                "started_at": _to_datetime(started_at) if started_at else None,
                "finished_at": _to_datetime(finished_at) if finished_at else None,
                "updated_at": _to_datetime(updated_at),
            }
            return

        if sql.startswith("DELETE FROM cp_run_attempts WHERE run_id ="):
            run_id = str(args[0])
            self._db.attempts = {
                key: row for key, row in self._db.attempts.items() if row["run_id"] != run_id
            }
            return

        if sql.startswith("INSERT INTO cp_run_attempts "):
            (
                run_id,
                attempt_id,
                attempt_no,
                status,
                started_at,
                finished_at,
                classification_raw,
                remediation_raw,
                artifacts_raw,
                payload_raw,
            ) = args
            self._db.attempts[(str(run_id), str(attempt_id))] = {
                "run_id": str(run_id),
                "attempt_id": str(attempt_id),
                "attempt_no": attempt_no,
                "status": str(status),
                "started_at": _to_datetime(started_at) if started_at else None,
                "finished_at": _to_datetime(finished_at) if finished_at else None,
                "classification": json.loads(str(classification_raw)),
                "remediation": json.loads(str(remediation_raw)),
                "artifacts": json.loads(str(artifacts_raw)),
                "payload": json.loads(str(payload_raw)),
            }
            return

        if sql.startswith("SELECT payload FROM cp_run_attempts WHERE run_id = %s AND attempt_id = %s"):
            row = self._db.attempts.get((str(args[0]), str(args[1])))
            if row:
                self._results = [(row["payload"],)]
            return

        if sql.startswith("SELECT payload FROM cp_run_attempts WHERE run_id = %s ORDER BY"):
            run_id = str(args[0])
            rows = [row for row in self._db.attempts.values() if row["run_id"] == run_id]
            rows.sort(key=lambda item: (item["attempt_no"] or 0, item["started_at"] or datetime.min.replace(tzinfo=timezone.utc), item["attempt_id"]))
            self._results = [(row["payload"],) for row in rows]
            return

        if sql.startswith("SELECT") and "FROM cp_runs" in sql and "WHERE run_id = %s" in sql:
            row = self._db.runs.get(str(args[0]))
            if row:
                self._results = [
                    (
                        row["run_id"],
                        row["plugin"],
                        row["status"],
                        row["source"],
                        row["session_id"],
                        row["project_root"],
                        row["profile"],
                        row["priority"],
                        row["test_case_text"],
                        row["target_path"],
                        row["create_file"],
                        row["overwrite_existing"],
                        row["language"],
                        row["quality_policy"],
                        row["quality_policy_explicit"],
                        row["zephyr_auth"],
                        row["jira_instance"],
                        row["cancel_requested"],
                        row["cancel_requested_at"],
                        row["execution_id"],
                        row["incident_uri"],
                        row["input"],
                        row["result"],
                        row["payload"],
                        row["started_at"],
                        row["finished_at"],
                        row["updated_at"],
                    )
                ]
            return

        if sql.startswith("SELECT next_idx FROM cp_run_event_cursor WHERE run_id =") and "FOR UPDATE" in sql:
            next_idx = self._db.event_cursors.get(str(args[0]))
            if next_idx is not None:
                self._results = [(next_idx,)]
            return

        if sql.startswith("SELECT next_idx FROM cp_run_event_cursor WHERE run_id ="):
            next_idx = self._db.event_cursors.get(str(args[0]))
            if next_idx is not None:
                self._results = [(next_idx,)]
            return

        if sql.startswith("INSERT INTO cp_run_event_cursor "):
            run_id, next_idx = args
            self._db.event_cursors[str(run_id)] = int(next_idx)
            return

        if sql.startswith("UPDATE cp_run_event_cursor SET next_idx ="):
            next_idx, run_id = args
            self._db.event_cursors[str(run_id)] = int(next_idx)
            return

        if sql.startswith("INSERT INTO cp_run_events "):
            run_id, idx, event_type, payload_raw = args
            self._db.events.append(
                {
                    "run_id": str(run_id),
                    "idx": int(idx),
                    "event_type": str(event_type),
                    "payload": json.loads(str(payload_raw)),
                    "created_at": datetime.now(timezone.utc),
                }
            )
            return

        if sql.startswith("SELECT idx, event_type, payload, created_at FROM cp_run_events WHERE run_id ="):
            run_id = str(args[0])
            floor = int(args[1])
            rows = [row for row in self._db.events if row["run_id"] == run_id and row["idx"] >= floor]
            rows.sort(key=lambda item: item["idx"])
            self._results = [(row["idx"], row["event_type"], row["payload"], row["created_at"]) for row in rows]
            return

        if sql.startswith("SELECT fingerprint, run_id FROM cp_run_idempotency WHERE idempotency_key ="):
            row = self._db.idempotency.get(str(args[0]))
            if row:
                self._results = [(row["fingerprint"], row["run_id"])]
            return

        if sql.startswith("INSERT INTO cp_run_idempotency "):
            key, fingerprint, run_id = args
            self._db.idempotency[str(key)] = {"fingerprint": str(fingerprint), "run_id": str(run_id)}
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


def test_postgres_run_state_store_round_trip(monkeypatch) -> None:
    db = _FakePostgresDb()
    monkeypatch.setattr(PostgresRunStateStore, "_load_psycopg", staticmethod(lambda: _FakePsycopg(db)))
    store = PostgresRunStateStore(dsn="postgresql://local/test")

    store.put_job(
        {
            "run_id": "run-1",
            "plugin": "testgen",
            "status": "running",
            "source": "test-suite",
            "session_id": "session-1",
            "project_root": "/tmp/project",
            "profile": "quick",
            "priority": "normal",
            "test_case_text": "SCBC-T123",
            "target_path": "src/test/resources/features/SCBC-T123.feature",
            "create_file": False,
            "overwrite_existing": False,
            "language": "ru",
            "quality_policy": "strict",
            "quality_policy_explicit": False,
            "zephyr_auth": {"authType": "TOKEN", "token": "secret"},
            "jira_instance": "https://jira.example",
            "cancel_requested": False,
            "cancel_requested_at": None,
            "execution_id": "exec-1",
            "incident_uri": None,
            "input": {"jiraKey": "SCBC-T123"},
            "result": None,
            "started_at": _utcnow(),
            "updated_at": _utcnow(),
            "attempts": [
                {
                    "attempt_id": "attempt-1",
                    "attempt_no": 1,
                    "status": "started",
                    "started_at": _utcnow(),
                    "artifacts": {"featureResult": "artifact://1"},
                }
            ],
        }
    )

    loaded = store.get_job("run-1")
    assert loaded is not None
    assert loaded["run_id"] == "run-1"
    assert loaded["execution_id"] == "exec-1"
    assert loaded["session_id"] == "session-1"
    assert loaded["zephyr_auth"] == {"authType": "TOKEN", "token": "secret"}
    assert loaded["attempts"][0]["attempt_id"] == "attempt-1"


def test_postgres_run_state_store_updates_attempts_and_events(monkeypatch) -> None:
    db = _FakePostgresDb()
    monkeypatch.setattr(PostgresRunStateStore, "_load_psycopg", staticmethod(lambda: _FakePsycopg(db)))
    store = PostgresRunStateStore(dsn="postgresql://local/test")

    store.put_job(
        {
            "run_id": "run-2",
            "plugin": "testgen",
            "status": "queued",
            "started_at": _utcnow(),
            "updated_at": _utcnow(),
            "attempts": [],
            "result": None,
        }
    )

    store.append_attempt(
        "run-2",
        {
            "attempt_id": "attempt-1",
            "attempt_no": 1,
            "status": "started",
            "started_at": _utcnow(),
            "artifacts": {},
        },
    )
    store.patch_attempt(
        "run-2",
        "attempt-1",
        status="succeeded",
        finished_at=_utcnow(),
        artifacts={"featureResult": "artifact://feature-1"},
    )
    attempts = store.list_attempts("run-2")
    assert len(attempts) == 1
    assert attempts[0]["status"] == "succeeded"
    assert attempts[0]["artifacts"]["featureResult"] == "artifact://feature-1"

    store.append_event("run-2", "run.queued", {"runId": "run-2"})
    store.append_event("run-2", "run.finished", {"runId": "run-2", "status": "succeeded"})
    events, next_index = store.list_events("run-2", since_index=1)
    assert next_index == 2
    assert [item["event_type"] for item in events] == ["run.finished"]


def test_postgres_run_state_store_claims_idempotency_keys(monkeypatch) -> None:
    db = _FakePostgresDb()
    monkeypatch.setattr(PostgresRunStateStore, "_load_psycopg", staticmethod(lambda: _FakePsycopg(db)))
    store = PostgresRunStateStore(dsn="postgresql://local/test")

    claimed, existing = store.claim_idempotency_key("key-1", fingerprint="fp-1", run_id="run-3")
    assert claimed is True
    assert existing is None

    claimed, existing = store.claim_idempotency_key("key-1", fingerprint="fp-1", run_id="run-4")
    assert claimed is False
    assert existing == "run-3"

    claimed, existing = store.claim_idempotency_key("key-1", fingerprint="fp-2", run_id="run-4")
    assert claimed is False
    assert existing is None
