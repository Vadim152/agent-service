from __future__ import annotations

import tempfile
from pathlib import Path

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
    ) -> dict[str, object]:
        self.calls.append(
            {
                "project_root": project_root,
                "target_path": target_path,
                "feature_text": feature_text,
                "overwrite_existing": overwrite_existing,
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

