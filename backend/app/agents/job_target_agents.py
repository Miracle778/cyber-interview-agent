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
from app.agents.job_target_contracts import DeepDiveTurnResult, JobRequirementExtraction
from app.agents.prompts.job_target_prompts import (
    JOB_ANALYSIS_PROMPT,
    PROJECT_DEEP_DIVE_PROMPT,
    render_deep_dive_turn,
    render_job_analysis_input,
)


@dataclass(frozen=True, slots=True)
class JobTargetAgents:
    """Structured model boundary. Callers own persistence and validate every result."""

    analysis: AgentRunnable
    deep_dive: AgentRunnable

    @classmethod
    def create(
        cls,
        factory: AgentFactory,
        *,
        model_bindings: Mapping[str, str],
        middleware: tuple[AgentMiddleware, ...] = (),
        model_override: ModelOverride | None = None,
        checkpointer=None,
    ) -> "JobTargetAgents":
        return cls(
            analysis=factory.create(
                AgentSpec(
                    role="job_analysis",
                    execution_name="job_analysis",
                    prompt=JOB_ANALYSIS_PROMPT,
                    middleware=middleware,
                    response_format=JobRequirementExtraction,
                ),
                model_bindings=model_bindings,
                model_override=model_override,
                checkpointer=checkpointer,
            ),
            deep_dive=factory.create(
                AgentSpec(
                    role="project_deep_dive",
                    execution_name="project_deep_dive",
                    prompt=PROJECT_DEEP_DIVE_PROMPT,
                    middleware=middleware,
                    response_format=DeepDiveTurnResult,
                ),
                model_bindings=model_bindings,
                model_override=model_override,
                checkpointer=checkpointer,
            ),
        )

    async def extract_requirements(
        self,
        *,
        role: str,
        seniority: str,
        company: str | None,
        document: str,
        context: AgentContext,
        config: dict[str, Any],
    ) -> JobRequirementExtraction:
        result = await self.analysis.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_job_analysis_input(
                            role=role,
                            seniority=seniority,
                            company=company,
                            document=document,
                        )
                    )
                ]
            },
            isolated_thread_config(config, context, "job_analysis"),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化岗位分析")
        return JobRequirementExtraction.model_validate(result["structured_response"])

    async def evaluate_turn(
        self,
        *,
        stage: str,
        target: dict,
        project: dict,
        requirements: list[dict],
        recent_messages: list[dict],
        answer: str,
        context: AgentContext,
        config: dict[str, Any],
    ) -> DeepDiveTurnResult:
        result = await self.deep_dive.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_deep_dive_turn(
                            stage=stage,
                            target=target,
                            project=project,
                            requirements=requirements,
                            recent_messages=recent_messages,
                            answer=answer,
                        )
                    )
                ]
            },
            isolated_thread_config(config, context, "project_deep_dive"),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化项目深挖结果")
        return DeepDiveTurnResult.model_validate(result["structured_response"])
