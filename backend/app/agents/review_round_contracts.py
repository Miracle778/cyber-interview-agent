from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictReviewRoundOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoundAnswerEvaluation(_StrictReviewRoundOutput):
    score: Literal["poor", "partial", "good"]
    missing_key_points: list[str]
    evidence: str = Field(min_length=1)
    follow_up_required: bool
    follow_up_prompt: str | None
    mastery_suggestion: Literal["weak", "partial", "stable", "strong"]
    project_dimensions: dict[
        Literal[
            "factual_consistency",
            "specificity",
            "structural_completeness",
            "follow_up_resilience",
        ],
        Literal["pending", "basic", "stable", "conflict"],
    ] | None = None
    fact_conflict: str | None = None
    project_mastery: Literal["pending", "basic", "stable"] | None = None

    @model_validator(mode="after")
    def validate_follow_up(self) -> "RoundAnswerEvaluation":
        if self.follow_up_required and not (
            self.follow_up_prompt and self.follow_up_prompt.strip()
        ):
            raise ValueError(
                "follow_up_prompt is required when follow_up_required is true"
            )
        if not self.follow_up_required and self.follow_up_prompt is not None:
            raise ValueError(
                "follow_up_prompt must be null when no follow-up is required"
            )
        if self.fact_conflict:
            self.project_mastery = "pending"
        return self


class ReviewSessionReportOutput(_StrictReviewRoundOutput):
    title: str = Field(min_length=1)
    markdown: str = Field(min_length=1)
    mastery_explanation: str = Field(min_length=1)
