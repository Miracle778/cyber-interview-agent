from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_agent_application
from app.api import routes_observability
from app.application.workspace_runtime import AgentApplication
from app.diagnostics.agent_trace import AgentTraceWriter, TraceIdentity
from app.main import app as production_app


def _unused_graph_factory(kind: str, **_dependencies):
    raise AssertionError(f"route tests must not execute graph {kind}")


@pytest_asyncio.fixture
async def application(tmp_path: Path):
    roots = {
        "workspace-1": tmp_path / "workspace-1",
        "workspace-2": tmp_path / "workspace-2",
    }
    for root in roots.values():
        root.mkdir()
    value = AgentApplication(
        workspace_resolver=lambda workspace_id: roots[workspace_id],
        workspace_ids=lambda: tuple(roots),
        model_bindings=lambda _workspace_id: {},
        graph_factory=_unused_graph_factory,
    )
    try:
        yield value
    finally:
        await value.close()


@pytest.fixture
def api(application):
    value = FastAPI()
    value.include_router(routes_observability.router)
    value.dependency_overrides[get_agent_application] = lambda: application
    return value


async def _insert_run(
    application: AgentApplication,
    *,
    workspace_id: str,
    run_id: str,
    graph_id: str = "review.round",
    status: str = "completed",
    title: str | None = None,
    visibility: str = "user",
    created_at: str = "2026-07-29T12:00:00+00:00",
):
    context = application._context(workspace_id)
    session_id = f"session-{run_id}"
    context.connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title, visibility) "
        "VALUES (?, ?, ?, 1, ?, ?)",
        (session_id, workspace_id, graph_id, title or run_id, visibility),
    )
    context.connection.execute(
        "INSERT INTO agent_runs "
        "(id, session_id, status, input_json, model_bindings_json, "
        "configuration_json, created_at, started_at, finished_at, error_code) "
        "VALUES (?, ?, ?, '{}', '{}', '{}', ?, ?, ?, ?)",
        (
            run_id,
            session_id,
            status,
            created_at,
            created_at,
            created_at if status in {"completed", "failed", "cancelled"} else None,
            "provider_error" if status == "failed" else None,
        ),
    )
    context.connection.commit()
    return context, session_id


@pytest.mark.asyncio
async def test_list_is_workspace_scoped_and_cursor_filters_round_trip(
    api, application
) -> None:
    await _insert_run(
        application,
        workspace_id="workspace-1",
        run_id="run-new",
        title="画像复习",
        created_at="2026-07-29T12:00:02+00:00",
    )
    await _insert_run(
        application,
        workspace_id="workspace-1",
        run_id="run-old",
        status="failed",
        title="失败复习",
        created_at="2026-07-29T12:00:01+00:00",
    )
    await _insert_run(
        application,
        workspace_id="workspace-2",
        run_id="run-other-workspace",
        created_at="2026-07-29T12:00:03+00:00",
    )

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        first = await client.get(
            "/api/agent-observability/executions",
            params={"workspaceId": "workspace-1", "limit": 1},
        )
        second = await client.get(
            "/api/agent-observability/executions",
            params={
                "workspaceId": "workspace-1",
                "limit": 1,
                "cursor": first.json()["nextCursor"],
            },
        )
        failed = await client.get(
            "/api/agent-observability/executions",
            params={"workspaceId": "workspace-1", "status": "failed"},
        )
        searched = await client.get(
            "/api/agent-observability/executions",
            params={"workspaceId": "workspace-1", "search": "画像"},
        )

    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 2
    assert [item["id"] for item in first.json()["items"]] == ["run-new"]
    assert [item["id"] for item in second.json()["items"]] == ["run-old"]
    assert [item["id"] for item in failed.json()["items"]] == ["run-old"]
    assert [item["id"] for item in searched.json()["items"]] == ["run-new"]
    assert "run-other-workspace" not in {
        item["id"] for item in first.json()["items"] + second.json()["items"]
    }


