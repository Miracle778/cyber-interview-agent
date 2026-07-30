from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_trace_cleanup_service,
    get_trace_retention_service,
)
from app.api.routes_observability import router
from app.observability.cleanup import TraceCleanupService
from app.observability.repository import TraceIndexRepository
from test_agent_trace_retention import _service


@pytest.mark.asyncio
async def test_retention_dry_run_confirmation_and_body_state_disclosure(
    tmp_path,
) -> None:
    connection, retention = _service(tmp_path)
    cleanup = TraceCleanupService(
        retention=retention,
        repository=TraceIndexRepository(connection),
    )
    api = FastAPI()
    api.include_router(router)
    api.dependency_overrides[get_trace_retention_service] = lambda: retention
    api.dependency_overrides[get_trace_cleanup_service] = lambda: cleanup
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            default = await client.get(
                "/api/agent-observability/retention",
                params={"workspaceId": "workspace-1"},
            )
            changed = await client.put(
                "/api/agent-observability/retention",
                params={"workspaceId": "workspace-1"},
                json={"bodyPolicy": "metadata_only", "bodyDays": None},
            )
            plan = await client.post(
                "/api/agent-observability/cleanup-plans",
                params={"workspaceId": "workspace-1"},
            )
            confirmed = await client.post(
                f"/api/agent-observability/cleanup-plans/{plan.json()['id']}/confirm",
                params={"workspaceId": "workspace-1"},
            )
            replay = await client.post(
                f"/api/agent-observability/cleanup-plans/{plan.json()['id']}/confirm",
                params={"workspaceId": "workspace-1"},
            )
        assert default.json()["bodyPolicy"] == "days"
        assert default.json()["bodyDays"] == 90
        assert changed.json()["bodyPolicy"] == "metadata_only"
        assert plan.json()["fileCount"] == 1
        assert plan.json()["totalBytes"] > 0
        assert confirmed.json()["status"] == replay.json()["status"] == "completed"
        assert connection.execute(
            "SELECT body_state FROM agent_trace_events LIMIT 1"
        ).fetchone()[0] == "deleted"
        assert "cost" not in str(confirmed.json()).casefold()
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_active_run_is_reported_and_not_cleaned(tmp_path) -> None:
    connection, retention = _service(tmp_path, status="running")
    cleanup = TraceCleanupService(
        retention=retention,
        repository=TraceIndexRepository(connection),
    )
    api = FastAPI()
    api.include_router(router)
    api.dependency_overrides[get_trace_retention_service] = lambda: retention
    api.dependency_overrides[get_trace_cleanup_service] = lambda: cleanup
    try:
        retention.replace_policy(body_policy="metadata_only")
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            plan = await client.post(
                "/api/agent-observability/cleanup-plans",
                params={"workspaceId": "workspace-1"},
            )
        assert plan.json()["fileCount"] == 0
        assert plan.json()["protectedActiveRuns"] == 1
    finally:
        connection.close()
