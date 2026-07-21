from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MAX_QUESTION_SEED_SOURCE_REFS = 32


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


class QuestionSeed(_StrictQuestionCurationOutput):
    question_text: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    source_refs: list[str] = Field(
        default_factory=list, max_length=MAX_QUESTION_SEED_SOURCE_REFS
    )

    @model_validator(mode="after")
    def normalize_source_refs(self) -> "QuestionSeed":
        primary = self.source_ref.strip()
        refs = [ref.strip() for ref in self.source_refs]
        if not primary or any(not ref for ref in refs):
            raise ValueError("source refs must not be blank")
        if not refs:
            refs = [primary]
        if refs[0] != primary:
            raise ValueError("primary source ref must be first")
        self.source_ref = primary
        self.source_refs = list(dict.fromkeys(refs))
        return self


class QuestionSeedChunk(_StrictQuestionCurationOutput):
    seeds: list[QuestionSeed] = Field(default_factory=list, max_length=20)


class QuestionCandidateChunk(_StrictQuestionCurationOutput):
    candidates: list[QuestionCandidate] = Field(default_factory=list, max_length=3)


class QuestionCandidateBatch(_StrictQuestionCurationOutput):
    candidates: list[QuestionCandidate] = Field(default_factory=list, max_length=200)


class QuestionRevisionOutput(_StrictQuestionCurationOutput):
    candidate: QuestionCandidate
