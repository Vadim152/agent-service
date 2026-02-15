from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.pop("CHROMA_TELEMETRY_IMPL", None)

from agents import create_orchestrator
from app.config import Settings
from app.main import _validate_external_credentials
from infrastructure.gigachat_adapter import GigaChatAdapter


def test_orchestrator_disables_llm_enrichment_without_credentials(tmp_path) -> None:
    for env_key in (
        "AGENT_SERVICE_LLM_API_KEY",
        "GIGACHAT_CLIENT_ID",
        "GIGACHAT_CLIENT_SECRET",
    ):
        os.environ[env_key] = ""

    settings = Settings(
        steps_index_dir=tmp_path / "steps_index",
        llm_api_key=None,
        gigachat_client_id=None,
        gigachat_client_secret=None,
    )

    orchestrator = create_orchestrator(settings)

    assert orchestrator.llm_client is not None
    assert orchestrator.llm_client.allow_fallback is True
    assert orchestrator.repo_scanner_agent.llm_client is None
    assert orchestrator.testcase_parser_agent.llm_client is None
    assert orchestrator.step_matcher_agent.llm_client is None
    assert orchestrator.feature_builder_agent.llm_client is None


def test_validate_credentials_fails_without_fallback(tmp_path) -> None:
    app = FastAPI()
    adapter = GigaChatAdapter(
        base_url=None,
        auth_url=None,
        client_id=None,
        client_secret=None,
        allow_fallback=False,
    )
    orchestrator = SimpleNamespace(llm_client=adapter)

    with pytest.raises(RuntimeError):
        _validate_external_credentials(app, orchestrator)


def test_validate_credentials_allows_fallback(tmp_path) -> None:
    app = FastAPI()
    adapter = GigaChatAdapter(
        base_url=None,
        auth_url=None,
        client_id=None,
        client_secret=None,
        allow_fallback=True,
    )
    orchestrator = SimpleNamespace(llm_client=adapter)

    _validate_external_credentials(app, orchestrator)


def test_llm_endpoint_uses_fallback(tmp_path) -> None:
    app = FastAPI()
    adapter = GigaChatAdapter(
        base_url=None,
        auth_url=None,
        client_id=None,
        client_secret=None,
        allow_fallback=True,
    )
    orchestrator = SimpleNamespace(llm_client=adapter)
    app.state.orchestrator = orchestrator

    from api.routes_llm import router

    app.include_router(router)

    client = TestClient(app)
    prompt = "ping"

    response = client.post("/llm/test", json={"prompt": prompt})

    assert response.status_code == 200
    payload = response.json()
    assert payload["reply"] == adapter.generate(prompt)
    assert payload["provider"] == adapter.__class__.__name__


def test_validate_credentials_allows_corp_mode_without_oauth_credentials() -> None:
    app = FastAPI()
    adapter = GigaChatAdapter(
        base_url=None,
        auth_url=None,
        client_id=None,
        client_secret=None,
        allow_fallback=False,
        corp_mode=True,
        corp_proxy_url="https://corp.local/sbe-ai-pdlc-integration-code-generator/v1/chat/proxy/completions",
        cert_file="C:/secrets/client.crt",
        key_file="C:/secrets/client.key",
    )
    orchestrator = SimpleNamespace(llm_client=adapter)

    _validate_external_credentials(app, orchestrator)


def test_validate_credentials_fails_for_incomplete_corp_mode_config() -> None:
    app = FastAPI()
    adapter = GigaChatAdapter(
        base_url=None,
        auth_url=None,
        client_id=None,
        client_secret=None,
        allow_fallback=False,
        corp_mode=True,
        corp_proxy_url="https://corp.local/sbe-ai-pdlc-integration-code-generator/v1/chat/proxy/completions",
        cert_file=None,
        key_file="C:/secrets/client.key",
    )
    orchestrator = SimpleNamespace(llm_client=adapter)

    with pytest.raises(RuntimeError, match="Corporate proxy settings"):
        _validate_external_credentials(app, orchestrator)
