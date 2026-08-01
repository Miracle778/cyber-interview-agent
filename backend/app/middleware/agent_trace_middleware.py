from __future__ import annotations

import asyncio
import re
import time
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware

from app.diagnostics.agent_trace import (
    AgentTraceWriter,
    TraceIdentity,
    stable_trace_operation_id,
)


_SENSITIVE_TEXT = (
    re.compile(r"\bsk-[A-Za-z0-9_-]+\b"),
    re.compile(r"(?i)\bBearer\s+[^\s,;]+"),
    re.compile(r"(?i)\b(?:api[_-]?key|authorization|access[_-]?token)\s*[:=]\s*[^\s,;]+"),
)


def safe_error_payload(error: BaseException) -> dict[str, object]:
    message = str(error)
    for pattern in _SENSITIVE_TEXT:
        message = pattern.sub("[REDACTED]", message)
    payload: dict[str, object] = {
        "error_type": type(error).__name__,
        "message": message,
    }
    code = getattr(error, "code", None)
    if isinstance(code, (str, int)):
        payload["code"] = code
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        payload["status_code"] = status_code
    return payload


class AgentTraceMiddleware(AgentMiddleware):
    """Record model and Tool exchanges without participating in product state."""

    def __init__(
        self,
        writer: AgentTraceWriter,
        *,
        agent_role: str,
        agent_name: str,
        provider_model_id: str,
    ) -> None:
        self._writer = writer
        self._agent_role = agent_role
        self._agent_name = agent_name
        self._provider_model_id = provider_model_id
        self._warned_runs: set[tuple[str, str, str]] = set()

    async def awrap_model_call(self, request, handler):
        invocation_id = str(uuid4())
        context = request.runtime.context
        identity = self._identity(context, invocation_id, "model")
        await self._append(
            context,
            identity,
            "model.request",
            {
                "provider_model_id": self._provider_model_id,
                "messages": request.messages,
                "system_message": request.system_message,
                "tools": request.tools,
                "response_format": request.response_format,
                "model_settings": request.model_settings,
            },
        )
        started_at = time.monotonic()
        try:
            response = await handler(request)
        except BaseException as error:
            await self._append(
                context,
                identity,
                "model.error",
                {
                    **safe_error_payload(error),
                    "duration_ms": max(0, int((time.monotonic() - started_at) * 1000)),
                },
                terminal=True,
            )
            raise
        await self._append(
            context,
            identity,
            "model.response",
            {
                "response": response,
                "duration_ms": max(0, int((time.monotonic() - started_at) * 1000)),
            },
            terminal=True,
        )
        return response

    async def awrap_tool_call(self, request, handler):
        tool_call = request.tool_call
        invocation_id = str(tool_call.get("id") or uuid4())
        context = request.runtime.context
        identity = self._identity(context, invocation_id, "tool")
        await self._append(
            context,
            identity,
            "tool.request",
            {
                "tool_name": tool_call.get("name", ""),
                "args": tool_call.get("args", {}),
            },
        )
        started_at = time.monotonic()
        try:
            result = await handler(request)
        except BaseException as error:
            await self._append(
                context,
                identity,
                "tool.error",
                {
                    **safe_error_payload(error),
                    "duration_ms": max(0, int((time.monotonic() - started_at) * 1000)),
                },
                terminal=True,
            )
            raise
        await self._append(
            context,
            identity,
            "tool.response",
            {
                "result": result,
                "duration_ms": max(0, int((time.monotonic() - started_at) * 1000)),
            },
            terminal=True,
        )
        return result

    def _identity(
        self,
        context,
        invocation_id: str,
        operation_kind: str,
    ) -> TraceIdentity:
        progress_scope = tuple(
            str(item) for item in (getattr(context, "progress_scope", ()) or ())
            if str(item)
        )
        agent_name = self._agent_name
        if (
            self._agent_name in {"review_round_evaluator", "project_answer_evaluator"}
            and len(progress_scope) >= 2
            and progress_scope[1].isdigit()
        ):
            agent_name = f"{self._agent_name}:{int(progress_scope[1])}"
        return TraceIdentity(
            workspace_id=context.workspace_id,
            workspace_root=context.workspace_root,
            session_id=context.session_id,
            run_id=context.run_id,
            agent_role=self._agent_role,
            agent_name=agent_name,
            invocation_id=invocation_id,
            operation_id=stable_trace_operation_id(
                context.run_id,
                invocation_id,
                operation_kind,
            ),
            parent_operation_id=stable_trace_operation_id(
                context.run_id,
                self._agent_role,
                self._agent_name,
                *progress_scope,
                "agent",
            ),
            operation_kind=operation_kind,
        )

    async def _append(
        self,
        context,
        identity: TraceIdentity,
        event_type: str,
        payload: dict[str, object],
        *,
        terminal: bool = False,
    ) -> None:
        try:
            written = await asyncio.to_thread(
                self._writer.append,
                identity,
                event_type,
                payload,
                terminal=terminal,
            )
            if written:
                return
        except BaseException:
            pass
        key = (context.workspace_id, context.session_id, context.run_id)
        if key in self._warned_runs:
            return
        self._warned_runs.add(key)
        warning = getattr(context, "trace_warning", None)
        if warning is not None:
            try:
                warning("agent_trace_write_failed")
            except Exception:
                pass
