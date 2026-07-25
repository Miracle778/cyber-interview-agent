from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schemas.agent import AgentModel


class MaterialActionCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)


class SetPrimaryMaterialCommand(MaterialActionCommand):
    version_id: str


class RetryMaterialVersionCommand(AgentModel):
    workspace_id: str


class AcceptedMaterialUploadResource(AgentModel):
    material_id: str
    version_id: str
    execution_id: str
    processing_status: str


class MaterialProcessingStageResource(AgentModel):
    key: str
    label: str
    status: str


class ProfileExecutionSummaryResource(AgentModel):
    id: str
    status: str
    error_code: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    retryable: bool


class ProfileMaterialResource(AgentModel):
    id: str
    workspace_id: str
    type: str
    title: str
    primary_role: str
    current_version_id: str | None
    lifecycle_status: str
    version: int
    version_count: int
    latest_processing_status: str | None
    created_at: str
    updated_at: str


class ProfileMaterialVersionResource(AgentModel):
    id: str
    material_id: str
    version_number: int
    source_type: str
    file_name: str
    mime_type: str
    processing_status: str
    stages: list[MaterialProcessingStageResource]
    can_retry: bool
    created_at: str


class ProfileEvidenceResource(AgentModel):
    id: str
    material_version_id: str
    locator: dict[str, Any]
    start_offset: int
    end_offset: int
    excerpt: str
    sensitivity: str
    created_at: str


class EvidencePageResource(AgentModel):
    items: list[ProfileEvidenceResource]
    offset: int
    limit: int
    total: int
    has_more: bool


class ProposalCountsResource(AgentModel):
    total: int
    pending: int
    accepted: int
    rejected: int
    superseded: int


class ProfileMaterialVersionDetailResource(ProfileMaterialVersionResource):
    material: ProfileMaterialResource
    evidence_page: EvidencePageResource
    proposal_counts: ProposalCountsResource
    execution: ProfileExecutionSummaryResource | None


class ProfileDocumentOutlineItemResource(AgentModel):
    evidence_id: str
    title: str
    locator: dict[str, Any]
    start_offset: int
    end_offset: int


class ProfileMaterialDocumentResource(AgentModel):
    version_id: str
    file_name: str
    mime_type: str
    version_number: int
    original_text: str
    redacted_text: str
    outline: list[ProfileDocumentOutlineItemResource]


class AcceptedMaterialRetryResource(AgentModel):
    version_id: str
    execution_id: str
    processing_status: str


class ClaimVersionResource(AgentModel):
    id: str
    claim_id: str
    version: int
    value: dict[str, Any]
    status: str
    support_status: str
    evidence_ids: list[str]
    source: str
    expected_previous_version: int | None
    created_at: str
    confirmed_at: str | None


class ClaimProposalResource(AgentModel):
    id: str
    proposal_type: str
    target_claim_id: str | None
    base_claim_version_id: str | None
    proposed_value: dict[str, Any]
    reason: str
    status: str
    source_kind: str
    source_ref: dict[str, Any]
    evidence: list[ProfileEvidenceResource]
    decided_at: str | None
    created_at: str


class ClaimConflictResource(AgentModel):
    id: str
    proposal_id: str
    conflicting_claim_version_id: str
    created_at: str


class ClaimReviewResource(AgentModel):
    id: str
    claim_type: str
    version: int
    current_version: ClaimVersionResource
    versions: list[ClaimVersionResource]
    proposals: list[ClaimProposalResource]
    conflicts: list[ClaimConflictResource]
    evidence: list[ProfileEvidenceResource]
    created_at: str
    updated_at: str


class ClaimReviewWorkspaceResource(AgentModel):
    workspace_id: str
    profile_version: str | None
    claims: list[ClaimReviewResource]
    proposals: list[ClaimProposalResource]


class ConfirmedProfileContextCommand(AgentModel):
    purpose: Literal[
        "job_target_analysis", "project_deep_dive", "interview_training"
    ]
    claim_types: list[
        Literal[
            "skill",
            "project",
            "experience",
            "education",
            "certification",
            "achievement",
            "link",
        ]
    ] = Field(default_factory=list, max_length=7)
    claim_ids: list[str] = Field(default_factory=list, max_length=50)
    sensitive_data_policy: Literal["exclude"] = "exclude"
    limit: int = Field(default=50, ge=1, le=50)


