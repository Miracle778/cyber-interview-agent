import pytest

from app.runtime.middleware.context_budget import (
    ContextBudgetMiddleware,
    compact_messages,
)
from app.runtime.middleware.types import (
    MiddlewareConfig,
    MiddlewareContext,
    ModelInvocation,
    RuntimeGuardError,
)


def test_compaction_keeps_system_recent_messages_and_references():
    messages = (
        {"role": "system", "content": "system rules"},
        *({"role": "user", "content": f"old-{index}"} for index in range(8)),
        {"role": "assistant", "content": "recent"},
    )
    compacted = compact_messages(
        messages=messages,
        summary="已掌握缓存穿透定义",
        keep_recent=4,
        protected_refs=("q1", "draft1"),
    )
    assert compacted[0]["role"] == "system"
    assert "已掌握缓存穿透定义" in str(compacted)
    assert "q1" in str(compacted) and "draft1" in str(compacted)
    assert "recent" in str(compacted)


@pytest.mark.asyncio
async def test_hard_budget_raises_stable_error_after_compaction():
    async def summarize(messages, existing):
        return "x" * 200

    middleware = ContextBudgetMiddleware(
        config=MiddlewareConfig(soft_context_tokens=10, hard_context_tokens=20),
        summarize_context=summarize,
        existing_summary=lambda context: None,
        publish_warning=lambda code: None,
    )
    invocation = ModelInvocation(
        "op1", "answer", "p1", "m1", ({"role": "user", "content": "x" * 200},)
    )

    async def call_next(value):
        return value

    with pytest.raises(RuntimeGuardError) as caught:
        await middleware.wrap_model(
            MiddlewareContext("w1", "s1", "r1", "review.single", 1),
            invocation,
            call_next,
        )
    assert caught.value.code == "token_budget_exceeded"


@pytest.mark.asyncio
async def test_soft_budget_saves_summary_and_passes_compacted_messages():
    saved: list[str] = []

    async def summarize(messages, existing):
        return "持久化摘要"

    middleware = ContextBudgetMiddleware(
        config=MiddlewareConfig(soft_context_tokens=10, hard_context_tokens=100),
        summarize_context=summarize,
        existing_summary=lambda context: None,
        save_summary=lambda context, summary: saved.append(summary),
        publish_warning=lambda code: None,
    )
    invocation = ModelInvocation(
        "op1", "answer", "p1", "m1", ({"role": "user", "content": "x" * 80},)
    )

    async def call_next(value):
        return value.messages

    result = await middleware.wrap_model(
        MiddlewareContext("w1", "s1", "r1", "review.single", 1),
        invocation,
        call_next,
    )
    assert saved == ["持久化摘要"]
    assert "持久化摘要" in str(result)
