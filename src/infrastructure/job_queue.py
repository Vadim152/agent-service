"""Queue backends used to dispatch runs to execution workers."""
from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Condition
from typing import Protocol


logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobQueueError(RuntimeError):
    """Queue operation failure."""


@dataclass(frozen=True)
class JobEnvelope:
    run_id: str
    source: str = "runs"
    enqueued_at: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "runId": self.run_id,
            "source": self.source,
            "enqueuedAt": self.enqueued_at or _utcnow(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, str]) -> "JobEnvelope":
        return cls(
            run_id=str(payload.get("runId") or "").strip(),
            source=str(payload.get("source", "runs")).strip() or "runs",
            enqueued_at=str(payload.get("enqueuedAt", "")).strip() or _utcnow(),
        )


class JobQueue:
    def enqueue(self, envelope: JobEnvelope) -> None:
        raise NotImplementedError

    def receive(self, timeout_s: float = 1.0) -> "JobLease | None":
        raise NotImplementedError


class JobLease(Protocol):
    envelope: JobEnvelope

    def ack(self) -> None: ...

    def reject(self, *, requeue: bool) -> None: ...


@dataclass
class LocalJobLease:
    envelope: JobEnvelope

    def ack(self) -> None:
        return None

    def reject(self, *, requeue: bool) -> None:
        _ = requeue
        return None


class LocalJobQueue(JobQueue):
    """In-process queue for single-process local mode."""

    def __init__(self) -> None:
        self._items: deque[JobEnvelope] = deque()
        self._cv = Condition()

    def enqueue(self, envelope: JobEnvelope) -> None:
        with self._cv:
            self._items.append(envelope)
            self._cv.notify()

    def receive(self, timeout_s: float = 1.0) -> JobLease | None:
        timeout = max(0.0, float(timeout_s))
        with self._cv:
            if not self._items:
                self._cv.wait(timeout=timeout)
            if not self._items:
                return None
            envelope = self._items.popleft()
        return LocalJobLease(envelope=envelope)


@dataclass
class RedisJobLease:
    envelope: JobEnvelope
    queue: "RedisJobQueue"

    def ack(self) -> None:
        return None

    def reject(self, *, requeue: bool) -> None:
        if requeue:
            self.queue.enqueue(self.envelope)


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
            raise JobQueueError(f"Failed to enqueue run {envelope.run_id}: {exc}") from exc

    def receive(self, timeout_s: float = 1.0) -> JobLease | None:
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
        if not envelope.run_id:
            logger.warning("Skipping queue item with empty runId: %s", payload)
            return None
        return RedisJobLease(envelope=envelope, queue=self)


@dataclass
class RabbitMqJobLease:
    envelope: JobEnvelope
    queue: "RabbitMqJobQueue"
    delivery_tag: int
    _settled: bool = False

    def ack(self) -> None:
        if self._settled:
            return
        self.queue._ack(self.delivery_tag)
        self._settled = True

    def reject(self, *, requeue: bool) -> None:
        if self._settled:
            return
        self.queue._reject(self.delivery_tag, requeue=requeue)
        self._settled = True


class RabbitMqJobQueue(JobQueue):
    """RabbitMQ-backed queue using manual ack/nack semantics."""

    def __init__(self, *, rabbitmq_url: str, queue_name: str) -> None:
        try:
            import pika  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise JobQueueError(
                "RabbitMQ backend requires 'pika' package. Install dependency and retry."
            ) from exc

        self._pika = pika
        self._queue_name = queue_name
        self._parameters = pika.URLParameters(rabbitmq_url)
        self._connection = None
        self._channel = None
        self._connect()

    def _connect(self) -> None:
        self._connection = self._pika.BlockingConnection(self._parameters)
        self._channel = self._connection.channel()
        self._channel.queue_declare(queue=self._queue_name, durable=True)

    def _ensure_channel(self):
        if self._connection is None or self._connection.is_closed:
            self._connect()
        elif self._channel is None or self._channel.is_closed:
            self._channel = self._connection.channel()
            self._channel.queue_declare(queue=self._queue_name, durable=True)
        return self._channel

    def enqueue(self, envelope: JobEnvelope) -> None:
        try:
            channel = self._ensure_channel()
            channel.basic_publish(
                exchange="",
                routing_key=self._queue_name,
                body=json.dumps(envelope.to_dict(), ensure_ascii=False).encode("utf-8"),
                properties=self._pika.BasicProperties(delivery_mode=2),
            )
        except Exception as exc:  # pragma: no cover - network/backend failures
            raise JobQueueError(f"Failed to enqueue run {envelope.run_id}: {exc}") from exc

    def receive(self, timeout_s: float = 1.0) -> JobLease | None:
        _ = timeout_s
        try:
            channel = self._ensure_channel()
            method_frame, _, body = channel.basic_get(queue=self._queue_name, auto_ack=False)
        except Exception as exc:  # pragma: no cover - network/backend failures
            raise JobQueueError(f"Failed to dequeue job: {exc}") from exc
        if method_frame is None or not body:
            return None
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            channel.basic_nack(method_frame.delivery_tag, requeue=False)
            raise JobQueueError("Invalid RabbitMQ queue payload") from exc
        envelope = JobEnvelope.from_dict(payload if isinstance(payload, dict) else {})
        if not envelope.run_id:
            channel.basic_nack(method_frame.delivery_tag, requeue=False)
            logger.warning("Skipping queue item with empty runId: %s", payload)
            return None
        return RabbitMqJobLease(
            envelope=envelope,
            queue=self,
            delivery_tag=int(method_frame.delivery_tag),
        )

    def _ack(self, delivery_tag: int) -> None:
        channel = self._ensure_channel()
        channel.basic_ack(delivery_tag)

    def _reject(self, delivery_tag: int, *, requeue: bool) -> None:
        channel = self._ensure_channel()
        channel.basic_nack(delivery_tag, requeue=requeue)


def create_job_queue(*, backend: str, redis_url: str, rabbitmq_url: str, queue_name: str) -> JobQueue:
    mode = (backend or "local").strip().lower()
    if mode == "local":
        return LocalJobQueue()
    if mode == "redis":
        return RedisJobQueue(redis_url=redis_url, queue_name=queue_name)
    if mode == "rabbitmq":
        return RabbitMqJobQueue(rabbitmq_url=rabbitmq_url, queue_name=queue_name)
    raise JobQueueError(f"Unsupported queue backend: {backend}")
