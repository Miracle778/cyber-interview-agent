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

export type ObservabilityCapability = z.infer<
  typeof observabilityCapabilitySchema
>;
export type ExecutionSummary = z.infer<typeof executionSummarySchema>;
export type ExecutionSummaryPage = z.infer<typeof executionSummaryPageSchema>;
export type ExecutionChangedEvent = z.infer<typeof executionChangedEventSchema>;

export interface ExecutionFilters {
  search: string;
  status: string;
  agentName: string;
  includeSystemAgents: boolean;
}
