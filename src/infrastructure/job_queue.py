"""Queue backends used to dispatch jobs to execution workers."""
from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Condition


logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobQueueError(RuntimeError):
    """Queue operation failure."""


@dataclass(frozen=True)
class JobEnvelope:
    job_id: str
    source: str = "jobs"
    enqueued_at: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "jobId": self.job_id,
            "source": self.source,
            "enqueuedAt": self.enqueued_at or _utcnow(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, str]) -> "JobEnvelope":
        return cls(
            job_id=str(payload.get("jobId", "")).strip(),
            source=str(payload.get("source", "jobs")).strip() or "jobs",
            enqueued_at=str(payload.get("enqueuedAt", "")).strip() or _utcnow(),
        )


class JobQueue:
    def enqueue(self, envelope: JobEnvelope) -> None:
        raise NotImplementedError

    def dequeue(self, timeout_s: float = 1.0) -> JobEnvelope | None:
        raise NotImplementedError


class LocalJobQueue(JobQueue):
    """In-process queue for single-process local mode."""

    def __init__(self) -> None:
        self._items: deque[JobEnvelope] = deque()
        self._cv = Condition()

    def enqueue(self, envelope: JobEnvelope) -> None:
        with self._cv:
            self._items.append(envelope)
            self._cv.notify()

    def dequeue(self, timeout_s: float = 1.0) -> JobEnvelope | None:
        timeout = max(0.0, float(timeout_s))
        with self._cv:
            if not self._items:
                self._cv.wait(timeout=timeout)
            if not self._items:
                return None
            return self._items.popleft()


class RedisJobQueue(JobQueue):
    """Redis-backed queue using LPUSH/BRPOP."""

    def __init__(self, *, redis_url: str, queue_name: str) -> None:
        try:
            import redis  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise JobQueueError(
                "Redis backend requires 'redis' package. Install dependency and retry."
            ) from exc

        self._queue_name = queue_name
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def enqueue(self, envelope: JobEnvelope) -> None:
        try:
            self._client.lpush(self._queue_name, json.dumps(envelope.to_dict(), ensure_ascii=False))
        except Exception as exc:  # pragma: no cover - network/backend failures
            raise JobQueueError(f"Failed to enqueue job {envelope.job_id}: {exc}") from exc

    def dequeue(self, timeout_s: float = 1.0) -> JobEnvelope | None:
        timeout_i = max(1, int(timeout_s))
        try:
            result = self._client.brpop(self._queue_name, timeout=timeout_i)
        except Exception as exc:  # pragma: no cover - network/backend failures
            raise JobQueueError(f"Failed to dequeue job: {exc}") from exc
        if not result:
            return None
        _, raw_payload = result
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise JobQueueError(f"Invalid queue payload: {raw_payload}") from exc
        envelope = JobEnvelope.from_dict(payload if isinstance(payload, dict) else {})
        if not envelope.job_id:
            logger.warning("Skipping queue item with empty jobId: %s", payload)
            return None
        return envelope


def create_job_queue(*, backend: str, redis_url: str, queue_name: str) -> JobQueue:
    mode = (backend or "local").strip().lower()
    if mode == "local":
        return LocalJobQueue()
    if mode == "redis":
        return RedisJobQueue(redis_url=redis_url, queue_name=queue_name)
    raise JobQueueError(f"Unsupported queue backend: {backend}")

