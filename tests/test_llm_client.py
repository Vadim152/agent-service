import pytest

from infrastructure.llm_client import LLMClient


class DummyProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_text(self, text: str):
        self.calls.append(f"embed:{text}")
        return [1.0, 2.0]

    def embed_texts(self, texts):
        self.calls.append(f"embeds:{len(texts)}")
        return [[float(idx)] for idx, _ in enumerate(texts)]

    def generate(self, prompt: str, **_: object):
        self.calls.append(f"generate:{prompt}")
        return f"generated:{prompt}"


def test_fallback_embeddings_are_deterministic():
    client = LLMClient()

    single = client.embed_text("text")
    batch = client.embed_texts(["text", "other"])

    assert len(single) == 8
    assert single == batch[0]
    assert batch[0] != batch[1]


def test_fallback_generation_is_deterministic():
    client = LLMClient()

    result = client.generate("Hello")
    assert result.startswith("Hello")
    assert result == client.generate("Hello")


def test_uses_injected_client_when_present():
    provider = DummyProvider()
    client = LLMClient(client=provider, allow_fallback=False)

    assert client.embed_text("foo") == [1.0, 2.0]
    assert client.embed_texts(["a", "b"]) == [[0.0], [1.0]]
    assert client.generate("prompt") == "generated:prompt"
    assert provider.calls == ["embed:foo", "embeds:2", "generate:prompt"]


def test_missing_credentials_raise_error_when_fallback_disabled():
    client = LLMClient(allow_fallback=False, api_key=None, client=None)

    with pytest.raises(RuntimeError):
        client.embed_text("data")

    with pytest.raises(RuntimeError):
        client.embed_texts(["data"])

    with pytest.raises(RuntimeError):
        client.generate("prompt")
