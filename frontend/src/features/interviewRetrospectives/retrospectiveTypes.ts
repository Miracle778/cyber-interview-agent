export type RetrospectiveOutcome =
  | "pending"
  | "passed"
  | "failed"
  | "cancelled"
  | "unrecorded";

export type RetrospectiveLifecycle = "active" | "archived" | "recycled";
export type SourceKind = "transcript" | "recollection";
export type SpeakerRole = "candidate" | "interviewer" | "unknown";

export interface InterviewRetrospective {
  id: string;
  workspaceId: string;
  jobTargetId: string;
  title: string;
  roundLabel: string;
  interviewDate: string | null;
  outcome: RetrospectiveOutcome;
  note: string;
  lifecycleStatus: RetrospectiveLifecycle;
  activeSourceVersionId: string | null;
  activeSourceAvailable: boolean;
  activeCleanupVersionId: string | null;
  activeAnalysisRunId: string | null;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface SourceVersion {
  id: string;
  retrospectiveId: string;
  ordinal: number;
  sourceKind: SourceKind;
  fileName: string | null;
  contentSha256: string;
  bodyAvailable: boolean;
  body?: string | null;
  clearedAt: string | null;
  createdAt: string;
}

export interface RetrospectiveDeletionImpact {
  sourceVersions: number;
  cleanupVersions: number;
  analysisRuns: number;
  candidates: number;
  actionItems: number;
  preservesReviewQuestions: boolean;
  preservesProfileAndProjects: boolean;
  preservesKnowledge: boolean;
}

export interface CleanupSegment {
  id: string;
  ordinal: number;
  speakerRole: SpeakerRole;
  rawSpeakerLabel: string | null;
  displayName: string;
  body: string;
  sourceStart: number;
  sourceEnd: number;
  confidence: number;
  uncertaintyReason: string | null;
  ignored: boolean;
  version: number;
}

export interface CleanupVersion {
  id: string;
  retrospectiveId: string;
  sourceVersionId: string;
  ordinal: number;
  executionId: string | null;
  status: string;
  stage: string;
  controlIntent: string | null;
  confirmedAt: string | null;
  version: number;
  createdAt: string;
  updatedAt: string;
  segments: CleanupSegment[];
}

export interface CleanupReceipt {
  cleanupVersionId: string;
  executionId: string;
}

export interface SegmentEdit {
  speakerRole: SpeakerRole;
  rawSpeakerLabel: string | null;
  displayName: string;
  body: string;
  sourceStart: number;
  sourceEnd: number;
  confidence: number;
  uncertaintyReason: string | null;
  ignored: boolean;
}

export interface AnalysisReceipt {
  analysisRunId: string;
  executionId: string;
}

export interface AnalysisRun {
  id: string;
  retrospectiveId: string;
  cleanupVersionId: string;
  executionId: string | null;
  retryOfAnalysisRunId: string | null;
  status: string;
  stage: string;
  controlIntent: string | null;
  completedItems: number;
  totalItems: number;
  currentWorkKey: string | null;
  cumulativeElapsedMs: number;
  latestProgressAt: string | null;
  summary: Record<string, unknown> | null;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface InterviewQuestion {
  id: string;
  retrospectiveId: string;
  cleanupVersionId: string;
  ordinal: number;
  questionKind: string;
  origin: "original" | "inferred";
  questionText: string;
  questionSegmentIds: string[];
  answerSegmentIds: string[];
  inferenceBasis: string;
  confidence: number;
  decisionStatus: "pending" | "confirmed" | "rejected" | "superseded";
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface AnalysisPoint {
  summary: string;
  evidenceSegmentIds: string[];
}

export interface AnalysisGap {
  kind: string;
  summary: string;
  evidenceSegmentIds: string[];
}

export interface QuestionAnalysis {
  id: string;
  analysisRunId: string;
  questionUnitId: string;
  verdict: string;
  strengths: AnalysisPoint[];
  improvements: AnalysisPoint[];
  omissions: AnalysisPoint[];
  gaps: AnalysisGap[];
  evidenceLevel: string;
  confidence: number;
  improvementOutline: string[];
  suggestedAnswer: string;
  sourceExcerpt: string;
  sourceAvailable: boolean;
  resultStatus: string;
  version: number;
}

export interface AnalysisWorkItem {
  id: string;
  questionUnitId: string | null;
  workKey: string;
  status: string;
  attemptCount: number;
  lastErrorCode: string | null;
  updatedAt: string;
}

export interface AnalysisReport {
  analysisRun: AnalysisRun;
  questions: InterviewQuestion[];
  analyses: QuestionAnalysis[];
  items: AnalysisWorkItem[];
  summary: Record<string, unknown>;
}

export type RetrospectiveCandidateKind =
  | "review_question"
  | "profile_claim"
  | "project_narrative"
  | "summary";

export type RetrospectiveCandidateDecision =
  | "link_existing"
  | "supplement_existing"
  | "create_new"
  | "propose_update"
  | "propose_new"
  | "reject"
  | "include"
  | "exclude";

export interface CandidateMatch {
  resourceId: string;
  resourceVersion?: number;
  score: number;
  title?: string;
}

export interface RetrospectiveCandidate {
  id: string;
  retrospectiveId: string;
  analysisRunId: string;
  questionUnitId: string | null;
  candidateKind: RetrospectiveCandidateKind;
  fingerprint: string;
  payload: Record<string, unknown>;
  matches: CandidateMatch[];
  status: "pending" | "confirmed" | "rejected" | "blocked" | "failed" | "superseded";
  targetResourceType: string | null;
  targetResourceId: string | null;
  lastErrorCode: string | null;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface CandidateDecisionInput {
  candidateId: string;
  action: RetrospectiveCandidateDecision;
  targetResourceId?: string | null;
  actionPayload?: Record<string, unknown>;
  expectedVersion: number;
}

export interface CandidateBatchResult {
  candidateId: string;
  status: "completed" | "failed";
  candidate: RetrospectiveCandidate | null;
  errorCode: string | null;
}

export interface RetrospectiveActionItem {
  id: string;
  retrospectiveId: string;
  analysisRunId: string;
  questionUnitId: string | null;
  gapId: string | null;
  actionKind: "material" | "expression" | "knowledge" | "experience";
  title: string;
  detail: string;
  status: "pending" | "completed" | "dismissed";
  version: number;
  completedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export type PublicationSection =
  | "basic_info"
  | "confirmed_questions"
  | "selected_conclusions"
  | "confirmed_experiences"
  | "action_items"
  | "stable_links";

export interface RetrospectivePublicationDraft {
  id: string;
  documentType: string;
  title: string;
  markdown: string;
  status: string;
  version: number;
}

export interface RetrospectiveConversationMessage {
  id: string;
  executionId: string | null;
  role: string;
  content: string;
  messageKind: string;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface RetrospectiveCorrectionProposal {
  id: string;
  retrospectiveId: string;
  chatMessageId: string | null;
  proposalType: "question_text_correction" | "question_segment_rebind" | "speaker_correction" | "analysis_reconsideration";
  targetQuestionId: string | null;
  sourceCleanupVersionId: string;
  sourceAnalysisRunId: string | null;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  rationale: string;
  expectedVersion: number;
  status: "pending" | "confirmed" | "rejected";
  resultingCleanupVersionId: string | null;
  resultingAnalysisRunId: string | null;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface RetrospectiveConversation {
  sessionId: string;
  messages: RetrospectiveConversationMessage[];
  proposals: RetrospectiveCorrectionProposal[];
  latestExecution: null | {
    id: string;
    status: string;
    errorCode: string | null;
    createdAt: string;
    finishedAt: string | null;
  };
}
