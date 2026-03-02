"""Postgres-backed run state store using explicit control-plane tables."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresRunStateStore:
    """Thread-safe Postgres implementation compatible with RunStateStore API."""

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
                "Postgres backend requires 'psycopg' package. Install dependency and retry."
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
                    CREATE TABLE IF NOT EXISTS cp_runs (
                        run_id TEXT PRIMARY KEY,
                        plugin TEXT NOT NULL,
                        status TEXT NOT NULL,
                        source TEXT,
                        session_id TEXT,
                        project_root TEXT,
                        profile TEXT,
                        priority TEXT,
                        test_case_text TEXT,
                        target_path TEXT,
                        create_file BOOLEAN NOT NULL DEFAULT FALSE,
                        overwrite_existing BOOLEAN NOT NULL DEFAULT FALSE,
                        language TEXT,
                        quality_policy TEXT,
                        quality_policy_explicit BOOLEAN NOT NULL DEFAULT FALSE,
                        zephyr_auth JSONB,
                        jira_instance TEXT,
                        cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
                        cancel_requested_at TIMESTAMPTZ,
                        execution_id TEXT,
                        incident_uri TEXT,
                        input JSONB,
                        result JSONB,
                        payload JSONB NOT NULL,
                        started_at TIMESTAMPTZ,
                        finished_at TIMESTAMPTZ,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cp_run_attempts (
                        run_id TEXT NOT NULL,
                        attempt_id TEXT NOT NULL,
                        attempt_no INTEGER,
                        status TEXT NOT NULL,
                        started_at TIMESTAMPTZ,
                        finished_at TIMESTAMPTZ,
                        classification JSONB,
                        remediation JSONB,
                        artifacts JSONB,
                        payload JSONB NOT NULL,
                        PRIMARY KEY (run_id, attempt_id)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cp_run_events (
                        run_id TEXT NOT NULL,
                        idx INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (run_id, idx)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cp_run_event_cursor (
                        run_id TEXT PRIMARY KEY,
                        next_idx INTEGER NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cp_run_idempotency (
                        idempotency_key TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL,
                        run_id TEXT NOT NULL
                    )
                    """
                )
            conn.commit()

    @staticmethod
    def _dumps(payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _loads(payload: Any) -> Any:
        if isinstance(payload, (dict, list)):
            return payload
        if isinstance(payload, str):
            return json.loads(payload)
        return None

    @staticmethod
    def _normalize_dt(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _base_payload(run_record: dict[str, Any]) -> dict[str, Any]:
        payload = deepcopy(run_record)
        payload.pop("attempts", None)
        return payload

    def put_job(self, job: dict[str, Any]) -> None:
        run_id = str(job["run_id"])
        payload = deepcopy(job)
        attempts = [deepcopy(attempt) for attempt in payload.pop("attempts", [])]
        updated_at = str(payload.get("updated_at") or _utcnow())
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cp_runs (
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
                        zephyr_auth,
                        jira_instance,
                        cancel_requested,
                        cancel_requested_at,
                        execution_id,
                        incident_uri,
                        input,
                        result,
                        payload,
                        started_at,
                        finished_at,
                        updated_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s
                    )
                    ON CONFLICT (run_id)
                    DO UPDATE SET
                        plugin = EXCLUDED.plugin,
                        status = EXCLUDED.status,
                        source = EXCLUDED.source,
                        session_id = EXCLUDED.session_id,
                        project_root = EXCLUDED.project_root,
                        profile = EXCLUDED.profile,
                        priority = EXCLUDED.priority,
                        test_case_text = EXCLUDED.test_case_text,
                        target_path = EXCLUDED.target_path,
                        create_file = EXCLUDED.create_file,
                        overwrite_existing = EXCLUDED.overwrite_existing,
                        language = EXCLUDED.language,
                        quality_policy = EXCLUDED.quality_policy,
                        quality_policy_explicit = EXCLUDED.quality_policy_explicit,
                        zephyr_auth = EXCLUDED.zephyr_auth,
                        jira_instance = EXCLUDED.jira_instance,
                        cancel_requested = EXCLUDED.cancel_requested,
                        cancel_requested_at = EXCLUDED.cancel_requested_at,
                        execution_id = EXCLUDED.execution_id,
                        incident_uri = EXCLUDED.incident_uri,
                        input = EXCLUDED.input,
                        result = EXCLUDED.result,
                        payload = EXCLUDED.payload,
                        started_at = EXCLUDED.started_at,
                        finished_at = EXCLUDED.finished_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        run_id,
                        str(payload.get("plugin", "testgen")),
                        str(payload.get("status", "queued")),
                        payload.get("source"),
                        payload.get("session_id"),
                        payload.get("project_root"),
                        payload.get("profile"),
                        payload.get("priority"),
                        payload.get("test_case_text"),
                        payload.get("target_path"),
                        bool(payload.get("create_file", False)),
                        bool(payload.get("overwrite_existing", False)),
                        payload.get("language"),
                        payload.get("quality_policy"),
                        bool(payload.get("quality_policy_explicit", False)),
                        self._dumps(payload.get("zephyr_auth")),
                        payload.get("jira_instance"),
                        bool(payload.get("cancel_requested", False)),
                        self._normalize_dt(payload.get("cancel_requested_at")),
                        payload.get("execution_id"),
                        payload.get("incident_uri"),
                        self._dumps(payload.get("input")),
                        self._dumps(payload.get("result")),
                        self._dumps(self._base_payload(payload)),
                        self._normalize_dt(payload.get("started_at")),
                        self._normalize_dt(payload.get("finished_at")),
                        updated_at,
                    ),
                )
                cur.execute("DELETE FROM cp_run_attempts WHERE run_id = %s", (run_id,))
                for attempt in attempts:
                    self._insert_attempt(cur, run_id, attempt)
            conn.commit()

    def _insert_attempt(self, cur, run_id: str, attempt: dict[str, Any]) -> None:
        cur.execute(
            """
            INSERT INTO cp_run_attempts (
                run_id,
                attempt_id,
                attempt_no,
                status,
                started_at,
                finished_at,
                classification,
                remediation,
                artifacts,
                payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
            ON CONFLICT (run_id, attempt_id)
            DO UPDATE SET
                attempt_no = EXCLUDED.attempt_no,
                status = EXCLUDED.status,
                started_at = EXCLUDED.started_at,
                finished_at = EXCLUDED.finished_at,
                classification = EXCLUDED.classification,
                remediation = EXCLUDED.remediation,
                artifacts = EXCLUDED.artifacts,
                payload = EXCLUDED.payload
            """,
            (
                run_id,
                str(attempt["attempt_id"]),
                attempt.get("attempt_no"),
                str(attempt.get("status", "started")),
                self._normalize_dt(attempt.get("started_at")),
                self._normalize_dt(attempt.get("finished_at")),
                self._dumps(attempt.get("classification")),
                self._dumps(attempt.get("remediation")),
                self._dumps(attempt.get("artifacts") or {}),
                self._dumps(attempt),
            ),
        )

    def _row_to_job(self, row: tuple[Any, ...], attempts: list[dict[str, Any]]) -> dict[str, Any]:
        payload = self._loads(row[23]) or {}
        run_record = payload if isinstance(payload, dict) else {}
        run_record["run_id"] = str(row[0])
        run_record["plugin"] = str(row[1])
        run_record["status"] = str(row[2])
        run_record["source"] = row[3]
        run_record["session_id"] = row[4]
        run_record["project_root"] = row[5]
        run_record["profile"] = row[6]
        run_record["priority"] = row[7]
        run_record["test_case_text"] = row[8]
        run_record["target_path"] = row[9]
        run_record["create_file"] = bool(row[10])
        run_record["overwrite_existing"] = bool(row[11])
        run_record["language"] = row[12]
        run_record["quality_policy"] = row[13]
        run_record["quality_policy_explicit"] = bool(row[14])
        run_record["zephyr_auth"] = self._loads(row[15])
        run_record["jira_instance"] = row[16]
        run_record["cancel_requested"] = bool(row[17])
        run_record["cancel_requested_at"] = self._normalize_dt(row[18])
        run_record["execution_id"] = row[19]
        run_record["incident_uri"] = row[20]
        run_record["input"] = self._loads(row[21])
        run_record["result"] = self._loads(row[22])
        run_record["started_at"] = self._normalize_dt(row[24])
        run_record["finished_at"] = self._normalize_dt(row[25])
        run_record["updated_at"] = self._normalize_dt(row[26]) or _utcnow()
        run_record["attempts"] = attempts
        return run_record

    def _load_attempts(self, cur, run_id: str) -> list[dict[str, Any]]:
        cur.execute(
            """
            SELECT payload
            FROM cp_run_attempts
            WHERE run_id = %s
            ORDER BY COALESCE(attempt_no, 0) ASC, started_at ASC, attempt_id ASC
            """,
            (run_id,),
        )
        return [deepcopy(self._loads(row[0])) for row in cur.fetchall()]

    def get_job(self, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
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
                        zephyr_auth,
                        jira_instance,
                        cancel_requested,
                        cancel_requested_at,
                        execution_id,
                        incident_uri,
                        input,
                        result,
                        payload,
                        started_at,
                        finished_at,
                        updated_at
                    FROM cp_runs
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                attempts = self._load_attempts(cur, run_id)
            return self._row_to_job(row, attempts)

    def patch_job(self, run_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            job = self.get_job(run_id)
            if not job:
                return None
            job.update(changes)
            job["updated_at"] = _utcnow()
            self.put_job(job)
            return deepcopy(job)

    def append_attempt(self, run_id: str, attempt: dict[str, Any]) -> dict[str, Any] | None:
        if not self.get_job(run_id):
            return None
        payload = deepcopy(attempt)
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                self._insert_attempt(cur, run_id, payload)
            conn.commit()
        self.patch_job(run_id)
        return payload

    def patch_attempt(self, run_id: str, attempt_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload
                    FROM cp_run_attempts
                    WHERE run_id = %s AND attempt_id = %s
                    """,
                    (run_id, attempt_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                payload = self._loads(row[0]) or {}
                payload.update(changes)
                self._insert_attempt(cur, run_id, payload)
            conn.commit()
        self.patch_job(run_id)
        return deepcopy(payload)

    def list_attempts(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                return self._load_attempts(cur, run_id)

    def append_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT next_idx FROM cp_run_event_cursor WHERE run_id = %s FOR UPDATE",
                    (run_id,),
                )
                row = cur.fetchone()
                idx = int(row[0]) if row else 0
                cur.execute(
                    """
                    INSERT INTO cp_run_events (run_id, idx, event_type, payload, created_at)
                    VALUES (%s, %s, %s, %s::jsonb, NOW())
                    """,
                    (run_id, idx, event_type, self._dumps(payload)),
                )
                if row:
                    cur.execute(
                        "UPDATE cp_run_event_cursor SET next_idx = %s WHERE run_id = %s",
                        (idx + 1, run_id),
                    )
                else:
                    cur.execute(
                        "INSERT INTO cp_run_event_cursor (run_id, next_idx) VALUES (%s, %s)",
                        (run_id, idx + 1),
                    )
            conn.commit()

    def list_events(self, run_id: str, since_index: int = 0) -> tuple[list[dict[str, Any]], int]:
        floor = max(0, int(since_index))
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT idx, event_type, payload, created_at
                    FROM cp_run_events
                    WHERE run_id = %s AND idx >= %s
                    ORDER BY idx ASC
                    """,
                    (run_id, floor),
                )
                rows = cur.fetchall()
                cur.execute("SELECT next_idx FROM cp_run_event_cursor WHERE run_id = %s", (run_id,))
                cursor_row = cur.fetchone()
            events = [
                {
                    "event_type": str(row[1]),
                    "payload": self._loads(row[2]) or {},
                    "created_at": self._normalize_dt(row[3]) or _utcnow(),
                    "index": int(row[0]),
                }
                for row in rows
            ]
            next_idx = int(cursor_row[0]) if cursor_row else 0
            return events, next_idx

    def claim_idempotency_key(
        self,
        key: str,
        *,
        fingerprint: str,
        run_id: str,
    ) -> tuple[bool, str | None]:
        resolved_run_id = str(run_id).strip()
        if not resolved_run_id:
            raise ValueError("run_id is required")
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT fingerprint, run_id FROM cp_run_idempotency WHERE idempotency_key = %s",
                    (key,),
                )
                row = cur.fetchone()
                if row:
                    same_payload = str(row[0]) == fingerprint
                    existing_run_id = str(row[1]) if same_payload else None
                    return False, existing_run_id
                cur.execute(
                    """
                    INSERT INTO cp_run_idempotency (idempotency_key, fingerprint, run_id)
                    VALUES (%s, %s, %s)
                    """,
                    (key, fingerprint, resolved_run_id),
                )
            conn.commit()
            return True, None
