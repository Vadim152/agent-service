"""Connector-style tool-host service."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status

from agents import create_orchestrator
from api.schemas import ApplyFeatureRequest, ApplyFeatureResponse
from app.bootstrap import create_artifact_store, create_policy_store
from app.config import get_settings
from app.logging_config import LOG_LEVEL, get_logger, init_logging
from tool_host import (
    ArtifactGetRequest,
    ArtifactGetResponse,
    ArtifactPutRequest,
    ArtifactPutResponse,
    PatchApplyRequest,
    PatchApplyResponse,
    PatchProposeRequest,
    PatchProposeResponse,
    RepoReadRequest,
    RepoReadResponse,
    ToolHostService,
    ToolRegistryResponse,
)


settings = get_settings()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_logging()
    app.state.orchestrator = create_orchestrator(settings)
    app.state.policy_store = create_policy_store(settings)
    app.state.artifact_store = create_artifact_store(settings)
    app.state.tool_host_service = ToolHostService(
        orchestrator=app.state.orchestrator,
        artifact_store=app.state.artifact_store,
        policy_store=app.state.policy_store,
    )
    logger.info("[ToolHost] Service initialized")
    try:
        yield
    finally:
        embeddings_store = getattr(getattr(app.state, "orchestrator", None), "embeddings_store", None)
        if embeddings_store is not None and hasattr(embeddings_store, "close"):
            embeddings_store.close()


app = FastAPI(title=f"{settings.app_name}-tool-host", lifespan=lifespan)


def _get_service(request: Request) -> ToolHostService:
    service = getattr(request.app.state, "tool_host_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Tool host is not initialized")
    return service


@app.get("/internal/tools/registry", response_model=ToolRegistryResponse)
async def list_registry(request: Request) -> ToolRegistryResponse:
    service = _get_service(request)
    return ToolRegistryResponse(items=service.list_tools())


@app.post("/internal/tools/repo/read", response_model=RepoReadResponse)
async def repo_read(payload: RepoReadRequest, request: Request) -> RepoReadResponse:
    service = _get_service(request)
    try:
        return service.repo_read(
            project_root=payload.project_root,
            path=payload.path,
            include_content=payload.include_content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@app.post("/internal/tools/patch/propose", response_model=PatchProposeResponse)
async def patch_propose(payload: PatchProposeRequest, request: Request) -> PatchProposeResponse:
    service = _get_service(request)
    try:
        return service.patch_propose(
            project_root=payload.project_root,
            target_path=payload.target_path,
            feature_text=payload.feature_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@app.post("/internal/tools/artifacts/put", response_model=ArtifactPutResponse)
async def artifacts_put(payload: ArtifactPutRequest, request: Request) -> ArtifactPutResponse:
    service = _get_service(request)
    return service.artifact_put(
        run_id=payload.run_id,
        execution_id=payload.execution_id,
        attempt_id=payload.attempt_id,
        name=payload.name,
        content=payload.content,
        media_type=payload.media_type,
        connector_source=payload.connector_source,
    )


@app.post("/internal/tools/artifacts/get", response_model=ArtifactGetResponse)
async def artifacts_get(payload: ArtifactGetRequest, request: Request) -> ArtifactGetResponse:
    service = _get_service(request)
    try:
        return service.artifact_get(artifact_id=payload.artifact_id, uri=payload.uri)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@app.post("/internal/tools/patch/apply", response_model=PatchApplyResponse)
async def patch_apply(payload: PatchApplyRequest, request: Request) -> PatchApplyResponse:
    service = _get_service(request)
    try:
        return service.patch_apply(
            project_root=payload.project_root,
            target_path=payload.target_path,
            feature_text=payload.feature_text,
            overwrite_existing=payload.overwrite_existing,
            approval_id=payload.approval_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@app.post("/internal/tools/save-feature", response_model=ApplyFeatureResponse)
async def save_feature(payload: ApplyFeatureRequest, request: Request) -> ApplyFeatureResponse:
    service = _get_service(request)
    return service.save_feature_legacy(
        project_root=payload.project_root,
        target_path=payload.target_path,
        feature_text=payload.feature_text,
        overwrite_existing=payload.overwrite_existing,
    )


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
