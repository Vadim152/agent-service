"""Schemas for internal tool-host connector endpoints."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from api.schemas import ApiBaseModel, ApplyFeatureResponse


class ToolRegistryItem(ApiBaseModel):
    name: str
    description: str
    risk_level: str = Field(alias="riskLevel")
    requires_approval: bool = Field(alias="requiresApproval")
    enabled: bool = True


class ToolRegistryResponse(ApiBaseModel):
    items: list[ToolRegistryItem] = Field(default_factory=list)


class RepoReadRequest(ApiBaseModel):
    project_root: str = Field(alias="projectRoot")
    path: str
    include_content: bool = Field(default=True, alias="includeContent")


class RepoReadResponse(ApiBaseModel):
    project_root: str = Field(alias="projectRoot")
    path: str
    exists: bool
    is_file: bool = Field(alias="isFile")
    is_dir: bool = Field(alias="isDir")
    size: int | None = None
    content: str | None = None
    entries: list[str] = Field(default_factory=list)


class ArtifactPutRequest(ApiBaseModel):
    run_id: str | None = Field(default=None, alias="runId")
    execution_id: str | None = Field(default=None, alias="executionId")
    attempt_id: str | None = Field(default=None, alias="attemptId")
    name: str
    content: str
    media_type: str = Field(default="text/plain", alias="mediaType")
    connector_source: str = Field(default="tool_host.artifacts", alias="connectorSource")


class ArtifactPutResponse(ApiBaseModel):
    artifact_id: str = Field(alias="artifactId")
    run_id: str | None = Field(default=None, alias="runId")
    execution_id: str | None = Field(default=None, alias="executionId")
    attempt_id: str | None = Field(default=None, alias="attemptId")
    name: str
    uri: str
    media_type: str = Field(alias="mediaType")
    size: int
    checksum: str
    connector_source: str = Field(alias="connectorSource")
    storage_backend: str | None = Field(default=None, alias="storageBackend")
    storage_path: str | None = Field(default=None, alias="storagePath")
    storage_bucket: str | None = Field(default=None, alias="storageBucket")
    storage_key: str | None = Field(default=None, alias="storageKey")
    signed_url: str | None = Field(default=None, alias="signedUrl")
    created_at: str | None = Field(default=None, alias="createdAt")


class ArtifactGetRequest(ApiBaseModel):
    artifact_id: str | None = Field(default=None, alias="artifactId")
    uri: str | None = None


class ArtifactGetResponse(ArtifactPutResponse):
    content: str | None = None


class PatchFilePreview(ApiBaseModel):
    file: str
    before: str
    after: str
    additions: int
    deletions: int


class PatchDiffPreview(ApiBaseModel):
    summary: dict[str, int]
    files: list[PatchFilePreview] = Field(default_factory=list)


class PatchProposeRequest(ApiBaseModel):
    project_root: str = Field(alias="projectRoot")
    target_path: str = Field(alias="targetPath")
    feature_text: str = Field(alias="featureText")


class PatchProposeResponse(ApiBaseModel):
    project_root: str = Field(alias="projectRoot")
    target_path: str = Field(alias="targetPath")
    message: str
    diff: PatchDiffPreview


class PatchApplyRequest(ApiBaseModel):
    project_root: str = Field(alias="projectRoot")
    target_path: str = Field(alias="targetPath")
    feature_text: str = Field(alias="featureText")
    overwrite_existing: bool = Field(default=False, alias="overwriteExisting")
    approval_id: str | None = Field(default=None, alias="approvalId")


class PatchApplyResponse(ApplyFeatureResponse):
    diff: PatchDiffPreview
    approval_id: str | None = Field(default=None, alias="approvalId")
    applied: bool = True
    tool_name: str = Field(default="patch.apply", alias="toolName")
