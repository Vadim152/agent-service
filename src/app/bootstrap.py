"""Factories for control-plane and execution-plane components."""
from __future__ import annotations

from pathlib import Path

from app.config import Settings
from infrastructure.artifact_store import ArtifactStore
from infrastructure.job_dispatcher import (
    DispatchComponents,
    JobExecutionDispatcher,
    LocalJobExecutionDispatcher,
    QueueJobExecutionDispatcher,
)
from infrastructure.job_queue import create_job_queue
from infrastructure.postgres_run_state_store import PostgresRunStateStore
from infrastructure.run_state_store import RunStateStore
from infrastructure.tool_host_client import RemoteToolHostClient


def create_run_state_store(settings: Settings):
    backend = (settings.state_backend or "memory").strip().lower()
    if backend == "memory":
        return RunStateStore()
    if backend == "postgres":
        return PostgresRunStateStore(dsn=str(settings.postgres_dsn))
    raise ValueError(f"Unsupported state backend: {settings.state_backend}")


def create_artifact_store(settings: Settings) -> ArtifactStore:
    return ArtifactStore(Path(settings.artifacts_dir))


def create_job_dispatch_components(settings: Settings) -> DispatchComponents:
    execution_mode = (settings.execution_backend or "local").strip().lower()
    if execution_mode == "local":
        return DispatchComponents(dispatcher=LocalJobExecutionDispatcher(), queue=None)

    queue = create_job_queue(
        backend=settings.queue_backend,
        redis_url=settings.redis_url,
        queue_name=settings.queue_name,
    )
    dispatcher: JobExecutionDispatcher = QueueJobExecutionDispatcher(queue=queue)
    return DispatchComponents(dispatcher=dispatcher, queue=queue)


def create_tool_host_client(settings: Settings):
    mode = (settings.tool_host_mode or "local").strip().lower()
    if mode == "local":
        return None
    if mode == "remote":
        return RemoteToolHostClient(base_url=str(settings.tool_host_url))
    raise ValueError(f"Unsupported tool host mode: {settings.tool_host_mode}")
