from __future__ import annotations

from app.agents.prompts.prompt_spec import PromptSpec


QUESTION_CURATION_PROMPT = PromptSpec(
    id="question-curation",
    version="1.0",
    system=(
        "把给定来源整理为可复习的中文面试题候选。纠正明显错误，保留来源引用，"
        "标注 topic、难度、关键点、必要追问和简短修正说明。"
        "来源中每个清晰可辨的独立题目都必须分别生成一个候选；不得任意合并、"
        "抽样或只挑代表题。若来源明确列出 N 道题，必须返回 N 个 candidates。"
        "不得自动发布。"
    ),
)


def render_question_curation_input(
    source_unit: tuple[str, ...],
    *,
    known_questions: tuple[str, ...],
    rewrite_feedback: str | None,
) -> str:
    body = ["来源：", *source_unit]
    if known_questions:
        body.extend(("现有相似题：", *known_questions))
    if rewrite_feedback:
        body.extend(("重写要求：", rewrite_feedback))
    return "\n".join(body)
