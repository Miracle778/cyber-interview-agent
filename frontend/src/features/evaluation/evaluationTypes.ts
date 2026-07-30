import { z } from "zod";


export const evaluationDimensionSchema = z.object({
  dimensionId: z.string(),
  source: z.string(),
  status: z.string(),
  score: z.number().int().nullable(),
  confidence: z.number().nullable(),
  summary: z.string(),
  citedEventHashes: z.array(z.string()),
  citedArtifactHashes: z.array(z.string()),
  risks: z.array(z.string()),
});

export const evaluationRunSchema = z.object({
  id: z.string(),
  workspaceId: z.string(),
  executionId: z.string(),
  evalPackId: z.string(),
  evalPackVersion: z.number().int(),
  trigger: z.string(),
  status: z.string(),
  frozenInputHash: z.string(),
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
  version: z.number().int(),
  snapshotHash: z.string(),
  containsPrivateBodies: z.boolean(),
  redactionSummary: z.string(),
  createdAt: z.string(),
});

export const regressionCaseListSchema = z.object({
  items: z.array(regressionCaseSchema),
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
  judgeProviderModelId: z.string().nullable(),
  promptVersion: z.string(),
  schemaVersion: z.string(),
  toolVersion: z.string(),
  runCount: z.number().int().nonnegative(),
  successRate: z.number(),
  deterministicIssueRate: z.number(),
  averageJudgeScore: z.number().nullable(),
  humanReviewRate: z.number(),
  averageLatencyMs: z.number().nullable(),
  averageTokens: z.number(),
  averageContextTokens: z.number(),
});

export const evaluationTrendListSchema = z.object({
  items: z.array(evaluationTrendPointSchema),
});

export type EvaluationRun = z.infer<typeof evaluationRunSchema>;
export type EvaluationDimension = z.infer<typeof evaluationDimensionSchema>;
export type EvaluationFeedback = z.infer<typeof feedbackSchema>;
export type RegressionCase = z.infer<typeof regressionCaseSchema>;
export type EvaluationComparison = z.infer<typeof comparisonSchema>;
export type EvaluationTrendPoint = z.infer<typeof evaluationTrendPointSchema>;
