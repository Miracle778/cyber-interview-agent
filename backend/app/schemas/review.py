from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent import MessageResource


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ReviewModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


ReviewMode = Literal[
    "weak-point", "random-mixed", "topic-focused", "recent-mistake"
]
MasteryState = Literal["unknown", "weak", "partial", "stable", "strong"]
Difficulty = Literal["easy", "medium", "hard"]
ReasoningEffort = Literal["none", "low", "medium", "high"]


class ReviewQuestion(ReviewModel):
    id: str
    title: str
    question_text: str
    reference_answer: str
    topics: list[str]
    difficulty: Difficulty
    key_points: list[str]
    follow_ups: list[str]
    mastery: MasteryState = "unknown"


class ReviewRoundSettings(ReviewModel):
    selected_topics: list[str]
    difficulties: list[Difficulty]
    question_count: int = Field(ge=1, le=50)
    mode: ReviewMode
    allow_follow_up: bool = True
    seed: int | None = None
    answer_model_id: str = Field(min_length=1)
    reasoning_effort: Literal["none", "low", "medium", "high"] = "none"


class CreateQuestionBatchCommand(ReviewModel):
    workspace_id: str = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    rewrite_feedback: str | None = None
    rewrite_of_batch_id: str | None = None


class CreateCurationSessionCommand(ReviewModel):
    workspace_id: str = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)


class SubmitCurationCommand(ReviewModel):
    text: str = Field(min_length=1, max_length=5000)
    summary_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=200)
    provider_model_id: str | None = Field(default=None, min_length=1)
    reasoning_effort: ReasoningEffort = "none"


class StartBulkPublicationCommand(ReviewModel):
    summary_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=200)
    candidate_ids: list[str] = Field(min_length=1)


class RetryBulkPublicationCommand(ReviewModel):
    idempotency_key: str = Field(min_length=8, max_length=200)


class UpdateQuestionCandidateCommand(ReviewModel):
    version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1)
    question_text: str | None = Field(default=None, min_length=1)
    reference_answer: str | None = Field(default=None, min_length=1)
    topics: list[str] | None = None
    difficulty: Difficulty | None = None
    key_points: list[str] | None = None
    follow_ups: list[str] | None = None


class RewriteQuestionCandidateCommand(ReviewModel):
    feedback: str = Field(min_length=1, max_length=5000)


class DeleteQuestionCandidateCommand(ReviewModel):
    idempotency_key: str = Field(min_length=8, max_length=200)
    expected_version: int | None = Field(default=None, ge=1)
    reason: str = Field(default="", max_length=1000)


class BulkDeleteQuestionCandidateItem(ReviewModel):
    candidate_id: str = Field(min_length=1)
    expected_version: int | None = Field(default=None, ge=1)


class BulkDeleteQuestionCandidatesCommand(ReviewModel):
    workspace_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=8, max_length=200)
    items: list[BulkDeleteQuestionCandidateItem] = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=1000)


class UpdateQuestionCandidateNoteCommand(ReviewModel):
    note: str = Field(max_length=5000)


class PublishQuestionCandidateCommand(ReviewModel):
    idempotency_key: str = Field(min_length=8, max_length=200)


class UpdateActiveQuestionVersionCommand(ReviewModel):
    target_question_id: str = Field(min_length=1)
    expected_active_hash: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=200)


class CreateReviewRoundCommand(ReviewRoundSettings):
    workspace_id: str = Field(min_length=1)


class SubmitReviewInputCommand(ReviewModel):
    input_request_id: str
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=200)
    value: str = Field(min_length=1, max_length=20000)


class RetryReviewEvaluationCommand(ReviewModel):
    idempotency_key: str = Field(min_length=8, max_length=200)


class SkipReviewInputCommand(ReviewModel):
    input_request_id: str
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=200)


class CreateReviewDiscussionCommand(ReviewModel):
    ordinal: int = Field(ge=1)
    message: str = Field(min_length=1, max_length=20000)


class QuestionSnapshotResource(ReviewModel):
    question_id: str
    document_id: str
    content_hash: str
    title: str
    question_text: str
    reference_answer: str
    topics: list[str]
    difficulty: Difficulty
    key_points: list[str]
    follow_ups: list[str]


class DraftSummaryResource(ReviewModel):
    id: str
    title: str
    markdown: str
    status: str
    version: int
    content_hash: str
    document_type: str


class QuestionCandidateResource(ReviewModel):
    id: str
    batch_id: str
    curation_session_id: str
    live_curation_session_id: str | None
    question: QuestionSnapshotResource
    source_refs: list[str]
    correction_note: str
    review_note: str
    review_note_updated_at: str | None
    rejection_reason: str | None
    rejected_at: str | None
    rejection_action_id: str | None
    duplicate_of_question_id: str | None
    duplicate_question: QuestionSnapshotResource | None
    revision_of_question_id: str | None
    is_active_version: bool
    status: str
    deleted_at: str | None
    deletion_reason: str
    draft: DraftSummaryResource | None
    created_at: str
    updated_at: str


class QuestionBatchResource(ReviewModel):
    id: str
    workspace_id: str
    session_id: str | None
    origin_session_id: str
    run_id: str | None
    source_refs: list[str]
    rewrite_of_batch_id: str | None
    status: str
    candidate_count: int = 0
    pending_count: int = 0
    candidates: list[QuestionCandidateResource] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ActiveQuestionResource(ReviewModel):
    id: str
    title: str
    question_text: str
    reference_answer: str
    topics: list[str]
    difficulty: Difficulty
    key_points: list[str]
    follow_ups: list[str]
    draft_id: str
    publication_id: str
    published_at: str


