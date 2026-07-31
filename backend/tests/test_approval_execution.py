from __future__ import annotations

import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.context import AgentContext
from app.application.approval_service import ApprovalService
from app.application.execution_service import AgentExecutionService
from app.application.session_service import ProductEventStream, ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.graphs.publication import create_publication_graph
from app.hitl.models import PendingActionRecord
from app.hitl.repository import PendingActionRepository


def _context(tmp_path):
    return AgentContext(
        workspace_id="w1",
        workspace_root=tmp_path,
        session_id="s1",
        run_id="r1",
        allowed_tools=frozenset({"write_review_draft"}),
        allowed_scopes=frozenset({"review.drafts"}),
    )


def _runtime_database(tmp_path):
    connection = connect_runtime_database(tmp_path)
    runtime = ProductRepository(connection)
    runtime.create_session(
        workspace_id="w1",
        kind="review.single",
        title="Review",
        session_id="s1",
    )
    runtime.create_execution(
        "s1",
        input={},
        model_bindings={},
        execution_id="r1",
    )
    runtime.transition_execution(
        "r1", expected=("running",), target="waiting_for_approval"
    )
    connection.close()


@pytest.mark.asyncio
async def test_approval_service_projects_official_interrupt_idempotently(tmp_path):
    _runtime_database(tmp_path)
    service = ApprovalService(PendingActionRepository(tmp_path))
    interrupt_value = {
        "action_requests": [
            {
                "name": "write_review_draft",
                "args": {"path": "draft.md", "content": "private"},
                "description": "Approve draft write",
            }
        ],
        "review_configs": [
            {
                "action_name": "write_review_draft",
                "allowed_decisions": ["approve", "reject"],
            }
        ],
    }

    first = await service.project_interrupt(
        interrupt_id="interrupt-1",
        value=interrupt_value,
        context=_context(tmp_path),
    )
    second = await service.project_interrupt(
        interrupt_id="interrupt-1",
        value=interrupt_value,
        context=_context(tmp_path),
    )

    assert second.id == first.id
    assert first.action_type == "tool.approval.write_review_draft"
    assert first.preview == {
        "actionName": "write_review_draft",
        "description": "Approve draft write",
    }
    assert "private" not in repr(first.preview)


@pytest.mark.asyncio
async def test_approval_service_translates_decision_to_resume_command(tmp_path):
    _runtime_database(tmp_path)
    service = ApprovalService(PendingActionRepository(tmp_path))
    action = await service.project_interrupt(
        interrupt_id="interrupt-1",
        value={
            "action_requests": [
                {"name": "write_review_draft", "args": {}, "description": "Approve"}
            ],
            "review_configs": [
                {
                    "action_name": "write_review_draft",
                    "allowed_decisions": ["approve", "reject"],
                }
            ],
        },
        context=_context(tmp_path),
    )

    approved = await service.approve(
        action.id,
        expected_version=action.version,
        idempotency_key="decision-1",
    )

    assert approved.action.status == "approved"
    assert approved.command.resume == {"decisions": [{"type": "approve"}]}


@pytest.mark.asyncio
async def test_resume_approval_waits_for_interrupt_state_to_persist(tmp_path):
    connection = connect_runtime_database(tmp_path)
    runtime = ProductRepository(connection)
    session = runtime.create_session(
        workspace_id="w1",
        kind="diagnostic.approval",
        title="Approval",
        session_id="s1",
    )
    runtime.create_execution(
        session.id,
        input={},
        model_bindings={},
        execution_id="r1",
    )
    service = AgentExecutionService(
        workspace_id="w1",
        workspace_root=tmp_path,
        repository=runtime,
        events=ProductEventStream(runtime, workspace_root=tmp_path),
        graph_factory=lambda *_args, **_kwargs: None,
        model_bindings=lambda: {},
        create_action=lambda _command: None,
        create_draft=lambda _command: None,
        mark_draft_review_pending=lambda *_args, **_kwargs: None,
    )
    spawned = []
    service._spawn = lambda execution_id, *, graph_input: spawned.append(  # type: ignore[method-assign]
        (execution_id, graph_input)
    )

    async def finish_interrupt():
        await asyncio.sleep(0)
        runtime.transition_execution(
            "r1",
            expected=("running",),
            target="waiting_for_approval",
        )

    service._tasks["r1"] = asyncio.create_task(finish_interrupt())

    await service.resume_approval("r1", {"decision": "approved"}, "receipt-1")

    execution = runtime.get_execution("r1")
    assert execution.status == "running"
    assert execution.resume_count == 1
    assert len(spawned) == 1
    connection.close()


def _action() -> PendingActionRecord:
    return PendingActionRecord(
        id="action-1",
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        action_type="knowledge.publish",
        payload={},
        preview={},
        editable_fields=(),
        status="pending",
        version=1,
        idempotency_key="publish-1",
        created_at="2026-07-13T00:00:00Z",
        resolved_at=None,
    )


@pytest.mark.asyncio
async def test_publication_graph_keeps_domain_approval_explicit():
    calls = []

    async def request_action(**kwargs):
        calls.append(kwargs)
        return _action()

    graph = create_publication_graph(
        request_action=request_action,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "s1"}}
    input = {
        "draftId": "draft-1",
        "draftVersion": 2,
        "contentHash": "hash-2",
        "title": "Review",
        "markdown": "# Review",
    }

    interrupted = await graph.ainvoke(input, config)
    resumed = await graph.ainvoke(
        Command(resume={"decision": "rejected", "reason": "revise"}), config
    )

    assert interrupted["__interrupt__"][0].value == {"actionId": "action-1"}
    assert calls[0]["idempotency_key"] == "knowledge.publish:draft-1:2:hash-2"
    assert resumed["response"] == "知识草稿未发布：revise"
