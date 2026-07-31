from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.agents.question_curation_contracts import (
    ProviderQuestionCandidate,
    ProviderQuestionCandidateChunk,
    QuestionCandidate,
)
from app.review.models import CurationSeedTaskRecord


@dataclass(frozen=True, slots=True)
class NormalizedSeedOutcome:
    seed_task_id: str
    status: Literal["completed", "degraded", "retryable"]
    candidate: dict[str, object] | None
    answer_basis: Literal["source", "mixed", "model", "unknown"]
    material_support: Literal["sufficient", "partial", "minimal", "unknown"]
    needs_review: bool
    normalization_issues: tuple[str, ...]
    source_answer: str | None
    supplemental_answer: str | None
    error_code: str | None


_DIFFICULTIES = {
    "easy": "easy",
    "简单": "easy",
    "容易": "easy",
    "beginner": "easy",
    "medium": "medium",
    "中等": "medium",
    "一般": "medium",
    "normal": "medium",
    "hard": "hard",
    "困难": "hard",
    "难": "hard",
    "advanced": "hard",
}


def normalize_provider_candidate_observation(
    observation: object,
    *,
    seed_tasks: tuple[CurationSeedTaskRecord, ...],
) -> tuple[NormalizedSeedOutcome, ...]:
    """Turn untrusted Provider output into one deterministic result per Seed Task."""
    try:
        if isinstance(observation, BaseModel):
            observation = observation.model_dump()
        chunk = ProviderQuestionCandidateChunk.model_validate(observation)
    except (ValidationError, TypeError, ValueError):
        return tuple(
            _retryable(task, "invalid_provider_response") for task in seed_tasks
        )

    by_key = {task.seed_key: task for task in seed_tasks}
    by_primary: dict[str, list[CurationSeedTaskRecord]] = {}
    by_question: dict[str, list[CurationSeedTaskRecord]] = {}
    for task in seed_tasks:
        by_primary.setdefault(task.primary_source_ref, []).append(task)
        by_question.setdefault(_question_key(task.question_text), []).append(task)

    associated: dict[str, list[ProviderQuestionCandidate]] = {}
    for item in chunk.candidates:
        task = _associate(item, by_key, by_primary, by_question)
        if task is not None:
            associated.setdefault(task.id, []).append(item)

    outcomes: list[NormalizedSeedOutcome] = []
    for task in seed_tasks:
        items = associated.get(task.id, [])
        if not items:
            outcomes.append(_retryable(task, "missing_candidate"))
            continue
        selected: NormalizedSeedOutcome | None = None
        retry: NormalizedSeedOutcome | None = None
        for item in items:
            outcome = _normalize_one(item, task)
            if outcome.status != "retryable":
                selected = outcome
                break
            retry = retry or outcome
        if selected is None:
            outcomes.append(retry or _retryable(task, "invalid_candidate"))
            continue
        if len(items) > 1:
            issues = (*selected.normalization_issues, "duplicate_candidate")
            selected = NormalizedSeedOutcome(
                seed_task_id=selected.seed_task_id,
                status="degraded",
                candidate=selected.candidate,
                answer_basis=selected.answer_basis,
                material_support=selected.material_support,
                needs_review=True,
                normalization_issues=issues,
                source_answer=selected.source_answer,
                supplemental_answer=selected.supplemental_answer,
                error_code=None,
            )
        outcomes.append(selected)
    return tuple(outcomes)


def _associate(
    item: ProviderQuestionCandidate,
    by_key: dict[str, CurationSeedTaskRecord],
    by_primary: dict[str, list[CurationSeedTaskRecord]],
    by_question: dict[str, list[CurationSeedTaskRecord]],
) -> CurationSeedTaskRecord | None:
    key = (item.seed_key or "").strip()
    if key in by_key:
        return by_key[key]
    refs, _changed = _strings(item.source_refs)
    primary_matches = {
        task.id: task
        for ref in refs
        for task in by_primary.get(ref, ())
    }
    if len(primary_matches) == 1:
        return next(iter(primary_matches.values()))
    question_matches = by_question.get(_question_key(item.question_text or ""), ())
    if len(question_matches) == 1:
        return question_matches[0]
    return None


