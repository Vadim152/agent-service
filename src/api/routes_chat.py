"""Chat API routes for OpenCode-backed session lifecycle and streaming."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.chat_schemas import (
    ChatEventDto,
    ChatHistoryResponse,
    ChatMessageAcceptedResponse,
    ChatMessageDto,
    ChatMessageRequest,
    ChatPendingPermissionDto,
    ChatSessionCreateRequest,
    ChatSessionCreateResponse,
    ChatToolDecisionRequest,
    ChatToolDecisionResponse,
)
from infrastructure.opencode_sidecar_client import OpencodeSidecarError

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


def _sidecar_to_http_error(exc: OpencodeSidecarError) -> HTTPException:
    if exc.status_code == 404:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if exc.status_code == 422:
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


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
    except OpencodeSidecarError as exc:
        raise _sidecar_to_http_error(exc) from exc

    created_at = datetime.fromisoformat(str(session["createdAt"]))
    return ChatSessionCreateResponse(
        session_id=str(session["sessionId"]),
        created_at=created_at,
        reused=bool(session.get("reused", False)),
        memory_snapshot={},
    )


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageAcceptedResponse)
async def send_chat_message(
    session_id: str,
    payload: ChatMessageRequest,
    request: Request,
) -> ChatMessageAcceptedResponse:
    runtime = _get_runtime(request)
    try:
        exists = await runtime.has_session(session_id)
    except OpencodeSidecarError as exc:
        raise _sidecar_to_http_error(exc) from exc
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}")

    run_id = str(uuid.uuid4())

    async def _worker() -> None:
        try:
            await runtime.process_message(
                session_id=session_id,
                run_id=run_id,
                message_id=payload.message_id or str(uuid.uuid4()),
                content=payload.content,
            )
        except Exception as exc:  # pragma: no cover - background branch
            logger.warning("Chat message processing failed for session %s: %s", session_id, exc)

    asyncio.create_task(_worker())
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
    except OpencodeSidecarError as exc:
        raise _sidecar_to_http_error(exc) from exc
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}")

    run_id = str(uuid.uuid4())

    async def _worker() -> None:
        try:
            await runtime.process_tool_decision(
                session_id=session_id,
                run_id=run_id,
                permission_id=payload.permission_id,
                decision=payload.decision,
            )
        except Exception as exc:  # pragma: no cover - background branch
            logger.warning("Chat permission decision failed for session %s: %s", session_id, exc)

    asyncio.create_task(_worker())
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
    except OpencodeSidecarError as exc:
        raise _sidecar_to_http_error(exc) from exc

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
        memory_snapshot={},
        updated_at=datetime.fromisoformat(history["updatedAt"]),
    )


@router.get("/sessions/{session_id}/stream")
async def stream_chat_events(session_id: str, request: Request):
    runtime = _get_runtime(request)
    try:
        exists = await runtime.has_session(session_id)
    except OpencodeSidecarError as exc:
        raise _sidecar_to_http_error(exc) from exc
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}")

    async def _stream():
        try:
            async for chunk in runtime.stream_events(session_id=session_id):
                if await request.is_disconnected():
                    return
                yield chunk
        except OpencodeSidecarError as exc:
            payload = {"eventType": "error", "payload": {"message": str(exc)}}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

    return StreamingResponse(_stream(), media_type="text/event-stream")
