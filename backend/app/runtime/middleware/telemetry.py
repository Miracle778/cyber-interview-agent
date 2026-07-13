from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from app.providers.chat_gateway import ProviderModelResult
from app.runtime.middleware.repository import RuntimeMiddlewareRepository
from app.runtime.middleware.observability import (
    NoopObservabilitySink,
    ObservabilitySink,
    TraceContext,
)
from app.runtime.middleware.types import (
    BaseRuntimeMiddleware,
    MiddlewareLayer,
    ModelUsage,
)


def normalize_message_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("content", ""))
    return str(getattr(value, "content", value))


def estimate_text_tokens(text: str) -> int:
    return max(1, (len(text.encode("utf-8")) + 3) // 4)


def estimate_message_tokens(messages: Sequence[Any]) -> int:
    return sum(estimate_text_tokens(normalize_message_text(item)) + 4 for item in messages)


class ModelUsageMiddleware(BaseRuntimeMiddleware):
    middleware_id = "model_usage"
    layer = MiddlewareLayer.INVOCATION
    order = 210

    def __init__(
        self,
        repository: RuntimeMiddlewareRepository,
        *,
        defer_writes: bool = False,
        observability: ObservabilitySink | None = None,
    ) -> None:
        self._repository = repository
        self._defer_writes = defer_writes
        self._pending: list[dict[str, Any]] = []
        self._observability = observability or NoopObservabilitySink()

    def _record(self, **values) -> None:
        if self._defer_writes:
            self._pending.append(values)
            return
        self._repository.record_usage(**values)

    def flush(self) -> None:
        pending, self._pending = self._pending, []
        for values in pending:
            self._repository.record_usage(**values)

    async def wrap_model(self, context, invocation, call_next):
        if invocation.is_stream:
            return await self._wrap_stream(context, invocation, call_next)
        started = time.monotonic()
        with self._observability.span(
            "model.invoke",
            context=self._trace_context(context),
            attributes=self._span_attributes(invocation),
        ) as span:
            try:
                result = await call_next(invocation)
            except Exception as error:
                latency_ms = int((time.monotonic() - started) * 1000)
                self._record(
                    workspace_id=context.workspace_id,
                    session_id=context.session_id,
                    run_id=context.run_id,
                    operation_key=invocation.operation_key,
                    role=invocation.role,
                    provider_id=invocation.provider_id,
                    provider_model_id=invocation.provider_model_id,
                    usage=ModelUsage(
                        input_tokens=estimate_message_tokens(invocation.messages),
                        output_tokens=0,
                        total_tokens=estimate_message_tokens(invocation.messages),
                        context_tokens=estimate_message_tokens(invocation.messages),
                        latency_ms=latency_ms,
                        estimated=True,
                    ),
                    status="failed",
                    error_code=str(getattr(error, "code", "provider_error")),
                )
                span.record_error(str(getattr(error, "code", "provider_error")))
                raise

            latency_ms = int((time.monotonic() - started) * 1000)
            native = result.usage if isinstance(result, ProviderModelResult) else None
            if native is None:
                input_tokens = estimate_message_tokens(invocation.messages)
                output_tokens = estimate_text_tokens(
                    normalize_message_text(getattr(result, "value", result))
                )
                estimated = True
            else:
                input_tokens = native.input_tokens
                output_tokens = native.output_tokens
                estimated = False
            self._record(
                workspace_id=context.workspace_id,
                session_id=context.session_id,
                run_id=context.run_id,
                operation_key=invocation.operation_key,
                role=invocation.role,
                provider_id=invocation.provider_id,
                provider_model_id=invocation.provider_model_id,
                usage=ModelUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    context_tokens=estimate_message_tokens(invocation.messages),
                    latency_ms=latency_ms,
                    estimated=estimated,
                ),
                status="completed",
            )
            span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
            span.set_attribute("cyber.usage.estimated", estimated)
            span.set_attribute("cyber.latency_ms", latency_ms)
            span.set_attribute("cyber.status", "completed")
            return result

    async def _wrap_stream(self, context, invocation, call_next):
        async def tracked_stream():
            started = time.monotonic()
            native = None
            output_parts: list[str] = []
            status = "completed"
            error_code = None
            with self._observability.span(
                "model.stream",
                context=self._trace_context(context),
                attributes=self._span_attributes(invocation),
            ) as span:
                try:
                    result = await call_next(invocation)
                    async for chunk in result:
                        output_parts.append(str(getattr(chunk, "text", "")))
                        if getattr(chunk, "usage", None) is not None:
                            native = chunk.usage
                        yield chunk
                except BaseException as error:
                    status = "failed"
                    error_code = str(getattr(error, "code", "provider_error"))
                    span.record_error(error_code)
                    raise
                finally:
                    input_tokens = native.input_tokens if native else estimate_message_tokens(invocation.messages)
                    output_tokens = native.output_tokens if native else estimate_text_tokens("".join(output_parts))
                    latency_ms = int((time.monotonic() - started) * 1000)
                    self._record(
                        workspace_id=context.workspace_id,
                        session_id=context.session_id,
                        run_id=context.run_id,
                        operation_key=invocation.operation_key,
                        role=invocation.role,
                        provider_id=invocation.provider_id,
                        provider_model_id=invocation.provider_model_id,
                        usage=ModelUsage(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            total_tokens=input_tokens + output_tokens,
                            context_tokens=estimate_message_tokens(invocation.messages),
                            latency_ms=latency_ms,
                            estimated=native is None,
                        ),
                        status=status,
                        error_code=error_code,
                    )
                    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
                    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
                    span.set_attribute("cyber.usage.estimated", native is None)
                    span.set_attribute("cyber.latency_ms", latency_ms)
                    span.set_attribute("cyber.status", status)
        return tracked_stream()

    @staticmethod
    def _trace_context(context) -> TraceContext:
        return TraceContext(
            context.workspace_id,
            context.session_id,
            context.run_id,
            context.graph_id,
            context.graph_version,
        )

    @staticmethod
    def _span_attributes(invocation) -> dict[str, str]:
        return {
            "gen_ai.operation.name": "stream" if invocation.is_stream else "invoke",
            "gen_ai.request.model": invocation.provider_model_id,
            "cyber.provider.id": invocation.provider_id,
            "cyber.model.role": invocation.role,
            "cyber.model.purpose": invocation.purpose,
        }
