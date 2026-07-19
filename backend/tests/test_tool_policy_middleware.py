from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain.tools import ToolRuntime
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.context import AgentContext
from app.middleware.tool_policy_middleware import ToolPolicyMiddleware
from app.tools.runtime_tools import create_runtime_tools


class RecordingAudit:
    def __init__(self):
        self.started = []
        self.completed = []
        self.failed = []

    async def start(self, context, **values):
        self.started.append((context, values))
        return SimpleNamespace(id="audit-1")

    async def complete(self, audit_id, **values):
        self.completed.append((audit_id, values))

    async def fail(self, audit_id, **values):
        self.failed.append((audit_id, values))


class ToolCallingModel(GenericFakeChatModel):
    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        del tools, tool_choice, kwargs
        return self


def _context(workspace: Path, *, allowed=True):
    return AgentContext(
        workspace_id="w1",
        workspace_root=workspace,
        session_id="s1",
        run_id="r1",
        allowed_tools=frozenset({"read_source"}) if allowed else frozenset(),
        allowed_scopes=frozenset({"review.sources"}) if allowed else frozenset(),
    )


def _request(workspace: Path, *, allowed=True):
    tool = next(tool for tool in create_runtime_tools() if tool.name == "read_source")
    runtime = ToolRuntime(
        state={},
        context=_context(workspace, allowed=allowed),
        config={},
        stream_writer=lambda _value: None,
        tool_call_id="call-1",
        store=None,
    )
    return ToolCallRequest(
        tool_call={
            "name": "read_source",
            "args": {"path": "notes.md", "api_key": "must-not-leak"},
            "id": "call-1",
            "type": "tool_call",
        },
        tool=tool,
        state={},
        runtime=runtime,
    )


@pytest.mark.asyncio
async def test_tool_policy_denies_scope_without_calling_handler(tmp_path):
    audit = RecordingAudit()
    middleware = ToolPolicyMiddleware(
        audit=audit,
        required_scopes={"read_source": "review.sources"},
    )
    called = False

    async def handler(_request):
        nonlocal called
        called = True
        return ToolMessage(content="unsafe", tool_call_id="call-1")

    result = await middleware.awrap_tool_call(
        _request(tmp_path, allowed=False), handler
    )

    assert result.status == "error"
    assert result.content == "tool_not_allowed"
    assert called is False
    assert audit.started == []


@pytest.mark.asyncio
async def test_tool_policy_audits_safe_metadata_once(tmp_path):
    audit = RecordingAudit()
    middleware = ToolPolicyMiddleware(
        audit=audit,
        required_scopes={"read_source": "review.sources"},
    )

    async def handler(_request):
        return ToolMessage(content="ok", tool_call_id="call-1")

    result = await middleware.awrap_tool_call(_request(tmp_path), handler)

    assert result.content == "ok"
    assert len(audit.started) == 1
    assert audit.started[0][1] == {
        "tool_name": "read_source",
        "resource_scope": "review.sources",
        "resource_path": "notes.md",
    }
    assert "must-not-leak" not in repr(audit.started)
    assert len(audit.completed) == 1


@pytest.mark.asyncio
async def test_official_hitl_interrupts_before_tool_policy_executes(tmp_path):
    source_root = tmp_path / "artifacts/review/sources"
    source_root.mkdir(parents=True)
    (tmp_path / "artifacts/review/drafts").mkdir(parents=True)
    (tmp_path / "knowledge-vault").mkdir()
    (tmp_path / ".cyber-interview-agent/diagnostics").mkdir(parents=True)
    (source_root / "notes.md").write_text("safe", encoding="utf-8")
    audit = RecordingAudit()
    tools = create_runtime_tools()
    model = ToolCallingModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "read_source",
                            "args": {"path": "notes.md"},
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="done"),
            ]
        )
    )
    agent = create_agent(
        model=model,
        tools=tools,
        middleware=[
            ToolPolicyMiddleware(
                audit=audit,
                required_scopes={"read_source": "review.sources"},
            ),
            HumanInTheLoopMiddleware(interrupt_on={"read_source": True}),
        ],
        context_schema=AgentContext,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "s1"}}

    interrupted = await agent.ainvoke(
        {"messages": [HumanMessage(content="read notes")]},
        config,
        context=_context(tmp_path),
    )

    assert interrupted["__interrupt__"]
    assert audit.started == []

    completed = await agent.ainvoke(
        Command(resume={"decisions": [{"type": "approve"}]}),
        config,
        context=_context(tmp_path),
    )

    assert completed["messages"][-1].text == "done"
    assert len(audit.started) == 1
