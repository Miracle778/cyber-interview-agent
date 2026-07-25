export type MaterialLifecycleStatus = "active" | "archived";
export type MaterialProcessingStatus = "uploaded" | "parsing" | "parsed" | "extracting" | "ready" | "parse_failed" | "extraction_failed";
export type ProcessingStageStatus = "pending" | "active" | "completed" | "failed";

export interface MaterialProcessingStage {
  key: string;
  label: string;
  status: ProcessingStageStatus | string;
}

export interface ProfileMaterial {
  id: string;
  workspaceId: string;
  type: string;
  title: string;
  primaryRole: string;
  currentVersionId: string | null;
  lifecycleStatus: MaterialLifecycleStatus | string;
  version: number;
  versionCount: number;
  latestProcessingStatus: MaterialProcessingStatus | string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ProfileMaterialVersion {
  id: string;
  materialId: string;
  versionNumber: number;
  sourceType: string;
  fileName: string;
  mimeType: string;
  processingStatus: MaterialProcessingStatus | string;
  stages: MaterialProcessingStage[];
  canRetry: boolean;
  createdAt: string;
}

export interface ProfileEvidence {
  id: string;
  materialVersionId: string;
  locator: Record<string, unknown>;
  startOffset: number;
  endOffset: number;
  excerpt: string;
  sensitivity: string;
  createdAt: string;
}

export interface ProfileExecutionSummary {
  id: string;
  status: string;
  errorCode: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  retryable: boolean;
}

export interface ProfileMaterialVersionDetail extends ProfileMaterialVersion {
  material: ProfileMaterial;
  evidencePage: { items: ProfileEvidence[]; offset: number; limit: number; total: number; hasMore: boolean };
  proposalCounts: { total: number; pending: number; accepted: number; rejected: number; superseded: number };
  execution: ProfileExecutionSummary | null;
}

export interface ProfileDocumentOutlineItem {
  evidenceId: string;
  title: string;
  locator: Record<string, unknown>;
  startOffset: number;
  endOffset: number;
}

export interface ProfileMaterialDocument {
  versionId: string;
  fileName: string;
  mimeType: string;
  versionNumber: number;
  originalText: string;
  redactedText: string;
  outline: ProfileDocumentOutlineItem[];
}

export interface AcceptedMaterialUpload {
  materialId: string;
  versionId: string;
  executionId: string;
  processingStatus: string;
}

export interface AcceptedMaterialRetry {
  versionId: string;
  executionId: string;
  processingStatus: string;
}

export interface ProfileClaimVersion {
  id: string;
  claimId: string;
  version: number;
  value: Record<string, unknown>;
  status: string;
  supportStatus: string;
  evidenceIds: string[];
  source: string;
  expectedPreviousVersion: number | null;
  createdAt: string;
  confirmedAt: string | null;
}

export interface ProfileClaimProposal {
  id: string;
  proposalType: string;
  targetClaimId: string | null;
  baseClaimVersionId: string | null;
  proposedValue: Record<string, unknown>;
  reason: string;
  status: string;
  sourceKind?: string;
  sourceRef?: Record<string, unknown>;
  evidence: ProfileEvidence[];
  decidedAt: string | null;
  createdAt: string;
}

export interface ProfileClaimReview {
  id: string;
  claimType: string;
  version: number;
  currentVersion: ProfileClaimVersion;
  versions: ProfileClaimVersion[];
  proposals: ProfileClaimProposal[];
  conflicts: { id: string; proposalId: string; conflictingClaimVersionId: string; createdAt: string }[];
  evidence: ProfileEvidence[];
  createdAt: string;
  updatedAt: string;
}

export interface ProfileClaimWorkspace {
  workspaceId: string;
  profileVersion: string | null;
  claims: ProfileClaimReview[];
  proposals: ProfileClaimProposal[];
}

export type ClaimDecision = "accepted" | "rejected";

export interface ClaimDecisionResult {
  proposalId: string;
  status: string;
  claimId: string | null;
  claimVersionId: string | null;
  supportStatus: string | null;
}

export interface BatchClaimDecisionResult {
  items: { proposalId: string; status: "completed" | "conflict" | "failed_terminal"; result: ClaimDecisionResult | null; errorCode: string | null; retryable: boolean }[];
}

export interface DuplicateProposalPreview {
  workspaceId: string;
  groupCount: number;
  proposalCount: number;
  groups: {
    category: string;
    label: string;
    canonicalProposalId: string;
    proposalIds: string[];
    mergedValue: Record<string, unknown>;
    evidenceCount: number;
  }[];
}

export interface DuplicateProposalConsolidationResult {
  workspaceId: string;
  canonicalProposalIds: string[];
  supersededProposalIds: string[];
}

export interface MaterialDeletionPreview {
  deletionPlanId: string;
  materialId: string;
  materialVersion: number;
  expiresAt: string;
  affectedEvidenceCount: number;
  affectedClaims: { claimId: string; claimType: string; claimVersion: number; claimVersionId: string; supportStatus: string; affectedEvidenceIds: string[]; remainingEvidenceIds: string[]; selectionIds: string[] }[];
  unsupportedClaimIds: string[];
  publicationSelectionIds: string[];
  activePublicationIds: string[];
}

export interface PermanentMaterialDeletionResult {
  planId: string;
  status: string;
  items: { kind: string; targetId: string; status: string; action: string; errorCode: string | null }[];
}

export interface ProfileAssessment {
  id: string;
  workspaceId: string;
  baseProfileVersion: string;
  currentProfileVersion: string | null;
  result: { summary?: string; strengths?: string[]; gaps?: string[]; risks?: string[]; recommendations?: { title?: string; detail?: string; evidenceIds?: string[] }[] };
  proposalIds: string[];
  createdByExecutionId: string | null;
  createdAt: string;
}

export interface ProfileActionPlanItem {
  itemId: string;
  ordinal: number;
  operation: string;
  target: Record<string, unknown>;
  expectedVersion: number | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown>;
  evidenceIds: string[];
  status: string;
  receiptId: string | null;
  errorCode: string | null;
}

export interface ProfileActionPlan {
  id: string;
  workspaceId: string;
  sessionId: string | null;
  executionId: string | null;
  requestSummary: string;
  baseProfileVersion: string;
  currentProfileVersion: string | null;
  selectionSnapshot: Record<string, unknown>;
  items: ProfileActionPlanItem[];
  status: string;
  version: number;
  stale: boolean;
  canConfirm: boolean;
  canCancel: boolean;
  retryable: boolean;
  createdAt: string;
}

export type ProfileCardCategory =
  | "summary"
  | "direction"
  | "highlight"
  | "experience"
  | "project"
  | "skill"
  | "education"
  | "certification"
  | "achievement"
  | "link";

export interface ProfileSourceSummary {
  sourceKind: string;
  label: string;
  status: string;
}

export interface ProfileCardReference {
  claimId: string;
  claimType: string;
  title: string;
}

export interface UnifiedProfileCard {
  claimId: string;
  claimVersionId: string;
  category: ProfileCardCategory;
  version: number;
  title: string;
  subtitle: string | null;
  value: Record<string, unknown>;
  sources: ProfileSourceSummary[];
  linkedTo: ProfileCardReference[];
  usedIn: ProfileCardReference[];
}

export interface ActionableProfileGap {
  claimId: string;
  category: ProfileCardCategory;
  field: string;
  message: string;
}

export interface UnifiedProfile {
  workspaceId: string;
  profileVersion: string | null;
  summary: UnifiedProfileCard | null;
  directions: UnifiedProfileCard[];
  primaryDirectionClaimId: string | null;
  presentationVersion: number;
  highlights: UnifiedProfileCard[];
  experiences: UnifiedProfileCard[];
  projects: UnifiedProfileCard[];
  skills: UnifiedProfileCard[];
  education: UnifiedProfileCard[];
  certifications: UnifiedProfileCard[];
  achievements: UnifiedProfileCard[];
  links: UnifiedProfileCard[];
  actionableGaps: ActionableProfileGap[];
  pendingCount: number;
  isUsable: boolean;
}

export interface ProfileCardCommand {
  workspaceId: string;
  category: ProfileCardCategory;
  value: Record<string, unknown>;
  expectedVersion: number;
  relations: { relationType: "belongs_to" | "used_in" | "supported_by"; targetClaimId: string }[];
}

export interface ProfileCardWriteResult {
  claimId: string;
  claimVersionId: string;
  category: ProfileCardCategory;
  version: number;
  status: string;
}

export interface ProfilePresentation {
  workspaceId: string;
  summaryClaimId: string | null;
  primaryDirectionClaimId: string | null;
  featuredClaimIds: string[];
  version: number;
  updatedAt: string;
}
