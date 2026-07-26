from __future__ import annotations

import re
from typing import Literal, TypeAlias


ReviewTurnIntent: TypeAlias = Literal[
    "answer",
    "show_question",
    "request_hint",
    "reveal_answer",
    "explain",
    "skip",
    "unrelated",
]

_TRAILING_PUNCTUATION = re.compile(r"[\s，。！？!?；;：:～~]+$")


def classify_review_turn(message: str) -> ReviewTurnIntent | None:
    text = _TRAILING_PUNCTUATION.sub("", message.strip()).casefold()
    if not text:
        return None
    if _matches(
        text,
        ("查看原题", "显示原题", "再说一遍题目", "重复题目", "题目是什么"),
    ):
        return "show_question"
    if _matches(text, ("给点提示", "给个提示", "提示一下", "我需要提示")):
        return "request_hint"
    if _matches(
        text,
        ("查看答案", "显示答案", "我想看答案", "告诉我答案", "直接看答案"),
    ):
        return "reveal_answer"
    if _matches(text, ("跳过", "跳过此题", "下一题", "不会这题")):
        return "skip"
    if (
        len(text) <= 40
        and any(marker in text for marker in ("什么意思", "怎么理解", "为什么问", "解释一下"))
    ):
        return "explain"
    if text in {"你好", "嗨", "hello", "hi", "在吗", "谢谢"}:
        return "unrelated"
    if any(marker in text for marker in ("？", "?", "为什么", "怎么", "是否", "吗")):
        return None
    return "answer"


def _matches(text: str, values: tuple[str, ...]) -> bool:
    return text in values or (
        len(text) <= 24 and any(text.startswith(value) for value in values)
    )
