from __future__ import annotations

import json
from collections.abc import Sequence

from app.agents.prompts.prompt_spec import PromptSpec
from app.agents.question_curation_contracts import QuestionSeed
from app.review.curation_sections import SourceSection
from app.review.models import CurationSeedTaskRecord


QUESTION_DISCOVERY_PROMPT = PromptSpec(
    id="question-discovery",
    version="3.1",
    system=(
        "从当前窗口的有界来源片段中识别值得复习的独立中文面试题，最多返回 20 个轻量题目种子。"
        "只输出 question_text、主锚点 source_ref 和有序 source_refs，不补全答案。主锚点必须是"
        "source_refs 第一项；每个引用都必须原样来自当前窗口，不得编造、跨来源或重复引用。"
        "即使当前片段没有题目，也必须按结构化协议返回空 seeds；不得只返回解释文字。"
    ),
)
QUESTION_ENRICHMENT_PROMPT = PromptSpec(
    id="question-enrichment",
    version="4.0",
    system=(
        "把不超过 3 个题目种子补全为可复习的中文面试题候选。每个候选必须原样回显 seed_key，"
        "把材料直接支持的答案写入 source_answer，把通用知识补充写入 supplemental_answer；不要混写。"
        "纠正明显错误，填写标题、topic、难度、关键点、必要追问和简短修正说明。每个候选必须保留"
        "对应种子的全部有序引用，且 source_refs 第一项仍是主锚点；"
        "不得自动发布。"
    ),
)
QUESTION_REVISION_PROMPT = PromptSpec(
    id="question-revision",
    version="3.0",
    system=(
        "根据来源和重写要求只修订一个中文面试题候选，在 candidates 中返回 exactly one candidate。"
        "原样回显 seed_key；把材料直接支持的答案写入 source_answer，把通用知识补充写入 "
        "supplemental_answer。保留权威来源引用，不得增加引用或自动发布。"
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
    seeds: Sequence[QuestionSeed | CurationSeedTaskRecord],
    *,
    sections: Sequence[SourceSection],
    known_questions: Sequence[str],
) -> str:
    body = [
        "题目种子：",
        json.dumps([_seed_row(seed) for seed in seeds], ensure_ascii=False),
        "对应来源：",
        *_section_rows(sections),
    ]
    if known_questions:
        body.extend(("现有相似题：", *known_questions))
    return "\n\n".join(body)


def _seed_row(seed: QuestionSeed | CurationSeedTaskRecord) -> dict[str, object]:
    if isinstance(seed, CurationSeedTaskRecord):
        return {
            "seed_key": seed.seed_key,
            "question_text": seed.question_text,
            "source_ref": seed.primary_source_ref,
            "source_refs": list(seed.source_refs),
        }
    return seed.model_dump()


def render_question_revision_input(
    source_excerpts: Sequence[str],
    *,
    rewrite_feedback: str,
    seed: CurationSeedTaskRecord | None = None,
) -> str:
    body = ["来源：", *source_excerpts]
    if seed is not None:
        body.extend((
            "权威题目种子：",
            json.dumps(_seed_row(seed), ensure_ascii=False),
        ))
    body.extend(("重写要求：", rewrite_feedback))
    return "\n\n".join(body)


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
