export type RequirementPreparationStatus =
  | "reliable_evidence"
  | "needs_deep_dive"
  | "profile_incomplete"
  | "no_experience";

export type TargetDerivedStatus =
  | "requirements_pending"
  | "project_selection_pending"
  | "deep_dive_in_progress"
  | "high_risk_open"
  | "core_preparation_complete";

export interface JobTarget {
  id: string;
  workspaceId: string;
  companyName: string | null;
  roleName: string;
  seniority: string;
  sourceUrl: string | null;
  lifecycleStatus: "active" | "archived" | "recycled";
  currentDocumentVersionId: string | null;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface JobDocumentVersion {
  id: string;
  jobTargetId: string;
  ordinal: number;
  sourceKind: "jd_text" | "direction_reference";
  body: string;
  contentHash: string;
  isCurrent: boolean;
  createdAt: string;
}

export interface JobRequirement {
  id: string;
  jobTargetId: string;
  documentVersionId: string;
  stableKey: string;
  requirementType: "responsibility" | "skill" | "experience" | "project";
  priority: "must_have" | "nice_to_have";
  text: string;
  sourceQuote: string;
  inferred: boolean;
  confirmationStatus: "pending" | "confirmed" | "rejected" | "superseded";
  preparationStatus: RequirementPreparationStatus;
  version: number;
}

export interface JobAnalysis {
  id: string;
  jobTargetId: string;
  status: string;
  stage: string;
  version: number;
  executionId?: string | null;
  progress: { completed: number; total: number; activeWorkers: number };
  timing: { currentElapsedMs: number; cumulativeElapsedMs: number };
  latestProgressAt: string | null;
  savedOutputs: { requirements: number; projectMappings: number };
  controls: { canPause: boolean; canResume: boolean; canTerminate: boolean };
}

export interface DeepDiveMessage {
  id: string;
  executionId: string | null;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  resolutionStatus: "active" | "unresolved" | "replaced" | "abandoned";
}

export interface DeepDiveExecution {
  id: string;
  inputMessageId: string | null;
  retryOfExecutionId: string | null;
  status: string;
  errorMessage: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  configuration?: {
    providerModelId: string | null;
    reasoningEffort: "none" | "low" | "medium" | "high";
  };
}

export interface ProjectQuestionCandidate {
  id: string;
  dimension: string;
  status: "review_pending" | "confirmed" | "ignored" | "duplicate";
  question: { title: string; question: string };
}

export interface DeepDiveResource {
  id: string;
  jobTargetId: string;
  projectClaimId: string;
  projectTitle?: string;
  sessionId: string;
  status: string;
  currentStage: string;
  completedStageIds: string[];
  waitingForInput: boolean;
  version: number;
  messages: DeepDiveMessage[];
  executions: DeepDiveExecution[];
  artifacts: { id: string; kind: string; payload: Record<string, unknown>; status: string }[];
  gaps: { id: string; gap_kind: string; summary: string; status: string }[];
  questionCandidates: ProjectQuestionCandidate[];
  runtime: {
    modelRole: string;
    providerModelId?: string | null;
    reasoningEffort?: "none" | "low" | "medium" | "high";
    calls: number;
    inputTokens: number;
    outputTokens: number;
    contextTokens: number;
    contextThreshold: number;
    estimated: boolean;
    compacted: boolean;
  };
}

export interface TargetReadiness {
  jobTargetId: string;
  status: TargetDerivedStatus;
  requirements: number;
}
