from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, TypeAlias

from app.review.coverage import KeyPointCoverage


Difficulty: TypeAlias = Literal["easy", "medium", "hard"]
ReviewMode: TypeAlias = Literal[
    "weak-point", "random-mixed", "topic-focused", "recent-mistake"
]
RoundStatus: TypeAlias = Literal[
    "waiting_for_input",
    "running",
    "report_pending",
    "completed",
    "failed",
    "cancelled",
]
InputKind: TypeAlias = Literal["answer", "follow_up"]
MasteryState: TypeAlias = Literal[
    "unknown", "weak", "partial", "stable", "strong"
]
ReasoningEffort: TypeAlias = Literal["none", "low", "medium", "high"]
CurationStage: TypeAlias = Literal[
    "queued",
    "reading_sources",
    "generating",
    "merging",
    "summarizing",
    "waiting_for_command",
    "publishing",
    "completed",
    "failed",
    "paused",
    "interrupted",
    "terminated",
]
AttemptStatus: TypeAlias = Literal[
    "evaluating", "waiting_for_follow_up", "completed", "evaluation_failed"
]
ReviewResultKind: TypeAlias = Literal[
    "independent_mastery", "assisted_mastery", "revealed", "skipped"
]
CurationWorkStage: TypeAlias = Literal["discovery", "enrichment"]
CurationProcessorKind: TypeAlias = Literal["deterministic", "model"]
CurationWorkStatus: TypeAlias = Literal[
    "pending", "running", "completed", "failed", "interrupted"
]
CurationBatchStatus: TypeAlias = Literal[
    "generating",
    "paused",
    "interrupted",
    "review_pending",
    "completed",
    "failed",
    "terminated",
]
CurationControlIntent: TypeAlias = Literal["pause", "terminate"]
CurationControlOperation: TypeAlias = Literal["pause", "resume", "terminate"]
CurationAttemptReason: TypeAlias = Literal[
    "initial", "paused", "failed", "interrupted"
]
SeedTaskStatus: TypeAlias = Literal[
    "pending",
    "running",
    "completed",
    "degraded",
    "retryable",
    "interrupted",
    "skipped",
]
AnswerBasis: TypeAlias = Literal["source", "mixed", "model", "unknown"]
MaterialSupport: TypeAlias = Literal[
    "sufficient", "partial", "minimal", "unknown"
]

_DIFFICULTIES = frozenset({"easy", "medium", "hard"})
_MODES = frozenset(
    {"weak-point", "random-mixed", "topic-focused", "recent-mistake"}
)
_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high"})
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class QuestionSnapshot:
    question_id: str
    document_id: str
    content_hash: str
    title: str
    question_text: str
    reference_answer: str
    topics: tuple[str, ...]
    difficulty: Difficulty
    key_points: tuple[str, ...]
    follow_ups: tuple[str, ...]
    required_key_points: tuple[str, ...] = ()
    bonus_key_points: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "question_id",
            "document_id",
            "title",
            "question_text",
            "reference_answer",
        ):
            value = getattr(self, name)
            if not value.strip():
                raise ValueError(f"{name} must not be empty")
        if _HASH_PATTERN.fullmatch(self.content_hash) is None:
            raise ValueError("content_hash must be a lowercase sha256 digest")
        if self.difficulty not in _DIFFICULTIES:
            raise ValueError("unsupported difficulty")
        if not self.topics or any(not topic.strip() for topic in self.topics):
            raise ValueError("topics must not be empty")
        required = self.required_key_points or self.key_points
        if not required or any(not point.strip() for point in required):
            raise ValueError("required_key_points must not be empty")
        if any(not point.strip() for point in self.bonus_key_points):
            raise ValueError("bonus_key_points must not contain empty values")
        if not self.required_key_points:
            object.__setattr__(self, "required_key_points", required)
        if not self.key_points:
            object.__setattr__(
                self, "key_points", (*required, *self.bonus_key_points)
            )


