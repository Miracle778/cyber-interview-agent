from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


TargetLifecycle: TypeAlias = Literal["active", "archived", "recycled"]
DocumentSourceKind: TypeAlias = Literal["jd_text", "direction_reference"]
RequirementType: TypeAlias = Literal[
    "responsibility", "skill", "experience", "project"
]
RequirementPriority: TypeAlias = Literal["must_have", "nice_to_have"]
RequirementConfirmation: TypeAlias = Literal[
    "pending", "confirmed", "rejected", "superseded"
]
PreparationStatus: TypeAlias = Literal[
    "reliable_evidence",
    "needs_deep_dive",
    "profile_incomplete",
    "no_experience",
]
AnalysisStatus: TypeAlias = Literal[
    "queued",
    "running",
    "pausing",
    "paused",
    "interrupted",
    "review_pending",
    "completed",
    "failed",
    "terminated",
]
DeepDiveStage: TypeAlias = Literal[
    "background",
    "role",
    "solution",
    "difficulty",
    "outcome",
    "tradeoff",
    "target_follow_up",
    "finished",
]


@dataclass(frozen=True, slots=True)
class JobTargetRecord:
    id: str
    workspace_id: str
    company_name: str | None
    role_name: str
    seniority: str
    source_url: str | None
    lifecycle_status: TargetLifecycle
    current_document_version_id: str | None
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class JobDocumentVersionRecord:
    id: str
    job_target_id: str
    ordinal: int
    source_kind: DocumentSourceKind
    body: str
    content_hash: str
    is_current: bool
    created_at: str


@dataclass(frozen=True, slots=True)
class JobRequirementRecord:
    id: str
    job_target_id: str
    document_version_id: str
    stable_key: str
    requirement_type: RequirementType
    priority: RequirementPriority
    text: str
    source_quote: str
    source_start: int | None
    source_end: int | None
    inferred: bool
    confirmation_status: RequirementConfirmation
    preparation_status: PreparationStatus
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class JobAnalysisRunRecord:
    id: str
    job_target_id: str
    document_version_id: str
    execution_id: str | None
    profile_version: int
    input_digest: str
    status: AnalysisStatus
    stage: str
    control_intent: str | None
    cumulative_elapsed_ms: int
    latest_progress_at: str | None
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ProjectDeepDiveRecord:
    id: str
    job_target_id: str
    project_claim_id: str
    session_id: str
    current_stage: DeepDiveStage
    status: str
    current_question_id: str | None
    completed_stage_ids: tuple[str, ...]
    follow_up_ids: tuple[str, ...]
    waiting_for_input: bool
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class RequirementDecisionReceipt:
    confirmed_ids: tuple[str, ...]
    rejected_ids: tuple[str, ...]
    pending_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectPriorityReceipt:
    job_target_id: str
    core_project_id: str
    supplementary_project_ids: tuple[str, ...]
    version: int


@dataclass(frozen=True, slots=True)
class TargetDeletionImpact:
    target_id: str
    documents: int
    requirements: int
    analyses: int
    deep_dives: int
    question_candidates: int
    preserved_profile: bool = True
    preserved_published_questions: bool = True
