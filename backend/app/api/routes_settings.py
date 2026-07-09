from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.schemas.settings import ProviderConfig, WorkspaceConfig
from app.services.provider_registry import test_provider_connection
from app.services.vault import initialize_vault
from app.services.workspace import resolve_workspace

router = APIRouter(prefix="/api/settings", tags=["settings"])

_workspace: WorkspaceConfig | None = None

class WorkspaceRequest(BaseModel):
    workspace_path: str = Field(alias="workspacePath")
    model_config = {"populate_by_name": True}

@router.get("/workspace")
def get_workspace() -> WorkspaceConfig | None:
    return _workspace

@router.post("/workspace")
def set_workspace(request: WorkspaceRequest) -> WorkspaceConfig:
    global _workspace
    workspace = resolve_workspace(request.workspace_path)
    vault = initialize_vault(workspace)
    _workspace = WorkspaceConfig(workspacePath=str(workspace), vaultPath=str(vault))
    return _workspace


@router.post("/providers/test")
def test_provider(provider: ProviderConfig) -> ProviderConfig:
    return test_provider_connection(provider)
