"""Connector-style tool host service."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api.schemas import ApplyFeatureResponse
from tool_host.schemas import (
    ArtifactGetResponse,
    ArtifactPutResponse,
    PatchApplyResponse,
    PatchDiffPreview,
    PatchFilePreview,
    PatchProposeResponse,
    RepoReadResponse,
    ToolRegistryItem,
)


@dataclass(frozen=True)
class _ToolDef:
    name: str
    description: str
    risk_level: str
    requires_approval: bool


class ToolHostService:
    """Internal connector registry with repo and patch operations."""

    def __init__(self, *, orchestrator, artifact_store, policy_store: Any | None = None) -> None:
        self._orchestrator = orchestrator
        self._artifact_store = artifact_store
        self._policy_store = policy_store
        self._tools = [
            _ToolDef(
                name="repo.read",
                description="Read files and directory metadata from the checked-out repository.",
                risk_level="read",
                requires_approval=False,
            ),
            _ToolDef(
                name="patch.propose",
                description="Build a patch preview for generated feature content without applying it.",
                risk_level="write",
                requires_approval=False,
            ),
            _ToolDef(
                name="artifacts.put",
                description="Publish an artifact into indexed storage and return a logical URI.",
                risk_level="write",
                requires_approval=False,
            ),
            _ToolDef(
                name="artifacts.get",
                description="Resolve artifact metadata and content by logical artifact URI.",
                risk_level="read",
                requires_approval=False,
            ),
            _ToolDef(
                name="patch.apply",
                description="Apply generated feature content to the repository.",
                risk_level="write",
                requires_approval=True,
            ),
            _ToolDef(
                name="save_generated_feature",
                description="Legacy alias for applying generated feature content.",
                risk_level="write",
                requires_approval=True,
            ),
        ]

    def list_tools(self) -> list[ToolRegistryItem]:
        return [
            ToolRegistryItem(
                name=item.name,
                description=item.description,
                riskLevel=item.risk_level,
                requiresApproval=item.requires_approval,
                enabled=True,
            )
            for item in self._tools
        ]

    def repo_read(self, *, project_root: str, path: str, include_content: bool = True) -> RepoReadResponse:
        target = self._resolve_path(project_root=project_root, path=path)
        exists = target.exists()
        content = None
        entries: list[str] = []
        size = target.stat().st_size if exists and target.is_file() else None
        if exists and target.is_file() and include_content:
            content = target.read_text(encoding="utf-8")
        if exists and target.is_dir():
            entries = sorted(item.name for item in target.iterdir())
        return RepoReadResponse(
            projectRoot=project_root,
            path=path,
            exists=exists,
            isFile=exists and target.is_file(),
            isDir=exists and target.is_dir(),
            size=size,
            content=content,
            entries=entries,
        )

    def artifact_put(
        self,
        *,
        name: str,
        content: str,
        media_type: str = "text/plain",
        connector_source: str = "tool_host.artifacts",
        run_id: str | None = None,
        execution_id: str | None = None,
        attempt_id: str | None = None,
    ) -> ArtifactPutResponse:
        payload = self._artifact_store.publish_text(
            name=name,
            content=content,
            media_type=media_type,
            connector_source=connector_source,
            run_id=run_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
        )
        return ArtifactPutResponse.model_validate(payload)

    def artifact_get(self, *, artifact_id: str | None = None, uri: str | None = None) -> ArtifactGetResponse:
        target_id = (artifact_id or "").strip()
        if not target_id and uri and uri.startswith("artifact://"):
            target_id = uri[len("artifact://") :]
        if not target_id:
            raise ValueError("artifactId or artifact:// URI is required")
        payload = self._artifact_store.get_artifact(target_id)
        if payload is None:
            raise FileNotFoundError(f"Artifact not found: {target_id}")
        return ArtifactGetResponse.model_validate(payload)

    def patch_propose(self, *, project_root: str, target_path: str, feature_text: str) -> PatchProposeResponse:
        target = self._resolve_path(project_root=project_root, path=target_path)
        before = target.read_text(encoding="utf-8") if target.exists() and target.is_file() else ""
        additions = max(0, len(feature_text.splitlines()) - len(before.splitlines()))
        deletions = max(0, len(before.splitlines()) - len(feature_text.splitlines()))
        diff = PatchDiffPreview(
            summary={
                "files": 1,
                "additions": additions,
                "deletions": deletions,
            },
            files=[
                PatchFilePreview(
                    file=target_path,
                    before=before,
                    after=feature_text,
                    additions=additions,
                    deletions=deletions,
                )
            ],
        )
        return PatchProposeResponse(
            projectRoot=project_root,
            targetPath=target_path,
            message=f"Patch preview prepared for {target_path}",
            diff=diff,
        )

    def patch_apply(
        self,
        *,
        project_root: str,
        target_path: str,
        feature_text: str,
        overwrite_existing: bool = False,
        approval_id: str | None = None,
    ) -> PatchApplyResponse:
        session_id = self._require_patch_approval(approval_id)
        self._append_audit_event(
            session_id=session_id,
            event_type="patch.apply.started",
            payload={
                "sessionId": session_id,
                "approvalId": approval_id,
                "toolName": "patch.apply",
                "targetPath": target_path,
            },
        )
        preview = self.patch_propose(
            project_root=project_root,
            target_path=target_path,
            feature_text=feature_text,
        )
        try:
            result = self._orchestrator.apply_feature(
                project_root,
                target_path,
                feature_text,
                overwrite_existing=bool(overwrite_existing),
            )
        except Exception as exc:
            self._append_audit_event(
                session_id=session_id,
                event_type="patch.apply.failed",
                payload={
                    "sessionId": session_id,
                    "approvalId": approval_id,
                    "toolName": "patch.apply",
                    "targetPath": target_path,
                    "message": str(exc),
                },
            )
            raise
        payload = ApplyFeatureResponse.model_validate(result)
        self._append_audit_event(
            session_id=session_id,
            event_type="patch.applied",
            payload={
                "sessionId": session_id,
                "approvalId": approval_id,
                "toolName": "patch.apply",
                "targetPath": target_path,
                "status": payload.status,
            },
        )
        return PatchApplyResponse(
            projectRoot=payload.project_root,
            targetPath=payload.target_path,
            status=payload.status,
            message=payload.message,
            diff=preview.diff,
            approvalId=approval_id,
        )

    def save_feature_legacy(
        self,
        *,
        project_root: str,
        target_path: str,
        feature_text: str,
        overwrite_existing: bool = False,
    ) -> ApplyFeatureResponse:
        result = self._orchestrator.apply_feature(
            project_root,
            target_path,
            feature_text,
            overwrite_existing=bool(overwrite_existing),
        )
        return ApplyFeatureResponse.model_validate(result)

    @staticmethod
    def _resolve_path(*, project_root: str, path: str) -> Path:
        root = Path(project_root).resolve()
        target = (root / path).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"path escapes project root: {path}") from exc
        return target

    def _require_patch_approval(self, approval_id: str | None) -> str:
        if not approval_id:
            raise PermissionError("approvalId is required for patch.apply")
        if self._policy_store is None:
            raise PermissionError("Policy store is not configured for patch.apply")
        pending = self._policy_store.get_pending_approval(str(approval_id))
        if not pending:
            raise PermissionError(f"Approval not found: {approval_id}")
        tool_name = str(pending.get("tool_name") or pending.get("toolName") or "")
        if tool_name not in {"patch.apply", "save_generated_feature"}:
            raise PermissionError(f"Approval {approval_id} is not valid for patch.apply")
        session_id = str(pending.get("session_id") or pending.get("sessionId") or "").strip()
        if not session_id:
            raise PermissionError(f"Approval {approval_id} is missing session context")
        return session_id

    def _append_audit_event(self, *, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
        if self._policy_store is None:
            return
        self._policy_store.append_audit_event(
            session_id=session_id,
            event_type=event_type,
            payload=payload,
        )
