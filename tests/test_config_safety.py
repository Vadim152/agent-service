from __future__ import annotations

import pytest

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


def test_safe_model_dump_redacts_corp_tls_paths() -> None:
    settings = Settings(
        corp_mode=True,
        corp_proxy_host="https://corp.local",
        corp_cert_file="C:/secrets/client.crt",
        corp_key_file="C:/secrets/client.key",
        corp_ca_bundle_file="C:/secrets/ca.pem",
    )
    dumped = settings.safe_model_dump()
    assert dumped["corp_cert_file"] == "***"
    assert dumped["corp_key_file"] == "***"
    assert dumped["corp_ca_bundle_file"] == "***"


def test_safe_defaults_for_local_runtime(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_SERVICE_HOST", raising=False)
    monkeypatch.delenv("AGENT_SERVICE_GIGACHAT_VERIFY_SSL", raising=False)
    monkeypatch.delenv("AGENT_SERVICE_JIRA_VERIFY_SSL", raising=False)
    monkeypatch.delenv("GIGACHAT_VERIFY_SSL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.host == "127.0.0.1"
    assert settings.gigachat_verify_ssl is True
    assert settings.jira_verify_ssl is True
    assert settings.jira_ca_bundle_file is None


def test_corp_mode_requires_proxy_host() -> None:
    with pytest.raises(ValueError, match="corp_proxy_host"):
        Settings(
            _env_file=None,
            corp_mode=True,
            corp_cert_file="C:/secrets/client.crt",
            corp_key_file="C:/secrets/client.key",
        )


def test_corp_mode_requires_cert_and_key() -> None:
    with pytest.raises(ValueError, match="corp_cert_file"):
        Settings(
            _env_file=None,
            corp_mode=True,
            corp_proxy_host="https://corp.local",
            corp_key_file="C:/secrets/client.key",
        )

    with pytest.raises(ValueError, match="corp_key_file"):
        Settings(
            _env_file=None,
            corp_mode=True,
            corp_proxy_host="https://corp.local",
            corp_cert_file="C:/secrets/client.crt",
        )


def test_corp_retry_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.corp_retry_attempts == 3
    assert settings.corp_retry_base_delay_s == 0.5
    assert settings.corp_retry_max_delay_s == 4.0
    assert settings.corp_retry_jitter_s == 0.2


def test_corp_retry_validation() -> None:
    with pytest.raises(ValueError, match="corp_retry_attempts"):
        Settings(_env_file=None, corp_retry_attempts=0)

    with pytest.raises(ValueError, match="corp_retry_max_delay_s must be >= corp_retry_base_delay_s"):
        Settings(_env_file=None, corp_retry_base_delay_s=1.0, corp_retry_max_delay_s=0.5)
