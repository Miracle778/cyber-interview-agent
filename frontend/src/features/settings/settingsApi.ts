import { apiDelete, apiGet, apiPatch, apiPost } from "../../shared/api/client";
import type {
  CreateProviderCommand,
  CreateProviderModelCommand,
  ProviderFormat,
  ProviderModelResource,
  ProviderResource,
  UpdateProviderCommand,
  UpdateProviderModelCommand,
} from "./providerTypes";

// Legacy (pre-R1) types still used by the current SettingsPage; removed in task 7.
export type { ProviderFormat } from "./providerTypes";

export interface ProviderConfig {
  id: string;
  name: string;
  apiFormat: ProviderFormat;
  baseUrl: string;
  modelIds: string[];
  activeModelId: string;
  connectivityStatus: "unknown" | "ok" | "failed";
}

export interface WorkspaceConfig {
  workspacePath: string;
  vaultPath: string;
}

export function getWorkspace(): Promise<WorkspaceConfig | null> {
  return apiGet<WorkspaceConfig | null>("/api/settings/workspace");
}

export function initializeWorkspace(workspacePath: string): Promise<WorkspaceConfig> {
  return apiPost<{ workspacePath: string }, WorkspaceConfig>("/api/settings/workspace", { workspacePath });
}

export function testProviderConnection(provider: ProviderConfig): Promise<ProviderConfig> {
  return apiPost<ProviderConfig, ProviderConfig>("/api/settings/providers/test", provider);
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
