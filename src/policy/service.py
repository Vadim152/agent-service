"""Policy service for tool registry, approvals, and audit views."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any
from uuid import uuid4

from infrastructure.runtime_errors import ChatRuntimeError
from policy.store import PolicyStore


DecisionExecutor = Callable[[str, str, str, str], Awaitable[None]]


class PolicyService:
    def __init__(
        self,
        *,
        state_store: Any,
        store: PolicyStore,
        decision_executor: DecisionExecutor | None = None,
    ) -> None:
        self._state_store = state_store
        self._store = store
        self._decision_executor = decision_executor

    def bind_decision_executor(self, executor: DecisionExecutor) -> None:
        self._decision_executor = executor

    def sync_tools(self, tools: list[dict[str, Any]]) -> None:
        for tool in tools:
            self._store.upsert_tool(tool)

    async def list_tools(self) -> list[dict[str, Any]]:
        return self._store.list_tools()

    async def list_pending_approvals(self) -> list[dict[str, Any]]:
        items = self._list_pending_from_store()
        return [self._normalize_pending(item) for item in items]

    async def get_pending_approval(self, approval_id: str) -> dict[str, Any] | None:
        item = self._get_pending_from_store(approval_id)
        if not item:
            return None
        return self._normalize_pending(item)

    async def submit_decision(
        self,
        *,
        approval_id: str,
        decision: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        if decision not in {"approve", "deny"}:
            raise ChatRuntimeError(f"Unsupported policy decision: {decision}", status_code=422)
        runtime_decision = "approve_once" if decision == "approve" else "reject"
        return await self._submit(
            approval_id=approval_id,
            public_decision=decision,
            runtime_decision=runtime_decision,
            run_id=run_id,
        )

    async def submit_runtime_decision(
        self,
        *,
        approval_id: str,
        decision: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        mapping = {
            "approve_once": "approve",
            "approve_always": "approve",
            "reject": "deny",
        }
        public_decision = mapping.get(decision)
        if public_decision is None:
            raise ChatRuntimeError(f"Unsupported runtime decision: {decision}", status_code=422)
        return await self._submit(
            approval_id=approval_id,
            public_decision=public_decision,
            runtime_decision=decision,
            run_id=run_id,
        )

    async def _submit(
        self,
        *,
        approval_id: str,
        public_decision: str,
        runtime_decision: str,
        run_id: str | None,
    ) -> dict[str, Any]:
        pending = await self.get_pending_approval(approval_id)
        if not pending:
            raise ChatRuntimeError(f"Permission not found: {approval_id}", status_code=404)
        if self._decision_executor is None:
            raise ChatRuntimeError("Policy decision executor is not configured", status_code=503)
        effective_run_id = run_id or str(uuid4())
        await self._decision_executor(
            pending["sessionId"],
            effective_run_id,
            approval_id,
            runtime_decision,
        )
        self.record_approval_decision(
            pending={
                "tool_call_id": pending["approvalId"],
                "session_id": pending["sessionId"],
                "tool_name": pending["toolName"],
                "args": pending.get("metadata", {}),
                "created_at": pending["createdAt"],
            },
            run_id=effective_run_id,
            decision=runtime_decision,
            accepted=public_decision == "approve",
        )
        if public_decision == "approve" and pending["toolName"] == "save_generated_feature":
            self.append_audit_event(
                session_id=pending["sessionId"],
                event_type="autotest.saved",
                payload={
                    "sessionId": pending["sessionId"],
                    "permissionId": approval_id,
                    "runId": effective_run_id,
                },
            )
        return {
            "approvalId": approval_id,
            "sessionId": pending["sessionId"],
            "runId": effective_run_id,
            "decision": public_decision,
            "accepted": True,
        }

    def record_approval_requested(self, pending: dict[str, Any]) -> None:
        normalized = self._normalize_pending(pending)
        self.append_audit_event(
            session_id=normalized["sessionId"],
            event_type="permission.requested",
            payload={
                "sessionId": normalized["sessionId"],
                "permissionId": normalized["approvalId"],
                "toolName": normalized["toolName"],
            },
        )

    def record_approval_decision(
        self,
        *,
        pending: dict[str, Any],
        run_id: str,
        decision: str,
        accepted: bool,
    ) -> None:
        normalized = self._normalize_pending(pending)
        payload = {
            "decisionId": str(uuid4()),
            "approvalId": normalized["approvalId"],
            "sessionId": normalized["sessionId"],
            "runId": run_id,
            "toolName": normalized["toolName"],
            "decision": "approve" if decision in {"approve_once", "approve_always"} else "deny",
            "accepted": accepted,
        }
        self._store.append_approval_decision(payload)
        event_type = "permission.approved" if accepted else "permission.rejected"
        self.append_audit_event(
            session_id=normalized["sessionId"],
            event_type=event_type,
            payload={
                "sessionId": normalized["sessionId"],
                "permissionId": normalized["approvalId"],
                "decision": payload["decision"],
                "runId": run_id,
            },
        )

    def append_audit_event(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str | None = None,
    ) -> dict[str, Any]:
        return self._store.append_audit_event(
            session_id=session_id,
            event_type=event_type,
            payload=deepcopy(payload),
            created_at=created_at,
        )

    async def list_audit_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._store.list_audit_events(limit=limit)

    def _list_pending_from_store(self) -> list[dict[str, Any]]:
        items = self._store.list_pending_approvals()
        if items:
            return items
        if self._state_store is None:
            return []
        return self._state_store.list_pending_tool_calls()

    def _get_pending_from_store(self, approval_id: str) -> dict[str, Any] | None:
        item = self._store.get_pending_approval(approval_id)
        if item is not None:
            return item
        if self._state_store is None:
            return None
        return self._state_store.find_pending_tool_call(approval_id)

    @staticmethod
    def _normalize_pending(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "approvalId": str(item.get("tool_call_id") or item.get("approvalId") or ""),
            "sessionId": str(item.get("session_id") or item.get("sessionId") or ""),
            "toolName": str(item.get("tool_name") or item.get("toolName") or ""),
            "title": str(item.get("title") or item.get("tool_name") or item.get("toolName") or ""),
            "kind": str(item.get("kind", "tool")),
            "riskLevel": str(item.get("risk_level") or item.get("riskLevel") or "read"),
            "requiresConfirmation": bool(item.get("requires_confirmation", item.get("requiresConfirmation", True))),
            "metadata": deepcopy(item.get("args") or item.get("metadata") or {}),
            "createdAt": str(item.get("created_at") or item.get("createdAt") or ""),
        }