@dataclass(frozen=True, slots=True)
class ReviewRoundSettings:
    topics: tuple[str, ...]
    difficulties: tuple[Difficulty, ...]
    mode: ReviewMode
    question_count: int
    allow_follow_up: bool
    seed: int
    answer_model_id: str
    reasoning_effort: ReasoningEffort

    def __post_init__(self) -> None:
        if not 1 <= self.question_count <= 50:
            raise ValueError("question_count must be between 1 and 50")
        if self.mode not in _MODES:
            raise ValueError("unsupported review mode")
        if self.mode == "topic-focused" and not self.topics:
            raise ValueError("topic-focused rounds require topics")
        if any(not topic.strip() for topic in self.topics):
            raise ValueError("topics must not contain empty values")
        if not self.difficulties or any(
            difficulty not in _DIFFICULTIES
            for difficulty in self.difficulties
        ):
            raise ValueError("difficulties must contain supported values")
        if not self.answer_model_id.strip():
            raise ValueError("answer_model_id must not be empty")
        if self.reasoning_effort not in _REASONING_EFFORTS:
            raise ValueError("unsupported reasoning_effort")


@dataclass(frozen=True, slots=True)
class QuestionCatalogRecord:
    snapshot: QuestionSnapshot
    workspace_id: str
    draft_id: str
    publication_id: str
    active: bool
    published_at: str
    question_type: str = "technical"
    project_claim_id: str | None = None
    project_dimension: str | None = None
    source_job_target_id: str | None = None
    source_deep_dive_id: str | None = None


