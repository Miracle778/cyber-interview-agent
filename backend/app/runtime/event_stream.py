import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from app.runtime.models import EventRecord
from app.runtime.repository import RuntimeRepository


class EventValidationError(ValueError):
    pass


_EVENT_TYPES = frozenset(
    {
        "session.created",
        "run.started",
        "graph.node.started",
        "graph.node.completed",
        "message.delta",
        "message.completed",
        "tool.started",
        "tool.completed",
        "tool.failed",
        "hitl.required",
        "hitl.resolved",
        "draft.created",
        "publication.started",
        "publication.completed",
        "publication.index_stale",
        "run.interrupted",
        "run.completed",
        "run.failed",
        "run.cancelled",
    }
)
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apiKey",
        "authorization",
        "secret",
        "access_token",
        "accessToken",
        "refresh_token",
        "refreshToken",
    }
)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _scrub(nested)
            for key, nested in value.items()
            if key not in _SECRET_KEYS
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def encode_sse_event(event: EventRecord) -> str:
    envelope = {
        "id": event.id,
        "sessionId": event.session_id,
        "runId": event.run_id,
        "type": event.type,
        "timestamp": event.created_at,
        "payload": event.payload,
    }
    data = json.dumps(
        envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return f"id: {event.id}\nevent: {event.type}\ndata: {data}\n\n"


class EventStream:
    def __init__(
        self, repository: RuntimeRepository, *, keepalive_seconds: float = 15.0
    ) -> None:
        self._repository = repository
        self._keepalive_seconds = keepalive_seconds
        self._conditions: dict[str, asyncio.Condition] = {}

    def _condition(self, session_id: str) -> asyncio.Condition:
        condition = self._conditions.get(session_id)
        if condition is None:
            condition = asyncio.Condition()
            self._conditions[session_id] = condition
        return condition

    async def publish(
        self,
        session_id: str,
        run_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> EventRecord:
        if event_type not in _EVENT_TYPES:
            raise EventValidationError(f"unsupported event type {event_type!r}")
        if not isinstance(payload, dict):
            raise EventValidationError("event payload must be an object")

        event = self._repository.append_event(
            session_id, run_id, event_type, _scrub(payload)
        )
        condition = self._condition(session_id)
        async with condition:
            condition.notify_all()
        return event

    async def subscribe(
        self, session_id: str, *, after_id: int | None
    ) -> AsyncIterator[EventRecord | None]:
        cursor = after_id or 0
        condition = self._condition(session_id)
        while True:
            events = self._repository.list_events(session_id, after_id=cursor)
            if events:
                for event in events:
                    cursor = event.id
                    yield event
                continue

            async with condition:
                if self._repository.list_events(session_id, after_id=cursor):
                    continue
                timed_out = False
                try:
                    await asyncio.wait_for(
                        condition.wait(), timeout=self._keepalive_seconds
                    )
                except TimeoutError:
                    timed_out = True
            if timed_out:
                yield None
