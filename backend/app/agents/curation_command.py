from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.messages import AIMessageChunk, HumanMessage

from app.agents.context import AgentContext
from app.agents.context_assembly import (
    AssembledContext,
    ContextSummary,
    ContextTurn,
    TokenCounter,
)
from app.agents.factory import AgentFactory, AgentSpec
from app.agents.factory import ModelOverride
from app.review.curation_command_contracts import (
    CurationCommandPlan,
    CurationDialogueSummary,
)


class AgentRunnable(Protocol):
    async def ainvoke(
        self, input: dict[str, Any], config=None, *, context=None
    ) -> dict[str, Any]: ...

    def astream(self, input: dict[str, Any], config=None, *, context=None, **kwargs): ...


_CLASSIFIER_PROMPT = """你是题库整理命令分类器，只负责把用户表达转换为结构化计划。
不得执行发布、拒绝或重写，不得调用工具，不得编造候选题序号。
结合输入中的工作状态、历史摘要、完整对话轮次和焦点资源解析指代。
无法安全确定时填写 clarification；普通问答可填写 response。
“加了备注的重新生成，其他的发布”应映射为 regenerate=noted、publish=unnoted。"""


_SUMMARIZER_PROMPT = """你是题库整理对话摘要器。
只压缩提供的历史摘要和早期完整对话轮次，保留稳定资源引用、已定事项和未决事项。
不得补充候选题正文、来源正文或未提供的领域事实。"""


_RESPONDER_PROMPT = """你是题库整理会话中的题匠。
只根据提供的已验证上下文回答普通问题，不得声称执行了未提供的发布、拒绝或重写操作。
涉及副作用时提醒用户给出明确命令，由领域服务完成。"""


@dataclass(frozen=True, slots=True)
class CurationCommandClassifier:
    runnable: AgentRunnable

    async def classify(
        self, assembled: AssembledContext, *, context: AgentContext
    ) -> CurationCommandPlan:
        result = await self.runnable.ainvoke(
            {"messages": [HumanMessage(content=assembled.render())]},
            context=context,
        )
        return CurationCommandPlan.model_validate(result["structured_response"])


@dataclass(frozen=True, slots=True)
class CurationContextSummarizer:
    runnable: AgentRunnable

    async def summarize(
        self,
        *,
        prior_summary: ContextSummary,
        overflow_turns: tuple[ContextTurn, ...],
        context: AgentContext,
    ) -> ContextSummary:
        if not overflow_turns:
            return prior_summary
        result = await self.runnable.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=_render_summary_input(
                            prior_summary, overflow_turns
                        )
                    )
                ]
            },
            context=context,
        )
        structured = CurationDialogueSummary.model_validate(
            result["structured_response"]
        )
        return ContextSummary(
            text=structured.text,
            resource_refs=tuple(structured.resource_refs),
            decisions=tuple(structured.decisions),
            open_items=tuple(structured.open_items),
            through_message_id=overflow_turns[-1].messages[-1].id,
        )


@dataclass(frozen=True, slots=True)
class CurationCommandResponder:
    runnable: AgentRunnable

    async def astream(self, rendered_context: str, *, context: AgentContext):
        async for part in self.runnable.astream(
            {"messages": [HumanMessage(content=rendered_context)]},
            context=context,
            stream_mode=["messages"],
            version="v2",
        ):
            if not isinstance(part, dict) or part.get("type") != "messages":
                continue
            message, _metadata = part.get("data", (None, {}))
            if isinstance(message, AIMessageChunk) and message.text:
                yield message.text


@dataclass(frozen=True, slots=True)
class CurationCommandModels:
    classifier: CurationCommandClassifier
    summarizer: CurationContextSummarizer
    responder: CurationCommandResponder
    context_limit_tokens: int
    token_counter: TokenCounter = len

    @classmethod
    def create(
        cls,
        factory: AgentFactory,
        *,
        model_bindings,
        interaction_override: ModelOverride | None = None,
        middleware=(),
        context_limit_tokens: int,
        token_counter: TokenCounter = len,
    ) -> CurationCommandModels:
        classifier = factory.create(
            AgentSpec(
                role="question_generation",
                execution_name="curation_command_classifier",
                system_prompt=_CLASSIFIER_PROMPT,
                middleware=tuple(middleware),
                response_format=CurationCommandPlan,
            ),
            model_bindings=model_bindings,
            model_override=interaction_override,
            checkpointer=None,
        )
        summarizer = factory.create(
            AgentSpec(
                role="report_summarization",
                execution_name="curation_context_summarizer",
                system_prompt=_SUMMARIZER_PROMPT,
                middleware=tuple(middleware),
                response_format=CurationDialogueSummary,
            ),
            model_bindings=model_bindings,
            model_override=None,
            checkpointer=None,
        )
        responder = factory.create(
            AgentSpec(
                role="question_generation",
                execution_name="curation_command_responder",
                system_prompt=_RESPONDER_PROMPT,
                middleware=tuple(middleware),
            ),
            model_bindings=model_bindings,
            model_override=interaction_override,
            checkpointer=None,
        )
        return cls(
            classifier=CurationCommandClassifier(classifier),
            summarizer=CurationContextSummarizer(summarizer),
            responder=CurationCommandResponder(responder),
            context_limit_tokens=context_limit_tokens,
            token_counter=token_counter,
        )


def _render_summary_input(
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
