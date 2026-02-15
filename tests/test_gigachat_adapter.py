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
    def _fake_post(url: str, **kwargs):
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
