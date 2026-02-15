from __future__ import annotations

import httpx
import pytest

from infrastructure.gigachat_adapter import GigaChatAdapter


def test_generate_uses_corp_proxy_with_tls(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post(url: str, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
            request=request,
        )

    monkeypatch.setattr(httpx, "post", _fake_post)

    adapter = GigaChatAdapter(
        base_url=None,
        auth_url=None,
        model_name="GigaChat-2-Max",
        corp_mode=True,
        corp_proxy_url="https://corp.local/sbe-ai-pdlc-integration-code-generator/v1/chat/proxy/completions",
        cert_file="C:/secrets/client.crt",
        key_file="C:/secrets/client.key",
        ca_bundle_file="C:/secrets/ca.pem",
        request_timeout_s=17.5,
    )

    result = adapter.generate("ping", temperature=0.3)

    assert result == "ok"
    assert captured["url"] == "https://corp.local/sbe-ai-pdlc-integration-code-generator/v1/chat/proxy/completions"
    kwargs = captured["kwargs"]
    assert kwargs["cert"] == ("C:/secrets/client.crt", "C:/secrets/client.key")
    assert kwargs["verify"] == "C:/secrets/ca.pem"
    assert kwargs["timeout"] == 17.5
    assert kwargs["json"]["model"] == "GigaChat-2-Max"
    assert kwargs["json"]["messages"] == [{"role": "user", "content": "ping"}]
    assert kwargs["json"]["temperature"] == 0.3


def test_generate_raises_on_corp_proxy_http_error(monkeypatch) -> None:
    calls = {"count": 0}

    def _fake_post(url: str, **kwargs):
        calls["count"] += 1
        request = httpx.Request("POST", url)
        return httpx.Response(403, json={"error": "forbidden"}, request=request)

    monkeypatch.setattr(httpx, "post", _fake_post)

    adapter = GigaChatAdapter(
        base_url=None,
        auth_url=None,
        corp_mode=True,
        corp_proxy_url="https://corp.local/sbe-ai-pdlc-integration-code-generator/v1/chat/proxy/completions",
        cert_file="C:/secrets/client.crt",
        key_file="C:/secrets/client.key",
    )

    with pytest.raises(RuntimeError, match="Corporate proxy request failed: 403"):
        adapter.generate("ping")
    assert calls["count"] == 1


def test_generate_raises_when_corp_config_missing() -> None:
    adapter = GigaChatAdapter(
        base_url=None,
        auth_url=None,
        corp_mode=True,
        corp_proxy_url=None,
        cert_file="C:/secrets/client.crt",
        key_file="C:/secrets/client.key",
    )

    with pytest.raises(RuntimeError, match="Corporate proxy URL"):
        adapter.generate("ping")


def test_embed_falls_back_in_corp_mode() -> None:
    adapter = GigaChatAdapter(
        base_url=None,
        auth_url=None,
        corp_mode=True,
        corp_proxy_url="https://corp.local/sbe-ai-pdlc-integration-code-generator/v1/chat/proxy/completions",
        cert_file="C:/secrets/client.crt",
        key_file="C:/secrets/client.key",
    )

    vector = adapter.embed_text("sample")
    assert len(vector) == 8


def test_generate_retries_on_503_then_succeeds(monkeypatch) -> None:
    calls = {"count": 0}
    sleeps: list[float] = []

    def _fake_post(url: str, **kwargs):
        calls["count"] += 1
        request = httpx.Request("POST", url)
        if calls["count"] < 3:
            return httpx.Response(503, text="temporary unavailable", request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok-after-retry"}}]},
            request=request,
        )

    monkeypatch.setattr(httpx, "post", _fake_post)
    monkeypatch.setattr("infrastructure.gigachat_adapter.time.sleep", lambda value: sleeps.append(value))
    monkeypatch.setattr("infrastructure.gigachat_adapter.random.uniform", lambda _a, _b: 0.0)

    adapter = GigaChatAdapter(
        base_url=None,
        auth_url=None,
        corp_mode=True,
        corp_proxy_url="https://corp.local/sbe-ai-pdlc-integration-code-generator/v1/chat/proxy/completions",
        cert_file="C:/secrets/client.crt",
        key_file="C:/secrets/client.key",
        corp_retry_attempts=3,
        corp_retry_base_delay_s=0.1,
        corp_retry_max_delay_s=1.0,
        corp_retry_jitter_s=0.0,
    )

    assert adapter.generate("ping") == "ok-after-retry"
    assert calls["count"] == 3
    assert sleeps == [0.1, 0.2]


def test_generate_retry_exhausted_on_503(monkeypatch) -> None:
    calls = {"count": 0}
    sleeps: list[float] = []

    def _fake_post(url: str, **kwargs):
        calls["count"] += 1
        request = httpx.Request("POST", url)
        return httpx.Response(503, text="temporary unavailable", request=request)

    monkeypatch.setattr(httpx, "post", _fake_post)
    monkeypatch.setattr("infrastructure.gigachat_adapter.time.sleep", lambda value: sleeps.append(value))
    monkeypatch.setattr("infrastructure.gigachat_adapter.random.uniform", lambda _a, _b: 0.0)

    adapter = GigaChatAdapter(
        base_url=None,
        auth_url=None,
        corp_mode=True,
        corp_proxy_url="https://corp.local/sbe-ai-pdlc-integration-code-generator/v1/chat/proxy/completions",
        cert_file="C:/secrets/client.crt",
        key_file="C:/secrets/client.key",
        corp_retry_attempts=3,
        corp_retry_base_delay_s=0.1,
        corp_retry_max_delay_s=1.0,
        corp_retry_jitter_s=0.0,
    )

    with pytest.raises(RuntimeError, match="Corporate proxy request failed: 503; body=.*; attempts=3/3"):
        adapter.generate("ping")

    assert calls["count"] == 3
    assert sleeps == [0.1, 0.2]


def test_generate_retries_on_transport_error(monkeypatch) -> None:
    calls = {"count": 0}
    sleeps: list[float] = []

    def _fake_post(url: str, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise httpx.ConnectError("connection reset")
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok-after-transport"}}]},
            request=request,
        )

    monkeypatch.setattr(httpx, "post", _fake_post)
    monkeypatch.setattr("infrastructure.gigachat_adapter.time.sleep", lambda value: sleeps.append(value))
    monkeypatch.setattr("infrastructure.gigachat_adapter.random.uniform", lambda _a, _b: 0.0)

    adapter = GigaChatAdapter(
        base_url=None,
        auth_url=None,
        corp_mode=True,
        corp_proxy_url="https://corp.local/sbe-ai-pdlc-integration-code-generator/v1/chat/proxy/completions",
        cert_file="C:/secrets/client.crt",
        key_file="C:/secrets/client.key",
        corp_retry_attempts=3,
        corp_retry_base_delay_s=0.1,
        corp_retry_max_delay_s=1.0,
        corp_retry_jitter_s=0.0,
    )

    assert adapter.generate("ping") == "ok-after-transport"
    assert calls["count"] == 3
    assert sleeps == [0.1, 0.2]
