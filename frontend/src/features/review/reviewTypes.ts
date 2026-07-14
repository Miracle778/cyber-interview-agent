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
  question: CandidateQuestion;
  sourceRefs: string[];
  correctionNote: string;
  duplicateOfQuestionId: string | null;
  duplicateQuestion: CandidateQuestion | null;
  status: "draft" | "review_pending" | "rejected" | "published";
  draft: CandidateDraft | null;
  createdAt: string;
  updatedAt: string;
}

export interface QuestionBatch {
  id: string;
  workspaceId: string;
  sessionId: string;
  runId: string | null;
  sourceRefs: string[];
  rewriteOfBatchId: string | null;
  status: "generating" | "review_pending" | "completed" | "failed";
  candidateCount: number;
  pendingCount: number;
  candidates: QuestionCandidate[];
  createdAt: string;
  updatedAt: string;
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
  createdAt: string;
  updatedAt: string;
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
  reports: { id: string; reportKind: "session_report" | "mastery_report"; title: string; status: string; version: number; publication: { state: string; target_path: string; error_code: string | null } | null }[];
  usage: { inputTokens: number; outputTokens: number; totalTokens: number; callCount: number; estimatedCount: number };
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
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
