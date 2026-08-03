from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langchain.agents.structured_output import StructuredOutputValidationError
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.agent_factory import AgentFactory, AgentSpec, ModelOverride
from app.agents.agent_model_resolver import ModelInvocationPolicy
from app.agents.agent_invocation import isolated_thread_config
from app.agents.agent_protocols import AgentRunnable
from app.agents.context import AgentContext
from app.agents.interview_retrospective_contracts import (
    CleanupWindowOutput,
    QuestionAnalysisOutput,
    QuestionExtractionModelOutput,
    QuestionExtractionOutput,
    RetrospectiveChatOutput,
)
from app.agents.prompts.interview_retrospective_prompts import (
    RETROSPECTIVE_ANALYSIS_PROMPT,
    RETROSPECTIVE_CLEANUP_PROMPT,
    RETROSPECTIVE_CHAT_PROMPT,
    RETROSPECTIVE_QUESTION_EXTRACTION_PROMPT,
    render_question_analysis_input,
    render_question_extraction_input,
    render_question_extraction_repair_input,
    render_cleanup_target_window,
    render_chat_input,
)


_CLEANUP_INVOCATION_POLICY = ModelInvocationPolicy(
    max_output_tokens=8_192,
    request_timeout_seconds=120,
    max_retries=0,
)

_QUESTION_EXTRACTION_INVOCATION_POLICY = ModelInvocationPolicy(
    max_output_tokens=8_192,
    request_timeout_seconds=120,
    max_retries=0,
)

_QUESTION_ANALYSIS_INVOCATION_POLICY = ModelInvocationPolicy(
    max_output_tokens=4_096,
    request_timeout_seconds=120,
    max_retries=0,
)


