from __future__ import annotations

import json
from collections.abc import Sequence

from app.agents.prompts.prompt_spec import PromptSpec
from app.agents.question_curation_contracts import QuestionSeed
from app.review.curation_sections import SourceSection


QUESTION_DISCOVERY_PROMPT = PromptSpec(
    id="question-discovery",
    version="2.0",
    system=(
        "从给定的有界来源片段中识别值得复习的独立中文面试题。每个片段最多返回一个题目种子，"
        "最多返回 6 个；只输出 question_text 和原样 source_ref，不得编造引用，不补全答案。"
    ),
)
QUESTION_ENRICHMENT_PROMPT = PromptSpec(
    id="question-enrichment",
    version="2.0",
    system=(
        "把不超过 3 个题目种子补全为可复习的中文面试题候选。纠正明显错误，填写标题、参考答案、"
        "topic、难度、关键点、必要追问和简短修正说明。每个候选必须且只能保留对应种子的 source_ref；"
        "不得自动发布。"
    ),
)
QUESTION_REVISION_PROMPT = PromptSpec(
    id="question-revision",
    version="2.0",
    system=(
        "根据来源和重写要求只修订一个中文面试题候选，返回 exactly one candidate。"
        "保留可验证来源引用，不得自动发布。"
    ),
)

# Compatibility prompt retained for module-structure consumers during rollout.
QUESTION_CURATION_PROMPT = PromptSpec(
    id="question-curation",
    version="1.0",
    system=QUESTION_ENRICHMENT_PROMPT.system,
)


def _section_rows(sections: Sequence[SourceSection]) -> list[str]:
    return [
        f"[{section.ref}] sha256={section.digest}\n{section.text}"
        for section in sections
    ]


def render_question_discovery_input(sections: Sequence[SourceSection]) -> str:
    return "来源片段：\n\n" + "\n\n".join(_section_rows(sections))


def render_question_enrichment_input(
    seeds: Sequence[QuestionSeed],
    *,
    sections: Sequence[SourceSection],
    known_questions: Sequence[str],
) -> str:
    body = [
        "题目种子：",
        json.dumps([seed.model_dump() for seed in seeds], ensure_ascii=False),
        "对应来源：",
        *_section_rows(sections),
    ]
    if known_questions:
        body.extend(("现有相似题：", *known_questions))
    return "\n\n".join(body)


def render_question_revision_input(
    source_excerpts: Sequence[str], *, rewrite_feedback: str
) -> str:
    return "\n\n".join(
        ("来源：", *source_excerpts, "重写要求：", rewrite_feedback)
    )


def render_question_curation_input(
    source_unit: tuple[str, ...],
    *,
    known_questions: tuple[str, ...],
    rewrite_feedback: str | None,
) -> str:
    """Compatibility renderer retained for old callers outside the new graph."""
    body = ["来源：", *source_unit]
    if known_questions:
        body.extend(("现有相似题：", *known_questions))
    if rewrite_feedback:
        body.extend(("重写要求：", rewrite_feedback))
    return "\n".join(body)
