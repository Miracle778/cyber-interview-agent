from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.profile.errors import (
    ProfileClaimSelectedForPublication,
    ProfileClaimVersionConflict,
    ProfileDeletionPlanConflict,
    ProfileMaterialNotFound,
    ProfileMaterialVersionHasPendingProposals,
    ProfileMaterialVersionNotFound,
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


def _material_with_two_versions(service: ProfileService):
    first = service.upload_material(
        file_name="resume-v1.txt",
        content=b"Python",
        title="Resume",
    )
    service.record_ingest_success(first.version.id)
    first_evidence = service.repository.replace_version_evidence(
        first.version.id,
        ({
            "section": "skills",
            "start_offset": 0,
            "end_offset": 6,
            "sanitized_text": "Python",
            "content_sha256": "1" * 64,
            "sensitivity": "normal",
        },),
    )[0]
    second = service.add_material_version(
        material_id=first.material.id,
        file_name="resume-v2.txt",
        content=b"Python and FastAPI",
    )
    service.record_ingest_success(second.version.id)
    second_evidence = service.repository.replace_version_evidence(
        second.version.id,
        ({
            "section": "skills",
            "start_offset": 0,
            "end_offset": 18,
            "sanitized_text": "Python and FastAPI",
            "content_sha256": "2" * 64,
            "sensitivity": "normal",
        },),
    )[0]
    material = service.set_primary_version(
        first.material.id,
        second.version.id,
        expected_version=service.get_material(first.material.id).version,
        idempotency_key="set-primary-v2",
    )
    return material, first.version, second.version, first_evidence, second_evidence


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


def test_duplicate_preview_and_consolidation_merge_only_pending_create_entities(
    service: ProfileService,
) -> None:
    uploaded = service.upload_material(
        file_name="resume.txt",
        content=b"Cyber Interview Agent project",
        title="Resume",
    )
    service.record_ingest_success(uploaded.version.id)
    evidence = service.repository.replace_version_evidence(
        uploaded.version.id,
        (
            {
                "section": "projects",
                "start_offset": 0,
                "end_offset": 12,
                "sanitized_text": "负责 Agent 工作流设计",
                "content_sha256": "a" * 64,
                "sensitivity": "normal",
            },
            {
                "section": "projects",
                "start_offset": 13,
                "end_offset": 28,
                "sanitized_text": "使用 LangGraph 与 SQLite",
                "content_sha256": "b" * 64,
                "sensitivity": "normal",
            },
        ),
    )
    proposals = service.repository.create_claim_proposals(
        uploaded.version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={
                    "category": "project",
                    "name": "Cyber Interview Agent",
                    "role": "后端开发",
                    "confidence": 0.91,
                },
                reason="简历列出了职责",
                evidence_ids=(evidence[0].id,),
            ),
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={
                    "category": "project",
                    "name": "Cyber Interview Agent",
                    "techStack": ["LangGraph", "SQLite"],
                    "confidence": 0.88,
                },
                reason="简历列出了技术栈",
                evidence_ids=(evidence[1].id,),
            ),
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "project", "role": "匿名项目职责"},
                reason="缺少稳定项目名称",
                evidence_ids=(evidence[0].id,),
            ),
        ),
    )

    preview = service.duplicate_proposal_preview()
    assert len(preview.groups) == 1
    assert set(preview.groups[0].proposal_ids) == {proposals[0].id, proposals[1].id}
    assert preview.groups[0].merged_value["role"] == "后端开发"
    assert preview.groups[0].merged_value["tech_stack"] == ["LangGraph", "SQLite"]

    result = service.consolidate_duplicate_proposals(
        expected_groups=(preview.groups[0].proposal_ids,),
        idempotency_key="consolidate-duplicate-proposals-1",
    )
    assert result.canonical_proposal_ids == (proposals[0].id,)
    assert result.superseded_proposal_ids == (proposals[1].id,)
    canonical = service.repository.get_proposal(proposals[0].id)
    assert canonical.status == "pending"
    assert canonical.proposed_value["tech_stack"] == ["LangGraph", "SQLite"]
    assert set(canonical.evidence_ids) == {evidence[0].id, evidence[1].id}
    assert service.repository.get_proposal(proposals[1].id).status == "superseded"
    assert service.repository.get_proposal(proposals[2].id).status == "pending"