class RetrospectiveCleanupModelError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class RetrospectiveQuestionExtractionModelError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class InterviewRetrospectiveAgents:
    cleanup: AgentRunnable
    question_extraction: AgentRunnable
    question_analysis: AgentRunnable
    chat: AgentRunnable

    @classmethod
    def create(
        cls,
        factory: AgentFactory,
        *,
        model_bindings: Mapping[str, str],
        middleware: tuple[AgentMiddleware, ...] = (),
        model_override: ModelOverride | None = None,
        checkpointer=None,
        chat_tools: tuple = (),
    ) -> "InterviewRetrospectiveAgents":
        def create_agent(
            execution_name,
            prompt,
            response_format,
            tools=(),
            role="retrospective_analysis",
            invocation_policy=None,
            structured_output_handle_errors=True,
        ):
            return factory.create(
                AgentSpec(
                    role=role,
                    execution_name=execution_name,
                    prompt=prompt,
                    tools=tools,
                    middleware=middleware,
                    response_format=response_format,
                    structured_output_handle_errors=structured_output_handle_errors,
                    invocation_policy=invocation_policy,
                ),
                model_bindings=model_bindings,
                model_override=model_override,
                checkpointer=checkpointer,
            )

        return cls(
            cleanup=create_agent(
                "interview_retrospective_cleanup",
                RETROSPECTIVE_CLEANUP_PROMPT,
                CleanupWindowOutput,
                invocation_policy=_CLEANUP_INVOCATION_POLICY,
                structured_output_handle_errors=False,
            ),
            question_extraction=create_agent(
                "interview_retrospective_question_extraction",
                RETROSPECTIVE_QUESTION_EXTRACTION_PROMPT,
                QuestionExtractionModelOutput,
                invocation_policy=_QUESTION_EXTRACTION_INVOCATION_POLICY,
                structured_output_handle_errors=False,
            ),
            question_analysis=create_agent(
                "interview_retrospective_question_analysis",
                RETROSPECTIVE_ANALYSIS_PROMPT,
                QuestionAnalysisOutput,
                invocation_policy=_QUESTION_ANALYSIS_INVOCATION_POLICY,
            ),
            chat=create_agent(
                "interview_retrospective_chat",
                RETROSPECTIVE_CHAT_PROMPT,
                RetrospectiveChatOutput,
                chat_tools,
                "retrospective_chat",
            ),
        )

    async def cleanup_window(
        self,
        *,
        source_kind: str,
        recording_coverage: str = "mixed_unknown",
        target_start: int,
        target_end: int,
        before_context: str,
        target_text: str,
        after_context: str,
        terminology_hints: tuple[str, ...] = (),
        context: AgentContext,
        config: dict[str, Any],
    ) -> CleanupWindowOutput:
        try:
            result = await self.cleanup.ainvoke(
                {
                    "messages": [
                        HumanMessage(
                            content=render_cleanup_target_window(
                                source_kind=source_kind,
                                recording_coverage=recording_coverage,
                                target_start=target_start,
                                target_end=target_end,
                                before_context=before_context,
                                target_text=target_text,
                                after_context=after_context,
                                terminology_hints=terminology_hints,
                            )
                        )
                    ]
                },
                isolated_thread_config(
                    config,
                    context,
                    f"interview_retrospective_cleanup:{target_start}:{target_end}",
                ),
                context=context,
            )
        except StructuredOutputValidationError as error:
            if _is_output_truncated(error.ai_message):
                raise RetrospectiveCleanupModelError(
                    "output_truncated",
                    "模型输出达到上限，当前文字窗口将缩小后重试",
                ) from error
            raise RetrospectiveCleanupModelError(
                "schema_validation_error",
                "模型返回格式不完整，当前文字窗口将缩小后重试",
            ) from error
        if "structured_response" not in result:
            messages = result.get("messages", ())
            final_message = messages[-1] if messages else None
            code = (
                "output_truncated"
                if isinstance(final_message, AIMessage)
                and _is_output_truncated(final_message)
                else "structured_output_missing"
            )
            raise RetrospectiveCleanupModelError(
                code,
                "模型未生成完整的结构化面试记录整理结果",
            )
        try:
            return CleanupWindowOutput.model_validate(result["structured_response"])
        except (TypeError, ValueError) as error:
            raise RetrospectiveCleanupModelError(
                "schema_validation_error",
                "模型返回结果与当前文字窗口不一致，将缩小窗口后重试",
            ) from error

    async def extract_questions(
        self,
        *,
        segments: list[dict[str, object]],
        recording_coverage: str = "mixed_unknown",
        work_key: str = "question_extraction",
        context: AgentContext,
        config: dict[str, Any],
    ) -> QuestionExtractionOutput:
        try:
            result = await self.question_extraction.ainvoke(
                {
                    "messages": [
                        HumanMessage(
                            content=render_question_extraction_input(
                                segments=segments,
                                recording_coverage=recording_coverage,
                            )
                        )
                    ]
                },
                isolated_thread_config(config, context, work_key),
                context=context,
            )
        except StructuredOutputValidationError as error:
            invalid_output = _invalid_structured_output(error.ai_message)
            repair_segments = _referenced_evidence_segments(
                invalid_output=invalid_output,
                segments=segments,
            )
            try:
                result = await self.question_extraction.ainvoke(
                    {
                        "messages": [
                            HumanMessage(
                                content=render_question_extraction_repair_input(
                                    invalid_output=invalid_output,
                                    validation_error=str(error.source),
                                    evidence_segments=repair_segments,
                                    recording_coverage=recording_coverage,
                                )
                            )
                        ]
                    },
                    isolated_thread_config(config, context, f"{work_key}:repair"),
                    context=context,
                )
            except StructuredOutputValidationError as repair_error:
                raise RetrospectiveQuestionExtractionModelError(
                    "schema_validation_error",
                    "模型返回的问题结构仍不完整，已停止当前窗口以保留其他结果",
                ) from repair_error
        if "structured_response" not in result:
            raise RetrospectiveQuestionExtractionModelError(
                "structured_output_missing",
                "模型未生成结构化面试问题",
            )
        try:
            model_output = QuestionExtractionModelOutput.model_validate(
                result["structured_response"]
            )
        except (TypeError, ValueError) as error:
            raise RetrospectiveQuestionExtractionModelError(
                "schema_validation_error",
                "模型返回的问题结构与当前提取合同不一致",
            ) from error
        try:
            return model_output.materialize(
                allowed_segment_ids={str(segment["id"]) for segment in segments}
            )
        except ValueError as error:
            raise RetrospectiveQuestionExtractionModelError(
                "schema_validation_error",
                "模型返回的问题引用了当前窗口之外的证据",
            ) from error

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

    async def discuss(
        self,
        *,
        message: str,
        selected_question_id: str | None,
        conversation: list[dict[str, str]],
        context: AgentContext,
        config: dict[str, Any],
    ) -> RetrospectiveChatOutput:
        result = await self.chat.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_chat_input(
                            message=message,
                            selected_question_id=selected_question_id,
                            conversation=conversation,
                        )
                    )
                ]
            },
            isolated_thread_config(config, context, "retrospective_chat"),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化复盘讨论结果")
        return RetrospectiveChatOutput.model_validate(result["structured_response"])


def _is_output_truncated(message: AIMessage) -> bool:
    stop_reason = message.response_metadata.get("stop_reason")
    if not isinstance(stop_reason, str):
        stop_reason = message.response_metadata.get("finish_reason")
    return isinstance(stop_reason, str) and stop_reason.casefold() in {
        "max_tokens",
        "length",
        "max_output_tokens",
    }


def _invalid_structured_output(message: AIMessage) -> dict[str, object]:
    for tool_call in message.tool_calls:
        arguments = tool_call.get("args")
        if isinstance(arguments, dict):
            return dict(arguments)
    return {"questions": []}


def _referenced_evidence_segments(
    *,
    invalid_output: dict[str, object],
    segments: list[dict[str, object]],
) -> list[dict[str, object]]:
    referenced: set[str] = set()
    questions = invalid_output.get("questions", [])
    if isinstance(questions, list):
        for question in questions:
            if not isinstance(question, dict):
                continue
            for field in (
                "anchorSegmentId",
                "questionSegmentIds",
                "answerSegmentIds",
            ):
                value = question.get(field)
                if isinstance(value, list):
                    referenced.update(str(item) for item in value if str(item))
                elif isinstance(value, str) and value:
                    referenced.add(value)
    return [
        {
            "id": str(segment["id"]),
            "speakerRole": segment.get("speakerRole", "unknown"),
            "body": str(segment.get("body", ""))[:1_200],
        }
        for segment in segments
        if str(segment.get("id", "")) in referenced
    ][:12]
