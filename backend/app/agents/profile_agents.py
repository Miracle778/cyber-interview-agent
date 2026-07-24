from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.agents.agent_factory import AgentFactory, AgentSpec
from app.agents.agent_invocation import final_ai_text, isolated_thread_config
from app.agents.agent_protocols import AgentRunnable
from app.agents.context import AgentContext
from app.agents.profile_contracts import (
    ProfileActionPlanProposal,
    ProfileAssessmentOutput,
    ProfileConversationProposalOutput,
    ProfileExtractionOutput,
)
from app.agents.prompts.profile_prompts import (
    PROFILE_ACTION_PLANNER_PROMPT,
    PROFILE_ASSESSMENT_PROMPT,
    PROFILE_CHAT_PROMPT,
    PROFILE_CONVERSATION_PROPOSAL_PROMPT,
    PROFILE_EXTRACTION_PROMPT,
    render_profile_assessment_input,
    render_profile_chat_input,
    render_profile_conversation_proposal_input,
    render_profile_extraction_input,
    render_profile_plan_input,
)


@dataclass(frozen=True, slots=True)
class ProfileAgents:
    extraction: AgentRunnable
    assessment: AgentRunnable
    chat: AgentRunnable
    action_planner: AgentRunnable
    conversation_proposal: AgentRunnable | None = None

    @classmethod
    def create(
        cls,
        factory: AgentFactory,
        *,
        model_bindings: Mapping[str, str],
        middleware: tuple[AgentMiddleware, ...] = (),
        chat_tools=(),
        planner_tools=(),
        checkpointer=None,
    ) -> "ProfileAgents":
        return cls(
            extraction=factory.create(
                AgentSpec(
                    role="profile_extraction",
                    execution_name="profile_extraction",
                    prompt=PROFILE_EXTRACTION_PROMPT,
                    middleware=middleware,
                    response_format=ProfileExtractionOutput,
                ),
                model_bindings=model_bindings,
                checkpointer=checkpointer,
            ),
            assessment=factory.create(
                AgentSpec(
                    role="profile_assessment",
                    execution_name="profile_assessment",
                    prompt=PROFILE_ASSESSMENT_PROMPT,
                    middleware=middleware,
                    response_format=ProfileAssessmentOutput,
                ),
                model_bindings=model_bindings,
                checkpointer=checkpointer,
            ),
            chat=factory.create(
                AgentSpec(
                    role="agent_chat",
                    execution_name="profile_chat",
                    prompt=PROFILE_CHAT_PROMPT,
                    tools=tuple(chat_tools),
                    middleware=middleware,
                ),
                model_bindings=model_bindings,
                checkpointer=checkpointer,
            ),
            action_planner=factory.create(
                AgentSpec(
                    role="profile_assessment",
                    execution_name="profile_action_planner",
                    prompt=PROFILE_ACTION_PLANNER_PROMPT,
                    tools=tuple(planner_tools),
                    middleware=middleware,
                    response_format=ProfileActionPlanProposal,
                ),
                model_bindings=model_bindings,
                checkpointer=checkpointer,
            ),
            conversation_proposal=factory.create(
                AgentSpec(
                    role="profile_assessment",
                    execution_name="profile_conversation_proposal",
                    prompt=PROFILE_CONVERSATION_PROPOSAL_PROMPT,
                    middleware=middleware,
                    response_format=ProfileConversationProposalOutput,
                ),
                model_bindings=model_bindings,
                checkpointer=checkpointer,
            ),
        )

    async def extract(
        self,
        *,
        evidence: Sequence[dict[str, object]],
        confirmed_profile: Sequence[dict[str, object]] = (),
        context: AgentContext,
        config: dict[str, Any],
    ) -> ProfileExtractionOutput:
        result = await self.extraction.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_profile_extraction_input(
                            evidence, confirmed_profile
                        )
                    )
                ]
            },
            isolated_thread_config(config, context, "profile_extraction"),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化画像候选")
        return ProfileExtractionOutput.model_validate(result["structured_response"])

    async def assess(
        self,
        *,
        snapshot: dict[str, object],
        context: AgentContext,
        config: dict[str, Any],
    ) -> ProfileAssessmentOutput:
        result = await self.assessment.ainvoke(
            {
                "messages": [
                    HumanMessage(content=render_profile_assessment_input(snapshot))
                ]
            },
            isolated_thread_config(config, context, "profile_assessment"),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化画像评估")
        return ProfileAssessmentOutput.model_validate(result["structured_response"])

    async def answer(
        self,
        *,
        profile_context: dict[str, object],
        message: str,
        context: AgentContext,
        config: dict[str, Any],
    ) -> str:
        result = await self.chat.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_profile_chat_input(profile_context, message)
                    )
                ]
            },
            isolated_thread_config(config, context, "profile_chat"),
            context=context,
        )
        text = final_ai_text(result)
        if not text:
            raise ValueError("模型未生成画像回复")
        return text

    async def plan(
        self,
        *,
        profile_context: dict[str, object],
        request: str,
        context: AgentContext,
        config: dict[str, Any],
    ) -> ProfileActionPlanProposal:
        execution_context = replace(context, session_id=context.run_id)
        result = await self.action_planner.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_profile_plan_input(profile_context, request)
                    )
                ]
            },
            isolated_thread_config(
                config, execution_context, "profile_action_planner"
            ),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化画像计划")
        return ProfileActionPlanProposal.model_validate(result["structured_response"])

    async def propose_from_conversation(
        self,
        *,
        profile_context: dict[str, object],
        message: str,
        context: AgentContext,
        config: dict[str, Any],
    ) -> ProfileConversationProposalOutput:
        if self.conversation_proposal is None:
            raise ValueError("画像对话建议 Agent 未配置")
        result = await self.conversation_proposal.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_profile_conversation_proposal_input(
                            profile_context, message
                        )
                    )
                ]
            },
            isolated_thread_config(
                config,
                replace(context, session_id=context.run_id),
                "profile_conversation_proposal",
            ),
            context=replace(
                context,
                allowed_tools=frozenset(),
                allowed_scopes=frozenset(),
                agent_role="profile_assessment",
            ),
        )
        if "structured_response" not in result:
            raise ValueError("模型未生成结构化画像更新建议")
        return ProfileConversationProposalOutput.model_validate(
            result["structured_response"]
        )
