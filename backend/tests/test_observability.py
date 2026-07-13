from contextlib import contextmanager

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.runtime.middleware.observability import (
    NoopObservabilitySink,
    ObservabilitySettings,
    OpenTelemetryObservabilitySink,
    SafeObservabilitySink,
    TraceContext,
)


def trace_context():
    return TraceContext("w1", "s1", "r1", "review.single", 1)


def test_noop_sink_is_safe_without_exporter():
    sink = NoopObservabilitySink()
    with sink.span("agent.run", context=trace_context(), attributes={}) as span:
        span.set_attribute("result", "completed")
        span.record_error("stable_error")
    assert sink.force_flush(50)


def test_safe_sink_fails_open_and_reports_stable_warning():
    warnings: list[str] = []

    class FailingSink:
        @contextmanager
        def span(self, *args, **kwargs):
            raise RuntimeError("secret exporter response")
            yield

        def force_flush(self, timeout_millis):
            raise RuntimeError("secret flush response")

    sink = SafeObservabilitySink(FailingSink(), warnings.append)
    with sink.span("model.invoke", context=trace_context(), attributes={}) as span:
        span.set_attribute("status", "completed")

    assert not sink.force_flush(50)
    assert warnings == ["observability_export_failed", "observability_flush_failed"]
    assert all("secret" not in warning for warning in warnings)


def test_safe_sink_handles_failure_before_context_manager_is_returned():
    warnings: list[str] = []

    class ImmediatelyFailingSink:
        def span(self, *args, **kwargs):
            raise RuntimeError("unavailable")

        def force_flush(self, timeout_millis):
            return True

    sink = SafeObservabilitySink(ImmediatelyFailingSink(), warnings.append)
    with sink.span("agent.run", context=trace_context(), attributes={}):
        business_result = "completed"

    assert business_result == "completed"
    assert warnings == ["observability_export_failed"]


def test_safe_sink_never_swallows_business_exception():
    sink = SafeObservabilitySink(NoopObservabilitySink(), lambda warning: None)

    with pytest.raises(ValueError, match="business failed"):
        with sink.span("agent.run", context=trace_context(), attributes={}):
            raise ValueError("business failed")


def test_opentelemetry_sink_exports_parent_child_safe_attributes():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    sink = OpenTelemetryObservabilitySink(provider)

    with sink.span(
        "agent.run",
        context=trace_context(),
        attributes={"cyber.status": "running"},
    ):
        with sink.span(
            "model.invoke",
            context=trace_context(),
            attributes={
                "gen_ai.request.model": "safe-model-id",
                "gen_ai.usage.input_tokens": 12,
                "cyber.usage.estimated": False,
            },
        ):
            pass

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["model.invoke"].parent.span_id == spans["agent.run"].context.span_id
    assert spans["agent.run"].attributes["cyber.session.id"] == "s1"
    serialized = str(spans)
    assert "api-key" not in serialized and "prompt body" not in serialized


def test_observability_settings_are_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CYBER_OBSERVABILITY_ENABLED", raising=False)
    settings = ObservabilitySettings.from_env()
    assert settings.enabled is False
    assert settings.capture_content is False
