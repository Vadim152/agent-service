"""Точка входа в приложение agent-service."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.logging_config import LOG_LEVEL, get_logger, init_logging
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
    app.state.is_ready = False
    app.state.init_error: str | None = None

    logger.info("[Startup] Инициализация оркестратора")
    try:
        global orchestrator
        orchestrator = create_orchestrator(settings)
        app.state.orchestrator = orchestrator
        logger.info("[Startup] Оркестратор создан")
    except Exception as exc:  # pragma: no cover - ранняя инициализация
        app.state.init_error = f"Ошибка создания оркестратора: {exc}"
        logger.exception("[Startup] Не удалось создать оркестратор")
        return

    init_steps = (
        ("Проверка учётных данных внешних сервисов", _validate_external_credentials),
        ("Предзагрузка индекса шагов", _preload_step_indexes),
        ("Прогрев эмбеддингового хранилища", _warm_embeddings_store),
    )

    for description, handler in init_steps:
        logger.info("[Startup] %s", description)
        try:
            handler(app, orchestrator)
            logger.info("[Startup] %s завершена успешно", description)
        except Exception as exc:  # pragma: no cover - ранняя инициализация
            app.state.init_error = f"{description}: {exc}"
            logger.exception("[Startup] Шаг инициализации завершился с ошибкой")
            return

    app.state.is_ready = True
    logger.info(
        "Сервис %s запущен на %s:%s и готов к работе", settings.app_name, settings.host, settings.port
    )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Действия при остановке приложения."""

    logger.info("Сервис %s останавливается", settings.app_name)


@app.get("/health", summary="Проверка доступности сервиса")
async def healthcheck() -> dict[str, str]:
    """Простой health-endpoint."""

    is_ready = getattr(app.state, "is_ready", False)
    error = getattr(app.state, "init_error", None)
    status = "ok" if is_ready else "initializing"

    payload = {"status": status, "service": settings.app_name}
    if error:
        payload["error"] = error

    if not is_ready:
        return JSONResponse(status_code=503, content=payload)

    return payload


app.include_router(api_router, prefix=settings.api_prefix)


def _validate_external_credentials(_: FastAPI, orchestrator) -> None:
    llm_client = getattr(orchestrator, "llm_client", None)
    if not llm_client:
        logger.warning("[Startup] LLM клиент не сконфигурирован")
        return

    logger.debug("[Startup] Проверка LLM credentials")
    try:
        llm_client._ensure_credentials()  # type: ignore[attr-defined]
    except Exception as exc:
        raise RuntimeError("Учётные данные LLM не заданы или недоступны") from exc

    has_custom_creds = any(
        getattr(settings, field)
        for field in ("llm_api_key", "gigachat_client_id", "gigachat_client_secret")
    )
    if not has_custom_creds and getattr(llm_client, "allow_fallback", False):
        logger.warning(
            "[Startup] Учётные данные LLM отсутствуют, будет использован fallback режим"
        )


def _preload_step_indexes(_: FastAPI, orchestrator) -> None:
    step_index_store = getattr(orchestrator, "step_index_store", None)
    if not step_index_store:
        logger.warning("[Startup] Хранилище индекса шагов не найдено")
        return

    index_dir: Path | None = getattr(step_index_store, "_index_dir", None)
    if not index_dir:
        logger.warning("[Startup] Каталог индекса шагов не задан")
        return

    index_dir.mkdir(parents=True, exist_ok=True)
    total_steps = 0
    for project_dir in index_dir.iterdir():
        if not project_dir.is_dir():
            continue

        steps_file = project_dir / "steps.json"
        if not steps_file.exists():
            continue

        try:
            data = json.loads(steps_file.read_text(encoding="utf-8"))
            total_steps += len(data.get("steps", []))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[Startup] Не удалось прочитать индекс %s: %s", steps_file, exc)

    logger.info("[Startup] Предзагружено шагов из индекса: %s", total_steps)


def _warm_embeddings_store(_: FastAPI, orchestrator) -> None:
    embeddings_store = getattr(orchestrator, "embeddings_store", None)
    if not embeddings_store:
        logger.warning("[Startup] Эмбеддинговое хранилище не найдено")
        return

    client = getattr(embeddings_store, "_client", None)
    if not client:
        logger.warning("[Startup] Клиент эмбеддингов не инициализирован")
        return

    try:
        collections = client.list_collections()
    except Exception as exc:  # pragma: no cover - внешнее хранилище
        raise RuntimeError("Не удалось инициализировать эмбеддинговое хранилище") from exc

    logger.info("[Startup] Эмбеддинговое хранилище готово, коллекций: %s", len(collections))


def main() -> None:
    """Запустить backend-сервис."""

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=logging.getLevelName(LOG_LEVEL).lower(),
    )


if __name__ == "__main__":
    main()