class CurrentQuestionResource(ReviewModel):
    id: str
    title: str
    question_text: str
    topics: list[str]
    difficulty: Difficulty


class ReviewInputResource(ReviewModel):
    id: str
    round_id: str
    ordinal: int
    kind: Literal["answer", "follow_up"]
    prompt: str
    version: int
    status: str
    created_at: str
    resolved_at: str | None


class ReviewAttemptResource(ReviewModel):
    id: str
    round_id: str
    ordinal: int
    question_snapshot: QuestionSnapshotResource
    answer: str | None
    follow_up_answer: str | None
    evaluation: dict[str, Any] | None
    mastery_suggestion: str | None
    skipped: bool
    status: Literal[
        "evaluating",
        "waiting_for_follow_up",
        "completed",
        "evaluation_failed",
    ]
    evaluation_error_code: str | None
    evaluation_started_at: str | None
    evaluation_completed_at: str | None
    created_at: str
    updated_at: str


class ReviewReportResource(ReviewModel):
    id: str
    report_kind: Literal["session_report", "mastery_report"]
    title: str
    status: str
    version: int
    publication: dict[str, Any] | None


class UsageResource(ReviewModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    call_count: int
    estimated_count: int


class ContextUsageResource(ReviewModel):
    current_tokens: int
    threshold_tokens: int
    estimated: bool


class ReviewAnswerReceiptResource(ReviewModel):
    receipt_id: str
    round_id: str
    attempt_id: str
    input_request_id: str
    status: Literal["evaluating"]
    accepted_at: str
    version: int


class CurationSourceResource(ReviewModel):
    id: str
    filename: str
    organization_state: Literal[
        "not_curated", "in_progress", "previously_curated"
    ]


class LatestCurationCommandResource(ReviewModel):
    command_id: str
    execution_id: str | None
    lifecycle_status: str
    retry_count: int


class CurationSessionResource(ReviewModel):
    id: str
    workspace_id: str
    title: str
    deleted_at: str | None = None
    source_refs: list[str]
    sources: list[CurationSourceResource]
    active_batch_id: str | None
    execution_id: str | None
    execution_status: str | None
    execution_started_at: str | None
    execution_finished_at: str | None
    execution_error_code: str | None
    execution_error_message: str | None
    context_compacted: bool
    context_usage: ContextUsageResource
    stage: str
    progress: dict[str, int]
    summary: dict[str, Any]
    summary_version: int
    warnings: list[dict[str, Any]]
    preferred_model_id: str | None = None
    preferred_reasoning_effort: ReasoningEffort = "none"
    latest_command: LatestCurationCommandResource | None = None
    candidate_count: int
    pending_count: int
    published_count: int
    messages: list[MessageResource]
    usage: UsageResource
    created_at: str
    updated_at: str


class CandidateOriginSessionResource(ReviewModel):
    status: Literal["available", "recycled", "projection_missing", "missing"]
    session_id: str
    session: CurationSessionResource | None = None


class QuestionDeletionItemResource(ReviewModel):
    candidate_id: str
    status: Literal["deleted", "already_deleted", "blocked", "failed"]
    reason: str | None = None


class QuestionDeletionResultResource(ReviewModel):
    items: list[QuestionDeletionItemResource]


class CurationCommandReceiptResource(ReviewModel):
    id: str
    session_id: str
    summary_version: int
    kind: str
    target_ids: list[str]
    status: str
    result: dict[str, Any]
    created_at: str
    completed_at: str | None


class AcceptedCurationCommandResource(ReviewModel):
    command_id: str
    execution_id: str
    status: Literal["accepted"] = "accepted"


class BulkPublicationPreflightResource(ReviewModel):
    session_id: str
    summary_version: int
    publishable: list[str]
    already_published: list[str]
    needs_review: list[str]
    blocked: list[str]


class AcceptedBulkPublicationResource(ReviewModel):
    operation_id: str
    execution_id: str
    status: Literal["accepted"] = "accepted"


class BulkPublicationItemResource(ReviewModel):
    id: str
    operation_id: str
    candidate_id: str
    idempotency_key: str
    status: str
    error_code: str | None
    created_at: str
    updated_at: str


class BulkPublicationResource(ReviewModel):
    id: str
    session_id: str
    execution_id: str | None
    summary_version: int
    status: str
    retry_count: int
    items: list[BulkPublicationItemResource]
    created_at: str
    completed_at: str | None


class ReviewRoundResource(ReviewModel):
    id: str
    workspace_id: str
    session_id: str
    execution_id: str | None
    settings: dict[str, Any]
    status: str
    execution_status: str | None
    current_index: int
    question_count: int
    current_question: CurrentQuestionResource | None
    current_input: ReviewInputResource | None
    attempts: list[ReviewAttemptResource]
    messages: list[MessageResource]
    reports: list[ReviewReportResource]
    usage: UsageResource
    created_at: str
    updated_at: str
    completed_at: str | None
    archived_at: str | None


class DiscussionSessionResource(ReviewModel):
    id: str
    workspace_id: str
    kind: str
    title: str
    status: str
    created_at: str
    updated_at: str
    latest_execution_id: str | None
