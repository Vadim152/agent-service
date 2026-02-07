"""Job API: единая control-plane точка входа + SSE событий."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.schemas import (
    JobAttemptsResponse,
    JobCancelResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobEventDto,
    JobFeatureResultDto,
    JobResultResponse,
    JobStatusResponse,
    RunAttemptDto,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("", response_model=JobCreateResponse)
async def create_job(payload: JobCreateRequest, request: Request) -> JobCreateResponse:
    supervisor = getattr(request.app.state, "execution_supervisor", None)
    run_state_store = getattr(request.app.state, "run_state_store", None)
    if not supervisor or not run_state_store:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Job control plane is not initialized")

    job_id = str(uuid.uuid4())
    run_state_store.put_job(
        {
            "job_id": job_id,
            "status": "queued",
            "project_root": payload.project_root,
            "test_case_text": payload.test_case_text,
            "target_path": payload.target_path,
            "create_file": payload.create_file,
            "overwrite_existing": payload.overwrite_existing,
            "language": payload.language,
            "profile": payload.profile,
            "source": payload.source,
            "started_at": _utcnow(),
            "updated_at": _utcnow(),
            "attempts": [],
            "result": None,
        }
    )
    run_state_store.append_event(job_id, "job.queued", {"jobId": job_id, "source": payload.source})
    asyncio.create_task(supervisor.execute_job(job_id))
    return JobCreateResponse(job_id=job_id, status="queued")


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str, request: Request) -> JobStatusResponse:
    run_state_store = getattr(request.app.state, "run_state_store", None)
    if not run_state_store:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Job control plane is not initialized")

    item = run_state_store.get_job(job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job not found: {job_id}")

    return JobStatusResponse(
        job_id=job_id,
        run_id=item.get("run_id"),
        status=item.get("status", "queued"),
        source=item.get("source"),
        incident_uri=item.get("incident_uri"),
        started_at=datetime.fromisoformat(item["started_at"]) if item.get("started_at") else None,
        finished_at=datetime.fromisoformat(item["finished_at"]) if item.get("finished_at") else None,
    )


@router.get("/{job_id}/attempts", response_model=JobAttemptsResponse)
async def get_job_attempts(job_id: str, request: Request) -> JobAttemptsResponse:
    run_state_store = getattr(request.app.state, "run_state_store", None)
    if not run_state_store:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Job control plane is not initialized")

    item = run_state_store.get_job(job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job not found: {job_id}")

    attempts = [RunAttemptDto.model_validate(attempt) for attempt in item.get("attempts", [])]
    return JobAttemptsResponse(job_id=job_id, run_id=item.get("run_id"), attempts=attempts)


@router.get("/{job_id}/result", response_model=JobResultResponse)
async def get_job_result(job_id: str, request: Request) -> JobResultResponse:
    run_state_store = getattr(request.app.state, "run_state_store", None)
    if not run_state_store:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Job control plane is not initialized")

    item = run_state_store.get_job(job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job not found: {job_id}")

    feature_payload = item.get("result")
    if feature_payload is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Result is not ready for job: {job_id}",
        )

    attempts = [RunAttemptDto.model_validate(attempt) for attempt in item.get("attempts", [])]
    return JobResultResponse(
        job_id=job_id,
        run_id=item.get("run_id"),
        status=item.get("status", "queued"),
        source=item.get("source"),
        incident_uri=item.get("incident_uri"),
        started_at=datetime.fromisoformat(item["started_at"]) if item.get("started_at") else None,
        finished_at=datetime.fromisoformat(item["finished_at"]) if item.get("finished_at") else None,
        feature=JobFeatureResultDto.model_validate(feature_payload),
        attempts=attempts,
    )


@router.post("/{job_id}/cancel", response_model=JobCancelResponse)
async def cancel_job(job_id: str, request: Request) -> JobCancelResponse:
    run_state_store = getattr(request.app.state, "run_state_store", None)
    if not run_state_store:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Job control plane is not initialized")

    item = run_state_store.patch_job(job_id, status="cancelled", finished_at=_utcnow())
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job not found: {job_id}")
    run_state_store.append_event(job_id, "job.cancelled", {"jobId": job_id, "status": "cancelled"})
    return JobCancelResponse(job_id=job_id, status="cancelled")


@router.get("/{job_id}/events")
async def stream_job_events(job_id: str, request: Request):
    run_state_store = getattr(request.app.state, "run_state_store", None)
    if not run_state_store:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Job control plane is not initialized")

    if not run_state_store.get_job(job_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job not found: {job_id}")

    async def event_stream():
        idx = 0
        while True:
            if await request.is_disconnected():
                return
            events, idx = run_state_store.list_events(job_id, idx)
            if not events:
                await asyncio.sleep(0.2)
                continue
            for event in events:
                payload = JobEventDto(
                    event_type=event["event_type"],
                    payload=event["payload"],
                    created_at=datetime.fromisoformat(event["created_at"]),
                    index=event["index"],
                ).model_dump(by_alias=True, mode="json")
                yield f"event: {payload['eventType']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
