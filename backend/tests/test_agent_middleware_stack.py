from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.agents.middleware import (
    AgentMiddleware,
    ContextEditingMiddleware,
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    SummarizationMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.context import AgentContext
from app.diagnostics.agent_trace import AgentTraceWriter, read_trace_rows
from app.middleware.middleware_stack import (
    PROFILE_CHAT_BUDGET_PROFILE,
    build_default_middleware,
)
from app.middleware.no_progress_middleware import NoProgressError, NoProgressMiddleware
from app.middleware.observability_middleware import ObservabilityMiddleware
from app.middleware.session_title_middleware import SessionTitleMiddleware
from app.middleware.summarization_middleware import ProjectingSummarizationMiddleware
from app.middleware.usage_projection_middleware import UsageProjectionMiddleware


class FakeProjection:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.usage = []
        self.titles = []
        self.warnings = []
        self.progress: dict[tuple[str, str], int] = {}
        self.compacted = []
        self.context_usage = []

    def record_usage(self, context, usage) -> bool:
        if self.fail:
            raise RuntimeError("database unavailable")
        self.usage.append((context, usage))
        return True

    def ensure_title(self, context, candidate: str) -> bool:
        if self.fail:
            raise RuntimeError("database unavailable")
        self.titles.append((context, candidate))
        return True

    def observe_progress(self, context, fingerprint: str) -> int:
        key = (context.run_id, fingerprint)
        self.progress[key] = self.progress.get(key, 0) + 1
        return self.progress[key]

    def warning(self, context, code: str) -> None:
        self.warnings.append((context, code))

    def mark_context_compacted(self, context) -> bool:
        self.compacted.append(context)
        return True

    def record_context_usage(self, context, usage) -> bool:
        self.context_usage.append((context, usage))
        return True


class StubPolicyMiddleware(AgentMiddleware):
    pass


class RecordingSink:
    @contextmanager
    def span(self, name, *, context, attributes, links=()):
        yield SimpleNamespace(record_error=lambda _code: None)


def _context() -> AgentContext:
    return AgentContext(
        workspace_id="workspace-1",
        workspace_root=Path("/workspace"),
        session_id="session-1",
        run_id="run-1",
        allowed_tools=frozenset({"write_review_draft"}),
        allowed_scopes=frozenset({"review.write"}),
    )


def _runtime():
    return SimpleNamespace(context=_context())


def test_default_stack_is_official_and_contains_only_four_project_middlewares():
    projection = FakeProjection()
    policy = StubPolicyMiddleware()
    model = GenericFakeChatModel(messages=iter([AIMessage(content="summary")]))

    stack = build_default_middleware(
        summary_model=model,
        projection=projection,
        policy=policy,
        observability=RecordingSink(),
        interrupt_on={"write_review_draft": True},
    )

    assert [type(item) for item in stack] == [
        ProjectingSummarizationMiddleware,
        ContextEditingMiddleware,
        ModelCallLimitMiddleware,
        ToolCallLimitMiddleware,
        StubPolicyMiddleware,
        HumanInTheLoopMiddleware,
        UsageProjectionMiddleware,
        SessionTitleMiddleware,
        NoProgressMiddleware,
        ObservabilityMiddleware,
    ]
    model_limit = next(x for x in stack if isinstance(x, ModelCallLimitMiddleware))
    tool_limit = next(x for x in stack if isinstance(x, ToolCallLimitMiddleware))
    assert vars(model_limit) == {
        "thread_limit": 40,
        "run_limit": 12,
        "exit_behavior": "error",
    }
    assert vars(tool_limit) == {
        "tool_name": None,
        "thread_limit": 80,
        "run_limit": 20,
        "exit_behavior": "error",
    }
    assert all(not hasattr(item, "layer") for item in stack)


def test_profile_chat_tool_limit_blocks_excess_calls_without_failing_execution():
    stack = build_default_middleware(
        summary_model=GenericFakeChatModel(
            messages=iter([AIMessage(content="summary")])
        ),
        projection=FakeProjection(),
        policy=StubPolicyMiddleware(),
        observability=RecordingSink(),
        interrupt_on={},
        budget_profile=PROFILE_CHAT_BUDGET_PROFILE,
    )
    tool_limit = next(x for x in stack if isinstance(x, ToolCallLimitMiddleware))
    calls = [
        {
            "name": "read_personal_evidence",
            "args": {"evidence_id": f"evidence-{index}"},
            "id": f"call-{index}",
        }
        for index in range(8)
    ]

    update = tool_limit.after_model(
        {"messages": [AIMessage(content="", tool_calls=calls)]},
        _runtime(),
    )

    assert update is not None
    assert tool_limit.exit_behavior == "continue"
    assert update["thread_tool_call_count"]["__all__"] == 6
    assert update["run_tool_call_count"]["__all__"] == 8
    blocked = [
        item for item in update["messages"] if isinstance(item, ToolMessage)
    ]
    assert [item.tool_call_id for item in blocked] == ["call-6", "call-7"]


@pytest.mark.asyncio
async def test_token_pressure_is_primary_and_message_count_is_fallback():
    projection = FakeProjection()
    model = GenericFakeChatModel(messages=iter([AIMessage(content="compact summary")]))
    stack = build_default_middleware(
        summary_model=model,
        projection=projection,
        policy=StubPolicyMiddleware(),
        observability=RecordingSink(),
        interrupt_on={},
        context_limit_tokens=100,
    )
    summarizer = next(x for x in stack if isinstance(x, SummarizationMiddleware))
    messages = [HumanMessage(content="x" * 400) for _index in range(3)]

    update = await summarizer.abefore_model({"messages": messages}, _runtime())

    assert update is not None
    assert "compact summary" in update["messages"][1].text
    assert projection.compacted == [_context()]
    assert projection.context_usage[-1][1].threshold_tokens == 70
    assert projection.context_usage[-1][1].current_tokens >= 70

    fallback_projection = FakeProjection()
    fallback = build_default_middleware(
        summary_model=GenericFakeChatModel(messages=iter([AIMessage(content="fallback summary")])),
        projection=fallback_projection,
        policy=StubPolicyMiddleware(),
        observability=RecordingSink(),
        interrupt_on={},
        context_limit_tokens=100000,
    )
    fallback_summarizer = next(x for x in fallback if isinstance(x, SummarizationMiddleware))
    fallback_update = await fallback_summarizer.abefore_model(
        {"messages": [HumanMessage(content="x" * 2000) for _index in range(101)]}, _runtime()
    )
    assert fallback_update is not None


@pytest.mark.asyncio
async def test_context_compaction_has_its_own_agent_trace_identity(tmp_path: Path):
    projection = FakeProjection()
    runtime = SimpleNamespace(
        context=AgentContext(
            workspace_id="w1",
            workspace_root=tmp_path,
            session_id="s1",
            run_id="r1",
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
        )
    )
    middleware = ProjectingSummarizationMiddleware(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="摘要")])),
        trigger=("messages", 2),
        keep=("messages", 1),
        projection=projection,
        threshold_tokens=1,
        trace_writer=AgentTraceWriter(),
        provider_model_id="provider-model-1",
    )

    await middleware.abefore_model(
        {"messages": [
            HumanMessage(content="第一轮"),
            AIMessage(content="第二轮"),
            HumanMessage(content="第三轮"),
        ]},
        runtime,
    )

    rows = read_trace_rows(tmp_path, "s1", "r1")
    assert [row["event_type"] for row in rows] == [
        "model.request", "model.response"
    ]
    assert {row["agent_name"] for row in rows} == {"context_summary"}


