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
    REVIEW_TURN_CLASSIFICATION_PROMPT,
    PROJECT_ANSWER_EVALUATION_PROMPT,
    REVIEW_ROUND_EVALUATION_PROMPT,
    REVIEW_ROUND_REPORT_PROMPT,
    render_review_discussion_input,
    render_review_turn_classification_input,
    render_round_evaluation_input,
    render_round_report_input,
)
from app.agents.review_round_contracts import (
    ReviewSessionReportOutput,
    ReviewTurnClassification,
    RoundAnswerEvaluation,
)
from app.review.models import QuestionSnapshot


@dataclass(frozen=True, slots=True)
class ReviewRoundAgents:
    evaluator: AgentRunnable
    reporter: AgentRunnable
    discussion: AgentRunnable
    project_evaluator: AgentRunnable | None = None
    turn_classifier: AgentRunnable | None = None

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
                # The evaluator is a single-turn decision.  Its complete
                # question and answer are supplied for every invocation, so
                # retaining Agent messages would leak an earlier question
                # into the next evaluation in the same review session.
                checkpointer=None,
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
                checkpointer=None,
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
            project_evaluator=factory.create(
                AgentSpec(
                    role="answer_evaluation",
                    execution_name="project_answer_evaluator",
                    prompt=PROJECT_ANSWER_EVALUATION_PROMPT,
                    middleware=middleware,
                    response_format=RoundAnswerEvaluation,
                ),
                model_bindings=model_bindings,
                model_override=answer_model_override,
                checkpointer=None,
            ),
            turn_classifier=factory.create(
                AgentSpec(
                    role="answer_evaluation",
                    execution_name="review_turn_classifier",
                    prompt=REVIEW_TURN_CLASSIFICATION_PROMPT,
                    middleware=middleware,
                    response_format=ReviewTurnClassification,
                ),
                model_bindings=model_bindings,
                model_override=answer_model_override,
                checkpointer=None,
            ),
        )

    async def classify_turn(
        self,
        *,
        question: QuestionSnapshot,
        message: str,
        context: AgentContext,
        config: dict[str, Any],
    ) -> ReviewTurnClassification:
        if self.turn_classifier is None:
            return ReviewTurnClassification(intent="answer")
        result = await self.turn_classifier.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_review_turn_classification_input(
                            question=asdict(question),
                            message=message,
                        )
                    )
                ]
            },
            isolated_thread_config(config, context, "turn_classification"),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化复习意图")
        return ReviewTurnClassification.model_validate(
            result["structured_response"]
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
        evaluator = (
            self.project_evaluator
            if question.question_id.startswith("project:") and self.project_evaluator
            else self.evaluator
        )
        result = await evaluator.ainvoke(
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
