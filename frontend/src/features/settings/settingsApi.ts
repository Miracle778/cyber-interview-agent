import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "../../shared/api/client";
import type {
  CreateProviderCommand,
  CreateProviderModelCommand,
  ProviderFormat,
  ProviderModelResource,
  ProviderResource,
  ModelRole,
  UpdateProviderCommand,
  UpdateProviderModelCommand,
  WorkspaceModelBindingsResource,
  WorkspaceResource,
} from "./providerTypes";

// Legacy (pre-R1) types still used by the current SettingsPage; removed in task 7.
export type { ProviderFormat } from "./providerTypes";

export interface WorkspaceConfig {
  workspacePath: string;
  vaultPath: string;
}

export function getWorkspace(): Promise<WorkspaceConfig | null> {
  return apiGet<WorkspaceConfig | null>("/api/settings/workspace");
}

// --- R1 provider/model API ---

export function listProviders(): Promise<ProviderResource[]> {
  return apiGet<ProviderResource[]>("/api/settings/providers");
}

export function createProvider(command: CreateProviderCommand): Promise<ProviderResource> {
  return apiPost<CreateProviderCommand, ProviderResource>("/api/settings/providers", command);
}

export function updateProvider(providerId: string, command: UpdateProviderCommand): Promise<ProviderResource> {
  return apiPatch<UpdateProviderCommand, ProviderResource>(`/api/settings/providers/${providerId}`, command);
}

export function deleteProvider(providerId: string): Promise<void> {
  return apiDelete(`/api/settings/providers/${providerId}`);
}

export function createProviderModel(
  providerId: string,
  command: CreateProviderModelCommand,
): Promise<ProviderModelResource> {
  return apiPost<CreateProviderModelCommand, ProviderModelResource>(
    `/api/settings/providers/${providerId}/models`,
    command,
  );
}

export function updateProviderModel(
  modelId: string,
  command: UpdateProviderModelCommand,
): Promise<ProviderModelResource> {
  return apiPatch<UpdateProviderModelCommand, ProviderModelResource>(`/api/settings/provider-models/${modelId}`, command);
}

export function deleteProviderModel(modelId: string): Promise<void> {
  return apiDelete(`/api/settings/provider-models/${modelId}`);
}

export function testProviderModel(modelId: string): Promise<ProviderModelResource> {
  return apiPost<undefined, ProviderModelResource>(`/api/settings/provider-models/${modelId}/test`, undefined);
}

export function listWorkspaces(): Promise<WorkspaceResource[]> {
  return apiGet<WorkspaceResource[]>("/api/settings/workspaces");
}

export function registerWorkspace(rootPath: string): Promise<WorkspaceResource> {
  return apiPost<{ rootPath: string }, WorkspaceResource>("/api/settings/workspaces", { rootPath });
}

export function getWorkspaceModelBindings(workspaceId: string): Promise<WorkspaceModelBindingsResource> {
  return apiGet<WorkspaceModelBindingsResource>(`/api/settings/workspaces/${workspaceId}/model-bindings`);
}

export function replaceWorkspaceModelBindings(
  workspaceId: string,
  bindings: Record<ModelRole, string>,
): Promise<WorkspaceModelBindingsResource> {
  return apiPut<{ bindings: Record<ModelRole, string> }, WorkspaceModelBindingsResource>(
    `/api/settings/workspaces/${workspaceId}/model-bindings`,
    { bindings },
  );
}
