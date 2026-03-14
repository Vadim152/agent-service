"""Pydantic models for OpenCode-specific agent-mode API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from api.chat_schemas import ChatDiffFileDto, ChatDiffSummaryDto, ChatLimitsDto, ChatUsageTotalsDto
from api.schemas import ApiBaseModel


class OpenCodeCommandDto(ApiBaseModel):
    name: str
    description: str | None = None
    source: str | None = None
    template: str | None = None
    subtask: bool = False
    hints: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    alias: bool = False
    hidden: bool = False
    native_action: str | None = Field(default=None, alias="nativeAction")


class OpenCodeCommandsResponse(ApiBaseModel):
    items: list[OpenCodeCommandDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class OpenCodeCommandExecutionRequest(ApiBaseModel):
    session_id: str | None = Field(default=None, alias="sessionId")
    project_root: str | None = Field(default=None, alias="projectRoot")
    arguments: list[str] = Field(default_factory=list)
    raw_input: str | None = Field(default=None, alias="rawInput")
    message_metadata: dict[str, Any] = Field(default_factory=dict, alias="messageMetadata")


class OpenCodeCommandExecutionResponse(ApiBaseModel):
    command_id: str = Field(..., alias="commandId")
    accepted: bool = True
    kind: str
    session_id: str | None = Field(default=None, alias="sessionId")
    run_id: str | None = Field(default=None, alias="runId")
    native_action: str | None = Field(default=None, alias="nativeAction")
    message: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(..., alias="updatedAt")


class OpenCodeAgentDto(ApiBaseModel):
    name: str
    description: str | None = None
    mode: str | None = None
    native: bool = False
    permission_count: int = Field(default=0, alias="permissionCount")
    raw: dict[str, Any] = Field(default_factory=dict)


class OpenCodeAgentsResponse(ApiBaseModel):
    items: list[OpenCodeAgentDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class OpenCodeMcpDto(ApiBaseModel):
    name: str
    enabled: bool = True
    transport: str | None = None
    description: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class OpenCodeMcpsResponse(ApiBaseModel):
    items: list[OpenCodeMcpDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class OpenCodeProviderDto(ApiBaseModel):
    model_config = ConfigDict(protected_namespaces=())

    provider_id: str = Field(..., alias="providerId")
    name: str
    model_count: int = Field(default=0, alias="modelCount")
    default_model_id: str | None = Field(default=None, alias="defaultModelId")
    raw: dict[str, Any] = Field(default_factory=dict)


class OpenCodeProvidersResponse(ApiBaseModel):
    items: list[OpenCodeProviderDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class OpenCodeModelDto(ApiBaseModel):
    id: str
    provider_id: str = Field(..., alias="providerId")
    name: str
    status: str = "active"
    limit: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class OpenCodeModelsResponse(ApiBaseModel):
    items: list[OpenCodeModelDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class OpenCodeToolDto(ApiBaseModel):
    id: str
    name: str
    description: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class OpenCodeToolsResponse(ApiBaseModel):
    items: list[OpenCodeToolDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class OpenCodeResourceEntryDto(ApiBaseModel):
    kind: Literal["skill", "plugin", "hook"]
    name: str
    path: str
    entry_type: str = Field(..., alias="entryType")
    description: str | None = None
    source_root: str = Field(..., alias="sourceRoot")
    metadata: dict[str, Any] = Field(default_factory=dict)


class OpenCodeResourcesResponse(ApiBaseModel):
    kind: Literal["skill", "plugin", "hook"]
    items: list[OpenCodeResourceEntryDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class OpenCodeConfigSnapshotDto(ApiBaseModel):
    active_project_root: str | None = Field(default=None, alias="activeProjectRoot")
    active_config_file: str | None = Field(default=None, alias="activeConfigFile")
    active_config_dir: str | None = Field(default=None, alias="activeConfigDir")
    resolved_providers: list[str] = Field(default_factory=list, alias="resolvedProviders")
    resolved_model: str | None = Field(default=None, alias="resolvedModel")
    raw_config: dict[str, Any] | None = Field(default=None, alias="rawConfig")
    config_error: str | None = Field(default=None, alias="configError")
    server_running: bool = Field(default=False, alias="serverRunning")
    server_ready: bool = Field(default=False, alias="serverReady")
    base_url: str = Field(default="", alias="baseUrl")


class OpenCodeCommandCatalogSummaryDto(ApiBaseModel):
    total: int = 0
    names: list[str] = Field(default_factory=list)
    updated_at: datetime | None = Field(default=None, alias="updatedAt")


class OpenCodeSessionEventDto(ApiBaseModel):
    event_type: str = Field(..., alias="eventType")
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(..., alias="createdAt")
    index: int


class OpenCodeSessionEventsResponse(ApiBaseModel):
    session_id: str = Field(..., alias="sessionId")
    items: list[OpenCodeSessionEventDto] = Field(default_factory=list)
    next_cursor: int = Field(..., alias="nextCursor")
    has_more: bool = Field(default=False, alias="hasMore")
    updated_at: datetime = Field(..., alias="updatedAt")


class OpenCodeSessionStatusDto(ApiBaseModel):
    model_config = ConfigDict(protected_namespaces=())

    session_id: str = Field(..., alias="sessionId")
    runtime: Literal["opencode"] = "opencode"
    activity: str
    current_action: str = Field(..., alias="currentAction")
    last_event_at: datetime = Field(..., alias="lastEventAt")
    updated_at: datetime = Field(..., alias="updatedAt")
    pending_permissions_count: int = Field(default=0, alias="pendingPermissionsCount")
    active_run_id: str | None = Field(default=None, alias="activeRunId")
    active_run_status: str | None = Field(default=None, alias="activeRunStatus")
    active_run_backend: str | None = Field(default=None, alias="activeRunBackend")
    backend_session_id: str | None = Field(default=None, alias="backendSessionId")
    agent_id: str | None = Field(default=None, alias="agentId")
    provider_id: str | None = Field(default=None, alias="providerId")
    model_id: str | None = Field(default=None, alias="modelId")
    mcp_count: int = Field(default=0, alias="mcpCount")
    command_catalog: OpenCodeCommandCatalogSummaryDto = Field(
        default_factory=OpenCodeCommandCatalogSummaryDto,
        alias="commandCatalog",
    )
    config: OpenCodeConfigSnapshotDto = Field(default_factory=OpenCodeConfigSnapshotDto)
    totals: ChatUsageTotalsDto = Field(default_factory=ChatUsageTotalsDto)
    limits: ChatLimitsDto = Field(default_factory=ChatLimitsDto)
    diff_summary: ChatDiffSummaryDto = Field(default_factory=ChatDiffSummaryDto, alias="diffSummary")
    diff_files: list[ChatDiffFileDto] = Field(default_factory=list, alias="diffFiles")
