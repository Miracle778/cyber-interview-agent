import pytest

from app.review.curation_commands import (
    CurationCommandService,
    StaleCurationSummaryError,
)
from app.review.models import CurationSummary


def _summary() -> CurationSummary:
    return CurationSummary(
        items=(
            {
                "ordinal": 1,
                "candidateId": "candidate-1",
                "recommendation": "recommend_confirm",
            },
            {
                "ordinal": 2,
                "candidateId": "candidate-2",
                "recommendation": "suggest_reject",
            },
            {
                "ordinal": 3,
                "candidateId": "candidate-3",
                "recommendation": "recommend_confirm",
            },
            {
                "ordinal": 4,
                "candidateId": "candidate-4",
                "recommendation": "suggest_edit",
            },
            {
                "ordinal": 5,
                "candidateId": "candidate-5",
                "recommendation": "recommend_confirm",
            },
        )
    )


@pytest.mark.parametrize("text", ["确认所有推荐题", "确认全部推荐题"])
def test_confirm_recommended_resolves_stable_candidate_ids(text: str) -> None:
    command = CurationCommandService().parse(
        text=text,
        summary=_summary(),
        current_summary_version=3,
        expected_summary_version=3,
    )

    assert command.kind == "confirm"
    assert command.candidate_ids == (
        "candidate-1",
        "candidate-3",
        "candidate-5",
    )


def test_partial_confirm_and_reject_resolve_summary_ordinals() -> None:
    service = CurationCommandService()

    confirmed = service.parse(
        text="确认 1、3、5",
        summary=_summary(),
        current_summary_version=3,
        expected_summary_version=3,
    )
    rejected = service.parse(
        text="拒绝第 2 题",
        summary=_summary(),
        current_summary_version=3,
        expected_summary_version=3,
    )

    assert confirmed.candidate_ids == (
        "candidate-1",
        "candidate-3",
        "candidate-5",
    )
    assert rejected.kind == "reject"
    assert rejected.candidate_ids == ("candidate-2",)


def test_rewrite_and_resummarize_are_bounded_commands() -> None:
    service = CurationCommandService()

    rewrite = service.parse(
        text="重写第 4 题：补充边界条件",
        summary=_summary(),
        current_summary_version=3,
        expected_summary_version=3,
    )
    resummarize = service.parse(
        text="重新总结",
        summary=_summary(),
        current_summary_version=3,
        expected_summary_version=3,
    )

    assert rewrite.kind == "rewrite"
    assert rewrite.candidate_ids == ("candidate-4",)
    assert rewrite.feedback == "补充边界条件"
    assert resummarize.kind == "resummarize"
    assert resummarize.candidate_ids == ()


def test_ambiguous_text_returns_clarification_without_targets() -> None:
    command = CurationCommandService().parse(
        text="看着办",
        summary=_summary(),
        current_summary_version=3,
        expected_summary_version=3,
    )

    assert command.kind == "clarify"
    assert command.candidate_ids == ()
    assert "确认" in command.clarification


def test_stale_summary_version_is_rejected_before_target_resolution() -> None:
    with pytest.raises(StaleCurationSummaryError):
        CurationCommandService().parse(
            text="确认全部推荐题",
            summary=_summary(),
            current_summary_version=4,
            expected_summary_version=3,
        )
