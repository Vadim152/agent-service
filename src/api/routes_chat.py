"""Chat API routes for LangGraph-backed session lifecycle and streaming."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.chat_schemas import (
    ChatCommandRequest,
    ChatCommandResponse,
    ChatDiffFileDto,
    ChatDiffSummaryDto,
    ChatEventDto,
    ChatHistoryResponse,
    ChatLimitsDto,
    ChatMessageAcceptedResponse,
    ChatMessageDto,
    ChatMessageRequest,
    ChatPendingPermissionDto,
    ChatRiskDto,
    ChatSessionDiffResponse,
    ChatSessionCreateRequest,
    ChatSessionCreateResponse,
    ChatSessionListItemDto,
    ChatSessionsListResponse,
    ChatSessionStatusResponse,
    ChatTokenTotalsDto,
    ChatToolDecisionRequest,
    ChatToolDecisionResponse,
    ChatUsageTotalsDto,
)
from infrastructure.runtime_errors import ChatRuntimeError

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


def _get_runtime(request: Request):
    runtime = getattr(request.app.state, "chat_runtime", None)
    if not runtime:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat runtime is not initialized",
        )
    return runtime


def _runtime_to_http_error(exc: ChatRuntimeError) -> HTTPException:
    if exc.status_code == 404:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if exc.status_code == 422:
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


def _schedule_background_task(
    request: Request,
    *,
    source: str,
    worker,
    metadata: dict[str, str],
    on_error,
) -> None:
    registry = getattr(request.app.state, "task_registry", None)
    if registry is None:
        asyncio.create_task(worker())
        return
    registry.create_task(worker(), source=source, metadata=metadata, on_error=on_error)


def _parse_iso_datetime(value: str | None) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        return datetime.utcnow()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    return datetime.fromisoformat(raw)


def _build_risk(
    *,
    pending_permissions_count: int,
    files_changed: int,
    lines_changed: int,
    activity: str,
) -> ChatRiskDto:
    reasons: list[str] = []
    high = False
    medium = False

    if pending_permissions_count > 0:
        reasons.append(f"Pending approvals: {pending_permissions_count}")
        medium = True
    if files_changed > 5:
        reasons.append(f"Large file scope: {files_changed} files")
        high = True
    if lines_changed > 200:
        reasons.append(f"Large diff volume: {lines_changed} lines")
        high = True
    if lines_changed > 0 and not high:
        reasons.append(f"Diff lines: {lines_changed}")
        medium = True
    if activity == "error":
        reasons.append("Agent reported an error state")
        high = True

    if high:
        level = "high"
    elif medium:
        level = "medium"
    else:
        level = "low"
        reasons.append("No pending approvals or high-impact changes")

    return ChatRiskDto(level=level, reasons=reasons)


@router.post("/sessions", response_model=ChatSessionCreateResponse)
async def create_chat_session(payload: ChatSessionCreateRequest, request: Request) -> ChatSessionCreateResponse:
    runtime = _get_runtime(request)
    try:
        session = await runtime.create_session(
            project_root=payload.project_root,
            source=payload.source,
            profile=payload.profile,
            reuse_existing=payload.reuse_existing,
        )
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc

    created_at = _parse_iso_datetime(str(session["createdAt"]))
    return ChatSessionCreateResponse(
        session_id=str(session["sessionId"]),
        created_at=created_at,
        reused=bool(session.get("reused", False)),
        memory_snapshot=session.get("memorySnapshot", {}),
    )


@router.get("/sessions", response_model=ChatSessionsListResponse)
async def list_chat_sessions(
    request: Request,
    projectRoot: str,
    limit: int = 50,
) -> ChatSessionsListResponse:
    runtime = _get_runtime(request)
    bounded_limit = max(1, min(limit, 200))
    try:
        payload = await runtime.list_sessions(project_root=projectRoot, limit=bounded_limit)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc

    raw_items = payload.get("items", [])
    items = [
        ChatSessionListItemDto(
            session_id=str(item.get("sessionId", "")),
            project_root=str(item.get("projectRoot", projectRoot)),
            source=str(item.get("source", "ide-plugin")),
            profile=str(item.get("profile", "quick")),
            status=str(item.get("status", "active")),
            activity=str(item.get("activity", "idle")),
            current_action=str(item.get("currentAction", "Idle")),
            created_at=_parse_iso_datetime(str(item.get("createdAt"))),
            updated_at=_parse_iso_datetime(str(item.get("updatedAt"))),
            last_message_preview=(
                str(item["lastMessagePreview"])
                if item.get("lastMessagePreview") is not None
                else None
            ),
            pending_permissions_count=int(item.get("pendingPermissionsCount", 0)),
        )
        for item in raw_items
    ]
    total = int(payload.get("total", len(items)))
    return ChatSessionsListResponse(items=items, total=total)


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageAcceptedResponse)
async def send_chat_message(
    session_id: str,
    payload: ChatMessageRequest,
    request: Request,
) -> ChatMessageAcceptedResponse:
    runtime = _get_runtime(request)
    try:
        exists = await runtime.has_session(session_id)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}")
    try:
        status_payload = await runtime.get_status(session_id=session_id)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc

    activity = str(status_payload.get("activity", "idle")).strip().lower()
    if activity in {"busy", "waiting_permission", "retry"}:
        current_action = str(status_payload.get("currentAction", "Processing request")).strip() or "Processing request"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is {activity}. Wait until it becomes idle before sending a new message. Action: {current_action}",
        )

    run_id = str(uuid.uuid4())

    async def _worker() -> None:
        await runtime.process_message(
            session_id=session_id,
            run_id=run_id,
            message_id=payload.message_id or str(uuid.uuid4()),
            content=payload.content,
        )

    def _on_error(exc: BaseException) -> None:
        logger.warning("Chat message processing failed for session %s: %s", session_id, exc)
        try:
            runtime.state_store.append_event(  # type: ignore[attr-defined]
                session_id,
                "message.worker_failed",
                {"sessionId": session_id, "runId": run_id, "error": str(exc)},
            )
            runtime.state_store.update_session(  # type: ignore[attr-defined]
                session_id,
                activity="error",
                current_action="Message processing failed",
            )
        except Exception:  # pragma: no cover - defensive branch
            logger.warning("Failed to persist chat worker failure for session %s", session_id)

    _schedule_background_task(
        request,
        source="chat.message",
        worker=_worker,
        metadata={"sessionId": session_id, "runId": run_id},
        on_error=_on_error,
    )
    return ChatMessageAcceptedResponse(session_id=session_id, run_id=run_id, accepted=True)


@router.post("/sessions/{session_id}/tool-decisions", response_model=ChatToolDecisionResponse)
async def submit_tool_decision(
    session_id: str,
    payload: ChatToolDecisionRequest,
    request: Request,
) -> ChatToolDecisionResponse:
    runtime = _get_runtime(request)
    try:
        exists = await runtime.has_session(session_id)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}")

    run_id = str(uuid.uuid4())

    async def _worker() -> None:
        await runtime.process_tool_decision(
            session_id=session_id,
            run_id=run_id,
            permission_id=payload.permission_id,
            decision=payload.decision,
        )

    def _on_error(exc: BaseException) -> None:
        logger.warning("Chat permission decision failed for session %s: %s", session_id, exc)
        try:
            runtime.state_store.append_event(  # type: ignore[attr-defined]
                session_id,
                "permission.worker_failed",
                {"sessionId": session_id, "runId": run_id, "error": str(exc)},
            )
            runtime.state_store.update_session(  # type: ignore[attr-defined]
                session_id,
                activity="error",
                current_action="Permission processing failed",
            )
        except Exception:  # pragma: no cover - defensive branch
            logger.warning("Failed to persist permission worker failure for session %s", session_id)

    _schedule_background_task(
        request,
        source="chat.permission",
        worker=_worker,
        metadata={"sessionId": session_id, "runId": run_id},
        on_error=_on_error,
    )
    return ChatToolDecisionResponse(session_id=session_id, run_id=run_id, accepted=True)


@router.get("/sessions/{session_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    request: Request,
    limit: int = 200,
) -> ChatHistoryResponse:
    runtime = _get_runtime(request)
    try:
        history = await runtime.get_history(session_id=session_id, limit=limit)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc

    messages = [ChatMessageDto.model_validate(item) for item in history.get("messages", [])]
    events = [ChatEventDto.model_validate(item) for item in history.get("events", [])]
    pending_permissions = [
        ChatPendingPermissionDto.model_validate(item)
        for item in history.get("pendingPermissions", [])
    ]
    return ChatHistoryResponse(
        session_id=history["sessionId"],
        project_root=history["projectRoot"],
        source=history.get("source", "ide-plugin"),
        profile=history.get("profile", "quick"),
        status=history.get("status", "active"),
        messages=messages,
        events=events,
        pending_permissions=pending_permissions,
        memory_snapshot=history.get("memorySnapshot", {}),
        updated_at=_parse_iso_datetime(history["updatedAt"]),
    )


@router.get("/sessions/{session_id}/status", response_model=ChatSessionStatusResponse)
async def get_chat_status(session_id: str, request: Request) -> ChatSessionStatusResponse:
    runtime = _get_runtime(request)
    try:
        exists = await runtime.has_session(session_id)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}")

    try:
        status_payload = await runtime.get_status(session_id=session_id)
        diff_payload = await runtime.get_diff(session_id=session_id)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc

    summary = diff_payload.get("summary", {})
    files_changed = int(summary.get("files", 0))
    lines_changed = int(summary.get("additions", 0)) + int(summary.get("deletions", 0))
    pending_permissions_count = int(status_payload.get("pendingPermissionsCount", 0))
    activity = str(status_payload.get("activity", "idle"))
    risk = _build_risk(
        pending_permissions_count=pending_permissions_count,
        files_changed=files_changed,
        lines_changed=lines_changed,
        activity=activity,
    )

    tokens = status_payload.get("totals", {}).get("tokens", {})
    totals = ChatUsageTotalsDto(
        tokens=ChatTokenTotalsDto(
            input=int(tokens.get("input", 0)),
            output=int(tokens.get("output", 0)),
            reasoning=int(tokens.get("reasoning", 0)),
            cache_read=int(tokens.get("cacheRead", 0)),
            cache_write=int(tokens.get("cacheWrite", 0)),
        ),
        cost=float(status_payload.get("totals", {}).get("cost", 0.0)),
    )
    limits_payload = status_payload.get("limits", {})
    limits = ChatLimitsDto(
        context_window=limits_payload.get("contextWindow"),
        used=int(limits_payload.get("used", 0)),
        percent=limits_payload.get("percent"),
    )
    return ChatSessionStatusResponse(
        session_id=status_payload["sessionId"],
        activity=activity,
        current_action=str(status_payload.get("currentAction", "Idle")),
        last_event_at=_parse_iso_datetime(str(status_payload.get("lastEventAt"))),
        updated_at=_parse_iso_datetime(str(status_payload.get("updatedAt"))),
        pending_permissions_count=pending_permissions_count,
        totals=totals,
        limits=limits,
        last_retry_message=status_payload.get("lastRetryMessage"),
        last_retry_attempt=(
            int(status_payload["lastRetryAttempt"])
            if status_payload.get("lastRetryAttempt") is not None
            else None
        ),
        last_retry_at=(
            _parse_iso_datetime(str(status_payload.get("lastRetryAt")))
            if status_payload.get("lastRetryAt")
            else None
        ),
        risk=risk,
    )


@router.get("/sessions/{session_id}/diff", response_model=ChatSessionDiffResponse)
async def get_chat_diff(session_id: str, request: Request) -> ChatSessionDiffResponse:
    runtime = _get_runtime(request)
    try:
        exists = await runtime.has_session(session_id)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}")

    try:
        diff_payload = await runtime.get_diff(session_id=session_id)
        status_payload = await runtime.get_status(session_id=session_id)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc

    summary_payload = diff_payload.get("summary", {})
    summary = ChatDiffSummaryDto(
        files=int(summary_payload.get("files", 0)),
        additions=int(summary_payload.get("additions", 0)),
        deletions=int(summary_payload.get("deletions", 0)),
    )
    files = [ChatDiffFileDto.model_validate(item) for item in diff_payload.get("files", [])]
    risk = _build_risk(
        pending_permissions_count=int(status_payload.get("pendingPermissionsCount", 0)),
        files_changed=summary.files,
        lines_changed=summary.additions + summary.deletions,
        activity=str(status_payload.get("activity", "idle")),
    )
    return ChatSessionDiffResponse(
        session_id=diff_payload["sessionId"],
        summary=summary,
        files=files,
        updated_at=_parse_iso_datetime(str(diff_payload.get("updatedAt"))),
        risk=risk,
    )


@router.post("/sessions/{session_id}/commands", response_model=ChatCommandResponse)
async def execute_chat_command(
    session_id: str,
    payload: ChatCommandRequest,
    request: Request,
) -> ChatCommandResponse:
    runtime = _get_runtime(request)
    try:
        exists = await runtime.has_session(session_id)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}")

    try:
        command_result = await runtime.execute_command(session_id=session_id, command=payload.command)
        status_payload = await runtime.get_status(session_id=session_id)
        diff_payload = await runtime.get_diff(session_id=session_id)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc

    summary_payload = diff_payload.get("summary", {})
    risk = _build_risk(
        pending_permissions_count=int(status_payload.get("pendingPermissionsCount", 0)),
        files_changed=int(summary_payload.get("files", 0)),
        lines_changed=int(summary_payload.get("additions", 0)) + int(summary_payload.get("deletions", 0)),
        activity=str(status_payload.get("activity", "idle")),
    )
    return ChatCommandResponse(
        session_id=command_result.get("sessionId", session_id),
        command=str(command_result.get("command", payload.command)),
        accepted=bool(command_result.get("accepted", True)),
        result=command_result.get("result", {}),
        updated_at=_parse_iso_datetime(str(command_result.get("updatedAt"))),
        risk=risk,
    )


@router.get("/sessions/{session_id}/stream")
async def stream_chat_events(session_id: str, request: Request, fromIndex: int = 0):
    runtime = _get_runtime(request)
    try:
        exists = await runtime.has_session(session_id)
    except ChatRuntimeError as exc:
        raise _runtime_to_http_error(exc) from exc
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}")

    async def _stream():
        try:
            async for chunk in runtime.stream_events(session_id=session_id, from_index=max(0, fromIndex)):
                if await request.is_disconnected():
                    return
                yield chunk
        except ChatRuntimeError as exc:
            payload = {"eventType": "error", "payload": {"message": str(exc)}}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

    return StreamingResponse(_stream(), media_type="text/event-stream")

