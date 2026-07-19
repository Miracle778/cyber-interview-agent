import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "../../shared/api/client";
import type {
  ActiveQuestion,
  AcceptedBulkPublication,
  AcceptedCurationCommand,
  BulkPublication,
  BulkPublicationPreflight,
  CandidateOriginSession,
  CurationSession,
  CreateReviewRoundRequest,
  QuestionBatch,
  QuestionCandidate,
  QuestionDeletionResult,
  ReviewAnswerReceipt,
  ReviewRound,
} from "./reviewTypes";

export function listCurationSessions(workspaceId: string, deletedOnly = false): Promise<CurationSession[]> {
  const query = new URLSearchParams({ workspaceId });
  if (deletedOnly) query.set("deletedOnly", "true");
  return apiGet(`/api/review/curation-sessions?${query}`);
}

export function getCurationSession(id: string): Promise<CurationSession> {
  return apiGet(`/api/review/curation-sessions/${id}`);
}

export function getQuestionCandidateOriginSession(candidateId: string): Promise<CandidateOriginSession> {
  return apiGet(`/api/review/question-candidates/${candidateId}/origin-session`);
}

export function createCurationSession(workspaceId: string, sourceRefs: string[]): Promise<CurationSession> {
  return apiPost("/api/review/curation-sessions", { workspaceId, sourceRefs });
}

export function retryCurationSession(id: string): Promise<CurationSession> {
  return apiPost(`/api/review/curation-sessions/${id}/retry`, {});
}

export function deleteCurationSession(id: string, hard = false): Promise<void> {
  return apiDelete(`/api/agent/sessions/${id}${hard ? "?hard=true" : ""}`);
}

export function restoreCurationSession(id: string): Promise<unknown> {
  return apiPost(`/api/agent/sessions/${id}/restore`, {});
}

export function submitCurationCommand(
  session: CurationSession,
  text: string,
  idempotencyKey: string,
  providerModelId: string | null = null,
  reasoningEffort: "none" | "low" | "medium" | "high" = "none",
): Promise<AcceptedCurationCommand> {
  return apiPost(`/api/review/curation-sessions/${session.id}/commands`, {
    text,
    summaryVersion: session.summaryVersion,
    idempotencyKey,
    providerModelId,
    reasoningEffort,
  });
}

export function retryCurationCommand(commandId: string): Promise<AcceptedCurationCommand> {
  return apiPost(`/api/review/curation-commands/${commandId}/retry`, {});
}

export function abandonCurationCommand(commandId: string): Promise<void> {
  return apiPost(`/api/review/curation-commands/${commandId}/abandon`, {});
}

export function getBulkPublicationPreflight(sessionId: string): Promise<BulkPublicationPreflight> {
  return apiGet(`/api/review/curation-sessions/${sessionId}/bulk-publication/preflight`);
}

export function startBulkPublication(
  sessionId: string,
  summaryVersion: number,
  candidateIds: string[],
  idempotencyKey: string,
): Promise<AcceptedBulkPublication> {
  return apiPost(`/api/review/curation-sessions/${sessionId}/bulk-publications`, {
    summaryVersion,
    candidateIds,
    idempotencyKey,
  });
}

export function retryBulkPublication(operationId: string, idempotencyKey: string): Promise<AcceptedBulkPublication> {
  return apiPost(`/api/review/bulk-publications/${operationId}/retry`, { idempotencyKey });
}

export function getBulkPublication(operationId: string): Promise<BulkPublication> {
  return apiGet(`/api/review/bulk-publications/${operationId}`);
}

export function listQuestionBatches(workspaceId: string): Promise<QuestionBatch[]> {
  return apiGet(`/api/review/question-batches?${new URLSearchParams({ workspaceId })}`);
}

export function createQuestionBatch(workspaceId: string, sourceRefs: string[]): Promise<QuestionBatch> {
  return apiPost("/api/review/question-batches", { workspaceId, sourceRefs });
}

export function listQuestionCandidates(
  workspaceId: string,
  filters: { query?: string; topic?: string; difficulty?: string; sourceId?: string; status?: string; page?: number; deletedOnly?: boolean } = {},
): Promise<QuestionCandidate[]> {
  const query = new URLSearchParams({ workspaceId });
  Object.entries(filters).forEach(([key, value]) => value && query.set(key, String(value)));
  return apiGet(`/api/review/question-candidates?${query}`);
}

