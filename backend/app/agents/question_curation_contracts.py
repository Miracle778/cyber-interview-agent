from __future__ import annotations

from collections.abc import Mapping
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
    source_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def deduplicate_raw_source_refs(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        primary = normalized.get("source_ref")
        raw_refs = normalized.get("source_refs")
        if raw_refs is None or raw_refs == []:
            raw_refs = [primary]
        if isinstance(raw_refs, (list, tuple)):
            unique: list[object] = []
            for raw_ref in raw_refs:
                ref = raw_ref.strip() if isinstance(raw_ref, str) else raw_ref
                if ref not in unique:
                    unique.append(ref)
            normalized["source_refs"] = unique
        return normalized

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
        if len(refs) > MAX_QUESTION_SEED_SOURCE_REFS:
            raise ValueError("source refs must contain at most 32 unique refs")
        self.source_ref = primary
        self.source_refs = refs
        return self


class QuestionSeedChunk(_StrictQuestionCurationOutput):
    seeds: list[QuestionSeed] = Field(default_factory=list, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def discard_ungrounded_raw_seeds(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        raw_seeds = value.get("seeds")
        if not isinstance(raw_seeds, (list, tuple)):
            return value
        normalized = dict(value)
        normalized["seeds"] = [
            seed
            for seed in raw_seeds
            if isinstance(seed, QuestionSeed)
            or (
                isinstance(seed, Mapping)
                and isinstance(seed.get("source_ref"), str)
                and bool(seed["source_ref"].strip())
                and (
                    seed.get("source_refs") in (None, [])
                    or (
                        isinstance(seed.get("source_refs"), (list, tuple))
                        and all(
                            isinstance(ref, str) and bool(ref.strip())
                            for ref in seed["source_refs"]
                        )
                    )
                )
            )
        ]
        return normalized


class QuestionCandidateChunk(_StrictQuestionCurationOutput):
    candidates: list[QuestionCandidate] = Field(default_factory=list, max_length=3)


class QuestionCandidateBatch(_StrictQuestionCurationOutput):
    candidates: list[QuestionCandidate] = Field(default_factory=list, max_length=200)


class QuestionRevisionOutput(_StrictQuestionCurationOutput):
    candidate: QuestionCandidate
