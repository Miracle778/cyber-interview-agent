from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.review import ReviewQuestion


class AnswerEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: Literal["poor", "partial", "good"]
    missing_key_points: list[str]
    evidence: str


class SingleReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: ReviewQuestion
    user_answer: str = Field(min_length=1)


class SingleReviewState(TypedDict, total=False):
    question: dict[str, Any]
    user_answer: str
    evaluation: dict[str, Any]
    report_markdown: str
    report_draft_id: str
    report_draft_version: int
    report_content_hash: str
    action_id: str
    decision: dict[str, Any]
    response: str
