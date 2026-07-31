from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


EvaluationApplicability = Literal[
    "applicable", "not_applicable", "insufficient_evidence"
]
EvaluationRating = Literal["meets", "usable", "needs_review", "severe"]
EvaluationSeverity = Literal["none", "low", "medium", "high", "critical"]
EvaluationRunKind = Literal["historical_review", "agent_regression"]


@dataclass(frozen=True, slots=True)
class EvalDimension:
    id: str
    title: str
    description: str
    weight: int = 1


@dataclass(frozen=True, slots=True)
class DeterministicRule:
    id: str
    title: str
    description: str
    required_event_types: frozenset[str]
    blocking: bool = False


@dataclass(frozen=True, slots=True)
class JudgeContract:
    prompt_id: str
    instructions: str
    response_contract: str = "JudgeResult"


@dataclass(frozen=True, slots=True)
class EvaluationTriggerPolicy:
    deterministic: Literal["always"] = "always"
    automatic_statuses: frozenset[str] = frozenset(
        {"failed", "partial_success", "degraded", "rejected", "heavily_edited"}
    )
    successful_sample_percent: int = 5
    daily_cap: int = 20


@dataclass(frozen=True, slots=True)
class EvalPack:
    id: str
    version: int
    agent_family: str
    title: str
    dimensions: tuple[EvalDimension, ...]
    required_evidence_event_types: frozenset[str]
    rules: tuple[DeterministicRule, ...]
    judge: JudgeContract
    trigger_policy: EvaluationTriggerPolicy = EvaluationTriggerPolicy()
    evaluation_contract_version: int = 1
    task_type: str = "legacy"


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class StrictJudgeModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class JudgeDimensionResult(StrictJudgeModel):
    dimension_id: str = Field(min_length=1)
    score: int = Field(ge=0, le=100)
    cited_event_hashes: list[str] = Field(min_length=1)
    cited_artifact_hashes: list[str]
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1)
    risks: list[str]


class JudgeResult(StrictJudgeModel):
    dimensions: list[JudgeDimensionResult] = Field(min_length=1)
    cited_event_hashes: list[str] = Field(min_length=1)
    cited_artifact_hashes: list[str]
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1)
    risks: list[str]
    human_review_required: bool


class JudgeDimensionResultV2(StrictJudgeModel):
    dimension_id: str = Field(min_length=1)
    applicability: EvaluationApplicability
    rating: EvaluationRating | None
    severity: EvaluationSeverity | None
    confidence: float | None = Field(default=None, ge=0, le=1)
    cited_event_hashes: list[str]
    cited_artifact_hashes: list[str]
    evidence_gaps: list[str]
    summary: str = Field(min_length=1)
    risks: list[str]

    @model_validator(mode="after")
    def validate_applicability_rating(self):
        if self.applicability == "applicable":
            if (
                self.rating is None
                or self.severity is None
                or self.confidence is None
            ):
                raise ValueError(
                    "applicable dimensions require rating, severity, and confidence"
                )
            return self
        if self.rating is not None or self.severity is not None:
            raise ValueError(
                "non-applicable dimensions cannot carry a quality rating or severity"
            )
        return self


class JudgeResultV2(StrictJudgeModel):
    dimensions: list[JudgeDimensionResultV2] = Field(min_length=1)
    summary: str = Field(min_length=1)
    risks: list[str]
    human_review_required: bool
