from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path, PureWindowsPath
from time import perf_counter

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from app.agents.context import AgentContext
from app.tools.audit import canonical_digest
from app.tools.context import ToolExecutionContext

ToolEventPublisher = Callable[
    [str, str | None, str, dict[str, object]], Awaitable[None]
]


class ToolPolicyMiddleware(AgentMiddleware):
    def __init__(
        self,
        *,
        audit,
        required_scopes: dict[str, str],
        publish_event: ToolEventPublisher | None = None,
    ) -> None:
        self._audit = audit
        self._required_scopes = dict(required_scopes)
        self._publish_event = publish_event

    async def awrap_tool_call(self, request, handler):
        context: AgentContext = request.runtime.context
        call = request.tool_call
        name = call["name"]
        tool_call_id = call.get("id")
        args = call.get("args", {}) or {}
        input_digest = canonical_digest(args)
        agent_role = getattr(context, "agent_role", None)
        scope = self._required_scopes.get(name)
        safe_path = self._safe_path(args.get("path"))

        if name not in context.allowed_tools or (
            scope is not None and scope not in context.allowed_scopes
        ):
            await self._audit.deny(
                self._audit_context(context),
                tool_name=name,
                resource_scope=scope,
                resource_path=safe_path,
                tool_call_id=tool_call_id,
                agent_role=agent_role,
                input_digest=input_digest,
            )
            await self._publish(
                context,
                "agent.tool.failed",
                self._payload(context, tool_call_id, name, status="failed",
                              result_count=0, error_code="tool_not_allowed"),
            )
            return ToolMessage(
                content="tool_not_allowed",
                name=name,
                tool_call_id=tool_call_id,
                status="error",
            )

        started_at = perf_counter()
        audit = await self._audit.start(
            self._audit_context(context),
            tool_name=name,
            resource_scope=scope,
            resource_path=safe_path,
            tool_call_id=tool_call_id,
            agent_role=agent_role,
            input_digest=input_digest,
        )
        await self._publish(
            context,
            "agent.tool.started",
            self._payload(context, tool_call_id, name, status="started",
                          result_count=0, error_code=None),
        )
        try:
            result = await handler(request)
        except Exception as error:
            error_code = str(getattr(error, "code", "tool_execution_failed"))
            await self._audit.fail(
                audit.id,
                error_code=error_code,
                latency_ms=self._latency_ms(started_at),
                result_digest=None,
            )
            await self._publish(
                context,
                "agent.tool.failed",
                self._payload(context, tool_call_id, name, status="failed",
                              result_count=0, error_code=error_code),
            )
            raise
        result_digest = self._result_digest(result)
        result_count = self._result_count(result)
        await self._audit.complete(
            audit.id,
            latency_ms=self._latency_ms(started_at),
            resource_sha256=None,
            result_digest=result_digest,
        )
        await self._publish(
            context,
            "agent.tool.completed",
            self._payload(context, tool_call_id, name, status="completed",
                          result_count=result_count, error_code=None),
        )
        return result

    async def _publish(
        self,
        context: AgentContext,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        if self._publish_event is None:
            return
        await self._publish_event(
            context.session_id, context.run_id, event_type, payload
        )

    @staticmethod
    def _payload(
        context: AgentContext,
        tool_call_id: str | None,
        tool_name: str,
        *,
        status: str,
        result_count: int,
        error_code: str | None,
    ) -> dict[str, object]:
        # Only safe correlation fields; never raw arguments, results, or model
        # reasoning. Purpose is the public tool name label.
        return {
            "executionId": context.run_id,
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "purpose": tool_name,
            "status": status,
            "resultCount": result_count,
            "errorCode": error_code,
        }

    @staticmethod
    def _result_digest(result: object) -> str | None:
        content = getattr(result, "content", None)
        if content is None:
            return None
        return canonical_digest(str(content))

    @staticmethod
    def _result_count(result: object) -> int:
        for attr in ("items", "results", "records"):
            value = getattr(result, attr, None)
            if isinstance(value, (list, tuple)):
                return len(value)
        payload = getattr(result, "artifact", None)
        if isinstance(payload, dict) and "items" in payload:
            return len(payload["items"])
        return 0

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
            agent_role=getattr(context, "agent_role", None),
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
