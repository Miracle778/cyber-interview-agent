from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.profile.errors import (
    ProfileClaimSelectedForPublication,
    ProfileDeletionPlanConflict,
    ProfileMaterialNotFound,
    ProfilePublicationRevocationRequired,
)
from app.profile.models import (
    CreateClaimProposalSpec,
    CreatePublicationSelectionCommand,
    DecideProposalCommand,
)
from app.profile.repository import ProfileRepository
from app.profile.service import ProfileService
from app.profile.storage import MaterialStorage


@pytest.fixture
def connection(tmp_path: Path) -> sqlite3.Connection:
    root = tmp_path / "ws"
    root.mkdir()
    initialize_knowledge_artifacts(root, domain="profile")
    return connect_runtime_database(root)


@pytest.fixture
def service(connection: sqlite3.Connection, tmp_path: Path) -> ProfileService:
    root = tmp_path / "ws"
    return ProfileService(
        workspace_id="w1",
        root=root,
        repository=ProfileRepository(connection),
        storage=MaterialStorage(root),
        product_repository=ProductRepository(connection),
    )


def _proposal(service: ProfileService, *, text: str = "Python"):
    uploaded = service.upload_material(
        file_name="resume.txt", content=b"Python and FastAPI", title="Resume"
    )
    service.record_ingest_success(uploaded.version.id)
    evidence = service.repository.replace_version_evidence(
        uploaded.version.id,
        ({
            "section": "skills",
            "start_offset": 0,
            "end_offset": 6,
            "sanitized_text": "Python",
            "content_sha256": "e" * 64,
            "sensitivity": "normal",
        },),
    )[0]
    proposal = service.repository.create_claim_proposals(
        uploaded.version.id,
        (CreateClaimProposalSpec(
            proposal_type="create",
            proposed_value={"category": "skill", "text": text},
            reason="简历明确列出",
            evidence_ids=(evidence.id,),
        ),),
    )[0]
    return uploaded, evidence, proposal


def test_claim_review_supports_traceable_edited_accept_and_idempotent_replay(
    service: ProfileService,
) -> None:
    _uploaded, evidence, proposal = _proposal(service)

    first = service.decide_claim_proposal(
        proposal.id,
        decision="accepted",
        expected_version=0,
        edited_value={"category": "skill", "text": "Python 3"},
        idempotency_key="accept-proposal-1",
    )
    replayed = service.decide_claim_proposal(
        proposal.id,
        decision="accepted",
        expected_version=0,
        edited_value={"category": "skill", "text": "Python 3"},
        idempotency_key="accept-proposal-1",
    )

    assert replayed == first
    review = service.claim_review_snapshot()
    assert len(review.claims) == 1
    detail = service.get_claim_review(first.claim_id)
    assert detail.current_version.value["text"] == "Python 3"
    assert detail.current_version.evidence_ids == (evidence.id,)
    assert detail.evidence[0].sanitized_text == "Python"
    assert len(detail.versions) == 1


def test_batch_decision_reports_completed_and_conflict_without_rolling_back(
    service: ProfileService,
) -> None:
    uploaded, evidence, first = _proposal(service)
    second = service.repository.create_claim_proposals(
        uploaded.version.id,
        (CreateClaimProposalSpec(
            proposal_type="create",
            proposed_value={"category": "skill", "text": "FastAPI"},
            reason="简历明确列出",
            evidence_ids=(evidence.id,),
        ),),
    )[0]
    service.decide_claim_proposal(
        first.id,
        decision="rejected",
        expected_version=0,
        idempotency_key="reject-first-1",
    )

    result = service.batch_decide_claim_proposals(
        (
            DecideProposalCommand(
                proposal_id=first.id,
                decision="accepted",
                expected_claim_version=0,
                idempotency_key="batch-1:first",
            ),
            DecideProposalCommand(
                proposal_id=second.id,
                decision="accepted",
                expected_claim_version=0,
                idempotency_key="batch-1:second",
            ),
        )
    )

    assert result.conflicts == (first.id,)
    assert [item.proposal_id for item in result.completed] == [second.id]
    assert service.repository.get_proposal(second.id).status == "accepted"


def test_permanent_delete_tombstones_evidence_and_retains_confirmed_claim_as_unsupported(
    service: ProfileService,
) -> None:
    uploaded, evidence, proposal = _proposal(service)
    accepted = service.decide_claim_proposal(
        proposal.id,
        decision="accepted",
        expected_version=0,
        idempotency_key="accept-before-delete",
    )
    material_version = service.get_material(uploaded.material.id).version
    preview = service.preview_material_deletion(
        uploaded.material.id,
        expected_version=material_version,
        idempotency_key="preview-delete-1",
    )

    assert preview.affected_evidence_ids == (evidence.id,)
    assert preview.affected_claim_ids == (accepted.claim_id,)
    result = service.permanently_delete_material(
        uploaded.material.id,
        deletion_plan_id=preview.id,
        expected_version=material_version,
        claim_choices={accepted.claim_id: "retain_unsupported"},
        active_publication_action="not_applicable",
        idempotency_key="permanent-delete-1",
    )
    replayed = service.permanently_delete_material(
        uploaded.material.id,
        deletion_plan_id=preview.id,
        expected_version=material_version,
        claim_choices={accepted.claim_id: "retain_unsupported"},
        active_publication_action="not_applicable",
        idempotency_key="permanent-delete-1",
    )

    assert replayed == result
    assert result.status == "completed"
    with pytest.raises(ProfileMaterialNotFound):
        service.get_material(uploaded.material.id)
    tombstone = service.repository.get_evidence(evidence.id)
    assert tombstone.tombstoned_at is not None
    assert tombstone.sanitized_text == ""
    claim_version = service.repository.get_claim_version(accepted.claim_version_id)
    assert claim_version.support_status == "unsupported"
    assert not service.storage.blob_exists(uploaded.version.storage_ref)


