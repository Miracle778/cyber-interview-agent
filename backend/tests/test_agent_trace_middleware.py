from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.agents.context import AgentContext
from app.diagnostics.agent_trace import (
    AgentTraceWriter,
    initialize_agent_trace_directory,
    read_trace_rows,
)
from app.middleware.agent_trace_middleware import AgentTraceMiddleware


def _context(tmp_path: Path, *, warning=None) -> AgentContext:
    initialize_agent_trace_directory(tmp_path)
    return AgentContext(
        workspace_id="w1",
        workspace_root=tmp_path,
        session_id="s1",
        run_id="r1",
        allowed_tools=frozenset({"read_personal_evidence"}),
        allowed_scopes=frozenset(),
        trace_warning=warning,
    )


@pytest.mark.asyncio
async def test_model_error_preserves_pairing_and_full_request(tmp_path: Path):
    middleware = AgentTraceMiddleware(
        AgentTraceWriter(),
        agent_role="question_generation",
        agent_name="question_discovery",
        provider_model_id="provider-model-1",
    )
    request = SimpleNamespace(
        messages=[HumanMessage(content="完整来源")],
        system_message=SystemMessage(content="系统提示"),
        tools=[],
        response_format=None,
        model_settings={"temperature": 0},
        runtime=SimpleNamespace(context=_context(tmp_path)),
    )

    async def fail(_request):
        raise TimeoutError("provider timed out with sk-hidden")

    with pytest.raises(TimeoutError):
        await middleware.awrap_model_call(request, fail)

    rows = read_trace_rows(tmp_path, "s1", "r1")
    assert [row["event_type"] for row in rows] == [
        "model.request",
        "model.error",
    ]
    assert rows[0]["invocation_id"] == rows[1]["invocation_id"]
    assert rows[0]["agent_name"] == "question_discovery"
    assert rows[0]["payload"]["messages"][0]["content"] == "完整来源"
    assert "sk-hidden" not in str(rows[1])
    assert rows[1]["payload"]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_model_success_records_monotonic_duration(tmp_path: Path):
    middleware = AgentTraceMiddleware(
        AgentTraceWriter(),
        agent_role="question_generation",
        agent_name="question_discovery",
        provider_model_id="provider-model-1",
    )
    request = SimpleNamespace(
        messages=[HumanMessage(content="完整来源")],
        system_message=SystemMessage(content="系统提示"),
        tools=[],
        response_format=None,
        model_settings={"temperature": 0},
        runtime=SimpleNamespace(context=_context(tmp_path)),
    )

    async def succeed(_request):
        return "完整模型回答"

    assert await middleware.awrap_model_call(request, succeed) == "完整模型回答"

    rows = read_trace_rows(tmp_path, "s1", "r1")
    assert rows[-1]["event_type"] == "model.response"
    assert rows[-1]["payload"]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_tool_success_records_full_args_and_result(tmp_path: Path):
    middleware = AgentTraceMiddleware(
        AgentTraceWriter(),
        agent_role="agent_chat",
        agent_name="profile_chat",
        provider_model_id="provider-model-1",
    )
    request = SimpleNamespace(
        tool_call={
            "id": "call-1",
            "name": "read_personal_evidence",
            "args": {"evidence_id": "ev-1"},
        },
        runtime=SimpleNamespace(context=_context(tmp_path)),
    )

    async def succeed(_request):
        return ToolMessage(content="完整证据", tool_call_id="call-1")

    result = await middleware.awrap_tool_call(request, succeed)

    assert result.content == "完整证据"
    rows = read_trace_rows(tmp_path, "s1", "r1")
    assert rows[0]["payload"]["args"] == {"evidence_id": "ev-1"}
    assert rows[1]["payload"]["result"]["content"] == "完整证据"
    assert rows[0]["invocation_id"] == rows[1]["invocation_id"] == "call-1"
    assert rows[1]["payload"]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_trace_failure_warns_once_without_changing_agent_result(tmp_path: Path):
    warnings: list[str] = []

    class FailingWriter:
        def append(self, *_args, **_kwargs):
            raise OSError("disk unavailable")

    middleware = AgentTraceMiddleware(
        FailingWriter(),
        agent_role="agent_chat",
        agent_name="profile_chat",
        provider_model_id="provider-model-1",
    )
    request = SimpleNamespace(
        tool_call={"id": "call-1", "name": "echo", "args": {}},
        runtime=SimpleNamespace(context=_context(tmp_path, warning=warnings.append)),
    )

    async def succeed(_request):
        return ToolMessage(content="ok", tool_call_id="call-1")

    result = await middleware.awrap_tool_call(request, succeed)

    assert result.content == "ok"
    assert warnings == ["agent_trace_write_failed"]
