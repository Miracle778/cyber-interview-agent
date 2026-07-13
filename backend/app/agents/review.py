from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
from typing import Any, Protocol

from langchain_core.messages import AIMessage, HumanMessage
from langchain.agents.middleware import AgentMiddleware

from app.agents.context import AgentContext
from app.agents.factory import AgentFactory, AgentSpec
from app.agents.review_contracts import AnswerEvaluation
from app.schemas.review import ReviewQuestion


logger = logging.getLogger(__name__)


class AgentRunnable(Protocol):
    async def ainvoke(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
        *,
        context: AgentContext | None = None,
    ) -> dict[str, Any]: ...


_EVALUATION_PROMPT = (
    "根据参考答案和关键点评价用户回答。只引用用户回答中的证据，"
    "返回 poor/partial/good、缺失关键点和简短证据。"
)
_REPORT_PROMPT = (
    "生成简洁的中文单题复习报告 Markdown，包含问题、评分、回答证据、"
    "缺失点和下一步；不得生成隐藏推理。"
)


@dataclass(frozen=True, slots=True)
class ReviewAgents:
    evaluator: AgentRunnable
    reporter: AgentRunnable

    @classmethod
    def create(
        cls,
        factory: AgentFactory,
        *,
        model_bindings: Mapping[str, str],
        middleware: tuple[AgentMiddleware, ...] = (),
        checkpointer=None,
    ) -> "ReviewAgents":
        return cls(
            evaluator=factory.create(
                AgentSpec(
                    role="answer_evaluation",
                    system_prompt=_EVALUATION_PROMPT,
                    response_format=AnswerEvaluation,
                    middleware=middleware,
                ),
                model_bindings=model_bindings,
                checkpointer=checkpointer,
            ),
            reporter=factory.create(
                AgentSpec(
                    role="report_summarization",
                    system_prompt=_REPORT_PROMPT,
                    middleware=middleware,
                ),
                model_bindings=model_bindings,
                checkpointer=checkpointer,
            ),
        )

    async def evaluate(
        self,
        *,
        question: ReviewQuestion | dict[str, Any],
        user_answer: str,
        context: AgentContext,
        config: dict[str, Any],
    ) -> AnswerEvaluation:
        validated = ReviewQuestion.model_validate(question)
        result = await self.evaluator.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            f"问题：{validated.question_text}\n"
                            f"参考答案：{validated.reference_answer}\n"
                            f"关键点：{', '.join(validated.key_points)}\n"
                            f"用户回答：{user_answer}"
                        )
                    )
                ]
            },
            _agent_config(config, context, "answer_evaluation"),
            context=context,
        )
        if "structured_response" not in result:
            tool_names = [
                call.get("name")
                for message in result.get("messages", ())
                if isinstance(message, AIMessage)
                for call in message.tool_calls
            ]
            logger.error(
                "evaluation agent returned no structured response keys=%s tools=%s",
                sorted(result),
                tool_names,
            )
            raise ValueError("模型未生成结构化评价")
        return AnswerEvaluation.model_validate(result["structured_response"])

    async def report(
        self,
        *,
        question: ReviewQuestion | dict[str, Any],
        user_answer: str,
        evaluation: AnswerEvaluation | dict[str, Any],
        context: AgentContext,
        config: dict[str, Any],
    ) -> str:
        validated = ReviewQuestion.model_validate(question)
        evaluated = AnswerEvaluation.model_validate(evaluation)
        result = await self.reporter.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            f"问题：{validated.question_text}\n"
                            f"用户回答：{user_answer}\n"
                            f"评价：{evaluated.model_dump()}"
                        )
                    )
                ]
            },
            _agent_config(config, context, "report_summarization"),
            context=context,
        )
        messages = result.get("messages", ())
        final = messages[-1] if messages else None
        markdown = final.text.strip() if isinstance(final, AIMessage) else ""
        if not markdown:
            raise ValueError("模型未生成复习报告")
        return markdown


def _agent_config(
    config: dict[str, Any], context: AgentContext, namespace: str
) -> dict[str, Any]:
    isolated = {
        key: value for key, value in config.items() if key != "configurable"
    }
    isolated["configurable"] = {
        "thread_id": f"{context.session_id}:{namespace}",
    }
    return isolated
