from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionCandidate(StrictAgentOutput):
    title: str = Field(min_length=1)
    question_text: str = Field(min_length=1)
    reference_answer: str = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    difficulty: Literal["easy", "medium", "hard"]
    key_points: list[str] = Field(min_length=1)
    follow_ups: list[str]
    source_refs: list[str] = Field(min_length=1)
    correction_note: str = Field(min_length=1)


class QuestionCandidateBatch(StrictAgentOutput):
    candidates: list[QuestionCandidate] = Field(min_length=1, max_length=50)


class AnswerEvaluationV2(StrictAgentOutput):
    score: Literal["poor", "partial", "good"]
    missing_key_points: list[str]
    evidence: str = Field(min_length=1)
    follow_up_required: bool
    follow_up_prompt: str | None
    mastery_suggestion: Literal["weak", "partial", "stable", "strong"]

    @model_validator(mode="after")
    def validate_follow_up(self) -> "AnswerEvaluationV2":
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
        return self


class FollowUpDecision(StrictAgentOutput):
    required: bool
    prompt: str | None
    reason: str = Field(min_length=1)


class SessionReportOutput(StrictAgentOutput):
    title: str = Field(min_length=1)
    markdown: str = Field(min_length=1)
    mastery_explanation: str = Field(min_length=1)


class ReviewRoundState(TypedDict, total=False):
    round_id: str
    settings: dict
    question_snapshots: list[dict]
    current_index: int
    current_input_request: dict
    current_answer: str
    current_evaluation: dict
    current_follow_up: str
    skipped: bool
    attempt_ids: list[str]
    report_draft_ids: list[str]
    report_drafts: list[dict]
    publication_action_ids: list[str]
    publication_index: int
    publication_decisions: list[dict]
    status: str
    response: str
