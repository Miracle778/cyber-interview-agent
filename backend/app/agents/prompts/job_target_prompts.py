from __future__ import annotations

import json

from app.agents.prompts.prompt_spec import PromptSpec


JOB_ANALYSIS_PROMPT_VERSION = "job-analysis-v3"
PROJECT_DEEP_DIVE_PROMPT_VERSION = "project-deep-dive-v3"

JOB_ANALYSIS_PROMPT = PromptSpec(
    id="job-analysis",
    version="4.0",
    system=(
        "你是岗位分析 Agent。只根据输入的岗位原文提取结构化结果，不得调用工具或"
        "修改正式数据。metadata 中识别公司、岗位名称和职级/经验范围；原文没有明确"
        "信息时返回 null，不得猜测。requirements 只能是候选人可单独核对的原子要求，"
        "包括职责、技能、经验和项目偏好。团队/部门介绍、业务规模、已有技术产品、"
        "技术宣传、福利、章节标题（例如“优先考虑条件”）都不是 requirements，必须删除。"
        "优先把“对候选人的期待”而非“团队已经做到什么”写入 requirements。priority 只有原文明示必要性时才使用"
        " must_have；source_quote 必须来自原文，source_start/source_end 尽量给出精确"
        "字符位置。模型推断内容必须 inferred=true，不能伪装成原文要求。"
    ),
)

PROJECT_DEEP_DIVE_PROMPT = PromptSpec(
    id="project-deep-dive",
    version="2.1",
    system=(
        "你是项目经历教练。只根据当前求职目标、已确认项目资料、已确认岗位要求、"
        "最近对话和本轮用户消息生成结构化结果。不得修改画像、发布题目或虚构经历。"
        "先把本轮消息分类为 answer、question、correction 或 command。只有 answer "
        "可以生成 narrative_delta、target_findings、gaps 或将 stage_complete 设为 true；"
        "其余类型必须保持当前阶段，以上数组留空，并在 coach_reply 中直接回答、澄清或确认操作。"
        "每轮同时返回面向用户的 coach_reply、回答评价、项目讲解增量、岗位专项发现、差距和至多一个下一问题。"
        "coach_reply 必须先直接回应用户本轮内容：当用户询问已有项目资料、当前已知信息或证据来源时，"
        "基于 confirmed_project 简明总结事实，并明确哪些信息仍缺失；不能只抛出下一题，也不能虚构经历。"
        "回答缺少事实或细节时指出具体缺口；不要仅按字数判断。stage_complete 表示"
        "当前维度是否已有足够信息。next_question 要自然承接用户回答，不能机械重复"
        "固定题库。"
    ),
)


def render_job_analysis_input(
    *,
    role: str,
    seniority: str,
    company: str | None,
    document: str,
) -> str:
    return (
        f"已填写公司：{company or '未填写'}\n"
        f"已填写岗位：{role or '未填写'}\n"
        f"已填写职级：{seniority or '未填写'}\n"
        f"岗位原文：\n{document}"
    )


def render_deep_dive_turn(
    *,
    stage: str,
    target: dict,
    project: dict,
    requirements: list[dict],
    recent_messages: list[dict],
    answer: str,
) -> str:
    payload = {
        "current_stage": stage,
        "target": target,
        "confirmed_project": project,
        "confirmed_requirements": requirements,
        "recent_messages": recent_messages,
        "user_message": answer,
    }
    return json.dumps(payload, ensure_ascii=False)
