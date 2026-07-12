from dataclasses import dataclass
from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from app.hitl.models import PendingActionRecord
from app.knowledge.drafts import KnowledgeDraftRecord


SchemaT = TypeVar("SchemaT", bound=BaseModel)


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


class ModelInvokerProtocol(Protocol):
    async def invoke_structured(
        self,
        *,
        role: str,
        schema: type[SchemaT],
        messages: Sequence[Any],
    ) -> SchemaT: ...

    def stream_text(
        self, *, role: str, messages: Sequence[Any]
    ) -> AsyncIterator[str]: ...


class DraftCreatorProtocol(Protocol):
    async def __call__(
        self,
        *,
        title: str,
        markdown: str,
        source_refs: tuple[str, ...],
        relation_refs: tuple[str, ...],
    ) -> KnowledgeDraftRecord: ...


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


class UnavailableModelInvoker:
    async def invoke_structured(self, **_kwargs: Any) -> Any:
        raise RuntimeError("Model invocation is not configured")

    async def stream_text(self, **_kwargs: Any) -> AsyncIterator[str]:
        del _kwargs
        raise RuntimeError("Model invocation is not configured")
        yield ""  # pragma: no cover


async def unavailable_draft_creator(**_kwargs: Any) -> KnowledgeDraftRecord:
    raise RuntimeError("Draft creation is not configured")


@dataclass(frozen=True, slots=True)
class GraphBuildContext:
    checkpointer: object
    invoke_tool: ToolInvokerProtocol
    request_action: ActionRequesterProtocol = unavailable_action_request
    invoke_model: ModelInvokerProtocol = UnavailableModelInvoker()
    create_draft: DraftCreatorProtocol = unavailable_draft_creator


async def unavailable_tool_invoker(
    _name: str, _raw_input: dict[str, object]
) -> dict[str, object]:
    raise RuntimeError("Tool invocation is not configured")
