from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ProviderFormat = Literal["openai-compatible", "anthropic-compatible"]
ConnectivityStatus = Literal["unknown", "ok", "failed"]


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


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
    id: str
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


class CreateProviderCommand(CamelModel):
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

    @field_validator("api_key", "secret_ref", mode="before")
    @classmethod
    def _empty_secret_value_is_missing(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _require_secret_configuration(self):
        if self.secret_source == "keyring" and self.api_key is None:
            raise ValueError("api_key is required for keyring secrets")
        if self.secret_source == "environment" and self.secret_ref is None:
            raise ValueError("secret_ref is required for environment secrets")
        return self


class UpdateProviderCommand(CamelModel):
    name: str | None = None
    api_format: ProviderFormat | None = None
    base_url: str | None = None
    api_key: str | None = None

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str | None) -> str | None:
        return _validate_base_url(value)

    @field_validator("api_key", mode="before")
    @classmethod
    def _blank_api_key_preserves_existing(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class CreateProviderModelCommand(CamelModel):
    model_id: str
    display_name: str
    enabled: bool = True
    max_input_tokens: int = Field(default=128000, ge=4096, le=2000000)


class UpdateProviderModelCommand(CamelModel):
    model_id: str | None = None
    display_name: str | None = None
    enabled: bool | None = None
    max_input_tokens: int | None = Field(default=None, ge=4096, le=2000000)


class ProviderModelResource(CamelModel):
    id: str
    provider_id: str
    model_id: str
    display_name: str
    enabled: bool
    max_input_tokens: int
    connectivity_status: ProviderConnectivityStatus
    last_tested_at: str | None
    last_error_code: str | None
    last_latency_ms: int | None


class ProviderResource(CamelModel):
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


ModelRole = Literal[
    "question_generation",
    "answer_evaluation",
    "report_summarization",
    "agent_chat",
    "profile_extraction",
    "profile_assessment",
    "job_analysis",
    "project_deep_dive",
]
MODEL_ROLES = {
    "question_generation",
    "answer_evaluation",
    "report_summarization",
    "agent_chat",
    "profile_extraction",
    "profile_assessment",
    "job_analysis",
    "project_deep_dive",
}


class RegisterWorkspaceCommand(CamelModel):
    root_path: str


class RelinkWorkspaceCommand(CamelModel):
    root_path: str


class UpdateWorkspaceCommand(CamelModel):
    available: bool


class WorkspaceResource(CamelModel):
    id: str
    root_path: str
    vault_path: str
    available: bool
    created_at: str
    updated_at: str


class UpdateWorkspaceModelBindingsCommand(CamelModel):
    bindings: dict[ModelRole, str]

    @model_validator(mode="after")
    def _require_all_roles(self):
        if set(self.bindings) != MODEL_ROLES:
            raise ValueError("bindings must contain all eight model roles")
        return self


class WorkspaceModelBindingsResource(CamelModel):
    workspace_id: str
    bindings: dict[ModelRole, str]
