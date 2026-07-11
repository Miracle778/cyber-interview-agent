import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_agent_runtime
from app.main import app
from app.runtime.default_graphs import create_default_graph_registry
from app.runtime.service import AgentRuntime


@pytest.fixture
def hitl_client(tmp_path: Path):
    runtime = AgentRuntime(
        graph_registry=create_default_graph_registry(),
        workspace_resolver=lambda _workspace_id: tmp_path,
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


def _create_pending(client: TestClient, *, summary: str = "original"):
    session = client.post(
        "/api/agent/sessions",
        json={
            "workspaceId": "w1",
            "graphId": "test.approval",
            "graphVersion": 1,
            "title": "确认自检",
        },
    ).json()
    run = client.post(
        f"/api/agent/sessions/{session['id']}/runs",
        json={"input": {"summary": summary, "secret": "do-not-return"}},
    ).json()
    for _ in range(50):
        listed = client.get(
            "/api/agent/actions",
            params={"workspaceId": "w1", "status": "pending"},
        )
        if listed.status_code == 200 and listed.json():
            return session, run, listed.json()[0]
        asyncio.run(asyncio.sleep(0.01))
    raise AssertionError("pending action did not appear")


def test_list_detail_and_session_summary_are_redacted(hitl_client) -> None:
    client, _runtime = hitl_client
    session, run, action = _create_pending(client)

    listed = client.get(
        "/api/agent/actions",
        params={
            "workspaceId": "w1",
            "status": "pending",
            "sessionId": session["id"],
        },
    )
    detail = client.get(f"/api/agent/actions/{action['id']}")
    session_detail = client.get(f"/api/agent/sessions/{session['id']}")

    assert listed.status_code == 200
    assert detail.status_code == 200
    assert detail.json()["runId"] == run["id"]
    assert detail.json()["preview"] == {"summary": "original"}
    assert detail.json()["editableFields"] == ["summary"]
    assert "payload" not in detail.json()
    assert "secret" not in detail.text
    assert session_detail.json()["pendingAction"]["id"] == action["id"]


def test_edit_approve_and_duplicate_key_return_same_result(hitl_client) -> None:
    client, _runtime = hitl_client
    _session, run, action = _create_pending(client)
    body = {
        "version": action["version"],
        "idempotencyKey": "approve-1",
        "editedPayload": {"summary": "edited"},
    }

    first = client.post(f"/api/agent/actions/{action['id']}/approve", json=body)
    second = client.post(f"/api/agent/actions/{action['id']}/approve", json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["status"] == "edited_and_approved"
    assert first.json()["preview"] == {"summary": "edited"}
    for _ in range(50):
        session = client.get(f"/api/agent/sessions/{first.json()['sessionId']}").json()
        if session["latestRun"]["status"] == "completed":
            break
        asyncio.run(asyncio.sleep(0.01))
    assert session["latestRun"]["id"] == run["id"]
    assert session["latestRun"]["resumeCount"] == 1


def test_reject_requires_reason_and_resolves_action(hitl_client) -> None:
    client, _runtime = hitl_client
    _session, _run, action = _create_pending(client, summary="reject me")

    missing_reason = client.post(
        f"/api/agent/actions/{action['id']}/reject",
        json={"version": action["version"], "idempotencyKey": "reject-0"},
    )
    rejected = client.post(
        f"/api/agent/actions/{action['id']}/reject",
        json={
            "version": action["version"],
            "idempotencyKey": "reject-1",
            "reason": "不继续",
        },
    )

    assert missing_reason.status_code == 422
    assert missing_reason.json()["code"] == "invalid_action_payload"
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_version_and_second_decision_return_typed_conflicts(hitl_client) -> None:
    client, _runtime = hitl_client
    _session, _run, action = _create_pending(client)

    stale = client.post(
        f"/api/agent/actions/{action['id']}/approve",
        json={"version": action["version"] + 1, "idempotencyKey": "stale"},
    )
    approved = client.post(
        f"/api/agent/actions/{action['id']}/approve",
        json={"version": action["version"], "idempotencyKey": "approve-1"},
    )
    conflicting = client.post(
        f"/api/agent/actions/{action['id']}/reject",
        json={
            "version": action["version"],
            "idempotencyKey": "reject-1",
            "reason": "changed",
        },
    )

    assert stale.status_code == 409
    assert stale.json()["code"] == "action_version_conflict"
    assert approved.status_code == 200
    assert conflicting.status_code == 409
    assert conflicting.json()["code"] == "action_already_resolved"
