from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.agents.prompts.prompt_spec import PromptSpec


REVIEW_ROUND_EVALUATION_PROMPT = PromptSpec(
    id="review-round-answer-evaluation",
    version="1.0",
    system=(
        "根据冻结题目、参考答案和关键点评价回答。返回证据、缺失点、是否需要一次"
        "必要追问和 mastery 建议；不得输出隐藏推理。"
    ),
)

REVIEW_ROUND_REPORT_PROMPT = PromptSpec(
    id="review-round-report",
    version="1.0",
    system=(
        "根据结构化 attempts 生成简洁中文轮次报告和 mastery 解释。"
        "不得直接修改 mastery，也不得输出隐藏推理。"
    ),
)

REVIEW_DISCUSSION_PROMPT = PromptSpec(
    id="review-discussion",
    version="1.0",
    system=(
        "围绕给定冻结题目和 attempt 证据深入讨论。只读知识，"
        "不得修改父复习轮次或自动发布内容。"
    ),
)


def render_round_evaluation_input(
    *, question: Mapping[str, Any], answer: str, supplement: str | None
) -> str:
    rendered = (
        f"冻结题目：{json.dumps(dict(question), ensure_ascii=False)}\n"
        f"用户回答：{answer}"
    )
    if supplement:
        rendered += f"\n补充回答：{supplement}"
    return rendered


def render_round_report_input(
    *,
    attempts: tuple[dict[str, Any], ...],
    settings: dict[str, Any],
    prior_reports: tuple[str, ...],
) -> str:
    return json.dumps(
        {
            "attempts": attempts,
            "settings": settings,
            "confirmedPriorReports": prior_reports[-3:],
        },
        ensure_ascii=False,
    )


def render_review_discussion_input(
    *, question: Mapping[str, Any], attempt_evidence: dict[str, Any], message: str
) -> str:
    return json.dumps(
        {
            "question": dict(question),
            "attemptEvidence": attempt_evidence,
            "message": message,
        },
        ensure_ascii=False,
    )
