import pytest

from app.review.coverage import (
    KeyPointCoverage,
    ReviewCompletionPolicy,
    merge_key_point_coverage,
)
from app.review.models import QuestionSnapshot


REQUIRED = ("事务边界", "幂等处理")


def test_partial_coverage_does_not_complete_question() -> None:
    coverage = merge_key_point_coverage(
        REQUIRED,
        (),
        (KeyPointCoverage(point="事务边界", status="covered"),),
    )

    assert [item.status for item in coverage] == ["covered", "uncovered"]
    assert ReviewCompletionPolicy.can_advance(coverage, skipped=False) is False


def test_coverage_accumulates_without_downgrading_previous_answer() -> None:
    first = merge_key_point_coverage(
        REQUIRED,
        (),
        (KeyPointCoverage(point="事务边界", status="covered", evidence=("第一轮",)),),
    )
    second = merge_key_point_coverage(
        REQUIRED,
        first,
        (
            KeyPointCoverage(point="事务边界", status="partial"),
            KeyPointCoverage(point="幂等处理", status="covered", evidence=("第二轮",)),
        ),
    )

    assert [item.status for item in second] == ["covered", "covered"]
    assert second[0].evidence == ("第一轮",)
    assert ReviewCompletionPolicy.can_advance(second, skipped=False) is True


def test_bonus_points_do_not_block_completion() -> None:
    coverage = merge_key_point_coverage(
        ("必答点",),
        (),
        (KeyPointCoverage(point="必答点", status="covered"),),
    )

    assert ReviewCompletionPolicy.can_advance(coverage, skipped=False) is True


def test_unknown_model_point_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown key point"):
        merge_key_point_coverage(
            REQUIRED,
            (),
            (KeyPointCoverage(point="模型臆造的点", status="covered"),),
        )


def test_explicit_skip_is_the_only_non_coverage_escape_hatch() -> None:
    coverage = merge_key_point_coverage(REQUIRED, (), ())

    assert ReviewCompletionPolicy.can_advance(coverage, skipped=True) is True


def test_legacy_snapshot_key_points_become_required_points() -> None:
    snapshot = QuestionSnapshot(
        question_id="question-1",
        document_id="document-1",
        content_hash="a" * 64,
        title="事务题",
        question_text="如何保证发布幂等？",
        reference_answer="使用稳定幂等键和单题事务。",
        topics=("database",),
        difficulty="medium",
        key_points=REQUIRED,
        follow_ups=(),
    )

    assert snapshot.required_key_points == REQUIRED
    assert snapshot.bonus_key_points == ()
