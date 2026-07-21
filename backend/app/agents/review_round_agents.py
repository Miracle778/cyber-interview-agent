from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.agents.context import AgentContext
from app.agents.agent_factory import AgentFactory, AgentSpec, ModelOverride
from app.agents.agent_invocation import final_ai_text, isolated_thread_config
from app.agents.agent_protocols import AgentRunnable
from app.agents.prompts.review_round_prompts import (
    REVIEW_DISCUSSION_PROMPT,
    REVIEW_ROUND_EVALUATION_PROMPT,
    REVIEW_ROUND_REPORT_PROMPT,
    render_review_discussion_input,
    render_round_evaluation_input,
    render_round_report_input,
)
from app.agents.review_round_contracts import (
    ReviewSessionReportOutput,
    RoundAnswerEvaluation,
)
from app.review.models import QuestionSnapshot


@dataclass(frozen=True, slots=True)
class ReviewRoundAgents:
    evaluator: AgentRunnable
    reporter: AgentRunnable
    discussion: AgentRunnable

    @classmethod
    def create(
        cls,
        factory: AgentFactory,
        *,
        model_bindings: Mapping[str, str],
        middleware: tuple[AgentMiddleware, ...] = (),
        discussion_tools=(),
        answer_model_override: ModelOverride | None = None,
        discussion_model_override: ModelOverride | None = None,
        checkpointer=None,
    ) -> "ReviewRoundAgents":
        return cls(
            evaluator=factory.create(
                AgentSpec(
                    role="answer_evaluation",
                    execution_name="review_round_evaluator",
                    prompt=REVIEW_ROUND_EVALUATION_PROMPT,
                    middleware=middleware,
                    response_format=RoundAnswerEvaluation,
                ),
                model_bindings=model_bindings,
                model_override=answer_model_override,
                checkpointer=checkpointer,
            ),
            reporter=factory.create(
                AgentSpec(
                    role="report_summarization",
                    execution_name="review_round_reporter",
                    prompt=REVIEW_ROUND_REPORT_PROMPT,
                    middleware=middleware,
                    response_format=ReviewSessionReportOutput,
                ),
                model_bindings=model_bindings,
                model_override=discussion_model_override,
                checkpointer=checkpointer,
            ),
            discussion=factory.create(
                AgentSpec(
                    role="agent_chat",
                    execution_name="review_discussion",
                    prompt=REVIEW_DISCUSSION_PROMPT,
                    tools=tuple(discussion_tools),
                    middleware=middleware,
                ),
                model_bindings=model_bindings,
                model_override=None,
                checkpointer=checkpointer,
            ),
        )

    async def evaluate(
        self,
        *,
        question: QuestionSnapshot,
        answer: str,
        supplement: str | None,
        context: AgentContext,
        config: dict[str, Any],
        progress_scope: tuple[str, ...] = (),
    ) -> RoundAnswerEvaluation:
        prompt = render_round_evaluation_input(
            question=asdict(question), answer=answer, supplement=supplement
        )
        result = await self.evaluator.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            isolated_thread_config(config, context, "answer_evaluation"),
            context=(
                replace(context, progress_scope=progress_scope)
                if progress_scope
                else context
            ),
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化回答评价")
        return RoundAnswerEvaluation.model_validate(
            result["structured_response"]
        )

    async def report(
        self,
        *,
        attempts: tuple[dict[str, Any], ...],
        settings: dict[str, Any],
        prior_reports: tuple[str, ...],
        context: AgentContext,
        config: dict[str, Any],
    ) -> ReviewSessionReportOutput:
        result = await self.reporter.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_round_report_input(
                            attempts=attempts,
                            settings=settings,
                            prior_reports=prior_reports,
                        )
                    )
                ]
            },
            isolated_thread_config(config, context, "report_summarization"),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化轮次报告")
        return ReviewSessionReportOutput.model_validate(
            result["structured_response"]
        )

    async def discuss(
        self,
        *,
        question: QuestionSnapshot,
        attempt_evidence: dict[str, Any],
        message: str,
        context: AgentContext,
        config: dict[str, Any],
    ) -> str:
        result = await self.discussion.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_review_discussion_input(
                            question=asdict(question),
                            attempt_evidence=attempt_evidence,
                            message=message,
                        )
                    )
                ]
            },
            isolated_thread_config(config, context, "agent_chat"),
            context=context,
        )
        text = final_ai_text(result)
        if not text:
            raise ValueError("模型未生成深入讨论回复")
        return text
