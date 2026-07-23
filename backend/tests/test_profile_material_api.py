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
from app.profile.models import CreateClaimProposalSpec


def _graph_factory(_kind: str, **dependencies):
    graph = StateGraph(dict)
    graph.add_node("complete", lambda state: state)
    graph.add_edge(START, "complete")
    graph.add_edge("complete", END)
    return graph.compile(checkpointer=dependencies.get("checkpointer"))


@pytest_asyncio.fixture
async def application(tmp_path: Path):
    roots = {"w1": tmp_path / "w1", "w2": tmp_path / "w2"}
    for root in roots.values():
        root.mkdir()
    value = AgentApplication(
        workspace_resolver=lambda workspace_id: roots[workspace_id],
        workspace_ids=lambda: ("w1", "w2"),
        model_bindings=lambda _workspace_id: {},
        graph_factory=_graph_factory,
    )
    app.dependency_overrides[get_agent_application] = lambda: value
    try:
        yield value
    finally:
        app.dependency_overrides.pop(get_agent_application, None)
        await value.close()


@pytest.fixture
def client(application):
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )


async def _upload(client: AsyncClient, *, key: str = "upload-resume-1"):
    return await client.post(
        "/api/workspaces/w1/profile/materials",
        data={"title": "后端工程师简历", "primaryRole": "resume"},
        files={"file": ("resume.md", b"# Experience\n\nLed a team", "text/markdown")},
        headers={"Idempotency-Key": key},
    )


@pytest.mark.asyncio
async def test_workspace_runtime_uses_a_separate_sqlite_connection_per_worker_thread(
    application: AgentApplication,
) -> None:
    connection = application.profile("w1").connection
    connection.execute("CREATE TEMP TABLE request_thread_marker(value TEXT)")
    connection.execute(
        "INSERT INTO request_thread_marker(value) VALUES ('main-thread-only')"
    )
    connection.commit()

    marker_visible_in_worker = await asyncio.to_thread(
        lambda: connection.execute(
            "SELECT name FROM sqlite_temp_master "
            "WHERE type = 'table' AND name = 'request_thread_marker'"
        ).fetchone()
        is not None
    )

    assert marker_visible_in_worker is False


@pytest.mark.asyncio
async def test_upload_list_and_paginated_version_detail_are_safe_and_idempotent(
    client: AsyncClient, application: AgentApplication
) -> None:
    async with client:
        uploaded = await _upload(client)
        replayed = await _upload(client)

        assert uploaded.status_code == 202, uploaded.text
        assert replayed.json() == uploaded.json()
        accepted = uploaded.json()
        assert set(accepted) == {
            "materialId", "versionId", "executionId", "processingStatus"
        }
        execution = application.profile("w1").latest_execution(accepted["versionId"])
        assert execution.input["material_id"] == accepted["materialId"]
        assert execution.input["version_id"] == accepted["versionId"]
        assert "materialId" not in execution.input
        assert "versionId" not in execution.input
        assert application.list_sessions("w1") == ()

        profile = application.profile("w1")
        profile.repository.replace_version_evidence(
            accepted["versionId"],
            tuple(
                {
                    "section": f'{{"lineEnd":{index},"lineStart":{index}}}',
                    "start_offset": index * 10,
                    "end_offset": index * 10 + 8,
                    "sanitized_text": f"Evidence {index}",
                    "content_sha256": str(index) * 64,
                    "sensitivity": "normal",
                }
                for index in range(1, 4)
            ),
        )
        evidence = profile.repository.list_evidence_for_version(accepted["versionId"])
        profile.repository.create_claim_proposals(
            accepted["versionId"],
            (
                CreateClaimProposalSpec(
                    proposal_type="create",
                    proposed_value={"category": "experience", "text": "Led a team"},
                    reason="grounded",
                    evidence_ids=(evidence[0].id,),
                ),
            ),
        )

        listed = await client.get("/api/workspaces/w1/profile/materials")
        versions = await client.get(
            f"/api/profile/materials/{accepted['materialId']}/versions",
            params={"workspaceId": "w1"},
        )
        detail = await client.get(
            f"/api/profile/material-versions/{accepted['versionId']}",
            params={"workspaceId": "w1", "evidenceOffset": 1, "evidenceLimit": 1},
        )

    assert listed.status_code == 200
    assert listed.json()[0]["title"] == "后端工程师简历"
    assert versions.status_code == 200
    assert versions.json()[0]["fileName"] == "resume.md"
    body = detail.json()
    assert body["evidencePage"]["total"] == 3
    assert body["evidencePage"]["hasMore"] is True
    assert body["evidencePage"]["items"][0]["locator"] == {
        "lineEnd": 2,
        "lineStart": 2,
    }
    assert body["proposalCounts"]["total"] == 1
    assert body["execution"]["id"] == accepted["executionId"]
    private_keys = {"storageRef", "textRef", "sessionId", "normalizedText"}
    assert not any(key in str(body) for key in private_keys)


