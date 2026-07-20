from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

MaterialType: TypeAlias = Literal[
    "resume", "github", "blog", "research", "project_document"
]
MaterialLifecycle: TypeAlias = Literal["active", "archived"]
VersionSourceType: TypeAlias = Literal["upload", "derived_draft"]
ProcessingStatus: TypeAlias = Literal[
    "uploaded",
    "parsing",
    "parsed",
    "extracting",
    "ready",
    "parse_failed",
    "extraction_failed",
]
EvidenceSensitivity: TypeAlias = Literal["normal", "sensitive"]
ClaimType: TypeAlias = Literal["skill", "project", "experience", "education", "link"]
ClaimVersionStatus: TypeAlias = Literal[
    "proposed", "confirmed", "rejected", "superseded"
]
ClaimSupportStatus: TypeAlias = Literal["supported", "conflicted", "unsupported"]
ProposalType: TypeAlias = Literal["create", "update", "reject"]
ProposalStatus: TypeAlias = Literal["pending", "accepted", "rejected", "superseded"]
ProposalDecision: TypeAlias = Literal["accepted", "rejected"]
ActionPlanStatus: TypeAlias = Literal[
    "proposed",
    "validated",
    "awaiting_confirmation",
    "executing",
    "completed",
    "partially_completed",
    "failed",
    "cancelled",
    "expired",
]
ActionPlanItemStatus: TypeAlias = Literal["pending", "completed", "failed", "skipped"]
PublicationSelectionStatus: TypeAlias = Literal["draft", "submitted", "superseded"]
PublicationState: TypeAlias = Literal["pending", "published", "revoked", "failed"]


# --- Records (immutable domain truth) ---


@dataclass(frozen=True, slots=True)
class ProfileMaterialRecord:
    id: str
    workspace_id: str
    type: MaterialType
    title: str
    primary_role: str
    current_version_id: str | None
    lifecycle_status: MaterialLifecycle
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ProfileMaterialVersionRecord:
    id: str
    material_id: str
    version_number: int
    source_type: VersionSourceType
    file_name: str
    mime_type: str
    content_sha256: str
    storage_ref: str
    text_ref: str
    processing_status: ProcessingStatus
    derived_from_version_id: str | None
    created_by: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    id: str
    material_version_id: str
    section: str
    start_offset: int
    end_offset: int
    sanitized_text: str
    content_sha256: str
    sensitivity: EvidenceSensitivity
    tombstoned_at: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class ProfileClaimRecord:
    id: str
    workspace_id: str
    claim_type: ClaimType
    current_confirmed_version_id: str | None
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ProfileClaimVersionRecord:
    id: str
    claim_id: str
    version: int
    value: dict[str, object]
    status: ClaimVersionStatus
    support_status: ClaimSupportStatus
    evidence_ids: tuple[str, ...]
    source: str
    expected_previous_version: int | None
    created_at: str
    confirmed_at: str | None


@dataclass(frozen=True, slots=True)
class ClaimProposalRecord:
    id: str
    workspace_id: str
    proposal_type: ProposalType
    target_claim_id: str | None
    base_claim_version_id: str | None
    proposed_value: dict[str, object]
    reason: str
    evidence_ids: tuple[str, ...]
    status: ProposalStatus
    created_by_execution_id: str | None
    decided_at: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class ClaimConflictRecord:
    id: str
    workspace_id: str
    claim_id: str
    proposal_id: str
    conflicting_claim_version_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ProfileAssessmentRecord:
    id: str
    workspace_id: str
    base_profile_version: str
    result: dict[str, object]
    created_by_execution_id: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class ActionPlanItemRecord:
    id: str
    plan_id: str
    item_id: str
    ordinal: int
    operation: str
    target: dict[str, object]
    expected_version: int | None
    before: dict[str, object] | None
    after: dict[str, object]
    evidence_ids: tuple[str, ...]
    status: ActionPlanItemStatus
    receipt_id: str | None
    error_code: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class ProfileActionPlanRecord:
    id: str
    workspace_id: str
    session_id: str | None
    execution_id: str | None
    request_summary: str
    base_profile_version: str
    selection_snapshot: dict[str, object]
    items: tuple[ActionPlanItemRecord, ...]
    status: ActionPlanStatus
    version: int
    expires_at: str | None
    created_at: str
    confirmed_at: str | None
    completed_at: str | None


@dataclass(frozen=True, slots=True)
class PublicationSelectionRecord:
    id: str
    workspace_id: str
    profile_version: str
    claim_version_ids: tuple[str, ...]
    excluded_sensitive_fields: tuple[str, ...]
    status: PublicationSelectionStatus
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ConfirmedClaimEntry:
    claim_id: str
    claim_type: ClaimType
    claim_version_id: str
    version_number: int
    value: dict[str, object]
    support_status: ClaimSupportStatus
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConfirmedProfileSnapshot:
    workspace_id: str
    profile_version: str | None
    claims: tuple[ConfirmedClaimEntry, ...]
    materials: tuple[ProfileMaterialRecord, ...]


# --- Commands and specs ---


@dataclass(frozen=True, slots=True)
class CreateMaterialCommand:
    workspace_id: str
    type: MaterialType
    title: str
    primary_role: str


@dataclass(frozen=True, slots=True)
class CreateClaimProposalSpec:
    proposal_type: ProposalType
    proposed_value: dict[str, object]
    reason: str
    evidence_ids: tuple[str, ...] = ()
    target_claim_id: str | None = None
    base_claim_version_id: str | None = None
    source: str = "extraction"


@dataclass(frozen=True, slots=True)
class DecideProposalCommand:
    proposal_id: str
    decision: ProposalDecision
    expected_status: ProposalStatus = "pending"
    edited_value: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class SaveAssessmentCommand:
    workspace_id: str
    base_profile_version: str
    result: dict[str, object]
    created_by_execution_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActionPlanItemSpec:
    item_id: str
    ordinal: int
    operation: str
    target: dict[str, object]
    after: dict[str, object]
    expected_version: int | None = None
    before: dict[str, object] | None = None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CreateActionPlanCommand:
    workspace_id: str
    session_id: str | None
    execution_id: str | None
    request_summary: str
    base_profile_version: str
    selection_snapshot: dict[str, object] = field(default_factory=dict)
    items: tuple[ActionPlanItemSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class CreatePublicationSelectionCommand:
    workspace_id: str
    profile_version: str
    claim_version_ids: tuple[str, ...]
    excluded_sensitive_fields: tuple[str, ...] = ()


# --- Results ---


@dataclass(frozen=True, slots=True)
class ClaimDecisionResult:
    proposal_id: str
    status: ProposalStatus
    claim_id: str | None = None
    claim_version_id: str | None = None
    support_status: ClaimSupportStatus | None = None


@dataclass(frozen=True, slots=True)
class BatchClaimDecisionResult:
    completed: tuple[ClaimDecisionResult, ...]
    conflicts: tuple[str, ...]
    failed: tuple[str, ...]
