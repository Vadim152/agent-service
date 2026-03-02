"""Schemas for policy, approvals, and audit APIs."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from api.schemas import ApiBaseModel


class PolicyToolDto(ApiBaseModel):
    name: str
    description: str
    risk_level: str = Field(..., alias="riskLevel")
    requires_confirmation: bool = Field(..., alias="requiresConfirmation")
    idempotent: bool = True


class PolicyToolsResponse(ApiBaseModel):
    items: list[PolicyToolDto] = Field(default_factory=list)


class PendingApprovalDto(ApiBaseModel):
    approval_id: str = Field(..., alias="approvalId")
    session_id: str = Field(..., alias="sessionId")
    tool_name: str = Field(..., alias="toolName")
    title: str
    kind: str
    risk_level: str = Field(..., alias="riskLevel")
    requires_confirmation: bool = Field(..., alias="requiresConfirmation")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(..., alias="createdAt")


class PendingApprovalsResponse(ApiBaseModel):
    items: list[PendingApprovalDto] = Field(default_factory=list)
    total: int = 0


class ApprovalDecisionRequest(ApiBaseModel):
    decision: Literal["approve", "deny"]


class ApprovalDecisionResponse(ApiBaseModel):
    approval_id: str = Field(..., alias="approvalId")
    session_id: str = Field(..., alias="sessionId")
    run_id: str = Field(..., alias="runId")
    decision: Literal["approve", "deny"]
    accepted: bool = True


class AuditEventDto(ApiBaseModel):
    session_id: str = Field(..., alias="sessionId")
    event_type: str = Field(..., alias="eventType")
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(..., alias="createdAt")
    index: int


class AuditEventsResponse(ApiBaseModel):
    items: list[AuditEventDto] = Field(default_factory=list)
    total: int = 0
