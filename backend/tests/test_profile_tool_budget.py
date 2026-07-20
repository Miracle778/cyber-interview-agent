from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain.tools import ToolRuntime

from app.agents.context import AgentContext
from app.middleware.tool_policy_middleware import ToolPolicyMiddleware  # noqa: F401
from app.tools.profile_tools import ProfileToolBudgetMiddleware


def _request(workspace: Path, *, tool_name: str, args: dict, call_id: str, run_id: str = "r1"):
    context = AgentContext(
        workspace_id="w1",
        workspace_root=workspace,
        session_id="s1",
        run_id=run_id,
        allowed_tools=frozenset({"read_personal_evidence"}),
        allowed_scopes=frozenset({"profile.materials"}),
        agent_role="profile_chat",
    )
    runtime = ToolRuntime(
        state={},
        context=context,
        config={},
        stream_writer=lambda _value: None,
        tool_call_id=call_id,
        store=None,
    )
    return ToolCallRequest(
        tool_call={
            "name": tool_name,
            "args": args,
            "id": call_id,
            "type": "tool_call",
        },
        tool=SimpleNamespace(name=tool_name),
        state={},
        runtime=runtime,
    )


async def _ok_handler(_request):
    from langchain_core.messages import ToolMessage

    return ToolMessage(content="ok", tool_call_id="ok")


@pytest.mark.asyncio
async def test_budget_allows_up_to_six_calls(tmp_path):
    middleware = ProfileToolBudgetMiddleware()

    for index in range(6):
        result = await middleware.awrap_tool_call(
            _request(tmp_path, tool_name="read_personal_evidence",
                     args={"evidence_id": f"ev-{index}"}, call_id=f"c-{index}"),
            _ok_handler,
        )
        assert result.content == "ok"


@pytest.mark.asyncio
async def test_budget_exhausts_after_six_calls(tmp_path):
    middleware = ProfileToolBudgetMiddleware()

    for index in range(6):
        await middleware.awrap_tool_call(
            _request(tmp_path, tool_name="read_personal_evidence",
                     args={"evidence_id": f"ev-{index}"}, call_id=f"c-{index}"),
            _ok_handler,
        )

    result = await middleware.awrap_tool_call(
        _request(tmp_path, tool_name="read_personal_evidence",
                 args={"evidence_id": "ev-7"}, call_id="c-7"),
        _ok_handler,
    )
    assert result.status == "error"
    assert "budget" in result.content.lower() or "answer" in result.content.lower()


@pytest.mark.asyncio
async def test_budget_blocks_third_identical_call(tmp_path):
    middleware = ProfileToolBudgetMiddleware()
    args = {"evidence_id": "ev-same"}

    first = await middleware.awrap_tool_call(
        _request(tmp_path, tool_name="read_personal_evidence", args=args, call_id="c-1"),
        _ok_handler,
    )
    second = await middleware.awrap_tool_call(
        _request(tmp_path, tool_name="read_personal_evidence", args=args, call_id="c-2"),
        _ok_handler,
    )
    assert first.content == "ok"
    assert second.content == "ok"

    third = await middleware.awrap_tool_call(
        _request(tmp_path, tool_name="read_personal_evidence", args=args, call_id="c-3"),
        _ok_handler,
    )
    assert third.status == "error"


@pytest.mark.asyncio
async def test_budget_distinct_args_do_not_count_as_identical(tmp_path):
    middleware = ProfileToolBudgetMiddleware()

    for index in range(4):
        result = await middleware.awrap_tool_call(
            _request(tmp_path, tool_name="read_personal_evidence",
                     args={"evidence_id": f"distinct-{index}"}, call_id=f"c-{index}"),
            _ok_handler,
        )
        assert result.content == "ok"


@pytest.mark.asyncio
async def test_budget_isolated_per_execution(tmp_path):
    middleware = ProfileToolBudgetMiddleware()
    args = {"evidence_id": "ev-same"}

    await middleware.awrap_tool_call(
        _request(tmp_path, tool_name="read_personal_evidence", args=args, call_id="c-1",
                 run_id="r1"),
        _ok_handler,
    )
    await middleware.awrap_tool_call(
        _request(tmp_path, tool_name="read_personal_evidence", args=args, call_id="c-2",
                 run_id="r1"),
        _ok_handler,
    )
    # A different execution has its own budget.
    result = await middleware.awrap_tool_call(
        _request(tmp_path, tool_name="read_personal_evidence", args=args, call_id="c-3",
                 run_id="r2"),
        _ok_handler,
    )
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_budget_normalizes_argument_key_order(tmp_path):
    middleware = ProfileToolBudgetMiddleware()

    await middleware.awrap_tool_call(
        _request(tmp_path, tool_name="read_personal_evidence",
                 args={"b": 2, "a": 1}, call_id="c-1"),
        _ok_handler,
    )
    await middleware.awrap_tool_call(
        _request(tmp_path, tool_name="read_personal_evidence",
                 args={"a": 1, "b": 2}, call_id="c-2"),
        _ok_handler,
    )
    third = await middleware.awrap_tool_call(
        _request(tmp_path, tool_name="read_personal_evidence",
                 args={"b": 2, "a": 1}, call_id="c-3"),
        _ok_handler,
    )

    assert third.status == "error"
    assert "repeated" in third.content