export async function listAllQuestionCandidates(
  workspaceId: string,
  filters: { query?: string; topic?: string; difficulty?: string; sourceId?: string; status?: string; deletedOnly?: boolean } = {},
): Promise<QuestionCandidate[]> {
  const items: QuestionCandidate[] = [];
  for (let page = 1; page <= 20; page += 1) {
    const batch = await listQuestionCandidates(workspaceId, { ...filters, page });
    items.push(...batch);
    if (batch.length < 50) break;
  }
  return items;
}

export function getQuestionCandidate(id: string): Promise<QuestionCandidate> {
  return apiGet(`/api/review/question-candidates/${id}`);
}

export function updateQuestionCandidate(
  id: string,
  command: { version: number; title?: string; questionText?: string; referenceAnswer?: string; topics?: string[]; difficulty?: string; keyPoints?: string[]; followUps?: string[] },
): Promise<QuestionCandidate> {
  return apiPatch(`/api/review/question-candidates/${id}`, command);
}

export function rewriteQuestionCandidate(id: string, feedback: string): Promise<CurationSession> {
  return apiPost(`/api/review/question-candidates/${id}/rewrite`, { feedback });
}

export function updateQuestionCandidateNote(id: string, note: string): Promise<QuestionCandidate> {
  return apiPut(`/api/review/question-candidates/${id}/note`, { note });
}

export function publishQuestionCandidate(id: string, idempotencyKey: string): Promise<QuestionCandidate> {
  return apiPost(`/api/review/question-candidates/${id}/publish`, { idempotencyKey });
}

export function updateActiveQuestionVersion(id: string, targetQuestionId: string, expectedActiveHash: string, idempotencyKey: string): Promise<QuestionCandidate> {
  return apiPost(`/api/review/question-candidates/${id}/update-active-version`, { targetQuestionId, expectedActiveHash, idempotencyKey });
}

export function deleteQuestionCandidate(id: string, expectedVersion: number | null, reason = ""): Promise<QuestionDeletionResult> {
  return apiPost(`/api/review/question-candidates/${id}/delete`, { idempotencyKey: crypto.randomUUID(), expectedVersion, reason });
}

export function bulkDeleteQuestionCandidates(workspaceId: string, candidates: QuestionCandidate[], reason = ""): Promise<QuestionDeletionResult> {
  return apiPost("/api/review/question-candidates/bulk-delete", {
    workspaceId,
    idempotencyKey: crypto.randomUUID(),
    items: candidates.map((candidate) => ({ candidateId: candidate.id, expectedVersion: candidate.draft?.version ?? null })),
    reason,
  });
}

export function restoreQuestionCandidate(id: string): Promise<QuestionCandidate> {
  return apiPost(`/api/review/question-candidates/${id}/restore`, {});
}

export function listActiveQuestions(workspaceId: string): Promise<ActiveQuestion[]> {
  return apiGet(`/api/review/questions?${new URLSearchParams({ workspaceId })}`);
}

export function listReviewRounds(workspaceId: string): Promise<ReviewRound[]> {
  return apiGet(`/api/review/rounds?${new URLSearchParams({ workspaceId })}`);
}

export function getReviewRound(id: string): Promise<ReviewRound> {
  return apiGet(`/api/review/rounds/${id}`);
}

export function createReviewRound(command: CreateReviewRoundRequest): Promise<ReviewRound> {
  return apiPost("/api/review/rounds", command);
}

export function submitReviewAnswer(round: ReviewRound, value: string, idempotencyKey: string): Promise<ReviewAnswerReceipt> {
  if (!round.currentInput) throw new Error("当前轮次没有待回答输入");
  return apiPost(`/api/review/rounds/${round.id}/answers`, {
    inputRequestId: round.currentInput.id,
    version: round.currentInput.version,
    idempotencyKey,
    value,
  });
}

export function retryReviewEvaluation(roundId: string, idempotencyKey: string): Promise<ReviewAnswerReceipt> {
  return apiPost(`/api/review/rounds/${roundId}/retry-evaluation`, { idempotencyKey });
}

export function skipReviewQuestion(round: ReviewRound, idempotencyKey: string): Promise<ReviewRound> {
  if (!round.currentInput) throw new Error("当前轮次没有待跳过输入");
  return apiPost(`/api/review/rounds/${round.id}/skip`, {
    inputRequestId: round.currentInput.id,
    version: round.currentInput.version,
    idempotencyKey,
  });
}

export function cancelReviewRound(id: string): Promise<ReviewRound> {
  return apiPost(`/api/review/rounds/${id}/cancel`, {});
}

export function createReviewDiscussion(roundId: string, ordinal: number, message: string) {
  return apiPost(`/api/review/rounds/${roundId}/discussions`, { ordinal, message });
}
