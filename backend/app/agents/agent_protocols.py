from __future__ import annotations

from typing import Any, Protocol

from app.agents.context import AgentContext


class AgentRunnable(Protocol):
    async def ainvoke(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
        *,
        context: AgentContext | None = None,
    ) -> dict[str, Any]: ...


class StreamingAgentRunnable(AgentRunnable, Protocol):
    def astream(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
        *,
        context: AgentContext | None = None,
        **kwargs: Any,
    ): ...
