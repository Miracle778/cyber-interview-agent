from __future__ import annotations

import hashlib
import json

from app.runtime.middleware.repository import RuntimeMiddlewareRepository
from app.runtime.middleware.types import (
    BaseRuntimeMiddleware,
    MiddlewareConfig,
    MiddlewareLayer,
    RuntimeGuardError,
)
from app.runtime.middleware.observability import NoopObservabilitySink, as_trace_context


class LoopGuardMiddleware(BaseRuntimeMiddleware):
    middleware_id = "loop_guard"
    layer = MiddlewareLayer.GUARD
    order = 110

    def __init__(
        self,
        repository: RuntimeMiddlewareRepository,
        config: MiddlewareConfig,
        *,
        publish_warning=lambda code: None,
        defer_writes: bool = False,
        observability=None,
    ) -> None:
        self._repository = repository
        self._config = config
        self._publish_warning = publish_warning
        self._defer_writes = defer_writes
        self._pending: list[dict[str, str | None]] = []
        self._local_counts: dict[tuple[str, str], int] = {}
        self._observability = observability or NoopObservabilitySink()

    async def wrap_model(self, context, invocation, call_next):
        fingerprint = self._fingerprint(
            {"kind": "model", "name": invocation.role, "purpose": invocation.purpose}
        )
        self._observe(context, "model", fingerprint)
        return await call_next(invocation)

    async def wrap_tool(self, context, invocation, call_next):
        fingerprint = self._fingerprint(
            {"kind": "tool", "name": invocation.tool_name}
        )
        self._observe(context, "tool", fingerprint)
        return await call_next(invocation)

    def _observe(self, context, kind: str, fingerprint: str) -> None:
        run_id = context.run_id
        key = (run_id, fingerprint)
        count = self._local_counts.get(key)
        if count is None:
            count = self._repository.fingerprint_count(run_id, fingerprint)
        count += 1
        self._local_counts[key] = count
        error_code = None
        if count == self._config.repeat_soft_limit:
            error_code = "loop_detected"
            self._publish_warning("loop_detected")
        record = {
            "run_id": run_id,
            "kind": kind,
            "fingerprint": fingerprint,
            "error_code": error_code,
        }
        if self._defer_writes:
            self._pending.append(record)
        else:
            self._repository.record_guard_observation(**record)
        with self._observability.span(
            "middleware.loop_guard",
            context=as_trace_context(context),
            attributes={"cyber.guard.kind": kind, "cyber.guard.count": count},
        ) as span:
            span.set_attribute("cyber.status", "blocked" if count >= self._config.repeat_hard_limit else "allowed")
        if count >= self._config.repeat_hard_limit:
            raise RuntimeGuardError("loop_detected", "检测到重复执行")

    def flush(self) -> None:
        pending, self._pending = self._pending, []
        for values in pending:
            self._repository.record_guard_observation(**values)

    @staticmethod
    def _fingerprint(value: dict[str, str]) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()
