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
