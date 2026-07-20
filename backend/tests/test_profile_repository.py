from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.infrastructure.runtime_database import connect_runtime_database
from app.profile.errors import (
    ProfileActionPlanNotFound,
    ProfileClaimVersionConflict,
    ProfileEvidenceMismatch,
    ProfileMaterialNotFound,
    ProfileProposalAlreadyDecided,
    ProfileSnapshotChanged,
)
from app.profile.models import (
    ActionPlanItemSpec,
    CreateActionPlanCommand,
    CreateClaimProposalSpec,
    CreateMaterialCommand,
    CreatePublicationSelectionCommand,
    DecideProposalCommand,
    SaveAssessmentCommand,
)
from app.profile.repository import ProfileRepository


@pytest.fixture
def connection(tmp_path: Path) -> sqlite3.Connection:
    return connect_runtime_database(tmp_path)


@pytest.fixture
def repository(connection: sqlite3.Connection) -> ProfileRepository:
    return ProfileRepository(connection)


def _material(repository: ProfileRepository, workspace_id: str = "w1", role: str = "resume"):
    return repository.create_material(
        CreateMaterialCommand(
            workspace_id=workspace_id,
            type="resume",
            title="My Resume",
            primary_role=role,
        )
    )


def _version(repository: ProfileRepository, material_id: str, sha: str = "a" * 64):
    return repository.add_material_version(
        material_id=material_id,
        source_type="upload",
        file_name="resume.pdf",
        mime_type="application/pdf",
        content_sha256=sha,
        storage_ref="blobs/aa/aaa.pdf",
        text_ref="text/v1.txt",
    )


def _parsed_version(repository: ProfileRepository, version_id: str):
    return repository.mark_version_parsed(
        version_id, text_path="text/v1.txt", content_sha256="b" * 64
    )


def _evidence(repository: ProfileRepository, version_id: str, section: str = "experience"):
    return repository.replace_version_evidence(
        version_id,
        (
            {
                "section": section,
                "start_offset": 0,
                "end_offset": 10,
                "sanitized_text": "Led team of 5",
                "content_sha256": "c" * 64,
                "sensitivity": "normal",
            },
        ),
    )[0]


def test_create_material_and_add_version_is_monotonic(repository: ProfileRepository) -> None:
    material = _material(repository)
    first = _version(repository, material.id)
    second = repository.add_material_version(
        material_id=material.id,
        source_type="upload",
        file_name="resume-v2.pdf",
        mime_type="application/pdf",
        content_sha256="d" * 64,
        storage_ref="blobs/dd/ddd.pdf",
        text_ref="text/v2.txt",
    )

    assert first.version_number == 1
    assert second.version_number == 2
    versions = repository.list_material_versions(material.id)
    assert [v.version_number for v in versions] == [2, 1]


def test_only_one_active_material_per_primary_role(repository: ProfileRepository) -> None:
    _material(repository, role="resume")
    with pytest.raises(Exception):
        _material(repository, role="resume")

    # A different role coexists.
    other = _material(repository, role="github")
    assert other.primary_role == "github"


def test_archive_and_restore_material(repository: ProfileRepository) -> None:
    material = _material(repository, role="resume")
    repository.archive_material(material.id)
    active = repository.list_materials(material.workspace_id)
    assert material.id not in {m.id for m in active}

    repository.restore_material(material.id)
    active = repository.list_materials(material.workspace_id)
    assert material.id in {m.id for m in active}


def test_replace_version_evidence_is_immutable_and_tombstones_previous(
    repository: ProfileRepository,
) -> None:
    material = _material(repository)
    version = _version(repository, material.id)
    first = repository.replace_version_evidence(
        version.id,
        (
            {
                "section": "experience",
                "start_offset": 0,
                "end_offset": 5,
                "sanitized_text": "old",
                "content_sha256": "c" * 64,
                "sensitivity": "normal",
            },
        ),
    )[0]
    second = repository.replace_version_evidence(
        version.id,
        (
            {
                "section": "experience",
                "start_offset": 0,
                "end_offset": 9,
                "sanitized_text": "new text",
                "content_sha256": "e" * 64,
                "sensitivity": "normal",
            },
        ),
    )[0]

    reloaded_first = repository.get_evidence(first.id)
    assert reloaded_first.tombstoned_at is not None
    assert reloaded_first.sanitized_text == ""  # sensitive body removed on tombstone
    assert second.tombstoned_at is None
    current = repository.list_evidence_for_version(version.id)
    assert [e.id for e in current] == [second.id]


