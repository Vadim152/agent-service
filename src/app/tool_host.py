"""Minimal tool-host service for write operations."""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request, status

from agents import create_orchestrator
from api.schemas import ApplyFeatureRequest, ApplyFeatureResponse
from app.config import get_settings
from app.logging_config import LOG_LEVEL, get_logger, init_logging


settings = get_settings()
logger = get_logger(__name__)

app = FastAPI(title=f"{settings.app_name}-tool-host")


@app.on_event("startup")
async def on_startup() -> None:
    init_logging()
    app.state.orchestrator = create_orchestrator(settings)
    logger.info("[ToolHost] Service initialized")


@app.post("/internal/tools/save-feature", response_model=ApplyFeatureResponse)
async def save_feature(payload: ApplyFeatureRequest, request: Request) -> ApplyFeatureResponse:
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Tool host is not initialized")
    result = orchestrator.apply_feature(
        payload.project_root,
        payload.target_path,
        payload.feature_text,
        overwrite_existing=payload.overwrite_existing,
    )
    return ApplyFeatureResponse.model_validate(result)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.tool_host:app",
        host=settings.host,
        port=settings.port + 1,
        reload=False,
        log_level=logging.getLevelName(LOG_LEVEL).lower(),
    )


if __name__ == "__main__":
    main()

