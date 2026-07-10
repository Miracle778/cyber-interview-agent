from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_provider_service, get_workspace_service
from app.schemas.settings import (
    CreateProviderCommand,
    CreateProviderModelCommand,
    ProviderModelResource,
    ProviderResource,
    RegisterWorkspaceCommand,
    RelinkWorkspaceCommand,
    UpdateProviderCommand,
    UpdateProviderModelCommand,
    UpdateWorkspaceCommand,
    UpdateWorkspaceModelBindingsCommand,
    WorkspaceConfig,
    WorkspaceModelBindingsResource,
    WorkspaceResource,
)
from app.services.provider_service import ProviderService
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/api/settings", tags=["settings"])


class LegacyWorkspaceCommand(BaseModel):
    workspace_path: str = Field(alias="workspacePath")
    model_config = {"populate_by_name": True}


@router.get("/providers", response_model=list[ProviderResource])
def list_providers(
    service: ProviderService = Depends(get_provider_service),
) -> list[ProviderResource]:
    return service.list_providers()


@router.post(
    "/providers",
    response_model=ProviderResource,
    status_code=status.HTTP_201_CREATED,
)
def create_provider(
    command: CreateProviderCommand,
    service: ProviderService = Depends(get_provider_service),
) -> ProviderResource:
    return service.create_provider(command)


@router.patch("/providers/{provider_id}", response_model=ProviderResource)
def update_provider(
    provider_id: str,
    command: UpdateProviderCommand,
    service: ProviderService = Depends(get_provider_service),
) -> ProviderResource:
    return service.update_provider(provider_id, command)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(
    provider_id: str,
    service: ProviderService = Depends(get_provider_service),
) -> Response:
    service.delete_provider(provider_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/providers/{provider_id}/models",
    response_model=ProviderModelResource,
    status_code=status.HTTP_201_CREATED,
)
def create_provider_model(
    provider_id: str,
    command: CreateProviderModelCommand,
    service: ProviderService = Depends(get_provider_service),
) -> ProviderModelResource:
    return service.create_provider_model(provider_id, command)


@router.patch(
    "/provider-models/{model_id}", response_model=ProviderModelResource
)
def update_provider_model(
    model_id: str,
    command: UpdateProviderModelCommand,
    service: ProviderService = Depends(get_provider_service),
) -> ProviderModelResource:
    return service.update_provider_model(model_id, command)


@router.delete(
    "/provider-models/{model_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_provider_model(
    model_id: str,
    service: ProviderService = Depends(get_provider_service),
) -> Response:
    service.delete_provider_model(model_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/provider-models/{model_id}/test", response_model=ProviderModelResource
)
async def test_provider_model(
    model_id: str,
    service: ProviderService = Depends(get_provider_service),
) -> ProviderModelResource:
    return await service.test_model(model_id)


@router.get("/workspaces", response_model=list[WorkspaceResource])
def list_workspaces(
    service: WorkspaceService = Depends(get_workspace_service),
) -> list[WorkspaceResource]:
    return service.list_workspaces()


@router.post(
    "/workspaces",
    response_model=WorkspaceResource,
    status_code=status.HTTP_201_CREATED,
)
def register_workspace(
    command: RegisterWorkspaceCommand,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResource:
    return service.register(command.root_path)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceResource)
def update_workspace(
    workspace_id: str,
    command: UpdateWorkspaceCommand,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResource:
    return service.update_available(workspace_id, command.available)


@router.post("/workspaces/{workspace_id}/relink", response_model=WorkspaceResource)
def relink_workspace(
    workspace_id: str,
    command: RelinkWorkspaceCommand,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResource:
    return service.relink(workspace_id, command.root_path)


@router.get(
    "/workspaces/{workspace_id}/model-bindings",
    response_model=WorkspaceModelBindingsResource,
)
def get_workspace_model_bindings(
    workspace_id: str,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceModelBindingsResource:
    return service.get_model_bindings(workspace_id)


@router.put(
    "/workspaces/{workspace_id}/model-bindings",
    response_model=WorkspaceModelBindingsResource,
)
def replace_workspace_model_bindings(
    workspace_id: str,
    command: UpdateWorkspaceModelBindingsCommand,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceModelBindingsResource:
    return service.replace_model_bindings(workspace_id, command.bindings)


@router.get("/workspace", response_model=WorkspaceConfig | None, deprecated=True)
def get_legacy_workspace(
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceConfig | None:
    workspace = service.get_current()
    if workspace is None:
        return None
    return WorkspaceConfig(
        workspacePath=workspace.root_path,
        vaultPath=workspace.vault_path,
    )


@router.post("/workspace", response_model=WorkspaceConfig, deprecated=True)
def set_legacy_workspace(
    command: LegacyWorkspaceCommand,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceConfig:
    workspace = service.register(command.workspace_path)
    return WorkspaceConfig(
        workspacePath=workspace.root_path,
        vaultPath=workspace.vault_path,
    )
