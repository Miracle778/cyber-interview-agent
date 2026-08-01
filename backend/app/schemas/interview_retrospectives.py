from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.agent import AgentModel


InterviewOutcome = Literal["pending", "passed", "failed", "cancelled", "unrecorded"]


class CreateRetrospectiveCommand(AgentModel):
    workspace_id: str
    job_target_id: str
    title: str = Field(min_length=1, max_length=240)
    round_label: str = Field(min_length=1, max_length=120)
    interview_date: str | None = None
    outcome: InterviewOutcome = "unrecorded"
    note: str = Field(default="", max_length=10_000)


class UpdateRetrospectiveCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    round_label: str | None = Field(default=None, min_length=1, max_length=120)
    interview_date: str | None = None
    outcome: InterviewOutcome | None = None
    note: str | None = Field(default=None, max_length=10_000)


class RetrospectiveResource(AgentModel):
    id: str
    workspace_id: str
    job_target_id: str
    title: str
    round_label: str
    interview_date: str | None
    outcome: InterviewOutcome
    note: str
    lifecycle_status: str
    active_source_version_id: str | None
    active_cleanup_version_id: str | None
    active_analysis_run_id: str | None
    version: int
    created_at: str
    updated_at: str


class AddSourceVersionCommand(AgentModel):
    workspace_id: str
    source_kind: Literal["transcript", "recollection"]
    body: str = Field(min_length=1, max_length=500_000)
    file_name: str | None = Field(default=None, max_length=255)


class SourceVersionResource(AgentModel):
    id: str
    retrospective_id: str
    ordinal: int
    source_kind: str
    file_name: str | None
    content_sha256: str
    body_available: bool
    body: str | None = None
    cleared_at: str | None
    created_at: str


class StartCleanupCommand(AgentModel):
    workspace_id: str
    source_version_id: str


class CleanupControlCommand(AgentModel):
    workspace_id: str


class CleanupStartResource(AgentModel):
    cleanup_version_id: str
    execution_id: str


class SegmentResource(AgentModel):
    id: str
    ordinal: int
    speaker_role: str
    raw_speaker_label: str | None
    display_name: str
    body: str
    source_start: int
    source_end: int
    confidence: float
    uncertainty_reason: str | None
    ignored: bool
    version: int


class CleanupVersionResource(AgentModel):
    id: str
    retrospective_id: str
    source_version_id: str
    ordinal: int
    execution_id: str | None
    status: str
    stage: str
    control_intent: str | None
    confirmed_at: str | None
    version: int
    created_at: str
    updated_at: str
    segments: list[SegmentResource]


class SegmentEdit(AgentModel):
    speaker_role: Literal["candidate", "interviewer", "unknown"]
    raw_speaker_label: str | None = Field(default=None, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=24_000)
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    uncertainty_reason: str | None = Field(default=None, max_length=500)
    ignored: bool = False


class UpdateSegmentsCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)
    segments: list[SegmentEdit] = Field(min_length=1, max_length=500)


class VersionedRetrospectiveCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)


class DeleteRetrospectiveCommand(VersionedRetrospectiveCommand):
    pass


class DeletionImpactResource(AgentModel):
    source_versions: int
    cleanup_versions: int
    analysis_runs: int
    candidates: int
    action_items: int
    preserves_review_questions: bool
    preserves_profile_and_projects: bool
    preserves_knowledge: bool
