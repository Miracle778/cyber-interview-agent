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
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.context import AgentContext
from app.middleware.middleware_stack import build_default_middleware
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
