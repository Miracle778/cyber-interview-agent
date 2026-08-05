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
from app.diagnostics.agent_trace import read_trace_rows
from app.observability.registry import require_registration


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


def _test_registration_guard(kind: str, *, for_user_creation: bool = False):
    if kind in {"diagnostic.echo", "diagnostic.slow", "diagnostic.draft"}:
        return None
    return require_registration(kind, for_user_creation=for_user_creation)


@pytest_asyncio.fixture
async def application(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    value = AgentApplication(
        workspace_resolver=lambda workspace_id: workspace,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=_graph_factory,
        registration_guard=_test_registration_guard,
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
async def test_unregistered_agent_session_is_rejected_without_database_writes(
    api, application
):
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/agent/sessions",
            json={"workspaceId": "w1", "kind": "unknown.agent"},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "agent_not_registered"
    row = application._context("w1").repository.connection.execute(
        "SELECT COUNT(*) AS count FROM agent_sessions"
    ).fetchone()
    assert row["count"] == 0


@pytest.mark.asyncio
async def test_system_only_agent_session_is_rejected_by_public_api(
    api, application
):
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/agent/sessions",
            json={"workspaceId": "w1", "kind": "knowledge.publish"},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "agent_not_user_creatable"


@pytest.mark.asyncio
async def test_unregistered_historical_session_cannot_start_a_new_execution(
    api, application
):
    context = application._context("w1")
    session = context.repository.create_session(
        workspace_id="w1",
        kind="removed.agent.v1",
        title="Historical session",
    )

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/agent/sessions/{session.id}/executions",
            json={"input": {"text": "do not run"}},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "agent_not_registered"
    row = context.repository.connection.execute(
        "SELECT COUNT(*) AS count FROM agent_runs WHERE session_id = ?",
        (session.id,),
    ).fetchone()
    assert row["count"] == 0


@pytest.mark.asyncio
async def test_unregistered_historical_execution_cannot_be_retried(
    api, application
):
    context = application._context("w1")
    session = context.repository.create_session(
        workspace_id="w1",
        kind="removed.agent.v1",
        title="Historical session",
    )
    execution = context.repository.create_execution(
        session.id, input={"text": "old"}, model_bindings={}
    )
    context.repository.transition_execution(
        execution.id,
        expected=("running",),
        target="failed",
        error_code="legacy_failure",
        error_message="legacy failure",
    )

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/agent/executions/{execution.id}/retry", json={}
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "agent_not_registered"
    row = context.repository.connection.execute(
        "SELECT COUNT(*) AS count FROM agent_runs WHERE session_id = ?",
        (session.id,),
    ).fetchone()
    assert row["count"] == 1


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
        assert execution["inputMessageId"]
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
        trace_rows = read_trace_rows(
            application._context("w1").root, session["id"], execution["id"]
        )
        assert [row["event_type"] for row in trace_rows] == [
            "execution.started", "execution.completed"
        ]
        assert {row["agent_name"] for row in trace_rows} == {
            "execution_runtime"
        }


@pytest.mark.asyncio
async def test_failed_execution_can_retry_without_duplicate_user_message(api, application):
    session = await application.create_session(
        workspace_id="w1", kind="diagnostic.echo", title="Echo"
    )
    context = application._context("w1")
    message = context.repository.append_user_message(
        session.id, content="hello again"
    )
    failed = context.repository.create_execution(
        session.id,
        input={"text": "hello again"},
        model_bindings={},
        input_message_id=message.id,
    )
    context.repository.transition_execution(
        failed.id,
        expected=("running",),
        target="failed",
        error_code="provider_error",
        error_message="provider unavailable",
    )
    context.repository.resolve_message(
        message.id, expected=("active",), target="unresolved"
    )

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/agent/executions/{failed.id}/retry", json={}
        )
        assert response.status_code == 202
        retried = response.json()
        await application.wait_execution(retried["id"])

        detail = (await client.get(f"/api/agent/sessions/{session.id}")).json()

    assert retried["retryOfExecutionId"] == failed.id
    assert retried["inputMessageId"] == message.id
    assert [item["content"] for item in detail["messages"]].count("hello again") == 1
    assert detail["messages"][0]["resolutionStatus"] == "active"


@pytest.mark.asyncio
async def test_cancel_and_replay_cursor_are_product_level(api, application):
    slow = await application.create_session(
        workspace_id="w1", kind="diagnostic.slow", title="Slow"
    )
    running = await application.start_execution(slow.id, input={"text": "wait"})
    background_task = application._context("w1").executions._tasks[running.id]
    cancelled = await application.cancel_execution(running.id)
    assert cancelled.status == "cancelled"
    assert background_task.cancelled() is True

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
async def test_curation_control_event_is_safe_and_replayable(application):
    session = await application.create_session(
        workspace_id="w1", kind="diagnostic.echo", title="Control event"
    )
    context = application._context("w1")
    event = await context.events.publish(
        session.id,
        None,
        "curation.control.changed",
        {
            "resourceId": session.id,
            "batchId": "batch-1",
            "status": "pausing",
            "operation": "pause",
            "version": 2,
        },
    )

    replayed = application.replay_events(session.id, after_id=event.id - 1)

    assert [(item.type, item.payload) for item in replayed] == [
        (
            "curation.control.changed",
            {
                "resourceId": session.id,
                "batchId": "batch-1",
                "status": "pausing",
                "operation": "pause",
                "version": 2,
            },
        )
    ]


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
async def test_session_title_can_be_renamed_only_inside_its_workspace(api, application):
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        session = (
            await client.post(
                "/api/agent/sessions",
                json={"workspaceId": "w1", "kind": "diagnostic.echo"},
            )
        ).json()

        blank = await client.patch(
            f"/api/agent/sessions/{session['id']}",
            json={"workspaceId": "w1", "title": "   "},
        )
        wrong_workspace = await client.patch(
            f"/api/agent/sessions/{session['id']}",
            json={"workspaceId": "w2", "title": "不应生效"},
        )
        renamed = await client.patch(
            f"/api/agent/sessions/{session['id']}",
            json={"workspaceId": "w1", "title": "  后端项目复盘  "},
        )

    assert blank.status_code == 422
    assert wrong_workspace.status_code == 404
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "后端项目复盘"
    stored = application._context("w1").repository.connection.execute(
        "SELECT title_source FROM agent_sessions WHERE id = ?", (session["id"],)
    ).fetchone()
    assert stored["title_source"] == "user"
    assert application.replay_events(session["id"], after_id=0)[-1].type == "session.renamed"


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


@pytest.mark.asyncio
async def test_hidden_ingest_session_cannot_be_mutated_by_generic_routes(
    api, application
):
    context = application._context("w1")
    context.repository.create_session(
        workspace_id="w1",
        kind="profile.ingest",
        title="hidden ingest",
        session_id="hidden-ingest-2",
        visibility="system",
    )

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        deleted = await client.delete("/api/agent/sessions/hidden-ingest-2")
        restored = await client.post("/api/agent/sessions/hidden-ingest-2/restore")

    assert deleted.status_code == 404
    assert restored.status_code == 404
    assert context.repository.get_session("hidden-ingest-2").visibility == "system"


@pytest.mark.asyncio
async def test_hidden_ingest_execution_cannot_be_cancelled_by_generic_route(
    api, application
):
    context = application._context("w1")
    context.repository.create_session(
        workspace_id="w1",
        kind="profile.ingest",
        title="hidden ingest",
        session_id="hidden-ingest-3",
        visibility="system",
    )
    execution = context.repository.create_execution(
        "hidden-ingest-3", input={}, model_bindings={}
    )

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        response = await client.post(f"/api/agent/executions/{execution.id}/cancel")

    assert response.status_code == 404
    assert context.repository.get_execution(execution.id).status == "running"
