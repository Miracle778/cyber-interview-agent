import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_agent_application
from app.application.graph_factory import ProductionGraphFactory
from app.application.workspace_runtime import AgentApplication
from app.main import app


@pytest.fixture
def hitl_client(tmp_path: Path):
    application = AgentApplication(
        workspace_resolver=lambda _workspace_id: tmp_path,
        model_bindings=lambda _workspace_id: {},
        workspace_ids=lambda: ("w1",),
        graph_factory=ProductionGraphFactory(None),
        registration_guard=lambda _kind, **_options: None,
    )
    app.dependency_overrides[get_agent_application] = lambda: application
    try:
        with TestClient(app) as client:
            yield client, application
    finally:
        app.dependency_overrides.clear()
        asyncio.run(application.close())


def _create_pending(client: TestClient, *, summary: str = "original"):
    session = client.post(
        "/api/agent/sessions",
        json={
            "workspaceId": "w1",
            "kind": "diagnostic.approval",
            "title": "确认自检",
        },
    ).json()
    run = client.post(
        f"/api/agent/sessions/{session['id']}/executions",
        json={"input": {"summary": summary, "secret": "do-not-return"}},
    ).json()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        listed = client.get(
            "/api/agent/actions",
            params={"workspaceId": "w1", "status": "pending"},
        )
        if listed.status_code == 200 and listed.json():
            return session, run, listed.json()[0]
        time.sleep(0.02)
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
    assert detail.json()["executionId"] == run["id"]
    assert detail.json()["preview"] == {"summary": "original"}
    assert detail.json()["editableFields"] == ["summary"]
    assert "payload" not in detail.json()
    assert "secret" not in detail.text
    assert session_detail.json()["currentAction"]["id"] == action["id"]


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
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        session = client.get(f"/api/agent/sessions/{first.json()['sessionId']}").json()
        if session["latestExecution"]["status"] == "completed":
            break
        time.sleep(0.02)
    assert session["latestExecution"]["id"] == run["id"]
    assert session["latestExecution"]["resumeCount"] == 1


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


def test_reused_resolution_key_with_changed_content_is_typed_conflict(
    hitl_client,
) -> None:
    client, _runtime = hitl_client
    _session, _run, action = _create_pending(client)
    endpoint = f"/api/agent/actions/{action['id']}/approve"

    first = client.post(
        endpoint,
        json={
            "version": action["version"],
            "idempotencyKey": "approve-1",
            "editedPayload": {"summary": "first"},
        },
    )
    changed = client.post(
        endpoint,
        json={
            "version": action["version"],
            "idempotencyKey": "approve-1",
            "editedPayload": {"summary": "second"},
        },
    )

    assert first.status_code == 200
    assert changed.status_code == 409
    assert changed.json()["code"] == "action_idempotency_conflict"