@dataclass(frozen=True, slots=True)
class MasteryEntry:
    subject_id: str
    state: MasteryState
    recent_mistake: bool = False
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MasteryProjection:
    workspace_id: str
    version: int
    entries: tuple[MasteryEntry, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.version < 0:
            raise ValueError("mastery version must not be negative")


@dataclass(frozen=True, slots=True)
class QuestionBatchRecord:
    id: str
    workspace_id: str
    session_id: str | None
    origin_session_id: str
    run_id: str | None
    source_refs: tuple[str, ...]
    rewrite_of_batch_id: str | None
    status: CurationBatchStatus
    version: int
    control_intent: CurationControlIntent | None
    concurrency_limit: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CurationWorkItemRecord:
    id: str
    batch_id: str
    stage: CurationWorkStage
    unit_index: int
    input_digest: str
    source_refs: tuple[str, ...]
    processor_kind: CurationProcessorKind
    status: CurationWorkStatus
    output: dict[str, object] | None
    attempt_count: int
    last_error_code: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CurationSeedTaskRecord:
    id: str
    batch_id: str
    discovery_work_item_id: str
    seed_key: str
    seed_ordinal: int
    question_text: str
    primary_source_ref: str
    source_refs: tuple[str, ...]
    input_digest: str
    status: SeedTaskStatus
    automatic_attempt_count: int
    manual_attempt_count: int
    candidate: dict[str, object] | None
    answer_basis: AnswerBasis
    material_support: MaterialSupport
    needs_review: bool
    normalization_issues: tuple[str, ...]
    last_error_code: str | None
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CurationSeedRetryReceiptRecord:
    id: str
    seed_task_id: str
    idempotency_key: str
    request_digest: str
    execution_id: str
    result_status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CurationBatchAttemptRecord:
    id: str
    batch_id: str
    execution_id: str
    ordinal: int
    reason: CurationAttemptReason
    created_at: str


@dataclass(frozen=True, slots=True)
class CurationControlReceiptRecord:
    id: str
    batch_id: str
    idempotency_key: str
    operation: CurationControlOperation
    request_digest: str
    execution_id: str | None
    reserved_execution_id: str | None
    result_status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CurationBatchTiming:
    current_elapsed_ms: int
    cumulative_elapsed_ms: int


@dataclass(frozen=True, slots=True)
class QuestionCandidateRecord:
    id: str
    batch_id: str
    draft_id: str | None
    question: QuestionSnapshot
    source_refs: tuple[str, ...]
    correction_note: str
    review_note: str
    review_note_updated_at: str | None
    rejection_reason: str | None
    rejected_at: str | None
    rejection_action_id: str | None
    duplicate_of_question_id: str | None
    revision_of_question_id: str | None
    revision_base_hash: str | None
    seed_task_id: str | None
    answer_basis: AnswerBasis
    material_support: MaterialSupport
    needs_review: bool
    normalization_issues: tuple[str, ...]
    confirmation_status: Literal["pending", "confirmed"]
    confirmation_version: int
    confirmed_at: str | None
    status: str
    deleted_at: str | None
    deletion_reason: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CurationSummary:
    items: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class CurationSessionRecord:
    session_id: str
    workspace_id: str
    source_refs: tuple[str, ...]
    active_batch_id: str | None
    stage: CurationStage
    completed_units: int
    total_units: int
    summary: CurationSummary
    summary_version: int
    warnings: tuple[dict[str, object], ...]
    preferred_model_id: str | None
    preferred_reasoning_effort: ReasoningEffort
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CurationContextRecord:
    session_id: str
    version: int
    focused_candidate_ids: tuple[str, ...]
    last_intent: str | None
    last_result_candidate_ids: tuple[str, ...]
    dialogue_summary: dict[str, object]
    summarized_through_message_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class QuestionSourceLinkRecord:
    id: str
    question_id: str
    source_id: str
    batch_id: str
    session_id: str | None
    origin_session_id: str
    evidence_ref: str
    merge_reason: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CurationCommandReceiptRecord:
    id: str
    session_id: str
    idempotency_key: str
    text_hash: str
    original_text: str
    summary_version: int
    command: dict[str, object]
    result: dict[str, object]
    status: str
    execution_id: str | None
    lifecycle_status: str
    retry_count: int
    created_at: str
    completed_at: str | None


@dataclass(frozen=True, slots=True)
class BulkPublicationPreflight:
    session_id: str
    summary_version: int
    publishable: tuple[str, ...]
    already_published: tuple[str, ...]
    needs_review: tuple[str, ...]
    blocked: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkPublicationRecord:
    id: str
    session_id: str
    execution_id: str | None
    summary_version: int
    idempotency_key: str
    retry_idempotency_key: str | None
    retry_count: int
    status: str
    created_at: str
    completed_at: str | None


@dataclass(frozen=True, slots=True)
class BulkPublicationItemRecord:
    id: str
    operation_id: str
    candidate_id: str
    idempotency_key: str
    status: str
    error_code: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ReviewRoundRecord:
    id: str
    workspace_id: str
    session_id: str
    execution_id: str | None
    settings: ReviewRoundSettings
    question_snapshots: tuple[QuestionSnapshot, ...]
    mastery_before: MasteryProjection
    current_index: int
    status: RoundStatus
    version: int
    created_at: str
    updated_at: str
    completed_at: str | None
    archived_at: str | None


@dataclass(frozen=True, slots=True)
class ReviewInputRequestRecord:
    id: str
    round_id: str
    ordinal: int
    kind: InputKind
    prompt: str
    version: int
    status: str
    created_at: str
    resolved_at: str | None


@dataclass(frozen=True, slots=True)
class ReviewInputReceipt:
    id: str
    input_request_id: str
    idempotency_key: str
    value_hash: str
    receipt: dict[str, object]
    created_at: str


@dataclass(frozen=True, slots=True)
class ReviewAttemptRecord:
    id: str
    round_id: str
    ordinal: int
    question_snapshot: QuestionSnapshot
    answer: str | None
    follow_up_answer: str | None
    evaluation: dict[str, object] | None
    mastery_suggestion: str | None
    skipped: bool
    created_at: str
    updated_at: str
    status: AttemptStatus = "completed"
    evaluation_error_code: str | None = None
    evaluation_started_at: str | None = None
    evaluation_completed_at: str | None = None
    coverage: tuple[KeyPointCoverage, ...] = ()
    result_kind: ReviewResultKind | None = None
    hint_level: int = 0
    answer_revisions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewAnswerReceipt:
    id: str
    round_id: str
    attempt_id: str
    input_request_id: str
    message_id: str
    status: AttemptStatus
    version: int
    accepted_at: str


@dataclass(frozen=True, slots=True)
class ReportProposalRecord:
    draft_id: str
    round_id: str
    report_kind: Literal["session_report", "mastery_report"]
    projection: MasteryProjection | None
    expected_mastery_version: int | None
    created_at: str
    updated_at: str
