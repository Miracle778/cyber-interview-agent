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
    active_source_available: bool
    active_cleanup_version_id: str | None
    active_analysis_run_id: str | None
    version: int
    created_at: str
    updated_at: str


class RetrospectiveSearchFiltersInput(AgentModel):
    job_target_id: str | None = None
    company: str | None = Field(default=None, max_length=240)
    role: str | None = Field(default=None, max_length=240)
    round_label: str | None = Field(default=None, max_length=120)
    date_from: str | None = None
    date_to: str | None = None
    origins: list[Literal["original", "inferred"]] = Field(
        default_factory=list, max_length=2
    )


class CreateRetrospectiveSearchCommand(AgentModel):
    workspace_id: str
    query_text: str = Field(min_length=1, max_length=2_000)
    filters: RetrospectiveSearchFiltersInput = Field(
        default_factory=RetrospectiveSearchFiltersInput
    )


class RetrospectiveSearchSetResource(AgentModel):
    id: str
    workspace_id: str
    session_id: str | None
    execution_id: str | None
    query_text: str
    filters: dict[str, object]
    search_plan: dict[str, object]
    status: Literal["pending", "searching", "completed", "failed"]
    total_questions: int
    total_retrospectives: int
    summary_markdown: str
    summary_citation_question_ids: list[str]
    summary_execution_id: str | None
    last_error_code: str | None
    version: int
    completed_at: str | None
    created_at: str
    updated_at: str


class RetrospectiveSearchResultResource(AgentModel):
    id: str
    search_set_id: str
    retrospective_id: str | None
    question_unit_id: str | None
    question_analysis_id: str | None
    rank: int
    score: float
    matched_terms: list[str]
    source_metadata: dict[str, object]
    question_snapshot: dict[str, object]
    answer_excerpt: str
    analysis_snapshot: dict[str, object]
    source_available: bool
    created_at: str


class RetrospectiveSearchSummaryCommand(AgentModel):
    workspace_id: str


class CreateRetrospectiveSearchReportCommand(AgentModel):
    workspace_id: str
    title: str = Field(min_length=1, max_length=240)
    focus: Literal["question_summary", "performance_review", "preparation"]
    selected_result_ids: list[str] = Field(default_factory=list, max_length=2_000)
    include_answer_excerpts: bool = True
    include_action_plan: bool = True


class RetrospectiveSearchReportResource(AgentModel):
    id: str
    workspace_id: str
    search_set_id: str | None
    report_key: str
    ordinal: int
    supersedes_report_id: str | None
    execution_id: str | None
    title: str
    focus: str
    selected_result_ids: list[str]
    body: dict[str, object]
    markdown: str
    citation_question_ids: list[str]
    include_answer_excerpts: bool
    include_action_plan: bool
    status: Literal["queued", "running", "completed", "failed"]
    last_error_code: str | None
    version: int
    completed_at: str | None
    created_at: str
    updated_at: str


class UpdateRetrospectiveSearchReportCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=240)
    markdown: str = Field(min_length=1, max_length=500_000)


class AddSourceVersionCommand(AgentModel):
    workspace_id: str
    source_kind: Literal["transcript", "recollection"]
    recording_coverage: Literal[
        "full_dialogue", "candidate_only", "mixed_unknown"
    ] = "mixed_unknown"
    body: str = Field(min_length=1, max_length=500_000)
    file_name: str | None = Field(default=None, max_length=255)


class SourceVersionResource(AgentModel):
    id: str
    retrospective_id: str
    ordinal: int
    source_kind: str
    recording_coverage: str
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


class TranscriptCorrectionResource(AgentModel):
    id: str
    segment_id: str
    source_start: int
    source_end: int
    original_text: str | None
    suggested_text: str | None
    adopted_text: str | None
    change_type: Literal["formatting", "recognition", "semantic"]
    risk_level: Literal["low", "high"]
    reason: str | None
    confidence: float
    decision: Literal[
        "auto_accepted",
        "pending",
        "accepted",
        "kept_original",
        "manual",
        "superseded",
    ]