class ConfirmedProfileContextItemResource(AgentModel):
    claim_id: str
    claim_version_id: str
    claim_type: str
    value: dict[str, Any]
    support_status: str
    evidence_ids: list[str]


class ConfirmedProfileContextResource(AgentModel):
    workspace_id: str
    purpose: str
    profile_version: str | None
    items: list[ConfirmedProfileContextItemResource]


ProfileCardCategory = Literal[
    "skill",
    "project",
    "experience",
    "education",
    "certification",
    "achievement",
    "link",
    "summary",
    "direction",
    "highlight",
]


class ProfileRelationCommand(AgentModel):
    relation_type: Literal["belongs_to", "used_in", "supported_by"]
    target_claim_id: str


class ProfileCardCommand(AgentModel):
    workspace_id: str
    category: ProfileCardCategory
    value: dict[str, Any]
    expected_version: int = Field(ge=0)
    relations: list[ProfileRelationCommand] = Field(
        default_factory=list, max_length=100
    )


class ProfileCardDeleteCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)


class ProfileCardRestoreCommand(ProfileCardDeleteCommand):
    source_version_id: str


class ProfilePresentationCommand(AgentModel):
    workspace_id: str
    summary_claim_id: str | None = None
    primary_direction_claim_id: str | None = None
    featured_claim_ids: list[str] = Field(default_factory=list, max_length=5)
    expected_version: int = Field(ge=0)


class ProfileSourceSummaryResource(AgentModel):
    source_kind: str
    label: str
    status: str


class ProfileSourceResource(ProfileSourceSummaryResource):
    id: str
    claim_version_id: str
    source_ref: dict[str, Any]
    created_at: str


class ProfileCardReferenceResource(AgentModel):
    claim_id: str
    claim_type: str
    title: str


class UnifiedProfileCardResource(AgentModel):
    claim_id: str
    claim_version_id: str
    category: str
    version: int
    title: str
    subtitle: str | None
    value: dict[str, Any]
    sources: list[ProfileSourceSummaryResource]
    linked_to: list[ProfileCardReferenceResource]
    used_in: list[ProfileCardReferenceResource]


class ActionableProfileGapResource(AgentModel):
    claim_id: str
    category: str
    field: str
    message: str


class UnifiedProfileResource(AgentModel):
    workspace_id: str
    profile_version: str | None
    summary: UnifiedProfileCardResource | None
    directions: list[UnifiedProfileCardResource]
    primary_direction_claim_id: str | None
    presentation_version: int
    highlights: list[UnifiedProfileCardResource]
    experiences: list[UnifiedProfileCardResource]
    projects: list[UnifiedProfileCardResource]
    skills: list[UnifiedProfileCardResource]
    education: list[UnifiedProfileCardResource]
    certifications: list[UnifiedProfileCardResource]
    achievements: list[UnifiedProfileCardResource]
    links: list[UnifiedProfileCardResource]
    actionable_gaps: list[ActionableProfileGapResource]
    pending_count: int
    is_usable: bool


class ProfileCardWriteResource(AgentModel):
    claim_id: str
    claim_version_id: str
    category: str
    version: int
    status: str


class ProfileCardDeleteResource(AgentModel):
    claim_id: str
    status: Literal["deleted"]


class ProfilePresentationResource(AgentModel):
    workspace_id: str
    summary_claim_id: str | None
    primary_direction_claim_id: str | None
    featured_claim_ids: list[str]
    version: int
    updated_at: str


class ClaimDecisionCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=0)
    edited_value: dict[str, Any] | None = None


class ClaimDecisionResource(AgentModel):
    proposal_id: str
    status: str
    claim_id: str | None
    claim_version_id: str | None
    support_status: str | None


class BatchClaimDecisionItemCommand(AgentModel):
    proposal_id: str
    decision: Literal["accepted", "rejected"]
    expected_version: int = Field(ge=0)
    edited_value: dict[str, Any] | None = None


