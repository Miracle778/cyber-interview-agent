from dataclasses import dataclass

import pytest

from app.runtime.middleware.pipeline import RuntimeMiddlewarePipeline
from app.runtime.middleware.types import (
    BaseRuntimeMiddleware,
    MiddlewareConfig,
    MiddlewareContext,
    MiddlewareLayer,
    ModelInvocation,
)
from app.runtime.graph_registry import GraphDefinition


def context() -> MiddlewareContext:
    return MiddlewareContext("w1", "s1", "r1", "review.single", 1)


def invocation() -> ModelInvocation:
    return ModelInvocation("op1", "agent_chat", "p1", "m1", ())


@dataclass
class RecordingMiddleware(BaseRuntimeMiddleware):
    middleware_id: str
    layer: MiddlewareLayer
    order: int
    events: list[str]

    async def wrap_model(self, context, invocation, call_next):
        self.events.append(f"{self.middleware_id}.before")
        result = await call_next(invocation)
        self.events.append(f"{self.middleware_id}.after")
        return result


@pytest.mark.asyncio
async def test_model_wrappers_use_layer_ordered_onion():
    events: list[str] = []
    pipeline = RuntimeMiddlewarePipeline(
        (
            RecordingMiddleware("usage", MiddlewareLayer.INVOCATION, 210, events),
            RecordingMiddleware("guard", MiddlewareLayer.GUARD, 110, events),
        ),
        MiddlewareConfig(),
    )

    async def call_model(value):
        events.append("model")
        return "ok"

    assert await pipeline.wrap_model(context(), invocation(), call_model) == "ok"
    assert events == [
        "guard.before",
        "usage.before",
        "model",
        "usage.after",
        "guard.after",
    ]


@pytest.mark.asyncio
async def test_one_middleware_can_be_disabled_without_disabling_layer():
    events: list[str] = []
    pipeline = RuntimeMiddlewarePipeline(
        (
            RecordingMiddleware("usage", MiddlewareLayer.INVOCATION, 210, events),
            RecordingMiddleware("trace", MiddlewareLayer.INVOCATION, 220, events),
        ),
        MiddlewareConfig(disabled_middleware=frozenset({"usage"})),
    )

    async def call_model(value):
        events.append("model")
        return "ok"

    await pipeline.wrap_model(context(), invocation(), call_model)
    assert events == ["trace.before", "model", "trace.after"]


@pytest.mark.parametrize(
    ("middleware", "message"),
    [
        (
            (
                RecordingMiddleware("same", MiddlewareLayer.GUARD, 110, []),
                RecordingMiddleware("same", MiddlewareLayer.INVOCATION, 210, []),
            ),
            "duplicate middleware_id: same",
        ),
        (
            (
                RecordingMiddleware("one", MiddlewareLayer.GUARD, 110, []),
                RecordingMiddleware("two", MiddlewareLayer.GUARD, 110, []),
            ),
            "duplicate middleware order in guard: 110",
        ),
        (
            (RecordingMiddleware("wrong", MiddlewareLayer.GUARD, 210, []),),
            "middleware wrong order 210 is outside guard range 100..199",
        ),
    ],
)
def test_pipeline_rejects_ambiguous_registration(middleware, message):
    with pytest.raises(ValueError, match=message.replace(".", r"\.")):
        RuntimeMiddlewarePipeline(middleware, MiddlewareConfig())


@pytest.mark.asyncio
async def test_base_middleware_passes_through_unimplemented_hooks():
    class MessageOnlyMiddleware(BaseRuntimeMiddleware):
        middleware_id = "message_only"
        layer = MiddlewareLayer.POST_PROCESSING
        order = 310

    middleware = MessageOnlyMiddleware()

    async def call_next(value):
        return value.operation_key

    assert await middleware.wrap_model(context(), invocation(), call_next) == "op1"
    assert await middleware.after_message(context(), object()) is None


def test_graph_definition_has_safe_middleware_defaults():
    definition = GraphDefinition(
        graph_id="test.echo",
        graph_version=1,
        factory=lambda context: object(),
        required_model_roles=frozenset(),
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )

    assert definition.middleware_config == MiddlewareConfig()
