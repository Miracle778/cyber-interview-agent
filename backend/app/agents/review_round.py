from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from typing import Any, Protocol

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.context import AgentContext
from app.agents.factory import AgentFactory, AgentSpec, ModelOverride
from app.agents.review_round_contracts import (
    ReviewSessionReportOutput,
    RoundAnswerEvaluation,
)
from app.review.models import QuestionSnapshot


class AgentRunnable(Protocol):
    async def ainvoke(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
        *,
        context: AgentContext | None = None,
    ) -> dict[str, Any]: ...


_EVALUATION_PROMPT = (
    "根据冻结题目、参考答案和关键点评价回答。返回证据、缺失点、是否需要一次"
    "必要追问和 mastery 建议；不得输出隐藏推理。"
)
_REPORT_PROMPT = (
    "根据结构化 attempts 生成简洁中文轮次报告和 mastery 解释。"
    "不得直接修改 mastery，也不得输出隐藏推理。"
)
_DISCUSSION_PROMPT = (
    "围绕给定冻结题目和 attempt 证据深入讨论。只读知识，"
    "不得修改父复习轮次或自动发布内容。"
)


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
                    system_prompt=_EVALUATION_PROMPT,
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
                    system_prompt=_REPORT_PROMPT,
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
                    system_prompt=_DISCUSSION_PROMPT,
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
        prompt = (
            f"冻结题目：{json.dumps(asdict(question), ensure_ascii=False)}\n"
            f"用户回答：{answer}"
        )
        if supplement:
            prompt += f"\n补充回答：{supplement}"
        result = await self.evaluator.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            _role_config(config, context, "answer_evaluation"),
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
        payload = {
            "attempts": attempts,
            "settings": settings,
            "confirmedPriorReports": prior_reports[-3:],
        }
        result = await self.reporter.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=json.dumps(payload, ensure_ascii=False)
                    )
                ]
            },
            _role_config(config, context, "report_summarization"),
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
                        content=json.dumps(
                            {
                                "question": asdict(question),
                                "attemptEvidence": attempt_evidence,
                                "message": message,
                            },
                            ensure_ascii=False,
                        )
                    )
                ]
            },
            _role_config(config, context, "agent_chat"),
            context=context,
        )
        messages = result.get("messages", ())
        final = messages[-1] if messages else None
        text = final.text.strip() if isinstance(final, AIMessage) else ""
        if not text:
            raise ValueError("模型未生成深入讨论回复")
        return text


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
