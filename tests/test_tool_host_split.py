from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import Mock

from app.bootstrap import create_tool_host_client
from app.config import Settings
from chat.memory_store import ChatMemoryStore
from chat.runtime import ChatAgentRuntime
from infrastructure.tool_host_client import RemoteToolHostClient


class _ToolHostStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def save_generated_feature(
        self,
        *,
        project_root: str,
        target_path: str,
        feature_text: str,
        overwrite_existing: bool = False,
        approval_id: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "project_root": project_root,
                "target_path": target_path,
                "feature_text": feature_text,
                "overwrite_existing": overwrite_existing,
                "approval_id": approval_id,
            }
        )
        return {
            "projectRoot": project_root,
            "targetPath": target_path,
            "status": "created",
            "message": None,
        }


def test_create_tool_host_client_local_mode_returns_none() -> None:
    settings = Settings(_env_file=None, tool_host_mode="local")
    assert create_tool_host_client(settings) is None


def test_create_tool_host_client_remote_mode_returns_http_client() -> None:
    settings = Settings(_env_file=None, tool_host_mode="remote", tool_host_url="http://127.0.0.1:9001")
    client = create_tool_host_client(settings)
    assert isinstance(client, RemoteToolHostClient)


def test_chat_runtime_save_feature_uses_tool_host_client_when_provided() -> None:
    memory_store = ChatMemoryStore(Path(tempfile.mkdtemp(prefix="chat-tool-host-")))
    stub = _ToolHostStub()
    runtime = ChatAgentRuntime(memory_store=memory_store, tool_host_client=stub, orchestrator=None)

    result = runtime._tool_save_generated_feature(
        project_root="/tmp/project",
        target_path="features/demo.feature",
        feature_text="Feature: demo",
        overwrite_existing=False,
    )

    assert len(stub.calls) == 1
    assert stub.calls[0]["target_path"] == "features/demo.feature"
    assert result["diff"]["files"][0]["file"] == "features/demo.feature"


def test_chat_runtime_save_feature_passes_approval_id_to_tool_host() -> None:
    memory_store = ChatMemoryStore(Path(tempfile.mkdtemp(prefix="chat-tool-host-approval-")))
    stub = _ToolHostStub()
    runtime = ChatAgentRuntime(memory_store=memory_store, tool_host_client=stub, orchestrator=None)

    runtime._tool_save_generated_feature(
        project_root="/tmp/project",
        target_path="features/demo.feature",
        feature_text="Feature: demo",
        overwrite_existing=False,
        approval_id="approval-123",
    )

    assert stub.calls[0]["approval_id"] == "approval-123"


def test_remote_tool_host_client_lists_registry(monkeypatch) -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"items": [{"name": "repo.read"}]}
    get_mock = Mock(return_value=response)
    monkeypatch.setattr("infrastructure.tool_host_client.httpx.get", get_mock)

    client = RemoteToolHostClient(base_url="http://127.0.0.1:9001")
    tools = client.list_tools()

    assert tools == [{"name": "repo.read"}]
    get_mock.assert_called_once()


def test_remote_tool_host_client_puts_artifact(monkeypatch) -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"artifactId": "artifact-1", "uri": "artifact://artifact-1"}
    post_mock = Mock(return_value=response)
    monkeypatch.setattr("infrastructure.tool_host_client.httpx.post", post_mock)

    client = RemoteToolHostClient(base_url="http://127.0.0.1:9001")
    payload = client.put_artifact(name="stdout.log", content="ok", run_id="run-1", attempt_id="attempt-1")

    assert payload["artifactId"] == "artifact-1"
    post_mock.assert_called_once()
