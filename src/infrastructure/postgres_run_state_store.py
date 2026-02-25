"""Postgres-backed run state store.

Stores job payloads as JSON and events as append-only rows.
"""
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
                    CREATE TABLE IF NOT EXISTS run_state_jobs (
                        job_id TEXT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS run_state_events (
                        job_id TEXT NOT NULL,
                        idx INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (job_id, idx)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS run_state_event_cursor (
                        job_id TEXT PRIMARY KEY,
                        next_idx INTEGER NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS run_state_idempotency (
                        idempotency_key TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL,
                        job_id TEXT NOT NULL
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
            value = json.loads(payload)
            return value if isinstance(value, dict) else {}
        return {}

    def put_job(self, job: dict[str, Any]) -> None:
        job_id = str(job["job_id"])
        payload = deepcopy(job)
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO run_state_jobs (job_id, payload, updated_at)
                    VALUES (%s, %s::jsonb, NOW())
                    ON CONFLICT (job_id)
                    DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                    """,
                    (job_id, self._dumps(payload)),
                )
            conn.commit()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM run_state_jobs WHERE job_id=%s", (job_id,))
                row = cur.fetchone()
            if not row:
                return None
            return deepcopy(self._loads(row[0]))

    def patch_job(self, job_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM run_state_jobs WHERE job_id=%s", (job_id,))
                row = cur.fetchone()
                if not row:
                    return None
                payload = self._loads(row[0])
                payload.update(changes)
                payload["updated_at"] = _utcnow()
                cur.execute(
                    """
                    UPDATE run_state_jobs
                    SET payload=%s::jsonb, updated_at=NOW()
                    WHERE job_id=%s
                    """,
                    (self._dumps(payload), job_id),
                )
            conn.commit()
            return deepcopy(payload)

    def append_attempt(self, job_id: str, attempt: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            job = self.get_job(job_id)
            if not job:
                return None
            attempts = job.setdefault("attempts", [])
            attempts.append(attempt)
            self.put_job(job)
            return deepcopy(attempt)

    def patch_attempt(self, job_id: str, attempt_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            job = self.get_job(job_id)
            if not job:
                return None
            attempts = job.setdefault("attempts", [])
            for attempt in attempts:
                if attempt.get("attempt_id") == attempt_id:
                    attempt.update(changes)
                    job["updated_at"] = _utcnow()
                    self.put_job(job)
                    return deepcopy(attempt)
            return None

    def list_attempts(self, job_id: str) -> list[dict[str, Any]]:
        job = self.get_job(job_id)
        if not job:
            return []
        return deepcopy(job.get("attempts", []))

    def append_event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT next_idx FROM run_state_event_cursor WHERE job_id=%s FOR UPDATE",
                    (job_id,),
                )
                row = cur.fetchone()
                idx = int(row[0]) if row else 0
                cur.execute(
                    """
                    INSERT INTO run_state_events (job_id, idx, event_type, payload, created_at)
                    VALUES (%s, %s, %s, %s::jsonb, NOW())
                    """,
                    (job_id, idx, event_type, self._dumps(payload)),
                )
                if row:
                    cur.execute(
                        "UPDATE run_state_event_cursor SET next_idx=%s WHERE job_id=%s",
                        (idx + 1, job_id),
                    )
                else:
                    cur.execute(
                        "INSERT INTO run_state_event_cursor (job_id, next_idx) VALUES (%s, %s)",
                        (job_id, idx + 1),
                    )
            conn.commit()

    def list_events(self, job_id: str, since_index: int = 0) -> tuple[list[dict[str, Any]], int]:
        floor = max(0, int(since_index))
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT idx, event_type, payload, created_at
                    FROM run_state_events
                    WHERE job_id=%s AND idx >= %s
                    ORDER BY idx ASC
                    """,
                    (job_id, floor),
                )
                rows = cur.fetchall()
                cur.execute("SELECT next_idx FROM run_state_event_cursor WHERE job_id=%s", (job_id,))
                cursor_row = cur.fetchone()
            events = [
                {
                    "event_type": str(row[1]),
                    "payload": self._loads(row[2]),
                    "created_at": row[3].isoformat(),
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
        job_id: str,
    ) -> tuple[bool, str | None]:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT fingerprint, job_id FROM run_state_idempotency WHERE idempotency_key=%s",
                    (key,),
                )
                row = cur.fetchone()
                if row:
                    same_payload = str(row[0]) == fingerprint
                    existing_job_id = str(row[1]) if same_payload else None
                    return False, existing_job_id
                cur.execute(
                    """
                    INSERT INTO run_state_idempotency (idempotency_key, fingerprint, job_id)
                    VALUES (%s, %s, %s)
                    """,
                    (key, fingerprint, job_id),
                )
            conn.commit()
            return True, None

