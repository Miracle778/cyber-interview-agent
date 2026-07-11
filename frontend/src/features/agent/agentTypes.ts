export type AgentRunStatus =
  | "queued"
  | "running"
  | "waiting_for_approval"
  | "interrupted"
  | "completed"
  | "failed"
  | "cancelled";

export interface AgentSession {
  id: string;
  workspaceId: string;
  graphId: string;
  graphVersion: number;
  title: string;
  status: string;
  createdAt: string;
  updatedAt: string;
  lastRunId: string | null;
}

export interface AgentRun {
  id: string;
  sessionId: string;
  status: AgentRunStatus;
  resumeCount: number;
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface AgentMessage {
  id: string;
  runId: string | null;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  createdAt: string;
}

export interface AgentSessionDetail extends AgentSession {
  messages: AgentMessage[];
  latestRun: AgentRun | null;
  pendingAction: {
    id: string;
    actionType: string;
    preview: Record<string, unknown>;
    status: string;
    version: number;
  } | null;
}

interface EventEnvelope<TType extends string, TPayload> {
  id: number;
  type: TType;
  sessionId: string;
  runId: string | null;
  timestamp: string;
  payload: TPayload;
}

export interface ToolEventPayload {
  toolName?: string;
  resourceScope?: string;
  resourcePath?: string;
  resourceSha256?: string;
  byteCount?: number;
  latencyMs?: number;
  code?: string;
}

export type AgentEvent =
  | EventEnvelope<"message.delta", { text: string }>
  | EventEnvelope<"message.completed", { messageId: string; content: string }>
  | EventEnvelope<"tool.started" | "tool.completed" | "tool.failed", ToolEventPayload>
  | EventEnvelope<"hitl.required", { actionId: string }>
  | EventEnvelope<"hitl.resolved", { actionId: string; status: string; version: number }>
  | EventEnvelope<"run.failed", { code: string; message: string }>
  | EventEnvelope<string, Record<string, unknown>>;
