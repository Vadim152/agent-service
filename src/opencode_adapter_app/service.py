from __future__ import annotations

import itertools
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from opencode_adapter_app.errors import AdapterApiError
from opencode_adapter_app.resource_discovery import (
    collect_candidate_roots,
    discover_resource_entries,
    extract_agents,
    extract_agents_from_raw_config,
    extract_commands,
    extract_commands_from_raw_config,
    extract_mcps,
    extract_mcps_from_raw_config,
    extract_tool_details,
    extract_tool_ids,
    flatten_models_from_provider_payload,
    flatten_models_from_raw_config,
    load_json_file,
    render_command_prompt,
)
from opencode_adapter_app.schemas import (
    AdapterAgentDto,
    AdapterAgentsResponse,
    AdapterApprovalDecisionRequest,
    AdapterApprovalDecisionResponse,
    AdapterApprovalStatusDto,
    AdapterConfigSnapshotResponse,
    AdapterCommandCatalogSummaryDto,
    AdapterCommandDto,
    AdapterCommandExecutionRequest,
    AdapterCommandExecutionResponse,
    AdapterCommandsResponse,
    AdapterMcpDto,
    AdapterMcpsResponse,
    AdapterModelDto,
    AdapterModelsResponse,
    AdapterProviderDto,
    AdapterProvidersResponse,
    AdapterResourceEntryDto,
    AdapterResourcesResponse,
    AdapterRunCancelResponse,
    AdapterRunCreateRequest,
    AdapterRunCreateResponse,
    AdapterRunEventDto,
    AdapterRunEventsResponse,
    AdapterRunStatusResponse,
    AdapterSessionCommandRequest,
    AdapterSessionCommandResponse,
    AdapterSessionDetailsResponse,
    AdapterSessionDiffResponse,
    AdapterSessionDto,
    AdapterSessionEventsResponse,
    AdapterSessionEnsureRequest,
    AdapterToolDto,
    AdapterToolsResponse,
)
from opencode_adapter_app.state_store import OpenCodeAdapterStateStore, utcnow


TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled"}


