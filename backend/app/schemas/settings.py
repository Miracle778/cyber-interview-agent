from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

ProviderFormat = Literal["openai-compatible", "anthropic-compatible"]
ConnectivityStatus = Literal["unknown", "ok", "failed"]

class ProviderConfig(BaseModel):
    id: str
    name: str
    api_format: ProviderFormat = Field(alias="apiFormat")
    base_url: str = Field(alias="baseUrl")
    model_ids: list[str] = Field(alias="modelIds")
    active_model_id: str = Field(alias="activeModelId")
    connectivity_status: ConnectivityStatus = Field(default="unknown", alias="connectivityStatus")

    model_config = {"populate_by_name": True}

class WorkspaceConfig(BaseModel):
    workspace_path: str = Field(alias="workspacePath")
    vault_path: str = Field(alias="vaultPath")

    model_config = {"populate_by_name": True}


# --- R1 provider/model resources and commands (service-facing) ---

SecretSource = Literal["keyring", "environment"]
ProviderConnectivityStatus = Literal[
    "unknown",
    "ok",
    "secret_missing",
    "auth_failed",
    "model_not_found",
    "rate_limited",
    "timeout",
    "network_error",
    "protocol_error",
]


def _validate_base_url(value: str | None) -> str | None:
    """base_url must be an absolute http(s) URL with no embedded credentials.

    localhost and private-network hosts are allowed for local model servers.
    """
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url must use an http or https scheme")
    if not parsed.netloc:
        raise ValueError("base_url must be an absolute URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url must not embed credentials")
    return value


class CreateProviderCommand(BaseModel):
    name: str
    api_format: ProviderFormat
    base_url: str
    secret_source: SecretSource = "keyring"
    api_key: str | None = None
    secret_ref: str | None = None

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        return _validate_base_url(value)  # type: ignore[return-value]


class UpdateProviderCommand(BaseModel):
    name: str | None = None
    api_format: ProviderFormat | None = None
    base_url: str | None = None
    api_key: str | None = None

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str | None) -> str | None:
        return _validate_base_url(value)


class CreateProviderModelCommand(BaseModel):
    model_id: str
    display_name: str
    enabled: bool = True


class UpdateProviderModelCommand(BaseModel):
    model_id: str | None = None
    display_name: str | None = None
    enabled: bool | None = None


class ProviderModelResource(BaseModel):
    id: str
    provider_id: str
    model_id: str
    display_name: str
    enabled: bool
    connectivity_status: ProviderConnectivityStatus
    last_tested_at: str | None
    last_error_code: str | None
    last_latency_ms: int | None


class ProviderResource(BaseModel):
    id: str
    name: str
    api_format: ProviderFormat
    base_url: str
    secret_source: SecretSource
    has_secret: bool
    enabled: bool
    created_at: str
    updated_at: str
    models: list[ProviderModelResource] = Field(default_factory=list)
