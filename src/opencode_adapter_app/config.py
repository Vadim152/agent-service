from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(ENV_PATH, override=False)


class AdapterSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPENCODE_ADAPTER_",
        env_file=ENV_PATH,
        case_sensitive=False,
        extra="ignore",
    )

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8011)
    log_level: str = Field(default="INFO")

    binary: str = Field(default="opencode.cmd")
    binary_args_json: str | None = Field(default=None)
    runner_type: str = Field(default="opencode")
    default_agent: str = Field(default="agent")
    default_model: str | None = Field(default=None)
    server_host: str = Field(default="127.0.0.1")
    server_port: int = Field(default=4096)
    print_logs: bool = Field(default=False)
    work_root: Path = Field(default=ROOT_DIR / ".agent" / "opencode-adapter")
    inline_artifact_max_bytes: int = Field(default=65_536)
    graceful_kill_timeout_ms: int = Field(default=3_000)
    run_start_timeout_ms: int = Field(default=10_000)
    max_events_per_run: int = Field(default=5_000)
    config_dir: str | None = Field(default=None)
    agent_map_json: str | None = Field(default=None)
    env_allowlist_json: str | None = Field(default=None)
    inherit_parent_env: bool = Field(default=True)

    @model_validator(mode="after")
    def _validate(self) -> "AdapterSettings":
        self.log_level = self.log_level.upper().strip()
        if self.log_level not in {"DEBUG", "INFO", "WARN", "ERROR"}:
            raise ValueError("log_level must be one of: DEBUG, INFO, WARN, ERROR")
        self.runner_type = self.runner_type.strip().lower()
        if self.runner_type not in {"opencode", "raw_json_runner"}:
            raise ValueError("runner_type must be one of: opencode, raw_json_runner")
        if self.server_port < 1:
            raise ValueError("server_port must be >= 1")
        if self.inline_artifact_max_bytes < 1:
            raise ValueError("inline_artifact_max_bytes must be >= 1")
        if self.graceful_kill_timeout_ms < 1:
            raise ValueError("graceful_kill_timeout_ms must be >= 1")
        if self.max_events_per_run < 1:
            raise ValueError("max_events_per_run must be >= 1")
        if not self.binary.strip():
            raise ValueError("binary must not be empty")
        self.work_root = Path(self.work_root)
        self.work_root.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def binary_args(self) -> list[str]:
        return _parse_json_list(self.binary_args_json)

    @property
    def agent_map(self) -> dict[str, str]:
        data = _parse_json_object(self.agent_map_json)
        return {str(key): str(value) for key, value in data.items()}

    @property
    def env_allowlist(self) -> list[str]:
        configured = _parse_json_list(self.env_allowlist_json)
        if configured:
            return configured
        return [
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "COMSPEC",
            "OS",
            "HOME",
            "HOMEDRIVE",
            "HOMEPATH",
            "USERPROFILE",
            "USERNAME",
            "USERDOMAIN",
            "USERDOMAIN_ROAMINGPROFILE",
            "PUBLIC",
            "ALLUSERSPROFILE",
            "PROGRAMDATA",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
            "TMP",
            "TEMP",
            "APPDATA",
            "LOCALAPPDATA",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_STATE_HOME",
            "XDG_CACHE_HOME",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "ALL_PROXY",
            "SSL_CERT_FILE",
            "REQUESTS_CA_BUNDLE",
            "CURL_CA_BUNDLE",
            "NODE_EXTRA_CA_CERTS",
            "NODE_OPTIONS",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_ENDPOINT",
            "LITELLM_API_KEY",
            "PORTKEY_API_KEY",
            "OPENCODE_CONFIG_DIR",
        ]

    def build_child_env(self) -> dict[str, str]:
        if self.inherit_parent_env:
            env: dict[str, str] = dict(os.environ)
        else:
            env = {}
            for key in self.env_allowlist:
                value = os.environ.get(key)
                if value is not None:
                    env[key] = value
        if self.config_dir:
            env["OPENCODE_CONFIG_DIR"] = self.config_dir
        return env


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Expected JSON list")
    return [str(item) for item in data]


def _parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object")
    return data


@lru_cache(maxsize=1)
def get_settings() -> AdapterSettings:
    return AdapterSettings()
