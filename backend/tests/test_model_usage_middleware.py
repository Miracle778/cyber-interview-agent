import pytest

from app.providers.chat_gateway import (
    ProviderModelResult,
    ProviderStreamChunk,
    ProviderUsage,
)
from app.runtime.middleware.repository import RuntimeMiddlewareRepository
from app.runtime.middleware.telemetry import (
    ModelUsageMiddleware,
    estimate_message_tokens,
)
from app.runtime.middleware.types import MiddlewareContext, ModelInvocation
from app.db.runtime_database import connect_runtime_database
from app.runtime.repository import RuntimeRepository


def setup_runtime(tmp_path):
    connection = connect_runtime_database(tmp_path)
    runtime = RuntimeRepository(connection)
    session = runtime.create_session(
        workspace_id="w1", graph_id="review.single", graph_version=1, title="新会话"
    )
    run = runtime.create_run(session.id, input={}, model_bindings={})
    return connection, MiddlewareContext("w1", session.id, run.id, "review.single", 1)


@pytest.mark.asyncio
async def test_native_usage_is_recorded_once(tmp_path):
    connection, context = setup_runtime(tmp_path)
    middleware = ModelUsageMiddleware(RuntimeMiddlewareRepository(connection))
    invocation = ModelInvocation("model:answer:1", "answer", "p1", "m1", ())

    async def call_next(value):
        return ProviderModelResult("ok", ProviderUsage(50, 10))

    result = await middleware.wrap_model(context, invocation, call_next)
    assert result.value == "ok"
    aggregate = RuntimeMiddlewareRepository(connection).aggregate_session_usage(
        context.session_id
    )
    assert aggregate.total_tokens == 60
    assert aggregate.estimated_count == 0


@pytest.mark.asyncio
async def test_missing_usage_uses_deterministic_estimate(tmp_path):
    connection, context = setup_runtime(tmp_path)
    middleware = ModelUsageMiddleware(RuntimeMiddlewareRepository(connection))
    messages = ({"role": "user", "content": "abcd"},)
    invocation = ModelInvocation("model:answer:1", "answer", "p1", "m1", messages)

    async def call_next(value):
        return ProviderModelResult("xy", None)

    await middleware.wrap_model(context, invocation, call_next)
    aggregate = RuntimeMiddlewareRepository(connection).aggregate_session_usage(
        context.session_id
    )
    assert aggregate.input_tokens == estimate_message_tokens(messages)
    assert aggregate.output_tokens > 0
    assert aggregate.estimated_count == 1


@pytest.mark.asyncio
async def test_stream_usage_is_finalized_once_after_iteration(tmp_path):
    connection, context = setup_runtime(tmp_path)
    middleware = ModelUsageMiddleware(RuntimeMiddlewareRepository(connection))
    invocation = ModelInvocation(
        "model:report:1", "report", "p1", "m1", (), is_stream=True
    )

    async def chunks():
        yield ProviderStreamChunk("甲")
        yield ProviderStreamChunk("乙", ProviderUsage(40, 8))

    async def call_next(value):
        return chunks()

    stream = await middleware.wrap_model(context, invocation, call_next)
    assert [chunk.text async for chunk in stream] == ["甲", "乙"]
    aggregate = RuntimeMiddlewareRepository(connection).aggregate_session_usage(
        context.session_id
    )
    assert aggregate.call_count == 1
    assert aggregate.total_tokens == 48
