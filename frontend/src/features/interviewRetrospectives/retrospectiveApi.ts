import { apiGet, apiRequest } from "../../shared/api/client";
import type {
  AnalysisReceipt,
  AnalysisReport,
  AnalysisRun,
  CandidateBatchResult,
  CandidateDecisionInput,
  CleanupReceipt,
  CleanupVersion,
  InterviewRetrospective,
  InterviewQuestion,
  RetrospectiveLifecycle,
  RetrospectiveActionItem,
  RetrospectiveCandidate,
  RetrospectivePublicationDraft,
  PublicationSection,
  RetrospectiveOutcome,
  SegmentEdit,
  SourceKind,
  SourceVersion,
  RetrospectiveConversation,
  RetrospectiveCorrectionProposal,
  RetrospectiveDeletionImpact,
} from "./retrospectiveTypes";

const commandKey = (prefix: string) =>
  `${prefix}-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`;

function command(method: string, body: unknown, prefix: string) {
  return {
    method,
    body: JSON.stringify(body),
    headers: { "Idempotency-Key": commandKey(prefix) },
  };
}

export function listRetrospectives(
  workspaceId: string,
  filters: { lifecycle: RetrospectiveLifecycle; jobTargetId?: string },
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    workspaceId,
    lifecycleStatus: filters.lifecycle,
  });
  if (filters.jobTargetId) query.set("jobTargetId", filters.jobTargetId);
  return apiGet<InterviewRetrospective[]>(
    `/api/interview-retrospectives?${query.toString()}`,
    { signal },
  );
}

export function createRetrospective(
  workspaceId: string,
  input: {
    jobTargetId: string;
    title: string;
    roundLabel: string;
    interviewDate: string | null;
    outcome: RetrospectiveOutcome;
    note: string;
  },
) {
  return apiRequest<InterviewRetrospective>(
    "/api/interview-retrospectives",
    command("POST", { workspaceId, ...input }, "retrospective-create"),
  );
}

export function addSourceVersion(
  workspaceId: string,
  retrospectiveId: string,
  input: { sourceKind: SourceKind; body: string; fileName?: string | null },
) {
  return apiRequest<SourceVersion>(
    `/api/interview-retrospectives/${retrospectiveId}/sources`,
    command("POST", { workspaceId, ...input }, "retrospective-source"),
  );
}

export function clearSourceVersion(workspaceId: string, retrospective: InterviewRetrospective) {
  return apiRequest<SourceVersion>(
    `/api/interview-retrospectives/${retrospective.id}/sources/${retrospective.activeSourceVersionId}/clear`,
    command("POST", { workspaceId, expectedVersion: retrospective.version }, "retrospective-source-clear"),
  );
}

export function transitionRetrospective(
  workspaceId: string,
  retrospective: InterviewRetrospective,
  action: "archive" | "recycle" | "restore",
) {
  return apiRequest<InterviewRetrospective>(
    `/api/interview-retrospectives/${retrospective.id}/${action}`,
    command("POST", { workspaceId, expectedVersion: retrospective.version }, `retrospective-${action}`),
  );
}

export function getRetrospectiveDeletionImpact(workspaceId: string, retrospectiveId: string) {
  return apiGet<RetrospectiveDeletionImpact>(
    `/api/interview-retrospectives/${retrospectiveId}/deletion-impact?workspaceId=${encodeURIComponent(workspaceId)}`,
  );
}

export function permanentlyDeleteRetrospective(workspaceId: string, retrospective: InterviewRetrospective) {
  return apiRequest<void>(
    `/api/interview-retrospectives/${retrospective.id}`,
    command("DELETE", { workspaceId, expectedVersion: retrospective.version }, "retrospective-delete"),
  );
}