@pytest.mark.asyncio
async def test_system_agents_are_opt_in_and_trace_missing_does_not_hide_run(
    api, application
) -> None:
    await _insert_run(
        application,
        workspace_id="workspace-1",
        run_id="run-business",
    )
    await _insert_run(
        application,
        workspace_id="workspace-1",
        run_id="run-system",
        graph_id="profile.ingest",
        visibility="system",
    )

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        default_page = await client.get(
            "/api/agent-observability/executions",
            params={"workspaceId": "workspace-1"},
        )
        with_system = await client.get(
            "/api/agent-observability/executions",
            params={
                "workspaceId": "workspace-1",
                "includeSystemAgents": "true",
            },
        )
        detail = await client.get(
            "/api/agent-observability/executions/run-business",
            params={"workspaceId": "workspace-1"},
        )
        operations = await client.get(
            "/api/agent-observability/executions/run-business/operations",
            params={"workspaceId": "workspace-1"},
        )

    assert [item["id"] for item in default_page.json()["items"]] == [
        "run-business"
    ]
    assert {item["id"] for item in with_system.json()["items"]} == {
        "run-business",
        "run-system",
    }
    assert detail.status_code == 200
    assert detail.json()["traceHealth"] == "missing"
    assert operations.json() == {"items": []}


@pytest.mark.asyncio
async def test_cross_workspace_detail_is_hidden_as_not_found(api, application) -> None:
    await _insert_run(
        application,
        workspace_id="workspace-2",
        run_id="run-private",
    )

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/agent-observability/executions/run-private",
            params={"workspaceId": "workspace-1"},
        )

    assert response.status_code == 404
    assert response.json() == {
        "code": "agent_execution_not_found",
        "message": "Agent Execution 不存在或无权访问",
    }


@pytest.mark.asyncio
async def test_event_content_route_requires_advanced_diagnostics(
    api, application
) -> None:
    await _insert_run(
        application,
        workspace_id="workspace-1",
        run_id="run-private-body",
    )

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/agent-observability/executions/run-private-body/"
            "events/event-private/content",
            params={"workspaceId": "workspace-1"},
        )

    assert response.status_code == 409
    assert response.json()["code"] == "advanced_diagnostics_disabled"


@pytest.mark.asyncio
async def test_event_content_route_reads_indexed_payload_and_omits_reasoning(
    api, application
) -> None:
    context, session_id = await _insert_run(
        application,
        workspace_id="workspace-1",
        run_id="run-content",
    )
    context.agent_observability.advanced_diagnostics_enabled = lambda: True
    identity = TraceIdentity(
        workspace_id="workspace-1",
        workspace_root=context.root,
        session_id=session_id,
        run_id="run-content",
        agent_role="answer_evaluation",
        agent_name="review_answer_evaluation",
        invocation_id="invocation-content",
    )
    AgentTraceWriter().append(
        identity,
        "model.response",
        {"structured_response": {"score": 4}},
    )
    context.agent_observability.sync()
    event_id = context.agent_observability.trace_repository.list_events(
        "run-content"
    )[0]["event_id"]

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/agent-observability/executions/run-content/"
            f"events/{event_id}/content",
            params={"workspaceId": "workspace-1"},
        )

    assert response.status_code == 200
    body = response.json()
    assert json.loads(body["content"]) == {
        "structured_response": {"score": 4}
    }
    assert "reasoning" not in body
    assert body["contentEncoding"] == "utf-8-json"


@pytest.mark.asyncio
async def test_event_content_route_hides_cross_workspace_run(
    api, application
) -> None:
    context, session_id = await _insert_run(
        application,
        workspace_id="workspace-2",
        run_id="run-other-content",
    )
    context.agent_observability.advanced_diagnostics_enabled = lambda: True
    AgentTraceWriter().append(
        TraceIdentity(
            workspace_id="workspace-2",
            workspace_root=context.root,
            session_id=session_id,
            run_id="run-other-content",
            agent_role="answer_evaluation",
            agent_name="review_answer_evaluation",
            invocation_id="invocation-other-content",
        ),
        "model.request",
        {"messages": ["private"]},
    )
    context.agent_observability.sync()
    event_id = context.agent_observability.trace_repository.list_events(
        "run-other-content"
    )[0]["event_id"]
    workspace_one = application._context("workspace-1")
    workspace_one.agent_observability.advanced_diagnostics_enabled = lambda: True

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/agent-observability/executions/run-other-content/"
            f"events/{event_id}/content",
            params={"workspaceId": "workspace-1"},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "agent_execution_not_found"


