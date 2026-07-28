from __future__ import annotations

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
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _prepare_proposals(client: AsyncClient, application: AgentApplication):
    uploaded = await client.post(
        "/api/workspaces/w1/profile/materials",
        data={"title": "后端工程师简历", "primaryRole": "resume"},
        files={"file": ("resume.md", b"Python and FastAPI", "text/markdown")},
        headers={"Idempotency-Key": "claim-api-upload-1"},
    )
    accepted = uploaded.json()
    service = application.profile("w1")
    evidence = service.repository.replace_version_evidence(
        accepted["versionId"],
        ({
            "section": "skills",
            "start_offset": 0,
            "end_offset": 6,
            "sanitized_text": "Python",
            "content_sha256": "d" * 64,
            "sensitivity": "normal",
        },),
    )[0]
    proposals = service.repository.create_claim_proposals(
        accepted["versionId"],
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="明确列出",
                evidence_ids=(evidence.id,),
            ),
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "FastAPI"},
                reason="明确列出",
                evidence_ids=(evidence.id,),
            ),
        ),
    )
    material = service.get_material(accepted["materialId"])
    return accepted, material, evidence, proposals


@pytest.mark.asyncio
async def test_claim_resources_accept_edit_and_preserve_evidence_trace(
    client: AsyncClient, application: AgentApplication
) -> None:
    async with client:
        _uploaded, _material, evidence, proposals = await _prepare_proposals(client, application)
        listed = await client.get("/api/workspaces/w1/profile/claims")
        assert listed.status_code == 200, listed.text
        assert {item["id"] for item in listed.json()["proposals"]} == {
            proposals[0].id,
            proposals[1].id,
        }

        accepted = await client.post(
            f"/api/profile/claim-proposals/{proposals[0].id}/accept",
            json={
                "workspaceId": "w1",
                "expectedVersion": 0,
                "editedValue": {"category": "skill", "text": "Python 3"},
            },
            headers={"Idempotency-Key": "claim-api-accept-1"},
        )
        replayed = await client.post(
            f"/api/profile/claim-proposals/{proposals[0].id}/accept",
            json={
                "workspaceId": "w1",
                "expectedVersion": 0,
                "editedValue": {"category": "skill", "text": "Python 3"},
            },
            headers={"Idempotency-Key": "claim-api-accept-1"},
        )
        assert accepted.status_code == 200, accepted.text
        assert replayed.json() == accepted.json()

        claim_id = accepted.json()["claimId"]
        detail = await client.get(
            f"/api/profile/claims/{claim_id}", params={"workspaceId": "w1"}
        )
        history = await client.get(
            f"/api/profile/claims/{claim_id}/versions", params={"workspaceId": "w1"}
        )
        assert detail.json()["currentVersion"]["value"]["text"] == "Python 3"
        assert detail.json()["evidence"][0]["id"] == evidence.id
        assert len(history.json()) == 1


@pytest.mark.asyncio
async def test_batch_decision_returns_item_level_partial_receipts(
    client: AsyncClient, application: AgentApplication
) -> None:
    async with client:
        _uploaded, _material, _evidence, proposals = await _prepare_proposals(client, application)
        rejected = await client.post(
            f"/api/profile/claim-proposals/{proposals[0].id}/reject",
            json={"workspaceId": "w1", "expectedVersion": 0},
            headers={"Idempotency-Key": "claim-api-reject-1"},
        )
        assert rejected.status_code == 200

        response = await client.post(
            "/api/profile/claim-proposals/batch-decide",
            json={
                "workspaceId": "w1",
                "decisions": [
                    {"proposalId": proposals[0].id, "decision": "accepted", "expectedVersion": 0},
                    {"proposalId": proposals[1].id, "decision": "accepted", "expectedVersion": 0},
                ],
            },
            headers={"Idempotency-Key": "claim-api-batch-1"},
        )

        assert response.status_code == 200, response.text
        by_id = {item["proposalId"]: item for item in response.json()["items"]}
        assert by_id[proposals[0].id]["status"] == "conflict"
        assert by_id[proposals[1].id]["status"] == "completed"


