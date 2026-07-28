import pytest

from app.review.turn_intent import classify_review_turn


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("查看原题", "show_question"),
        ("再说一遍题目", "show_question"),
        ("给点提示", "request_hint"),
        ("我想看答案", "reveal_answer"),
        ("跳过此题", "skip"),
        ("这道题是什么意思？", "explain"),
        ("你好", "unrelated"),
    ],
)
def test_high_confidence_review_commands(message: str, expected: str) -> None:
    assert classify_review_turn(message) == expected


def test_plain_answer_is_classified_without_an_extra_model_call() -> None:
    assert classify_review_turn("MVCC 通过版本链判断可见性") == "answer"
    assert classify_review_turn("事务边界和幂等处理") == "answer"


def test_mixed_answer_and_question_is_left_for_structured_classification() -> None:
    assert classify_review_turn("我认为先检查幂等键，不过这里为什么还需要事务？") is None
