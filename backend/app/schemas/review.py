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
    question: QuestionSnapshotResource
    source_refs: list[str]
    correction_note: str
    duplicate_of_question_id: str | None
    duplicate_question: QuestionSnapshotResource | None
    status: str
    draft: DraftSummaryResource | None
    created_at: str
    updated_at: str


class QuestionBatchResource(ReviewModel):
    id: str
    workspace_id: str
    session_id: str
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
    stage: str
    progress: dict[str, int]
    summary: dict[str, Any]
    summary_version: int
    warnings: list[dict[str, Any]]
    candidate_count: int
    pending_count: int
    published_count: int
    messages: list[MessageResource]
    usage: UsageResource
    created_at: str
    updated_at: str


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


class DiscussionSessionResource(ReviewModel):
    id: str
    workspace_id: str
    kind: str
    title: str
    status: str
    created_at: str
    updated_at: str
    latest_execution_id: str | None