def test_create_claim_proposals_validates_evidence_belongs_to_version(
    repository: ProfileRepository,
) -> None:
    material = _material(repository)
    version = _version(repository, material.id)
    _parsed_version(repository, version.id)
    evidence = _evidence(repository, version.id)

    proposals = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="mentioned",
                evidence_ids=(evidence.id,),
            ),
        ),
    )
    assert len(proposals) == 1
    assert proposals[0].status == "pending"


def test_create_claim_proposals_rejects_foreign_evidence(
    repository: ProfileRepository,
) -> None:
    material = _material(repository)
    version = _version(repository, material.id)
    _parsed_version(repository, version.id)
    evidence = _evidence(repository, version.id)

    other_material = _material(repository, role="github")
    other_version = _version(repository, other_material.id, sha="f" * 64)

    with pytest.raises(ProfileEvidenceMismatch):
        repository.create_claim_proposals(
            other_version.id,
            (
                CreateClaimProposalSpec(
                    proposal_type="create",
                    proposed_value={"category": "skill", "text": "Python"},
                    reason="x",
                    evidence_ids=(evidence.id,),
                ),
            ),
        )


def test_accept_proposal_creates_confirmed_claim_atomically(
    repository: ProfileRepository,
) -> None:
    material = _material(repository)
    version = _version(repository, material.id)
    _parsed_version(repository, version.id)
    evidence = _evidence(repository, version.id)
    proposal = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="mentioned",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]

    result = repository.decide_proposal(
        proposal.id,
        DecideProposalCommand(
            proposal_id=proposal.id,
            decision="accepted",
            expected_status="pending",
        ),
    )

    assert result.status == "accepted"
    assert result.claim_id is not None
    claim = repository.get_claim(result.claim_id)
    assert claim.current_confirmed_version_id == result.claim_version_id
    version_record = repository.get_claim_version(result.claim_version_id)
    assert version_record.status == "confirmed"
    assert version_record.support_status == "supported"


def test_decide_proposal_is_idempotent(repository: ProfileRepository) -> None:
    material = _material(repository)
    version = _version(repository, material.id)
    _parsed_version(repository, version.id)
    evidence = _evidence(repository, version.id)
    proposal = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="mentioned",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]

    repository.decide_proposal(
        proposal.id,
        DecideProposalCommand(proposal_id=proposal.id, decision="accepted", expected_status="pending"),
    )
    with pytest.raises(ProfileProposalAlreadyDecided):
        repository.decide_proposal(
            proposal.id,
            DecideProposalCommand(proposal_id=proposal.id, decision="rejected", expected_status="pending"),
        )


def test_optimistic_claim_version_conflict(repository: ProfileRepository) -> None:
    material = _material(repository)
    version = _version(repository, material.id)
    _parsed_version(repository, version.id)
    evidence = _evidence(repository, version.id)
    proposal = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="mentioned",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]

    with pytest.raises(ProfileClaimVersionConflict):
        repository.decide_proposal(
            proposal.id,
            DecideProposalCommand(
                proposal_id=proposal.id,
                decision="accepted",
                expected_status="accepted",  # stale: still pending
            ),
        )


def test_conflicting_proposal_records_conflict_without_overwriting(
    repository: ProfileRepository,
) -> None:
    material = _material(repository)
    version = _version(repository, material.id)
    _parsed_version(repository, version.id)
    evidence = _evidence(repository, version.id)
    proposal_a = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="first",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]
    accepted = repository.decide_proposal(
        proposal_a.id,
        DecideProposalCommand(proposal_id=proposal_a.id, decision="accepted", expected_status="pending"),
    )

    # A new conflicting proposal against the same claim.
    proposal_b = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="update",
                target_claim_id=accepted.claim_id,
                base_claim_version_id=accepted.claim_version_id,
                proposed_value={"category": "skill", "text": "Go"},
                reason="conflict",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]

    conflicts = repository.list_conflicts_for_claim(accepted.claim_id)
    assert any(c.proposal_id == proposal_b.id for c in conflicts)
    # Confirmed version untouched.
    claim = repository.get_claim(accepted.claim_id)
    assert claim.current_confirmed_version_id == accepted.claim_version_id


