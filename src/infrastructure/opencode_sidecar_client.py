"""Async client for the local OpenCode wrapper sidecar."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


class OpencodeSidecarError(RuntimeError):
    """Raised when sidecar responds with an error payload."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class OpencodeSidecarClient:
    def __init__(self, *, base_url: str, timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def create_session(
        self,
        *,
        project_root: str,
        source: str,
        profile: str,
        reuse_existing: bool,
    ) -> dict[str, Any]:
        payload = {
            "projectRoot": project_root,
            "source": source,
            "profile": profile,
            "reuseExisting": reuse_existing,
        }
        return await self._post_json("/internal/sessions", payload)

    async def prompt_async(
        self,
        *,
        session_id: str,
        message_id: str,
        content: str,
    ) -> dict[str, Any]:
        payload = {"messageId": message_id, "content": content}
        return await self._post_json(f"/internal/sessions/{session_id}/prompt-async", payload)

    async def reply_permission(
        self,
        *,
        session_id: str,
        permission_id: str,
        response: str,
    ) -> dict[str, Any]:
        payload = {"response": response}
        return await self._post_json(
            f"/internal/sessions/{session_id}/permissions/{permission_id}",
            payload,
        )

    async def get_history(self, *, session_id: str, limit: int = 200) -> dict[str, Any]:
        params = {"limit": max(1, min(limit, 500))}
        return await self._get_json(f"/internal/sessions/{session_id}/history", params=params)

    async def get_status(self, *, session_id: str) -> dict[str, Any]:
        return await self._get_json(f"/internal/sessions/{session_id}/status")

    async def get_diff(self, *, session_id: str) -> dict[str, Any]:
        return await self._get_json(f"/internal/sessions/{session_id}/diff")

    async def execute_command(self, *, session_id: str, command: str) -> dict[str, Any]:
        payload = {"command": command}
        return await self._post_json(f"/internal/sessions/{session_id}/commands", payload)

    async def stream_events(
        self,
        *,
        session_id: str,
        from_index: int = 0,
    ) -> AsyncIterator[bytes]:
        timeout = httpx.Timeout(connect=5.0, read=None, write=10.0, pool=5.0)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
            async with client.stream(
                "GET",
                f"/internal/sessions/{session_id}/events",
                params={"fromIndex": max(0, from_index)},
            ) as response:
                if response.status_code >= 400:
                    detail = await self._error_detail(response)
                    raise OpencodeSidecarError(
                        f"Sidecar stream error ({response.status_code}): {detail}",
                        status_code=response.status_code,
                    )
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_s) as client:
            response = await client.post(path, json=payload)
        return await self._decode_response(response)

    async def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_s) as client:
            response = await client.get(path, params=params)
        return await self._decode_response(response)

    async def _decode_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            detail = await self._error_detail(response)
            raise OpencodeSidecarError(
                f"Sidecar error ({response.status_code}): {detail}",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise OpencodeSidecarError("Sidecar returned invalid JSON payload") from exc
        if not isinstance(payload, dict):
            raise OpencodeSidecarError("Sidecar returned unsupported payload type")
        return payload

    async def _error_detail(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:
            return response.text.strip() or "unknown sidecar error"
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str) and detail:
                return detail
        return response.text.strip() or "unknown sidecar error"
