import { apiGet, apiPost } from "../../shared/api/client";
import type { AgentExecution, AgentSession, AgentSessionDetail } from "./agentTypes";

export interface CreateAgentSessionCommand {
  workspaceId: string;
  kind: string;
  title?: string;
}

export function createAgentSession(command: CreateAgentSessionCommand): Promise<AgentSession> {
  return apiPost<CreateAgentSessionCommand, AgentSession>("/api/agent/sessions", command);
}

export function listAgentSessions(workspaceId: string): Promise<AgentSession[]> {
  return apiGet<AgentSession[]>(
    `/api/agent/sessions?workspaceId=${encodeURIComponent(workspaceId)}`,
  );
}

export function getAgentSession(sessionId: string): Promise<AgentSessionDetail> {
  return apiGet<AgentSessionDetail>(`/api/agent/sessions/${sessionId}`);
}

export function startAgentExecution(
  sessionId: string,
  input: Record<string, unknown>,
  configuration?: { providerModelId: string | null; reasoningEffort: "none" | "low" | "medium" | "high" },
): Promise<AgentExecution> {
  const command = configuration ? { input, configuration } : { input };
  return apiPost<typeof command, AgentExecution>(
    `/api/agent/sessions/${sessionId}/executions`,
    command,
  );
}

export function cancelAgentExecution(executionId: string): Promise<AgentExecution> {
  return apiPost<undefined, AgentExecution>(
    `/api/agent/executions/${executionId}/cancel`,
    undefined,
  );
}
