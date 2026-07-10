export type ProviderFormat = "openai-compatible" | "anthropic-compatible";
export type SecretSource = "keyring" | "environment";

export type ProviderConnectivityStatus =
  | "unknown"
  | "ok"
  | "secret_missing"
  | "auth_failed"
  | "model_not_found"
  | "rate_limited"
  | "timeout"
  | "network_error"
  | "protocol_error";

export interface ProviderModelResource {
  id: string;
  providerId: string;
  modelId: string;
  displayName: string;
  enabled: boolean;
  connectivityStatus: ProviderConnectivityStatus;
  lastTestedAt: string | null;
  lastErrorCode: string | null;
  lastLatencyMs: number | null;
}

export interface ProviderResource {
  id: string;
  name: string;
  apiFormat: ProviderFormat;
  baseUrl: string;
  secretSource: SecretSource;
  hasSecret: boolean;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
  models: ProviderModelResource[];
}

export interface CreateProviderCommand {
  name: string;
  apiFormat: ProviderFormat;
  baseUrl: string;
  secretSource?: SecretSource;
  apiKey?: string;
  secretRef?: string;
}

export interface UpdateProviderCommand {
  name?: string;
  apiFormat?: ProviderFormat;
  baseUrl?: string;
  apiKey?: string;
}

export interface CreateProviderModelCommand {
  modelId: string;
  displayName: string;
  enabled?: boolean;
}

export interface UpdateProviderModelCommand {
  modelId?: string;
  displayName?: string;
  enabled?: boolean;
}

export type ModelRole =
  | "question_generation"
  | "answer_evaluation"
  | "report_summarization"
  | "agent_chat";

export interface WorkspaceResource {
  id: string;
  rootPath: string;
  vaultPath: string;
  available: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface WorkspaceModelBindingsResource {
  workspaceId: string;
  bindings: Partial<Record<ModelRole, string>>;
}
