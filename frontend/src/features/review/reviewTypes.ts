export type ReviewMode = "weak-point" | "random-mixed" | "topic-focused" | "recent-mistake";
export type MasteryState = "unknown" | "weak" | "partial" | "stable" | "strong";
export type Difficulty = "easy" | "medium" | "hard";

export interface ReviewQuestion {
  id: string;
  title: string;
  questionText: string;
  referenceAnswer: string;
  topics: string[];
  difficulty: Difficulty;
  keyPoints: string[];
  followUps: string[];
  mastery: MasteryState;
}

export interface ActiveQuestion extends Omit<ReviewQuestion, "mastery"> {
  draftId: string;
  publicationId: string;
  publishedAt: string;
  questionType?: "technical" | "project_experience";
  projectClaimId?: string | null;
  projectDimension?: string | null;
  sourceJobTargetId?: string | null;
}

export interface CandidateQuestion {
  questionId: string;
  documentId: string;
  contentHash: string;
  title: string;
  questionText: string;
  referenceAnswer: string;
  topics: string[];
  difficulty: Difficulty;
  keyPoints: string[];
  followUps: string[];
}

export interface CandidateDraft {
  id: string;
  title: string;
  markdown: string;
  status: string;
  version: number;
  contentHash: string;
  documentType: string;
}

export interface QuestionCandidate {
  id: string;
  batchId: string;
  curationSessionId: string;
  liveCurationSessionId?: string | null;
  question: CandidateQuestion;
  sourceRefs: string[];
  correctionNote: string;
  reviewNote: string;
  reviewNoteUpdatedAt: string | null;
  rejectionReason?: string | null;
  rejectedAt?: string | null;
  rejectionActionId?: string | null;
  duplicateOfQuestionId: string | null;
  duplicateQuestion: CandidateQuestion | null;
  revisionOfQuestionId?: string | null;
  seedTaskId?: string | null;
  answerBasis?: CurationAnswerBasis;
  materialSupport?: CurationMaterialSupport;
  needsReview?: boolean;
  normalizationIssues?: string[];
  isActiveVersion?: boolean;
  status: "draft" | "review_pending" | "rejected" | "published";
  deletedAt?: string | null;
  deletionReason?: string;
  draft: CandidateDraft | null;
  createdAt: string;
  updatedAt: string;
}

export type CurationAnswerBasis = "source" | "mixed" | "model" | "unknown";
export type CurationMaterialSupport = "sufficient" | "partial" | "minimal" | "unknown";
export type CurationSeedTaskStatus = "pending" | "running" | "retryable" | "completed" | "degraded" | "skipped" | "interrupted";

export interface CandidateOriginSession {
  status: "available" | "recycled" | "projection_missing" | "missing";
  sessionId: string;
  session: CurationSession | null;
}

export interface QuestionDeletionResult {
  items: { candidateId: string; status: "deleted" | "already_deleted" | "blocked" | "failed"; reason: string | null }[];
}

export interface QuestionBatch {
  id: string;
  workspaceId: string;
  sessionId: string | null;
  originSessionId?: string;
  runId: string | null;
  sourceRefs: string[];
  rewriteOfBatchId: string | null;
  status: CurationBatchStatus;
  candidateCount: number;
  pendingCount: number;
  candidates: QuestionCandidate[];
  createdAt: string;
  updatedAt: string;
}

export type CurationBatchStatus =
  | "generating"
  | "paused"
  | "interrupted"
  | "review_pending"
  | "completed"
  | "failed"
  | "terminated";

export type CurationStage =
  | "queued"
  | "reading_sources"
  | "generating"
  | "pausing"
  | "paused"
  | "interrupted"
  | "merging"
  | "summarizing"
  | "waiting_for_command"
  | "publishing"
  | "completed"
  | "failed"
  | "terminated";

export interface CurationProvisionalCandidate {
  id: string;
  title: string;
  questionText: string;
  sourceRefs: string[];
  seedTaskId?: string | null;
  answerBasis?: CurationAnswerBasis;
  materialSupport?: CurationMaterialSupport;
  needsReview?: boolean;
  normalizationIssues?: string[];
  status?: CurationSeedTaskStatus | string;
  version?: number;
  errorCode?: string | null;
}

