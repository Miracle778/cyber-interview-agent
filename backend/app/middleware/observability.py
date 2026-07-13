from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from langchain.agents.middleware import AgentMiddleware


@dataclass(frozen=True, slots=True)
class TraceContext:
    workspace_id: str
    session_id: str
    run_id: str
    graph_id: str
    graph_version: int


class ObservabilitySink(Protocol):
    def span(self, name, *, context, attributes, links=()): ...


class ObservabilityMiddleware(AgentMiddleware):
    """Trace official model calls with identifiers and counts, never content."""

    def __init__(self, sink: ObservabilitySink) -> None:
        self._sink = sink

    async def awrap_model_call(self, request, handler):
        context = request.runtime.context
        trace_context = TraceContext(
            workspace_id=context.workspace_id,
            session_id=context.session_id,
            run_id=context.run_id,
            graph_id="agent",
            graph_version=1,
        )
        attributes = {
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model_type": type(request.model).__name__,
            "gen_ai.input.messages": len(request.messages),
        }
        with self._sink.span(
            "agent.model.call",
            context=trace_context,
            attributes=attributes,
        ) as span:
            try:
                return await handler(request)
            except Exception as error:
                span.record_error(getattr(error, "code", type(error).__name__))
                raise
