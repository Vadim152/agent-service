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

    def save_generated_feature(
        self,
        *,
        project_root: str,
        target_path: str,
        feature_text: str,
        overwrite_existing: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "projectRoot": project_root,
            "targetPath": target_path,
            "featureText": feature_text,
            "overwriteExisting": bool(overwrite_existing),
        }
        url = f"{self._base_url}/internal/tools/save-feature"
        try:
            response = httpx.post(url, json=payload, timeout=self._timeout_s)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ToolHostClientError("Tool host returned non-object response")
            return data
        except Exception as exc:
            raise ToolHostClientError(f"Tool host request failed: {exc}") from exc

