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
from app.agents.interview_retrospective_contracts import CleanupOutput
from app.agents.prompts.interview_retrospective_prompts import (
    RETROSPECTIVE_CLEANUP_PROMPT,
    render_cleanup_window,
)


@dataclass(frozen=True, slots=True)
class InterviewRetrospectiveAgents:
    cleanup: AgentRunnable

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
        return cls(
            cleanup=factory.create(
                AgentSpec(
                    role="retrospective_analysis",
                    execution_name="interview_retrospective_cleanup",
                    prompt=RETROSPECTIVE_CLEANUP_PROMPT,
                    tools=(),
                    middleware=middleware,
                    response_format=CleanupOutput,
                ),
                model_bindings=model_bindings,
                model_override=model_override,
                checkpointer=checkpointer,
            )
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
