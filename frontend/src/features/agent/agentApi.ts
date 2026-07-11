import { apiGet, apiPost } from "../../shared/api/client";
import type { AgentRun, AgentSession, AgentSessionDetail } from "./agentTypes";

export interface CreateAgentSessionCommand {
  workspaceId: string;
  graphId: string;
  graphVersion: number;
  title: string;
}

export function createAgentSession(
  command: CreateAgentSessionCommand,
): Promise<AgentSession> {
  return apiPost<CreateAgentSessionCommand, AgentSession>(
    "/api/agent/sessions",
    command,
  );
}

export function listAgentSessions(workspaceId: string): Promise<AgentSession[]> {
  return apiGet<AgentSession[]>(
    `/api/agent/sessions?workspaceId=${encodeURIComponent(workspaceId)}`,
  );
}

export function getAgentSession(sessionId: string): Promise<AgentSessionDetail> {
  return apiGet<AgentSessionDetail>(`/api/agent/sessions/${sessionId}`);
}

export function startAgentRun(
  sessionId: string,
  input: Record<string, unknown>,
): Promise<AgentRun> {
  return apiPost<{ input: Record<string, unknown> }, AgentRun>(
    `/api/agent/sessions/${sessionId}/runs`,
    { input },
  );
}

export function resumeAgentRun(runId: string): Promise<AgentRun> {
  return apiPost<undefined, AgentRun>(`/api/agent/runs/${runId}/resume`, undefined);
}

export function cancelAgentRun(runId: string): Promise<AgentRun> {
  return apiPost<undefined, AgentRun>(`/api/agent/runs/${runId}/cancel`, undefined);
}
