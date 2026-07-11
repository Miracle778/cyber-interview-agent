import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiosqlite

from app.db.runtime_database import runtime_database_path
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
        self,
        repository: RuntimeRepository,
        *,
        keepalive_seconds: float = 15.0,
        workspace_root: Path | None = None,
    ) -> None:
        self._repository = repository
        self._keepalive_seconds = keepalive_seconds
        self._database_path = (
            runtime_database_path(workspace_root)
            if workspace_root is not None
            else None
        )
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

        safe_payload = _scrub(payload)
        event = (
            await self._append_event_async(
                session_id, run_id, event_type, safe_payload
            )
            if self._database_path is not None
            else self._repository.append_event(
                session_id, run_id, event_type, safe_payload
            )
        )
        condition = self._condition(session_id)
        async with condition:
            condition.notify_all()
        return event

    async def _append_event_async(
        self,
        session_id: str,
        run_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> EventRecord:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("PRAGMA busy_timeout = 5000")
            cursor = await connection.execute(
                "INSERT INTO agent_events "
                "(session_id, run_id, type, payload_json) VALUES (?, ?, ?, ?)",
                (
                    session_id,
                    run_id,
                    event_type,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                ),
            )
            event_id = cursor.lastrowid
            await connection.commit()
            row_cursor = await connection.execute(
                "SELECT created_at FROM agent_events WHERE id = ?", (event_id,)
            )
            row = await row_cursor.fetchone()
        if event_id is None or row is None:
            raise RuntimeError("Persisted event could not be loaded")
        return EventRecord(
            id=event_id,
            session_id=session_id,
            run_id=run_id,
            type=event_type,
            payload=payload,
            created_at=row["created_at"],
        )

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
