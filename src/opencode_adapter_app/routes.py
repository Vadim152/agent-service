from __future__ import annotations

from fastapi import APIRouter, Query, Request

from opencode_adapter_app.schemas import (
    AdapterApprovalDecisionRequest,
    AdapterApprovalDecisionResponse,
    AdapterRunCancelResponse,
    AdapterRunCreateRequest,
    AdapterRunCreateResponse,
    AdapterRunEventsResponse,
    AdapterRunStatusResponse,
)


router = APIRouter(prefix="/v1/runs", tags=["opencode-adapter"])


def _service(request: Request):
    return request.app.state.opencode_adapter_service


@router.post("", response_model=AdapterRunCreateResponse)
async def create_run(payload: AdapterRunCreateRequest, request: Request) -> AdapterRunCreateResponse:
    return _service(request).create_run(payload)


@router.get("/{backend_run_id}", response_model=AdapterRunStatusResponse)
async def get_run(backend_run_id: str, request: Request) -> AdapterRunStatusResponse:
    return _service(request).get_run(backend_run_id)


@router.get("/{backend_run_id}/events", response_model=AdapterRunEventsResponse)
async def list_events(
    backend_run_id: str,
    request: Request,
    after: int = Query(default=0),
) -> AdapterRunEventsResponse:
    return _service(request).list_events(backend_run_id, after=after)


@router.post("/{backend_run_id}/cancel", response_model=AdapterRunCancelResponse)
async def cancel_run(backend_run_id: str, request: Request) -> AdapterRunCancelResponse:
    return _service(request).cancel_run(backend_run_id)


@router.post(
    "/{backend_run_id}/approvals/{approval_id}",
    response_model=AdapterApprovalDecisionResponse,
)
async def submit_approval_decision(
    backend_run_id: str,
    approval_id: str,
    payload: AdapterApprovalDecisionRequest,
    request: Request,
) -> AdapterApprovalDecisionResponse:
    return _service(request).submit_approval_decision(backend_run_id, approval_id, payload)