export function getSourceVersion(
  workspaceId: string,
  retrospectiveId: string,
  sourceVersionId: string,
  signal?: AbortSignal,
) {
  return apiGet<SourceVersion>(
    `/api/interview-retrospectives/${retrospectiveId}/sources/${sourceVersionId}?workspaceId=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
}

export function startCleanup(
  workspaceId: string,
  retrospectiveId: string,
  sourceVersionId: string,
) {
  return apiRequest<CleanupReceipt>(
    `/api/interview-retrospectives/${retrospectiveId}/cleanup-runs`,
    command(
      "POST",
      { workspaceId, sourceVersionId },
      "retrospective-cleanup",
    ),
  );
}

export function getCleanup(
  workspaceId: string,
  retrospectiveId: string,
  cleanupId: string,
  signal?: AbortSignal,
) {
  return apiGet<CleanupVersion>(
    `/api/interview-retrospectives/${retrospectiveId}/cleanup-runs/${cleanupId}?workspaceId=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
}

export function getCurrentCleanup(
  workspaceId: string,
  retrospectiveId: string,
  signal?: AbortSignal,
) {
  return apiGet<CleanupVersion | null>(
    `/api/interview-retrospectives/${retrospectiveId}/cleanup-runs/current?workspaceId=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
}

export function updateSegments(
  workspaceId: string,
  retrospectiveId: string,
  cleanupId: string,
  expectedVersion: number,
  segments: SegmentEdit[],
) {
  return apiRequest<CleanupVersion>(
    `/api/interview-retrospectives/${retrospectiveId}/cleanup-runs/${cleanupId}/segments`,
    command(
      "PATCH",
      { workspaceId, expectedVersion, segments },
      "retrospective-segments",
    ),
  );
}

export function confirmCleanup(
  workspaceId: string,
  retrospectiveId: string,
  cleanupId: string,
  expectedVersion: number,
) {
  return apiRequest<CleanupVersion>(
    `/api/interview-retrospectives/${retrospectiveId}/cleanup-runs/${cleanupId}/confirm`,
    command(
      "POST",
      { workspaceId, expectedVersion },
      "retrospective-confirm",
    ),
  );
}

export function stopCleanup(
  workspaceId: string,
  retrospectiveId: string,
  cleanupId: string,
) {
  return apiRequest<CleanupVersion>(
    `/api/interview-retrospectives/${retrospectiveId}/cleanup-runs/${cleanupId}/stop`,
    command("POST", { workspaceId }, "retrospective-stop"),
  );
}

export function resumeCleanup(
  workspaceId: string,
  retrospectiveId: string,
  cleanupId: string,
) {
  return apiRequest<CleanupReceipt>(
    `/api/interview-retrospectives/${retrospectiveId}/cleanup-runs/${cleanupId}/resume`,
    command("POST", { workspaceId }, "retrospective-resume"),
  );
}

export function startAnalysis(
  workspaceId: string,
  retrospectiveId: string,
  cleanupVersionId: string,
) {
  return apiRequest<AnalysisReceipt>(
    `/api/interview-retrospectives/${retrospectiveId}/analysis-runs`,
    command("POST", { workspaceId, cleanupVersionId }, "retrospective-analysis"),
  );
}

export function getAnalysisRun(
  workspaceId: string,
  retrospectiveId: string,
  runId: string,
  signal?: AbortSignal,
) {
  return apiGet<AnalysisRun>(
    `/api/interview-retrospectives/${retrospectiveId}/analysis-runs/${runId}?workspaceId=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
}

export function getAnalysisReport(
  workspaceId: string,
  retrospectiveId: string,
  signal?: AbortSignal,
) {
  return apiGet<AnalysisReport | null>(
    `/api/interview-retrospectives/${retrospectiveId}/report?workspaceId=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
}

export function stopAnalysis(workspaceId: string, retrospectiveId: string, runId: string) {
  return apiRequest<AnalysisRun>(
    `/api/interview-retrospectives/${retrospectiveId}/analysis-runs/${runId}/stop`,
    command("POST", { workspaceId }, "retrospective-analysis-stop"),
  );
}

export function resumeAnalysis(workspaceId: string, retrospectiveId: string, runId: string) {
  return apiRequest<AnalysisReceipt>(
    `/api/interview-retrospectives/${retrospectiveId}/analysis-runs/${runId}/resume`,
    command("POST", { workspaceId }, "retrospective-analysis-resume"),
  );
}

export function retryAnalysis(workspaceId: string, retrospectiveId: string, runId: string) {
  return apiRequest<AnalysisReceipt>(
    `/api/interview-retrospectives/${retrospectiveId}/analysis-runs/${runId}/retry`,
    command("POST", { workspaceId }, "retrospective-analysis-retry"),
  );
}

export function decideQuestion(
  workspaceId: string,
  retrospectiveId: string,
  questionId: string,
  decision: "confirmed" | "rejected" | "superseded",
  expectedVersion: number,
  editedText?: string,
) {
  return apiRequest<InterviewQuestion>(
    `/api/interview-retrospectives/${retrospectiveId}/questions/${questionId}/decision`,
    command(
      "POST",
      { workspaceId, decision, expectedVersion, editedText },
      "retrospective-question-decision",
    ),
  );
}

export function getRetrospectiveConversation(
  workspaceId: string,
  retrospectiveId: string,
  signal?: AbortSignal,
) {
  return apiGet<RetrospectiveConversation>(
    `/api/interview-retrospectives/${retrospectiveId}/conversation?workspaceId=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
}

export function sendRetrospectiveMessage(
  workspaceId: string,
  retrospectiveId: string,
  message: string,
  selectedQuestionId: string | null,
) {
  return apiRequest<{ executionId: string; status: string }>(
    `/api/interview-retrospectives/${retrospectiveId}/conversation/messages`,
    { method: "POST", body: JSON.stringify({ workspaceId, message, selectedQuestionId }) },
  );
}

export function stopRetrospectiveMessage(
  workspaceId: string,
  retrospectiveId: string,
  executionId: string,
) {
  return apiRequest<{ executionId: string; status: string }>(
    `/api/interview-retrospectives/${retrospectiveId}/conversation/executions/${executionId}/stop`,
    { method: "POST", body: JSON.stringify({ workspaceId }) },
  );
}

export function decideRetrospectiveCorrection(
  workspaceId: string,
  retrospectiveId: string,
  proposalId: string,
  decision: "confirmed" | "rejected",
) {
  return apiRequest<RetrospectiveCorrectionProposal>(
    `/api/interview-retrospectives/${retrospectiveId}/corrections/${proposalId}/decision`,
    command("POST", { workspaceId, decision }, "retrospective-correction"),
  );
}

export function listCandidates(
  workspaceId: string,
  retrospectiveId: string,
  signal?: AbortSignal,
) {
  return apiGet<RetrospectiveCandidate[]>(
    `/api/interview-retrospectives/${retrospectiveId}/candidates?workspaceId=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
}

export function decideCandidate(
  workspaceId: string,
  retrospectiveId: string,
  input: CandidateDecisionInput,
) {
  return apiRequest<RetrospectiveCandidate>(
    `/api/interview-retrospectives/${retrospectiveId}/candidates/${input.candidateId}/decision`,
    command(
      "POST",
      {
        workspaceId,
        action: input.action,
        targetResourceId: input.targetResourceId ?? null,
        actionPayload: input.actionPayload ?? {},
        expectedVersion: input.expectedVersion,
      },
      "retrospective-candidate-decision",
    ),
  );
}

export function batchDecideCandidates(
  workspaceId: string,
  retrospectiveId: string,
  inputs: CandidateDecisionInput[],
) {
  return apiRequest<CandidateBatchResult[]>(
    `/api/interview-retrospectives/${retrospectiveId}/candidates/batch-decision`,
    {
      method: "POST",
      body: JSON.stringify({
        workspaceId,
        decisions: inputs.map((input) => ({
          ...input,
          targetResourceId: input.targetResourceId ?? null,
          actionPayload: input.actionPayload ?? {},
          idempotencyKey: commandKey("retrospective-candidate-batch-item"),
        })),
      }),
    },
  );
}

export function listActions(
  workspaceId: string,
  retrospectiveId: string,
  signal?: AbortSignal,
) {
  return apiGet<RetrospectiveActionItem[]>(
    `/api/interview-retrospectives/${retrospectiveId}/actions?workspaceId=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
}

export function decideAction(
  workspaceId: string,
  retrospectiveId: string,
  actionId: string,
  decision: "completed" | "dismissed",
  expectedVersion: number,
) {
  return apiRequest<RetrospectiveActionItem>(
    `/api/interview-retrospectives/${retrospectiveId}/actions/${actionId}/decision`,
    command(
      "POST",
      { workspaceId, decision, expectedVersion },
      "retrospective-action-decision",
    ),
  );
}

export function createPublicationDraft(
  workspaceId: string,
  retrospectiveId: string,
  selectedSections: PublicationSection[],
) {
  return apiRequest<RetrospectivePublicationDraft>(
    `/api/interview-retrospectives/${retrospectiveId}/publication-drafts`,
    command(
      "POST",
      { workspaceId, selectedSections },
      "retrospective-publication-draft",
    ),
  );
}
