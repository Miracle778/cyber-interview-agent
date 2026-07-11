import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TypedDict

import pytest
from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph

from app.api.dependencies import get_agent_runtime
from app.main import app
from app.runtime.graph_registry import GraphDefinition, GraphRegistry
from app.runtime.service import AgentRuntime


class EchoState(TypedDict, total=False):
    text: str
    response: str


def echo_registry(*, gate: asyncio.Event | None = None) -> GraphRegistry:
    def factory(checkpointer):
        async def echo(state):
            if gate is not None:
                await gate.wait()
            return {"response": f"Echo: {state['text']}"}

        graph = StateGraph(EchoState)
        graph.add_node("echo", echo)
        graph.add_edge(START, "echo")
        graph.add_edge("echo", END)
        return graph.compile(checkpointer=checkpointer)

    registry = GraphRegistry()
    registry.register(
        GraphDefinition(
            graph_id="test.echo",
            graph_version=1,
            factory=factory,
            required_model_roles=frozenset(),
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
        )
    )
    return registry


@pytest.fixture
def agent_client(tmp_path: Path):
    runtime = AgentRuntime(
        graph_registry=echo_registry(),
        workspace_resolver=lambda workspace_id: tmp_path / workspace_id,
        model_binding_resolver=lambda _workspace_id: {},
        workspace_ids=lambda: ("w1",),
    )
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    try:
        with TestClient(app) as client:
            yield client, runtime
    finally:
        app.dependency_overrides.clear()
        asyncio.run(runtime.close())


def test_session_create_list_detail_and_run(agent_client):
    client, _runtime = agent_client
    response = client.post(
        "/api/agent/sessions",
        json={
            "workspaceId": "w1",
            "graphId": "test.echo",
            "graphVersion": 1,
            "title": "Echo",
        },
    )
    assert response.status_code == 201
    session_id = response.json()["id"]

    listed = client.get("/api/agent/sessions", params={"workspaceId": "w1"})
    assert [item["id"] for item in listed.json()] == [session_id]

    started = client.post(
        f"/api/agent/sessions/{session_id}/runs",
        json={"input": {"text": "hello"}},
    )
    assert started.status_code == 202
    run_id = started.json()["id"]

    for _ in range(50):
        detail = client.get(f"/api/agent/sessions/{session_id}")
        if detail.json()["latestRun"]["status"] == "completed":
            break
        asyncio.run(asyncio.sleep(0.01))

    body = detail.json()
    assert body["latestRun"]["id"] == run_id
    assert body["messages"][-1]["content"] == "Echo: hello"
    assert "checkpoint" not in body

    repository = _runtime._context("w1").repository
    repository.transition_run(run_id, expected="completed", target="interrupted")
    resumed = client.post(f"/api/agent/runs/{run_id}/resume")
    assert resumed.status_code == 202
    assert resumed.json()["id"] == run_id
    assert resumed.json()["resumeCount"] == 1


def test_concurrent_run_returns_structured_conflict(tmp_path: Path):
    gate = asyncio.Event()
    runtime = AgentRuntime(
        graph_registry=echo_registry(gate=gate),
        workspace_resolver=lambda workspace_id: tmp_path / workspace_id,
        model_binding_resolver=lambda _workspace_id: {},
        workspace_ids=lambda: ("w1",),
    )
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    try:
        with TestClient(app) as client:
            session = client.post(
                "/api/agent/sessions",
                json={
                    "workspaceId": "w1",
                    "graphId": "test.echo",
                    "graphVersion": 1,
                    "title": "Echo",
                },
            ).json()
            first = client.post(
                f"/api/agent/sessions/{session['id']}/runs",
                json={"input": {"text": "one"}},
            )
            assert first.status_code == 202
            conflict = client.post(
                f"/api/agent/sessions/{session['id']}/runs",
                json={"input": {"text": "two"}},
            )
            assert conflict.status_code == 409
            assert conflict.json()["code"] == "session_busy"
            cancelled = client.post(f"/api/agent/runs/{first.json()['id']}/cancel")
            repeated = client.post(f"/api/agent/runs/{first.json()['id']}/cancel")
            assert cancelled.json()["status"] == "cancelled"
            assert repeated.json()["status"] == "cancelled"
    finally:
        app.dependency_overrides.clear()
        asyncio.run(runtime.close())


def test_sse_prefers_query_cursor_then_last_event_id():
    seen: list[int | None] = []

    class FakeRuntime:
        async def events(
            self, _session_id: str, *, after_id: int | None
        ) -> AsyncIterator[str]:
            seen.append(after_id)
            yield "id: 8\nevent: run.completed\ndata: {}\n\n"

    app.dependency_overrides[get_agent_runtime] = lambda: FakeRuntime()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/agent/sessions/s1/events?after=7",
                headers={"Last-Event-ID": "6"},
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            response = client.get(
                "/api/agent/sessions/s1/events", headers={"Last-Event-ID": "6"}
            )
        assert seen == [7, 6]
    finally:
        app.dependency_overrides.clear()
