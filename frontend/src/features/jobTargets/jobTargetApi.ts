import { apiGet, apiRequest } from "../../shared/api/client";
import type { DeepDiveResource, JobAnalysis, JobDocumentVersion, JobRequirement, JobTarget, TargetReadiness } from "./jobTargetTypes";

const key = (prefix: string) => `${prefix}-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`;
const json = (method: string, body: unknown, prefix: string) => ({
  method,
  body: JSON.stringify(body),
  headers: { "Idempotency-Key": key(prefix) },
});

export const listJobTargets = (workspaceId: string, signal?: AbortSignal) =>
  apiGet<JobTarget[]>(`/api/workspaces/${workspaceId}/job-targets?includeArchived=true`, { signal });

export const createJobTarget = (workspaceId: string, input: { roleName: string; seniority: string; companyName?: string; sourceUrl?: string }) =>
  apiRequest<JobTarget>(`/api/workspaces/${workspaceId}/job-targets`, json("POST", input, "target"));

export const updateJobTarget = (
  workspaceId: string,
  target: JobTarget,
  input: { roleName: string; seniority: string; companyName?: string; sourceUrl?: string },
) =>
  apiRequest<JobTarget>(
    `/api/job-targets/${target.id}`,
    json("PATCH", { workspaceId, expectedVersion: target.version, ...input }, "target-update"),
  );

export const createDocumentVersion = (workspaceId: string, targetId: string, body: string) =>
  apiRequest<JobDocumentVersion>(`/api/job-targets/${targetId}/document-versions`, json("POST", { workspaceId, sourceKind: "jd_text", body }, "jd"));

export const confirmDocumentVersion = (workspaceId: string, target: JobTarget, versionId: string) =>
  apiRequest<JobTarget>(`/api/job-targets/${target.id}/document-versions/${versionId}/confirm`, json("POST", { workspaceId, expectedVersion: target.version }, "confirm-jd"));

export const listRequirements = (workspaceId: string, targetId: string, signal?: AbortSignal) =>
  apiGet<JobRequirement[]>(`/api/job-targets/${targetId}/requirements?workspaceId=${workspaceId}`, { signal });

export const decideRequirements = (workspaceId: string, targetId: string, decisions: { requirementId: string; expectedVersion: number; decision: "pending" | "confirmed" | "rejected" }[]) =>
  apiRequest<{ confirmedIds: string[]; rejectedIds: string[]; pendingIds: string[]; excludedIds: string[] }>(
    `/api/job-targets/${targetId}/requirements/decisions`,
    json("POST", { workspaceId, decisions }, "requirements"),
  );

export const startAnalysis = (workspaceId: string, target: JobTarget) =>
  apiRequest<JobAnalysis>(`/api/job-targets/${target.id}/analysis-runs`, json("POST", { workspaceId, expectedVersion: target.version }, "analysis"));

export const getCurrentAnalysis = (workspaceId: string, targetId: string, signal?: AbortSignal) =>
  apiGet<JobAnalysis | null>(`/api/job-targets/${targetId}/analysis-runs/current?workspaceId=${workspaceId}`, { signal });

export const controlAnalysis = (workspaceId: string, targetId: string, analysis: JobAnalysis, action: "pause" | "resume" | "terminate") =>
  apiRequest<JobAnalysis>(`/api/job-targets/${targetId}/analysis-runs/${analysis.id}/${action}`, json("POST", { workspaceId, expectedVersion: analysis.version }, `analysis-${action}`));

export const getReadiness = (workspaceId: string, targetId: string, signal?: AbortSignal) =>
  apiGet<TargetReadiness>(`/api/job-targets/${targetId}/readiness?workspaceId=${workspaceId}`, { signal });

export const setProjectPriorities = (workspaceId: string, target: JobTarget, coreProjectId: string, supplementaryProjectIds: string[]) =>
  apiRequest<{ jobTargetId: string; coreProjectId: string; supplementaryProjectIds: string[]; version: number }>(
    `/api/job-targets/${target.id}/project-priorities`,
    json("PUT", { workspaceId, expectedVersion: target.version, coreProjectId, supplementaryProjectIds }, "priorities"),
  );