class OpenCodeAdapterService:
    def __init__(
        self,
        *,
        settings: Any,
        state_store: OpenCodeAdapterStateStore,
        process_supervisor: Any,
        headless_server: Any | None = None,
    ) -> None:
        self._settings = settings
        self._state_store = state_store
        self._process_supervisor = process_supervisor
        self._headless_server = headless_server
        self._id_counter = itertools.count(1)

    def ensure_session(self, request: AdapterSessionEnsureRequest) -> AdapterSessionDto:
        external_session_id = str(request.external_session_id or "").strip()
        if not external_session_id:
            raise AdapterApiError(
                "validation_error",
                "externalSessionId must not be empty",
                status_code=422,
            )
        project_root = self._normalize_project_root(request.project_root)
        existing = self._state_store.get_session_mapping(external_session_id)
        if existing is not None:
            mapped_project_root = str(existing.get("project_root") or "").strip()
            if mapped_project_root and _normalized_path(mapped_project_root) != _normalized_path(project_root):
                raise AdapterApiError(
                    "project_root_mismatch",
                    f"projectRoot mismatch for existing sessionId: expected {mapped_project_root}, got {project_root}",
                    status_code=422,
                    details={"expectedProjectRoot": mapped_project_root, "actualProjectRoot": project_root},
                )
            self._state_store.ensure_session_diff(
                external_session_id=external_session_id,
                backend_session_id=str(existing.get("backend_session_id") or "").strip() or None,
            )
            return self._session_dto(existing)

        if self._settings.runner_type == "raw_json_runner":
            backend_session_id = f"session-{abs(hash(external_session_id)) % 100000}"
        else:
            payload = self._process_supervisor.create_backend_session(
                project_root=project_root,
                external_session_id=external_session_id,
            )
            backend_session_id = str(payload.get("id") or "").strip()
            if not backend_session_id:
                raise AdapterApiError(
                    "backend_unavailable",
                    "OpenCode did not return a backend session id.",
                    status_code=503,
                    retryable=True,
                )

        provider_id, model_id = self._resolve_provider_model(None, None)
        mapping = self._state_store.upsert_session_mapping(
            external_session_id,
            backend_session_id=backend_session_id,
            project_root=project_root,
            last_backend_run_id=None,
            status="idle",
            current_action="Idle",
            last_activity_at=utcnow().isoformat(),
            last_provider_id=provider_id,
            last_model_id=model_id,
        )
        self._state_store.ensure_session_diff(
            external_session_id=external_session_id,
            backend_session_id=backend_session_id,
        )
        return self._session_dto(mapping)

    def get_session(self, external_session_id: str) -> AdapterSessionDto:
        mapping = self._require_session_mapping(external_session_id)
        return self._session_dto(mapping)

    def create_run(self, request: AdapterRunCreateRequest) -> AdapterRunCreateResponse:
        project_root = self._normalize_project_root(request.project_root)
        if not str(request.prompt or "").strip():
            raise AdapterApiError("validation_error", "prompt must not be empty", status_code=422)

        backend_session_id = request.backend_session_id
        session_mapping = None
        if request.session_id:
            session_mapping = self.ensure_session(
                AdapterSessionEnsureRequest(
                    externalSessionId=request.session_id,
                    projectRoot=project_root,
                    source=request.source,
                    profile=request.profile,
                )
            )
            backend_session_id = str(session_mapping.backend_session_id or "").strip() or backend_session_id

        backend_run_id = f"oc-adapter-{next(self._id_counter)}"
        now = utcnow().isoformat()
        run = {
            "backend_run_id": backend_run_id,
            "external_run_id": request.run_id,
            "external_session_id": request.session_id,
            "backend_session_id": backend_session_id,
            "project_root": project_root,
            "prompt": request.prompt,
            "source": request.source,
            "profile": request.profile,
            "config_profile": request.config_profile,
            "policy_mode": request.policy_mode,
            "status": "queued",
            "current_action": "Queued",
            "result": None,
            "output": None,
            "artifacts": [],
            "pending_approvals": [],
            "cancel_requested": False,
            "exit_code": None,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "updated_at": now,
            "work_dir": str((self._settings.work_root / "runs" / backend_run_id).resolve()),
        }
        self._state_store.create_run(run)
        if request.session_id:
            self._state_store.upsert_session_mapping(
                str(request.session_id),
                backend_session_id=str(backend_session_id or "").strip() or None,
                project_root=project_root,
                last_backend_run_id=backend_run_id,
                status="queued",
                current_action="Queued",
                last_activity_at=now,
            )
        self._state_store.append_event(
            backend_run_id,
            "run.queued",
            {"backendRunId": backend_run_id, "runId": request.run_id},
        )
        self._process_supervisor.start_run(run)
        stored = self._require_run(backend_run_id)
        return AdapterRunCreateResponse(
            backendRunId=backend_run_id,
            backendSessionId=stored.get("backend_session_id"),
            status=stored["status"],
            currentAction=stored.get("current_action") or "Queued",
            createdAt=stored["created_at"],
            startedAt=stored.get("started_at"),
        )

    def get_run(self, backend_run_id: str) -> AdapterRunStatusResponse:
        run = self._require_run(backend_run_id)
        approvals = self._approval_dtos(run.get("approvals") or [])
        pending = [item for item in approvals if item.status == "pending"]
        return AdapterRunStatusResponse(
            backendRunId=backend_run_id,
            backendSessionId=run.get("backend_session_id"),
            status=run["status"],
            currentAction=run.get("current_action") or "Queued",
            result=run.get("result"),
            output=run.get("output"),
            artifacts=run.get("artifacts") or [],
            pendingApprovals=pending,
            approvals=approvals,
            totals=run.get("totals"),
            limits=run.get("limits"),
            createdAt=run["created_at"],
            startedAt=run.get("started_at"),
            finishedAt=run.get("finished_at"),
            exitCode=run.get("exit_code"),
            updatedAt=run["updated_at"],
        )

    def list_events(self, backend_run_id: str, *, after: int, limit: int) -> AdapterRunEventsResponse:
        self._require_run(backend_run_id)
        events, next_cursor, has_more, oldest_cursor, stale = self._state_store.list_events(
            backend_run_id,
            after=after,
            limit=limit,
        )
        if stale:
            raise AdapterApiError(
                "stale_cursor",
                "Requested events cursor is outside the retention window.",
                status_code=409,
                details={"oldestCursor": oldest_cursor, "nextCursor": next_cursor},
            )
        return AdapterRunEventsResponse(
            items=[
                AdapterRunEventDto(
                    eventType=item["event_type"],
                    payload=item["payload"],
                    createdAt=item["created_at"],
                    index=item["index"],
                )
                for item in events
            ],
            nextCursor=next_cursor,
            hasMore=has_more,
        )

    def cancel_run(self, backend_run_id: str) -> AdapterRunCancelResponse:
        run = self._require_run(backend_run_id)
        if str(run.get("status") or "") in TERMINAL_RUN_STATUSES:
            return AdapterRunCancelResponse(
                backendRunId=backend_run_id,
                status=str(run.get("status") or "cancelled"),
                updatedAt=run.get("updated_at") or utcnow(),
            )
        updated = self._process_supervisor.cancel_run(backend_run_id)
        return AdapterRunCancelResponse(
            backendRunId=backend_run_id,
            status=str(updated.get("status") or "cancelled"),
            updatedAt=updated.get("updated_at") or utcnow(),
        )

    def submit_approval_decision(
        self,
        backend_run_id: str,
        approval_id: str,
        request: AdapterApprovalDecisionRequest,
    ) -> AdapterApprovalDecisionResponse:
        current = self._state_store.get_approval(backend_run_id, approval_id)
        if current is None:
            raise AdapterApiError(
                "approval_not_found",
                f"Approval not found: {approval_id}",
                status_code=404,
            )
        requested_status = "approved" if request.decision == "approve" else "denied"
        current_status = str(current.get("status") or "").strip()
        if current_status in {"approved", "denied"}:
            if current_status == requested_status:
                run = self._require_run(backend_run_id)
                return AdapterApprovalDecisionResponse(
                    backendRunId=backend_run_id,
                    approvalId=approval_id,
                    decision=request.decision,
                    status=str(run.get("status") or "running"),
                    updatedAt=current.get("updatedAt") or run.get("updated_at") or utcnow(),
                )
            raise AdapterApiError(
                "approval_already_resolved",
                f"Approval already resolved: {approval_id}",
                status_code=409,
                details={"currentStatus": current_status},
            )
        updated = self._process_supervisor.submit_approval_decision(backend_run_id, approval_id, request.decision)
        self._state_store.resolve_approval(backend_run_id, approval_id, request.decision)
        return AdapterApprovalDecisionResponse(
            backendRunId=backend_run_id,
            approvalId=approval_id,
            decision=request.decision,
            status=str(updated.get("status") or "running"),
            updatedAt=updated.get("updated_at") or utcnow(),
        )

    def compact_session(self, external_session_id: str) -> AdapterSessionCommandResponse:
        mapping = self._require_session_mapping(external_session_id)
        active_run = self._state_store.find_active_run_for_session(external_session_id)
        if active_run is not None or self._state_store.has_pending_approvals_for_session(external_session_id):
            raise AdapterApiError(
                "session_busy",
                "Session is busy and cannot be compacted.",
                status_code=409,
                details={"activeRunId": (active_run or {}).get("backend_run_id")},
            )
        last_activity_at = str(mapping.get("last_activity_at") or "").strip()
        last_compaction_at = str(mapping.get("last_compaction_at") or "").strip()
        if last_compaction_at and last_activity_at and last_activity_at <= last_compaction_at:
            return AdapterSessionCommandResponse(
                externalSessionId=external_session_id,
                command="compact",
                accepted=True,
                result={"status": "noop", "backendSessionId": mapping.get("backend_session_id")},
                updatedAt=mapping.get("updated_at") or utcnow(),
            )

        backend_session_id = str(mapping.get("backend_session_id") or "").strip()
        if not backend_session_id:
            raise AdapterApiError(
                "session_not_found",
                f"Session mapping is missing backend session id: {external_session_id}",
                status_code=404,
            )

        provider_id, model_id = self._resolve_provider_model(
            mapping.get("last_provider_id"),
            mapping.get("last_model_id"),
        )
        if self._settings.runner_type != "raw_json_runner":
            self._process_supervisor.compact_session(
                project_root=str(mapping.get("project_root") or ""),
                backend_session_id=backend_session_id,
                provider_id=provider_id,
                model_id=model_id,
            )
        compacted_at = utcnow().isoformat()
        updated = self._state_store.upsert_session_mapping(
            external_session_id,
            status="idle",
            current_action="Idle",
            last_compaction_at=compacted_at,
            last_activity_at=compacted_at,
            last_provider_id=provider_id,
            last_model_id=model_id,
        )
        return AdapterSessionCommandResponse(
            externalSessionId=external_session_id,
            command="compact",
            accepted=True,
            result={
                "status": "completed",
                "backendSessionId": backend_session_id,
                "providerId": provider_id,
                "modelId": model_id,
            },
            updatedAt=updated.get("updated_at") or utcnow(),
        )

    def get_session_diff(self, external_session_id: str) -> AdapterSessionDiffResponse:
        mapping = self._require_session_mapping(external_session_id)
        cached = self._state_store.get_session_diff(external_session_id)
        backend_session_id = str(mapping.get("backend_session_id") or "").strip()
        if self._settings.runner_type != "raw_json_runner" and backend_session_id:
            try:
                live_diff = self._process_supervisor.fetch_session_diff(
                    project_root=str(mapping.get("project_root") or ""),
                    backend_session_id=backend_session_id,
                )
                summary = _normalize_diff_summary(live_diff.get("summary"), live_diff.get("files"))
                files = _normalize_diff_files(live_diff.get("files"))
                self._state_store.set_session_diff(
                    external_session_id=external_session_id,
                    backend_session_id=backend_session_id,
                    summary=summary,
                    files=files,
                    stale=False,
                )
                cached = self._state_store.get_session_diff(external_session_id)
            except Exception:
                if cached is None:
                    raise AdapterApiError(
                        "diff_unavailable",
                        "Session diff is temporarily unavailable.",
                        status_code=503,
                        retryable=True,
                    )
                self._state_store.set_session_diff(
                    external_session_id=external_session_id,
                    backend_session_id=backend_session_id,
                    summary=dict(cached.get("summary") or {}),
                    files=list(cached.get("files") or []),
                    stale=True,
                )
                cached = self._state_store.get_session_diff(external_session_id)

        if cached is None:
            raise AdapterApiError(
                "diff_unavailable",
                "Session diff is temporarily unavailable.",
                status_code=503,
                retryable=True,
            )
        return AdapterSessionDiffResponse(
            externalSessionId=external_session_id,
            backendSessionId=cached.get("backend_session_id"),
            summary=cached.get("summary") or {"files": 0, "additions": 0, "deletions": 0},
            files=cached.get("files") or [],
            stale=bool(cached.get("stale", False)),
            updatedAt=cached.get("updated_at") or utcnow(),
        )

    def execute_session_command(
        self,
        external_session_id: str,
        payload: AdapterSessionCommandRequest,
    ) -> AdapterSessionCommandResponse:
        command = str(payload.command or "").strip().lower()
        if command == "status":
            session = self.get_session(external_session_id)
            return AdapterSessionCommandResponse(
                externalSessionId=external_session_id,
                command=command,
                accepted=True,
                result={"status": session.model_dump(by_alias=True, mode="json")},
                updatedAt=session.updated_at,
            )
        if command == "diff":
            diff = self.get_session_diff(external_session_id)
            return AdapterSessionCommandResponse(
                externalSessionId=external_session_id,
                command=command,
                accepted=True,
                result={"diff": diff.model_dump(by_alias=True, mode="json")},
                updatedAt=diff.updated_at,
            )
        if command == "compact":
            return self.compact_session(external_session_id)
        if command == "help":
            mapping = self._require_session_mapping(external_session_id)
            return AdapterSessionCommandResponse(
                externalSessionId=external_session_id,
                command=command,
                accepted=True,
                result={"commands": ["status", "diff", "compact", "abort", "help"]},
                updatedAt=mapping.get("updated_at") or utcnow(),
            )
        if command == "abort":
            active_run = self._state_store.find_active_run_for_session(external_session_id)
            if active_run is None:
                mapping = self._require_session_mapping(external_session_id)
                return AdapterSessionCommandResponse(
                    externalSessionId=external_session_id,
                    command=command,
                    accepted=True,
                    result={"status": "noop", "message": "No active run to cancel."},
                    updatedAt=mapping.get("updated_at") or utcnow(),
                )
            cancelled = self.cancel_run(str(active_run["backend_run_id"]))
            return AdapterSessionCommandResponse(
                externalSessionId=external_session_id,
                command=command,
                accepted=True,
                result={"cancel": cancelled.model_dump(by_alias=True, mode="json")},
                updatedAt=cancelled.updated_at,
            )
        raise AdapterApiError(
            "validation_error",
            f"Unsupported command: {command}",
            status_code=422,
        )

    def list_commands(self, *, project_root: str | None = None) -> AdapterCommandsResponse:
        normalized_project_root = self._normalize_optional_project_root(project_root)
        raw_config = self._load_raw_config(normalized_project_root)
        items = extract_commands_from_raw_config(raw_config)
        if self._settings.runner_type != "raw_json_runner":
            payload = self._server_request("GET", "/command", project_root=normalized_project_root)
            items = extract_commands(payload)
        updated_at = utcnow()
        return AdapterCommandsResponse(
            items=[AdapterCommandDto.model_validate(item) for item in items],
            total=len(items),
            updatedAt=updated_at,
        )

    def execute_command(
        self,
        command_id: str,
        payload: AdapterCommandExecutionRequest,
    ) -> AdapterCommandExecutionResponse:
        commands = self.list_commands(project_root=payload.project_root).items
        command = next((item for item in commands if item.name == command_id), None)
        if command is None:
            raise AdapterApiError(
                "command_not_found",
                f"Command not found: {command_id}",
                status_code=404,
            )
        raw_command = command.model_dump(by_alias=True, mode="json")
        prompt = render_command_prompt(
            command=raw_command,
            arguments=list(payload.arguments or []),
            raw_input=payload.raw_input,
        )
        return AdapterCommandExecutionResponse(
            commandId=command_id,
            kind="prompt",
            prompt=prompt,
            result={"command": raw_command},
            updatedAt=utcnow(),
        )

    def list_agents(self, *, project_root: str | None = None) -> AdapterAgentsResponse:
        normalized_project_root = self._normalize_optional_project_root(project_root)
        raw_config = self._load_raw_config(normalized_project_root)
        items = extract_agents_from_raw_config(raw_config)
        if self._settings.runner_type != "raw_json_runner":
            payload = self._server_request("GET", "/agent", project_root=normalized_project_root)
            items = extract_agents(payload)
        return AdapterAgentsResponse(
            items=[AdapterAgentDto.model_validate(item) for item in items],
            total=len(items),
            updatedAt=utcnow(),
        )

    def list_mcps(self, *, project_root: str | None = None) -> AdapterMcpsResponse:
        normalized_project_root = self._normalize_optional_project_root(project_root)
        raw_config = self._load_raw_config(normalized_project_root)
        items = extract_mcps_from_raw_config(raw_config)
        if self._settings.runner_type != "raw_json_runner":
            payload = self._server_request("GET", "/mcp", project_root=normalized_project_root)
            items = extract_mcps(payload)
        return AdapterMcpsResponse(
            items=[AdapterMcpDto.model_validate(item) for item in items],
            total=len(items),
            updatedAt=utcnow(),
        )

    def list_providers(self, *, project_root: str | None = None) -> AdapterProvidersResponse:
        normalized_project_root = self._normalize_optional_project_root(project_root)
        raw_config = self._load_raw_config(normalized_project_root)
        providers, _ = flatten_models_from_raw_config(raw_config)
        if self._settings.runner_type != "raw_json_runner":
            payload = self._server_request("GET", "/provider", project_root=normalized_project_root)
            providers, _ = flatten_models_from_provider_payload(payload)
        return AdapterProvidersResponse(
            items=[AdapterProviderDto.model_validate(item) for item in providers],
            total=len(providers),
            updatedAt=utcnow(),
        )

    def list_models(self, *, project_root: str | None = None) -> AdapterModelsResponse:
        normalized_project_root = self._normalize_optional_project_root(project_root)
        raw_config = self._load_raw_config(normalized_project_root)
        _, models = flatten_models_from_raw_config(raw_config)
        if self._settings.runner_type != "raw_json_runner":
            payload = self._server_request("GET", "/provider", project_root=normalized_project_root)
            _, models = flatten_models_from_provider_payload(payload)
        return AdapterModelsResponse(
            items=[AdapterModelDto.model_validate(item) for item in models],
            total=len(models),
            updatedAt=utcnow(),
        )

    def list_tools(self, *, project_root: str | None = None) -> AdapterToolsResponse:
        normalized_project_root = self._normalize_optional_project_root(project_root)
        items: list[dict[str, Any]] = []
        if self._settings.runner_type != "raw_json_runner":
            ids_payload = self._server_request("GET", "/experimental/tool/ids", project_root=normalized_project_root)
            items = extract_tool_ids(ids_payload)
            snapshot = self.get_config_snapshot(project_root=normalized_project_root)
            provider_id, model_id = _split_model_identifier(snapshot.resolved_model)
            if provider_id and model_id:
                try:
                    details_payload = self._server_request(
                        "GET",
                        "/experimental/tool",
                        project_root=normalized_project_root,
                        params={"provider": provider_id, "model": model_id},
                    )
                    detailed_items = extract_tool_details(details_payload)
                    if detailed_items:
                        items = detailed_items
                except AdapterApiError:
                    pass
        return AdapterToolsResponse(
            items=[AdapterToolDto.model_validate(item) for item in items],
            total=len(items),
            updatedAt=utcnow(),
        )

    def list_resources(
        self,
        kind: str,
        *,
        project_root: str | None = None,
    ) -> AdapterResourcesResponse:
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind not in {"skill", "plugin", "hook"}:
            raise AdapterApiError(
                "validation_error",
                f"Unsupported resource kind: {kind}",
                status_code=422,
            )
        snapshot = self.get_config_snapshot(project_root=project_root)
        roots = collect_candidate_roots(
            project_root=project_root,
            active_project_root=snapshot.active_project_root,
            active_config_file=snapshot.active_config_file,
            active_config_dir=snapshot.active_config_dir,
        )
        items = discover_resource_entries(normalized_kind, roots=roots)
        return AdapterResourcesResponse(
            kind=normalized_kind,
            items=[AdapterResourceEntryDto.model_validate(item) for item in items],
            total=len(items),
            updatedAt=utcnow(),
        )

    def get_config_snapshot(self, *, project_root: str | None = None) -> AdapterConfigSnapshotResponse:
        normalized_project_root = self._normalize_optional_project_root(project_root)
        if normalized_project_root and self._settings.runner_type != "raw_json_runner" and self._headless_server is not None:
            self._headless_server.ensure_started(project_root=normalized_project_root)
        if self._headless_server is not None:
            snapshot = self._headless_server.debug_snapshot()
        else:
            snapshot = {
                "base_url": "",
                "server_running": False,
                "server_ready": False,
                "active_project_root": normalized_project_root,
                "active_config_file": self._settings.resolve_opencode_config_file(normalized_project_root),
                "active_config_dir": self._settings.resolve_opencode_config_dir(normalized_project_root),
                "resolved_providers": [],
                "resolved_model": self._settings.resolve_forced_model(),
                "raw_config": None,
                "config_error": None,
            }
        if normalized_project_root and not snapshot.get("active_project_root"):
            snapshot["active_project_root"] = normalized_project_root
        if normalized_project_root and not snapshot.get("active_config_file"):
            snapshot["active_config_file"] = self._settings.resolve_opencode_config_file(normalized_project_root)
        if normalized_project_root and not snapshot.get("active_config_dir"):
            snapshot["active_config_dir"] = self._settings.resolve_opencode_config_dir(normalized_project_root)
        if snapshot.get("raw_config") is None:
            raw_config = self._load_raw_config(normalized_project_root)
            if raw_config is not None:
                snapshot["raw_config"] = raw_config
                configured_providers, configured_models = flatten_models_from_raw_config(raw_config)
                if not snapshot.get("resolved_providers"):
                    snapshot["resolved_providers"] = [item["providerId"] for item in configured_providers]
                if not snapshot.get("resolved_model"):
                    configured_model = str(raw_config.get("model") or "").strip()
                    if configured_model:
                        snapshot["resolved_model"] = configured_model
                    elif configured_models:
                        first = configured_models[0]
                        snapshot["resolved_model"] = f"{first['providerId']}/{first['id']}"
        return AdapterConfigSnapshotResponse.model_validate(
            {
                "activeProjectRoot": snapshot.get("active_project_root"),
                "activeConfigFile": snapshot.get("active_config_file"),
                "activeConfigDir": snapshot.get("active_config_dir"),
                "resolvedProviders": snapshot.get("resolved_providers") or [],
                "resolvedModel": snapshot.get("resolved_model"),
                "rawConfig": snapshot.get("raw_config"),
                "configError": snapshot.get("config_error"),
                "serverRunning": bool(snapshot.get("server_running", False)),
                "serverReady": bool(snapshot.get("server_ready", False)),
                "baseUrl": str(snapshot.get("base_url") or ""),
            }
        )

    def get_session_details(
        self,
        external_session_id: str,
        *,
        project_root: str | None = None,
    ) -> AdapterSessionDetailsResponse:
        mapping = self._require_session_mapping(external_session_id)
        session = self.get_session(external_session_id)
        commands = self.list_commands(project_root=project_root or mapping.get("project_root"))
        mcps = self.list_mcps(project_root=project_root or mapping.get("project_root"))
        agent_id = self._resolve_session_agent(mapping)
        provider_id = str(mapping.get("last_provider_id") or "").strip() or None
        model_id = str(mapping.get("last_model_id") or "").strip() or None
        if not provider_id or not model_id:
            configured_model = self.get_config_snapshot(
                project_root=project_root or mapping.get("project_root")
            ).resolved_model
            configured_provider_id, configured_model_id = _split_model_identifier(configured_model)
            provider_id = provider_id or configured_provider_id
            model_id = model_id or configured_model_id
        return AdapterSessionDetailsResponse(
            session=session,
            agentId=agent_id,
            providerId=provider_id,
            modelId=model_id,
            pendingApprovalsCount=len(self._state_store.list_pending_approvals(str(mapping.get("last_backend_run_id") or "")))
            if mapping.get("last_backend_run_id")
            else 0,
            mcpCount=mcps.total,
            commandCatalog=AdapterCommandCatalogSummaryDto(
                total=commands.total,
                names=[item.name for item in commands.items],
                updatedAt=commands.updated_at,
            ),
            updatedAt=_parse_iso_datetime(mapping.get("updated_at")) or utcnow(),
        )

    def list_session_events(
        self,
        external_session_id: str,
        *,
        after: int,
        limit: int,
    ) -> AdapterSessionEventsResponse:
        mapping = self._require_session_mapping(external_session_id)
        backend_run_id = str(mapping.get("last_backend_run_id") or "").strip()
        if not backend_run_id:
            return AdapterSessionEventsResponse(
                externalSessionId=external_session_id,
                items=[],
                nextCursor=max(0, after),
                hasMore=False,
                updatedAt=_parse_iso_datetime(mapping.get("updated_at")) or utcnow(),
            )
        events = self.list_events(backend_run_id, after=after, limit=limit)
        return AdapterSessionEventsResponse(
            externalSessionId=external_session_id,
            items=events.items,
            nextCursor=events.next_cursor,
            hasMore=events.has_more,
            updatedAt=_parse_iso_datetime(mapping.get("updated_at")) or utcnow(),
        )

    def _require_run(self, backend_run_id: str) -> dict[str, Any]:
        run = self._state_store.get_run(backend_run_id)
        if not run:
            raise AdapterApiError(
                "run_not_found",
                f"Run not found: {backend_run_id}",
                status_code=404,
            )
        return run

    def _require_session_mapping(self, external_session_id: str) -> dict[str, Any]:
        mapping = self._state_store.get_session_mapping(external_session_id)
        if not mapping:
            raise AdapterApiError(
                "session_not_found",
                f"Session not found: {external_session_id}",
                status_code=404,
            )
        return mapping

    def _session_dto(self, mapping: dict[str, Any]) -> AdapterSessionDto:
        return AdapterSessionDto(
            externalSessionId=str(mapping["external_session_id"]),
            backendSessionId=mapping.get("backend_session_id"),
            projectRoot=str(mapping.get("project_root") or ""),
            lastBackendRunId=mapping.get("last_backend_run_id"),
            status=str(mapping.get("status") or "idle"),
            currentAction=str(mapping.get("current_action") or "Idle"),
            lastActivityAt=_parse_iso_datetime(mapping.get("last_activity_at")),
            lastCompactionAt=_parse_iso_datetime(mapping.get("last_compaction_at")),
            updatedAt=_parse_iso_datetime(mapping.get("updated_at")) or utcnow(),
            lastProviderId=mapping.get("last_provider_id"),
            lastModelId=mapping.get("last_model_id"),
        )

    def _approval_dtos(self, items: list[dict[str, Any]]) -> list[AdapterApprovalStatusDto]:
        return [
            AdapterApprovalStatusDto(
                approvalId=str(item.get("approvalId") or item.get("approval_id") or ""),
                toolName=str(item.get("toolName") or item.get("tool_name") or "opencode.tool"),
                title=str(item.get("title") or item.get("toolName") or "OpenCode approval"),
                kind=str(item.get("kind") or "tool"),
                riskLevel=str(item.get("riskLevel") or item.get("risk_level") or "high"),
                metadata=dict(item.get("metadata") or {}),
                status=str(item.get("status") or "pending"),
                updatedAt=_parse_iso_datetime(item.get("updatedAt")) or utcnow(),
            )
            for item in items
        ]

    def _normalize_project_root(self, project_root: str) -> str:
        if not str(project_root or "").strip():
            raise AdapterApiError("validation_error", "projectRoot must not be empty", status_code=422)
        return str(Path(project_root).resolve())

    def _normalize_optional_project_root(self, project_root: str | None) -> str | None:
        raw = str(project_root or "").strip()
        if not raw:
            return None
        return self._normalize_project_root(raw)

    def _resolve_provider_model(
        self,
        provider_id: str | None,
        model_id: str | None,
    ) -> tuple[str | None, str | None]:
        resolved_provider = str(provider_id or "").strip() or None
        resolved_model = str(model_id or "").strip() or None
        if resolved_provider and resolved_model:
            return resolved_provider, resolved_model
        forced = str(self._settings.resolve_forced_model() or "").strip()
        if "/" in forced:
            forced_provider, forced_model = forced.split("/", 1)
            return forced_provider or None, forced_model or None
        return resolved_provider, resolved_model

    def _resolve_session_agent(self, mapping: dict[str, Any]) -> str | None:
        backend_run_id = str(mapping.get("last_backend_run_id") or "").strip()
        if backend_run_id:
            run = self._state_store.get_run(backend_run_id) or {}
            profile = str(run.get("profile") or run.get("config_profile") or "").strip()
            if profile:
                return self._settings.agent_map.get(profile, profile) or self._settings.default_agent
        return self._settings.default_agent or None

    def _load_raw_config(self, project_root: str | None) -> dict[str, Any] | None:
        config_path = self._settings.resolve_opencode_config_file(project_root)
        return load_json_file(config_path)

    def _server_request(
        self,
        method: str,
        path: str,
        *,
        project_root: str | None = None,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
        timeout_s: float = 30.0,
    ) -> Any:
        if self._headless_server is None or self._settings.runner_type == "raw_json_runner":
            raise AdapterApiError(
                "backend_unavailable",
                "OpenCode headless server is not enabled for this adapter runtime.",
                status_code=503,
                retryable=False,
            )
        query = dict(params or {})
        if project_root:
            query.setdefault("directory", project_root)
        try:
            return self._headless_server.request(
                method,
                path,
                params=query or None,
                json_payload=json_payload,
                timeout_s=timeout_s,
            )
        except Exception as exc:
            raise AdapterApiError(
                "backend_unavailable",
                f"OpenCode server request failed: {exc}",
                status_code=503,
                retryable=True,
            ) from exc


