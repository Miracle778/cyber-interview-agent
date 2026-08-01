from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.agents.agent_factory import AgentFactory, AgentSpec, ModelOverride
from app.agents.agent_invocation import isolated_thread_config
from app.agents.agent_protocols import AgentRunnable
from app.agents.context import AgentContext
from app.agents.interview_retrospective_contracts import (
    CleanupOutput,
    QuestionAnalysisOutput,
    QuestionExtractionOutput,
)
from app.agents.prompts.interview_retrospective_prompts import (
    RETROSPECTIVE_ANALYSIS_PROMPT,
    RETROSPECTIVE_CLEANUP_PROMPT,
    RETROSPECTIVE_QUESTION_EXTRACTION_PROMPT,
    render_question_analysis_input,
    render_question_extraction_input,
    render_cleanup_window,
)


@dataclass(frozen=True, slots=True)
class InterviewRetrospectiveAgents:
    cleanup: AgentRunnable
    question_extraction: AgentRunnable
    question_analysis: AgentRunnable

    @classmethod
    def create(
        cls,
        factory: AgentFactory,
        *,
        model_bindings: Mapping[str, str],
        middleware: tuple[AgentMiddleware, ...] = (),
        model_override: ModelOverride | None = None,
        checkpointer=None,
    ) -> "InterviewRetrospectiveAgents":
        def create_agent(execution_name, prompt, response_format):
            return factory.create(
                AgentSpec(
                    role="retrospective_analysis",
                    execution_name=execution_name,
                    prompt=prompt,
                    tools=(),
                    middleware=middleware,
                    response_format=response_format,
                ),
                model_bindings=model_bindings,
                model_override=model_override,
                checkpointer=checkpointer,
            )

        return cls(
            cleanup=create_agent(
                "interview_retrospective_cleanup",
                RETROSPECTIVE_CLEANUP_PROMPT,
                CleanupOutput,
            ),
            question_extraction=create_agent(
                "interview_retrospective_question_extraction",
                RETROSPECTIVE_QUESTION_EXTRACTION_PROMPT,
                QuestionExtractionOutput,
            ),
            question_analysis=create_agent(
                "interview_retrospective_question_analysis",
                RETROSPECTIVE_ANALYSIS_PROMPT,
                QuestionAnalysisOutput,
            ),
        )

    async def cleanup_window(
        self,
        *,
        source_kind: str,
        source_start: int,
        source_end: int,
        body: str,
        context: AgentContext,
        config: dict[str, Any],
    ) -> CleanupOutput:
        result = await self.cleanup.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_cleanup_window(
                            source_kind=source_kind,
                            source_start=source_start,
                            source_end=source_end,
                            body=body,
                        )
                    )
                ]
            },
            isolated_thread_config(
                config,
                context,
                f"interview_retrospective_cleanup:{source_start}:{source_end}",
            ),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化面试记录整理结果")
        output = CleanupOutput.model_validate(result["structured_response"])
        output.validate_window(source_start=source_start, source_end=source_end)
        return output

    async def extract_questions(
        self,
        *,
        segments: list[dict[str, object]],
        context_snapshot: dict[str, object],
        context: AgentContext,
        config: dict[str, Any],
    ) -> QuestionExtractionOutput:
        result = await self.question_extraction.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_question_extraction_input(
                            segments=segments, context_snapshot=context_snapshot
                        )
                    )
                ]
            },
            isolated_thread_config(config, context, "question_extraction"),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化面试问题")
        return QuestionExtractionOutput.model_validate(result["structured_response"])

    async def analyze_question(
        self,
        *,
        question: dict[str, object],
        segments: list[dict[str, object]],
        context_snapshot: dict[str, object],
        context: AgentContext,
        config: dict[str, Any],
    ) -> QuestionAnalysisOutput:
        result = await self.question_analysis.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_question_analysis_input(
                            question=question,
                            segments=segments,
                            context_snapshot=context_snapshot,
                        )
                    )
                ]
            },
            isolated_thread_config(
                config, context, f"question_analysis:{question['id']}"
            ),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化逐题分析")
        return QuestionAnalysisOutput.model_validate(result["structured_response"])
