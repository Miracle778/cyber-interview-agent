import { ZodError } from "zod";
import { apiGet, apiPost } from "../../shared/api/client";
import {
  executionSummaryPageSchema,
  executionSummarySchema,
  operationSummaryPageSchema,
  traceEventContentSchema,
  traceEventSummaryPageSchema,
  traceExportSchema,
  type ExecutionFilters,
  type ExecutionSummary,
  type ExecutionSummaryPage,
  type OperationSummary,
  type TraceEventContent,
  type TraceEventSummary,
  type TraceExport,
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

export async function listObservabilityEvents(
  workspaceId: string,
  executionId: string,
  signal?: AbortSignal,
): Promise<TraceEventSummary[]> {
  const payload = await apiGet<unknown>(
    `/api/agent-observability/executions/${encodeURIComponent(executionId)}/events?workspaceId=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
  return parsePayload(() => traceEventSummaryPageSchema.parse(payload).items);
}

export async function getTraceEventContent(
  workspaceId: string,
  executionId: string,
  eventId: string,
  offset = 0,
  signal?: AbortSignal,
): Promise<TraceEventContent> {
  const query = new URLSearchParams({
    workspaceId,
    offset: String(offset),
    limit: "65536",
  });
  const payload = await apiGet<unknown>(
    `/api/agent-observability/executions/${encodeURIComponent(executionId)}/events/${encodeURIComponent(eventId)}/content?${query.toString()}`,
    { signal },
  );
  return parsePayload(() => traceEventContentSchema.parse(payload));
}

export async function createTraceExport(
  workspaceId: string,
  executionId: string,
  includeStoredBodies: boolean,
): Promise<TraceExport> {
  const idempotencyKey =
    globalThis.crypto?.randomUUID?.() ??
    `trace-export-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const payload = await apiPost<
    { metadataOnly: boolean; includeStoredBodies: boolean },
    unknown
  >(
    `/api/agent-observability/executions/${encodeURIComponent(executionId)}/exports?workspaceId=${encodeURIComponent(workspaceId)}`,
    {
      metadataOnly: !includeStoredBodies,
      includeStoredBodies,
    },
    { headers: { "Idempotency-Key": idempotencyKey } },
  );
  return parsePayload(() => traceExportSchema.parse(payload));
}

export function traceExportDownloadUrl(
  workspaceId: string,
  exportId: string,
): string {
  return `/api/agent-observability/exports/${encodeURIComponent(exportId)}?workspaceId=${encodeURIComponent(workspaceId)}`;
}