@pytest.mark.asyncio
async def test_trace_export_route_creates_receipt_and_downloads_private_zip(
    api, application
) -> None:
    context, session_id = await _insert_run(
        application,
        workspace_id="workspace-1",
        run_id="run-export",
    )
    context.agent_observability.advanced_diagnostics_enabled = lambda: True
    AgentTraceWriter().append(
        TraceIdentity(
            workspace_id="workspace-1",
            workspace_root=context.root,
            session_id=session_id,
            run_id="run-export",
            agent_role="answer_evaluation",
            agent_name="review_answer_evaluation",
            invocation_id="invocation-export",
        ),
        "model.request",
        {"messages": ["private"]},
    )
    context.agent_observability.sync()

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/agent-observability/executions/run-export/exports",
            params={"workspaceId": "workspace-1"},
            headers={"Idempotency-Key": "route-export-001"},
            json={
                "metadataOnly": False,
                "includeStoredBodies": True,
            },
        )
        downloaded = await client.get(
            f"/api/agent-observability/exports/{created.json()['id']}",
            params={"workspaceId": "workspace-1"},
        )

    assert created.status_code == 201
    assert created.json()["includesBodies"] is True
    assert created.json()["status"] == "completed"
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/zip"
    assert downloaded.content.startswith(b"PK")


@pytest.mark.asyncio
async def test_trace_body_export_route_is_disabled_with_advanced_mode_off(
    api, application
) -> None:
    await _insert_run(
        application,
        workspace_id="workspace-1",
        run_id="run-export-disabled",
    )

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/agent-observability/executions/run-export-disabled/exports",
            params={"workspaceId": "workspace-1"},
            headers={"Idempotency-Key": "route-export-002"},
            json={
                "metadataOnly": False,
                "includeStoredBodies": True,
            },
        )

    assert response.status_code == 409
    assert response.json()["code"] == "advanced_diagnostics_disabled"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "message"),
    (
        (
            {"workspaceId": "workspace-1", "cursor": "not-a-cursor"},
            "分页游标无效",
        ),
        (
            {"workspaceId": "workspace-1", "startedFrom": "not-a-time"},
            "时间筛选格式无效",
        ),
        (
            {"workspaceId": "workspace-1", "limit": "0"},
            "每页数量必须在 1 到 200 之间",
        ),
    ),
)
async def test_invalid_query_uses_project_error_envelope(
    api, params, message
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/agent-observability/executions",
            params=params,
        )

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_observability_query",
        "message": message,
    }


@pytest.mark.asyncio
async def test_list_syncs_trace_index_with_a_debounce_guard(
    api, application, monkeypatch
) -> None:
    context, _session_id = await _insert_run(
        application,
        workspace_id="workspace-1",
        run_id="run-sync",
    )
    calls = 0
    original = context.agent_observability.indexer.sync_workspace

    def counted_sync():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(
        context.agent_observability.indexer,
        "sync_workspace",
        counted_sync,
    )

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        for _ in range(2):
            response = await client.get(
                "/api/agent-observability/executions",
                params={"workspaceId": "workspace-1"},
            )
            assert response.status_code == 200

    assert calls == 1


@pytest.mark.asyncio
async def test_sse_reconnect_replays_only_later_workspace_changes(
    application,
) -> None:
    context, session_id = await _insert_run(
        application,
        workspace_id="workspace-1",
        run_id="run-live",
        status="running",
    )
    first = context.repository.append_event(
        session_id,
        "run-live",
        "execution.started",
        {"status": "running"},
    )
    second = context.repository.append_event(
        session_id,
        "run-live",
        "execution.warning",
        {"code": "slow"},
    )
    other_context, other_session_id = await _insert_run(
        application,
        workspace_id="workspace-2",
        run_id="run-other-live",
        status="running",
    )
    other_context.repository.append_event(
        other_session_id,
        "run-other-live",
        "execution.started",
        {"status": "running"},
    )

    response = await routes_observability.stream_observability_events(
        workspace_id="workspace-1",
        after_event_id=str(first.id),
        last_event_id=None,
        application=application,
    )
    chunk = await anext(response.body_iterator)
    await response.body_iterator.aclose()

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert f"id: {second.id}\n" in chunk
    assert "event: execution.summary.changed\n" in chunk
    assert '"id":"run-live"' in chunk
    assert "run-other-live" not in chunk


def test_production_application_registers_observability_routes() -> None:
    paths = set(production_app.openapi()["paths"])
    assert "/api/agent-observability/executions" in paths
    assert "/api/agent-observability/events" in paths
    assert (
        "/api/agent-observability/executions/{run_id}/exports" in paths
    )
    assert "/api/agent-observability/exports/{export_id}" in paths
