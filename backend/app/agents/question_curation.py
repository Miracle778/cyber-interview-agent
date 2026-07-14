from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.agents.context import AgentContext
from app.agents.factory import AgentFactory, AgentSpec
from app.agents.r2_contracts import QuestionCandidateBatch


class AgentRunnable(Protocol):
    async def ainvoke(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
        *,
        context: AgentContext | None = None,
    ) -> dict[str, Any]: ...


_PROMPT = (
    "把给定来源整理为可复习的中文面试题候选。纠正明显错误，保留来源引用，"
    "标注 topic、难度、关键点、必要追问和简短修正说明。不得自动发布。"
)


@dataclass(frozen=True, slots=True)
class QuestionCurationAgent:
    runnable: AgentRunnable

    @classmethod
    def create(
        cls,
        factory: AgentFactory,
        *,
        model_bindings: Mapping[str, str],
        middleware: tuple[AgentMiddleware, ...] = (),
        tools=(),
        checkpointer=None,
    ) -> "QuestionCurationAgent":
        return cls(
            factory.create(
                AgentSpec(
                    role="question_generation",
                    system_prompt=_PROMPT,
                    tools=tuple(tools),
                    middleware=middleware,
                    response_format=QuestionCandidateBatch,
                ),
                model_bindings=model_bindings,
                checkpointer=checkpointer,
            )
        )

    async def generate(
        self,
        *,
        source_excerpts: tuple[str, ...],
        similar_questions: tuple[str, ...],
        rewrite_feedback: str | None,
        context: AgentContext,
        config: dict[str, Any],
    ) -> QuestionCandidateBatch:
        body = ["来源：", *source_excerpts]
        if similar_questions:
            body.extend(("现有相似题：", *similar_questions))
        if rewrite_feedback:
            body.extend(("重写要求：", rewrite_feedback))
        result = await self.runnable.ainvoke(
            {"messages": [HumanMessage(content="\n".join(body))]},
            _role_config(config, context, "question_generation"),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化题目候选")
        return QuestionCandidateBatch.model_validate(
            result["structured_response"]
        )


def _role_config(
    config: dict[str, Any], context: AgentContext, role: str
) -> dict[str, Any]:
    isolated = {
        key: value for key, value in config.items() if key != "configurable"
    }
    isolated["configurable"] = {
        "thread_id": f"{context.session_id}:{role}"
    }
    return isolated
