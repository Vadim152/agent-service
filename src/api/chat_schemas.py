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
    tool_call_id: str = Field(..., alias="toolCallId")
    decision: Literal["approve", "reject"]
    edited_args: dict[str, Any] | None = Field(default=None, alias="editedArgs")


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


class ChatPendingToolCallDto(ApiBaseModel):
    tool_call_id: str = Field(..., alias="toolCallId")
    tool_name: str = Field(..., alias="toolName")
    args: dict[str, Any]
    risk_level: str = Field(..., alias="riskLevel")
    requires_confirmation: bool = Field(..., alias="requiresConfirmation")
    created_at: datetime = Field(..., alias="createdAt")


class ChatHistoryResponse(ApiBaseModel):
    session_id: str = Field(..., alias="sessionId")
    project_root: str = Field(..., alias="projectRoot")
    source: str
    profile: str
    status: str
    messages: list[ChatMessageDto] = Field(default_factory=list)
    events: list[ChatEventDto] = Field(default_factory=list)
    pending_tool_calls: list[ChatPendingToolCallDto] = Field(default_factory=list, alias="pendingToolCalls")
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
    "ChatPendingToolCallDto",
    "ChatHistoryResponse",
]

