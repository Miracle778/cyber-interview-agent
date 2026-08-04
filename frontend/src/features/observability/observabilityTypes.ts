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

export const agentDefinitionSnapshotSchema = z.object({
  snapshotVersion: z.number().int().positive(),
  legacy: z.boolean(),
  agentId: z.string().min(1).nullable(),
  agentDefinitionVersion: z.string().min(1).nullable(),
  graphVersion: z.number().int().positive().nullable(),
  builderKey: z.string().min(1).nullable(),
  promptSchemaVersions: z.record(z.string()),
  inputSchemaVersion: z.string().min(1).nullable(),
  outputSchemaVersion: z.string().min(1).nullable(),
  childComponents: z.array(z.string()),
  modelRoles: z.array(z.string()),
  allowedTools: z.array(z.string()),
  allowedScopes: z.array(z.string()),
  toolsetDigest: z.string().nullable(),
  modelBindingDigest: z.string().nullable(),
  contextPolicyId: z.string().min(1).nullable(),
  retryPolicyId: z.string().min(1).nullable(),
  tracePolicyId: z.string().min(1).nullable(),
  evalPackId: z.string().min(1).nullable(),
  evalPackVersion: z.number().int().positive().nullable(),
});

export const executionDetailSchema = executionSummarySchema.extend({
  definitionSnapshot: agentDefinitionSnapshotSchema,
});

export const executionSummaryPageSchema = z.object({
  items: z.array(executionSummarySchema),
  nextCursor: z.string().nullable(),
  total: z.number().int().nonnegative(),
  statusCounts: z.record(z.number().int().nonnegative()).optional()
    .transform((value) => value ?? {}),
  agentCounts: z.record(z.record(z.number().int().nonnegative())).optional()
    .transform((value) => value ?? {}),
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

export const traceEventSummarySchema = z.object({
  eventId: z.string().min(1),
  operationId: z.string().min(1),
  eventType: z.string().min(1),
  observedAt: z.string().nullable(),
  byteLength: z.number().int().nonnegative(),
  sequence: z.number().int().nonnegative(),
  bodyState: z.enum(["available", "quarantined", "deleted", "unavailable"])
    .optional()
    .transform((value) => value ?? "available"),
});

export const traceEventSummaryPageSchema = z.object({
  items: z.array(traceEventSummarySchema),
});

export const traceEventContentSchema = z.object({
  eventId: z.string().min(1),
  eventType: z.string().min(1),
  content: z.string(),
  contentEncoding: z.literal("utf-8-json"),
  offset: z.number().int().nonnegative(),
  nextOffset: z.number().int().nonnegative().nullable().optional()
    .transform((value) => value ?? null),
  complete: z.boolean(),
  sha256: z.string().min(1),
  redactionsApplied: z.boolean(),
  reasoning: z.unknown().optional(),
});

export const traceExportSchema = z.object({
  id: z.string().min(1),
  workspaceId: z.string().min(1),
  runId: z.string().min(1),
  status: z.enum(["pending", "completed", "failed"]),
  metadataOnly: z.boolean(),
  includesBodies: z.boolean(),
  artifactSha256: z.string().nullable(),
  errorCode: z.string().nullable(),
  createdAt: z.string().min(1),
  completedAt: z.string().nullable(),
});

export type ObservabilityCapability = z.infer<
  typeof observabilityCapabilitySchema
>;
export type ExecutionSummary = z.infer<typeof executionSummarySchema>;
export type AgentDefinitionSnapshot = z.infer<typeof agentDefinitionSnapshotSchema>;
export type ExecutionDetail = z.infer<typeof executionDetailSchema>;
export type ExecutionSummaryPage = z.infer<typeof executionSummaryPageSchema>;
export type ExecutionChangedEvent = z.infer<typeof executionChangedEventSchema>;
export type OperationSummary = z.infer<typeof operationSummarySchema>;
export type TraceEventSummary = z.infer<typeof traceEventSummarySchema>;
export type TraceEventContent = z.infer<typeof traceEventContentSchema>;
export type TraceExport = z.infer<typeof traceExportSchema>;

export interface ExecutionFilters {
  search: string;
  status: string;
  agentName: string;
  includeSystemAgents: boolean;
}
