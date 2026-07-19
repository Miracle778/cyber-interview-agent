from __future__ import annotations

from typing import Any

from app.agents.prompts.prompt_spec import PromptSpec


SINGLE_REVIEW_EVALUATION_PROMPT = PromptSpec(
    id="single-review-answer-evaluation",
    version="1.0",
    system=(
        "根据参考答案和关键点评价用户回答。只引用用户回答中的证据，"
        "返回 poor/partial/good、缺失关键点和简短证据。"
    ),
)

SINGLE_REVIEW_REPORT_PROMPT = PromptSpec(
    id="single-review-report",
    version="1.0",
    system=(
        "生成简洁的中文单题复习报告 Markdown，包含问题、评分、回答证据、"
        "缺失点和下一步；不得生成隐藏推理。"
    ),
)


def render_single_evaluation_input(
    *, question: str, reference_answer: str, key_points: tuple[str, ...], user_answer: str
) -> str:
    return (
        f"问题：{question}\n"
        f"参考答案：{reference_answer}\n"
        f"关键点：{', '.join(key_points)}\n"
        f"用户回答：{user_answer}"
    )


def render_single_report_input(
    *, question: str, user_answer: str, evaluation: dict[str, Any]
) -> str:
    return (
        f"问题：{question}\n"
        f"用户回答：{user_answer}\n"
        f"评价：{evaluation}"
    )
