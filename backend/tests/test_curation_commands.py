import pytest

from app.review.curation_commands import (
    CurationCommandService,
    StaleCurationSummaryError,
)
from app.review.models import CurationSummary
from app.review.curation_command_contracts import (
    CandidateSelector,
    CurationCommandPlan,
)


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


def test_free_intent_can_regenerate_noted_and_publish_the_rest() -> None:
    command = CurationCommandService().resolve_plan(
        plan=CurationCommandPlan(
            publish=CandidateSelector(scope="unnoted"),
            regenerate=CandidateSelector(scope="noted"),
        ),
        summary=_summary(),
        candidates=(
            {"id": "candidate-1", "review_note": "补充异常场景"},
            {"id": "candidate-2", "review_note": ""},
            {"id": "candidate-3", "review_note": ""},
            {"id": "candidate-4", "review_note": ""},
            {"id": "candidate-5", "review_note": ""},
        ),
        current_summary_version=3,
        expected_summary_version=3,
    )

    assert command.kind == "mixed"
    assert command.rewrite_candidate_ids == ("candidate-1",)
    assert command.candidate_ids == (
        "candidate-2",
        "candidate-3",
        "candidate-4",
        "candidate-5",
    )


def test_input_router_separates_safe_questions_from_ambiguous_side_effects() -> None:
    service = CurationCommandService()

    assert service.route_input("为什么推荐这道题？") == "conversation"
    assert service.route_input("请分析这些候选题的优缺点") == "conversation"
    assert service.route_input("给我讲讲这批题") == "conversation"
    assert service.route_input("把合适的处理一下") == "classification"
    assert service.route_input("帮我优化这道题") == "classification"


def test_question_inspection_response_is_deterministic_and_includes_key_points() -> None:
    command = CurationCommandService().resolve_plan(
        plan=CurationCommandPlan(
            inspect=CandidateSelector(scope="explicit", ordinals=[1])
        ),
        summary=_summary(),
        candidates=(
            {
                "id": "candidate-1",
                "ordinal": 1,
                "title": "MVCC 可见性",
                "question": {
                    "question_text": "Read View 如何判断版本可见性？",
                    "reference_answer": "比较事务 ID 与活跃事务集合。",
                    "key_points": ["上下界", "活跃事务集合"],
                    "follow_ups": ["当前读与快照读有什么区别？"],
                },
            },
        ),
        current_summary_version=3,
        expected_summary_version=3,
    )

    assert command.kind == "clarify"
    assert "题目：" in command.clarification
    assert "参考答案：" in command.clarification
    assert "关键点：" in command.clarification
    assert "1. 上下界" in command.clarification
    assert "必要追问：" in command.clarification


def test_deterministic_commands_use_ordinals_and_durable_focus() -> None:
    service = CurationCommandService()

    explicit = service.try_parse("发布第 5 题", _summary(), ())
    focused = service.try_parse(
        "这题发布吧", _summary(), ("candidate-5",)
    )

    assert explicit is not None
    assert explicit.publish.ordinals == [5]
    assert focused is not None
    assert focused.publish.ordinals == [5]


def test_multi_focus_pronoun_clarifies_and_complex_text_uses_model() -> None:
    service = CurationCommandService()

    ambiguous = service.try_parse(
        "这题发布吧", _summary(), ("candidate-2", "candidate-5")
    )

    assert ambiguous is not None
    assert ambiguous.clarification == "当前同时关联多道题，请明确要操作的题号。"
    assert (
        service.try_parse(
            "加了备注的重新生成，其他的发布", _summary(), ()
        )
        is None
    )
