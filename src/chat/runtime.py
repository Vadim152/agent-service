"""Chat runtime backed by OpenCode sidecar."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from infrastructure.opencode_sidecar_client import OpencodeSidecarClient, OpencodeSidecarError


_DECISION_MAP = {
    "approve_once": "once",
    "approve_always": "always",
    "reject": "reject",
}


class ChatAgentRuntime:
    def __init__(self, *, sidecar_client: OpencodeSidecarClient) -> None:
        self.sidecar_client = sidecar_client
        self._known_sessions: set[str] = set()

    async def create_session(
        self,
        *,
        project_root: str,
        source: str,
        profile: str,
        reuse_existing: bool,
    ) -> dict[str, Any]:
        payload = await self.sidecar_client.create_session(
            project_root=project_root,
            source=source,
            profile=profile,
            reuse_existing=reuse_existing,
        )
        session_id = str(payload.get("sessionId", "")).strip()
        if session_id:
            self._known_sessions.add(session_id)
        return payload

    async def has_session(self, session_id: str) -> bool:
        if session_id in self._known_sessions:
            return True
        try:
            await self.sidecar_client.get_history(session_id=session_id, limit=1)
        except OpencodeSidecarError as exc:
            if exc.status_code == 404:
                return False
            raise
        self._known_sessions.add(session_id)
        return True

    async def process_message(
        self,
        *,
        session_id: str,
        run_id: str,
        message_id: str,
        content: str,
    ) -> None:
        _ = run_id
        await self.sidecar_client.prompt_async(
            session_id=session_id,
            message_id=message_id or str(uuid.uuid4()),
            content=content,
        )

    async def process_tool_decision(
        self,
        *,
        session_id: str,
        run_id: str,
        permission_id: str,
        decision: str,
    ) -> None:
        _ = run_id
        normalized = _DECISION_MAP.get(decision)
        if not normalized:
            raise ValueError(f"Unsupported decision: {decision}")
        await self.sidecar_client.reply_permission(
            session_id=session_id,
            permission_id=permission_id,
            response=normalized,
        )

    async def get_history(self, *, session_id: str, limit: int = 200) -> dict[str, Any]:
        self._known_sessions.add(session_id)
        return await self.sidecar_client.get_history(session_id=session_id, limit=limit)

    async def list_sessions(self, *, project_root: str, limit: int = 50) -> dict[str, Any]:
        payload = await self.sidecar_client.get_sessions(project_root=project_root, limit=limit)
        for item in payload.get("items", []):
            session_id = str(item.get("sessionId", "")).strip()
            if session_id:
                self._known_sessions.add(session_id)
        return payload

    async def get_status(self, *, session_id: str) -> dict[str, Any]:
        self._known_sessions.add(session_id)
        return await self.sidecar_client.get_status(session_id=session_id)

    async def get_diff(self, *, session_id: str) -> dict[str, Any]:
        self._known_sessions.add(session_id)
        return await self.sidecar_client.get_diff(session_id=session_id)

    async def execute_command(self, *, session_id: str, command: str) -> dict[str, Any]:
        self._known_sessions.add(session_id)
        return await self.sidecar_client.execute_command(
            session_id=session_id,
            command=command,
        )

    async def stream_events(
        self,
        *,
        session_id: str,
        from_index: int = 0,
    ) -> AsyncIterator[bytes]:
        self._known_sessions.add(session_id)
        async for chunk in self.sidecar_client.stream_events(
            session_id=session_id,
            from_index=from_index,
        ):
            yield chunk