def test_duplicate_consolidation_rejects_a_stale_preview(
    service: ProfileService,
) -> None:
    uploaded, evidence, first = _proposal(service, text="Python")
    second = service.repository.create_claim_proposals(
        uploaded.version.id,
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
    preview = service.duplicate_proposal_preview()
    assert set(preview.groups[0].proposal_ids) == {first.id, second.id}
    service.decide_claim_proposal(
        second.id,
        decision="rejected",
        expected_version=0,
        idempotency_key="reject-before-consolidate-1",
    )

    with pytest.raises(ProfileClaimVersionConflict):
        service.consolidate_duplicate_proposals(
            expected_groups=(preview.groups[0].proposal_ids,),
            idempotency_key="consolidate-stale-preview-1",
        )


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


def test_material_version_deletion_only_tombstones_the_target_version(
    service: ProfileService,
) -> None:
    material, first, second, first_evidence, second_evidence = (
        _material_with_two_versions(service)
    )
    preview = service.preview_material_version_deletion(
        first.id,
        expected_version=material.version,
        idempotency_key="preview-version-delete-1",
    )

    assert preview.impact["versionIds"] == [first.id]
    assert preview.impact["targetVersionId"] == first.id
    result = service.permanently_delete_material_version(
        first.id,
        deletion_plan_id=preview.id,
        expected_version=material.version,
        replacement_version_id=None,
        claim_choices={},
        active_publication_action="not_applicable",
        idempotency_key="delete-version-1",
    )

    assert result.status == "completed"
    assert service.repository.get_evidence(first_evidence.id).tombstoned_at is not None
    assert service.repository.get_evidence(second_evidence.id).tombstoned_at is None
    assert (
        service.repository.get_material_version_for_audit(first.id).file_name
        == "[deleted]"
    )
    assert service.repository.get_material_version(second.id).file_name == "resume-v2.txt"
    with pytest.raises(ProfileMaterialVersionNotFound):
        service.get_material_version(first.id)
    assert service.get_material(material.id).current_version_id == second.id


def test_material_version_deletion_preview_exposes_affected_claim_content(
    service: ProfileService,
) -> None:
    material, first, _second, first_evidence, _second_evidence = (
        _material_with_two_versions(service)
    )
    proposal = service.repository.create_claim_proposals(
        first.id,
        (CreateClaimProposalSpec(
            proposal_type="create",
            proposed_value={
                "category": "project",
                "name": "面试准备 Agent",
                "description": "基于可恢复工作流整理面试资料",
            },
            reason="第一版项目经历",
            evidence_ids=(first_evidence.id,),
        ),),
    )[0]
    service.decide_claim_proposal(
        proposal.id,
        decision="accepted",
        expected_version=0,
        idempotency_key="accept-before-version-preview",
    )

    preview = service.preview_material_version_deletion(
        first.id,
        expected_version=material.version,
        idempotency_key="preview-version-claim-content",
    )

    assert preview.impact["claims"][0]["value"] == {
        "category": "project",
        "description": "基于可恢复工作流整理面试资料",
        "name": "面试准备 Agent",
    }


def test_material_version_deletion_preserves_claim_supported_by_another_version(
    service: ProfileService,
) -> None:
    material, first, second, first_evidence, second_evidence = (
        _material_with_two_versions(service)
    )
    proposal = service.repository.create_claim_proposals(
        first.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "name": "Python"},
                reason="第一版列出 Python",
                evidence_ids=(first_evidence.id,),
            ),
        ),
    )[0]
    accepted = service.decide_claim_proposal(
        proposal.id,
        decision="accepted",
        expected_version=0,
        idempotency_key="accept-multi-source-claim",
    )
    service.repository.attach_claim_source(
        workspace_id="w1",
        claim_version_id=accepted.claim_version_id,
        source_kind="resume_extraction",
        source_ref={
            "materialVersionId": second.id,
            "evidenceIds": [second_evidence.id],
        },
    )

    preview = service.preview_material_version_deletion(
        first.id,
        expected_version=material.version,
        idempotency_key="preview-multi-source-version-delete",
    )

    affected = preview.impact["claims"][0]
    assert affected["affectedEvidenceIds"] == [first_evidence.id]
    assert affected["remainingEvidenceIds"] == [second_evidence.id]

    service.permanently_delete_material_version(
        first.id,
        deletion_plan_id=preview.id,
        expected_version=material.version,
        replacement_version_id=None,
        claim_choices={accepted.claim_id: "retain_unsupported"},
        active_publication_action="not_applicable",
        idempotency_key="delete-one-of-two-claim-sources",
    )

    claim = service.repository.profile_snapshot("w1").claims[0]
    assert claim.support_status == "supported"
    assert claim.evidence_ids == (second_evidence.id,)
    assert {source.status for source in claim.sources} == {"active", "source_deleted"}


