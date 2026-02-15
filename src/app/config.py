"""Application settings module."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(ENV_PATH, override=False)


class Settings(BaseSettings):
    """Main service settings."""

    _secret_fields: ClassVar[set[str]] = {
        "llm_api_key",
        "gigachat_client_secret",
        "gigachat_client_id",
        "corp_cert_file",
        "corp_key_file",
        "corp_ca_bundle_file",
    }

    model_config = SettingsConfigDict(
        env_prefix="AGENT_SERVICE_", env_file=ENV_PATH, case_sensitive=False, extra="ignore"
    )

    app_name: str = Field(default="agent-service", description="Service name")
    api_prefix: str = Field(default="/api/v1", description="HTTP API prefix")
    host: str = Field(default="127.0.0.1", description="Bind host")
    port: int = Field(default=8000, description="Bind port")
    log_request_bodies: bool = Field(default=False, description="Enable request body logging for diagnostics")
    steps_index_dir: Path = Field(default=ROOT_DIR / ".agent" / "steps_index", description="Path to steps index")
    artifacts_dir: Path = Field(
        default=ROOT_DIR / ".agent" / "artifacts",
        description="Directory for job artifacts and incidents",
    )
    jira_source_mode: str = Field(
        default="stub",
        description="Source mode for Jira testcase retrieval: stub|live|disabled",
    )
    jira_request_timeout_s: int = Field(
        default=20,
        description="Timeout for Jira testcase HTTP requests in seconds",
    )
    jira_default_instance: str | None = Field(
        default="https://jira.sberbank.ru",
        description="Default Jira instance URL for testcase retrieval",
    )

    llm_endpoint: str | None = Field(default=None, description="LLM service endpoint")
    llm_api_key: str | None = Field(default=None, description="LLM API key")
    llm_model: str | None = Field(default=None, description="LLM model identifier")
    llm_api_version: str | None = Field(default=None, description="LLM API version")

    gigachat_client_id: str | None = Field(
        default=None,
        description="GigaChat client id",
        validation_alias=AliasChoices("GIGACHAT_CLIENT_ID", "AGENT_SERVICE_GIGACHAT_CLIENT_ID"),
    )
    gigachat_client_secret: str | None = Field(
        default=None,
        description="GigaChat client secret",
        validation_alias=AliasChoices("GIGACHAT_CLIENT_SECRET", "AGENT_SERVICE_GIGACHAT_CLIENT_SECRET"),
    )
    gigachat_scope: str = Field(
        default="GIGACHAT_API_PERS",
        description="OAuth scope for GigaChat",
        validation_alias=AliasChoices("GIGACHAT_SCOPE", "AGENT_SERVICE_GIGACHAT_SCOPE"),
    )
    gigachat_auth_url: str = Field(
        default="https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        description="GigaChat auth endpoint",
        validation_alias=AliasChoices("GIGACHAT_AUTH_URL", "AGENT_SERVICE_GIGACHAT_AUTH_URL"),
    )
    gigachat_api_url: str = Field(
        default="https://gigachat.devices.sberbank.ru/api/v1",
        description="GigaChat API endpoint",
        validation_alias=AliasChoices("GIGACHAT_API_URL", "AGENT_SERVICE_GIGACHAT_API_URL"),
    )
    gigachat_verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates for GigaChat",
        validation_alias=AliasChoices("GIGACHAT_VERIFY_SSL", "AGENT_SERVICE_GIGACHAT_VERIFY_SSL"),
    )
    corp_mode: bool = Field(
        default=False,
        description="Enable corporate proxy mode for chat completions with mTLS",
    )
    corp_proxy_host: str | None = Field(
        default=None,
        description="Corporate proxy host (scheme + host) without endpoint path",
    )
    corp_proxy_path: str = Field(
        default="/sbe-ai-pdlc-integration-code-generator/v1/chat/proxy/completions",
        description="Corporate proxy path for chat completions",
    )
    corp_model: str = Field(
        default="GigaChat-2-Max",
        description="Model name used in corporate proxy mode",
    )
    corp_cert_file: str | None = Field(
        default=None,
        description="Path to client certificate PEM/CRT for corporate proxy mTLS",
    )
    corp_key_file: str | None = Field(
        default=None,
        description="Path to client key file for corporate proxy mTLS",
    )
    corp_ca_bundle_file: str | None = Field(
        default=None,
        description="Optional CA bundle path for corporate TLS verification",
    )
    corp_request_timeout_s: float = Field(
        default=30.0,
        description="Timeout for corporate proxy requests in seconds",
    )

    @model_validator(mode="after")
    def _validate_corporate_mode(self) -> "Settings":
        if self.corp_proxy_host:
            self.corp_proxy_host = self.corp_proxy_host.strip().rstrip("/")
        self.corp_proxy_path = "/" + self.corp_proxy_path.strip().lstrip("/")

        if not self.corp_mode:
            return self

        if not self.corp_proxy_host:
            raise ValueError("corp_proxy_host is required when corp_mode=true")
        if not self.corp_cert_file:
            raise ValueError("corp_cert_file is required when corp_mode=true")
        if not self.corp_key_file:
            raise ValueError("corp_key_file is required when corp_mode=true")

        return self

    def safe_model_dump(self) -> dict[str, Any]:
        """Return settings payload with secrets redacted for logging."""

        payload = self.model_dump()
        for field_name in self._secret_fields:
            if payload.get(field_name):
                payload[field_name] = "***"
        return payload


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached app settings."""

    settings = Settings()
    logging.getLogger(__name__).debug("Config loaded: %s", settings.safe_model_dump())
    return settings
