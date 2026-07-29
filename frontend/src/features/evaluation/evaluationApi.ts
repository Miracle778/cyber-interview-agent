import { z, ZodError } from "zod";
import { apiGet, apiPost } from "../../shared/api/client";
import {
  comparisonSchema,
  evaluationRunListSchema,
  evaluationRunSchema,
  feedbackSchema,
  regressionCaseListSchema,
  regressionCaseSchema,
  type EvaluationComparison,
  type EvaluationFeedback,
  type EvaluationRun,
  type RegressionCase,
} from "./evaluationTypes";


export class EvaluationPayloadError extends Error {}

function parse<T>(read: () => T): T {
  try {
    return read();
  } catch (error) {
    if (error instanceof ZodError) {
      throw new EvaluationPayloadError("质量评估数据格式不完整");
    }
    throw error;
  }
}

export async function listEvaluationRuns(
  workspaceId: string,
  executionId?: string,
  signal?: AbortSignal,
): Promise<EvaluationRun[]> {
  const query = new URLSearchParams({ workspaceId });
  if (executionId) query.set("executionId", executionId);
  const payload = await apiGet<unknown>(
    `/api/agent-evaluations/runs?${query.toString()}`,
    { signal },
  );
  return parse(() => evaluationRunListSchema.parse(payload).items);
}

export async function createEvaluationRun(
  workspaceId: string,
  executionId: string,
): Promise<EvaluationRun> {
  const idempotencyKey =
    globalThis.crypto?.randomUUID?.() ??
    `manual-judge-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const payload = await apiPost<{ executionId: string }, unknown>(
    `/api/agent-evaluations/runs?workspaceId=${encodeURIComponent(workspaceId)}`,
    { executionId },
    { headers: { "Idempotency-Key": idempotencyKey } },
  );
  return parse(() => evaluationRunSchema.parse(payload));
}

export async function submitEvaluationFeedback(
  workspaceId: string,
  evalRunId: string,
  verdict: "accurate" | "incorrect" | "uncertain",
  reason: string,
): Promise<EvaluationFeedback> {
  const payload = await apiPost<
    { verdict: string; reason: string | null },
    unknown
  >(
    `/api/agent-evaluations/runs/${encodeURIComponent(evalRunId)}/feedback?workspaceId=${encodeURIComponent(workspaceId)}`,
    { verdict, reason: reason.trim() || null },
  );
  return parse(() => feedbackSchema.parse(payload));
}

export async function listEvaluationFeedback(
  workspaceId: string,
  evalRunId: string,
  signal?: AbortSignal,
): Promise<EvaluationFeedback[]> {
  const payload = await apiGet<unknown>(
    `/api/agent-evaluations/runs/${encodeURIComponent(evalRunId)}/feedback?workspaceId=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
  return parse(() => z.array(feedbackSchema).parse(payload));
}

export async function createRegressionCase(
  workspaceId: string,
  evalRunId: string,
  includePrivateBodies: boolean,
): Promise<RegressionCase> {
  const payload = await apiPost<
    {
      evalRunId: string;
      confirmed: boolean;
      includePrivateBodies: boolean;
      expectedInvariants: string[];
    },
    unknown
  >(
    `/api/agent-evaluations/regression-cases?workspaceId=${encodeURIComponent(workspaceId)}`,
    {
      evalRunId,
      confirmed: true,
      includePrivateBodies,
      expectedInvariants: ["维度 ID 与 Eval Pack 版本保持兼容"],
    },
  );
  return parse(() => regressionCaseSchema.parse(payload));
}

export async function listRegressionCases(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<RegressionCase[]> {
  const payload = await apiGet<unknown>(
    `/api/agent-evaluations/regression-cases?workspaceId=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
  return parse(() => regressionCaseListSchema.parse(payload).items);
}

export async function compareEvaluationRuns(
  workspaceId: string,
  runIds: string[],
  signal?: AbortSignal,
): Promise<EvaluationComparison> {
  const query = new URLSearchParams({ workspaceId });
  for (const runId of runIds) query.append("runId", runId);
  const payload = await apiGet<unknown>(
    `/api/agent-evaluations/comparisons?${query.toString()}`,
    { signal },
  );
  return parse(() => comparisonSchema.parse(payload));
}