class TranscriptReviewIssueResource(AgentModel):
    id: str
    ordinal: int
    document_start: int
    document_end: int
    excerpt: str
    suggestion: str | None
    issue_kind: Literal["uncertain_term", "speaker", "semantic"]
    reason: str
    confidence: float
    decision: Literal["pending", "accepted", "kept", "manual"]


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
    document_body: str | None
    document_sha256: str | None
    completed_items: int
    total_items: int
    active_items: int
    failed_items: int
    current_work_key: str | None
    last_error_code: str | None
    active_since: str | None
    latest_progress_at: str | None
    version: int
    created_at: str
    updated_at: str
    segments: list[SegmentResource]
    corrections: list[TranscriptCorrectionResource]
    review_issues: list[TranscriptReviewIssueResource]


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


class CorrectionDecisionEdit(AgentModel):
    id: str = Field(min_length=1, max_length=128)
    decision: Literal["accepted", "kept_original", "manual"]
    manual_text: str | None = Field(default=None, max_length=24_000)


class UpdateSegmentsCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)
    segments: list[SegmentEdit] = Field(min_length=1, max_length=500)
    correction_decisions: list[CorrectionDecisionEdit] = Field(
        default_factory=list, max_length=5_000
    )


class TranscriptReviewIssueDecisionEdit(AgentModel):
    id: str = Field(min_length=1, max_length=128)
    decision: Literal["accepted", "kept", "manual"]


class UpdateCleanTranscriptCommand(AgentModel):
    workspace_id: str
    expected_version: int = Field(ge=1)
    document_body: str = Field(min_length=1, max_length=500_000)
    review_issue_decisions: list[TranscriptReviewIssueDecisionEdit] = Field(
        default_factory=list, max_length=5_000
    )


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


class StartAnalysisCommand(AgentModel):
    workspace_id: str
    cleanup_version_id: str


class AnalysisControlCommand(AgentModel):
    workspace_id: str


class AnalysisStartResource(AgentModel):
    analysis_run_id: str
    execution_id: str


class AnalysisRunResource(AgentModel):
    id: str
    retrospective_id: str
    cleanup_version_id: str
    execution_id: str | None
    retry_of_analysis_run_id: str | None
    status: str
    stage: str
    control_intent: str | None
    completed_items: int
    total_items: int
    current_work_key: str | None
    cumulative_elapsed_ms: int
    latest_progress_at: str | None
    summary: dict[str, object] | None
    version: int
    created_at: str
    updated_at: str


class QuestionResource(AgentModel):
    id: str
    retrospective_id: str
    cleanup_version_id: str
    ordinal: int
    question_kind: str
    origin: Literal["original", "inferred"]
    question_text: str
    question_segment_ids: list[str]
    answer_segment_ids: list[str]
    inference_basis: str
    confidence: float
    decision_status: Literal["pending", "confirmed", "rejected", "superseded"]
    version: int
    created_at: str
    updated_at: str


class QuestionDecisionCommand(AgentModel):
    workspace_id: str
    decision: Literal["confirmed", "rejected", "superseded"]
    edited_text: str | None = Field(default=None, min_length=1, max_length=4_000)
    expected_version: int = Field(ge=1)


class AnalysisGapResource(AgentModel):
    kind: str
    summary: str
    evidence_segment_ids: list[str]


class QuestionAnalysisResource(AgentModel):
    id: str
    analysis_run_id: str
    question_unit_id: str
    verdict: str
    strengths: list[dict[str, object]]
    improvements: list[dict[str, object]]
    omissions: list[dict[str, object]]
    gaps: list[AnalysisGapResource]
    evidence_level: str
    confidence: float
    improvement_outline: list[str]
    suggested_answer: str
    source_excerpt: str
    source_available: bool
    result_status: str
    version: int


class AnalysisWorkItemResource(AgentModel):
    id: str
    question_unit_id: str | None
    work_key: str
    status: str
    attempt_count: int
    last_error_code: str | None
    updated_at: str


class AnalysisReportResource(AgentModel):
    analysis_run: AnalysisRunResource
    questions: list[QuestionResource]
    analyses: list[QuestionAnalysisResource]
    items: list[AnalysisWorkItemResource]
    summary: dict[str, object]


