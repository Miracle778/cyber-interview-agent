from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol

from app.hitl.handlers import (
    ActionHandlerRegistry,
    ActionPayloadValidationError,
)
from app.hitl.models import (
    CreatePendingAction,
    PendingActionRecord,
    ResolutionReceipt,
    ResolveActionCommand,
)
from app.hitl.repository import PendingActionRepository


class EventPublisher(Protocol):
    async def publish(
        self,
        session_id: str,
        run_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> object: ...


ResumeAction = Callable[[str, dict[str, Any], str], Awaitable[None]]


class HitlService:
    def __init__(
        self,
        *,
        repository: PendingActionRepository,
        handlers: ActionHandlerRegistry,
        event_stream: EventPublisher,
        resume_action: ResumeAction,
    ) -> None:
        self._repository = repository
        self._handlers = handlers
        self._event_stream = event_stream
        self._resume_action = resume_action

    async def create_action(
        self, request: CreatePendingAction
    ) -> PendingActionRecord:
        self._handlers.get(request.action_type)
        return await self._repository.create(request)

    async def approve(
        self, action_id: str, command: ResolveActionCommand
    ) -> PendingActionRecord:
        action = await self._repository.get(action_id)
        handler = self._handlers.get(action.action_type)
        edited = command.edited_payload
        resolved_payload = (
            handler.apply_edit(action, edited) if edited is not None else action.payload
        )
        status = "edited_and_approved" if edited is not None else "approved"
        decision = {
            "actionId": action.id,
            "decision": "approved",
            "payload": resolved_payload,
        }
        receipt = await self._repository.resolve(
            action.id,
            expected_version=command.version,
            status=status,
            resolution_key=command.idempotency_key,
            decision=decision,
            resolved_payload=resolved_payload,
            resolved_preview={
                **action.preview,
                **{
                    key: value
                    for key, value in resolved_payload.items()
                    if key in action.preview
                },
            },
        )
        resolved = await self._repository.get(action.id)
        await self._deliver(resolved, receipt, handler)
        return resolved

    async def reject(
        self, action_id: str, command: ResolveActionCommand
    ) -> PendingActionRecord:
        reason = (command.reason or "").strip()
        if not reason:
            raise ActionPayloadValidationError("rejection reason must not be empty")
        action = await self._repository.get(action_id)
        handler = self._handlers.get(action.action_type)
        decision = {
            "actionId": action.id,
            "decision": "rejected",
            "reason": reason,
        }
        receipt = await self._repository.resolve(
            action.id,
            expected_version=command.version,
            status="rejected",
            resolution_key=command.idempotency_key,
            decision=decision,
            reason=reason,
        )
        resolved = await self._repository.get(action.id)
        await self._deliver(resolved, receipt, handler)
        return resolved

    async def reconcile(self) -> tuple[str, ...]:
        delivered: list[str] = []
        for receipt in await self._repository.list_recoverable_resolutions():
            action = await self._repository.get(receipt.action_id)
            if receipt.delivery_status in {"delivering", "delivered"}:
                receipt = await self._repository.prepare_delivery_retry(receipt.id)
            handler = self._handlers.get(action.action_type)
            try:
                await self._deliver(action, receipt, handler)
            except Exception:
                continue
            delivered.append(receipt.id)
        return tuple(delivered)

    async def _deliver(self, action, receipt, handler) -> None:
        if receipt.delivery_status == "delivered":
            return
        delivering = await self._repository.claim_delivery(receipt.id)
        if delivering is None:
            return
        try:
            await handler.after_resolution(action, delivering)
            await self._event_stream.publish(
                action.session_id,
                action.run_id,
                "hitl.resolved",
                {
                    "actionId": action.id,
                    "status": action.status,
                    "version": action.version,
                },
            )
            await self._resume_action(
                action.run_id, delivering.decision, delivering.id
            )
            await self._repository.mark_delivered(delivering.id)
        except Exception:
            await self._repository.mark_delivery_failed(
                delivering.id, error_code="hitl_resume_failed"
            )
            raise
