from pathlib import Path

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.hitl.models import ResolveActionCommand
from app.runtime.default_graphs import create_default_graph_registry
from app.runtime.graph_registry import GraphDefinition, GraphRegistry
from app.runtime.service import AgentRuntime


def _runtime(workspace: Path) -> AgentRuntime:
    return AgentRuntime(
        graph_registry=create_default_graph_registry(),
        workspace_resolver=lambda _workspace_id: workspace,
        model_binding_resolver=lambda _workspace_id: {},
        workspace_ids=lambda: ("w1",),
    )


async def _waiting_run(runtime: AgentRuntime, *, summary: str = "original"):
    session = await runtime.create_session(
        workspace_id="w1",
        graph_id="test.approval",
        graph_version=1,
        title="确认自检",
    )
    run = await runtime.start_run(session.id, input={"summary": summary})
    waiting = await runtime._context("w1").manager.wait(run.id)
    actions = await runtime.list_actions("w1", status="pending")
    return session, waiting, actions[0]


@pytest.mark.asyncio
async def test_interrupt_waits_without_completing_or_writing_response(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)

    session, waiting, action = await _waiting_run(runtime)
    context = runtime._context("w1")

    assert waiting.status == "waiting_for_approval"
    assert context.repository.get_session(session.id).status == "waiting_for_approval"
    assert context.repository.list_messages(session.id) == ()
    assert [event.type for event in context.repository.list_events(session.id)] == [
        "session.created",
        "run.started",
        "hitl.required",
    ]
    assert action.workspace_id == "w1"
    assert action.session_id == session.id
    assert action.run_id == waiting.id
    assert action.preview == {"summary": "original"}
    assert len(await runtime.list_actions("w1", status="pending")) == 1
    await runtime.close()


@pytest.mark.asyncio
async def test_restart_preserves_action_and_approval_resumes_same_run(
    tmp_path: Path,
) -> None:
    first_runtime = _runtime(tmp_path)
    session, waiting, action = await _waiting_run(first_runtime)
    await first_runtime.close()

    restarted = _runtime(tmp_path)
    pending = await restarted.list_actions("w1", status="pending")
    assert pending == (action,)

    resolved = await restarted.approve_action(
        action.id,
        ResolveActionCommand(
            version=action.version,
            idempotency_key="approve-1",
            edited_payload={"summary": "edited"},
        ),
    )
    completed = await restarted._context("w1").manager.wait(waiting.id)

    assert resolved.status == "edited_and_approved"
    assert completed.id == waiting.id
    assert completed.status == "completed"
    assert completed.resume_count == 1
    messages = restarted._context("w1").repository.list_messages(session.id)
    assert messages[-1].content == "确认测试已批准：edited"
    assert len(await restarted.list_actions("w1", status="pending")) == 0
    assert len(await restarted.list_actions("w1", status="edited_and_approved")) == 1
    await restarted.close()


@pytest.mark.asyncio
async def test_cancel_waiting_run_cancels_pending_action(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _session, waiting, action = await _waiting_run(runtime)

    cancelled = await runtime.cancel_run(waiting.id)
    stored = await runtime.get_action(action.id)

    assert cancelled.status == "cancelled"
    assert stored.status == "cancelled"
    assert await runtime.list_actions("w1", status="pending") == ()
    await runtime.close()


@pytest.mark.asyncio
async def test_startup_reconciles_resolution_left_delivering(
    tmp_path: Path,
) -> None:
    first_runtime = _runtime(tmp_path)
    _session, waiting, action = await _waiting_run(first_runtime)
    context = first_runtime._context("w1")
    receipt = await context.hitl_repository.resolve(
        action.id,
        expected_version=action.version,
        status="approved",
        resolution_key="approve-1",
        decision={
            "actionId": action.id,
            "decision": "approved",
            "payload": action.payload,
        },
    )
    await context.hitl_repository.mark_delivering(receipt.id)
    await first_runtime.close()

    restarted = _runtime(tmp_path)
    recovered = await restarted.recover_interrupted_runs()
    completed = await restarted._context("w1").manager.wait(waiting.id)
    stored_receipt = (
        await restarted._context("w1").hitl_repository.list_resolutions(action.id)
    )[0]

    assert recovered == ()
    assert completed.status == "completed"
    assert completed.resume_count == 1
    assert stored_receipt.delivery_status == "delivered"
    assert stored_receipt.delivery_attempts == 2
    await restarted.close()


@pytest.mark.asyncio
async def test_interrupt_rejects_action_id_not_created_by_runtime(
    tmp_path: Path,
) -> None:
    registry = GraphRegistry()

    def factory(context):
        graph = StateGraph(dict)
        graph.add_node("invalid", lambda _state: interrupt({"actionId": "fake"}))
        graph.add_edge(START, "invalid")
        graph.add_edge("invalid", END)
        return graph.compile(checkpointer=context.checkpointer)

    registry.register(
        GraphDefinition(
            graph_id="test.invalid-approval",
            graph_version=1,
            factory=factory,
            required_model_roles=frozenset(),
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
        )
    )
    runtime = AgentRuntime(
        graph_registry=registry,
        workspace_resolver=lambda _workspace_id: tmp_path,
        model_binding_resolver=lambda _workspace_id: {},
        workspace_ids=lambda: ("w1",),
    )
    session = await runtime.create_session(
        workspace_id="w1",
        graph_id="test.invalid-approval",
        graph_version=1,
        title="Invalid",
    )

    run = await runtime.start_run(session.id, input={})
    failed = await runtime._context("w1").manager.wait(run.id)

    assert failed.status == "failed"
    assert await runtime.list_actions("w1", status="pending") == ()
    await runtime.close()
