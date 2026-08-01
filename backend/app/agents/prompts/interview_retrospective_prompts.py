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
