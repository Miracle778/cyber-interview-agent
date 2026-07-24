from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace
from typing import Any, Literal, TypedDict

from langchain_core.messages import HumanMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents.context import AgentContext
from app.agents.context_assembly import (
    ContextAssembler,
    ContextBudget,
    ContextMaterial,
    ContextResource,
    ContextSummary,
)
from app.agents.profile_agents import ProfileAgents
from app.profile.errors import (
    ProfileClaimNotFound,
    ProfileDomainError,
    ProfileProposalNotFound,
)
from app.profile.models import (
    ActionPlanItemSpec,
    CreateActionPlanCommand,
    CreateClaimProposalSpec,
)
from app.profile.repository import ProfileRepository
from app.profile.service import ProfileService
from app.tools.profile_tools import PROFILE_TOOL_NAMES, PROFILE_TOOL_SCOPES


ProfileManageIntent = Literal[
    "chat", "assess", "propose", "single_change", "plan", "clarify"
]


class ProfileManageState(TypedDict, total=False):
    message: str
    text: str
    focus: dict[str, object]
    intent: ProfileManageIntent
    profile_context: dict[str, object]
    profile_snapshot: dict[str, object]
    profile_focus: dict[str, object]
    response: str
    assessment_id: str
    proposal_ids: list[str]
    action_plan_id: str
    user_message_id: str
    scope_claim_ids: list[str]
    scope_categories: list[str]


ActionPlanCardProjector = Callable[[object], Awaitable[None]]


_ASSESS_RE = re.compile(r"评估|诊断|优势|短板|差距|风险|分析(?:一下)?(?:我的)?画像")
_MULTI_RE = re.compile(r"同时|并且|以及|然后|一并|全部|批量|规划|计划|优化简历")
_CHANGE_RE = re.compile(r"新增|添加|修改|更新|删除|去掉|拒绝|改成|改为|设为|调整")
_PROPOSE_RE = re.compile(r"整理成(?:个人)?画像(?:更新)?建议|生成画像更新建议|加入待确认")


def classify_profile_manage_intent(message: str) -> ProfileManageIntent:
    normalized = " ".join(message.split())
    if not normalized or normalized in {"帮我改一下", "改一下", "处理一下"}:
        return "clarify"
    if _ASSESS_RE.search(normalized):
        return "assess"
    if _PROPOSE_RE.search(normalized):
        return "propose"
    if _CHANGE_RE.search(normalized):
        return "plan" if _MULTI_RE.search(normalized) else "single_change"
    return "chat"


