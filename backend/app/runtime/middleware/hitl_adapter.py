from __future__ import annotations

from dataclasses import dataclass

from app.runtime.middleware.types import BaseRuntimeMiddleware, MiddlewareLayer


@dataclass(frozen=True, slots=True)
class ToolApprovalPolicy:
    require_approval: frozenset[str] = frozenset()

    def requires_approval(self, tool_name: str) -> bool:
        return tool_name != "knowledge.publish" and tool_name in self.require_approval


@dataclass(frozen=True, slots=True)
class ToolApprovalInterrupt:
    interrupted_action_id: str


class PersistentHitlMiddleware(BaseRuntimeMiddleware):
    middleware_id = "persistent_hitl"
    layer = MiddlewareLayer.GUARD
    order = 130

    def __init__(
        self,
        *,
        policy: ToolApprovalPolicy,
        request_action,
        interrupt_call=lambda payload: ToolApprovalInterrupt(payload["actionId"]),
    ) -> None:
        self._policy = policy
        self._request_action = request_action
        self._interrupt_call = interrupt_call

    async def wrap_tool(self, context, invocation, call_next):
        if not self._policy.requires_approval(invocation.tool_name):
            return await call_next(invocation)
        action = await self._request_action(
            action_type=f"tool.approval.{invocation.tool_name}",
            payload={"toolName": invocation.tool_name, "arguments": invocation.arguments},
            preview={"toolName": invocation.tool_name},
            editable_fields=(),
            idempotency_key=f"{invocation.operation_key}:approval",
        )
        decision = self._interrupt_call({"actionId": action.id})
        if isinstance(decision, ToolApprovalInterrupt):
            return decision
        if isinstance(decision, dict) and decision.get("decision") == "approved":
            return await call_next(invocation)
        return {"error": "tool_rejected", "toolName": invocation.tool_name}
