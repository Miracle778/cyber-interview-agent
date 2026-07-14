from __future__ import annotations

from typing import Any

from app.application.session_service import (
    MessageKind,
    MessageRecord,
    ProductEventStream,
    ProductRepository,
)


class SessionTimelineProjector:
    """Persist user-visible messages and emit only safe invalidation metadata."""

    def __init__(
        self, repository: ProductRepository, events: ProductEventStream
    ) -> None:
        self._repository = repository
        self._events = events

    async def append(
        self,
        *,
        session_id: str,
        execution_id: str | None,
        role: str,
        message_kind: MessageKind,
        content: str,
        payload: dict[str, Any],
    ) -> MessageRecord:
        message = self._repository.append_message(
            session_id,
            execution_id=execution_id,
            role=role,
            content=content,
            message_kind=message_kind,
            payload=payload,
        )
        event_payload: dict[str, Any] = {
            "messageId": message.id,
            "messageKind": message.message_kind,
        }
        for key in ("resourceId", "version"):
            if key in payload:
                event_payload[key] = payload[key]
        await self._events.publish(
            session_id,
            execution_id,
            "session.message.created",
            event_payload,
        )
        return message
