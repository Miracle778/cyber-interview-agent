import { apiGet, apiRequest } from "../../shared/api/client";
import type {
  CleanupReceipt,
  CleanupVersion,
  InterviewRetrospective,
  RetrospectiveLifecycle,
  RetrospectiveOutcome,
  SegmentEdit,
  SourceKind,
  SourceVersion,
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
