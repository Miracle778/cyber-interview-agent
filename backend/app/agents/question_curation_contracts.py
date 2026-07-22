from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


MAX_QUESTION_SEED_SOURCE_REFS = 32


class _StrictQuestionCurationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ProviderQuestionCurationOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")


ProviderStringList: TypeAlias = str | list[str | None] | None


class ProviderQuestionSeed(_ProviderQuestionCurationOutput):
    question_text: str | None = None
    source_ref: str | None = None
    source_refs: ProviderStringList = None


class ProviderQuestionSeedChunk(_ProviderQuestionCurationOutput):
    seeds: list[ProviderQuestionSeed] = Field(default_factory=list)


class ProviderQuestionCandidate(_ProviderQuestionCurationOutput):
    seed_key: str | None = None
    title: str | None = None
    question_text: str | None = None
    source_answer: str | None = None
    supplemental_answer: str | None = None
    # Kept only as a compatibility observation for pre-R3 Provider output.
    reference_answer: str | None = None
    topics: ProviderStringList = None
    difficulty: str | None = None
    key_points: ProviderStringList = None
    follow_ups: ProviderStringList = None
    source_refs: ProviderStringList = None
    correction_note: str | None = None


class ProviderQuestionCandidateChunk(_ProviderQuestionCurationOutput):
    candidates: list[ProviderQuestionCandidate] = Field(default_factory=list)


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


def normalize_provider_seed_chunk(value: object) -> QuestionSeedChunk:
    if isinstance(value, BaseModel):
        value = value.model_dump()
    raw = ProviderQuestionSeedChunk.model_validate(value)
    seeds: list[QuestionSeed] = []
    for item in raw.seeds[:20]:
        question_text = (item.question_text or "").strip()
        primary = (item.source_ref or "").strip()
        if not question_text or not primary:
            continue
        secondary_refs: list[str] = []
        for raw_ref in _provider_values(item.source_refs):
            ref = (raw_ref or "").strip()
            if not ref or ref == primary or ref in secondary_refs:
                continue
            secondary_refs.append(ref)
        seeds.append(
            QuestionSeed(
                question_text=question_text,
                source_ref=primary,
                source_refs=[primary, *secondary_refs][
                    :MAX_QUESTION_SEED_SOURCE_REFS
                ],
            )
        )
    return QuestionSeedChunk(seeds=seeds)


def normalize_provider_candidate_chunk(
    value: object,
    *,
    seed_source_refs: Mapping[str, Sequence[str]],
) -> QuestionCandidateChunk:
    if isinstance(value, BaseModel):
        value = value.model_dump()
    raw = ProviderQuestionCandidateChunk.model_validate(value)
    candidates: list[QuestionCandidate] = []
    seen_primary_refs: set[str] = set()
    for item in raw.candidates[:3]:
        provider_refs: list[str] = []
        for raw_ref in _provider_values(item.source_refs):
            ref = (raw_ref or "").strip()
            if ref and ref not in provider_refs:
                provider_refs.append(ref)
        if not provider_refs:
            continue
        primary_refs = [
            ref for ref in provider_refs if ref in seed_source_refs
        ]
        if len(primary_refs) != 1:
            raise ValueError("question enrichment returned an unknown source ref")
        primary = primary_refs[0]
        expected_refs = tuple(seed_source_refs.get(primary, ()))
        if not expected_refs or any(
            ref not in expected_refs for ref in provider_refs
        ):
            raise ValueError("question enrichment returned an unknown source ref")
        if primary in seen_primary_refs:
            continue

        question_text = (item.question_text or "").strip()
        reference_answer = (item.reference_answer or "").strip()
        key_points = _non_blank_strings(item.key_points)
        if (
            not question_text
            or not reference_answer
            or item.difficulty not in {"easy", "medium", "hard"}
            or not key_points
        ):
            continue
        seen_primary_refs.add(primary)
        candidates.append(
            QuestionCandidate(
                title=(item.title or "").strip() or question_text,
                question_text=question_text,
                reference_answer=reference_answer,
                topics=_non_blank_strings(item.topics) or ["未分类"],
                difficulty=item.difficulty,
                key_points=key_points,
                follow_ups=_non_blank_strings(item.follow_ups),
                source_refs=list(expected_refs),
                correction_note=(item.correction_note or "").strip()
                or "未发现需要修正的明显错误",
            )
        )
    return QuestionCandidateChunk(candidates=candidates)


def _non_blank_strings(values: ProviderStringList) -> list[str]:
    normalized: list[str] = []
    for value in _provider_values(values):
        text = (value or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _provider_values(values: ProviderStringList) -> Sequence[str | None]:
    return [values] if isinstance(values, str) else values or ()


class QuestionCandidateChunk(_StrictQuestionCurationOutput):
    candidates: list[QuestionCandidate] = Field(default_factory=list, max_length=3)


class QuestionCandidateBatch(_StrictQuestionCurationOutput):
    candidates: list[QuestionCandidate] = Field(default_factory=list, max_length=200)


class QuestionRevisionOutput(_StrictQuestionCurationOutput):
    candidate: QuestionCandidate
