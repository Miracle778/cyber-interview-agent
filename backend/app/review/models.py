from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, TypeAlias


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
]
AttemptStatus: TypeAlias = Literal[
    "evaluating", "waiting_for_follow_up", "completed", "evaluation_failed"
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
        if not self.key_points or any(
            not point.strip() for point in self.key_points
        ):
            raise ValueError("key_points must not be empty")


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
    session_id: str
    run_id: str | None
    source_refs: tuple[str, ...]
    rewrite_of_batch_id: str | None
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class QuestionCandidateRecord:
    id: str
    batch_id: str
    draft_id: str | None
    question: QuestionSnapshot
    source_refs: tuple[str, ...]
    correction_note: str
    duplicate_of_question_id: str | None
    status: str
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
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class QuestionSourceLinkRecord:
    id: str
    question_id: str
    source_id: str
    batch_id: str
    session_id: str
    evidence_ref: str
    merge_reason: str
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
