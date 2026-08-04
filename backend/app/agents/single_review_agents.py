from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain.agents.middleware import AgentMiddleware

from app.agents.context import AgentContext
from app.agents.agent_factory import AgentSpec, RegisteredAgentFactory
from app.agents.agent_invocation import final_ai_text, isolated_thread_config
from app.agents.agent_protocols import AgentRunnable
from app.agents.prompts.single_review_prompts import (
    SINGLE_REVIEW_EVALUATION_PROMPT,
    SINGLE_REVIEW_REPORT_PROMPT,
    render_single_evaluation_input,
    render_single_report_input,
)
from app.agents.review_contracts import AnswerEvaluation
from app.schemas.review import ReviewQuestion


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SingleReviewAgents:
    evaluator: AgentRunnable
    reporter: AgentRunnable

    @classmethod
    def create(
        cls,
        factory: RegisteredAgentFactory,
        *,
        model_bindings: Mapping[str, str],
        middleware: tuple[AgentMiddleware, ...] = (),
        checkpointer=None,
    ) -> "SingleReviewAgents":
        return cls(
            evaluator=factory.create(
                AgentSpec(
                    role="answer_evaluation",
                    execution_name="single_review_evaluator",
                    prompt=SINGLE_REVIEW_EVALUATION_PROMPT,
                    response_format=AnswerEvaluation,
                    middleware=middleware,
                ),
                component_id="single_review_evaluator",
                model_bindings=model_bindings,
                checkpointer=checkpointer,
            ),
            reporter=factory.create(
                AgentSpec(
                    role="report_summarization",
                    execution_name="single_review_reporter",
                    prompt=SINGLE_REVIEW_REPORT_PROMPT,
                    middleware=middleware,
                ),
                component_id="single_review_reporter",
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
                    HumanMessage(content=render_single_evaluation_input(
                        question=validated.question_text,
                        reference_answer=validated.reference_answer,
                        key_points=tuple(validated.key_points),
                        user_answer=user_answer,
                    ))
                ]
            },
            isolated_thread_config(config, context, "answer_evaluation"),
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
                    HumanMessage(content=render_single_report_input(
                        question=validated.question_text,
                        user_answer=user_answer,
                        evaluation=evaluated.model_dump(),
                    ))
                ]
            },
            isolated_thread_config(config, context, "report_summarization"),
            context=context,
        )
        markdown = final_ai_text(result)
        if not markdown:
            raise ValueError("模型未生成复习报告")
        return markdown
