import { apiDelete, apiGet, apiPatch, apiPost, apiPut, apiRequest } from "../../shared/api/client";
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
  WorkspaceDeletionImpactResource,
} from "./providerTypes";

// Legacy (pre-R1) types still used by the current SettingsPage; removed in task 7.
export type { ProviderFormat } from "./providerTypes";

export interface WorkspaceConfig {
  id: string;
  displayName?: string;
  workspacePath: string;
  vaultPath: string;
}

export interface AgentDiagnosticsSettingsResource {
  advancedEnabled: boolean;
  updatedAt: string;
}

export interface AgentQualityEvaluationSettingsResource {
  enabled: boolean;
  captureRegressionInputs: boolean;
  automaticSamplePercent: number;
  automaticDailyCap: number;
  judgeProviderModelId: string | null;
  updatedAt: string;
}

export interface TraceRetentionPolicyResource {
  workspaceId: string;
  bodyPolicy: "permanent" | "days" | "metadata_only";
  bodyDays: number | null;
  metadataPolicy: "retain";
  updatedAt: string;
}

export interface TraceCleanupPlanResource {
  id: string;
  workspaceId: string;
  status: string;
  fileCount: number;
  eventCount: number;
  totalBytes: number;
  protectedActiveRuns: number;
  errorCode: string | null;
  createdAt: string;
  completedAt: string | null;
  items: Array<{
    relativePath: string;
    runId: string;
    eventCount: number;
    byteCount: number;
    sha256: string;
    status: string;
    errorCode: string | null;
  }>;
}

export function getWorkspace(): Promise<WorkspaceConfig | null> {
  return apiGet<WorkspaceConfig | null>("/api/settings/workspace");
}

export function getAgentDiagnosticsSettings(): Promise<AgentDiagnosticsSettingsResource> {
  return apiGet<AgentDiagnosticsSettingsResource>(
    "/api/settings/agent-diagnostics",
  );
}

export function replaceAgentDiagnosticsSettings(
  advancedEnabled: boolean,
): Promise<AgentDiagnosticsSettingsResource> {
  return apiPut<
    { advancedEnabled: boolean },
    AgentDiagnosticsSettingsResource
  >("/api/settings/agent-diagnostics", { advancedEnabled });
}

export function getAgentQualityEvaluationSettings(): Promise<AgentQualityEvaluationSettingsResource> {
  return apiGet<AgentQualityEvaluationSettingsResource>(
    "/api/settings/agent-quality-evaluation",
  );
}

export function replaceAgentQualityEvaluationSettings(
  resource: Omit<AgentQualityEvaluationSettingsResource, "updatedAt">,
): Promise<AgentQualityEvaluationSettingsResource> {
  return apiPut<
    Omit<AgentQualityEvaluationSettingsResource, "updatedAt">,
    AgentQualityEvaluationSettingsResource
  >("/api/settings/agent-quality-evaluation", resource);
}

export function getTraceRetentionPolicy(
  workspaceId: string,
): Promise<TraceRetentionPolicyResource> {
  return apiGet<TraceRetentionPolicyResource>(
    `/api/agent-observability/retention?workspaceId=${encodeURIComponent(workspaceId)}`,
  );
}

export function replaceTraceRetentionPolicy(
  workspaceId: string,
  bodyPolicy: TraceRetentionPolicyResource["bodyPolicy"],
): Promise<TraceRetentionPolicyResource> {
  return apiPut<
    { bodyPolicy: string; bodyDays: number | null },
    TraceRetentionPolicyResource
  >(
    `/api/agent-observability/retention?workspaceId=${encodeURIComponent(workspaceId)}`,
    {
      bodyPolicy,
      bodyDays: bodyPolicy === "days" ? 90 : null,
    },
  );
}

export function createTraceCleanupPlan(
  workspaceId: string,
): Promise<TraceCleanupPlanResource> {
  return apiPost<undefined, TraceCleanupPlanResource>(
    `/api/agent-observability/cleanup-plans?workspaceId=${encodeURIComponent(workspaceId)}`,
    undefined,
  );
}

export function confirmTraceCleanupPlan(
  workspaceId: string,
  cleanupId: string,
): Promise<TraceCleanupPlanResource> {
  return apiPost<undefined, TraceCleanupPlanResource>(
    `/api/agent-observability/cleanup-plans/${encodeURIComponent(cleanupId)}/confirm?workspaceId=${encodeURIComponent(workspaceId)}`,
    undefined,
  );
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

export function listWorkspaces(status: "active" | "recycled" | "all" = "active"): Promise<WorkspaceResource[]> {
  return apiGet<WorkspaceResource[]>(
    status === "active" ? "/api/settings/workspaces" : `/api/settings/workspaces?status=${status}`,
  );
}

export function registerWorkspace(rootPath: string, displayName?: string): Promise<WorkspaceResource> {
  return apiPost<{ rootPath: string; displayName?: string }, WorkspaceResource>("/api/settings/workspaces", { rootPath, displayName });
}

export function updateWorkspace(
  workspaceId: string,
  command: { displayName?: string; available?: boolean },
): Promise<WorkspaceResource> {
  return apiPatch<typeof command, WorkspaceResource>(`/api/settings/workspaces/${workspaceId}`, command);
}

export function selectWorkspace(workspaceId: string): Promise<WorkspaceResource> {
  return apiPost<undefined, WorkspaceResource>(`/api/settings/workspaces/${workspaceId}/select`, undefined);
}

export function recycleWorkspace(workspaceId: string): Promise<WorkspaceResource> {
  return apiPost<undefined, WorkspaceResource>(`/api/settings/workspaces/${workspaceId}/recycle`, undefined);
}

export function restoreWorkspace(workspaceId: string): Promise<WorkspaceResource> {
  return apiPost<undefined, WorkspaceResource>(`/api/settings/workspaces/${workspaceId}/restore`, undefined);
}

export function getWorkspaceDeletionImpact(workspaceId: string): Promise<WorkspaceDeletionImpactResource> {
  return apiGet<WorkspaceDeletionImpactResource>(`/api/settings/workspaces/${workspaceId}/deletion-impact`);
}

export function permanentlyDeleteWorkspace(workspaceId: string, confirmation: string): Promise<void> {
  return apiRequest<void>(
    `/api/settings/workspaces/${workspaceId}?confirmation=${encodeURIComponent(confirmation)}`,
    { method: "DELETE" },
  );
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
