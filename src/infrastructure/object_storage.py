"""Object storage backends for artifact blobs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ObjectStorage(Protocol):
    def put_bytes(self, *, name: str, content: bytes, media_type: str) -> dict[str, Any]: ...

    def read_bytes(self, metadata: dict[str, Any]) -> bytes | None: ...

    def read_text(self, metadata: dict[str, Any]) -> str | None: ...

    def build_access_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]: ...


class LocalObjectStorage:
    """Filesystem-backed object storage used in local development and tests."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, *, name: str, content: bytes, media_type: str) -> dict[str, Any]:
        safe_name = Path(name).name or "artifact.bin"
        path = self._base_dir / safe_name
        path.write_bytes(content)
        return {
            "storageBackend": "local",
            "storagePath": str(path),
            "mediaType": media_type,
        }

    def read_text(self, metadata: dict[str, Any]) -> str | None:
        raw = self.read_bytes(metadata)
        if raw is None:
            return None
        return raw.decode("utf-8")

    def read_bytes(self, metadata: dict[str, Any]) -> bytes | None:
        storage_path = metadata.get("storagePath") or metadata.get("storage_path")
        if not isinstance(storage_path, str) or not storage_path:
            return None
        path = Path(storage_path)
        if not path.exists() or not path.is_file():
            return None
        return path.read_bytes()

    def build_access_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        return {
            "storageBackend": "local",
            "storagePath": metadata.get("storagePath") or metadata.get("storage_path"),
            "signedUrl": None,
        }


class S3ObjectStorage:
    """S3-compatible object storage using boto3-compatible clients."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key_id: str | None,
        secret_access_key: str | None,
        session_token: str | None,
        key_prefix: str = "",
        presign_expiry_s: int = 3600,
        addressing_style: str = "path",
    ) -> None:
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._region = region
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._session_token = session_token
        self._key_prefix = key_prefix.strip("/")
        self._presign_expiry_s = presign_expiry_s
        self._addressing_style = addressing_style
        self._client = self._build_client()

    @staticmethod
    def _load_boto3():
        try:
            import boto3  # type: ignore
            from botocore.config import Config  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "S3 artifact storage backend requires 'boto3'. Install dependency and retry."
            ) from exc
        return boto3, Config

    def _build_client(self):
        boto3, Config = self._load_boto3()
        return boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
            aws_session_token=self._session_token,
            config=Config(signature_version="s3v4", s3={"addressing_style": self._addressing_style}),
        )

    def _object_key(self, name: str) -> str:
        safe_name = Path(name).name or "artifact.bin"
        if not self._key_prefix:
            return safe_name
        return f"{self._key_prefix}/{safe_name}"

    def put_bytes(self, *, name: str, content: bytes, media_type: str) -> dict[str, Any]:
        key = self._object_key(name)
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=content,
            ContentType=media_type,
        )
        return {
            "storageBackend": "s3",
            "storageBucket": self._bucket,
            "storageKey": key,
            "storagePath": f"s3://{self._bucket}/{key}",
            "mediaType": media_type,
            "signedUrl": self._build_signed_url(key),
        }

    def _build_signed_url(self, key: str) -> str:
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=self._presign_expiry_s,
            )
        )

    def read_text(self, metadata: dict[str, Any]) -> str | None:
        raw = self.read_bytes(metadata)
        if raw is None:
            return None
        return raw.decode("utf-8")

    def read_bytes(self, metadata: dict[str, Any]) -> bytes | None:
        key = metadata.get("storageKey") or metadata.get("storage_key")
        if not isinstance(key, str) or not key:
            return None
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body = response.get("Body")
        if body is None:
            return None
        return body.read()

    def build_access_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        key = metadata.get("storageKey") or metadata.get("storage_key")
        signed_url = None
        if isinstance(key, str) and key:
            signed_url = self._build_signed_url(key)
        return {
            "storageBackend": "s3",
            "storagePath": metadata.get("storagePath") or metadata.get("storage_path"),
            "storageBucket": self._bucket,
            "storageKey": key,
            "signedUrl": signed_url,
        }
