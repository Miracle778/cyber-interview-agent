import { apiGet, apiPost } from "../../shared/api/client";

export type ProviderFormat = "openai-compatible" | "anthropic-compatible";

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
