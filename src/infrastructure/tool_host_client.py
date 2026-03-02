"""Tool host client adapters."""
from __future__ import annotations

from typing import Any

import httpx


class ToolHostClientError(RuntimeError):
    """Tool host request failure."""


class RemoteToolHostClient:
    """HTTP client for remote tool host service."""

    def __init__(self, *, base_url: str, timeout_s: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = httpx.get(url, timeout=self._timeout_s)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ToolHostClientError("Tool host returned non-object response")
            return data
        except Exception as exc:
            raise ToolHostClientError(f"Tool host request failed: {exc}") from exc

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = httpx.post(url, json=payload, timeout=self._timeout_s)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ToolHostClientError("Tool host returned non-object response")
            return data
        except Exception as exc:
            raise ToolHostClientError(f"Tool host request failed: {exc}") from exc

    def list_tools(self) -> list[dict[str, Any]]:
        data = self._get("/internal/tools/registry")
        items = data.get("items", [])
        if not isinstance(items, list):
            raise ToolHostClientError("Tool host registry returned non-list items")
        return [item for item in items if isinstance(item, dict)]

    def read_repo_file(
        self,
        *,
        project_root: str,
        path: str,
        include_content: bool = True,
    ) -> dict[str, Any]:
        return self._post(
            "/internal/tools/repo/read",
            {
                "projectRoot": project_root,
                "path": path,
                "includeContent": bool(include_content),
            },
        )

    def propose_patch(
        self,
        *,
        project_root: str,
        target_path: str,
        feature_text: str,
    ) -> dict[str, Any]:
        return self._post(
            "/internal/tools/patch/propose",
            {
                "projectRoot": project_root,
                "targetPath": target_path,
                "featureText": feature_text,
            },
        )

    def put_artifact(
        self,
        *,
        name: str,
        content: str,
        media_type: str = "text/plain",
        connector_source: str = "tool_host.artifacts",
        run_id: str | None = None,
        execution_id: str | None = None,
        attempt_id: str | None = None,
    ) -> dict[str, Any]:
        return self._post(
            "/internal/tools/artifacts/put",
            {
                "runId": run_id,
                "executionId": execution_id,
                "attemptId": attempt_id,
                "name": name,
                "content": content,
                "mediaType": media_type,
                "connectorSource": connector_source,
            },
        )

    def get_artifact(self, *, artifact_id: str | None = None, uri: str | None = None) -> dict[str, Any]:
        return self._post(
            "/internal/tools/artifacts/get",
            {
                "artifactId": artifact_id,
                "uri": uri,
            },
        )

    def save_generated_feature(
        self,
        *,
        project_root: str,
        target_path: str,
        feature_text: str,
        overwrite_existing: bool = False,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "projectRoot": project_root,
            "targetPath": target_path,
            "featureText": feature_text,
            "overwriteExisting": bool(overwrite_existing),
            "approvalId": approval_id,
        }
        return self._post("/internal/tools/patch/apply", payload)
