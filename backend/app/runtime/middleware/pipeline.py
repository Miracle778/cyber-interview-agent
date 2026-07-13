from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from app.runtime.middleware.types import (
    MiddlewareConfig,
    MiddlewareLayer,
    RuntimeMiddleware,
)


_ORDER_RANGES = {
    MiddlewareLayer.GUARD: (100, 199),
    MiddlewareLayer.INVOCATION: (200, 299),
    MiddlewareLayer.POST_PROCESSING: (300, 399),
}


class RuntimeMiddlewarePipeline:
    def __init__(
        self,
        middleware: Sequence[RuntimeMiddleware],
        config: MiddlewareConfig,
    ) -> None:
        self._validate(middleware)
        self._middleware = tuple(sorted(middleware, key=lambda item: item.order))
        self._config = config

    @staticmethod
    def _validate(middleware: Sequence[RuntimeMiddleware]) -> None:
        ids: set[str] = set()
        orders: set[tuple[MiddlewareLayer, int]] = set()
        for item in middleware:
            if item.middleware_id in ids:
                raise ValueError(f"duplicate middleware_id: {item.middleware_id}")
            ids.add(item.middleware_id)
            order_key = (item.layer, item.order)
            if order_key in orders:
                raise ValueError(
                    f"duplicate middleware order in {item.layer.value}: {item.order}"
                )
            orders.add(order_key)
            lower, upper = _ORDER_RANGES[item.layer]
            if not lower <= item.order <= upper:
                raise ValueError(
                    f"middleware {item.middleware_id} order {item.order} is outside "
                    f"{item.layer.value} range {lower}..{upper}"
                )

    def _enabled(self, *layers: MiddlewareLayer) -> tuple[RuntimeMiddleware, ...]:
        requested = frozenset(layers) & self._config.enabled_layers
        return tuple(
            item
            for item in self._middleware
            if item.layer in requested
            and item.middleware_id not in self._config.disabled_middleware
        )

    async def wrap_model(self, context, invocation, call_next):
        handler = call_next
        for item in reversed(
            self._enabled(MiddlewareLayer.GUARD, MiddlewareLayer.INVOCATION)
        ):
            previous = handler

            async def wrapped(value, *, current=item, next_handler=previous):
                return await current.wrap_model(context, value, next_handler)

            handler = wrapped
        return await handler(invocation)

    async def wrap_tool(self, context, invocation, call_next):
        handler = call_next
        for item in reversed(
            self._enabled(MiddlewareLayer.GUARD, MiddlewareLayer.INVOCATION)
        ):
            previous = handler

            async def wrapped(value, *, current=item, next_handler=previous):
                return await current.wrap_tool(context, value, next_handler)

            handler = wrapped
        return await handler(invocation)

    async def after_message(self, context, message) -> None:
        for item in self._enabled(MiddlewareLayer.POST_PROCESSING):
            await item.after_message(context, message)
