from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from api.schemas import ApiBaseModel


class AdapterRunCreateRequest(ApiBaseModel):
    run_id: str = Field(..., alias="runId")
    session_id: str | None = Field(default=None, alias="sessionId")
    project_root: str = Field(..., alias="projectRoot")
    prompt: str
    source: str | None = None
    profile: str | None = None
    backend_session_id: str | None = Field(default=None, alias="backendSessionId")
    policy_mode: str | None = Field(default=None, alias="policyMode")
    config_profile: str | None = Field(default=None, alias="configProfile")


class AdapterArtifactDto(ApiBaseModel):
    name: str
    media_type: str = Field(default="text/plain", alias="mediaType")
    uri: str | None = None
    content: str | None = None


class AdapterApprovalDto(ApiBaseModel):
    approval_id: str = Field(..., alias="approvalId")
    tool_name: str = Field(..., alias="toolName")
    title: str
    kind: str = "tool"
    risk_level: str = Field(default="high", alias="riskLevel")
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdapterApprovalStatusDto(AdapterApprovalDto):
    status: Literal["pending", "approved", "denied"]
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterRunStatusResponse(ApiBaseModel):
    backend_run_id: str = Field(..., alias="backendRunId")
    backend_session_id: str | None = Field(default=None, alias="backendSessionId")
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    current_action: str = Field(default="Queued", alias="currentAction")
    result: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    artifacts: list[AdapterArtifactDto] = Field(default_factory=list)
    pending_approvals: list[AdapterApprovalDto] = Field(default_factory=list, alias="pendingApprovals")
    approvals: list[AdapterApprovalStatusDto] = Field(default_factory=list)
    totals: dict[str, Any] | None = None
    limits: dict[str, Any] | None = None
    created_at: datetime = Field(..., alias="createdAt")
    started_at: datetime | None = Field(default=None, alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")
    exit_code: int | None = Field(default=None, alias="exitCode")
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterRunCreateResponse(ApiBaseModel):
    backend_run_id: str = Field(..., alias="backendRunId")
    backend_session_id: str | None = Field(default=None, alias="backendSessionId")
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    current_action: str = Field(..., alias="currentAction")
    created_at: datetime = Field(..., alias="createdAt")
    started_at: datetime | None = Field(default=None, alias="startedAt")


class AdapterRunEventDto(ApiBaseModel):
    event_type: str = Field(..., alias="eventType")
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(..., alias="createdAt")
    index: int


class AdapterRunEventsResponse(ApiBaseModel):
    items: list[AdapterRunEventDto] = Field(default_factory=list)
    next_cursor: int = Field(..., alias="nextCursor")
    has_more: bool = Field(default=False, alias="hasMore")


class AdapterRunCancelResponse(ApiBaseModel):
    backend_run_id: str = Field(..., alias="backendRunId")
    status: str
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterApprovalDecisionRequest(ApiBaseModel):
    decision: Literal["approve", "deny"]


class AdapterApprovalDecisionResponse(ApiBaseModel):
    backend_run_id: str = Field(..., alias="backendRunId")
    approval_id: str = Field(..., alias="approvalId")
    decision: str
    status: str
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterSessionEnsureRequest(ApiBaseModel):
    external_session_id: str = Field(..., alias="externalSessionId")
    project_root: str = Field(..., alias="projectRoot")
    source: str | None = None
    profile: str | None = None


class AdapterSessionDto(ApiBaseModel):
    external_session_id: str = Field(..., alias="externalSessionId")
    backend_session_id: str | None = Field(default=None, alias="backendSessionId")
    project_root: str = Field(..., alias="projectRoot")
    last_backend_run_id: str | None = Field(default=None, alias="lastBackendRunId")
    status: str = "idle"
    current_action: str = Field(default="Idle", alias="currentAction")
    last_activity_at: datetime | None = Field(default=None, alias="lastActivityAt")
    last_compaction_at: datetime | None = Field(default=None, alias="lastCompactionAt")
    updated_at: datetime = Field(..., alias="updatedAt")
    last_provider_id: str | None = Field(default=None, alias="lastProviderId")
    last_model_id: str | None = Field(default=None, alias="lastModelId")


class AdapterSessionDiffResponse(ApiBaseModel):
    external_session_id: str = Field(..., alias="externalSessionId")
    backend_session_id: str | None = Field(default=None, alias="backendSessionId")
    summary: dict[str, Any] = Field(default_factory=dict)
    files: list[dict[str, Any]] = Field(default_factory=list)
    stale: bool = False
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterSessionCommandRequest(ApiBaseModel):
    command: Literal["status", "diff", "compact", "abort", "help"]


class AdapterSessionCommandResponse(ApiBaseModel):
    external_session_id: str = Field(..., alias="externalSessionId")
    command: str
    accepted: bool = True
    result: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterCommandDto(ApiBaseModel):
    name: str
    description: str | None = None
    source: str | None = None
    template: str | None = None
    subtask: bool = False
    hints: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class AdapterCommandsResponse(ApiBaseModel):
    items: list[AdapterCommandDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterCommandExecutionRequest(ApiBaseModel):
    session_id: str | None = Field(default=None, alias="sessionId")
    project_root: str | None = Field(default=None, alias="projectRoot")
    arguments: list[str] = Field(default_factory=list)
    raw_input: str | None = Field(default=None, alias="rawInput")


class AdapterCommandExecutionResponse(ApiBaseModel):
    command_id: str = Field(..., alias="commandId")
    kind: str
    prompt: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterAgentDto(ApiBaseModel):
    name: str
    description: str | None = None
    mode: str | None = None
    native: bool = False
    permission_count: int = Field(default=0, alias="permissionCount")
    raw: dict[str, Any] = Field(default_factory=dict)


class AdapterAgentsResponse(ApiBaseModel):
    items: list[AdapterAgentDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterMcpDto(ApiBaseModel):
    name: str
    enabled: bool = True
    transport: str | None = None
    description: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class AdapterMcpsResponse(ApiBaseModel):
    items: list[AdapterMcpDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterProviderDto(ApiBaseModel):
    model_config = ConfigDict(protected_namespaces=())

    provider_id: str = Field(..., alias="providerId")
    name: str
    model_count: int = Field(default=0, alias="modelCount")
    default_model_id: str | None = Field(default=None, alias="defaultModelId")
    raw: dict[str, Any] = Field(default_factory=dict)


class AdapterProvidersResponse(ApiBaseModel):
    items: list[AdapterProviderDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterModelDto(ApiBaseModel):
    id: str
    provider_id: str = Field(..., alias="providerId")
    name: str
    status: str = "active"
    limit: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class AdapterModelsResponse(ApiBaseModel):
    items: list[AdapterModelDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterToolDto(ApiBaseModel):
    id: str
    name: str
    description: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class AdapterToolsResponse(ApiBaseModel):
    items: list[AdapterToolDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterResourceEntryDto(ApiBaseModel):
    kind: Literal["skill", "plugin", "hook"]
    name: str
    path: str
    entry_type: str = Field(..., alias="entryType")
    description: str | None = None
    source_root: str = Field(..., alias="sourceRoot")
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdapterResourcesResponse(ApiBaseModel):
    kind: Literal["skill", "plugin", "hook"]
    items: list[AdapterResourceEntryDto] = Field(default_factory=list)
    total: int = 0
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterConfigSnapshotResponse(ApiBaseModel):
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


class AdapterCommandCatalogSummaryDto(ApiBaseModel):
    total: int = 0
    names: list[str] = Field(default_factory=list)
    updated_at: datetime | None = Field(default=None, alias="updatedAt")


class AdapterSessionDetailsResponse(ApiBaseModel):
    model_config = ConfigDict(protected_namespaces=())

    session: AdapterSessionDto
    agent_id: str | None = Field(default=None, alias="agentId")
    provider_id: str | None = Field(default=None, alias="providerId")
    model_id: str | None = Field(default=None, alias="modelId")
    pending_approvals_count: int = Field(default=0, alias="pendingApprovalsCount")
    mcp_count: int = Field(default=0, alias="mcpCount")
    command_catalog: AdapterCommandCatalogSummaryDto = Field(default_factory=AdapterCommandCatalogSummaryDto, alias="commandCatalog")
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterSessionEventsResponse(ApiBaseModel):
    external_session_id: str = Field(..., alias="externalSessionId")
    items: list[AdapterRunEventDto] = Field(default_factory=list)
    next_cursor: int = Field(..., alias="nextCursor")
    has_more: bool = Field(default=False, alias="hasMore")
    updated_at: datetime = Field(..., alias="updatedAt")


class AdapterDebugRuntimeResponse(ApiBaseModel):
    service: str = "opencode-adapter"
    runner_type: str = Field(..., alias="runnerType")
    resolution_mode: str = Field(..., alias="modelResolution")
    forced_model: str | None = Field(default=None, alias="forcedModel")
    base_url: str = Field(..., alias="baseUrl")
    server_running: bool = Field(..., alias="serverRunning")
    server_ready: bool = Field(..., alias="serverReady")
    active_project_root: str | None = Field(default=None, alias="activeProjectRoot")
    active_config_file: str | None = Field(default=None, alias="activeConfigFile")
    active_config_dir: str | None = Field(default=None, alias="activeConfigDir")
    resolved_providers: list[str] = Field(default_factory=list, alias="resolvedProviders")
    resolved_model: str | None = Field(default=None, alias="resolvedModel")
    raw_config: dict[str, Any] | None = Field(default=None, alias="rawConfig")
    config_error: str | None = Field(default=None, alias="configError")
