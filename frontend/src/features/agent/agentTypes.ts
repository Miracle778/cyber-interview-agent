export type AgentExecutionStatus =
  | "running"
  | "cancelling"
  | "waiting_for_input"
  | "waiting_for_approval"
  | "interrupted"
  | "completed"
  | "failed"
  | "cancelled";

export interface AgentSession {
  id: string;
  workspaceId: string;
  kind: string;
  title: string;
  status: string;
  createdAt: string;
  updatedAt: string;
  latestExecutionId: string | null;
  latestExecutionStatus?: AgentExecutionStatus | null;
  pendingActionCount?: number;
  deletedAt?: string | null;
  lastMessagePreview?: string | null;
}

export interface AgentExecution {
  id: string;
  sessionId: string;
  inputMessageId?: string | null;
  retryOfExecutionId?: string | null;
  status: AgentExecutionStatus;
  configuration?: {
    providerModelId: string | null;
    reasoningEffort: "none" | "low" | "medium" | "high";
  };
  cancelRequestedAt?: string | null;
  resumeCount: number;
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface StreamingAssistantState {
  text: string;
  status: "running" | "cancelling" | "cancelled" | "completed" | "failed" | "interrupted";
}

export interface AgentMessage {
  id: string;
  executionId: string | null;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  messageKind?: string;
  payload?: Record<string, unknown>;
  createdAt: string;
  replacesMessageId?: string | null;
  resolutionStatus?: "active" | "unresolved" | "replaced" | "abandoned";
}

export interface AgentSessionDetail extends AgentSession {
  usage: {
    inputTokens: number;
    outputTokens: number;
    totalTokens: number;
    callCount: number;
    estimatedCount: number;
  };
  contextUsage: {
    currentTokens: number;
    thresholdTokens: number;
    estimated: boolean;
  };
  contextCompacted?: boolean;
  latestWarning: { code: string; message: string } | null;
  messages: AgentMessage[];
  executions: AgentExecution[];
  latestExecution: AgentExecution | null;
  currentAction: {
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
  executionId: string | null;
  timestamp: string;
  payload: TPayload;
}

export type AgentEvent =
  | EventEnvelope<"assistant.delta", { text: string }>
  | EventEnvelope<"approval.required" | "approval.resolved", Record<string, unknown>>
  | EventEnvelope<"artifact.changed" | "publication.changed", Record<string, unknown>>
  | EventEnvelope<"execution.warning" | "execution.failed", { code: string; message?: string }>
  | EventEnvelope<string, Record<string, unknown>>;
