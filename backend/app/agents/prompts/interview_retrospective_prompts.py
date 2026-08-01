from __future__ import annotations

import json

from app.agents.prompts.prompt_spec import PromptSpec


RETROSPECTIVE_CLEANUP_PROMPT = PromptSpec(
    id="interview_retrospective.cleanup",
    version="2026-08-01",
    system=(
        "你是面试记录整理 Agent。只整理当前文字窗口，不补写缺失对话，不把事后回忆"
        "伪装成逐字转写。识别候选人、面试官或未知说话人，保留每个片段在完整原文中的"
        "绝对 sourceStart/sourceEnd。无法可靠判断时必须使用 unknown 并说明原因。不得调用"
        "工具、修改正式资料、总结表现或推断未出现的问答。"
    ),
)


RETROSPECTIVE_QUESTION_EXTRACTION_PROMPT = PromptSpec(
    id="interview_retrospective.question_extraction",
    version="2026-08-02",
    system=(
        "你是面试问题还原 Agent。只能使用输入中的已确认说话人片段，按面试发生顺序"
        "提取问题并关联回答片段。原文明确出现的问题标为 original；只有回答明确暗示"
        "存在某个问题时才可标为 inferred，并给出 inferenceBasis。不得把建议、总结或"
        "常识补充伪装成面试原问题，不得调用工具或输出整场评分。"
    ),
)


RETROSPECTIVE_ANALYSIS_PROMPT = PromptSpec(
    id="interview_retrospective.question_analysis",
    version="2026-08-02",
    system=(
        "你是逐题面试复盘 Agent。只分析当前问题、关联回答片段和冻结的有限上下文。"
        "明确区分原始证据、画像冲突、模型判断和证据不足；所有优点、改进和缺口尽量"
        "绑定证据片段。不得输出思维过程、整场总分、费用或未经证实的事实，不得调用"
        "工具或修改题库、画像、项目资料与 Knowledge。"
    ),
)


def render_cleanup_window(
    *,
    source_kind: str,
    source_start: int,
    source_end: int,
    body: str,
) -> str:
    return json.dumps(
        {
            "sourceKind": source_kind,
            "sourceStart": source_start,
            "sourceEnd": source_end,
            "body": body,
        },
        ensure_ascii=False,
        indent=2,
    )


def render_question_extraction_input(
    *, segments: list[dict[str, object]], context_snapshot: dict[str, object]
) -> str:
    return json.dumps(
        {"contextSnapshot": context_snapshot, "segments": segments},
        ensure_ascii=False,
        indent=2,
    )


def render_question_analysis_input(
    *,
    question: dict[str, object],
    segments: list[dict[str, object]],
    context_snapshot: dict[str, object],
) -> str:
    return json.dumps(
        {
            "contextSnapshot": context_snapshot,
            "question": question,
            "segments": segments,
        },
        ensure_ascii=False,
        indent=2,
    )
