"""Artifact index persistence for logical artifact URIs."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Protocol


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactIndexStore(Protocol):
    def put_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]: ...

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None: ...


class InMemoryArtifactIndexStore:
    """In-memory artifact index used in tests and local mode."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._items: dict[str, dict[str, Any]] = {}

    def put_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        payload = deepcopy(artifact)
        artifact_id = str(payload.get("artifactId") or payload.get("artifact_id") or "").strip()
        if not artifact_id:
            raise ValueError("artifactId is required")
        payload.setdefault("createdAt", _utcnow())
        with self._lock:
            self._items[artifact_id] = payload
        return deepcopy(payload)

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(artifact_id)
        return deepcopy(item) if item else None


class PostgresArtifactIndexStore:
    """Postgres-backed artifact index for logical artifact metadata."""

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
                "Postgres artifact index backend requires 'psycopg' package. Install dependency and retry."
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
                    CREATE TABLE IF NOT EXISTS cp_artifacts (
                        artifact_id TEXT PRIMARY KEY,
                        run_id TEXT NULL,
                        attempt_id TEXT NULL,
                        name TEXT NOT NULL,
                        uri TEXT NOT NULL,
                        media_type TEXT NOT NULL,
                        size_bytes BIGINT NOT NULL,
                        checksum_sha256 TEXT NOT NULL,
                        connector_source TEXT NOT NULL,
                        storage_path TEXT NULL,
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
            return deepcopy(payload)
        if isinstance(payload, str):
            loaded = json.loads(payload)
            return loaded if isinstance(loaded, dict) else {}
        return {}

    def put_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        payload = deepcopy(artifact)
        artifact_id = str(payload.get("artifactId") or payload.get("artifact_id") or "").strip()
        if not artifact_id:
            raise ValueError("artifactId is required")
        payload.setdefault("createdAt", _utcnow())
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cp_artifacts (
                        artifact_id,
                        run_id,
                        attempt_id,
                        name,
                        uri,
                        media_type,
                        size_bytes,
                        checksum_sha256,
                        connector_source,
                        storage_path,
                        created_at,
                        payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (artifact_id)
                    DO UPDATE SET
                        run_id = EXCLUDED.run_id,
                        attempt_id = EXCLUDED.attempt_id,
                        name = EXCLUDED.name,
                        uri = EXCLUDED.uri,
                        media_type = EXCLUDED.media_type,
                        size_bytes = EXCLUDED.size_bytes,
                        checksum_sha256 = EXCLUDED.checksum_sha256,
                        connector_source = EXCLUDED.connector_source,
                        storage_path = EXCLUDED.storage_path,
                        created_at = EXCLUDED.created_at,
                        payload = EXCLUDED.payload
                    """,
                    (
                        artifact_id,
                        payload.get("runId") or payload.get("run_id"),
                        payload.get("attemptId") or payload.get("attempt_id"),
                        str(payload.get("name") or ""),
                        str(payload.get("uri") or ""),
                        str(payload.get("mediaType") or payload.get("media_type") or "application/octet-stream"),
                        int(payload.get("size") or payload.get("sizeBytes") or 0),
                        str(payload.get("checksum") or payload.get("checksumSha256") or ""),
                        str(payload.get("connectorSource") or payload.get("connector_source") or "unknown"),
                        payload.get("storagePath") or payload.get("storage_path"),
                        str(payload.get("createdAt")),
                        self._dumps(payload),
                    ),
                )
            conn.commit()
        return payload

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload
                    FROM cp_artifacts
                    WHERE artifact_id = %s
                    """,
                    (artifact_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._loads(row[0])
