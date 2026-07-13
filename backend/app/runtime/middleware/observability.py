from __future__ import annotations

import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol


AttributeValue = str | int | float | bool


@dataclass(frozen=True, slots=True)
class TraceContext:
    workspace_id: str
    session_id: str
    run_id: str
    graph_id: str
    graph_version: int


class SpanHandle(Protocol):
    def set_attribute(self, key: str, value: AttributeValue) -> None: ...
    def record_error(self, code: str) -> None: ...


class ObservabilitySink(Protocol):
    def span(
        self,
        name: str,
        *,
        context: TraceContext,
        attributes: Mapping[str, AttributeValue],
        links: Sequence[object] = (),
    ): ...

    def force_flush(self, timeout_millis: int) -> bool: ...


class NoopSpanHandle:
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


class SafeObservabilitySink:
    def __init__(
        self,
        inner: ObservabilitySink,
        warning_callback: Callable[[str], None],
    ) -> None:
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