@pytest.mark.asyncio
async def test_usage_projects_native_metadata_once_and_estimates_when_missing():
    projection = FakeProjection()
    middleware = UsageProjectionMiddleware(projection)
    native = AIMessage(
        id="message-1",
        content="answer",
        usage_metadata={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
    )

    await middleware.aafter_model({"messages": [HumanMessage(content="q"), native]}, _runtime())
    await middleware.aafter_model({"messages": [native]}, _runtime())

    assert len(projection.usage) == 1
    assert projection.usage[0][1].input_tokens == 11
    assert projection.usage[0][1].estimated is False

    estimated_projection = FakeProjection()
    estimated = UsageProjectionMiddleware(estimated_projection)
    await estimated.aafter_model(
        {"messages": [HumanMessage(content="question"), AIMessage(id="m2", content="answer")]},
        _runtime(),
    )
    assert estimated_projection.usage[0][1].estimated is True
    assert estimated_projection.usage[0][1].total_tokens > 0


@pytest.mark.asyncio
async def test_title_is_projected_once_and_projection_owns_compare_and_swap():
    projection = FakeProjection()
    middleware = SessionTitleMiddleware(projection)
    state = {
        "messages": [
            HumanMessage(content="Explain Python generators and lazy evaluation in detail"),
            AIMessage(content="..."),
        ]
    }

    await middleware.aafter_agent(state, _runtime())
    await middleware.aafter_agent(state, _runtime())

    assert len(projection.titles) == 1
    assert projection.titles[0][1].startswith("Explain Python generators")


@pytest.mark.asyncio
async def test_projection_failure_is_fail_open_and_emits_warning():
    projection = FakeProjection(fail=True)
    middleware = UsageProjectionMiddleware(projection)

    result = await middleware.aafter_model(
        {"messages": [AIMessage(id="m1", content="answer")]}, _runtime()
    )

    assert result is None
    assert projection.warnings[0][1] == "usage_projection_failed"


@pytest.mark.asyncio
async def test_repeated_semantic_progress_raises_stable_error():
    projection = FakeProjection()
    middleware = NoProgressMiddleware(projection, hard_limit=3)
    state = {
        "messages": [
            AIMessage(
                content="checking",
                tool_calls=[{"id": "call-1", "name": "read_source", "args": {"path": "a.md"}}],
            )
        ]
    }

    await middleware.aafter_model(state, _runtime())
    await middleware.aafter_model(state, _runtime())
    with pytest.raises(NoProgressError) as raised:
        await middleware.aafter_model(state, _runtime())

    assert raised.value.code == "no_progress"
