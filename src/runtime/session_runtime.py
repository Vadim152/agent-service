"""Shared contracts for session-oriented runtimes."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from infrastructure.runtime_errors import ChatRuntimeError


class SessionRuntime(Protocol):
    """Runtime contract used by `/sessions` control-plane routes."""

    name: str

    async def create_session(
        self,
        *,
        project_root: str,
        source: str,
        profile: str,
        reuse_existing: bool,
        zephyr_auth: dict[str, Any] | None = None,
        jira_instance: str | None = None,
    ) -> dict[str, Any]: ...

    async def list_sessions(self, *, project_root: str, limit: int = 50) -> dict[str, Any]: ...

    async def has_session(self, session_id: str) -> bool: ...

    async def process_message(
        self,
        *,
        session_id: str,
        run_id: str,
        message_id: str,
        content: str,
        display_text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def get_history(self, *, session_id: str, limit: int = 200) -> dict[str, Any]: ...

    async def get_status(self, *, session_id: str) -> dict[str, Any]: ...

    async def get_diff(self, *, session_id: str) -> dict[str, Any]: ...

    async def execute_command(self, *, session_id: str, command: str) -> dict[str, Any]: ...

    async def process_tool_decision(
        self,
        *,
        session_id: str,
        run_id: str,
        permission_id: str,
        decision: str,
    ) -> None: ...

    async def stream_events(
        self,
        *,
        session_id: str,
        from_index: int = 0,
    ) -> AsyncIterator[bytes]: ...

    def describe_registered_tools(self) -> list[dict[str, Any]]: ...


class SessionRuntimeRegistry:
    """Registry and resolver for session runtimes."""

    def __init__(self, *, state_store: Any, default_runtime: str = "chat") -> None:
        self._state_store = state_store
        self._default_runtime = default_runtime
        self._runtimes: dict[str, SessionRuntime] = {}

    def register(self, runtime: SessionRuntime) -> None:
        self._runtimes[runtime.name] = runtime

    def get(self, runtime_name: str | None) -> SessionRuntime:
        resolved = str(runtime_name or self._default_runtime).strip().lower() or self._default_runtime
        runtime = self._runtimes.get(resolved)
        if runtime is None:
            raise ChatRuntimeError(f"Unsupported session runtime: {resolved}", status_code=422)
        return runtime

    def resolve_session(self, session_id: str) -> SessionRuntime:
        session = self._state_store.get_session(session_id)
        if not session:
            raise ChatRuntimeError(f"Session not found: {session_id}", status_code=404)
        return self.get(str(session.get("runtime", self._default_runtime)))

    def all_tools(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for runtime in self._runtimes.values():
            items.extend(runtime.describe_registered_tools())
        return items
