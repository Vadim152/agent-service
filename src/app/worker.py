"""Execution-plane worker entrypoint."""
from __future__ import annotations

import asyncio

from agents import create_orchestrator
from app.bootstrap import create_artifact_store, create_run_state_store
from app.config import get_settings
from app.logging_config import get_logger, init_logging
from infrastructure.job_queue import create_job_queue
from infrastructure.job_worker import JobQueueWorker
from self_healing.supervisor import ExecutionSupervisor


logger = get_logger(__name__)


async def _run_worker() -> None:
    settings = get_settings()
    init_logging()
    logger.info("[Worker] Initializing execution plane")

    queue = create_job_queue(
        backend=settings.queue_backend,
        redis_url=settings.redis_url,
        rabbitmq_url=settings.rabbitmq_url,
        queue_name=settings.queue_name,
    )
    orchestrator = create_orchestrator(settings)
    run_state_store = create_run_state_store(settings)
    artifact_store = create_artifact_store(settings)
    supervisor = ExecutionSupervisor(
        orchestrator=orchestrator,
        run_state_store=run_state_store,
        artifact_store=artifact_store,
    )
    worker = JobQueueWorker(
        queue=queue,
        supervisor=supervisor,
        run_state_store=run_state_store,
        concurrency=settings.worker_concurrency,
    )
    logger.info(
        "[Worker] Started (queue_backend=%s, queue_name=%s, concurrency=%s)",
        settings.queue_backend,
        settings.queue_name,
        settings.worker_concurrency,
    )
    await worker.run_forever()


def main() -> None:
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