class BatchClaimDecisionCommand(AgentModel):
    workspace_id: str
    decisions: list[BatchClaimDecisionItemCommand] = Field(min_length=1, max_length=100)


class BatchClaimDecisionItemResource(AgentModel):
    proposal_id: str
    status: Literal["completed", "conflict", "failed_terminal"]
    result: ClaimDecisionResource | None = None
    error_code: str | None = None
    retryable: bool


class BatchClaimDecisionResource(AgentModel):
    items: list[BatchClaimDecisionItemResource]


class DuplicateProposalGroupResource(AgentModel):
    category: str
    label: str
    canonical_proposal_id: str
    proposal_ids: list[str]
    merged_value: dict[str, Any]
    evidence_count: int


class DuplicateProposalPreviewResource(AgentModel):
    workspace_id: str
    group_count: int
    proposal_count: int
    groups: list[DuplicateProposalGroupResource]


class DuplicateProposalGroupCommand(AgentModel):
    proposal_ids: list[str] = Field(min_length=2, max_length=50)


class ConsolidateDuplicateProposalsCommand(AgentModel):
    workspace_id: str
    groups: list[DuplicateProposalGroupCommand] = Field(
        min_length=1, max_length=50
    )


class ConsolidateDuplicateProposalsResource(AgentModel):
    workspace_id: str
    canonical_proposal_ids: list[str]
    superseded_proposal_ids: list[str]


class MaterialDeletionPreviewCommand(MaterialActionCommand):
    pass


class AffectedClaimResource(AgentModel):
    claim_id: str
    claim_type: str
    claim_version: int
    claim_version_id: str
    support_status: str
    affected_evidence_ids: list[str]
    remaining_evidence_ids: list[str]
    selection_ids: list[str]


class MaterialDeletionPreviewResource(AgentModel):
    deletion_plan_id: str
    material_id: str
    material_version: int
    expires_at: str
    affected_evidence_count: int
    affected_claims: list[AffectedClaimResource]
    unsupported_claim_ids: list[str]
    publication_selection_ids: list[str]
    active_publication_ids: list[str]


class MaterialDeletionClaimChoice(AgentModel):
    claim_id: str
    action: Literal["delete", "retain_unsupported", "cancel"]


class PermanentMaterialDeletionCommand(MaterialActionCommand):
    deletion_plan_id: str
    claim_choices: list[MaterialDeletionClaimChoice]
    active_publication_action: Literal["revoke", "cancel", "not_applicable"]


class DeletionItemReceiptResource(AgentModel):
    kind: str
    target_id: str
    status: str
    action: str
    error_code: str | None = None


class PermanentMaterialDeletionResource(AgentModel):
    plan_id: str
    status: str
    items: list[DeletionItemReceiptResource]


class CreateProfileSessionCommand(AgentModel):
    title: str | None = Field(default=None, max_length=200)


class ProfileAssessmentResource(AgentModel):
    id: str
    workspace_id: str
    base_profile_version: str
    current_profile_version: str | None
    result: dict[str, Any]
    proposal_ids: list[str]
    created_by_execution_id: str | None
    created_at: str


class ProfileActionPlanCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)


class ProfileActionPlanRetryCommand(AgentModel):
    workspace_id: str


class ProfileActionPlanItemResource(AgentModel):
    item_id: str
    ordinal: int
    operation: str
    target: dict[str, Any]
    expected_version: int | None
    before: dict[str, Any] | None
    after: dict[str, Any]
    evidence_ids: list[str]
    status: str
    receipt_id: str | None
    error_code: str | None


class ProfileActionPlanResource(AgentModel):
    id: str
    workspace_id: str
    session_id: str | None
    execution_id: str | None
    request_summary: str
    base_profile_version: str
    current_profile_version: str | None
    selection_snapshot: dict[str, Any]
    items: list[ProfileActionPlanItemResource]
    status: str
    version: int
    stale: bool
    can_confirm: bool
    can_cancel: bool
    retryable: bool
    expires_at: str | None
    created_at: str
    confirmed_at: str | None
    completed_at: str | None
