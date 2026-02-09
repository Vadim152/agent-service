"""Pydantic models for chat control-plane API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from api.schemas import ApiBaseModel


class ChatSessionCreateRequest(ApiBaseModel):
    project_root: str = Field(..., alias="projectRoot")
    source: str = Field(default="ide-plugin")
    profile: str = Field(default="quick")
    reuse_existing: bool = Field(default=True, alias="reuseExisting")


class ChatSessionCreateResponse(ApiBaseModel):
    session_id: str = Field(..., alias="sessionId")
    created_at: datetime = Field(..., alias="createdAt")
    reused: bool = False
    memory_snapshot: dict[str, Any] = Field(default_factory=dict, alias="memorySnapshot")


class ChatMessageRequest(ApiBaseModel):
    message_id: str | None = Field(default=None, alias="messageId")
    role: Literal["user"] = "user"
    content: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class ChatMessageAcceptedResponse(ApiBaseModel):
    session_id: str = Field(..., alias="sessionId")
    run_id: str = Field(..., alias="runId")
    accepted: bool = True


class ChatToolDecisionRequest(ApiBaseModel):
    permission_id: str = Field(..., alias="permissionId")
    decision: Literal["approve_once", "approve_always", "reject"]


class ChatToolDecisionResponse(ApiBaseModel):
    session_id: str = Field(..., alias="sessionId")
    run_id: str = Field(..., alias="runId")
    accepted: bool = True


class ChatMessageDto(ApiBaseModel):
    message_id: str = Field(..., alias="messageId")
    role: str
    content: str
    run_id: str | None = Field(default=None, alias="runId")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(..., alias="createdAt")


class ChatEventDto(ApiBaseModel):
    event_type: str = Field(..., alias="eventType")
    payload: dict[str, Any]
    created_at: datetime = Field(..., alias="createdAt")
    index: int


class ChatPendingPermissionDto(ApiBaseModel):
    permission_id: str = Field(..., alias="permissionId")
    title: str
    kind: str
    call_id: str | None = Field(default=None, alias="callId")
    message_id: str | None = Field(default=None, alias="messageId")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(..., alias="createdAt")


class ChatHistoryResponse(ApiBaseModel):
    session_id: str = Field(..., alias="sessionId")
    project_root: str = Field(..., alias="projectRoot")
    source: str
    profile: str
    status: str
    messages: list[ChatMessageDto] = Field(default_factory=list)
    events: list[ChatEventDto] = Field(default_factory=list)
    pending_permissions: list[ChatPendingPermissionDto] = Field(
        default_factory=list,
        alias="pendingPermissions",
    )
    memory_snapshot: dict[str, Any] = Field(default_factory=dict, alias="memorySnapshot")
    updated_at: datetime = Field(..., alias="updatedAt")


__all__ = [
    "ChatSessionCreateRequest",
    "ChatSessionCreateResponse",
    "ChatMessageRequest",
    "ChatMessageAcceptedResponse",
    "ChatToolDecisionRequest",
    "ChatToolDecisionResponse",
    "ChatMessageDto",
    "ChatEventDto",
    "ChatPendingPermissionDto",
    "ChatHistoryResponse",
]
