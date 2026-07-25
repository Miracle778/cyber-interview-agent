from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schemas.agent import AgentModel


class CreateJobTargetCommand(AgentModel):
    role_name: str = Field(default="", max_length=120)
    seniority: str = Field(default="", max_length=80)
    company_name: str | None = Field(default=None, max_length=160)
    source_url: str | None = Field(default=None, max_length=2000)


class UpdateJobTargetCommand(CreateJobTargetCommand):
    workspace_id: str
    expected_version: int = Field(ge=1)


class JobTargetLifecycleCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)


class JobDocumentVersionCommand(AgentModel):
    workspace_id: str
    source_kind: Literal["jd_text", "direction_reference"]
    body: str = Field(min_length=1, max_length=200_000)


class ConfirmJobDocumentCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)


class RequirementDecisionItem(AgentModel):
    requirement_id: str
    expected_version: int = Field(ge=1)
    decision: Literal["pending", "confirmed", "rejected"]


class RequirementDecisionCommand(AgentModel):
    workspace_id: str
    decisions: list[RequirementDecisionItem] = Field(min_length=1, max_length=100)


class SafeRequirementConfirmationCommand(AgentModel):
    workspace_id: str
    document_version_id: str


class ProjectPriorityCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)
    core_project_id: str
    supplementary_project_ids: list[str] = Field(default_factory=list, max_length=2)


class JobTargetResource(AgentModel):
    id: str
    workspace_id: str
    company_name: str | None
    role_name: str
    seniority: str
    source_url: str | None
    lifecycle_status: str
    current_document_version_id: str | None
    version: int
    created_at: str
    updated_at: str


class JobDocumentVersionResource(AgentModel):
    id: str
    job_target_id: str
    ordinal: int
    source_kind: str
    body: str
    content_hash: str
    is_current: bool
    created_at: str


class JobRequirementResource(AgentModel):
    id: str
    job_target_id: str
    document_version_id: str
    stable_key: str
    requirement_type: str
    priority: str
    text: str
    source_quote: str
    source_start: int | None
    source_end: int | None
    inferred: bool
    confirmation_status: str
    preparation_status: str
    version: int
    created_at: str
    updated_at: str


class RequirementDecisionResource(AgentModel):
    confirmed_ids: list[str]
    rejected_ids: list[str]
    pending_ids: list[str]
    excluded_ids: list[str]


class ProjectPriorityResource(AgentModel):
    job_target_id: str
    core_project_id: str
    supplementary_project_ids: list[str]
    version: int


class TargetDeletionImpactResource(AgentModel):
    target_id: str
    documents: int
    requirements: int
    analyses: int
    deep_dives: int
    question_candidates: int
    preserved_profile: bool
    preserved_published_questions: bool


class JobTargetDeleteCommand(AgentModel):
    workspace_id: str


class JobAnalysisStartCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)


class AnalysisControlCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)


class ProjectDeepDiveStartCommand(AgentModel):
    workspace_id: str
    project_claim_id: str


class DeepDiveAnswerCommand(AgentModel):
    workspace_id: str
    content: str = Field(min_length=1, max_length=20_000)
    message_id: str | None = None
    provider_model_id: str | None = None
    reasoning_effort: Literal["none", "low", "medium", "high"] = "none"


class MessageAttemptCommand(AgentModel):
    workspace_id: str
    message_id: str


class MessageResolutionCommand(AgentModel):
    workspace_id: str
    resolution: Literal["abandoned", "replaced"]
    replacement_content: str | None = Field(default=None, max_length=20_000)


class GenericReceiptResource(AgentModel):
    id: str
    status: str
    version: int = 1
    detail: dict[str, Any] = Field(default_factory=dict)


class QuestionCandidateDecisionCommand(AgentModel):
    workspace_id: str
    decision: Literal["confirmed", "ignored", "duplicate"]


class QuestionCandidateBatchDecisionCommand(AgentModel):
    workspace_id: str
    candidate_ids: list[str] = Field(min_length=1, max_length=50)
    decision: Literal["confirmed", "ignored"]


class QuestionCandidateEditCommand(AgentModel):
    workspace_id: str
    title: str = Field(min_length=1, max_length=300)
    question: str = Field(min_length=1, max_length=4_000)


class NarrativeDecisionCommand(AgentModel):
    workspace_id: str
    section_ids: list[str] = Field(min_length=1, max_length=7)
    edited_values: dict[str, str] = Field(default_factory=dict)
    expected_project_version: int = Field(ge=1)


class GapDispatchCommand(AgentModel):
    workspace_id: str
