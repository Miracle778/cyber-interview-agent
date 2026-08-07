from __future__ import annotations

import pytest

from app.evaluation.question_curation_recall import (
    DraftGoldDatasetError,
    evaluate_question_curation_recall,
)


def gold_dataset(*, status: str = "confirmed") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "datasetId": "java-v1",
        "status": status,
        "expectedQuestions": [
            {
                "id": "java-001",
                "question": "HashMap 的底层实现是什么？",
                "kind": "explicit",
                "sourceRefs": ["source#section-0001"],
                "critical": True,
                "reviewStatus": "confirmed",
            },
            {
                "id": "java-002",
                "question": "项目中遇到过哪些难题？",
                "kind": "implicit",
                "sourceRefs": ["source#section-0002"],
                "critical": False,
                "reviewStatus": "confirmed",
            },
        ],
    }


def test_recall_evaluator_reports_total_explicit_implicit_and_critical_recall() -> None:
    report = evaluate_question_curation_recall(
        gold_dataset(),
        [{
            "questionText": "HashMap 的 put 和扩容过程是什么？",
            "sourceRefs": ["source#section-0001"],
        }],
    )

    assert report.total == 2
    assert report.matched == 1
    assert report.recall == 0.5
    assert report.explicit_recall == 1.0
    assert report.implicit_recall == 0.0
    assert report.critical_recall == 1.0
    assert report.missing_ids == ("java-002",)


def test_recall_evaluator_uses_one_to_one_matching_for_duplicate_candidates() -> None:
    report = evaluate_question_curation_recall(
        gold_dataset(),
        [
            {"questionText": "HashMap 是什么？", "sourceRefs": ["source#section-0001"]},
            {"questionText": "HashMap 如何实现？", "sourceRefs": ["source#section-0001"]},
        ],
    )

    assert report.matched == 1
    assert report.duplicate_candidate_count == 1


def test_recall_evaluator_rejects_unconfirmed_gold_by_default() -> None:
    with pytest.raises(DraftGoldDatasetError):
        evaluate_question_curation_recall(
            gold_dataset(status="draft_requires_human_review"), []
        )

    provisional = evaluate_question_curation_recall(
        gold_dataset(status="draft_requires_human_review"),
        [],
        allow_draft=True,
    )
    assert provisional.provisional is True
