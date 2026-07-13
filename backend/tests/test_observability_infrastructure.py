from contextlib import contextmanager

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.infrastructure.observability import (
    NoopObservabilitySink,
    ObservabilitySettings,
    OpenTelemetryObservabilitySink,
    SafeObservabilitySink,
)
from app.middleware.observability import TraceContext


def trace_context() -> TraceContext:
    return TraceContext("w1", "s1", "e1", "review.single", 1)


def test_observability_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CYBER_OBSERVABILITY_ENABLED", raising=False)

    settings = ObservabilitySettings.from_env()

    assert settings.enabled is False
    assert settings.capture_content is False


def test_safe_sink_fails_open_without_leaking_exporter_details():
    warnings: list[str] = []

    class FailingSink:
        @contextmanager
        def span(self, *args, **kwargs):
            raise RuntimeError("secret exporter response")
            yield

        def force_flush(self, timeout_millis):
            raise RuntimeError("secret flush response")

    sink = SafeObservabilitySink(FailingSink(), warnings.append)
    with sink.span("agent.model.call", context=trace_context(), attributes={}) as span:
        span.set_attribute("status", "completed")

    assert not sink.force_flush(50)
    assert warnings == ["observability_export_failed", "observability_flush_failed"]
    assert "secret" not in str(warnings)


def test_safe_sink_preserves_business_exceptions():
    sink = SafeObservabilitySink(NoopObservabilitySink(), lambda _warning: None)

    with pytest.raises(ValueError, match="business failed"):
        with sink.span("agent.model.call", context=trace_context(), attributes={}):
            raise ValueError("business failed")


def test_opentelemetry_sink_exports_only_safe_runtime_attributes():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    sink = OpenTelemetryObservabilitySink(provider)

    with sink.span(
        "agent.model.call",
        context=trace_context(),
        attributes={"gen_ai.input.messages": 2},
    ):
        pass

    span = exporter.get_finished_spans()[0]
    assert span.attributes["cyber.execution.id"] == "e1"
    assert span.attributes["langfuse.session.id"] == "s1"
    assert "prompt" not in str(span.attributes).lower()