@pytest.mark.asyncio
async def test_version_primary_archive_and_restore_use_optimistic_idempotent_writes(
    client: AsyncClient,
) -> None:
    async with client:
        first = (await _upload(client)).json()
        added = await client.post(
            f"/api/profile/materials/{first['materialId']}/versions",
            data={"workspaceId": "w1"},
            files={"file": ("resume-v2.txt", b"version two", "text/plain")},
            headers={"Idempotency-Key": "add-resume-version-2"},
        )
        assert added.status_code == 202, added.text

        primary = await client.post(
            f"/api/profile/materials/{first['materialId']}/primary",
            json={
                "workspaceId": "w1",
                "versionId": added.json()["versionId"],
                "expectedVersion": 1,
            },
            headers={"Idempotency-Key": "set-primary-version-2"},
        )
        replayed = await client.post(
            f"/api/profile/materials/{first['materialId']}/primary",
            json={
                "workspaceId": "w1",
                "versionId": added.json()["versionId"],
                "expectedVersion": 1,
            },
            headers={"Idempotency-Key": "set-primary-version-2"},
        )
        assert primary.status_code == 200
        assert replayed.json() == primary.json()
        assert primary.json()["currentVersionId"] == added.json()["versionId"]

        stale = await client.post(
            f"/api/profile/materials/{first['materialId']}/primary",
            json={
                "workspaceId": "w1",
                "versionId": first["versionId"],
                "expectedVersion": 1,
            },
            headers={"Idempotency-Key": "stale-primary-version-1"},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "profile_material_version_conflict"

        archived = await client.post(
            f"/api/profile/materials/{first['materialId']}/archive",
            json={"workspaceId": "w1", "expectedVersion": 2},
            headers={"Idempotency-Key": "archive-resume-1"},
        )
        active = await client.get("/api/workspaces/w1/profile/materials")
        all_materials = await client.get(
            "/api/workspaces/w1/profile/materials",
            params={"includeArchived": True},
        )
        assert archived.json()["lifecycleStatus"] == "archived"
        assert active.json() == []
        assert all_materials.json()[0]["lifecycleStatus"] == "archived"

        restored = await client.post(
            f"/api/profile/materials/{first['materialId']}/restore",
            json={"workspaceId": "w1", "expectedVersion": 3},
            headers={"Idempotency-Key": "restore-resume-1"},
        )
    assert restored.status_code == 200
    assert restored.json()["lifecycleStatus"] == "active"


@pytest.mark.asyncio
async def test_retry_returns_a_safe_execution_and_replays_the_same_receipt(
    client: AsyncClient, application: AgentApplication
) -> None:
    async with client:
        accepted = (await _upload(client)).json()
        await application._context("w1").executions.wait(accepted["executionId"])
        application.profile("w1").record_ingest_failure(
            accepted["versionId"],
            processing_status="parse_failed",
            error_code="profile_parse_failed",
        )
        first = await client.post(
            f"/api/profile/material-versions/{accepted['versionId']}/retry",
            json={"workspaceId": "w1"},
            headers={"Idempotency-Key": "retry-resume-version-1"},
        )
        replayed = await client.post(
            f"/api/profile/material-versions/{accepted['versionId']}/retry",
            json={"workspaceId": "w1"},
            headers={"Idempotency-Key": "retry-resume-version-1"},
        )
    assert first.status_code == 202, first.text
    assert replayed.json() == first.json()
    assert first.json()["versionId"] == accepted["versionId"]
    assert "sessionId" not in first.json()


@pytest.mark.asyncio
async def test_stale_failed_ingest_is_projected_as_retryable_instead_of_waiting(
    client: AsyncClient, application: AgentApplication
) -> None:
    async with client:
        accepted = (await _upload(client, key="upload-stale-failure")).json()
        await application._context("w1").executions.wait(accepted["executionId"])
        profile = application.profile("w1")
        profile.connection.execute(
            "UPDATE agent_runs SET status = 'failed', "
            "error_code = 'agent_execution_failed' WHERE id = ?",
            (accepted["executionId"],),
        )
        profile.connection.execute(
            "UPDATE profile_material_versions SET processing_status = 'uploaded' "
            "WHERE id = ?",
            (accepted["versionId"],),
        )
        profile.connection.commit()

        detail = await client.get(
            f"/api/profile/material-versions/{accepted['versionId']}",
            params={"workspaceId": "w1"},
        )

    assert detail.status_code == 200
    assert detail.json()["processingStatus"] == "parse_failed"
    assert detail.json()["canRetry"] is True


@pytest.mark.asyncio
async def test_profile_ids_are_rechecked_against_the_requested_workspace(
    client: AsyncClient,
) -> None:
    async with client:
        accepted = (await _upload(client)).json()
        material = await client.get(
            f"/api/profile/materials/{accepted['materialId']}/versions",
            params={"workspaceId": "w2"},
        )
        version = await client.get(
            f"/api/profile/material-versions/{accepted['versionId']}",
            params={"workspaceId": "w2"},
        )
    assert material.status_code == 404
    assert version.status_code == 404
    assert material.json() == {
        "code": "profile_material_not_found",
        "message": "个人材料不存在或无权访问",
        "retryable": False,
    }


@pytest.mark.asyncio
async def test_upload_validation_uses_stable_redacted_error_envelopes(
    client: AsyncClient,
) -> None:
    async with client:
        unsupported = await client.post(
            "/api/workspaces/w1/profile/materials",
            data={"title": "Resume", "primaryRole": "resume"},
            files={"file": ("resume.exe", b"private", "application/octet-stream")},
            headers={"Idempotency-Key": "unsupported-resume"},
        )
        missing_file = await client.post(
            "/api/workspaces/w1/profile/materials",
            data={"title": "Resume", "primaryRole": "resume"},
            headers={"Idempotency-Key": "missing-file-resume"},
        )
        too_large = await client.post(
            "/api/workspaces/w1/profile/materials",
            data={"title": "Resume", "primaryRole": "resume"},
            files={"file": ("resume.txt", b"x" * (10 * 1024 * 1024 + 1), "text/plain")},
            headers={"Idempotency-Key": "large-resume-file"},
        )
    assert unsupported.status_code == 422
    assert unsupported.json()["code"] == "profile_unsupported_file_type"
    assert missing_file.status_code == 422
    assert missing_file.json()["code"] == "invalid_request"
    assert too_large.status_code == 413
    assert too_large.json()["code"] == "profile_upload_too_large"
    assert "private" not in str(unsupported.json())
