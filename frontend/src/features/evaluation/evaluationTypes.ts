import { z } from "zod";


export const evaluationDimensionSchema = z.object({
  dimensionId: z.string(),
  source: z.string(),
  status: z.string(),
  applicability: z.enum([
    "applicable",
    "not_applicable",
    "insufficient_evidence",
  ]).default("applicable"),
  rating: z.enum(["meets", "usable", "needs_review", "severe"]).nullable().default(null),
  severity: z.enum(["none", "low", "medium", "high", "critical"]).nullable().default(null),
  score: z.number().int().nullable(),
  confidence: z.number().nullable(),
  summary: z.string(),
  citedEventHashes: z.array(z.string()),
  citedArtifactHashes: z.array(z.string()),
  risks: z.array(z.string()),
  evidenceGaps: z.array(z.string()).default([]),
  evidenceRefs: z.array(z.string()).default([]),
});

export const evaluationRunSchema = z.object({
  id: z.string(),
  workspaceId: z.string(),
  executionId: z.string(),
  evalPackId: z.string(),
  evalPackVersion: z.number().int(),
  evaluationContractVersion: z.number().int().default(1),
  taskType: z.string().default("legacy"),
  runKind: z.enum(["historical_review", "agent_regression"]).default("historical_review"),
  trigger: z.string(),
  status: z.string(),
  frozenInputHash: z.string(),
  businessOutcomeHash: z.string().nullable().default(null),
  judgeDataScope: z.record(z.unknown()).default({}),
  judgeProviderModelId: z.string().nullable(),
  errorCode: z.string().nullable(),
  createdAt: z.string(),
  startedAt: z.string().nullable(),
  completedAt: z.string().nullable(),
  dimensions: z.array(evaluationDimensionSchema),
  deterministicResult: z.record(z.unknown()).nullable(),
  judgeSummary: z.record(z.unknown()).nullable(),
  judgeTraceRunId: z.string().nullable().optional(),
  rawSnapshot: z.record(z.unknown()).nullable().optional(),
  rawJudgeResult: z.record(z.unknown()).nullable().optional(),
});

export const evaluationRunListSchema = z.object({
  items: z.array(evaluationRunSchema),
});

export const evaluationRunStartSchema = z.object({
  judgeExecutionId: z.string().min(1),
  sourceExecutionId: z.string().min(1),
});

export const feedbackSchema = z.object({
  id: z.string(),
  workspaceId: z.string(),
  evalRunId: z.string(),
  version: z.number().int(),
  verdict: z.string(),
  dimensionId: z.string().nullable(),
  reason: z.string().nullable(),
  createdAt: z.string(),
});

export const regressionCaseSchema = z.object({
  id: z.string(),
  executionId: z.string(),
  evalPackId: z.string(),
  evalPackVersion: z.number().int(),
  evaluationContractVersion: z.number().int().default(1),
  runKind: z.enum(["historical_review", "agent_regression"]).default("historical_review"),
  version: z.number().int(),
  snapshotHash: z.string(),
  containsPrivateBodies: z.boolean(),
  redactionSummary: z.string(),
  caseContractVersion: z.number().int().default(1),
  taskType: z.string().default("legacy"),
  privacyManifest: z.record(z.unknown()).default({}),
  baselineVersions: z.record(z.unknown()).default({}),
  runnable: z.boolean().default(false),
  unavailableReason: z.string().nullable().default(null),
  availableImplementationIds: z.array(z.string()).default([]),
  createdAt: z.string(),
});

export const regressionCaseListSchema = z.object({
  items: z.array(regressionCaseSchema),
});

export const regressionRunSchema = z.object({
  id: z.string(),
  caseId: z.string(),
  caseVersion: z.number().int(),
  status: z.string(),
  baselineImplementationId: z.string(),
  candidateImplementationId: z.string(),
  baselineExecutionId: z.string().nullable(),
  candidateExecutionId: z.string().nullable(),
  baselineOutcomeHash: z.string().nullable(),
  candidateOutcomeHash: z.string().nullable(),
  deterministicComparison: z.record(z.unknown()).nullable(),
  pairwiseResult: z.record(z.unknown()).nullable(),
  infrastructureFailures: z.array(z.record(z.unknown())),
  isolationManifest: z.record(z.unknown()),
  errorCode: z.string().nullable(),
  createdAt: z.string(),
  startedAt: z.string().nullable(),
  completedAt: z.string().nullable(),
});

export const regressionRunListSchema = z.object({
  items: z.array(regressionRunSchema),
});

export const comparisonSchema = z.object({
  evalPackId: z.string(),
  evalPackVersion: z.number().int(),
  dimensionIds: z.array(z.string()),
  runs: z.array(evaluationRunSchema),
});

export const evaluationTrendPointSchema = z.object({
  bucket: z.string(),
  graphId: z.string(),
  evalPackId: z.string(),
  evalPackVersion: z.number().int(),
  evaluationContractVersion: z.number().int().default(1),
  runKind: z.enum(["historical_review", "agent_regression"]).default("historical_review"),
  judgeProviderModelId: z.string().nullable(),
  promptVersion: z.string(),
  schemaVersion: z.string(),
  toolVersion: z.string(),
  runCount: z.number().int().nonnegative(),
  successRate: z.number(),
  deterministicIssueRate: z.number(),
  averageJudgeScore: z.number().nullable(),
  needsReviewRate: z.number().default(0),
  severeRate: z.number().default(0),
  judgeHumanAgreementRate: z.number().nullable().default(null),
  userEditRejectRate: z.number().default(0),
  infrastructureFailureRate: z.number().default(0),
  humanReviewRate: z.number(),
  averageLatencyMs: z.number().nullable(),
  averageTokens: z.number(),
  averageContextTokens: z.number(),
});

export const evaluationTrendListSchema = z.object({
  items: z.array(evaluationTrendPointSchema),
});

export type EvaluationRun = z.infer<typeof evaluationRunSchema>;
export type EvaluationRunStart = z.infer<typeof evaluationRunStartSchema>;
export type EvaluationDimension = z.infer<typeof evaluationDimensionSchema>;
export type EvaluationFeedback = z.infer<typeof feedbackSchema>;
export type RegressionCase = z.infer<typeof regressionCaseSchema>;
export type RegressionRun = z.infer<typeof regressionRunSchema>;
export type EvaluationComparison = z.infer<typeof comparisonSchema>;
export type EvaluationTrendPoint = z.infer<typeof evaluationTrendPointSchema>;
