import { z } from "zod";


export const observabilityCapabilitySchema = z.enum([
  "open_business",
  "cancel",
  "retry",
  "resume",
  "manual_judge",
  "export_trace",
]);

export const executionSummarySchema = z.object({
  id: z.string().min(1),
  sessionId: z.string().min(1),
  workspaceId: z.string().min(1),
  graphId: z.string().min(1),
  displayName: z.string().min(1),
  system: z.boolean(),
  title: z.string().min(1),
  status: z.string().min(1),
  traceHealth: z.enum(["complete", "partial", "missing", "unavailable"]),
  capabilities: z.array(observabilityCapabilitySchema),
  route: z.string(),
  systemOperationCount: z.number().int().nonnegative(),
  modelCallCount: z.number().int().nonnegative(),
  totalTokens: z.number().int().nonnegative(),
  contextCurrentTokens: z.number().int().nonnegative(),
  contextThresholdTokens: z.number().int().nonnegative(),
  latencyMs: z.number().int().nonnegative().nullable(),
  retryCount: z.number().int().nonnegative(),
  createdAt: z.string().min(1),
  startedAt: z.string().nullable(),
  finishedAt: z.string().nullable(),
  errorCode: z.string().nullable(),
});

export const executionSummaryPageSchema = z.object({
  items: z.array(executionSummarySchema),
  nextCursor: z.string().nullable(),
  total: z.number().int().nonnegative(),
});

export const executionChangedEventSchema = z.object({
  eventId: z.string().regex(/^\d+$/),
  type: z.literal("execution.summary.changed"),
  execution: executionSummarySchema,
});

export const operationSummarySchema = z.object({
  id: z.string().min(1),
  runId: z.string().min(1),
  parentOperationId: z.string().nullable(),
  kind: z.enum(["execution", "agent", "model", "tool", "graph"]),
  name: z.string().min(1),
  agentRole: z.string().nullable(),
  status: z.string().min(1),
  startedAt: z.string().nullable(),
  finishedAt: z.string().nullable(),
  latencyMs: z.number().int().nonnegative().nullable(),
  retryCount: z.number().int().nonnegative(),
  errorCode: z.string().nullable(),
  eventCount: z.number().int().nonnegative(),
});

export const operationSummaryPageSchema = z.object({
  items: z.array(operationSummarySchema),
});

export type ObservabilityCapability = z.infer<
  typeof observabilityCapabilitySchema
>;
export type ExecutionSummary = z.infer<typeof executionSummarySchema>;
export type ExecutionSummaryPage = z.infer<typeof executionSummaryPageSchema>;
export type ExecutionChangedEvent = z.infer<typeof executionChangedEventSchema>;
export type OperationSummary = z.infer<typeof operationSummarySchema>;

export interface ExecutionFilters {
  search: string;
  status: string;
  agentName: string;
  includeSystemAgents: boolean;
}
