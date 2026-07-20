from __future__ import annotations

from pathlib import Path
import asyncio

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.graph import END, START, StateGraph

from app.api.dependencies import get_agent_application
from app.api.routes_agent import router as agent_router
from app.application.workspace_runtime import AgentApplication


def _graph_factory(kind, **dependencies):
    graph = StateGraph(dict)

    async def respond(state):
        if kind == "diagnostic.draft":
            draft = await dependencies["create_draft"](
                title="Review report",
                markdown="# Review report",
                source_refs=(),
                relation_refs=(),
            )
            return {"response": draft.id}
        if kind == "diagnostic.slow":
            await asyncio.Event().wait()
        if kind not in {"diagnostic.echo", "diagnostic.slow", "diagnostic.draft"}:
            raise ValueError(f"unknown agent kind: {kind}")
        return {"response": f"Echo: {state['text']}"}

    graph.add_node("respond", respond)
    graph.add_edge(START, "respond")
    graph.add_edge("respond", END)
    return graph.compile()


@pytest_asyncio.fixture
async def application(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    value = AgentApplication(
        workspace_resolver=lambda workspace_id: workspace,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=_graph_factory,
    )
    try:
        yield value
    finally:
        await value.close()


@pytest.fixture
def api(application):
    api = FastAPI()
    api.include_router(agent_router)
    api.dependency_overrides[get_agent_application] = lambda: application
    return api


@pytest.mark.asyncio
async def test_session_and_execution_resources_do_not_expose_graph_internals(api, application):
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        created = await client.post(
            "/api/agent/sessions",
            json={"workspaceId": "w1", "kind": "diagnostic.echo", "title": "Echo"},
        )
        assert created.status_code == 201
        session = created.json()
        assert session["kind"] == "diagnostic.echo"
        assert "graphId" not in session

        started = await client.post(
            f"/api/agent/sessions/{session['id']}/executions",
            json={
                "input": {"text": "hello"},
                "configuration": {
                    "providerModelId": "model-1",
                    "reasoningEffort": "medium",
                },
            },
        )
        assert started.status_code == 202
        execution = started.json()
        assert execution["status"] == "running"
        assert execution["configuration"] == {
            "providerModelId": "model-1",
            "reasoningEffort": "medium",
        }
        assert "modelBindings" not in execution

        completed = await application.wait_execution(execution["id"])
        assert completed.status == "completed"

        detail = (await client.get(f"/api/agent/sessions/{session['id']}")).json()
        assert detail["latestExecution"]["status"] == "completed"
        assert detail["contextUsage"] == {
            "currentTokens": 0,
            "thresholdTokens": 0,
            "estimated": True,
        }
        assert detail["messages"][-1]["content"] == "Echo: hello"
        assert detail["messages"][-1]["messageKind"] == "text"
        assert detail["messages"][-1]["payload"] == {}


@pytest.mark.asyncio
async def test_cancel_and_replay_cursor_are_product_level(api, application):
    slow = await application.create_session(
        workspace_id="w1", kind="diagnostic.slow", title="Slow"
    )
    running = await application.start_execution(slow.id, input={"text": "wait"})
    cancelled = await application.cancel_execution(running.id)
    assert cancelled.status == "cancelled"

    cancel_events = application.replay_events(slow.id, after_id=None)
    assert [event.type for event in cancel_events][-2:] == [
        "execution.cancelling",
        "execution.cancelled",
    ]

    session = await application.create_session(
        workspace_id="w1", kind="diagnostic.echo", title="Echo"
    )
    execution = await application.start_execution(session.id, input={"text": "hello"})
    await application.wait_execution(execution.id)

    all_events = application.replay_events(session.id, after_id=None)
    replayed = application.replay_events(session.id, after_id=all_events[0].id)

    assert [event.type for event in all_events] == [
        "session.created",
        "execution.started",
        "assistant.delta",
        "execution.completed",
    ]
    assert [event.id for event in replayed] == [event.id for event in all_events[1:]]


@pytest.mark.asyncio
async def test_completed_execution_wins_race_with_late_cancel(application):
    session = await application.create_session(
        workspace_id="w1", kind="diagnostic.echo", title="Echo"
    )
    execution = await application.start_execution(session.id, input={"text": "done"})
    completed = await application.wait_execution(execution.id)

    repeated = await application.cancel_execution(execution.id)

    assert completed.status == "completed"
    assert repeated.status == "completed"
    assert [
        event.type
        for event in application.replay_events(session.id, after_id=None)
    ].count("execution.cancelled") == 0


@pytest.mark.asyncio
async def test_domain_handler_finishes_critical_section_before_cancel(application):
    session = await application.create_session(
        workspace_id="w1", kind="diagnostic.echo", title="Critical"
    )
    runtime = application._context("w1").executions
    execution = await runtime.prepare(
        session,
        input={"operation": "test.critical"},
        project_input_message=False,
        configuration={},
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    committed: list[str] = []

    async def handler(current, cancellation):
        with cancellation.critical_section():
            entered.set()
            await release.wait()
            committed.append(current.id)
        cancellation.raise_if_requested()

    runtime.run_background(execution, handler)
    await entered.wait()
    cancelling = await application.cancel_execution(execution.id)
    assert cancelling.status == "running"
    assert cancelling.cancel_requested_at is not None
    assert committed == []

    release.set()
    terminal = await application.wait_execution(execution.id)

    assert committed == [execution.id]
    assert terminal.status == "cancelled"


@pytest.mark.asyncio
async def test_graceful_close_waits_for_domain_critical_section(application):
    session = await application.create_session(
        workspace_id="w1", kind="diagnostic.echo", title="Graceful close"
    )
    runtime = application._context("w1").executions
    execution = await runtime.prepare(
        session,
        input={"operation": "test.graceful-close"},
        project_input_message=False,
        configuration={},
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    committed: list[str] = []

    async def handler(current, cancellation):
        with cancellation.critical_section():
            entered.set()
            await release.wait()
            committed.append(current.id)

    runtime.run_background(execution, handler)
    await entered.wait()
    closing = asyncio.create_task(application.close())
    await asyncio.sleep(0)

    assert closing.done() is False
    assert committed == []

    release.set()
    await closing

    assert committed == [execution.id]


@pytest.mark.asyncio
async def test_missing_session_event_stream_stops_browser_reconnects(api):
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        response = await client.get("/api/agent/sessions/missing-session/events?after=54")

    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_session_soft_delete_hides_history_and_stops_event_stream(api):
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        session = (await client.post(
            "/api/agent/sessions",
            json={"workspaceId": "w1", "kind": "diagnostic.echo", "title": "Echo"},
        )).json()

        deleted = await client.delete(f"/api/agent/sessions/{session['id']}")

        assert deleted.status_code == 204
        assert (await client.get(
            "/api/agent/sessions", params={"workspaceId": "w1"}
        )).json() == []
        assert (await client.get(
            f"/api/agent/sessions/{session['id']}/events"
        )).status_code == 204

        restored = await client.post(f"/api/agent/sessions/{session['id']}/restore")
        assert restored.status_code == 200
        assert restored.json()["id"] == session["id"]


@pytest.mark.asyncio
async def test_review_draft_is_pending_as_soon_as_execution_requests_approval(application):
    session = await application.create_session(
        workspace_id="w1", kind="diagnostic.draft", title="Draft"
    )
    execution = await application.start_execution(session.id, input={})
    await application.wait_execution(execution.id)

    drafts = await application.list_drafts("w1")
    assert drafts[0]["status"] == "review_pending"


@pytest.mark.asyncio
async def test_hidden_ingest_session_excluded_from_generic_list_and_detail(
    api, application
):
    context = application._context("w1")
    context.repository.create_session(
        workspace_id="w1",
        kind="profile.ingest",
        title="hidden ingest",
        session_id="hidden-ingest-1",
        visibility="system",
    )
    await application.create_session(
        workspace_id="w1", kind="diagnostic.echo", title="User session"
    )

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        listed = (
            await client.get("/api/agent/sessions", params={"workspaceId": "w1"})
        ).json()
        ids = [item["id"] for item in listed]
        assert "hidden-ingest-1" not in ids
        assert any(item["title"] == "User session" for item in listed)

        detail = await client.get("/api/agent/sessions/hidden-ingest-1")
        assert detail.status_code == 404