def test_confirmed_claim_can_be_unsupported(repository: ProfileRepository) -> None:
    material = _material(repository)
    version = _version(repository, material.id)
    _parsed_version(repository, version.id)
    evidence = _evidence(repository, version.id)
    proposal = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="mentioned",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]
    accepted = repository.decide_proposal(
        proposal.id,
        DecideProposalCommand(proposal_id=proposal.id, decision="accepted", expected_status="pending"),
    )

    repository.mark_claim_unsupported(accepted.claim_id, reason="evidence tombstoned")

    claim = repository.get_claim(accepted.claim_id)
    assert claim.current_confirmed_version_id == accepted.claim_version_id
    version_record = repository.get_claim_version(accepted.claim_version_id)
    assert version_record.status == "confirmed"
    assert version_record.support_status == "unsupported"


def test_edited_acceptance_creates_new_claim_version(repository: ProfileRepository) -> None:
    material = _material(repository)
    version = _version(repository, material.id)
    _parsed_version(repository, version.id)
    evidence = _evidence(repository, version.id)
    proposal = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="mentioned",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]

    result = repository.decide_proposal(
        proposal.id,
        DecideProposalCommand(
            proposal_id=proposal.id,
            decision="accepted",
            expected_status="pending",
            edited_value={"category": "skill", "text": "Python & FastAPI"},
        ),
    )

    claim = repository.get_claim(result.claim_id)
    versions = repository.list_claim_versions(claim.id)
    assert len(versions) == 1
    assert versions[0].id == result.claim_version_id
    assert versions[0].value["text"] == "Python & FastAPI"


def test_profile_snapshot_is_deterministic_and_excludes_unconfirmed(
    repository: ProfileRepository,
) -> None:
    material = _material(repository)
    version = _version(repository, material.id)
    _parsed_version(repository, version.id)
    evidence = _evidence(repository, version.id)
    proposal = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="mentioned",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]
    repository.decide_proposal(
        proposal.id,
        DecideProposalCommand(proposal_id=proposal.id, decision="accepted", expected_status="pending"),
    )

    snapshot = repository.profile_snapshot(material.workspace_id)
    assert len(snapshot.claims) == 1
    assert snapshot.claims[0].value["text"] == "Python"
    first_version = snapshot.profile_version
    assert first_version is not None

    snapshot_again = repository.profile_snapshot(material.workspace_id)
    assert snapshot_again.profile_version == first_version


def test_save_assessment_and_retrieve(repository: ProfileRepository) -> None:
    material = _material(repository)
    snapshot_version = repository.profile_snapshot(material.workspace_id).profile_version
    assessment = repository.save_assessment(
        SaveAssessmentCommand(
            workspace_id=material.workspace_id,
            base_profile_version=snapshot_version or "",
            result={"strengths": ["Python"], "gaps": []},
        )
    )
    reloaded = repository.get_assessment(assessment.id)
    assert reloaded.result["strengths"] == ["Python"]
    assert reloaded.base_profile_version == (snapshot_version or "")


def test_create_action_plan_with_ordered_items(repository: ProfileRepository) -> None:
    material = _material(repository)
    snapshot_version = repository.profile_snapshot(material.workspace_id).profile_version or ""
    plan = repository.create_action_plan(
        CreateActionPlanCommand(
            workspace_id=material.workspace_id,
            session_id=None,
            execution_id=None,
            request_summary="polish resume",
            base_profile_version=snapshot_version,
            selection_snapshot={},
            items=(
                ActionPlanItemSpec(item_id="i1", ordinal=1, operation="propose_claim_create",
                                   target={"claim_type": "skill"}, after={"text": "Rust"}),
                ActionPlanItemSpec(item_id="i2", ordinal=2, operation="propose_claim_update",
                                   target={"claim_type": "project"}, after={"text": "rewrite"}),
            ),
        )
    )
    reloaded = repository.get_action_plan(plan.id)
    assert [item.item_id for item in reloaded.items] == ["i1", "i2"]
    assert reloaded.status == "proposed"


