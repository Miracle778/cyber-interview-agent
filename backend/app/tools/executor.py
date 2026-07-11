from __future__ import annotations

from pathlib import Path, PureWindowsPath
from time import perf_counter
from typing import Any

from app.runtime.event_stream import EventStream
from app.security.workspace_paths import PathPolicyError
from app.tools.audit import ToolAuditRepository
from app.tools.context import ToolExecutionContext
from app.tools.registry import ToolError, ToolNotAllowedError, ToolRegistry


class ToolExecutionFailedError(ToolError):
    code = "tool_execution_failed"


_SECRET_KEYS = {
    "apikey",
    "authorization",
    "secret",
    "accesstoken",
    "refreshtoken",
    "headers",
}
_BODY_KEYS = {"body", "content", "text", "prompt", "request", "response"}
_DROP = object()


def sanitize_tool_payload(value: Any) -> Any:
    sanitized = _sanitize(value)
    return {} if sanitized is _DROP else sanitized


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            normalized = key.replace("_", "").lower()
            if normalized in _SECRET_KEYS or normalized in _BODY_KEYS:
                continue
            cleaned = _sanitize(nested)
            if cleaned is not _DROP:
                result[key] = cleaned
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for nested in value:
            cleaned = _sanitize(nested)
            if cleaned is not _DROP:
                result.append(cleaned)
        return result
    if isinstance(value, str) and (
        Path(value).is_absolute() or PureWindowsPath(value).is_absolute()
    ):
        return _DROP
    return value


class BoundToolInvoker:
    def __init__(
        self,
        *,
        context: ToolExecutionContext,
        registry: ToolRegistry,
        audit_repository: ToolAuditRepository,
        event_stream: EventStream,
    ) -> None:
        self._context = context
        self._registry = registry
        self._audit_repository = audit_repository
        self._event_stream = event_stream

    async def invoke_tool(
        self, name: str, raw_input: dict[str, object]
    ) -> dict[str, object]:
        started_at = perf_counter()
        scope = self._resource_scope(name)
        resource_path = self._safe_relative_path(raw_input.get("path"))
        audit = await self._audit_repository.start(
            self._context,
            tool_name=name,
            resource_scope=scope,
            resource_path=resource_path,
        )
        await self._event_stream.publish(
            self._context.session_id,
            self._context.run_id,
            "tool.started",
            sanitize_tool_payload(
                {
                    "toolName": name,
                    "resourceScope": scope,
                    "resourcePath": resource_path,
                }
            ),
        )

        try:
            output = self._registry.invoke(name, self._context, raw_input)
        except Exception as error:
            exposed = self._stable_error(error)
            latency_ms = self._latency_ms(started_at)
            await self._audit_repository.fail(
                audit.id, error_code=exposed.code, latency_ms=latency_ms
            )
            await self._event_stream.publish(
                self._context.session_id,
                self._context.run_id,
                "tool.failed",
                sanitize_tool_payload(
                    {
                        "toolName": name,
                        "resourceScope": scope,
                        "resourcePath": resource_path,
                        "code": exposed.code,
                        "latencyMs": latency_ms,
                    }
                ),
            )
            if exposed is error:
                raise
            raise exposed from error

        latency_ms = self._latency_ms(started_at)
        resource_sha256 = output.get("sha256")
        safe_sha256 = resource_sha256 if isinstance(resource_sha256, str) else None
        await self._audit_repository.complete(
            audit.id,
            latency_ms=latency_ms,
            resource_sha256=safe_sha256,
        )
        await self._event_stream.publish(
            self._context.session_id,
            self._context.run_id,
            "tool.completed",
            sanitize_tool_payload(
                {
                    "toolName": name,
                    "resourceScope": scope,
                    "resourcePath": resource_path,
                    "resourceSha256": safe_sha256,
                    "byteCount": output.get("byte_count"),
                    "latencyMs": latency_ms,
                }
            ),
        )
        return output

    def _resource_scope(self, name: str) -> str | None:
        try:
            return self._registry.get(name).required_scope
        except ToolNotAllowedError:
            return None

    @staticmethod
    def _safe_relative_path(value: object) -> str | None:
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
    def _stable_error(error: Exception) -> Exception:
        if isinstance(error, (ToolError, PathPolicyError)):
            return error
        return ToolExecutionFailedError("Tool execution failed")

    @staticmethod
    def _latency_ms(started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))
