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
            json={"input": {"text": "hello"}},
        )
        assert started.status_code == 202
        execution = started.json()
        assert execution["status"] == "running"
        assert "modelBindings" not in execution

        completed = await application.wait_execution(execution["id"])
        assert completed.status == "completed"

        detail = (await client.get(f"/api/agent/sessions/{session['id']}")).json()
        assert detail["latestExecution"]["status"] == "completed"
        assert detail["messages"][-1]["content"] == "Echo: hello"


@pytest.mark.asyncio
async def test_cancel_and_replay_cursor_are_product_level(api, application):
    slow = await application.create_session(
        workspace_id="w1", kind="diagnostic.slow", title="Slow"
    )
    running = await application.start_execution(slow.id, input={"text": "wait"})
    cancelled = await application.cancel_execution(running.id)
    assert cancelled.status == "cancelled"

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
async def test_review_draft_is_pending_as_soon_as_execution_requests_approval(application):
    session = await application.create_session(
        workspace_id="w1", kind="diagnostic.draft", title="Draft"
    )
    execution = await application.start_execution(session.id, input={})
    await application.wait_execution(execution.id)

    drafts = await application.list_drafts("w1")
    assert drafts[0]["status"] == "review_pending"
