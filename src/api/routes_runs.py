"""Run API: plugin-aware control-plane endpoints and SSE stream."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse, StreamingResponse

from api.run_schemas import (
    RunArtifactsResponse,
    RunArtifactDto,
    RunAttemptsResponse,
    RunCancelResponse,
    RunCreateRequest,
    RunCreateResponse,
    RunEventDto,
    RunResultResponse,
    RunStatusResponse,
)
from api.schemas import FeatureResultDto, RunAttemptDto
from runtime.run_service import RunService


router = APIRouter(prefix="/runs", tags=["runs"])


def _get_run_service(request: Request) -> RunService:
    service = getattr(request.app.state, "run_service", None)
    if service is not None:
        return service

    run_state_store = getattr(request.app.state, "run_state_store", None)
    if run_state_store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Run control plane is not initialized")

    return RunService(
        run_state_store=run_state_store,
        supervisor=getattr(request.app.state, "execution_supervisor", None),
        dispatcher=getattr(request.app.state, "job_dispatcher", None),
        task_registry=getattr(request.app.state, "task_registry", None),
    )


def _normalize_run_payload(payload: dict[str, object]) -> dict[str, object]:
    return dict(payload)


def _get_artifact_store(request: Request):
    return getattr(request.app.state, "artifact_store", None)


def _resolve_artifact(uri: str, request: Request) -> dict[str, object] | None:
    if not uri.startswith("artifact://"):
        return None
    artifact_store = _get_artifact_store(request)
    if artifact_store is None:
        return None
    artifact_id = uri[len("artifact://") :]
    resolved = artifact_store.get_artifact(artifact_id)
    if not isinstance(resolved, dict):
        return None
    return resolved


def _collect_artifacts(item: dict[str, object], request: Request | None = None) -> list[RunArtifactDto]:
    artifacts: list[RunArtifactDto] = []
    for attempt in item.get("attempts", []):
        attempt_id = attempt.get("attempt_id")
        attempt_artifacts = attempt.get("artifacts", {})
        if not isinstance(attempt_artifacts, dict):
            continue
        for name, uri in attempt_artifacts.items():
            if not uri:
                continue
            resolved = _resolve_artifact(str(uri), request) if request is not None else None
            artifacts.append(
                RunArtifactDto(
                    artifactId=resolved.get("artifactId") if resolved else None,
                    name=str(resolved.get("name") or name) if resolved else str(name),
                    uri=str(uri),
                    attemptId=attempt_id,
                    mediaType=resolved.get("mediaType") if resolved else None,
                    size=resolved.get("size") if resolved else None,
                    checksum=resolved.get("checksum") if resolved else None,
                    connectorSource=resolved.get("connectorSource") if resolved else None,
                    storageBackend=resolved.get("storageBackend") if resolved else None,
                    storagePath=resolved.get("storagePath") if resolved else None,
                    storageBucket=resolved.get("storageBucket") if resolved else None,
                    storageKey=resolved.get("storageKey") if resolved else None,
                    signedUrl=resolved.get("signedUrl") if resolved else None,
                    content=resolved.get("content") if resolved else None,
                )
            )
    incident_uri = item.get("incident_uri")
    if incident_uri:
        resolved = _resolve_artifact(str(incident_uri), request) if request is not None else None
        artifacts.append(
            RunArtifactDto(
                artifactId=resolved.get("artifactId") if resolved else None,
                name=str(resolved.get("name") or "incident") if resolved else "incident",
                uri=str(incident_uri),
                attemptId=None,
                mediaType=resolved.get("mediaType") if resolved else None,
                size=resolved.get("size") if resolved else None,
                checksum=resolved.get("checksum") if resolved else None,
                connectorSource=resolved.get("connectorSource") if resolved else None,
                storageBackend=resolved.get("storageBackend") if resolved else None,
                storagePath=resolved.get("storagePath") if resolved else None,
                storageBucket=resolved.get("storageBucket") if resolved else None,
                storageKey=resolved.get("storageKey") if resolved else None,
                signedUrl=resolved.get("signedUrl") if resolved else None,
                content=resolved.get("content") if resolved else None,
            )
        )
    return artifacts


def _get_run_artifact(run_id: str, artifact_id: str, request: Request) -> dict[str, object]:
    run_service = _get_run_service(request)
    item = run_service.get_run(run_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run not found: {run_id}")
    artifacts = _collect_artifacts(item, request)
    for artifact in artifacts:
        if artifact.artifact_id == artifact_id:
            return artifact.model_dump(by_alias=True, mode="json")
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Artifact not found for run: {artifact_id}",
    )


@router.post("", response_model=RunCreateResponse)
async def create_run(payload: RunCreateRequest, request: Request) -> RunCreateResponse:
    run_service = _get_run_service(request)
    created = run_service.create_run(
        plugin=payload.plugin,
        project_root=payload.project_root,
        input_payload=dict(payload.input),
        session_id=payload.session_id,
        profile=payload.profile,
        source=payload.source,
        priority=payload.priority,
        idempotency_key=request.headers.get("Idempotency-Key"),
    )
    return RunCreateResponse(
        runId=created["run_id"],
        status=created["status"],
        sessionId=created.get("session_id"),
        plugin=created["plugin"],
    )


@router.get("/{run_id}", response_model=RunStatusResponse)
async def get_run(run_id: str, request: Request) -> RunStatusResponse:
    run_service = _get_run_service(request)
    item = run_service.get_run(run_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run not found: {run_id}")

    return RunStatusResponse(
        runId=run_id,
        sessionId=item.get("session_id"),
        plugin=str(item.get("plugin", "testgen")),
        runtime=item.get("runtime"),
        backend=item.get("backend"),
        status=str(item.get("status", "queued")),
        source=item.get("source"),
        currentAttempt=len(item.get("attempts", [])),
        executionId=item.get("execution_id") or item.get("run_id"),
        backendRunId=item.get("backend_run_id"),
        backendSessionId=item.get("backend_session_id"),
        lastSyncedAt=datetime.fromisoformat(item["last_synced_at"]) if item.get("last_synced_at") else None,
        incidentUri=item.get("incident_uri"),
        startedAt=datetime.fromisoformat(item["started_at"]) if item.get("started_at") else None,
        finishedAt=datetime.fromisoformat(item["finished_at"]) if item.get("finished_at") else None,
    )


@router.get("/{run_id}/attempts", response_model=RunAttemptsResponse)
async def get_run_attempts(run_id: str, request: Request) -> RunAttemptsResponse:
    run_service = _get_run_service(request)
    item = run_service.get_run(run_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run not found: {run_id}")

    attempts = [RunAttemptDto.model_validate(attempt) for attempt in item.get("attempts", [])]
    return RunAttemptsResponse(runId=run_id, plugin=str(item.get("plugin", "testgen")), attempts=attempts)


@router.get("/{run_id}/result", response_model=RunResultResponse)
async def get_run_result(run_id: str, request: Request) -> RunResultResponse:
    run_service = _get_run_service(request)
    item = run_service.get_run(run_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run not found: {run_id}")

    result_payload = item.get("result")
    if result_payload is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Result is not ready for run: {run_id}")

    output: FeatureResultDto | dict[str, object]
    if str(item.get("plugin", "testgen")) == "testgen":
        output = FeatureResultDto.model_validate(result_payload)
    else:
        output = result_payload if isinstance(result_payload, dict) else {"value": result_payload}

    attempts = [RunAttemptDto.model_validate(attempt) for attempt in item.get("attempts", [])]
    artifacts = _collect_artifacts(item, request)
    return RunResultResponse(
        runId=run_id,
        sessionId=item.get("session_id"),
        plugin=str(item.get("plugin", "testgen")),
        runtime=item.get("runtime"),
        backend=item.get("backend"),
        status=str(item.get("status", "queued")),
        source=item.get("source"),
        backendRunId=item.get("backend_run_id"),
        backendSessionId=item.get("backend_session_id"),
        lastSyncedAt=datetime.fromisoformat(item["last_synced_at"]) if item.get("last_synced_at") else None,
        incidentUri=item.get("incident_uri"),
        startedAt=datetime.fromisoformat(item["started_at"]) if item.get("started_at") else None,
        finishedAt=datetime.fromisoformat(item["finished_at"]) if item.get("finished_at") else None,
        output=output,
        attempts=attempts,
        artifacts=artifacts,
    )


@router.post("/{run_id}/cancel", response_model=RunCancelResponse)
async def cancel_run(run_id: str, request: Request) -> RunCancelResponse:
    run_service = _get_run_service(request)
    result = run_service.cancel_run(run_id)
    return RunCancelResponse(
        runId=result["run_id"],
        status=result["status"],
        cancelRequested=result["cancel_requested"],
        effectiveStatus=result["effective_status"],
    )


@router.get("/{run_id}/artifacts", response_model=RunArtifactsResponse)
async def list_run_artifacts(run_id: str, request: Request) -> RunArtifactsResponse:
    run_service = _get_run_service(request)
    item = run_service.get_run(run_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run not found: {run_id}")
    return RunArtifactsResponse(runId=run_id, items=_collect_artifacts(item, request))


@router.get("/{run_id}/artifacts/{artifact_id}/content")
async def get_run_artifact_content(
    run_id: str,
    artifact_id: str,
    request: Request,
    download: bool = Query(default=False),
):
    artifact = _get_run_artifact(run_id, artifact_id, request)
    artifact_store = _get_artifact_store(request)
    if artifact_store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Artifact store is not initialized")

    resolved = artifact_store.get_artifact_bytes(artifact_id)
    if resolved is None:
        signed_url = artifact.get("signedUrl")
        if isinstance(signed_url, str) and signed_url:
            return RedirectResponse(url=signed_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact content not found: {artifact_id}")

    metadata, payload = resolved
    filename = str(metadata.get("name") or artifact.get("name") or artifact_id)
    disposition = "attachment" if download else "inline"
    headers = {"Content-Disposition": f'{disposition}; filename="{filename}"'}
    return Response(
        content=payload,
        media_type=str(metadata.get("mediaType") or "application/octet-stream"),
        headers=headers,
    )


@router.get("/{run_id}/events")
async def stream_run_events(run_id: str, request: Request, fromIndex: int = 0):
    run_service = _get_run_service(request)
    if not run_service.get_run(run_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run not found: {run_id}")

    async def event_stream():
        idx = max(0, fromIndex)
        loop = asyncio.get_running_loop()
        heartbeat_interval_s = 2.0
        last_emit_ts = loop.time()
        while True:
            if await request.is_disconnected():
                return
            events, idx = run_service.list_events(run_id, idx)
            if not events:
                now = loop.time()
                if now - last_emit_ts >= heartbeat_interval_s:
                    payload = RunEventDto(
                        eventType="heartbeat",
                        payload={"runId": run_id},
                        createdAt=datetime.now(timezone.utc),
                        index=idx,
                    ).model_dump(by_alias=True, mode="json")
                    yield f"event: heartbeat\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    last_emit_ts = now
                await asyncio.sleep(0.2)
                continue

            for event in events:
                payload = RunEventDto(
                    eventType=event["event_type"],
                    payload=_normalize_run_payload(event["payload"]),
                    createdAt=datetime.fromisoformat(event["created_at"]),
                    index=event["index"],
                ).model_dump(by_alias=True, mode="json")
                yield f"event: {payload['eventType']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_emit_ts = loop.time()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