def _normalized_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _split_model_identifier(value: str | None) -> tuple[str | None, str | None]:
    raw = str(value or "").strip()
    if not raw or "/" not in raw:
        return None, None
    provider_id, model_id = raw.split("/", 1)
    provider_id = provider_id.strip() or None
    model_id = model_id.strip() or None
    return provider_id, model_id


def _parse_iso_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    return datetime.fromisoformat(raw)


def _normalize_diff_summary(summary: Any, files: Any) -> dict[str, int]:
    if isinstance(summary, dict):
        return {
            "files": int(summary.get("files", len(files) if isinstance(files, list) else 0)),
            "additions": int(summary.get("additions", 0)),
            "deletions": int(summary.get("deletions", 0)),
        }
    normalized_files = _normalize_diff_files(files)
    return {
        "files": len(normalized_files),
        "additions": sum(int(item.get("additions", 0)) for item in normalized_files),
        "deletions": sum(int(item.get("deletions", 0)) for item in normalized_files),
    }


def _normalize_diff_files(files: Any) -> list[dict[str, Any]]:
    if not isinstance(files, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "file": str(item.get("file") or item.get("path") or item.get("name") or ""),
                "additions": int(item.get("additions", 0)),
                "deletions": int(item.get("deletions", 0)),
                "before": str(item.get("before") or ""),
                "after": str(item.get("after") or ""),
            }
        )
    return normalized
