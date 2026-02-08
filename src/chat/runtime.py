"""Chat agent runtime: intent routing, tool calling and approval-gated execution."""
from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import datetime, timezone
from typing import Any

from chat.state_store import ChatStateStore
from chat.tool_registry import ChatToolRegistry, ToolDescriptor


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _contains_any(text: str, needles: set[str]) -> bool:
    return any(needle in text for needle in needles)


class ChatAgentRuntime:
    def __init__(
        self,
        *,
        orchestrator,
        run_state_store,
        execution_supervisor,
        state_store: ChatStateStore,
    ) -> None:
        self.orchestrator = orchestrator
        self.run_state_store = run_state_store
        self.execution_supervisor = execution_supervisor
        self.state_store = state_store
        self.registry = ChatToolRegistry()
        self._register_tools()

    def _register_tools(self) -> None:
        self.registry.register(
            ToolDescriptor(
                name="scan_steps",
                description="Scan repository and rebuild cucumber step index",
                handler=self._tool_scan_steps,
                risk_level="read",
                requires_confirmation=False,
            )
        )
        self.registry.register(
            ToolDescriptor(
                name="generate_feature_job",
                description="Submit feature generation job and stream progress",
                handler=self._tool_generate_feature_job,
                risk_level="external",
                requires_confirmation=True,
            )
        )
        self.registry.register(
            ToolDescriptor(
                name="get_job_status",
                description="Read current job status",
                handler=self._tool_get_job_status,
                risk_level="read",
                requires_confirmation=False,
            )
        )
        self.registry.register(
            ToolDescriptor(
                name="get_job_result",
                description="Read final job result",
                handler=self._tool_get_job_result,
                risk_level="read",
                requires_confirmation=False,
            )
        )
        self.registry.register(
            ToolDescriptor(
                name="apply_feature",
                description="Write feature file into repository",
                handler=self._tool_apply_feature,
                risk_level="write",
                requires_confirmation=True,
            )
        )
        self.registry.register(
            ToolDescriptor(
                name="create_automation_plan",
                description="Build structured plan for requested automation",
                handler=self._tool_create_automation_plan,
                risk_level="read",
                requires_confirmation=False,
            )
        )
        self.registry.register(
            ToolDescriptor(
                name="open_incident_summary",
                description="Read incident summary from job artifacts",
                handler=self._tool_open_incident_summary,
                risk_level="read",
                requires_confirmation=False,
            )
        )

    async def process_message(
        self,
        *,
        session_id: str,
        run_id: str,
        message_id: str,
        content: str,
    ) -> None:
        session = self.state_store.get_session(session_id)
        if not session:
            return

        self.state_store.append_message(
            session_id,
            role="user",
            content=content,
            message_id=message_id,
            run_id=run_id,
        )
        self.state_store.append_event(
            session_id,
            "agent.state",
            {"runId": run_id, "state": "planning"},
        )
        self.state_store.patch_project_memory(
            str(session.get("project_root", "")),
            summary=f"Last user message at {_utcnow()}",
        )

        tool_name, args = self._resolve_intent(session=session, content=content)
        if not tool_name:
            self._append_assistant(
                session_id,
                run_id,
                (
                    "Готов работать через чат. Используйте `/scan-steps`, `/generate-test <текст>` "
                    "или `/new-automation <цель>`."
                ),
            )
            self.state_store.append_event(session_id, "message.final", {"runId": run_id})
            return

        descriptor = self.registry.get(tool_name)
        await self._dispatch_tool(
            session_id=session_id,
            run_id=run_id,
            descriptor=descriptor,
            args=args,
        )

    async def process_tool_decision(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        decision: str,
        edited_args: dict[str, Any] | None,
    ) -> None:
        pending = self.state_store.get_pending_tool_call(session_id, tool_call_id)
        if not pending:
            self._append_assistant(
                session_id,
                run_id,
                f"Tool call `{tool_call_id}` не найден или уже обработан.",
            )
            return

        if decision.lower() == "reject":
            self.state_store.pop_pending_tool_call(session_id, tool_call_id)
            self.state_store.append_event(
                session_id,
                "tool.call.rejected",
                {"runId": run_id, "toolCallId": tool_call_id},
            )
            self._append_assistant(session_id, run_id, f"Операция `{pending['tool_name']}` отменена.")
            return

        descriptor = self.registry.get(str(pending["tool_name"]))
        final_args = dict(pending.get("args", {}))
        if edited_args:
            final_args.update(edited_args)
        self.state_store.pop_pending_tool_call(session_id, tool_call_id)
        self.state_store.append_event(
            session_id,
            "tool.call.approved",
            {"runId": run_id, "toolCallId": tool_call_id, "args": final_args},
        )
        await self._execute_tool(
            session_id=session_id,
            run_id=run_id,
            descriptor=descriptor,
            args=final_args,
            tool_call_id=tool_call_id,
        )

    async def _dispatch_tool(
        self,
        *,
        session_id: str,
        run_id: str,
        descriptor: ToolDescriptor,
        args: dict[str, Any],
    ) -> None:
        tool_call_id = str(uuid.uuid4())
        if descriptor.requires_confirmation:
            proposal = self.state_store.set_pending_tool_call(
                session_id,
                tool_call_id=tool_call_id,
                tool_name=descriptor.name,
                args=args,
                risk_level=descriptor.risk_level,
                requires_confirmation=descriptor.requires_confirmation,
            )
            if not proposal:
                return
            self.state_store.append_event(
                session_id,
                "tool.call.proposed",
                {
                    "runId": run_id,
                    "toolCall": proposal,
                },
            )
            self._append_assistant(
                session_id,
                run_id,
                (
                    f"Предлагаю выполнить `{descriptor.name}` (risk: {descriptor.risk_level}). "
                    "Подтвердите в карточке ниже."
                ),
            )
            return

        await self._execute_tool(
            session_id=session_id,
            run_id=run_id,
            descriptor=descriptor,
            args=args,
            tool_call_id=tool_call_id,
        )

    async def _execute_tool(
        self,
        *,
        session_id: str,
        run_id: str,
        descriptor: ToolDescriptor,
        args: dict[str, Any],
        tool_call_id: str,
    ) -> None:
        self.state_store.append_event(
            session_id,
            "tool.call.started",
            {
                "runId": run_id,
                "toolCallId": tool_call_id,
                "toolName": descriptor.name,
                "args": args,
            },
        )
        try:
            result = descriptor.handler(session_id=session_id, run_id=run_id, args=args)
            if inspect.isawaitable(result):
                result = await result
            self.state_store.append_event(
                session_id,
                "tool.call.result",
                {
                    "runId": run_id,
                    "toolCallId": tool_call_id,
                    "toolName": descriptor.name,
                    "result": result,
                },
            )
            self._append_assistant(
                session_id,
                run_id,
                self._format_result(descriptor.name, result),
            )
        except Exception as exc:  # pragma: no cover - defensive branch
            self.state_store.append_event(
                session_id,
                "error",
                {
                    "runId": run_id,
                    "toolCallId": tool_call_id,
                    "toolName": descriptor.name,
                    "message": str(exc),
                },
            )
            self._append_assistant(
                session_id,
                run_id,
                f"Ошибка во время `{descriptor.name}`: {exc}",
            )
        finally:
            self.state_store.append_event(session_id, "message.final", {"runId": run_id})

    def _resolve_intent(self, *, session: dict[str, Any], content: str) -> tuple[str | None, dict[str, Any]]:
        project_root = str(session.get("project_root", "")).strip()
        text = content.strip()
        if not text:
            return None, {}

        if text.startswith("/"):
            command, _, rest = text.partition(" ")
            payload = rest.strip()
            if command == "/scan-steps":
                target_root = payload if payload else project_root
                return "scan_steps", {"projectRoot": target_root}
            if command == "/generate-test":
                return "generate_feature_job", {"projectRoot": project_root, "testCaseText": payload}
            if command == "/new-automation":
                return "create_automation_plan", {"goal": payload}
            if command == "/job-status":
                return "get_job_status", {"jobId": payload}
            if command == "/job-result":
                return "get_job_result", {"jobId": payload}
            if command == "/help":
                return None, {}

        normalized = text.lower()
        if _contains_any(normalized, {"scan", "скан", "индекс", "steps"}):
            return "scan_steps", {"projectRoot": project_root}
        if _contains_any(normalized, {"автотест", "autotest", "generate feature", "сгенер"}):
            return "generate_feature_job", {
                "projectRoot": project_root,
                "testCaseText": text,
            }
        if _contains_any(normalized, {"автоматизац", "automation plan", "новую automation"}):
            return "create_automation_plan", {"goal": text}
        return None, {}

    def _append_assistant(self, session_id: str, run_id: str, content: str) -> None:
        self.state_store.append_message(
            session_id,
            role="assistant",
            content=content,
            run_id=run_id,
        )
        self.state_store.append_event(
            session_id,
            "message.delta",
            {"runId": run_id, "content": content},
        )

    def _format_result(self, tool_name: str, result: Any) -> str:
        if tool_name == "scan_steps" and isinstance(result, dict):
            return (
                f"Сканирование завершено: найдено шагов {result.get('steps_count', 0)}, "
                f"обновлено {result.get('updated_at')}."
            )
        if tool_name == "generate_feature_job" and isinstance(result, dict):
            return (
                f"Job `{result.get('jobId')}` завершен со статусом `{result.get('status')}`. "
                f"Unmapped steps: {result.get('unmappedSteps', 0)}."
            )
        if tool_name == "get_job_status" and isinstance(result, dict):
            return f"Текущий статус job `{result.get('jobId')}`: `{result.get('status')}`."
        if tool_name == "get_job_result" and isinstance(result, dict):
            return (
                f"Результат job `{result.get('jobId')}` получен: feature length="
                f"{len(str(result.get('featureText', '')))}."
            )
        if tool_name == "apply_feature" and isinstance(result, dict):
            return f"Feature `{result.get('targetPath')}` -> `{result.get('status')}`."
        if tool_name == "create_automation_plan" and isinstance(result, dict):
            lines = result.get("steps", [])
            rendered = "\n".join(f"{idx + 1}. {line}" for idx, line in enumerate(lines))
            return f"План автоматизации:\n{rendered}"
        if tool_name == "open_incident_summary" and isinstance(result, dict):
            return str(result.get("summary", "Инцидент без summary"))
        return str(result)

    async def _tool_scan_steps(self, *, session_id: str, run_id: str, args: dict[str, Any]) -> dict[str, Any]:
        project_root = str(args.get("projectRoot", "")).strip()
        if not project_root:
            raise ValueError("projectRoot is required")
        result = await asyncio.to_thread(self.orchestrator.scan_steps, project_root)
        self.state_store.patch_project_memory(
            project_root,
            recentArtifacts=[{"type": "stepIndex", "updatedAt": result.get("updated_at")}],
        )
        return result

    async def _tool_generate_feature_job(
        self,
        *,
        session_id: str,
        run_id: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        project_root = str(args.get("projectRoot", "")).strip()
        test_case_text = str(args.get("testCaseText", "")).strip()
        target_path = args.get("targetPath")
        create_file = bool(args.get("createFile", False))
        overwrite_existing = bool(args.get("overwriteExisting", False))
        language = args.get("language")
        if not project_root:
            raise ValueError("projectRoot is required")
        if not test_case_text:
            raise ValueError("testCaseText is required")

        job_id = str(uuid.uuid4())
        self.run_state_store.put_job(
            {
                "job_id": job_id,
                "status": "queued",
                "project_root": project_root,
                "test_case_text": test_case_text,
                "target_path": target_path,
                "create_file": create_file,
                "overwrite_existing": overwrite_existing,
                "language": language,
                "profile": "quick",
                "source": "chat-agent",
                "started_at": _utcnow(),
                "updated_at": _utcnow(),
                "attempts": [],
                "result": None,
            }
        )
        self.run_state_store.append_event(job_id, "job.queued", {"jobId": job_id, "source": "chat-agent"})
        self.state_store.append_event(
            session_id,
            "job.status",
            {"runId": run_id, "jobId": job_id, "status": "queued"},
        )
        asyncio.create_task(self.execution_supervisor.execute_job(job_id))

        final_status = "queued"
        incident_uri = None
        for _ in range(900):  # up to ~180s
            snapshot = self.run_state_store.get_job(job_id)
            if not snapshot:
                await asyncio.sleep(0.2)
                continue
            current_status = str(snapshot.get("status", "queued"))
            if current_status != final_status:
                final_status = current_status
                self.state_store.append_event(
                    session_id,
                    "job.status",
                    {"runId": run_id, "jobId": job_id, "status": final_status},
                )
            incident_uri = snapshot.get("incident_uri")
            if final_status in {"succeeded", "needs_attention", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.2)

        snapshot = self.run_state_store.get_job(job_id) or {}
        feature = snapshot.get("result") or {}
        unmapped_steps = feature.get("unmappedSteps", [])
        self.state_store.patch_project_memory(
            project_root,
            recentArtifacts=[
                {
                    "type": "jobResult",
                    "jobId": job_id,
                    "status": final_status,
                    "updatedAt": _utcnow(),
                }
            ],
        )
        return {
            "jobId": job_id,
            "status": final_status,
            "incidentUri": incident_uri,
            "unmappedSteps": len(unmapped_steps),
            "featureText": feature.get("featureText", ""),
        }

    def _tool_get_job_status(self, *, session_id: str, run_id: str, args: dict[str, Any]) -> dict[str, Any]:
        _ = session_id, run_id
        job_id = str(args.get("jobId", "")).strip()
        if not job_id:
            raise ValueError("jobId is required")
        snapshot = self.run_state_store.get_job(job_id)
        if not snapshot:
            raise ValueError(f"Job not found: {job_id}")
        return {
            "jobId": job_id,
            "status": snapshot.get("status", "queued"),
            "runId": snapshot.get("run_id"),
            "incidentUri": snapshot.get("incident_uri"),
        }

    def _tool_get_job_result(self, *, session_id: str, run_id: str, args: dict[str, Any]) -> dict[str, Any]:
        _ = session_id, run_id
        job_id = str(args.get("jobId", "")).strip()
        if not job_id:
            raise ValueError("jobId is required")
        snapshot = self.run_state_store.get_job(job_id)
        if not snapshot:
            raise ValueError(f"Job not found: {job_id}")
        result = snapshot.get("result")
        if result is None:
            raise ValueError(f"Result is not ready for job: {job_id}")
        return {
            "jobId": job_id,
            "status": snapshot.get("status", "queued"),
            "featureText": result.get("featureText", ""),
            "pipeline": result.get("pipeline", []),
        }

    async def _tool_apply_feature(self, *, session_id: str, run_id: str, args: dict[str, Any]) -> dict[str, Any]:
        _ = session_id, run_id
        project_root = str(args.get("projectRoot", "")).strip()
        target_path = str(args.get("targetPath", "")).strip()
        feature_text = str(args.get("featureText", ""))
        if not project_root or not target_path:
            raise ValueError("projectRoot and targetPath are required")
        result = await asyncio.to_thread(
            self.orchestrator.apply_feature,
            project_root,
            target_path,
            feature_text,
            overwrite_existing=bool(args.get("overwriteExisting", False)),
        )
        return result

    def _tool_create_automation_plan(self, *, session_id: str, run_id: str, args: dict[str, Any]) -> dict[str, Any]:
        _ = session_id, run_id
        goal = str(args.get("goal", "")).strip() or "Новая automation задача"
        return {
            "goal": goal,
            "steps": [
                "Уточнить целевой user-flow и критерии готовности.",
                "Собрать входные данные/тестовые фикстуры.",
                "Сгенерировать BDD feature и проверить unmapped steps.",
                "Запустить job-пайплайн и сохранить артефакты.",
                "Добавить quality-gates и стратегию rerun/remediation.",
            ],
        }

    def _tool_open_incident_summary(self, *, session_id: str, run_id: str, args: dict[str, Any]) -> dict[str, Any]:
        _ = session_id, run_id
        job_id = str(args.get("jobId", "")).strip()
        if not job_id:
            raise ValueError("jobId is required")
        snapshot = self.run_state_store.get_job(job_id)
        if not snapshot:
            raise ValueError(f"Job not found: {job_id}")
        incident_uri = snapshot.get("incident_uri")
        if not incident_uri:
            return {"jobId": job_id, "summary": "Для job нет инцидента."}
        return {
            "jobId": job_id,
            "summary": f"Инцидент доступен по пути: {incident_uri}",
        }

