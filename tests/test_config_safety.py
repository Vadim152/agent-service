from __future__ import annotations

from app.config import Settings


def test_safe_model_dump_redacts_secrets() -> None:
    settings = Settings(
        llm_api_key="secret-key",
        gigachat_client_id="client-id",
        gigachat_client_secret="client-secret",
    )
    dumped = settings.safe_model_dump()
    assert dumped["llm_api_key"] == "***"
    assert dumped["gigachat_client_id"] == "***"
    assert dumped["gigachat_client_secret"] == "***"


def test_safe_defaults_for_local_runtime(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_SERVICE_HOST", raising=False)
    monkeypatch.delenv("AGENT_SERVICE_GIGACHAT_VERIFY_SSL", raising=False)
    monkeypatch.delenv("GIGACHAT_VERIFY_SSL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.host == "127.0.0.1"
    assert settings.gigachat_verify_ssl is True