export interface CurationMessage {
  id: string;
  executionId: string | null;
  role: "user" | "assistant" | "system" | string;
  content: string;
  messageKind: string;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface CurationSource {
  id: string;
  filename: string;
  organizationState: "not_curated" | "in_progress" | "previously_curated";
}

export interface CurationSummaryItem {
  ordinal: number;
  candidateId: string;
  title: string;
  topics: string[];
  difficulty: Difficulty;
  sourceCount: number;
  recommendation: "recommend_confirm" | "suggest_reject" | "link_existing" | string;
}

export interface CurationSession {
  id: string;
  workspaceId: string;
  title: string;
  deletedAt?: string | null;
  sourceRefs: string[];
  sources: CurationSource[];
  activeBatchId: string | null;
  batchStatus: CurationBatchStatus | null;
  batchVersion: number | null;
  executionId: string | null;
  executionStatus: string | null;
  executionStartedAt: string | null;
  executionFinishedAt: string | null;
  executionErrorCode: string | null;
  executionErrorMessage: string | null;
  contextCompacted: boolean;
  contextUsage: { currentTokens: number; thresholdTokens: number; estimated: boolean };
  stage: CurationStage;
  progress: {
    phase: "discovery" | "enrichment" | null;
    completed: number;
    total: number;
    generatedCandidateCount: number;
    activeWorkers: number;
  };
  timing: { currentElapsedMs: number; cumulativeElapsedMs: number };
  controls: { canPause: boolean; canResume: boolean; canTerminate: boolean };
  provisionalCandidates: CurationProvisionalCandidate[];
  seedProgress?: { total: number; completed: number; degraded: number; retrying: number; skipped: number; pending: number };
  qualitySummary?: { source: number; mixed: number; model: number; unknown: number; needsReview: number };
  sourceWarnings?: { sourceId: string; code: string }[];
  summary: { items: CurationSummaryItem[] };
  summaryVersion: number;
  warnings: { sourceId?: string; code: string; limit?: number }[];
  preferredModelId: string | null;
  preferredReasoningEffort: "none" | "low" | "medium" | "high";
  latestCommand: {
    commandId: string;
    executionId: string | null;
    lifecycleStatus: string;
    retryCount: number;
  } | null;
  candidateCount: number;
  pendingCount: number;
  publishedCount: number;
  messages: CurationMessage[];
  usage: { inputTokens: number; outputTokens: number; totalTokens: number; callCount: number; estimatedCount: number };
  createdAt: string;
  updatedAt: string;
}

export interface CurationCommandReceipt {
  id: string;
  sessionId: string;
  summaryVersion: number;
  kind: string;
  targetIds: string[];
  status: string;
  result: Record<string, unknown>;
  createdAt: string;
  completedAt: string | null;
}

export interface AcceptedCurationCommand {
  commandId: string;
  executionId: string;
  status: "accepted";
}

export interface AcceptedCurationSeedRetry {
  receiptId: string;
  seedTaskId: string;
  executionId: string;
  status: string;
}

export interface BulkPublicationPreflight {
  sessionId: string;
  summaryVersion: number;
  publishable: string[];
  alreadyPublished: string[];
  needsReview: string[];
  blocked: string[];
}

export interface AcceptedBulkPublication {
  operationId: string;
  executionId: string;
  status: "accepted";
}

export interface BulkPublication {
  id: string;
  sessionId: string;
  executionId: string | null;
  summaryVersion: number;
  status: string;
  retryCount: number;
  items: {
    id: string;
    operationId: string;
    candidateId: string;
    idempotencyKey: string;
    status: string;
    errorCode: string | null;
    createdAt: string;
    updatedAt: string;
  }[];
  createdAt: string;
  completedAt: string | null;
}

export interface ReviewInput {
  id: string;
  roundId: string;
  ordinal: number;
  kind: "answer" | "follow_up";
  prompt: string;
  version: number;
  status: string;
  createdAt: string;
  resolvedAt: string | null;
}

export interface ReviewAttempt {
  id: string;
  roundId: string;
  ordinal: number;
  questionSnapshot: CandidateQuestion;
  answer: string | null;
  followUpAnswer: string | null;
  evaluation: {
    score: "poor" | "partial" | "good";
    missing_key_points: string[];
    evidence: string;
    mastery_suggestion: MasteryState;
  } | null;
  masterySuggestion: MasteryState | null;
  skipped: boolean;
  status: "evaluating" | "waiting_for_follow_up" | "completed" | "evaluation_failed";
  evaluationErrorCode: string | null;
  evaluationStartedAt: string | null;
  evaluationCompletedAt: string | null;
  discussionSessionId?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ReviewTimelineMessage {
  id: string;
  executionId: string | null;
  role: string;
  content: string;
  messageKind: "review_prompt" | "review_answer" | "evaluation_card" | "error" | string;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface ReviewAnswerReceipt {
  receiptId: string;
  roundId: string;
  attemptId: string;
  inputRequestId: string;
  status: "evaluating";
  acceptedAt: string;
  version: number;
}

export interface ReviewRound {
  id: string;
  workspaceId: string;
  sessionId: string;
  executionId: string | null;
  settings: {
    topics: string[];
    difficulties: Difficulty[];
    mode: ReviewMode;
    question_count: number;
    allow_follow_up: boolean;
    seed: number;
    answer_model_id: string;
    reasoning_effort: "none" | "low" | "medium" | "high";
  };
  status: "waiting_for_input" | "running" | "report_pending" | "completed" | "failed" | "cancelled";
  executionStatus: string | null;
  currentIndex: number;
  questionCount: number;
  currentQuestion: {
    id: string;
    title: string;
    questionText: string;
    topics: string[];
    difficulty: Difficulty;
  } | null;
  currentInput: ReviewInput | null;
  attempts: ReviewAttempt[];
  messages: ReviewTimelineMessage[];
  reports: { id: string; reportKind: "session_report" | "mastery_report"; title: string; status: string; version: number; publication: { state: string; target_path: string; error_code: string | null } | null }[];
  usage: { inputTokens: number; outputTokens: number; totalTokens: number; callCount: number; estimatedCount: number };
  contextUsage?: { currentTokens: number; thresholdTokens: number; estimated: boolean };
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
  archivedAt?: string | null;
}

export interface CreateReviewRoundRequest {
  workspaceId: string;
  selectedTopics: string[];
  difficulties: Difficulty[];
  mode: ReviewMode;
  questionCount: number;
  allowFollowUp: boolean;
  seed?: number;
  answerModelId: string;
  reasoningEffort: "none" | "low" | "medium" | "high";
}
