"""Policy and approval routes backed by the control-plane policy service."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from api.policy_schemas import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    AuditEventDto,
    AuditEventsResponse,
    PendingApprovalDto,
    PendingApprovalsResponse,
    PolicyToolDto,
    PolicyToolsResponse,
)
from infrastructure.runtime_errors import ChatRuntimeError


router = APIRouter(prefix="/policy", tags=["policy"])


def _get_policy_service(request: Request):
    service = getattr(request.app.state, "policy_service", None)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Policy service is not initialized",
        )
    return service


def _runtime_to_http_error(exc: ChatRuntimeError) -> HTTPException:
    if exc.status_code == 404:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if exc.status_code == 422:
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


@router.get("/tools", response_model=PolicyToolsResponse)
async def list_tools(request: Request) -> PolicyToolsResponse:
    service = _get_policy_service(request)
    items = await service.list_tools()
    return PolicyToolsResponse(items=[PolicyToolDto.model_validate(item) for item in items])


@router.get("/approvals", response_model=PendingApprovalsResponse)
async def list_approvals(request: Request) -> PendingApprovalsResponse:
    service = _get_policy_service(request)
    items = await service.list_pending_approvals()
    approvals = [PendingApprovalDto.model_validate(item) for item in items]
    return PendingApprovalsResponse(items=approvals, total=len(approvals))


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalDecisionResponse)
async def submit_approval_decision(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    request: Request,
) -> ApprovalDecisionResponse:
    service = _get_policy_service(request)
    try:
        result = await service.submit_decision(approval_id=approval_id, decision=payload.decision)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc
    return ApprovalDecisionResponse.model_validate(result)


@router.get("/audit", response_model=AuditEventsResponse)
async def list_audit_events(request: Request, limit: int = 100) -> AuditEventsResponse:
    service = _get_policy_service(request)
    items = await service.list_audit_events(limit=max(1, min(limit, 500)))
    events = [AuditEventDto.model_validate(item) for item in items]
    return AuditEventsResponse(items=events, total=len(events))