class AssetCandidateResource(AgentModel):
    id: str
    retrospective_id: str
    analysis_run_id: str
    question_unit_id: str | None
    candidate_kind: Literal[
        "review_question", "profile_claim", "project_narrative", "summary"
    ]
    fingerprint: str
    payload: dict[str, object]
    matches: list[dict[str, object]]
    status: str
    target_resource_type: str | None
    target_resource_id: str | None
    last_error_code: str | None
    version: int
    created_at: str
    updated_at: str


CandidateDecision = Literal[
    "link_existing",
    "supplement_existing",
    "create_new",
    "propose_update",
    "propose_new",
    "reject",
    "include",
    "exclude",
]


class CandidateDecisionCommand(AgentModel):
    workspace_id: str
    action: CandidateDecision
    target_resource_id: str | None = None
    action_payload: dict[str, object] = Field(default_factory=dict)
    expected_version: int = Field(ge=1)


class BatchCandidateDecisionItem(AgentModel):
    candidate_id: str
    action: CandidateDecision
    target_resource_id: str | None = None
    action_payload: dict[str, object] = Field(default_factory=dict)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=200)


class BatchCandidateDecisionCommand(AgentModel):
    workspace_id: str
    decisions: list[BatchCandidateDecisionItem] = Field(min_length=1, max_length=100)


class BatchCandidateDecisionResult(AgentModel):
    candidate_id: str
    status: Literal["completed", "failed"]
    candidate: AssetCandidateResource | None = None
    error_code: str | None = None


class ActionItemResource(AgentModel):
    id: str
    retrospective_id: str
    analysis_run_id: str
    question_unit_id: str | None
    gap_id: str | None
    action_kind: Literal["material", "expression", "knowledge", "experience"]
    title: str
    detail: str
    status: Literal["pending", "completed", "dismissed"]
    version: int
    completed_at: str | None
    created_at: str
    updated_at: str


class ActionDecisionCommand(AgentModel):
    workspace_id: str
    decision: Literal["completed", "dismissed"]
    expected_version: int = Field(ge=1)


class PublicationDraftCommand(AgentModel):
    workspace_id: str
    selected_sections: list[
        Literal[
            "basic_info",
            "confirmed_questions",
            "selected_conclusions",
            "confirmed_experiences",
            "action_items",
            "stable_links",
        ]
    ] = Field(min_length=1, max_length=6)


class PublicationDraftResource(AgentModel):
    id: str
    document_type: str
    title: str
    markdown: str
    status: str
    version: int


class ImmediatePracticeResource(AgentModel):
    question_id: str
    href: str


class RetrospectiveChatCommand(AgentModel):
    workspace_id: str
    message: str = Field(min_length=1, max_length=20_000)
    selected_question_id: str | None = None


class RetrospectiveChatControlCommand(AgentModel):
    workspace_id: str


class CorrectionDecisionCommand(AgentModel):
    workspace_id: str
    decision: Literal["confirmed", "rejected"]


class ConversationMessageResource(AgentModel):
    id: str
    execution_id: str | None
    role: str
    content: str
    message_kind: str
    payload: dict[str, object]
    created_at: str


class CorrectionProposalResource(AgentModel):
    id: str
    retrospective_id: str
    chat_message_id: str | None
    proposal_type: str
    target_question_id: str | None
    source_cleanup_version_id: str
    source_analysis_run_id: str | None
    before: dict[str, object]
    after: dict[str, object]
    rationale: str
    expected_version: int
    status: str
    resulting_cleanup_version_id: str | None
    resulting_analysis_run_id: str | None
    version: int
    created_at: str
    updated_at: str


class ConversationExecutionResource(AgentModel):
    id: str
    status: str
    error_code: str | None
    created_at: str
    finished_at: str | None


class RetrospectiveConversationResource(AgentModel):
    session_id: str
    messages: list[ConversationMessageResource]
    proposals: list[CorrectionProposalResource]
    latest_execution: ConversationExecutionResource | None
