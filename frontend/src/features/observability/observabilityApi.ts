import { ZodError } from "zod";
import { apiGet } from "../../shared/api/client";
import {
  executionSummaryPageSchema,
  executionSummarySchema,
  operationSummaryPageSchema,
  type ExecutionFilters,
  type ExecutionSummary,
  type ExecutionSummaryPage,
  type OperationSummary,
} from "./observabilityTypes";


export class ObservabilityPayloadError extends Error {}

function parsePayload<T>(parser: () => T): T {
  try {
    return parser();
  } catch (error) {
    if (error instanceof ZodError) {
      throw new ObservabilityPayloadError("运行数据格式不完整");
    }
    throw error;
  }
}

export async function listObservabilityExecutions(
  workspaceId: string,
  filters: ExecutionFilters,
  signal?: AbortSignal,
): Promise<ExecutionSummaryPage> {
  const query = new URLSearchParams({
    workspaceId,
    limit: "200",
  });
  if (filters.search.trim()) query.set("search", filters.search.trim());
  if (filters.status) query.set("status", filters.status);
  if (filters.agentName) query.set("agentName", filters.agentName);
  if (filters.includeSystemAgents) {
    query.set("includeSystemAgents", "true");
  }
  const payload = await apiGet<unknown>(
    `/api/agent-observability/executions?${query.toString()}`,
    { signal },
  );
  return parsePayload(() => executionSummaryPageSchema.parse(payload));
}

export async function getObservabilityExecution(
  workspaceId: string,
  executionId: string,
  signal?: AbortSignal,
): Promise<ExecutionSummary> {
  const payload = await apiGet<unknown>(
    `/api/agent-observability/executions/${encodeURIComponent(executionId)}?workspaceId=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
  return parsePayload(() => executionSummarySchema.parse(payload));
}

export async function listObservabilityOperations(
  workspaceId: string,
  executionId: string,
  signal?: AbortSignal,
): Promise<OperationSummary[]> {
  const payload = await apiGet<unknown>(
    `/api/agent-observability/executions/${encodeURIComponent(executionId)}/operations?workspaceId=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
  return parsePayload(() => operationSummaryPageSchema.parse(payload).items);
}
