from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from typing import Any

from app.runtime.middleware.telemetry import estimate_message_tokens
from app.runtime.middleware.types import (
    BaseRuntimeMiddleware,
    MiddlewareConfig,
    MiddlewareLayer,
    RuntimeGuardError,
)


def compact_messages(
    *,
    messages: Sequence[Any],
    summary: str,
    keep_recent: int,
    protected_refs: Sequence[str] = (),
) -> tuple[Any, ...]:
    system = tuple(
        item for item in messages if isinstance(item, dict) and item.get("role") == "system"
    )
    non_system = tuple(item for item in messages if item not in system)
    reference_text = "\n".join(protected_refs)
    summary_message = {
        "role": "system",
        "content": f"会话压缩摘要：\n{summary}\n保留引用：\n{reference_text}",
    }
    return (summary_message, *system, *non_system[-keep_recent:])


class ContextBudgetMiddleware(BaseRuntimeMiddleware):
    middleware_id = "context_budget"
    layer = MiddlewareLayer.GUARD
    order = 120

    def __init__(
        self,
        *,
        config: MiddlewareConfig,
        summarize_context: Callable[[Sequence[Any], str | None], Awaitable[str]],
        existing_summary: Callable[[Any], str | None],
        save_summary: Callable[[Any, str], None] = lambda context, summary: None,
        publish_warning: Callable[[str], None],
        keep_recent: int = 4,
    ) -> None:
        self._config = config
        self._summarize_context = summarize_context
        self._existing_summary = existing_summary
        self._save_summary = save_summary
        self._publish_warning = publish_warning
        self._keep_recent = keep_recent

    async def wrap_model(self, context, invocation, call_next):
        if invocation.purpose != "business":
            return await call_next(invocation)
        original_tokens = estimate_message_tokens(invocation.messages)
        if original_tokens < self._config.soft_context_tokens:
            return await call_next(invocation)
        try:
            summary = await self._summarize_context(
                invocation.messages, self._existing_summary(context)
            )
            messages = compact_messages(
                messages=invocation.messages,
                summary=summary,
                keep_recent=self._keep_recent,
            )
            self._save_summary(context, summary)
        except Exception:
            self._publish_warning("context_compression_failed")
            if original_tokens >= self._config.hard_context_tokens:
                raise RuntimeGuardError(
                    "token_budget_exceeded", "上下文已超过运行预算"
                )
            return await call_next(invocation)
        if estimate_message_tokens(messages) >= self._config.hard_context_tokens:
            raise RuntimeGuardError("token_budget_exceeded", "上下文已超过运行预算")
        return await call_next(replace(invocation, messages=messages))
