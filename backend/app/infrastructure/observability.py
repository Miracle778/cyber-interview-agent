from __future__ import annotations

import os
import secrets
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.middleware.observability import TraceContext


AttributeValue = str | int | float | bool


class SpanHandle(Protocol):
    def set_attribute(self, key: str, value: AttributeValue) -> None: ...

    def record_error(self, code: str) -> None: ...


class NoopSpanHandle:
    def __init__(self) -> None:
        self.trace_id = secrets.token_hex(16)
        self.span_id = secrets.token_hex(8)

    def set_attribute(self, key: str, value: AttributeValue) -> None:
        return None

    def record_error(self, code: str) -> None:
        return None


class NoopObservabilitySink:
    @contextmanager
    def span(self, *_args, **_kwargs) -> Iterator[NoopSpanHandle]:
        yield NoopSpanHandle()

    def force_flush(self, timeout_millis: int) -> bool:
        return True


class OpenTelemetrySpanHandle:
    def __init__(self, span) -> None:
        self._span = span

    def set_attribute(self, key: str, value: AttributeValue) -> None:
        self._span.set_attribute(key, value)

    def record_error(self, code: str) -> None:
        self._span.set_attribute("error.type", code)


class OpenTelemetryObservabilitySink:
    def __init__(self, provider: TracerProvider) -> None:
        self._provider = provider
        self._tracer = provider.get_tracer("cyber-interview-agent.agent")

    @contextmanager
    def span(
        self,
        name: str,
        *,
        context: TraceContext,
        attributes: Mapping[str, AttributeValue],
        links: Sequence[object] = (),
    ) -> Iterator[OpenTelemetrySpanHandle]:
        safe_attributes = {
            "cyber.workspace.id": context.workspace_id,
            "cyber.session.id": context.session_id,
            "langfuse.session.id": context.session_id,
            "cyber.execution.id": context.execution_id,
            "cyber.agent.kind": context.graph_id,
            "cyber.agent.version": context.graph_version,
            **attributes,
        }
        with self._tracer.start_as_current_span(
            name, attributes=safe_attributes, links=links
        ) as span:
            yield OpenTelemetrySpanHandle(span)

    def force_flush(self, timeout_millis: int) -> bool:
        return self._provider.force_flush(timeout_millis)


class SafeObservabilitySink:
    """Keep telemetry failure outside the product execution failure boundary."""

    def __init__(self, inner, warning_callback: Callable[[str], None]) -> None:
        self._inner = inner
        self._warning_callback = warning_callback

    @contextmanager
    def span(
        self,
        name: str,
        *,
        context: TraceContext,
        attributes: Mapping[str, AttributeValue],
        links: Sequence[object] = (),
    ) -> Iterator[SpanHandle]:
        try:
            manager = self._inner.span(
                name, context=context, attributes=attributes, links=links
            )
            handle = manager.__enter__()
        except Exception:
            self._warning_callback("observability_export_failed")
            yield NoopSpanHandle()
            return

        try:
            yield handle
        except BaseException:
            error_type, error, traceback = sys.exc_info()
            try:
                manager.__exit__(error_type, error, traceback)
            except Exception:
                self._warning_callback("observability_export_failed")
            raise
        else:
            try:
                manager.__exit__(None, None, None)
            except Exception:
                self._warning_callback("observability_export_failed")

    def force_flush(self, timeout_millis: int) -> bool:
        try:
            return self._inner.force_flush(timeout_millis)
        except Exception:
            self._warning_callback("observability_flush_failed")
            return False


@dataclass(frozen=True, slots=True)
class ObservabilitySettings:
    enabled: bool = False
    service_name: str = "cyber-interview-agent"
    otlp_endpoint: str = "http://127.0.0.1:3000/api/public/otel/v1/traces"
    otlp_headers: str = ""
    capture_content: bool = False
    flush_timeout_ms: int = 2_000

    @classmethod
    def from_env(cls) -> "ObservabilitySettings":
        return cls(
            enabled=_env_bool("CYBER_OBSERVABILITY_ENABLED", False),
            service_name=os.getenv(
                "CYBER_OBSERVABILITY_SERVICE_NAME", "cyber-interview-agent"
            ),
            otlp_endpoint=os.getenv(
                "CYBER_OTLP_ENDPOINT",
                "http://127.0.0.1:3000/api/public/otel/v1/traces",
            ),
            otlp_headers=os.getenv("CYBER_OTLP_HEADERS", ""),
            capture_content=_env_bool("CYBER_OBSERVABILITY_CAPTURE_CONTENT", False),
            flush_timeout_ms=int(
                os.getenv("CYBER_OBSERVABILITY_FLUSH_TIMEOUT_MS", "2000")
            ),
        )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_otlp_headers(value: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for part in value.split(","):
        if not part.strip():
            continue
        key, separator, header_value = part.partition("=")
        if not separator or not key.strip():
            raise ValueError("invalid OTLP header configuration")
        headers[key.strip()] = header_value.strip()
    return headers


def create_observability_sink(
    settings: ObservabilitySettings,
    publish_warning: Callable[[str], None],
):
    if not settings.enabled:
        return NoopObservabilitySink()
    exporter = OTLPSpanExporter(
        endpoint=settings.otlp_endpoint,
        headers=parse_otlp_headers(settings.otlp_headers),
    )
    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.service_name})
    )
    provider.add_span_processor(BatchSpanProcessor(exporter, max_queue_size=512))
    return SafeObservabilitySink(
        OpenTelemetryObservabilitySink(provider), publish_warning
    )