def test_unified_profile_marks_semantically_related_resume_text_for_review(
    service: ProfileService,
) -> None:
    material, first, second, first_evidence, second_evidence = (
        _material_with_two_versions(service)
    )
    service.repository.connection.execute(
        "UPDATE profile_evidence SET sanitized_text = ?, section = ? WHERE id = ?",
        (
            "负责限流熔断、灰度发布和故障演练",
            '{"block":"可信软件供应链安全平台","lineEnd":46,'
            '"lineStart":39,"section":"项目经历"}',
            second_evidence.id,
        ),
    )
    service.repository.connection.commit()
    proposal = service.repository.create_claim_proposals(
        first.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "name": "Nginx 灰度发布"},
                reason="旧版明确写出 Nginx 灰度发布",
                evidence_ids=(first_evidence.id,),
            ),
        ),
    )[0]
    accepted = service.decide_claim_proposal(
        proposal.id,
        decision="accepted",
        expected_version=0,
        idempotency_key="accept-related-source-claim",
    )
    preview = service.preview_material_version_deletion(
        first.id,
        expected_version=material.version,
        idempotency_key="preview-related-source-delete",
    )
    service.permanently_delete_material_version(
        first.id,
        deletion_plan_id=preview.id,
        expected_version=material.version,
        replacement_version_id=None,
        claim_choices={accepted.claim_id: "retain_unsupported"},
        active_publication_action="not_applicable",
        idempotency_key="delete-direct-but-keep-related-source",
    )

    card = service.unified_profile().skills[0]
    assert card.support_status == "related"
    assert card.support_summary == "剩余简历中发现相关描述，需要你核对是否能作为这条资料的依据"
    assert len(card.support_evidence) == 1
    assert card.support_evidence[0].evidence_id == second_evidence.id
    assert card.support_evidence[0].section == "项目经历 · 第 39–46 行"
    assert "灰度发布" in card.support_evidence[0].excerpt


def test_material_version_deletion_blocks_when_any_version_has_pending_proposals(
    service: ProfileService,
) -> None:
    material, first, second, _first_evidence, second_evidence = (
        _material_with_two_versions(service)
    )
    service.repository.create_claim_proposals(
        second.id,
        (CreateClaimProposalSpec(
            proposal_type="create",
            proposed_value={"category": "skill", "text": "FastAPI"},
            reason="第二版列出",
            evidence_ids=(second_evidence.id,),
        ),),
    )

    with pytest.raises(ProfileMaterialVersionHasPendingProposals):
        service.preview_material_version_deletion(
            first.id,
            expected_version=material.version,
            idempotency_key="preview-any-version-pending-blocked",
        )


def test_material_version_deletion_rechecks_workspace_pending_proposals_at_execution(
    service: ProfileService,
) -> None:
    material, first, _second, _first_evidence, _second_evidence = (
        _material_with_two_versions(service)
    )
    preview = service.preview_material_version_deletion(
        first.id,
        expected_version=material.version,
        idempotency_key="preview-before-material-pending",
    )
    unrelated = service.upload_material(
        file_name="other-resume.txt",
        content=b"FastAPI",
        title="Other resume",
        primary_role="other-resume",
    )
    service.record_ingest_success(unrelated.version.id)
    unrelated_evidence = service.repository.replace_version_evidence(
        unrelated.version.id,
        ({
            "section": "skills",
            "start_offset": 0,
            "end_offset": 7,
            "sanitized_text": "FastAPI",
            "content_sha256": "3" * 64,
            "sensitivity": "normal",
        },),
    )[0]
    service.repository.create_claim_proposals(
        unrelated.version.id,
        (CreateClaimProposalSpec(
            proposal_type="create",
            proposed_value={"category": "skill", "text": "FastAPI"},
            reason="预检后新增的其他简历待确认信息",
            evidence_ids=(unrelated_evidence.id,),
        ),),
    )

    with pytest.raises(ProfileMaterialVersionHasPendingProposals):
        service.permanently_delete_material_version(
            first.id,
            deletion_plan_id=preview.id,
            expected_version=material.version,
            replacement_version_id=None,
            claim_choices={},
            active_publication_action="not_applicable",
            idempotency_key="delete-after-material-pending",
        )
    assert service.get_material_version(first.id).id == first.id


def test_material_version_deletion_requires_replacement_for_current_version(
    service: ProfileService,
) -> None:
    material, first, second, _first_evidence, _second_evidence = (
        _material_with_two_versions(service)
    )
    preview = service.preview_material_version_deletion(
        second.id,
        expected_version=material.version,
        idempotency_key="preview-current-version-delete",
    )

    with pytest.raises(ProfileDeletionPlanConflict, match="replacement"):
        service.permanently_delete_material_version(
            second.id,
            deletion_plan_id=preview.id,
            expected_version=material.version,
            replacement_version_id=None,
            claim_choices={},
            active_publication_action="not_applicable",
            idempotency_key="delete-current-without-replacement",
        )

    result = service.permanently_delete_material_version(
        second.id,
        deletion_plan_id=preview.id,
        expected_version=material.version,
        replacement_version_id=first.id,
        claim_choices={},
        active_publication_action="not_applicable",
        idempotency_key="delete-current-with-replacement",
    )
    assert result.status == "completed"
    assert service.get_material(material.id).current_version_id == first.id
