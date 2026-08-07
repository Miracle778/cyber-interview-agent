from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.review.question_similarity import question_similarity


class DraftGoldDatasetError(ValueError):
    """Raised when a provisional annotation set is used as a formal score."""


@dataclass(frozen=True, slots=True)
class QuestionCurationRecallReport:
    dataset_id: str
    provisional: bool
    total: int
    matched: int
    recall: float
    explicit_recall: float
    implicit_recall: float
    critical_recall: float
    missing_ids: tuple[str, ...]
    duplicate_candidate_count: int
    unanchored_candidate_count: int


@dataclass(frozen=True, slots=True)
class _GoldQuestion:
    id: str
    text: str
    kind: str
    refs: frozenset[str]
    critical: bool


@dataclass(frozen=True, slots=True)
class _Candidate:
    text: str
    refs: frozenset[str]


def evaluate_question_curation_recall(
    gold: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    allow_draft: bool = False,
) -> QuestionCurationRecallReport:
    """Compare one frozen curation result with a human-reviewed question set.

    Source anchors are the primary identity because generated wording may change.
    Matching is one-to-one so duplicated candidates cannot inflate recall.
    """

    provisional = str(gold.get("status", "")) != "confirmed"
    if provisional and not allow_draft:
        raise DraftGoldDatasetError(
            "question curation Gold dataset must be confirmed before formal scoring"
        )
    expected = tuple(_gold_question(item) for item in gold.get("expectedQuestions", []))
    actual = tuple(_candidate(item) for item in candidates)

    scores = sorted(
        (
            (_match_score(expected_item, candidate), expected_index, candidate_index)
            for expected_index, expected_item in enumerate(expected)
            for candidate_index, candidate in enumerate(actual)
        ),
        reverse=True,
    )
    matched_expected: set[int] = set()
    matched_candidates: set[int] = set()
    for score, expected_index, candidate_index in scores:
        if score <= 0:
            break
        if expected_index in matched_expected or candidate_index in matched_candidates:
            continue
        matched_expected.add(expected_index)
        matched_candidates.add(candidate_index)

    duplicate_count = sum(
        candidate_index not in matched_candidates
        and any(
            expected_index in matched_expected
            and _match_score(expected_item, candidate) > 0
            for expected_index, expected_item in enumerate(expected)
        )
        for candidate_index, candidate in enumerate(actual)
    )
    return QuestionCurationRecallReport(
        dataset_id=str(gold.get("datasetId", "unknown")),
        provisional=provisional,
        total=len(expected),
        matched=len(matched_expected),
        recall=_ratio(len(matched_expected), len(expected)),
        explicit_recall=_subset_recall(expected, matched_expected, kind="explicit"),
        implicit_recall=_subset_recall(expected, matched_expected, kind="implicit"),
        critical_recall=_subset_recall(expected, matched_expected, critical=True),
        missing_ids=tuple(
            item.id for index, item in enumerate(expected) if index not in matched_expected
        ),
        duplicate_candidate_count=duplicate_count,
        unanchored_candidate_count=sum(not item.refs for item in actual),
    )


def _gold_question(value: dict[str, Any]) -> _GoldQuestion:
    return _GoldQuestion(
        id=str(value["id"]),
        text=str(value["question"]),
        kind=str(value.get("kind", "unknown")),
        refs=frozenset(str(item) for item in value.get("sourceRefs", [])),
        critical=bool(value.get("critical", False)),
    )


def _candidate(value: dict[str, Any]) -> _Candidate:
    text = value.get("questionText", value.get("question_text", value.get("title", "")))
    refs = value.get("sourceRefs", value.get("source_refs", []))
    return _Candidate(str(text), frozenset(str(item) for item in refs))


def _match_score(expected: _GoldQuestion, candidate: _Candidate) -> float:
    similarity = question_similarity(expected.text, candidate.text)
    if expected.refs and candidate.refs and expected.refs.intersection(candidate.refs):
        return 1.0 + similarity
    return similarity if similarity >= 0.9 else 0.0


def _subset_recall(
    expected: tuple[_GoldQuestion, ...],
    matched: set[int],
    *,
    kind: str | None = None,
    critical: bool | None = None,
) -> float:
    indexes = [
        index
        for index, item in enumerate(expected)
        if (kind is None or item.kind == kind)
        and (critical is None or item.critical is critical)
    ]
    return _ratio(sum(index in matched for index in indexes), len(indexes))


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else round(numerator / denominator, 4)
