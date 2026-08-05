from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.agents.prompts.prompt_spec import PromptSpec


REVIEW_ROUND_EVALUATION_PROMPT = PromptSpec(
    id="review-round-answer-evaluation",
    version="2.1",
    system=(
        "根据冻结题目、参考答案和必答/加分点评价本次回答。逐项返回已覆盖、"
        "部分覆盖、未覆盖及对应回答证据；只能使用题目中给出的关键点，不能臆造。"
        "covered_key_points、partial_key_points、missing_key_points 中的每一项必须逐字复制"
        "冻结题目的 required_key_points，不得追加括号说明、改写或拆分；解释只写入"
        "evidence_by_point。"
        "仍有待完善关键点时，必须令 follow_up_required=true 且 follow_up_prompt 非空，"
        "follow_up_prompt 只指出仍需完善的方向，不泄露完整答案。"
        "没有待完善关键点时，必须令 follow_up_required=false 且 follow_up_prompt=null。"
        "不要把延伸学习建议写进 follow_up_prompt。不得输出隐藏推理。"
    ),
)

REVIEW_TURN_CLASSIFICATION_PROMPT = PromptSpec(
    id="review-turn-classification",
    version="1.0",
    system=(
        "判断用户在当前复习题中的意图，只返回结构化 intent。"
        "同时包含答案和疑问时优先 answer；只有明确请求重复题目、提示、答案、"
        "解释或跳过时才选择对应意图。不得回答问题。"
    ),
)

PROJECT_ANSWER_EVALUATION_PROMPT = PromptSpec(
    id="project-answer-evaluation",
    version="1.0",
    system=(
        "评价项目经历回答。除通用评分外，必须评价事实一致性、具体程度、"
        "结构完整性和追问承受力。若回答与已确认项目事实冲突，标记 fact_conflict，"
        "project_mastery 必须为 pending；不得自行修改个人画像。"
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


def render_review_turn_classification_input(
    *, question: Mapping[str, Any], message: str
) -> str:
    return json.dumps(
        {"question": dict(question), "message": message},
        ensure_ascii=False,
    )


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
