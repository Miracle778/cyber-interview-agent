import { apiDelete, apiGet, apiPatch, apiPost } from "../../shared/api/client";
import type {
  ActiveQuestion,
  CurationCommandReceipt,
  CurationSession,
  CreateReviewRoundRequest,
  QuestionBatch,
  QuestionCandidate,
  ReviewAnswerReceipt,
  ReviewRound,
} from "./reviewTypes";

export function listCurationSessions(workspaceId: string): Promise<CurationSession[]> {
  return apiGet(`/api/review/curation-sessions?${new URLSearchParams({ workspaceId })}`);
}

export function getCurationSession(id: string): Promise<CurationSession> {
  return apiGet(`/api/review/curation-sessions/${id}`);
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

export function submitCurationCommand(
  session: CurationSession,
  text: string,
  idempotencyKey: string,
): Promise<CurationCommandReceipt> {
  return apiPost(`/api/review/curation-sessions/${session.id}/commands`, {
    text,
    summaryVersion: session.summaryVersion,
    idempotencyKey,
  });
}

export function listQuestionBatches(workspaceId: string): Promise<QuestionBatch[]> {
  return apiGet(`/api/review/question-batches?${new URLSearchParams({ workspaceId })}`);
}

export function createQuestionBatch(workspaceId: string, sourceRefs: string[]): Promise<QuestionBatch> {
  return apiPost("/api/review/question-batches", { workspaceId, sourceRefs });
}

export function listQuestionCandidates(
  workspaceId: string,
  filters: { query?: string; topic?: string; difficulty?: string; sourceId?: string; status?: string } = {},
): Promise<QuestionCandidate[]> {
  const query = new URLSearchParams({ workspaceId });
  Object.entries(filters).forEach(([key, value]) => value && query.set(key, value));
  return apiGet(`/api/review/question-candidates?${query}`);
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
