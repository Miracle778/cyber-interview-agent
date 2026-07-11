from __future__ import annotations

from typing import Any, Protocol

from app.hitl.models import PendingActionRecord, ResolutionReceipt


class ActionHandlerError(RuntimeError):
    pass


class DuplicateActionHandlerError(ActionHandlerError):
    pass


class UnknownActionTypeError(ActionHandlerError):
    pass


class ActionPayloadValidationError(ActionHandlerError):
    pass


class ActionHandler(Protocol):
    def apply_edit(
        self,
        action: PendingActionRecord,
        edited_payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def after_resolution(
        self,
        action: PendingActionRecord,
        receipt: ResolutionReceipt,
    ) -> None: ...


class DefaultActionHandler:
    def apply_edit(
        self,
        action: PendingActionRecord,
        edited_payload: dict[str, Any],
    ) -> dict[str, Any]:
        disallowed = set(edited_payload) - set(action.editable_fields)
        if disallowed:
            fields = ", ".join(sorted(disallowed))
            raise ActionPayloadValidationError(
                f"fields are not editable for {action.action_type!r}: {fields}"
            )
        return {**action.payload, **edited_payload}

    async def after_resolution(
        self,
        _action: PendingActionRecord,
        _receipt: ResolutionReceipt,
    ) -> None:
        return None


class ActionHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {}

    def register(self, action_type: str, handler: ActionHandler) -> None:
        if not action_type.strip():
            raise ValueError("action_type must not be empty")
        if action_type in self._handlers:
            raise DuplicateActionHandlerError(
                f"handler for {action_type!r} is already registered"
            )
        self._handlers[action_type] = handler

    def get(self, action_type: str) -> ActionHandler:
        try:
            return self._handlers[action_type]
        except KeyError as error:
            raise UnknownActionTypeError(
                f"no handler is registered for {action_type!r}"
            ) from error
