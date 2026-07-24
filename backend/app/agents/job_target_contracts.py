from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class JobRequirementSuggestion(BaseModel):
    stable_key: str
    requirement_type: Literal["responsibility", "skill", "experience", "project"]
    priority: Literal["must_have", "nice_to_have"]
    text: str
    source_quote: str
    source_start: int | None = None
    source_end: int | None = None
    inferred: bool = False


class JobRequirementExtraction(BaseModel):
    requirements: list[JobRequirementSuggestion] = Field(max_length=100)


class ProjectRelevanceSuggestion(BaseModel):
    project_claim_id: str
    requirement_ids: list[str] = Field(default_factory=list)
    claim_version_ids: list[str] = Field(default_factory=list)
    rationale: str
    unresolved: list[str] = Field(default_factory=list)


class AnswerEvaluation(BaseModel):
    summary: str
    completeness: Literal["insufficient", "basic", "complete"]


class NarrativeSectionDelta(BaseModel):
    section: Literal["background", "role", "solution", "difficulty", "outcome", "tradeoff", "retrospective"]
    content: str


class TargetFinding(BaseModel):
    requirement_id: str | None = None
    summary: str


class GapSuggestion(BaseModel):
    kind: Literal["profile", "expression", "knowledge", "experience"]
    summary: str


class NextQuestion(BaseModel):
    stage: str
    content: str


class DeepDiveTurnResult(BaseModel):
    answer_evaluation: AnswerEvaluation
    narrative_delta: list[NarrativeSectionDelta] = Field(default_factory=list)
    target_findings: list[TargetFinding] = Field(default_factory=list)
    gaps: list[GapSuggestion] = Field(default_factory=list)
    next_question: NextQuestion | None = None
    stage_complete: bool
