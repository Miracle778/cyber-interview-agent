from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


RetrospectiveLifecycle: TypeAlias = Literal["active", "archived", "recycled"]
InterviewOutcome: TypeAlias = Literal[
    "pending", "passed", "failed", "cancelled", "unrecorded"
]
SourceKind: TypeAlias = Literal["transcript", "recollection"]
SpeakerRole: TypeAlias = Literal["candidate", "interviewer", "unknown"]
QuestionOrigin: TypeAlias = Literal["original", "inferred"]
QuestionDecision: TypeAlias = Literal["pending", "confirmed", "rejected", "superseded"]
QuestionKind: TypeAlias = Literal[
    "technical_knowledge",
    "project_experience",
    "system_design",
    "behavioral_collaboration",
    "motivation_hr",
    "unknown",
]
AnalysisVerdict: TypeAlias = Literal[
    "strong", "improvable", "high_risk", "insufficient_evidence"
]
EvidenceLevel: TypeAlias = Literal[
    "internal_evidence", "profile_conflict", "model_judgment", "insufficient"
]
GapKind: TypeAlias = Literal["material", "expression", "knowledge", "experience"]
CandidateKind: TypeAlias = Literal[
    "review_question", "profile_claim", "project_narrative", "summary"
]


@dataclass(frozen=True, slots=True)
class RetrospectiveRecord:
    id: str
    workspace_id: str
    job_target_id: str
    title: str
    round_label: str
    interview_date: str | None
    outcome: InterviewOutcome
    note: str
    lifecycle_status: RetrospectiveLifecycle
    active_source_version_id: str | None
    active_cleanup_version_id: str | None
    active_analysis_run_id: str | None
    analysis_session_id: str
    chat_session_id: str
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SourceVersionRecord:
    id: str
    retrospective_id: str
    ordinal: int
    source_kind: SourceKind
    file_name: str | None
    body: str
    content_sha256: str
    cleared_at: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class CleanupVersionRecord:
    id: str
    retrospective_id: str
    source_version_id: str
    ordinal: int
    execution_id: str | None
    input_digest: str
    status: str
    stage: str
    control_intent: str | None
    confirmed_at: str | None
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CleanupWorkItemRecord:
    id: str
    cleanup_version_id: str
    work_key: str
    source_start: int
    source_end: int
    input_digest: str
    status: str
    output: dict[str, object] | None
    attempt_count: int
    last_error_code: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SegmentRecord:
    id: str
    cleanup_version_id: str
    ordinal: int
    speaker_role: SpeakerRole
    raw_speaker_label: str | None
    display_name: str
    body: str
    source_start: int
    source_end: int
    confidence: float
    uncertainty_reason: str | None
    ignored: bool
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class QuestionUnitRecord:
    id: str
    retrospective_id: str
    cleanup_version_id: str
    stable_key: str
    ordinal: int
    question_kind: QuestionKind
    origin: QuestionOrigin
    question_text: str
    question_segment_ids: tuple[str, ...]
    answer_segment_ids: tuple[str, ...]
    inference_basis: str
    confidence: float
    decision_status: QuestionDecision
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class AnalysisRunRecord:
    id: str
    retrospective_id: str
    cleanup_version_id: str
    execution_id: str | None
    retry_of_analysis_run_id: str | None
    input_digest: str
    context_snapshot_json: str
    status: str
    stage: str
    control_intent: str | None
    completed_items: int
    total_items: int
    current_work_key: str | None
    cumulative_elapsed_ms: int
    latest_progress_at: str | None
    summary_json: str | None
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class AnalysisWorkItemRecord:
    id: str
    analysis_run_id: str
    question_unit_id: str | None
    work_key: str
    input_digest: str
    status: str
    output: dict[str, object] | None
    attempt_count: int
    last_error_code: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class QuestionAnalysisRecord:
    id: str
    analysis_run_id: str
    question_unit_id: str
    verdict: AnalysisVerdict
    strengths: tuple[dict[str, object], ...]
    improvements: tuple[dict[str, object], ...]
    omissions: tuple[dict[str, object], ...]
    evidence_level: EvidenceLevel
    confidence: float
    improvement_outline: tuple[str, ...]
    suggested_answer: str
    source_excerpt: str
    source_excerpt_sha256: str | None
    source_available: bool
    result_status: str
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class GapRecord:
    id: str
    analysis_run_id: str
    question_analysis_id: str
    question_unit_id: str
    gap_kind: GapKind
    summary: str
    evidence: tuple[dict[str, object], ...]
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class AssetCandidateRecord:
    id: str
    retrospective_id: str
    analysis_run_id: str
    question_unit_id: str | None
    candidate_kind: CandidateKind
    fingerprint: str
    payload_json: str
    match_json: str
    status: str
    target_resource_type: str | None
    target_resource_id: str | None
    last_error_code: str | None
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ActionItemRecord:
    id: str
    retrospective_id: str
    analysis_run_id: str
    question_unit_id: str | None
    gap_id: str | None
    action_kind: GapKind
    title: str
    detail: str
    status: str
    version: int
    completed_at: str | None
    created_at: str
    updated_at: str
