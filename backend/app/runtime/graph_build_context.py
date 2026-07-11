from dataclasses import dataclass
from typing import Any, Protocol

from app.hitl.models import PendingActionRecord


class ToolInvokerProtocol(Protocol):
    async def __call__(
        self, name: str, raw_input: dict[str, object]
    ) -> dict[str, object]: ...


class ActionRequesterProtocol(Protocol):
    async def __call__(
        self,
        *,
        action_type: str,
        payload: dict[str, Any],
        preview: dict[str, Any],
        editable_fields: tuple[str, ...],
        idempotency_key: str,
    ) -> PendingActionRecord: ...


async def unavailable_action_request(
    *,
    action_type: str,
    payload: dict[str, Any],
    preview: dict[str, Any],
    editable_fields: tuple[str, ...],
    idempotency_key: str,
) -> PendingActionRecord:
    del action_type, payload, preview, editable_fields, idempotency_key
    raise RuntimeError("HITL action requests are not configured")


@dataclass(frozen=True, slots=True)
class GraphBuildContext:
    checkpointer: object
    invoke_tool: ToolInvokerProtocol
    request_action: ActionRequesterProtocol = unavailable_action_request


async def unavailable_tool_invoker(
    _name: str, _raw_input: dict[str, object]
) -> dict[str, object]:
    raise RuntimeError("Tool invocation is not configured")
