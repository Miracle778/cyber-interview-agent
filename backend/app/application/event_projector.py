from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessageChunk


@dataclass(frozen=True, slots=True)
class ProductEvent:
    type: str
    payload: dict[str, Any]
    cursor: int | None


_CUSTOM_KEYS = {
    "execution.started": {"run_id", "session_id"},
    "execution.completed": {"run_id", "session_id"},
    "execution.interrupted": {"run_id", "action_id"},
    "approval.resolved": {"action_id", "decision", "status"},
    "artifact.changed": {"draft_id", "version", "status"},
    "publication.changed": {
        "draft_id",
        "publication_id",
        "status",
        "target_path",
        "index_stale",
    },
    "execution.warning": {"code", "message"},
}


class AgentEventProjector:
    """Collapse LangGraph v2 streams into replayable, content-safe UI events."""

    def __init__(self, *, start_cursor: int = 0) -> None:
        self._cursor = start_cursor
        self._interrupts: set[str] = set()

    def project(self, stream_part: Mapping[str, Any]) -> tuple[ProductEvent, ...]:
        part_type = stream_part.get("type")
        if part_type == "messages":
            message, _metadata = stream_part.get("data", (None, {}))
            if not isinstance(message, AIMessageChunk) or not message.text:
                return ()
            return (self._event("assistant.delta", {"text": message.text}),)

        if part_type == "values":
            events = []
            for interrupt in stream_part.get("interrupts", ()):
                interrupt_id = str(getattr(interrupt, "id", ""))
                if not interrupt_id or interrupt_id in self._interrupts:
                    continue
                self._interrupts.add(interrupt_id)
                events.append(
                    self._event(
                        "approval.required",
                        {"interrupt_id": interrupt_id},
                    )
                )
            return tuple(events)

        if part_type == "custom":
            data = stream_part.get("data")
            if not isinstance(data, Mapping):
                return ()
            event_type = data.get("type")
            allowed = _CUSTOM_KEYS.get(event_type)
            payload = data.get("payload", {})
            if allowed is None or not isinstance(payload, Mapping):
                return ()
            safe_payload = {key: payload[key] for key in allowed if key in payload}
            return (self._event(event_type, safe_payload),)

        if part_type == "tasks":
            data = stream_part.get("data")
            if isinstance(data, Mapping) and data.get("error"):
                return (
                    self._event(
                        "execution.failed",
                        {"code": "agent_execution_failed"},
                    ),
                )
        return ()

    def keepalive(self) -> ProductEvent:
        return ProductEvent(type="keepalive", payload={}, cursor=None)

    def _event(self, event_type: str, payload: dict[str, Any]) -> ProductEvent:
        self._cursor += 1
        return ProductEvent(type=event_type, payload=payload, cursor=self._cursor)
