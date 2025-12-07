"""Точка входа в приложение agent-service."""
from __future__ import annotations

import logging
from fastapi import FastAPI

from app.config import get_settings
from app.logging_config import get_logger, init_logging
from api import router as api_router
from agents import create_orchestrator

settings = get_settings()
logger = get_logger(__name__)
orchestrator = None


app = FastAPI(title=settings.app_name)


@app.on_event("startup")
async def on_startup() -> None:
    """Действия при запуске приложения."""

    init_logging()
    global orchestrator
    orchestrator = create_orchestrator(settings)
    app.state.orchestrator = orchestrator
    logger.info("Сервис %s запущен на %s:%s", settings.app_name, settings.host, settings.port)
    # TODO: Инициализировать агентов и инфраструктурные ресурсы


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Действия при остановке приложения."""

    logger.info("Сервис %s останавливается", settings.app_name)


@app.get("/health", summary="Проверка доступности сервиса")
async def healthcheck() -> dict[str, str]:
    """Простой health-endpoint."""

    return {"status": "ok", "service": settings.app_name}


app.include_router(api_router, prefix=settings.api_prefix)


def main() -> None:
    """Запустить backend-сервис."""

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=logging.getLevelName(logger.level).lower(),
    )


if __name__ == "__main__":
    main()
