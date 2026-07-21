from __future__ import annotations

import json
from collections.abc import Sequence

from app.agents.prompts.prompt_spec import PromptSpec


PROFILE_EXTRACTION_PROMPT = PromptSpec(
    id="profile-extraction",
    version="1.0",
    system=(
        "你是个人画像证据提取 Agent。只能根据输入的 Evidence 产生结构化 Claim "
        "候选；每个候选必须引用输入中的精确 Evidence ID。不得推测缺失事实、不得修改"
        "画像、不得发布知识，也不得请求或调用工具。"
    ),
)

PROFILE_ASSESSMENT_PROMPT = PromptSpec(
    id="profile-assessment",
    version="1.0",
    system=(
        "你是个人画像评估 Agent。基于服务端提供的已确认画像快照生成结构化评估、"
        "优势、缺口、风险和有证据的建议。不得直接创建正式 Claim，不得调用工具。"
    ),
)

PROFILE_CHAT_PROMPT = PromptSpec(
    id="profile-chat",
    version="1.0",
    system=(
        "你是个人画像对话 Agent。回答必须基于当前画像事实和获准的只读工具；"
        "不能修改画像、删除材料或发布知识。证据不足时明确说明或请求澄清。"
    ),
)

PROFILE_ACTION_PLANNER_PROMPT = PromptSpec(
    id="profile-action-planner",
    version="1.0",
    system=(
        "你是受约束的个人画像计划 Agent。只输出允许操作组成的结构化计划，"
        "不执行任何写入、代码、任意路径访问或发布动作。"
    ),
)


def render_profile_extraction_input(evidence: Sequence[dict[str, object]]) -> str:
    return "Evidence（只能引用其中 ID）：\n" + _json(evidence)


def render_profile_assessment_input(snapshot: dict[str, object]) -> str:
    return "已确认画像快照：\n" + _json(snapshot)


def render_profile_chat_input(context: dict[str, object], message: str) -> str:
    return f"当前画像上下文：\n{_json(context)}\n\n用户问题：\n{message.strip()}"


def render_profile_plan_input(context: dict[str, object], request: str) -> str:
    return f"当前画像快照：\n{_json(context)}\n\n修改请求：\n{request.strip()}"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