@pytest.mark.asyncio
async def test_duplicate_proposals_require_preview_before_explicit_consolidation(
    client: AsyncClient, application: AgentApplication
) -> None:
    async with client:
        uploaded, _material, evidence, proposals = await _prepare_proposals(
            client, application
        )
        duplicate = application.profile("w1").repository.create_claim_proposals(
            uploaded["versionId"],
            (
                CreateClaimProposalSpec(
                    proposal_type="create",
                    proposed_value={
                        "category": "skill",
                        "name": "Python",
                        "confidence": -0.1,
                    },
                    reason="再次列出",
                    evidence_ids=(evidence.id,),
                ),
            ),
        )[0]

        preview = await client.get(
            "/api/workspaces/w1/profile/claim-proposals/duplicate-preview"
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["groupCount"] == 1
        assert set(body["groups"][0]["proposalIds"]) == {
            proposals[0].id,
            duplicate.id,
        }

        consolidated = await client.post(
            "/api/workspaces/w1/profile/claim-proposals/consolidate-duplicates",
            json={
                "workspaceId": "w1",
                "groups": [
                    {"proposalIds": body["groups"][0]["proposalIds"]}
                ],
            },
            headers={"Idempotency-Key": "claim-api-consolidate-1"},
        )
        assert consolidated.status_code == 200, consolidated.text
        assert consolidated.json()["supersededProposalIds"] == [duplicate.id]


@pytest.mark.asyncio
async def test_material_version_deletion_preview_and_current_replacement(
    client: AsyncClient, application: AgentApplication
) -> None:
    async with client:
        first = await client.post(
            "/api/workspaces/w1/profile/materials",
            data={"title": "后端工程师简历", "primaryRole": "resume"},
            files={"file": ("resume-v1.md", b"Python", "text/markdown")},
            headers={"Idempotency-Key": "version-delete-upload-v1"},
        )
        assert first.status_code == 202, first.text
        first_body = first.json()
        second = await client.post(
            f"/api/profile/materials/{first_body['materialId']}/versions",
            data={"workspaceId": "w1"},
            files={"file": ("resume-v2.md", b"Python and FastAPI", "text/markdown")},
            headers={"Idempotency-Key": "version-delete-upload-v2"},
        )
        assert second.status_code == 202, second.text
        second_body = second.json()
        service = application.profile("w1")
        evidence = service.repository.replace_version_evidence(
            second_body["versionId"],
            ({
                "section": "projects",
                "start_offset": 0,
                "end_offset": 18,
                "sanitized_text": "Python and FastAPI",
                "content_sha256": "f" * 64,
                "sensitivity": "normal",
            },),
        )[0]
        proposal = service.repository.create_claim_proposals(
            second_body["versionId"],
            (CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={
                    "category": "project",
                    "name": "面试准备 Agent",
                    "description": "基于可恢复工作流整理面试资料",
                },
                reason="第二版项目经历",
                evidence_ids=(evidence.id,),
            ),),
        )[0]
        accepted = service.decide_claim_proposal(
            proposal.id,
            decision="accepted",
            expected_version=0,
            idempotency_key="version-delete-accept-api",
        )
        material = service.set_primary_version(
            first_body["materialId"],
            second_body["versionId"],
            expected_version=service.get_material(first_body["materialId"]).version,
            idempotency_key="version-delete-set-primary",
        )

        preview = await client.post(
            f"/api/profile/material-versions/{second_body['versionId']}/deletion-preview",
            json={"workspaceId": "w1", "expectedVersion": material.version},
            headers={"Idempotency-Key": "version-delete-preview-api"},
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["versionId"] == second_body["versionId"]
        assert body["isCurrentVersion"] is True
        assert body["replacementVersions"][0]["id"] == first_body["versionId"]
        assert body["affectedClaims"][0]["value"]["name"] == "面试准备 Agent"

        deleted = await client.post(
            f"/api/profile/material-versions/{second_body['versionId']}/permanent-delete",
            json={
                "workspaceId": "w1",
                "expectedVersion": material.version,
                "deletionPlanId": body["deletionPlanId"],
                "replacementVersionId": first_body["versionId"],
                "claimChoices": [
                    {"claimId": accepted.claim_id, "action": "retain_unsupported"}
                ],
                "activePublicationAction": "not_applicable",
            },
            headers={"Idempotency-Key": "version-delete-execute-api"},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "completed"
        versions = await client.get(
            f"/api/profile/materials/{first_body['materialId']}/versions",
            params={"workspaceId": "w1"},
        )
        assert [item["id"] for item in versions.json()] == [first_body["versionId"]]


@pytest.mark.asyncio
async def test_material_version_deletion_rejects_pending_proposals_from_another_version(
    client: AsyncClient, application: AgentApplication
) -> None:
    async with client:
        first = await client.post(
            "/api/workspaces/w1/profile/materials",
            data={"title": "后端工程师简历", "primaryRole": "resume"},
            files={"file": ("resume-v1.md", b"Python", "text/markdown")},
            headers={"Idempotency-Key": "version-delete-pending-v1"},
        )
        assert first.status_code == 202, first.text
        first_body = first.json()
        second = await client.post(
            f"/api/profile/materials/{first_body['materialId']}/versions",
            data={"workspaceId": "w1"},
            files={"file": ("resume-v2.md", b"FastAPI", "text/markdown")},
            headers={"Idempotency-Key": "version-delete-pending-v2"},
        )
        assert second.status_code == 202, second.text
        second_body = second.json()
        service = application.profile("w1")
        evidence = service.repository.replace_version_evidence(
            second_body["versionId"],
            ({
                "section": "skills",
                "start_offset": 0,
                "end_offset": 7,
                "sanitized_text": "FastAPI",
                "content_sha256": "e" * 64,
                "sensitivity": "normal",
            },),
        )[0]
        service.repository.create_claim_proposals(
            second_body["versionId"],
            (CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "FastAPI"},
                reason="第二版明确列出",
                evidence_ids=(evidence.id,),
            ),),
        )
        material = service.get_material(first_body["materialId"])

        blocked = await client.post(
            f"/api/profile/material-versions/{first_body['versionId']}/deletion-preview",
            json={"workspaceId": "w1", "expectedVersion": material.version},
            headers={"Idempotency-Key": "version-delete-pending-preview"},
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["code"] == (
            "profile_material_version_has_pending_proposals"
        )


@pytest.mark.asyncio
async def test_deletion_preview_requires_exact_claim_choice_and_returns_receipts(
    client: AsyncClient, application: AgentApplication
) -> None:
    async with client:
        uploaded, material, evidence, proposals = await _prepare_proposals(client, application)
        accepted = await client.post(
            f"/api/profile/claim-proposals/{proposals[0].id}/accept",
            json={"workspaceId": "w1", "expectedVersion": 0},
            headers={"Idempotency-Key": "claim-before-delete-1"},
        )
        claim_id = accepted.json()["claimId"]
        preview = await client.post(
            f"/api/profile/materials/{uploaded['materialId']}/deletion-preview",
            json={"workspaceId": "w1", "expectedVersion": material.version},
            headers={"Idempotency-Key": "claim-delete-preview-1"},
        )
        assert preview.status_code == 200, preview.text
        impact = preview.json()
        assert impact["affectedEvidenceCount"] == 1
        assert impact["affectedClaims"][0]["claimId"] == claim_id

        deleted = await client.post(
            f"/api/profile/materials/{uploaded['materialId']}/permanent-delete",
            json={
                "workspaceId": "w1",
                "deletionPlanId": impact["deletionPlanId"],
                "expectedVersion": material.version,
                "claimChoices": [{"claimId": claim_id, "action": "retain_unsupported"}],
                "activePublicationAction": "not_applicable",
            },
            headers={"Idempotency-Key": "claim-permanent-delete-1"},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "completed"
        assert {item["kind"] for item in deleted.json()["items"]} >= {
            "claim",
            "evidence",
            "material",
        }
        tombstone = application.profile("w1").repository.get_evidence(evidence.id)
        assert tombstone.sanitized_text == ""


@pytest.mark.asyncio
async def test_claim_and_deletion_routes_enforce_workspace_ownership(
    client: AsyncClient, application: AgentApplication
) -> None:
    async with client:
        uploaded, material, _evidence, proposals = await _prepare_proposals(client, application)
        foreign_claim = await client.post(
            f"/api/profile/claim-proposals/{proposals[0].id}/accept",
            json={"workspaceId": "w2", "expectedVersion": 0},
            headers={"Idempotency-Key": "foreign-claim-accept"},
        )
        foreign_delete = await client.post(
            f"/api/profile/materials/{uploaded['materialId']}/deletion-preview",
            json={"workspaceId": "w2", "expectedVersion": material.version},
            headers={"Idempotency-Key": "foreign-delete-preview"},
        )

        assert foreign_claim.status_code == 404
        assert foreign_delete.status_code == 404
