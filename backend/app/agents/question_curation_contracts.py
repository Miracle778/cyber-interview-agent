from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictQuestionCurationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionCandidate(_StrictQuestionCurationOutput):
    title: str = Field(min_length=1)
    question_text: str = Field(min_length=1)
    reference_answer: str = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    difficulty: Literal["easy", "medium", "hard"]
    key_points: list[str] = Field(min_length=1)
    follow_ups: list[str]
    source_refs: list[str] = Field(min_length=1)
    correction_note: str = Field(min_length=1)


class QuestionCandidateBatch(_StrictQuestionCurationOutput):
    candidates: list[QuestionCandidate] = Field(min_length=1, max_length=50)
