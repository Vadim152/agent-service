"""Artifact storage with pluggable object backend and logical artifact index."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from infrastructure.artifact_index_store import ArtifactIndexStore
from infrastructure.object_storage import LocalObjectStorage, ObjectStorage


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ArtifactStore:
    """Stores artifacts in an object backend and can publish logical artifact URIs via an index."""

    def __init__(
        self,
        base_dir: Path,
        index_store: ArtifactIndexStore | None = None,
        object_storage: ObjectStorage | None = None,
    ) -> None:
        self._base_dir = base_dir
        self._index_store = index_store
        self._object_storage = object_storage or LocalObjectStorage(self._base_dir / "published")
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _run_dir(self, run_id: str, execution_id: str, attempt_id: str) -> Path:
        target = self._base_dir / run_id / execution_id / attempt_id
        target.mkdir(parents=True, exist_ok=True)
        return target

    def write_text(
        self, *, run_id: str, execution_id: str, attempt_id: str, name: str, content: str
    ) -> str:
        path = self._run_dir(run_id, execution_id, attempt_id) / name
        path.write_text(content, encoding="utf-8")
        return str(path)

    def write_json(
        self, *, run_id: str, execution_id: str, attempt_id: str, name: str, payload: dict[str, Any]
    ) -> str:
        path = self._run_dir(run_id, execution_id, attempt_id) / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def write_incident(self, run_id: str, payload: dict[str, Any]) -> str:
        target = self._base_dir / run_id
        target.mkdir(parents=True, exist_ok=True)
        stamp = _utcnow().strftime("%Y%m%d-%H%M%S")
        path = target / f"incident-{stamp}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def publish_json(
        self,
        *,
        name: str,
        payload: dict[str, Any],
        connector_source: str = "execution.artifacts",
        run_id: str | None = None,
        execution_id: str | None = None,
        attempt_id: str | None = None,
    ) -> dict[str, Any]:
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        return self.publish_text(
            name=name,
            content=content,
            media_type="application/json",
            connector_source=connector_source,
            run_id=run_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
        )

    def publish_incident(
        self,
        *,
        payload: dict[str, Any],
        run_id: str,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        return self.publish_json(
            name="incident.json",
            payload=payload,
            connector_source="execution.incident",
            run_id=run_id,
            execution_id=execution_id,
            attempt_id=None,
        )

    def publish_text(
        self,
        *,
        name: str,
        content: str,
        media_type: str = "text/plain",
        connector_source: str = "tool_host.artifacts",
        run_id: str | None = None,
        execution_id: str | None = None,
        attempt_id: str | None = None,
    ) -> dict[str, Any]:
        return self._publish_bytes(
            name=name,
            content=content.encode("utf-8"),
            media_type=media_type,
            connector_source=connector_source,
            run_id=run_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
        )

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        if self._index_store is None:
            return None
        metadata = self._index_store.get_artifact(artifact_id)
        if not metadata:
            return None
        metadata.update(self._object_storage.build_access_metadata(metadata))
        try:
            content = self._object_storage.read_text(metadata)
        except Exception:  # pragma: no cover - backend access failures are non-fatal for metadata lookup
            content = None
        if content is not None:
            metadata["content"] = content
        return metadata

    def get_artifact_bytes(self, artifact_id: str) -> tuple[dict[str, Any], bytes] | None:
        metadata = self.get_artifact(artifact_id)
        if metadata is None:
            return None
        try:
            payload = self._object_storage.read_bytes(metadata)
        except Exception:  # pragma: no cover - backend access failures are surfaced via endpoint response
            payload = None
        if payload is None:
            return None
        return metadata, payload

    def _publish_bytes(
        self,
        *,
        name: str,
        content: bytes,
        media_type: str,
        connector_source: str,
        run_id: str | None,
        execution_id: str | None,
        attempt_id: str | None,
    ) -> dict[str, Any]:
        artifact_id = str(uuid.uuid4())
        safe_name = Path(name).name or "artifact.bin"
        storage_name = f"{artifact_id}-{safe_name}"
        storage_metadata = self._object_storage.put_bytes(
            name=storage_name,
            content=content,
            media_type=media_type,
        )
        payload = {
            "artifactId": artifact_id,
            "runId": run_id,
            "executionId": execution_id,
            "attemptId": attempt_id,
            "name": safe_name,
            "uri": f"artifact://{artifact_id}",
            "mediaType": media_type,
            "size": len(content),
            "checksum": hashlib.sha256(content).hexdigest(),
            "connectorSource": connector_source,
            **storage_metadata,
            "createdAt": _utcnow().isoformat(),
        }
        if self._index_store is not None:
            self._index_store.put_artifact(payload)
        return payload
