from typing import Literal

from pydantic import BaseModel, Field

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
