from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.types import Command

from app.agents.context import AgentContext
from app.hitl.models import CreatePendingAction, PendingActionRecord, ResolutionReceipt
from app.hitl.repository import PendingActionRepository


@dataclass(frozen=True, slots=True)
class ApprovalResolution:
    action: PendingActionRecord
    receipt: ResolutionReceipt
    command: Command


class ApprovalService:
    def __init__(self, repository: PendingActionRepository) -> None:
        self._repository = repository

    async def project_interrupt(
        self,
        *,
        interrupt_id: str,
        value: dict[str, Any],
        context: AgentContext,
    ) -> PendingActionRecord:
        requests = value.get("action_requests")
        configs = value.get("review_configs")
        if not isinstance(requests, list) or len(requests) != 1:
            raise ValueError("exactly one tool approval action is required")
        if not isinstance(configs, list) or len(configs) != 1:
            raise ValueError("exactly one tool approval config is required")
        request = requests[0]
        config = configs[0]
        name = str(request["name"])
        args = request.get("args")
        description = str(request.get("description", ""))
        return await self._repository.create(
            CreatePendingAction(
                workspace_id=context.workspace_id,
                session_id=context.session_id,
                run_id=context.run_id,
                action_type=f"tool.approval.{name}",
                payload={
                    "interruptId": interrupt_id,
                    "actionName": name,
                    "arguments": args if isinstance(args, dict) else {},
                    "allowedDecisions": config.get("allowed_decisions", []),
                },
                preview={
                    "actionName": name,
                    "description": description,
                },
                editable_fields=(),
                idempotency_key=f"langgraph.interrupt:{interrupt_id}:0",
            )
        )

    async def approve(
        self,
        action_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> ApprovalResolution:
        return await self._resolve(
            action_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            status="approved",
            decision={"decisions": [{"type": "approve"}]},
        )

    async def reject(
        self,
        action_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        reason: str | None,
    ) -> ApprovalResolution:
        decision: dict[str, Any] = {"type": "reject"}
        if reason:
            decision["message"] = reason
        return await self._resolve(
            action_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            status="rejected",
            decision={"decisions": [decision]},
            reason=reason,
        )

    async def _resolve(
        self,
        action_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        status: str,
        decision: dict[str, Any],
        reason: str | None = None,
    ) -> ApprovalResolution:
        receipt = await self._repository.resolve(
            action_id,
            expected_version=expected_version,
            status=status,
            resolution_key=idempotency_key,
            decision=decision,
            reason=reason,
        )
        action = await self._repository.get(action_id)
        return ApprovalResolution(
            action=action,
            receipt=receipt,
            command=Command(resume=decision),
        )
