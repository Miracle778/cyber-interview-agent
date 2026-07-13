from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain.agents.middleware import AgentMiddleware

from app.runtime.middleware.hitl_adapter import (
    PersistentHitlMiddleware,
    ToolApprovalInterrupt,
    ToolApprovalPolicy,
)
from app.runtime.middleware.langchain_adapter import LangChainRuntimeMiddlewareAdapter
from app.runtime.middleware.pipeline import RuntimeMiddlewarePipeline
from app.runtime.middleware.types import MiddlewareConfig, MiddlewareContext, ToolInvocation


def context():
    return MiddlewareContext("w1", "s1", "r1", "test", 1)


@pytest.mark.asyncio
async def test_ordinary_tool_policy_creates_persistent_action():
    request_action = AsyncMock(return_value=SimpleNamespace(id="action-1"))
    call_next = AsyncMock(return_value={"ok": True})
    middleware = PersistentHitlMiddleware(
        policy=ToolApprovalPolicy(require_approval=frozenset({"write_profile"})),
        request_action=request_action,
    )
    result = await middleware.wrap_tool(
        context(), ToolInvocation("tool:1", "write_profile", {"content": "secret"}), call_next
    )
    assert result == ToolApprovalInterrupt("action-1")
    request_action.assert_awaited_once()
    assert request_action.await_args.kwargs["preview"] == {"toolName": "write_profile"}
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_unlisted_and_knowledge_publish_tools_pass_through():
    request_action = AsyncMock()
    call_next = AsyncMock(return_value={"ok": True})
    middleware = PersistentHitlMiddleware(
        policy=ToolApprovalPolicy(require_approval=frozenset({"write_profile", "knowledge.publish"})),
        request_action=request_action,
    )
    assert await middleware.wrap_tool(
        context(), ToolInvocation("tool:1", "read_source", {}), call_next
    ) == {"ok": True}
    assert await middleware.wrap_tool(
        context(), ToolInvocation("tool:2", "knowledge.publish", {}), call_next
    ) == {"ok": True}
    request_action.assert_not_awaited()


def test_langchain_adapter_subclasses_official_agent_middleware():
    adapter = LangChainRuntimeMiddlewareAdapter(
        RuntimeMiddlewarePipeline((), MiddlewareConfig()),
        context_factory=SimpleNamespace(),
    )
    assert isinstance(adapter, AgentMiddleware)
