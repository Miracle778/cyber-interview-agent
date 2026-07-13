from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware


class LangChainRuntimeMiddlewareAdapter(AgentMiddleware):
    def __init__(self, pipeline, context_factory) -> None:
        self._pipeline = pipeline
        self._context_factory = context_factory

    async def awrap_model_call(self, request, handler):
        context, invocation = self._context_factory.model(request)
        return await self._pipeline.wrap_model(
            context, invocation, lambda _invocation: handler(request)
        )

    async def awrap_tool_call(self, request, handler):
        context, invocation = self._context_factory.tool(request)
        return await self._pipeline.wrap_tool(
            context, invocation, lambda _invocation: handler(request)
        )
