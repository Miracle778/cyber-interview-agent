from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol


class MiddlewareLayer(StrEnum):
    GUARD = "guard"
    INVOCATION = "invocation"
    POST_PROCESSING = "post_processing"


@dataclass(frozen=True, slots=True)
class MiddlewareConfig:
    enabled_layers: frozenset[MiddlewareLayer] = frozenset(MiddlewareLayer)
    disabled_middleware: frozenset[str] = frozenset()
    soft_context_tokens: int = 12_000
    hard_context_tokens: int = 16_000
    max_graph_steps: int = 40
    max_model_calls: int = 12
    max_tool_calls: int = 20
    max_run_seconds: int = 300
    repeat_soft_limit: int = 3
    repeat_hard_limit: int = 4

    def __post_init__(self) -> None:
        values = (
            self.soft_context_tokens,
            self.hard_context_tokens,
            self.max_graph_steps,
            self.max_model_calls,
            self.max_tool_calls,
            self.max_run_seconds,
            self.repeat_soft_limit,
            self.repeat_hard_limit,
        )
        if any(value <= 0 for value in values):
            raise ValueError("middleware budgets must be positive")
        if self.soft_context_tokens >= self.hard_context_tokens:
            raise ValueError("soft context budget must be below hard context budget")
        if self.repeat_soft_limit >= self.repeat_hard_limit:
            raise ValueError("repeat soft limit must be below hard limit")


@dataclass(frozen=True, slots=True)
class MiddlewareContext:
    workspace_id: str
    session_id: str
    run_id: str
    graph_id: str
    graph_version: int


@dataclass(frozen=True, slots=True)
class ModelInvocation:
    operation_key: str
    role: str
    provider_id: str
    provider_model_id: str
    messages: tuple[Any, ...]
    purpose: Literal["business", "context_summary", "session_title"] = "business"
    is_stream: bool = False


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    operation_key: str
    tool_name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    context_tokens: int
    latency_ms: int
    estimated: bool


@dataclass(frozen=True, slots=True)
class TodoCandidate:
    source_message_ids: tuple[str, ...]
    suggested_title: str
    due_at: str | None
    related_entity_type: str | None
    related_entity_id: str | None
    confidence: float


class RuntimeGuardError(RuntimeError):
    STABLE_CODES = frozenset(
        {
            "loop_detected",
            "no_progress",
            "step_budget_exceeded",
            "token_budget_exceeded",
            "run_timeout",
        }
    )

    def __init__(self, code: str, message: str) -> None:
        if code not in self.STABLE_CODES:
            raise ValueError(f"unsupported runtime guard code: {code}")
        self.code = code
        super().__init__(message)


CallNext = Callable[[Any], Awaitable[Any]]


class RuntimeMiddleware(Protocol):
    middleware_id: str
    layer: MiddlewareLayer
    order: int

    async def wrap_model(self, context, invocation, call_next): ...
    async def wrap_tool(self, context, invocation, call_next): ...
    async def after_message(self, context, message): ...


class BaseRuntimeMiddleware:
    async def wrap_model(self, context, invocation, call_next: CallNext):
        return await call_next(invocation)

    async def wrap_tool(self, context, invocation, call_next: CallNext):
        return await call_next(invocation)

    async def after_message(self, context, message) -> None:
        return None
