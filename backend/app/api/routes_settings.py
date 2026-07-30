from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from app.api.dependencies import (
    get_agent_application,
    get_provider_service,
    get_workspace_service,
)
from app.application.workspace_runtime import AgentApplication
from app.core.errors import WorkspaceConflictError
from app.schemas.settings import (
    AgentDiagnosticsSettingsResource,
    AgentQualityEvaluationSettingsResource,
    CreateProviderCommand,
    CreateProviderModelCommand,
    ProviderModelResource,
    ProviderResource,
    RegisterWorkspaceCommand,
    RelinkWorkspaceCommand,
    UpdateProviderCommand,
    UpdateProviderModelCommand,
    UpdateAgentDiagnosticsSettingsCommand,
    UpdateAgentQualityEvaluationSettingsCommand,
    UpdateWorkspaceCommand,
    UpdateWorkspaceModelBindingsCommand,
    WorkspaceConfig,
    WorkspaceDeletionImpactResource,
    WorkspaceModelBindingsResource,
    WorkspaceResource,
)
from app.services.provider_service import ProviderService
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/api/settings", tags=["settings"])


class LegacyWorkspaceCommand(BaseModel):
    workspace_path: str = Field(alias="workspacePath")
    model_config = {"populate_by_name": True}


@router.get(
    "/agent-diagnostics",
    response_model=AgentDiagnosticsSettingsResource,
)
def get_agent_diagnostics_settings(
    service: WorkspaceService = Depends(get_workspace_service),
) -> AgentDiagnosticsSettingsResource:
    return service.get_agent_diagnostics_settings()


@router.put(
    "/agent-diagnostics",
    response_model=AgentDiagnosticsSettingsResource,
)
def replace_agent_diagnostics_settings(
    command: UpdateAgentDiagnosticsSettingsCommand,
    service: WorkspaceService = Depends(get_workspace_service),
) -> AgentDiagnosticsSettingsResource:
    return service.replace_agent_diagnostics_settings(
        advanced_enabled=command.advanced_enabled
    )


@router.get(
    "/agent-quality-evaluation",
    response_model=AgentQualityEvaluationSettingsResource,
)
def get_agent_quality_evaluation_settings(
    service: WorkspaceService = Depends(get_workspace_service),
) -> AgentQualityEvaluationSettingsResource:
    return service.get_agent_quality_evaluation_settings()


@router.put(
    "/agent-quality-evaluation",
    response_model=AgentQualityEvaluationSettingsResource,
)
def replace_agent_quality_evaluation_settings(
    command: UpdateAgentQualityEvaluationSettingsCommand,
    service: WorkspaceService = Depends(get_workspace_service),
) -> AgentQualityEvaluationSettingsResource:
    return service.replace_agent_quality_evaluation_settings(
        enabled=command.enabled,
        automatic_sample_percent=command.automatic_sample_percent,
        automatic_daily_cap=command.automatic_daily_cap,
        judge_provider_model_id=command.judge_provider_model_id,
    )


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
    lifecycle_status: Annotated[
        Literal["active", "recycled", "all"], Query(alias="status")
    ] = "active",
    service: WorkspaceService = Depends(get_workspace_service),
) -> list[WorkspaceResource]:
    return service.list_workspaces(
        lifecycle_status=None if lifecycle_status == "all" else lifecycle_status
    )


@router.post(
    "/workspaces",
    response_model=WorkspaceResource,
    status_code=status.HTTP_201_CREATED,
)
def register_workspace(
    command: RegisterWorkspaceCommand,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResource:
    return service.register(command.root_path, command.display_name)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceResource)
def update_workspace(
    workspace_id: str,
    command: UpdateWorkspaceCommand,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResource:
    return service.update(
        workspace_id,
        available=command.available,
        display_name=command.display_name,
    )


@router.post("/workspaces/{workspace_id}/select", response_model=WorkspaceResource)
def select_workspace(
    workspace_id: str,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResource:
    return service.select(workspace_id)


@router.post("/workspaces/{workspace_id}/recycle", response_model=WorkspaceResource)
async def recycle_workspace(
    workspace_id: str,
    service: WorkspaceService = Depends(get_workspace_service),
    application: AgentApplication = Depends(get_agent_application),
) -> WorkspaceResource:
    resource = service.recycle(workspace_id)
    await application.unload_workspace(workspace_id)
    return resource


@router.post("/workspaces/{workspace_id}/restore", response_model=WorkspaceResource)
def restore_workspace(
    workspace_id: str,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResource:
    return service.restore(workspace_id)


@router.get(
    "/workspaces/{workspace_id}/deletion-impact",
    response_model=WorkspaceDeletionImpactResource,
)
def workspace_deletion_impact(
    workspace_id: str,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceDeletionImpactResource:
    return service.deletion_impact(workspace_id)


@router.delete("/workspaces/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def permanently_delete_workspace(
    workspace_id: str,
    confirmation: str,
    service: WorkspaceService = Depends(get_workspace_service),
    application: AgentApplication = Depends(get_agent_application),
) -> Response:
    impact = service.deletion_impact(workspace_id)
    if confirmation != f"DELETE {impact.display_name}":
        raise WorkspaceConflictError("永久删除确认文字不匹配")
    await application.unload_workspace(workspace_id)
    service.permanently_delete(workspace_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
        id=workspace.id,
        displayName=workspace.display_name,
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
        id=workspace.id,
        displayName=workspace.display_name,
        workspacePath=workspace.root_path,
        vaultPath=workspace.vault_path,
    )
