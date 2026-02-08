"""Chat API routes for session lifecycle, messaging and streaming."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.chat_schemas import (
    ChatEventDto,
    ChatHistoryResponse,
    ChatMessageAcceptedResponse,
    ChatMessageDto,
    ChatMessageRequest,
    ChatPendingToolCallDto,
    ChatSessionCreateRequest,
    ChatSessionCreateResponse,
    ChatToolDecisionRequest,
    ChatToolDecisionResponse,
)

router = APIRouter(prefix="/chat", tags=["chat"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_runtime(request: Request):
    runtime = getattr(request.app.state, "chat_runtime", None)
    if not runtime:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat runtime is not initialized",
        )
    return runtime


def _get_store(request: Request):
    store = getattr(request.app.state, "chat_state_store", None)
    if not store:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat state store is not initialized",
        )
    return store


@router.post("/sessions", response_model=ChatSessionCreateResponse)
async def create_chat_session(payload: ChatSessionCreateRequest, request: Request) -> ChatSessionCreateResponse:
    store = _get_store(request)
    session, reused = store.create_session(
        project_root=payload.project_root,
        source=payload.source,
        profile=payload.profile,
        reuse_existing=payload.reuse_existing,
    )
    created_at = datetime.fromisoformat(session["created_at"])
    return ChatSessionCreateResponse(
        session_id=session["session_id"],
        created_at=created_at,
        reused=reused,
        memory_snapshot=session.get("memory_snapshot", {}),
    )


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageAcceptedResponse)
async def send_chat_message(
    session_id: str,
    payload: ChatMessageRequest,
    request: Request,
) -> ChatMessageAcceptedResponse:
    runtime = _get_runtime(request)
    store = _get_store(request)
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}")

    run_id = str(uuid.uuid4())
    asyncio.create_task(
        runtime.process_message(
            session_id=session_id,
            run_id=run_id,
            message_id=payload.message_id or str(uuid.uuid4()),
            content=payload.content,
        )
    )
    return ChatMessageAcceptedResponse(session_id=session_id, run_id=run_id, accepted=True)


@router.post("/sessions/{session_id}/tool-decisions", response_model=ChatToolDecisionResponse)
async def submit_tool_decision(
    session_id: str,
    payload: ChatToolDecisionRequest,
    request: Request,
) -> ChatToolDecisionResponse:
    runtime = _get_runtime(request)
    store = _get_store(request)
    if not store.get_session(session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}")

    run_id = str(uuid.uuid4())
    asyncio.create_task(
        runtime.process_tool_decision(
            session_id=session_id,
            run_id=run_id,
            tool_call_id=payload.tool_call_id,
            decision=payload.decision,
            edited_args=payload.edited_args,
        )
    )
    return ChatToolDecisionResponse(session_id=session_id, run_id=run_id, accepted=True)


@router.get("/sessions/{session_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    request: Request,
    limit: int = 200,
) -> ChatHistoryResponse:
    store = _get_store(request)
    history = store.history(session_id, limit=limit)
    if not history:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}")

    messages = [ChatMessageDto.model_validate(item) for item in history.get("messages", [])]
    events = [ChatEventDto.model_validate(item) for item in history.get("events", [])]
    pending_tool_calls = [
        ChatPendingToolCallDto.model_validate(item) for item in history.get("pending_tool_calls", [])
    ]
    return ChatHistoryResponse(
        session_id=history["session_id"],
        project_root=history["project_root"],
        source=history.get("source", "chat"),
        profile=history.get("profile", "quick"),
        status=history.get("status", "active"),
        messages=messages,
        events=events,
        pending_tool_calls=pending_tool_calls,
        memory_snapshot=history.get("memory_snapshot", {}),
        updated_at=datetime.fromisoformat(history["updated_at"]),
    )


@router.get("/sessions/{session_id}/stream")
async def stream_chat_events(session_id: str, request: Request):
    store = _get_store(request)
    if not store.get_session(session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}")

    async def event_stream():
        idx = 0
        while True:
            if await request.is_disconnected():
                return
            events, idx = store.list_events(session_id, idx)
            if not events:
                await asyncio.sleep(0.2)
                continue
            for event in events:
                payload = ChatEventDto.model_validate(event).model_dump(by_alias=True, mode="json")
                yield f"event: {payload['eventType']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

