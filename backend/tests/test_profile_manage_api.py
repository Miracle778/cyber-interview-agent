from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langgraph.graph import END, START, StateGraph

from app.api.dependencies import get_agent_application
from app.application.workspace_runtime import AgentApplication
from app.main import app


@pytest_asyncio.fixture
async def profile_application(tmp_path: Path):
    root = tmp_path / "w1"
    root.mkdir()
    blocking_started = asyncio.Event()

    def graph_factory(_kind: str, **dependencies):
        async def answer(state):
            if state.get("message") == "block":
                blocking_started.set()
                await asyncio.Future()
            return {"response": "画像回答"}

        graph = StateGraph(dict)
        graph.add_node("answer", answer)
        graph.add_edge(START, "answer")
        graph.add_edge("answer", END)
        return graph.compile(checkpointer=dependencies.get("checkpointer"))

    application = AgentApplication(
        workspace_resolver=lambda _workspace_id: root,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=graph_factory,
    )
    app.dependency_overrides[get_agent_application] = lambda: application
    try:
        yield application, blocking_started
    finally:
        app.dependency_overrides.pop(get_agent_application, None)
        await application.close()


@pytest.mark.asyncio
async def test_profile_sessions_reuse_generic_execution_and_replay(
    profile_application,
) -> None:
    application, _started = profile_application
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/workspaces/w1/profile/sessions", json={"title": "简历优化"}
        )
        session_id = created.json()["id"]
        listed = await client.get("/api/workspaces/w1/profile/sessions")
        execution = await client.post(
            f"/api/agent/sessions/{session_id}/executions",
            json={"input": {"message": "介绍我的画像"}},
        )
        terminal = await application.wait_execution(execution.json()["id"])
        detail = await client.get(f"/api/agent/sessions/{session_id}")

    assert created.status_code == 201
    assert created.json()["kind"] == "profile.manage"
    assert [item["id"] for item in listed.json()] == [session_id]
    assert terminal.status == "completed"
    assert [item["content"] for item in detail.json()["messages"]] == [
        "介绍我的画像",
        "画像回答",
    ]
    event_types = [item.type for item in application.replay_events(session_id, after_id=0)]
    assert event_types[-1] == "execution.completed"


@pytest.mark.asyncio
async def test_profile_session_archive_is_listed_separately_and_can_be_restored(
    profile_application,
) -> None:
    application, _started = profile_application
    context = application._context("w1")
    context.repository.create_session(
        workspace_id="w1",
        kind="diagnostic.echo",
        title="其他 Agent 会话",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/workspaces/w1/profile/sessions", json={}
        )
        session_id = created.json()["id"]
        assert created.json()["title"] == "新会话"

        archived = await client.delete(f"/api/agent/sessions/{session_id}")
        active = await client.get("/api/workspaces/w1/profile/sessions")
        recycle_bin = await client.get(
            "/api/workspaces/w1/profile/sessions", params={"deletedOnly": "true"}
        )
        restored = await client.post(f"/api/agent/sessions/{session_id}/restore")

    assert archived.status_code == 204
    assert active.json() == []
    assert [item["id"] for item in recycle_bin.json()] == [session_id]
    assert recycle_bin.json()[0]["deletedAt"] is not None
    assert restored.status_code == 200
    assert restored.json()["deletedAt"] is None


@pytest.mark.asyncio
async def test_profile_execution_can_cancel_and_hidden_session_creation_is_rejected(
    profile_application,
) -> None:
    _application, started = profile_application
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        hidden = await client.post(
            "/api/agent/sessions",
            json={"workspaceId": "w1", "kind": "profile.ingest"},
        )
        session = await client.post(
            "/api/workspaces/w1/profile/sessions", json={}
        )
        execution = await client.post(
            f"/api/agent/sessions/{session.json()['id']}/executions",
            json={"input": {"message": "block"}},
        )
        await started.wait()
        cancelled = await client.post(
            f"/api/agent/executions/{execution.json()['id']}/cancel"
        )

    assert hidden.status_code == 422
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
