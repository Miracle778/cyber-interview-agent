from contextlib import contextmanager

import pytest

from app.runtime.middleware.observability import (
    NoopObservabilitySink,
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
