"""HTTP client for the OpenCode wrapper API."""
from __future__ import annotations

from typing import Any

import httpx


class OpenCodeAdapterError(RuntimeError):
    """Raised when the OpenCode adapter call fails."""


class HttpOpenCodeAdapterClient:
    def __init__(self, *, base_url: str, timeout_s: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = httpx.request(
                method,
                url,
                json=json_payload,
                params=params,
                timeout=self._timeout_s,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise OpenCodeAdapterError(f"OpenCode adapter request failed: {exc}") from exc
        if not isinstance(data, dict):
            raise OpenCodeAdapterError("OpenCode adapter returned non-object response")
        return data

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/runs", json_payload=payload)

    def get_run(self, backend_run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/runs/{backend_run_id}")

    def list_events(self, backend_run_id: str, *, after: int | str | None) -> dict[str, Any]:
        params = {}
        if after not in {None, ""}:
            params["after"] = after
        return self._request("GET", f"/v1/runs/{backend_run_id}/events", params=params or None)

    def cancel_run(self, backend_run_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/runs/{backend_run_id}/cancel", json_payload={})

    def submit_approval_decision(self, backend_run_id: str, approval_id: str, decision: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/runs/{backend_run_id}/approvals/{approval_id}",
            json_payload={"decision": decision},
        )
