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