def _normalize_one(
    item: ProviderQuestionCandidate, task: CurationSeedTaskRecord
) -> NormalizedSeedOutcome:
    issues: list[str] = []
    key = (item.seed_key or "").strip()
    if not key:
        issues.append("seed_key_missing")
    elif key != task.seed_key:
        issues.append("seed_key_invalid")

    refs, refs_changed = _strings(item.source_refs)
    expected_refs = list(task.source_refs)
    if not refs:
        issues.append("source_refs_restored")
    elif any(ref not in expected_refs for ref in refs):
        return _retryable(task, "untrusted_source_refs", (*issues, "source_refs_invalid"))
    elif refs != expected_refs:
        issues.append("source_refs_restored")
    elif refs_changed:
        issues.append("source_refs_normalized")

    question_text = (item.question_text or "").strip()
    if not question_text:
        question_text = task.question_text
        issues.append("question_defaulted")
    title = (item.title or "").strip()
    if not title:
        title = question_text
        issues.append("title_defaulted")

    source_answer = (item.source_answer or "").strip()
    supplemental_answer = (item.supplemental_answer or "").strip()
    legacy_answer = (item.reference_answer or "").strip()
    if source_answer and supplemental_answer:
        answer_basis: Literal["source", "mixed", "model", "unknown"] = "mixed"
        material_support: Literal["sufficient", "partial", "minimal", "unknown"] = "partial"
        reference_answer = f"{source_answer}\n\n{supplemental_answer}"
        issues.append("supplemental_answer_present")
    elif source_answer:
        answer_basis = "source"
        material_support = "sufficient"
        reference_answer = source_answer
    elif supplemental_answer:
        answer_basis = "model"
        material_support = "minimal"
        reference_answer = supplemental_answer
        issues.append("model_only_answer")
    elif legacy_answer:
        answer_basis = "unknown"
        material_support = "unknown"
        reference_answer = legacy_answer
        issues.append("answer_basis_undeclared")
    else:
        return _retryable(task, "missing_answer", (*issues, "missing_answer"))

    topics, topics_changed = _strings(item.topics)
    if not topics:
        topics = ["未分类"]
        issues.append("topics_defaulted")
    elif topics_changed:
        issues.append("topics_normalized")

    raw_difficulty = (item.difficulty or "").strip().casefold()
    difficulty = _DIFFICULTIES.get(raw_difficulty)
    if difficulty is None:
        difficulty = "medium"
        issues.append("difficulty_defaulted")
    elif raw_difficulty != difficulty:
        issues.append("difficulty_mapped")

    required_key_points, required_changed = _strings(item.required_key_points)
    bonus_key_points, bonus_changed = _strings(item.bonus_key_points)
    key_points, key_points_changed = _strings(item.key_points)
    if required_key_points:
        key_points = list(dict.fromkeys((*required_key_points, *bonus_key_points)))
        key_points_changed = key_points_changed or required_changed or bonus_changed
    else:
        required_key_points = key_points
    if not key_points:
        return _retryable(task, "missing_key_points", (*issues, "missing_key_points"))
    if key_points_changed:
        issues.append("key_points_normalized")

    follow_ups, follow_ups_changed = _strings(item.follow_ups)
    if item.follow_ups is None:
        issues.append("follow_ups_defaulted")
    elif follow_ups_changed:
        issues.append("follow_ups_normalized")

    correction_note = (item.correction_note or "").strip()
    if not correction_note:
        correction_note = "未发现需要修正的明显错误"
        issues.append("correction_note_defaulted")

    candidate = QuestionCandidate(
        title=title,
        question_text=question_text,
        reference_answer=reference_answer,
        topics=topics,
        difficulty=difficulty,
        key_points=key_points,
        required_key_points=required_key_points,
        bonus_key_points=bonus_key_points,
        follow_ups=follow_ups,
        source_refs=expected_refs,
        correction_note=correction_note,
    )
    needs_review = answer_basis != "source" or bool(issues)
    return NormalizedSeedOutcome(
        seed_task_id=task.id,
        status="degraded" if needs_review else "completed",
        candidate=candidate.model_dump(mode="json"),
        answer_basis=answer_basis,
        material_support=material_support,
        needs_review=needs_review,
        normalization_issues=tuple(issues),
        source_answer=source_answer or None,
        supplemental_answer=supplemental_answer or None,
        error_code=None,
    )


def _retryable(
    task: CurationSeedTaskRecord,
    error_code: str,
    issues: tuple[str, ...] | None = None,
) -> NormalizedSeedOutcome:
    return NormalizedSeedOutcome(
        seed_task_id=task.id,
        status="retryable",
        candidate=None,
        answer_basis="unknown",
        material_support="unknown",
        needs_review=True,
        normalization_issues=issues or (error_code,),
        source_answer=None,
        supplemental_answer=None,
        error_code=error_code,
    )


def _strings(value: str | list[str | None] | None) -> tuple[list[str], bool]:
    raw = [value] if isinstance(value, str) else list(value or ())
    normalized: list[str] = []
    for item in raw:
        text = (item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized, not isinstance(value, list) or raw != normalized


def _question_key(value: str) -> str:
    return re.sub(r"[\s？?。！!，,、：:；;]+", "", value).casefold()