def test_selected_claim_cannot_be_silently_deleted_with_material(
    service: ProfileService,
) -> None:
    uploaded, _evidence, proposal = _proposal(service)
    accepted = service.decide_claim_proposal(
        proposal.id,
        decision="accepted",
        expected_version=0,
        idempotency_key="accept-selected-claim",
    )
    snapshot = service.repository.profile_snapshot("w1")
    service.repository.create_publication_selection(
        CreatePublicationSelectionCommand(
            workspace_id="w1",
            profile_version=snapshot.profile_version or "",
            claim_version_ids=(accepted.claim_version_id,),
        )
    )
    preview = service.preview_material_deletion(
        uploaded.material.id,
        expected_version=service.get_material(uploaded.material.id).version,
        idempotency_key="preview-selected-delete",
    )

    with pytest.raises(ProfileClaimSelectedForPublication):
        service.permanently_delete_material(
            uploaded.material.id,
            deletion_plan_id=preview.id,
            expected_version=preview.material_version,
            claim_choices={accepted.claim_id: "delete"},
            active_publication_action="not_applicable",
            idempotency_key="delete-selected-claim",
        )

    assert service.get_material(uploaded.material.id).id == uploaded.material.id
    assert service.repository.get_evidence(preview.affected_evidence_ids[0]).tombstoned_at is None


def test_acceptance_after_preview_invalidates_deletion_plan(
    service: ProfileService,
) -> None:
    uploaded, _evidence, proposal = _proposal(service)
    material_version = service.get_material(uploaded.material.id).version
    preview = service.preview_material_deletion(
        uploaded.material.id,
        expected_version=material_version,
        idempotency_key="preview-before-acceptance",
    )
    accepted = service.decide_claim_proposal(
        proposal.id,
        decision="accepted",
        expected_version=0,
        idempotency_key="accept-after-preview",
    )

    with pytest.raises(ProfileDeletionPlanConflict):
        service.permanently_delete_material(
            uploaded.material.id,
            deletion_plan_id=preview.id,
            expected_version=material_version,
            claim_choices={},
            active_publication_action="not_applicable",
            idempotency_key="stale-permanent-delete",
        )

    assert service.repository.get_claim(accepted.claim_id).id == accepted.claim_id
    assert service.get_material(uploaded.material.id).id == uploaded.material.id


def test_active_publication_must_be_explicitly_revoked_before_deletion(
    service: ProfileService, connection: sqlite3.Connection
) -> None:
    uploaded, _evidence, proposal = _proposal(service)
    accepted = service.decide_claim_proposal(
        proposal.id,
        decision="accepted",
        expected_version=0,
        idempotency_key="accept-published-claim",
    )
    snapshot = service.repository.profile_snapshot("w1")
    selection = service.repository.create_publication_selection(
        CreatePublicationSelectionCommand(
            workspace_id="w1",
            profile_version=snapshot.profile_version or "",
            claim_version_ids=(accepted.claim_version_id,),
        )
    )
    connection.execute(
        "INSERT INTO profile_publications "
        "(id, workspace_id, selection_id, profile_version, state) "
        "VALUES ('pub-active', 'w1', ?, ?, 'published')",
        (selection.id, snapshot.profile_version),
    )
    connection.commit()
    material_version = service.get_material(uploaded.material.id).version
    preview = service.preview_material_deletion(
        uploaded.material.id,
        expected_version=material_version,
        idempotency_key="preview-active-publication",
    )
    assert preview.active_publication_ids == ("pub-active",)

    with pytest.raises(ProfilePublicationRevocationRequired):
        service.permanently_delete_material(
            uploaded.material.id,
            deletion_plan_id=preview.id,
            expected_version=material_version,
            claim_choices={accepted.claim_id: "retain_unsupported"},
            active_publication_action="not_applicable",
            idempotency_key="delete-without-revoke",
        )

    assert service.get_material(uploaded.material.id).id == uploaded.material.id


def test_permanent_delete_retries_only_unfinished_artifact_cleanup(
    service: ProfileService, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploaded, _evidence, proposal = _proposal(service)
    accepted = service.decide_claim_proposal(
        proposal.id,
        decision="accepted",
        expected_version=0,
        idempotency_key="accept-before-cleanup-retry",
    )
    material_version = service.get_material(uploaded.material.id).version
    preview = service.preview_material_deletion(
        uploaded.material.id,
        expected_version=material_version,
        idempotency_key="preview-cleanup-retry",
    )
    original_delete_ref = service.storage.delete_ref
    attempts = 0

    def fail_once(ref: str, *, remaining_references: int) -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("simulated cleanup interruption")
        return original_delete_ref(ref, remaining_references=remaining_references)

    monkeypatch.setattr(service.storage, "delete_ref", fail_once)
    with pytest.raises(OSError):
        service.permanently_delete_material(
            uploaded.material.id,
            deletion_plan_id=preview.id,
            expected_version=material_version,
            claim_choices={accepted.claim_id: "retain_unsupported"},
            active_publication_action="not_applicable",
            idempotency_key="cleanup-retry",
        )

    result = service.permanently_delete_material(
        uploaded.material.id,
        deletion_plan_id=preview.id,
        expected_version=material_version,
        claim_choices={accepted.claim_id: "retain_unsupported"},
        active_publication_action="not_applicable",
        idempotency_key="cleanup-retry",
    )

    assert result.status == "completed"
    assert service.repository.get_material_deletion_plan(preview.id).status == "completed"
    assert len(service.repository.list_claim_versions(accepted.claim_id)) == 1
