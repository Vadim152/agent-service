"""GigaChat-based LLM adapter with optional corporate proxy mode."""
from __future__ import annotations

from base64 import b64encode
from typing import Any, Iterable, List

import httpx
from gigachat import GigaChat
from gigachat.exceptions import GigaChatException

try:  # SDK 0.2.x and newer
    from gigachat.models import ChatCompletion, Embeddings
except ImportError:  # pragma: no cover - compatibility with older SDK
    from gigachat.models import ChatCompletionResponse as ChatCompletion  # type: ignore
    from gigachat.models import EmbeddingsResponse as Embeddings  # type: ignore

from infrastructure.llm_client import LLMClient


class GigaChatAdapter(LLMClient):
    """LLMClient implementation for GigaChat and corporate proxy mode."""

    def __init__(
        self,
        *,
        base_url: str | None,
        auth_url: str | None,
        credentials: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        model_name: str = "GigaChat",
        scope: str = "GIGACHAT_API_PERS",
        verify_ssl_certs: bool = True,
        access_token: str | None = None,
        allow_fallback: bool | None = None,
        corp_mode: bool = False,
        corp_proxy_url: str | None = None,
        cert_file: str | None = None,
        key_file: str | None = None,
        ca_bundle_file: str | None = None,
        request_timeout_s: float = 30.0,
    ) -> None:
        self.credentials = credentials or self._build_credentials(client_id, client_secret)
        fallback_enabled = (
            allow_fallback if allow_fallback is not None else not bool(self.credentials or access_token)
        )

        super().__init__(
            endpoint=base_url,
            api_key=self.credentials,
            model_name=model_name,
            allow_fallback=fallback_enabled,
        )
        self.scope = scope
        self.verify_ssl_certs = verify_ssl_certs
        self.auth_url = auth_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.corp_mode = corp_mode
        self.corp_proxy_url = corp_proxy_url
        self.cert_file = cert_file
        self.key_file = key_file
        self.ca_bundle_file = ca_bundle_file
        self.request_timeout_s = request_timeout_s

    @staticmethod
    def _build_credentials(client_id: str | None, client_secret: str | None) -> str | None:
        if not client_id or not client_secret:
            return None
        token = f"{client_id}:{client_secret}".encode("utf-8")
        return b64encode(token).decode("utf-8")

    def validate_corp_config(self) -> None:
        if not self.corp_mode:
            return
        if not self.corp_proxy_url:
            raise RuntimeError("Corporate proxy URL is not configured")
        if not self.cert_file:
            raise RuntimeError("Corporate cert file is not configured")
        if not self.key_file:
            raise RuntimeError("Corporate key file is not configured")

    def _create_client(self) -> GigaChat | None:
        if not (self.credentials or self.access_token):
            if self.allow_fallback:
                return None
            raise RuntimeError("GigaChat credentials are not configured")

        return GigaChat(
            base_url=self.endpoint,
            auth_url=self.auth_url,
            credentials=self.credentials,
            access_token=self.access_token,
            scope=self.scope,
            verify_ssl_certs=self.verify_ssl_certs,
            model=self.model_name,
        )

    def _extract_embeddings(self, response: Embeddings) -> List[List[float]]:
        return [item.embedding for item in response.data]

    def embed_text(self, text: str) -> List[float]:
        if self.corp_mode:
            return super().embed_text(text)

        client = self._create_client()
        if not client:
            return super().embed_text(text)

        try:
            with client:
                response = client.embeddings([text])
        except GigaChatException as exc:  # pragma: no cover - external SDK
            raise RuntimeError("Failed to get embedding from GigaChat") from exc

        embeddings = self._extract_embeddings(response)
        return embeddings[0] if embeddings else []

    def embed_texts(self, texts: Iterable[str]) -> List[List[float]]:
        text_list = list(texts)
        if self.corp_mode:
            return super().embed_texts(text_list)

        client = self._create_client()
        if not client:
            return super().embed_texts(text_list)

        try:
            with client:
                response = client.embeddings(text_list)
        except GigaChatException as exc:  # pragma: no cover - external SDK
            raise RuntimeError("Failed to get batch embeddings from GigaChat") from exc

        return self._extract_embeddings(response)

    def generate(self, prompt: str, **kwargs: Any) -> str:
        if self.corp_mode:
            return self._generate_via_corp_proxy(prompt, **kwargs)

        client = self._create_client()
        if not client:
            return super().generate(prompt, **kwargs)

        try:
            with client:
                response: ChatCompletion = client.chat(prompt, **kwargs)
        except GigaChatException as exc:  # pragma: no cover - external SDK
            raise RuntimeError("Failed to generate text via GigaChat") from exc

        if not response.choices:
            return ""

        return response.choices[0].message.content or ""

    def _generate_via_corp_proxy(self, prompt: str, **kwargs: Any) -> str:
        self.validate_corp_config()

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
        }
        for key in (
            "temperature",
            "top_p",
            "max_tokens",
            "presence_penalty",
            "frequency_penalty",
            "stop",
        ):
            value = kwargs.get(key)
            if value is not None:
                payload[key] = value

        verify: bool | str = self.verify_ssl_certs
        if self.ca_bundle_file:
            verify = self.ca_bundle_file

        try:
            response = httpx.post(
                self.corp_proxy_url,
                json=payload,
                cert=(self.cert_file, self.key_file),
                verify=verify,
                timeout=self.request_timeout_s,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            body_preview = exc.response.text[:512] if exc.response is not None else ""
            raise RuntimeError(
                f"Corporate proxy request failed: {status_code}; body={body_preview}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("Corporate proxy request failed") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("Corporate proxy returned non-JSON response") from exc

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""

        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first, dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        return content if isinstance(content, str) else ""
