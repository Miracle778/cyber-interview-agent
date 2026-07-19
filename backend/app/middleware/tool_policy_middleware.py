from __future__ import annotations

from pathlib import Path, PureWindowsPath
from time import perf_counter

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from app.agents.context import AgentContext
from app.tools.context import ToolExecutionContext


class ToolPolicyMiddleware(AgentMiddleware):
    def __init__(self, *, audit, required_scopes: dict[str, str]) -> None:
        self._audit = audit
        self._required_scopes = dict(required_scopes)

    async def awrap_tool_call(self, request, handler):
        context: AgentContext = request.runtime.context
        call = request.tool_call
        name = call["name"]
        scope = self._required_scopes.get(name)
        if name not in context.allowed_tools or (
            scope is not None and scope not in context.allowed_scopes
        ):
            return ToolMessage(
                content="tool_not_allowed",
                name=name,
                tool_call_id=call["id"],
                status="error",
            )

        started_at = perf_counter()
        audit = await self._audit.start(
            self._audit_context(context),
            tool_name=name,
            resource_scope=scope,
            resource_path=self._safe_path(call.get("args", {}).get("path")),
        )
        try:
            result = await handler(request)
        except Exception as error:
            await self._audit.fail(
                audit.id,
                error_code=str(getattr(error, "code", "tool_execution_failed")),
                latency_ms=self._latency_ms(started_at),
            )
            raise
        await self._audit.complete(
            audit.id,
            latency_ms=self._latency_ms(started_at),
            resource_sha256=None,
        )
        return result

    @staticmethod
    def _audit_context(context: AgentContext) -> ToolExecutionContext:
        return ToolExecutionContext(
            workspace_id=context.workspace_id,
            workspace_root=context.workspace_root,
            session_id=context.session_id,
            run_id=context.run_id,
            graph_id="agent",
            graph_version=1,
            allowed_tools=context.allowed_tools,
            allowed_scopes=context.allowed_scopes,
        )

    @staticmethod
    def _safe_path(value: object) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        path = Path(value)
        if (
            path.is_absolute()
            or PureWindowsPath(value).is_absolute()
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            return None
        return value

    @staticmethod
    def _latency_ms(started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))
