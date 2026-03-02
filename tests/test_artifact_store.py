from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from infrastructure.artifact_index_store import InMemoryArtifactIndexStore, PostgresArtifactIndexStore
from infrastructure.artifact_store import ArtifactStore


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.now(timezone.utc)


class _FakePostgresDb:
    def __init__(self) -> None:
        self.artifacts: dict[str, dict[str, Any]] = {}


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

        if sql.startswith("INSERT INTO cp_artifacts "):
            (
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
                payload_raw,
            ) = args
            self._db.artifacts[str(artifact_id)] = {
                "artifact_id": str(artifact_id),
                "run_id": run_id,
                "attempt_id": attempt_id,
                "name": str(name),
                "uri": str(uri),
                "media_type": str(media_type),
                "size_bytes": int(size_bytes),
                "checksum_sha256": str(checksum_sha256),
                "connector_source": str(connector_source),
                "storage_path": storage_path,
                "created_at": _to_datetime(created_at),
                "payload": json.loads(str(payload_raw)),
            }
            return

        if sql.startswith("SELECT payload FROM cp_artifacts WHERE artifact_id = %s"):
            row = self._db.artifacts.get(str(args[0]))
            if row:
                self._results = [(row["payload"],)]
            return

        raise AssertionError(f"Unsupported SQL in fake cursor: {sql}")

    def fetchone(self) -> tuple[Any, ...] | None:
        if not self._results:
            return None
        return self._results.pop(0)


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


class _FakeS3ObjectStorage:
    def __init__(self) -> None:
        self._items: dict[str, bytes] = {}

    def put_bytes(self, *, name: str, content: bytes, media_type: str) -> dict[str, Any]:
        self._items[name] = content
        return {
            "storageBackend": "s3",
            "storageBucket": "artifacts",
            "storageKey": name,
            "storagePath": f"s3://artifacts/{name}",
            "signedUrl": f"https://minio.local/artifacts/{name}?signature=test",
            "mediaType": media_type,
        }

    def read_text(self, metadata: dict[str, Any]) -> str | None:
        key = str(metadata.get("storageKey") or "")
        raw = self._items.get(key)
        return raw.decode("utf-8") if raw is not None else None

    def build_access_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        key = str(metadata.get("storageKey") or "")
        return {
            "storageBackend": "s3",
            "storageBucket": "artifacts",
            "storageKey": key,
            "storagePath": f"s3://artifacts/{key}",
            "signedUrl": f"https://minio.local/artifacts/{key}?signature=test",
        }


def test_artifact_store_publish_and_lookup_round_trip(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, index_store=InMemoryArtifactIndexStore())

    published = store.publish_text(
        name="stdout.log",
        content="ok",
        media_type="text/plain",
        connector_source="tool_host.artifacts",
        run_id="run-1",
        attempt_id="attempt-1",
    )

    assert published["uri"].startswith("artifact://")
    assert published["size"] == 2
    assert Path(str(published["storagePath"])).exists()

    loaded = store.get_artifact(str(published["artifactId"]))
    assert loaded is not None
    assert loaded["content"] == "ok"
    assert loaded["runId"] == "run-1"


def test_postgres_artifact_index_store_round_trip(monkeypatch) -> None:
    db = _FakePostgresDb()
    monkeypatch.setattr(PostgresArtifactIndexStore, "_load_psycopg", staticmethod(lambda: _FakePsycopg(db)))
    store = PostgresArtifactIndexStore(dsn="postgresql://local/test")

    payload = store.put_artifact(
        {
            "artifactId": "artifact-1",
            "runId": "run-1",
            "attemptId": "attempt-1",
            "name": "stdout.log",
            "uri": "artifact://artifact-1",
            "mediaType": "text/plain",
            "size": 2,
            "checksum": "abc123",
            "connectorSource": "tool_host.artifacts",
            "storagePath": "C:/tmp/stdout.log",
        }
    )

    assert payload["artifactId"] == "artifact-1"
    loaded = store.get_artifact("artifact-1")
    assert loaded is not None
    assert loaded["uri"] == "artifact://artifact-1"


def test_artifact_store_supports_s3_style_object_storage(tmp_path: Path) -> None:
    store = ArtifactStore(
        tmp_path / "virtual-artifacts",
        index_store=InMemoryArtifactIndexStore(),
        object_storage=_FakeS3ObjectStorage(),
    )

    published = store.publish_text(
        name="stdout.log",
        content="ok",
        media_type="text/plain",
        connector_source="tool_host.artifacts",
        run_id="run-1",
        attempt_id="attempt-1",
    )

    assert published["storageBackend"] == "s3"
    assert str(published["signedUrl"]).startswith("https://minio.local/")

    loaded = store.get_artifact(str(published["artifactId"]))
    assert loaded is not None
    assert loaded["storageBackend"] == "s3"
    assert loaded["storageBucket"] == "artifacts"
    assert loaded["content"] == "ok"
