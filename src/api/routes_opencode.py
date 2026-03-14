"""OpenCode-specific agent-mode routes."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from api.opencode_schemas import (
    OpenCodeAgentsResponse,
    OpenCodeCommandDto,
    OpenCodeCommandExecutionRequest,
    OpenCodeCommandExecutionResponse,
    OpenCodeCommandsResponse,
    OpenCodeConfigSnapshotDto,
    OpenCodeMcpsResponse,
    OpenCodeModelsResponse,
    OpenCodeProvidersResponse,
    OpenCodeResourcesResponse,
    OpenCodeSessionEventsResponse,
    OpenCodeSessionStatusDto,
    OpenCodeToolsResponse,
)
from infrastructure.runtime_errors import ChatRuntimeError
from runtime.opencode_adapter import OpenCodeAdapterError


router = APIRouter(prefix="/opencode", tags=["opencode"])

_NATIVE_ACTIONS: dict[str, dict[str, Any]] = {
    "new": {"description": "Create a new agent dialog", "nativeAction": "new_session", "hidden": True},
    "sessions": {"description": "Open agent session history", "nativeAction": "open_history", "hidden": True},
    "editor": {"description": "Open the editor integration", "nativeAction": "open_editor", "hidden": False},
    "help": {"description": "Show available OpenCode commands", "nativeAction": None, "hidden": False},
    "agents": {"description": "Inspect available agents", "nativeAction": None, "hidden": False},
    "mcps": {"description": "Inspect configured MCP servers", "nativeAction": None, "hidden": False},
    "skills": {"description": "Inspect discovered skills", "nativeAction": None, "hidden": False},
    "models": {"description": "Inspect configured models", "nativeAction": None, "hidden": False},
    "status": {"description": "Show current agent status and diff", "nativeAction": None, "hidden": False},
    "review": {"description": "Run repository review", "nativeAction": None, "hidden": False},
    "init": {"description": "Initialize OpenCode for the current project", "nativeAction": None, "hidden": False},
}


def _get_adapter_client(request: Request):
    client = getattr(request.app.state, "opencode_adapter_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenCode adapter is not initialized",
        )
    return client


def _get_runtime(request: Request):
    runtime = getattr(request.app.state, "opencode_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenCode runtime is not initialized",
        )
    return runtime


def _parse_iso_datetime(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value
    raw = str(value or "").strip()
    if not raw:
        return datetime.utcnow()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    return datetime.fromisoformat(raw)


def _adapter_to_http_error(exc: OpenCodeAdapterError, request: Request) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code or status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": {
                "code": exc.code or "backend_unavailable",
                "message": str(exc),
                "retryable": bool(exc.retryable),
                "details": dict(exc.details or {}),
                "requestId": exc.request_id or getattr(request.state, "request_id", None),
            }
        },
    )


def _runtime_to_http_error(exc: ChatRuntimeError, request: Request) -> HTTPException:
    if exc.code:
        return HTTPException(
            status_code=exc.status_code or status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "retryable": bool(exc.retryable),
                    "details": dict(exc.details or {}),
                    "requestId": exc.request_id or getattr(request.state, "request_id", None),
                }
            },
        )
    return HTTPException(
        status_code=exc.status_code or status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=str(exc),
    )


def _resolve_project_root(runtime: Any, *, session_id: str | None, project_root: str | None) -> str | None:
    raw_project_root = str(project_root or "").strip()
    if raw_project_root:
        return raw_project_root
    raw_session_id = str(session_id or "").strip()
    if not raw_session_id:
        return None
    session = runtime.state_store.get_session(raw_session_id)
    if not session:
        return None
    value = str(session.get("project_root") or "").strip()
    return value or None


def _build_alias_catalog(upstream_items: list[dict[str, Any]]) -> list[OpenCodeCommandDto]:
    items = [OpenCodeCommandDto.model_validate(item) for item in upstream_items]
    known = {item.name for item in items}
    for name, meta in _NATIVE_ACTIONS.items():
        if name in known:
            continue
        items.append(
            OpenCodeCommandDto(
                name=name,
                description=str(meta.get("description") or ""),
                source="plugin-alias",
                hints=[],
                alias=True,
                hidden=bool(meta.get("hidden", False)),
                nativeAction=meta.get("nativeAction"),
            )
        )
    items.sort(key=lambda item: item.name)
    return items


async def _build_session_status(request: Request, session_id: str) -> OpenCodeSessionStatusDto:
    runtime = _get_runtime(request)
    adapter = _get_adapter_client(request)
    try:
        exists = await runtime.has_session(session_id)
        if not exists:
            raise ChatRuntimeError(f"Session not found: {session_id}", status_code=404)
        status_payload = await runtime.get_status(session_id=session_id)
        diff_payload = await runtime.get_diff(session_id=session_id)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc, request) from exc

    project_root = _resolve_project_root(runtime, session_id=session_id, project_root=None)
    try:
        details_payload = adapter.get_session_details(session_id, project_root=project_root)
        config_payload = adapter.get_config_snapshot(project_root=project_root)
    except OpenCodeAdapterError as exc:
        raise _adapter_to_http_error(exc, request) from exc

    session_details = dict(details_payload.get("session") or {})
    return OpenCodeSessionStatusDto(
        sessionId=status_payload["sessionId"],
        runtime="opencode",
        activity=str(status_payload.get("activity", "idle")),
        currentAction=str(status_payload.get("currentAction", "Idle")),
        lastEventAt=_parse_iso_datetime(status_payload.get("lastEventAt")),
        updatedAt=_parse_iso_datetime(status_payload.get("updatedAt")),
        pendingPermissionsCount=int(status_payload.get("pendingPermissionsCount", 0)),
        activeRunId=status_payload.get("activeRunId"),
        activeRunStatus=status_payload.get("activeRunStatus"),
        activeRunBackend=status_payload.get("activeRunBackend"),
        backendSessionId=session_details.get("backendSessionId"),
        agentId=details_payload.get("agentId"),
        providerId=details_payload.get("providerId"),
        modelId=details_payload.get("modelId"),
        mcpCount=int(details_payload.get("mcpCount", 0)),
        commandCatalog=details_payload.get("commandCatalog") or {},
        config=OpenCodeConfigSnapshotDto.model_validate(config_payload),
        totals=status_payload.get("totals") or {},
        limits=status_payload.get("limits") or {},
        diffSummary=diff_payload.get("summary") or {},
        diffFiles=diff_payload.get("files") or [],
    )


async def _dispatch_prompt_command(
    request: Request,
    *,
    command_id: str,
    payload: OpenCodeCommandExecutionRequest,
    prompt: str,
) -> OpenCodeCommandExecutionResponse:
    runtime = _get_runtime(request)
    session_id = str(payload.session_id or "").strip() or None
    project_root = _resolve_project_root(runtime, session_id=session_id, project_root=payload.project_root)
    if session_id is None:
        if not project_root:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="projectRoot is required when sessionId is not provided",
            )
        try:
            created = await runtime.create_session(
                project_root=project_root,
                source="ide-plugin",
                profile="agent",
                reuse_existing=False,
            )
        except ChatRuntimeError as exc:
            raise _runtime_to_http_error(exc, request) from exc
        session_id = str(created["sessionId"])

    arguments = [str(item).strip() for item in payload.arguments if str(item).strip()]
    raw_input = str(payload.raw_input or "").strip()
    suffix = raw_input if raw_input else " ".join(arguments)
    display_text = f"/{command_id} {suffix}".strip()
    run_id = uuid.uuid4().hex
    message_id = uuid.uuid4().hex
    try:
        await runtime.dispatch_command(
            session_id=session_id,
            run_id=run_id,
            message_id=message_id,
            command_id=command_id,
            prompt=prompt,
            display_text=display_text,
            raw_input=suffix or None,
            message_metadata=payload.message_metadata,
        )
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc, request) from exc
    return OpenCodeCommandExecutionResponse(
        commandId=command_id,
        accepted=True,
        kind="run",
        sessionId=session_id,
        runId=run_id,
        result={"displayText": display_text, "prompt": prompt},
        updatedAt=datetime.utcnow(),
    )


@router.get("/commands", response_model=OpenCodeCommandsResponse)
async def list_commands(request: Request, projectRoot: str | None = None) -> OpenCodeCommandsResponse:
    adapter = _get_adapter_client(request)
    try:
        payload = adapter.list_commands(project_root=projectRoot)
    except OpenCodeAdapterError as exc:
        raise _adapter_to_http_error(exc, request) from exc
    return OpenCodeCommandsResponse.model_validate(payload)


@router.get("/agents", response_model=OpenCodeAgentsResponse)
async def list_agents(request: Request, projectRoot: str | None = None) -> OpenCodeAgentsResponse:
    adapter = _get_adapter_client(request)
    try:
        payload = adapter.list_agents(project_root=projectRoot)
    except OpenCodeAdapterError as exc:
        raise _adapter_to_http_error(exc, request) from exc
    return OpenCodeAgentsResponse.model_validate(payload)


@router.get("/mcps", response_model=OpenCodeMcpsResponse)
async def list_mcps(request: Request, projectRoot: str | None = None) -> OpenCodeMcpsResponse:
    adapter = _get_adapter_client(request)
    try:
        payload = adapter.list_mcps(project_root=projectRoot)
    except OpenCodeAdapterError as exc:
        raise _adapter_to_http_error(exc, request) from exc
    return OpenCodeMcpsResponse.model_validate(payload)


@router.get("/providers", response_model=OpenCodeProvidersResponse)
async def list_providers(request: Request, projectRoot: str | None = None) -> OpenCodeProvidersResponse:
    adapter = _get_adapter_client(request)
    try:
        payload = adapter.list_providers(project_root=projectRoot)
    except OpenCodeAdapterError as exc:
        raise _adapter_to_http_error(exc, request) from exc
    return OpenCodeProvidersResponse.model_validate(payload)


@router.get("/models", response_model=OpenCodeModelsResponse)
async def list_models(request: Request, projectRoot: str | None = None) -> OpenCodeModelsResponse:
    adapter = _get_adapter_client(request)
    try:
        payload = adapter.list_models(project_root=projectRoot)
    except OpenCodeAdapterError as exc:
        raise _adapter_to_http_error(exc, request) from exc
    return OpenCodeModelsResponse.model_validate(payload)


@router.get("/tools", response_model=OpenCodeToolsResponse)
async def list_tools(request: Request, projectRoot: str | None = None) -> OpenCodeToolsResponse:
    adapter = _get_adapter_client(request)
    try:
        payload = adapter.list_tools(project_root=projectRoot)
    except OpenCodeAdapterError as exc:
        raise _adapter_to_http_error(exc, request) from exc
    return OpenCodeToolsResponse.model_validate(payload)


@router.get("/resources/{kind}", response_model=OpenCodeResourcesResponse)
async def list_resources(
    kind: str,
    request: Request,
    projectRoot: str | None = None,
) -> OpenCodeResourcesResponse:
    adapter = _get_adapter_client(request)
    try:
        payload = adapter.list_resources(kind, project_root=projectRoot)
    except OpenCodeAdapterError as exc:
        raise _adapter_to_http_error(exc, request) from exc
    return OpenCodeResourcesResponse.model_validate(payload)


@router.get("/config", response_model=OpenCodeConfigSnapshotDto)
async def get_config(request: Request, projectRoot: str | None = None) -> OpenCodeConfigSnapshotDto:
    adapter = _get_adapter_client(request)
    try:
        payload = adapter.get_config_snapshot(project_root=projectRoot)
    except OpenCodeAdapterError as exc:
        raise _adapter_to_http_error(exc, request) from exc
    return OpenCodeConfigSnapshotDto.model_validate(payload)


@router.get("/sessions/{session_id}/status", response_model=OpenCodeSessionStatusDto)
async def get_session_status(session_id: str, request: Request) -> OpenCodeSessionStatusDto:
    return await _build_session_status(request, session_id)


@router.get("/sessions/{session_id}/events", response_model=OpenCodeSessionEventsResponse)
async def list_session_events(
    session_id: str,
    request: Request,
    after: int = Query(default=0),
    limit: int = Query(default=200, ge=1, le=5_000),
) -> OpenCodeSessionEventsResponse:
    runtime = _get_runtime(request)
    adapter = _get_adapter_client(request)
    project_root = _resolve_project_root(runtime, session_id=session_id, project_root=None)
    try:
        payload = adapter.list_session_events(session_id, after=after, limit=limit)
    except OpenCodeAdapterError as exc:
        raise _adapter_to_http_error(exc, request) from exc
    return OpenCodeSessionEventsResponse(
        sessionId=payload.get("externalSessionId", session_id),
        items=payload.get("items") or [],
        nextCursor=int(payload.get("nextCursor", max(0, after))),
        hasMore=bool(payload.get("hasMore", False)),
        updatedAt=_parse_iso_datetime(payload.get("updatedAt")),
    )


@router.post("/commands/{command_id}/execute", response_model=OpenCodeCommandExecutionResponse)
async def execute_command(
    command_id: str,
    payload: OpenCodeCommandExecutionRequest,
    request: Request,
) -> OpenCodeCommandExecutionResponse:
    normalized_command_id = str(command_id or "").strip().lower()
    if not normalized_command_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="commandId must not be empty")

    runtime = _get_runtime(request)
    adapter = _get_adapter_client(request)
    session_id = str(payload.session_id or "").strip() or None
    project_root = _resolve_project_root(runtime, session_id=session_id, project_root=payload.project_root)

    if normalized_command_id in {"new", "sessions", "editor"}:
        meta = _NATIVE_ACTIONS[normalized_command_id]
        return OpenCodeCommandExecutionResponse(
            commandId=normalized_command_id,
            accepted=True,
            kind="native_action",
            sessionId=session_id,
            nativeAction=meta.get("nativeAction"),
            result={"action": meta.get("nativeAction")},
            updatedAt=datetime.utcnow(),
        )

    if normalized_command_id == "status":
        if session_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="sessionId is required for /status")
        status_payload = await _build_session_status(request, session_id)
        return OpenCodeCommandExecutionResponse(
            commandId=normalized_command_id,
            accepted=True,
            kind="status",
            sessionId=session_id,
            result={"status": status_payload.model_dump(by_alias=True, mode="json")},
            updatedAt=datetime.utcnow(),
        )

    if normalized_command_id == "help":
        try:
            commands_payload = adapter.list_commands(project_root=project_root)
        except OpenCodeAdapterError as exc:
            raise _adapter_to_http_error(exc, request) from exc
        merged_items = _build_alias_catalog(commands_payload.get("items") or [])
        return OpenCodeCommandExecutionResponse(
            commandId=normalized_command_id,
            accepted=True,
            kind="catalog",
            sessionId=session_id,
            result={
                "commands": [item.model_dump(by_alias=True, mode="json") for item in merged_items],
                "total": len(merged_items),
            },
            updatedAt=datetime.utcnow(),
        )

    if normalized_command_id == "agents":
        payload_result = list_agents(request, projectRoot=project_root)
        response = await payload_result
        return OpenCodeCommandExecutionResponse(
            commandId=normalized_command_id,
            accepted=True,
            kind="resource",
            sessionId=session_id,
            result={"resourceKind": "agent", "items": response.model_dump(by_alias=True, mode="json")["items"]},
            updatedAt=datetime.utcnow(),
        )

    if normalized_command_id == "mcps":
        response = await list_mcps(request, projectRoot=project_root)
        return OpenCodeCommandExecutionResponse(
            commandId=normalized_command_id,
            accepted=True,
            kind="resource",
            sessionId=session_id,
            result={"resourceKind": "mcp", "items": response.model_dump(by_alias=True, mode="json")["items"]},
            updatedAt=datetime.utcnow(),
        )

    if normalized_command_id == "skills":
        response = await list_resources("skill", request, projectRoot=project_root)
        return OpenCodeCommandExecutionResponse(
            commandId=normalized_command_id,
            accepted=True,
            kind="resource",
            sessionId=session_id,
            result={"resourceKind": "skill", "items": response.model_dump(by_alias=True, mode="json")["items"]},
            updatedAt=datetime.utcnow(),
        )

    if normalized_command_id == "models":
        response = await list_models(request, projectRoot=project_root)
        return OpenCodeCommandExecutionResponse(
            commandId=normalized_command_id,
            accepted=True,
            kind="resource",
            sessionId=session_id,
            result={"resourceKind": "model", "items": response.model_dump(by_alias=True, mode="json")["items"]},
            updatedAt=datetime.utcnow(),
        )

    if normalized_command_id == "review":
        try:
            commands_payload = adapter.list_commands(project_root=project_root)
        except OpenCodeAdapterError as exc:
            raise _adapter_to_http_error(exc, request) from exc
        if any(str(item.get("name") or "").strip().lower() == "review" for item in commands_payload.get("items") or []):
            try:
                execution = adapter.execute_command(
                    "review",
                    payload.model_dump(by_alias=True, mode="json"),
                )
            except OpenCodeAdapterError as exc:
                raise _adapter_to_http_error(exc, request) from exc
            prompt = str(execution.get("prompt") or "").strip()
            return await _dispatch_prompt_command(request, command_id="review", payload=payload, prompt=prompt)
        suffix = str(payload.raw_input or "").strip()
        prompt = "Review the current repository changes, identify risks, and summarize recommended fixes."
        if suffix:
            prompt = f"{prompt}\n\nFocus area: {suffix}"
        return await _dispatch_prompt_command(request, command_id="review", payload=payload, prompt=prompt)

    if normalized_command_id == "init":
        try:
            execution = adapter.execute_command(
                "init",
                payload.model_dump(by_alias=True, mode="json"),
            )
            prompt = str(execution.get("prompt") or "").strip()
            if prompt:
                return await _dispatch_prompt_command(request, command_id="init", payload=payload, prompt=prompt)
        except OpenCodeAdapterError as exc:
            if exc.status_code not in {404, 422}:
                raise _adapter_to_http_error(exc, request) from exc
        prompt = "Initialize OpenCode for this project by inspecting the repository and preparing the required setup guidance."
        return await _dispatch_prompt_command(request, command_id="init", payload=payload, prompt=prompt)

    try:
        execution = adapter.execute_command(
            normalized_command_id,
            payload.model_dump(by_alias=True, mode="json"),
        )
    except OpenCodeAdapterError as exc:
        raise _adapter_to_http_error(exc, request) from exc

    prompt = str(execution.get("prompt") or "").strip()
    kind = str(execution.get("kind") or "prompt").strip().lower()
    if kind == "prompt" and prompt:
        return await _dispatch_prompt_command(
            request,
            command_id=normalized_command_id,
            payload=payload,
            prompt=prompt,
        )

    return OpenCodeCommandExecutionResponse(
        commandId=normalized_command_id,
        accepted=True,
        kind=kind or "result",
        sessionId=session_id,
        message=str(execution.get("message") or "").strip() or None,
        result=execution.get("result") or {},
        updatedAt=datetime.utcnow(),
    )