def test_action_plan_rejects_stale_base_profile(repository: ProfileRepository) -> None:
    material = _material(repository)
    version = _version(repository, material.id)
    _parsed_version(repository, version.id)
    evidence = _evidence(repository, version.id)

    stale_version = repository.profile_snapshot(material.workspace_id).profile_version or ""
    plan = repository.create_action_plan(
        CreateActionPlanCommand(
            workspace_id=material.workspace_id,
            session_id=None,
            execution_id=None,
            request_summary="polish",
            base_profile_version=stale_version,
            selection_snapshot={},
            items=(
                ActionPlanItemSpec(item_id="i1", ordinal=1, operation="propose_claim_create",
                                   target={"claim_type": "skill"}, after={"text": "Rust"}),
            ),
        )
    )

    # Confirm a claim, which changes the profile version.
    proposal = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="mentioned",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]
    repository.decide_proposal(
        proposal.id,
        DecideProposalCommand(proposal_id=proposal.id, decision="accepted", expected_status="pending"),
    )

    with pytest.raises(ProfileSnapshotChanged):
        repository.validate_action_plan_fresh(plan.id)


def test_publication_selection_is_versioned(repository: ProfileRepository) -> None:
    material = _material(repository)
    version = _version(repository, material.id)
    _parsed_version(repository, version.id)
    evidence = _evidence(repository, version.id)
    proposal = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="mentioned",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]
    accepted = repository.decide_proposal(
        proposal.id,
        DecideProposalCommand(proposal_id=proposal.id, decision="accepted", expected_status="pending"),
    )
    snapshot_version = repository.profile_snapshot(material.workspace_id).profile_version or ""

    selection = repository.create_publication_selection(
        CreatePublicationSelectionCommand(
            workspace_id=material.workspace_id,
            profile_version=snapshot_version,
            claim_version_ids=(accepted.claim_version_id,),
            excluded_sensitive_fields=("salary",),
        )
    )
    assert selection.version == 1
    assert selection.claim_version_ids == (accepted.claim_version_id,)

    replaced = repository.create_publication_selection(
        CreatePublicationSelectionCommand(
            workspace_id=material.workspace_id,
            profile_version=snapshot_version,
            claim_version_ids=(accepted.claim_version_id,),
            excluded_sensitive_fields=(),
        )
    )
    assert replaced.version == 2
    previous = repository.get_publication_selection(selection.id)
    assert previous.status == "superseded"


def test_workspace_isolation(repository: ProfileRepository) -> None:
    material_a = _material(repository, workspace_id="w1", role="resume")
    material_b = _material(repository, workspace_id="w2", role="resume")

    assert {m.id for m in repository.list_materials("w1")} == {material_a.id}
    assert {m.id for m in repository.list_materials("w2")} == {material_b.id}
    assert repository.profile_snapshot("w1").claims == ()

    with pytest.raises(ProfileMaterialNotFound):
        repository.get_material(material_b.id, workspace_id="w1")


def test_repository_leaves_no_foreign_key_violations(
    repository: ProfileRepository, connection: sqlite3.Connection
) -> None:
    material = _material(repository)
    version = _version(repository, material.id)
    _parsed_version(repository, version.id)
    evidence = _evidence(repository, version.id)
    proposal = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="mentioned",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]
    repository.decide_proposal(
        proposal.id,
        DecideProposalCommand(proposal_id=proposal.id, decision="accepted", expected_status="pending"),
    )
    repository.profile_snapshot(material.workspace_id)

    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []


def test_decide_proposal_rejects_foreign_workspace_proposal(
    repository: ProfileRepository,
) -> None:
    """Proposals are workspace-scoped: a proposal id from another workspace is
    not addressable through the workspace-bound service path (repository returns
    the record only by id, but the service validates workspace ownership)."""
    material = _material(repository, workspace_id="w1")
    version = _version(repository, material.id)
    _parsed_version(repository, version.id)
    evidence = _evidence(repository, version.id)
    proposal = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="mentioned",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]
    assert proposal.workspace_id == "w1"
