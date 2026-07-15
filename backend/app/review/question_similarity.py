from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from difflib import SequenceMatcher


_BOILERPLATE = re.compile(
    r"请问|请解释一下|请解释|解释一下|什么是|是什么|谈谈|简述|如何理解"
)
_NON_WORD = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")


def canonical_question(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return _NON_WORD.sub("", _BOILERPLATE.sub("", normalized))


def question_similarity(left: str, right: str) -> float:
    left_key = canonical_question(left)
    right_key = canonical_question(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    sequence = SequenceMatcher(None, left_key, right_key).ratio()
    left_grams = _bigrams(left_key)
    right_grams = _bigrams(right_key)
    overlap = len(left_grams & right_grams) / len(left_grams | right_grams)
    return max(sequence, overlap)


def same_question(
    left: str,
    right: str,
    *,
    left_topics: Iterable[str] = (),
    right_topics: Iterable[str] = (),
    threshold: float = 0.9,
) -> bool:
    left_topic_set = {item.casefold() for item in left_topics}
    right_topic_set = {item.casefold() for item in right_topics}
    if left_topic_set and right_topic_set and left_topic_set.isdisjoint(right_topic_set):
        return False
    return question_similarity(left, right) >= threshold


def _bigrams(value: str) -> set[str]:
    if len(value) < 2:
        return {value}
    return {value[index : index + 2] for index in range(len(value) - 1)}
