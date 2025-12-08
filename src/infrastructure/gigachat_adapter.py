"""Адаптер LLM для GigaChat под Microsoft Agent Framework (MAF).

Класс реализует унифицированный интерфейс :class:`~infrastructure.llm_client.LLMClient`
через официальный SDK GigaChat. Он обеспечивает получение эмбеддингов и генерацию
ответов, необходимых агентам сервиса.
"""

from __future__ import annotations

from base64 import b64encode
from typing import Any, Iterable, List

from gigachat import GigaChat
from gigachat.exceptions import GigaChatException

try:  # SDK 0.2.x and newer
    from gigachat.models import ChatCompletion, Embeddings
except ImportError:  # pragma: no cover - совместимость со старыми версиями SDK
    from gigachat.models import ChatCompletionResponse as ChatCompletion  # type: ignore
    from gigachat.models import EmbeddingsResponse as Embeddings  # type: ignore

from infrastructure.llm_client import LLMClient


class GigaChatAdapter(LLMClient):
    """Реализация ``LLMClient`` для работы с GigaChat.

    Parameters
    ----------
    base_url: str | None
        Endpoint GigaChat API.
    auth_url: str | None
        Endpoint авторизации для получения токена.
    credentials: str | None
        Готовая строка credentials (обычно base64 от ``client_id:client_secret``).
    client_id: str | None
        Идентификатор клиента, используется для построения credentials.
    client_secret: str | None
        Секрет клиента, используется для построения credentials.
    model_name: str
        Идентификатор модели (по умолчанию ``"GigaChat"``).
    scope: str
        OAuth scope, используемый при инициализации клиента (по умолчанию
        ``"GIGACHAT_API_PERS"``).
    verify_ssl_certs: bool
        Проверять ли SSL-сертификаты при обращении к API.
    access_token: str | None
        Готовый токен доступа, если credentials не требуется.
    """

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
    ) -> None:
        super().__init__(endpoint=base_url, api_key=credentials, model_name=model_name)
        self.scope = scope
        self.verify_ssl_certs = verify_ssl_certs
        self.auth_url = auth_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.credentials = credentials or self._build_credentials(client_id, client_secret)

    @staticmethod
    def _build_credentials(client_id: str | None, client_secret: str | None) -> str | None:
        if not client_id or not client_secret:
            return None
        token = f"{client_id}:{client_secret}".encode("utf-8")
        return b64encode(token).decode("utf-8")

    def _create_client(self) -> GigaChat:
        if not (self.credentials or self.access_token):
            raise RuntimeError("Не заданы учетные данные для подключения к GigaChat")

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
        """Возвращает эмбеддинг для одного текста через GigaChat."""

        try:
            with self._create_client() as client:
                response = client.embeddings(text)
        except GigaChatException as exc:  # pragma: no cover - внешний SDK
            raise RuntimeError("Ошибка получения эмбеддинга из GigaChat") from exc

        embeddings = self._extract_embeddings(response)
        return embeddings[0] if embeddings else []

    def embed_texts(self, texts: Iterable[str]) -> List[List[float]]:
        """Возвращает эмбеддинги для списка текстов."""

        try:
            with self._create_client() as client:
                response = client.embeddings(list(texts))
        except GigaChatException as exc:  # pragma: no cover - внешний SDK
            raise RuntimeError("Ошибка пакетного получения эмбеддингов из GigaChat") from exc

        return self._extract_embeddings(response)

    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Генерирует ответ от GigaChat по заданному промпту."""

        try:
            with self._create_client() as client:
                response: ChatCompletion = client.chat(prompt, **kwargs)
        except GigaChatException as exc:  # pragma: no cover - внешний SDK
            raise RuntimeError("Ошибка генерации текста через GigaChat") from exc

        if not response.choices:
            return ""

        return response.choices[0].message.content or ""
