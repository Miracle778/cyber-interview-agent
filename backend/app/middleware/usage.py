from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langchain_core.messages.utils import count_tokens_approximately

from app.agents.context import AgentContext


@dataclass(frozen=True, slots=True)
class UsageProjection:
    operation_key: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated: bool


@dataclass(frozen=True, slots=True)
class ContextUsageProjection:
    current_tokens: int
    threshold_tokens: int
    estimated: bool = True


class MiddlewareProjection(Protocol):
    def record_usage(self, context: AgentContext, usage: UsageProjection) -> bool: ...

    def ensure_title(self, context: AgentContext, candidate: str) -> bool: ...

    def observe_progress(self, context: AgentContext, fingerprint: str) -> int: ...

    def warning(self, context: AgentContext, code: str) -> None: ...

    def mark_context_compacted(self, context: AgentContext) -> bool: ...

    def record_context_usage(
        self, context: AgentContext, usage: ContextUsageProjection
    ) -> bool: ...


class UsageProjectionMiddleware(AgentMiddleware):
    """Project model usage without introducing a second invocation protocol."""

    def __init__(self, projection: MiddlewareProjection) -> None:
        self._projection = projection
        self._seen: set[tuple[str, str]] = set()

    async def aafter_model(self, state, runtime) -> None:
        messages = state.get("messages", ())
        message = next(
            (item for item in reversed(messages) if isinstance(item, AIMessage)),
            None,
        )
        if message is None:
            return None

        operation_key = message.id or _message_operation_key(message)
        seen_key = (runtime.context.run_id, operation_key)
        if seen_key in self._seen:
            return None

        metadata = message.usage_metadata
        if metadata:
            input_tokens = int(metadata.get("input_tokens", 0))
            output_tokens = int(metadata.get("output_tokens", 0))
            total_tokens = int(
                metadata.get("total_tokens", input_tokens + output_tokens)
            )
            estimated = False
        else:
            input_tokens = count_tokens_approximately(messages[:-1])
            output_tokens = count_tokens_approximately([message])
            total_tokens = input_tokens + output_tokens
            estimated = True

        usage = UsageProjection(
            operation_key=operation_key,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated=estimated,
        )
        try:
            self._projection.record_usage(runtime.context, usage)
        except Exception:
            self._projection.warning(runtime.context, "usage_projection_failed")
            return None
        self._seen.add(seen_key)
        return None


def _message_operation_key(message: AIMessage) -> str:
    from hashlib import sha256

    body = f"{message.text}|{message.tool_calls}".encode("utf-8")
    return sha256(body).hexdigest()
