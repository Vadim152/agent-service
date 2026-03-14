from __future__ import annotations

from fastapi import APIRouter, Query, Request

from opencode_adapter_app.schemas import (
    AdapterApprovalDecisionRequest,
    AdapterApprovalDecisionResponse,
    AdapterAgentsResponse,
    AdapterCommandExecutionRequest,
    AdapterCommandExecutionResponse,
    AdapterCommandsResponse,
    AdapterConfigSnapshotResponse,
    AdapterMcpsResponse,
    AdapterModelsResponse,
    AdapterProvidersResponse,
    AdapterResourcesResponse,
    AdapterRunCancelResponse,
    AdapterRunCreateRequest,
    AdapterRunCreateResponse,
    AdapterRunEventsResponse,
    AdapterRunStatusResponse,
    AdapterSessionCommandRequest,
    AdapterSessionCommandResponse,
    AdapterSessionDetailsResponse,
    AdapterSessionDiffResponse,
    AdapterSessionDto,
    AdapterSessionEventsResponse,
    AdapterSessionEnsureRequest,
    AdapterToolsResponse,
)


router = APIRouter(tags=["opencode-adapter"])
routing_router = APIRouter(prefix="/v1", tags=["opencode-adapter"])
runs_router = APIRouter(prefix="/v1/runs", tags=["opencode-adapter"])
sessions_router = APIRouter(prefix="/v1/sessions", tags=["opencode-adapter"])


def _service(request: Request):
    return request.app.state.opencode_adapter_service


@routing_router.get("/commands", response_model=AdapterCommandsResponse)
async def list_commands(request: Request, projectRoot: str | None = None) -> AdapterCommandsResponse:
    return _service(request).list_commands(project_root=projectRoot)


@routing_router.post("/commands/{command_id}/execute", response_model=AdapterCommandExecutionResponse)
async def execute_command(
    command_id: str,
    payload: AdapterCommandExecutionRequest,
    request: Request,
) -> AdapterCommandExecutionResponse:
    return _service(request).execute_command(command_id, payload)


@routing_router.get("/agents", response_model=AdapterAgentsResponse)
async def list_agents(request: Request, projectRoot: str | None = None) -> AdapterAgentsResponse:
    return _service(request).list_agents(project_root=projectRoot)


@routing_router.get("/mcps", response_model=AdapterMcpsResponse)
async def list_mcps(request: Request, projectRoot: str | None = None) -> AdapterMcpsResponse:
    return _service(request).list_mcps(project_root=projectRoot)


@routing_router.get("/providers", response_model=AdapterProvidersResponse)
async def list_providers(request: Request, projectRoot: str | None = None) -> AdapterProvidersResponse:
    return _service(request).list_providers(project_root=projectRoot)


@routing_router.get("/models", response_model=AdapterModelsResponse)
async def list_models(request: Request, projectRoot: str | None = None) -> AdapterModelsResponse:
    return _service(request).list_models(project_root=projectRoot)


@routing_router.get("/tools", response_model=AdapterToolsResponse)
async def list_tools(request: Request, projectRoot: str | None = None) -> AdapterToolsResponse:
    return _service(request).list_tools(project_root=projectRoot)


@routing_router.get("/resources/{kind}", response_model=AdapterResourcesResponse)
async def list_resources(
    kind: str,
    request: Request,
    projectRoot: str | None = None,
) -> AdapterResourcesResponse:
    return _service(request).list_resources(kind, project_root=projectRoot)


@routing_router.get("/config", response_model=AdapterConfigSnapshotResponse)
async def get_config_snapshot(request: Request, projectRoot: str | None = None) -> AdapterConfigSnapshotResponse:
    return _service(request).get_config_snapshot(project_root=projectRoot)


@runs_router.post("", response_model=AdapterRunCreateResponse)
async def create_run(payload: AdapterRunCreateRequest, request: Request) -> AdapterRunCreateResponse:
    return _service(request).create_run(payload)


@runs_router.get("/{backend_run_id}", response_model=AdapterRunStatusResponse)
async def get_run(backend_run_id: str, request: Request) -> AdapterRunStatusResponse:
    return _service(request).get_run(backend_run_id)


@runs_router.get("/{backend_run_id}/events", response_model=AdapterRunEventsResponse)
async def list_events(
    backend_run_id: str,
    request: Request,
    after: int = Query(default=0),
    limit: int = Query(default=200, ge=1, le=5_000),
) -> AdapterRunEventsResponse:
    return _service(request).list_events(backend_run_id, after=after, limit=limit)


@runs_router.post("/{backend_run_id}/cancel", response_model=AdapterRunCancelResponse)
async def cancel_run(backend_run_id: str, request: Request) -> AdapterRunCancelResponse:
    return _service(request).cancel_run(backend_run_id)


@runs_router.post(
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


@sessions_router.post("", response_model=AdapterSessionDto)
async def ensure_session(payload: AdapterSessionEnsureRequest, request: Request) -> AdapterSessionDto:
    return _service(request).ensure_session(payload)


@sessions_router.get("/{external_session_id}", response_model=AdapterSessionDto)
async def get_session(external_session_id: str, request: Request) -> AdapterSessionDto:
    return _service(request).get_session(external_session_id)


@sessions_router.get("/{external_session_id}/details", response_model=AdapterSessionDetailsResponse)
async def get_session_details(
    external_session_id: str,
    request: Request,
    projectRoot: str | None = None,
) -> AdapterSessionDetailsResponse:
    return _service(request).get_session_details(external_session_id, project_root=projectRoot)


@sessions_router.post("/{external_session_id}/compact", response_model=AdapterSessionCommandResponse)
async def compact_session(external_session_id: str, request: Request) -> AdapterSessionCommandResponse:
    return _service(request).compact_session(external_session_id)


@sessions_router.get("/{external_session_id}/diff", response_model=AdapterSessionDiffResponse)
async def get_session_diff(external_session_id: str, request: Request) -> AdapterSessionDiffResponse:
    return _service(request).get_session_diff(external_session_id)


@sessions_router.post("/{external_session_id}/commands", response_model=AdapterSessionCommandResponse)
async def execute_session_command(
    external_session_id: str,
    payload: AdapterSessionCommandRequest,
    request: Request,
) -> AdapterSessionCommandResponse:
    return _service(request).execute_session_command(external_session_id, payload)


@sessions_router.get("/{external_session_id}/events", response_model=AdapterSessionEventsResponse)
async def list_session_events(
    external_session_id: str,
    request: Request,
    after: int = Query(default=0),
    limit: int = Query(default=200, ge=1, le=5_000),
) -> AdapterSessionEventsResponse:
    return _service(request).list_session_events(external_session_id, after=after, limit=limit)


router.include_router(routing_router)
router.include_router(runs_router)
router.include_router(sessions_router)
