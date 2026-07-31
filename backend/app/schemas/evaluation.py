from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class EvaluationModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class CreateEvaluationRunCommand(EvaluationModel):
    execution_id: str = Field(min_length=1)


class EvaluationDimensionResource(EvaluationModel):
    dimension_id: str
    source: str
    status: str
    applicability: Literal[
        "applicable", "not_applicable", "insufficient_evidence"
    ]
    rating: Literal["meets", "usable", "needs_review", "severe"] | None
    severity: Literal["none", "low", "medium", "high", "critical"] | None
    score: int | None
    confidence: float | None
    summary: str
    cited_event_hashes: list[str]
    cited_artifact_hashes: list[str]
    risks: list[str]
    evidence_gaps: list[str]
    evidence_refs: list[str]


class EvaluationRunResource(EvaluationModel):
    id: str
    workspace_id: str
    execution_id: str
    eval_pack_id: str
    eval_pack_version: int
    evaluation_contract_version: int
    task_type: str
    run_kind: Literal["historical_review", "agent_regression"]
    trigger: str
    status: str
    frozen_input_hash: str
    business_outcome_hash: str | None
    judge_data_scope: dict[str, Any]
    judge_provider_model_id: str | None
    error_code: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None
    dimensions: list[EvaluationDimensionResource]
    deterministic_result: dict[str, Any] | None
    judge_summary: dict[str, Any] | None
    judge_trace_run_id: str | None = None
    raw_snapshot: dict[str, Any] | None = None
    raw_judge_result: dict[str, Any] | None = None


class EvaluationRunListResource(EvaluationModel):
    items: list[EvaluationRunResource]


class CreateEvaluationFeedbackCommand(EvaluationModel):
    verdict: Literal["accurate", "incorrect", "uncertain"]
    dimension_id: str | None = None
    reason: str | None = Field(default=None, max_length=2000)


class EvaluationFeedbackResource(EvaluationModel):
    id: str
    workspace_id: str
    eval_run_id: str
    version: int
    verdict: str
    dimension_id: str | None
    reason: str | None
    created_at: str


class CreateRegressionCaseCommand(EvaluationModel):
    eval_run_id: str
    confirmed: StrictBool
    include_private_bodies: StrictBool = False
    expected_invariants: list[str] = Field(default_factory=list)


class RegressionCaseResource(EvaluationModel):
    id: str
    execution_id: str
    eval_pack_id: str
    eval_pack_version: int
    version: int
    snapshot_hash: str
    contains_private_bodies: bool
    redaction_summary: str
    created_at: str


class RegressionCaseListResource(EvaluationModel):
    items: list[RegressionCaseResource]


class CreateRegressionRunCommand(EvaluationModel):
    case_id: str


class EvaluationComparisonResource(EvaluationModel):
    eval_pack_id: str
    eval_pack_version: int
    dimension_ids: list[str]
    runs: list[EvaluationRunResource]


class EvaluationTrendPointResource(EvaluationModel):
    bucket: str
    graph_id: str
    eval_pack_id: str
    eval_pack_version: int
    judge_provider_model_id: str | None
    prompt_version: str
    schema_version: str
    tool_version: str
    run_count: int
    success_rate: float
    deterministic_issue_rate: float
    average_judge_score: float | None
    human_review_rate: float
    average_latency_ms: float | None
    average_tokens: float
    average_context_tokens: float


class EvaluationTrendListResource(EvaluationModel):
    items: list[EvaluationTrendPointResource]