def create_profile_manage_graph(
    agents: ProfileAgents,
    *,
    repository: ProfileRepository,
    service: ProfileService,
    assessment_graph,
    project_action_plan_card: ActionPlanCardProjector | None,
    checkpointer=None,
):
    async def assemble(
        state: ProfileManageState, runtime: Runtime[AgentContext]
    ) -> dict[str, Any]:
        message = str(state.get("message") or state.get("text") or "").strip()
        if state.get("focus") is not None:
            _persist_focus(
                repository,
                session_id=runtime.context.session_id,
                workspace_id=runtime.context.workspace_id,
                values=state["focus"],
            )
        focus = repository.get_agent_focus(
            runtime.context.session_id, workspace_id=runtime.context.workspace_id
        )
        requested_ids, requested_categories = _requested_scope(state.get("focus") or {})
        snapshot = _snapshot_payload(
            repository,
            runtime.context.workspace_id,
            claim_ids=requested_ids,
            claim_types=requested_categories,
        )
        user_message_id = next(
            (
                item.id
                for item in reversed(
                    service.product_repository.list_messages(runtime.context.session_id)
                )
                if item.role == "user"
                and item.execution_id == runtime.context.run_id
            ),
            runtime.context.run_id,
        )
        assembled_context = _assemble_profile_context(
            focus={} if focus is None else asdict(focus),
            snapshot=snapshot,
        )
        return {
            "message": message,
            "profile_snapshot": snapshot,
            "profile_focus": {} if focus is None else asdict(focus),
            "profile_context": {"assembledContext": assembled_context},
            # A session-level outer checkpoint is reused across Executions;
            # clear terminal outputs so an earlier card never leaks forward.
            "response": "",
            "assessment_id": "",
            "proposal_ids": [],
            "action_plan_id": "",
            "user_message_id": user_message_id,
            "scope_claim_ids": list(requested_ids),
            "scope_categories": list(requested_categories),
        }

    async def classify(state: ProfileManageState) -> dict[str, Any]:
        return {"intent": classify_profile_manage_intent(state["message"])}

    def route(state: ProfileManageState) -> str:
        return state["intent"]

    async def chat(
        state: ProfileManageState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        allowed_tools = _chat_tools_for_message(state["message"])
        narrowed = replace(
            runtime.context,
            allowed_tools=frozenset(runtime.context.allowed_tools & allowed_tools),
            allowed_scopes=frozenset(
                PROFILE_TOOL_SCOPES[name]
                for name in runtime.context.allowed_tools & allowed_tools
                if PROFILE_TOOL_SCOPES[name] in runtime.context.allowed_scopes
            ),
            agent_role="profile_chat",
            profile_claim_ids=tuple(state.get("scope_claim_ids") or ()),
            profile_claim_types=tuple(state.get("scope_categories") or ()),
        )
        response = await agents.answer(
            profile_context=state["profile_context"],
            message=state["message"],
            context=narrowed,
            config=dict(config),
        )
        return {"response": response}

    async def propose(
        state: ProfileManageState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        output = await agents.propose_from_conversation(
            profile_context=state["profile_context"],
            message=state["message"],
            context=runtime.context,
            config=dict(config),
        )
        specs = tuple(
            CreateClaimProposalSpec(
                proposal_type=item.proposal_type,
                target_claim_id=item.target_claim_id,
                proposed_value={"category": item.category, **item.value},
                reason=item.rationale,
                source="conversation",
                source_kind="conversation",
                source_ref={
                    "messageId": state["user_message_id"],
                    "sessionId": runtime.context.session_id,
                },
            )
            for item in output.proposals
        )
        if not specs:
            return {
                "response": "这段对话里还没有足够明确的新信息。请补充具体经历、做法或结果后再整理。"
            }
        proposals = service.create_conversation_proposals(
            specs,
            execution_id=runtime.context.run_id,
            user_message_id=state["user_message_id"],
            session_id=runtime.context.session_id,
        )
        return {
            "proposal_ids": [item.id for item in proposals],
            "response": f"已整理出 {len(proposals)} 条更新建议，请到“待确认”中核对后再加入个人画像。",
        }

    async def assess(
        state: ProfileManageState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        snapshot = state["profile_snapshot"]
        if not snapshot.get("profileVersion") or not snapshot.get("claims"):
            return {"response": "当前还没有已确认的画像事实，请先确认至少一条画像建议后再评估。"}
        assessment_context = replace(
            runtime.context,
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
            agent_role="profile_assessment",
        )
        result = await assessment_graph.ainvoke(
            {}, config=dict(config), context=assessment_context
        )
        return {
            "assessment_id": result["assessment_id"],
            "proposal_ids": result["proposal_ids"],
            "response": "画像评估已完成，结果和建议已添加到当前会话。",
        }

    async def single_change(
        state: ProfileManageState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        return await _plan_and_persist(
            state,
            config,
            runtime,
            agents=agents,
            service=service,
            require_single=True,
            project_action_plan_card=project_action_plan_card,
        )

    async def plan(
        state: ProfileManageState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        return await _plan_and_persist(
            state,
            config,
            runtime,
            agents=agents,
            service=service,
            require_single=False,
            project_action_plan_card=project_action_plan_card,
        )

    async def clarify(_state: ProfileManageState) -> dict[str, Any]:
        return {
            "response": (
                "你希望修改哪一项？请说明目标和期望结果，例如："
                "“把 Python 熟练度改为高级，并保留简历中的对应证据”。"
            )
        }

    graph = StateGraph(ProfileManageState, context_schema=AgentContext)
    graph.add_node("assemble_context", assemble)
    graph.add_node("classify_intent", classify)
    graph.add_node("chat", chat)
    graph.add_node("propose", propose)
    graph.add_node("assess", assess)
    graph.add_node("single_change", single_change)
    graph.add_node("plan", plan)
    graph.add_node("clarify", clarify)
    graph.add_edge(START, "assemble_context")
    graph.add_edge("assemble_context", "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route,
        {
            "chat": "chat",
            "propose": "propose",
            "assess": "assess",
            "single_change": "single_change",
            "plan": "plan",
            "clarify": "clarify",
        },
    )
    for node in ("chat", "assess", "propose", "single_change", "plan", "clarify"):
        graph.add_edge(node, END)
    return graph.compile(checkpointer=checkpointer)


async def _plan_and_persist(
    state: ProfileManageState,
    config: RunnableConfig,
    runtime: Runtime[AgentContext],
    *,
    agents: ProfileAgents,
    service: ProfileService,
    require_single: bool,
    project_action_plan_card: ActionPlanCardProjector | None,
) -> dict[str, Any]:
    proposal = await agents.plan(
        profile_context=state["profile_context"],
        request=state["message"],
        context=replace(
            runtime.context,
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
            agent_role="profile_action_planner",
        ),
        config=dict(config),
    )
    if not proposal.items:
        return {
            "response": "我还不能确定要修改的目标或依据，请补充具体项目和期望结果。"
        }
    if require_single and len(proposal.items) != 1:
        return {
            "response": "这条请求包含多个可能的修改，请分别说明，或明确让我生成一份多项修改方案。"
        }
    snapshot = state["profile_snapshot"]
    try:
        plan = service.create_action_plan(
            CreateActionPlanCommand(
                workspace_id=runtime.context.workspace_id,
                session_id=runtime.context.session_id,
                execution_id=runtime.context.run_id,
                request_summary=proposal.request_summary,
                base_profile_version=str(snapshot.get("profileVersion") or ""),
                selection_snapshot=dict(state.get("profile_focus") or {}),
                items=tuple(
                    ActionPlanItemSpec(
                        item_id=item.item_id,
                        ordinal=index,
                        operation=item.operation,
                        target=item.target,
                        expected_version=item.expected_version,
                        before=item.before,
                        after=item.after,
                        evidence_ids=tuple(item.evidence_ids),
                    )
                    for index, item in enumerate(proposal.items, start=1)
                ),
            )
        )
    except ProfileDomainError:
        return {
            "response": (
                "这项修改目前缺少足够的简历原文依据，因此没有生成修改方案。"
                "你可以先补充相关经历，或改为整理现有表述。"
            )
        }
    if project_action_plan_card is not None:
        await project_action_plan_card(plan)
    return {
        "action_plan_id": plan.id,
        "response": "修改方案已生成，请检查后确认执行。",
    }


def _snapshot_payload(
    repository: ProfileRepository,
    workspace_id: str,
    *,
    claim_ids: tuple[str, ...] = (),
    claim_types: tuple[str, ...] = (),
) -> dict[str, object]:
    snapshot = repository.profile_snapshot(workspace_id)
    selected_ids = set(claim_ids)
    selected_types = set(claim_types)
    return {
        "profileVersion": snapshot.profile_version,
        "claims": [
            {
                "id": claim.claim_id,
                "type": claim.claim_type,
                "claimVersionId": claim.claim_version_id,
                "versionNumber": claim.version_number,
                "value": claim.value,
                "supportStatus": claim.support_status,
                "evidenceIds": list(claim.evidence_ids),
            }
            for claim in snapshot.claims
            if (not selected_ids or claim.claim_id in selected_ids)
            and (not selected_types or claim.claim_type in selected_types)
        ][:50],
        "materials": [
            {
                "id": material.id,
                "title": material.title,
                "type": material.type,
                "currentVersionId": material.current_version_id,
            }
            for material in snapshot.materials[:50]
        ],
    }


def _persist_focus(
    repository: ProfileRepository,
    *,
    session_id: str,
    workspace_id: str,
    values: dict[str, object],
) -> None:
    material_id = values.get("materialId") or values.get("material_id")
    material_version_id = values.get("materialVersionId") or values.get(
        "material_version_id"
    )
    claim_id = values.get("claimId") or values.get("claim_id")
    proposal_id = values.get("proposalId") or values.get("proposal_id")
    material_id = material_id if isinstance(material_id, str) else None
    material_version_id = (
        material_version_id if isinstance(material_version_id, str) else None
    )
    claim_id = claim_id if isinstance(claim_id, str) else None
    proposal_id = proposal_id if isinstance(proposal_id, str) else None
    if material_id is not None:
        repository.get_material(material_id, workspace_id=workspace_id)
    if material_version_id is not None:
        version = repository.get_material_version(material_version_id)
        repository.get_material(version.material_id, workspace_id=workspace_id)
    if claim_id is not None:
        claim = repository.get_claim(claim_id)
        if claim.workspace_id != workspace_id:
            raise ProfileClaimNotFound(claim_id)
    if proposal_id is not None:
        proposal = repository.get_proposal(proposal_id)
        if proposal.workspace_id != workspace_id:
            raise ProfileProposalNotFound(proposal_id)
    repository.save_agent_focus(
        session_id,
        workspace_id=workspace_id,
        material_id=material_id,
        material_version_id=material_version_id,
        claim_id=claim_id,
        proposal_id=proposal_id,
    )


def _requested_scope(values: dict[str, object]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    allowed_categories = {
        "summary",
        "direction",
        "highlight",
        "experience",
        "project",
        "skill",
        "education",
        "certification",
        "achievement",
        "link",
    }
    raw_ids = values.get("claimIds") or values.get("claim_ids") or ()
    raw_categories = values.get("categories") or ()
    claim_ids = tuple(
        dict.fromkeys(
            item for item in raw_ids if isinstance(item, str) and item.strip()
        )
    ) if isinstance(raw_ids, (list, tuple)) else ()
    categories = tuple(
        dict.fromkeys(
            item
            for item in raw_categories
            if isinstance(item, str) and item in allowed_categories
        )
    ) if isinstance(raw_categories, (list, tuple)) else ()
    return claim_ids[:50], categories


def _assemble_profile_context(
    *,
    focus: dict[str, object],
    snapshot: dict[str, object],
) -> str:
    material = ContextMaterial(
        # The current HumanMessage and compacted conversation are already owned
        # by the persistent profile_chat Agent thread. Only rehydrate domain truth.
        current_input="（当前问题见本轮用户消息）",
        working_state=json.dumps(focus, ensure_ascii=False, sort_keys=True),
        prior_summary=ContextSummary.empty(),
        turns=(),
        resources=(
            ContextResource(
                ref="profile:confirmed-snapshot",
                label="当前已确认画像",
                content=json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                priority=0,
                required=True,
            ),
        ),
    )
    assembled = ContextAssembler().assemble(
        material,
        ContextBudget(
            max_input_tokens=16_000,
            reserved_output_tokens=2_000,
            reserved_system_tokens=1_000,
            reserved_schema_tokens=500,
            reserved_tool_tokens=500,
        ),
        lambda value: max(
            1,
            count_tokens_approximately([HumanMessage(content=value)]),
        ),
    )
    return assembled.render()


def _chat_tools_for_message(message: str) -> frozenset[str]:
    tools = {
        "get_profile_claims",
        "get_profile_claim_evidence",
        "list_personal_materials",
    }
    if re.search(r"原文|材料|简历|证据|经历", message):
        tools.update(
            {
                "search_personal_materials",
                "read_personal_evidence",
                "read_personal_evidence_batch",
            }
        )
    if re.search(r"版本|对比|变化|差异", message):
        tools.add("compare_material_versions")
    return frozenset(tools) & frozenset(PROFILE_TOOL_NAMES)
