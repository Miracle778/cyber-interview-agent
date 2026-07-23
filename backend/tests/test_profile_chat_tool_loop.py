from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from app.agents.context import AgentContext
from app.agents.profile_agents import ProfileAgents
from app.agents.profile_contracts import ProfileActionPlanProposal


class Runnable:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = []

    async def ainvoke(self, value, config=None, *, context=None):
        self.calls.append((value, config, context))
        return self.result


def _context(tmp_path: Path) -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=tmp_path,
        session_id="session-1",
        run_id="execution-1",
        allowed_tools=frozenset({"get_profile_claims"}),
        allowed_scopes=frozenset({"profile.materials"}),
        agent_role="profile_chat",
    )


@pytest.mark.asyncio
async def test_chat_keeps_session_thread_and_server_tool_permissions(tmp_path: Path):
    unused = Runnable({})
    chat = Runnable({"messages": [AIMessage(content="grounded answer")]})
    planner = Runnable(
        {"structured_response": ProfileActionPlanProposal(request_summary="noop")}
    )
    agents = ProfileAgents(unused, unused, chat, planner)
    context = _context(tmp_path)

    answer = await agents.answer(
        profile_context={"snapshot": {}},
        message="我的技能是什么？",
        context=context,
        config={"configurable": {"thread_id": "outer"}, "tags": ["profile"]},
    )

    assert answer == "grounded answer"
    _value, config, invoked_context = chat.calls[0]
    assert config["configurable"]["thread_id"] == "session-1:profile_chat"
    assert config["tags"] == ["profile"]
    assert invoked_context.allowed_tools == frozenset({"get_profile_claims"})


@pytest.mark.asyncio
async def test_planner_uses_execution_thread_and_never_inherits_chat_history(
    tmp_path: Path,
):
    unused = Runnable({})
    chat = Runnable({"messages": [AIMessage(content="unused")]})
    proposal = ProfileActionPlanProposal(request_summary="noop")
    planner = Runnable({"structured_response": proposal})
    agents = ProfileAgents(unused, unused, chat, planner)

    result = await agents.plan(
        profile_context={"snapshot": {}},
        request="生成方案",
        context=_context(tmp_path),
        config={"configurable": {"thread_id": "outer"}},
    )

    assert result == proposal
    _value, config, _invoked_context = planner.calls[0]
    assert config["configurable"]["thread_id"] == (
        "execution-1:profile_action_planner"
    )
