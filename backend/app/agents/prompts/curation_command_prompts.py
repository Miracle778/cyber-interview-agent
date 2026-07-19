from __future__ import annotations

from app.agents.context_assembly import ContextSummary, ContextTurn
from app.agents.prompts.prompt_spec import PromptSpec


CURATION_COMMAND_CLASSIFIER_PROMPT = PromptSpec(
    id="curation-command-classifier",
    version="1.0",
    system="""你是题库整理命令分类器，只负责把可能涉及副作用的用户表达转换为结构化计划。
不得执行发布、拒绝或重写，不得调用工具，不得编造候选题序号。
结合输入中的工作状态、历史摘要、完整对话轮次和焦点资源解析指代。
无法安全确定时填写 clarification；不要生成普通问答内容。
“加了备注的重新生成，其他的发布”应映射为 regenerate=noted、publish=unnoted。""",
)

CURATION_CONTEXT_SUMMARIZER_PROMPT = PromptSpec(
    id="curation-context-summarizer",
    version="1.0",
    system="""你是题库整理对话摘要器。
只压缩提供的历史摘要和早期完整对话轮次，保留稳定资源引用、已定事项和未决事项。
不得补充候选题正文、来源正文或未提供的领域事实。""",
)

CURATION_COMMAND_RESPONDER_PROMPT = PromptSpec(
    id="curation-command-responder",
    version="1.0",
    system="""你是题库整理会话中的题匠。
只根据提供的已验证上下文回答普通问题，不得声称执行了未提供的发布、拒绝或重写操作。
涉及副作用时提醒用户给出明确命令，由领域服务完成。""",
)


def render_curation_summary_input(
    prior_summary: ContextSummary,
    overflow_turns: tuple[ContextTurn, ...],
) -> str:
    lines = [
        "已有摘要",
        prior_summary.text or "（无）",
        *(f"资源引用 {item}" for item in prior_summary.resource_refs),
        *(f"已定事项 {item}" for item in prior_summary.decisions),
        *(f"未决事项 {item}" for item in prior_summary.open_items),
        "待压缩对话",
    ]
    for turn in overflow_turns:
        for message in turn.messages:
            lines.extend((message.role, message.content))
    return "\n".join(lines)