export const createDeepDive = (workspaceId: string, targetId: string, projectClaimId: string) =>
  apiRequest<DeepDiveResource>(`/api/job-targets/${targetId}/projects/${projectClaimId}/deep-dives`, json("POST", { workspaceId, projectClaimId }, "deep-dive"));

export const getCurrentDeepDive = (workspaceId: string, targetId: string, projectClaimId: string, signal?: AbortSignal) =>
  apiGet<DeepDiveResource | null>(`/api/job-targets/${targetId}/projects/${projectClaimId}/deep-dives/current?workspaceId=${workspaceId}`, { signal });

export const answerDeepDive = (
  workspaceId: string,
  targetId: string,
  diveId: string,
  content: string,
  configuration: { providerModelId?: string; reasoningEffort: "none" | "low" | "medium" | "high" },
) =>
  apiRequest<DeepDiveResource>(`/api/job-targets/${targetId}/deep-dives/${diveId}/messages`, json("POST", { workspaceId, content, ...configuration }, "answer"));

export const controlDeepDive = (workspaceId: string, targetId: string, diveId: string, version: number, action: "pause" | "resume" | "terminate") =>
  apiRequest<DeepDiveResource>(`/api/job-targets/${targetId}/deep-dives/${diveId}/${action}`, json("POST", { workspaceId, expectedVersion: version }, `dive-${action}`));

export const restartDeepDive = (workspaceId: string, targetId: string, diveId: string, version: number) =>
  apiRequest<DeepDiveResource>(`/api/job-targets/${targetId}/deep-dives/${diveId}/restart`, json("POST", { workspaceId, expectedVersion: version }, "restart-deep-dive"));

export const retryDeepDive = (workspaceId: string, targetId: string, diveId: string, executionId: string) =>
  apiRequest<DeepDiveResource>(`/api/job-targets/${targetId}/deep-dives/${diveId}/executions/${executionId}/retry`, json("POST", { workspaceId, expectedVersion: 1 }, "retry"));

export const cancelDeepDive = (workspaceId: string, targetId: string, diveId: string, executionId: string) =>
  apiRequest<DeepDiveResource>(`/api/job-targets/${targetId}/deep-dives/${diveId}/executions/${executionId}/cancel`, json("POST", { workspaceId, expectedVersion: 1 }, "cancel-deep-dive"));

export const resolveDeepDiveMessage = (workspaceId: string, targetId: string, diveId: string, messageId: string, resolution: "abandoned" | "replaced", replacementContent?: string) =>
  apiRequest<DeepDiveResource>(`/api/job-targets/${targetId}/deep-dives/${diveId}/messages/${messageId}/resolve`, json("POST", { workspaceId, resolution, replacementContent }, "resolve-message"));

export const decideProjectQuestion = (workspaceId: string, targetId: string, candidateId: string, decision: "confirmed" | "ignored" | "duplicate") =>
  apiRequest<void>(`/api/job-targets/${targetId}/question-candidates/${candidateId}/decision`, json("POST", { workspaceId, decision }, "question-decision"));

export const decideProjectQuestions = (workspaceId: string, targetId: string, candidateIds: string[], decision: "confirmed" | "ignored") =>
  apiRequest<void>(`/api/job-targets/${targetId}/question-candidates/decisions`, json("POST", { workspaceId, candidateIds, decision }, "question-decisions"));

export const editProjectQuestion = (workspaceId: string, targetId: string, candidateId: string, input: { title: string; question: string }) =>
  apiRequest<void>(`/api/job-targets/${targetId}/question-candidates/${candidateId}`, json("PUT", { workspaceId, ...input }, "question-edit"));

export const dispatchProjectGap = (workspaceId: string, targetId: string, gapId: string) =>
  apiRequest(`/api/job-targets/${targetId}/gaps/${gapId}/dispatch`, json("POST", { workspaceId }, "dispatch-gap"));
