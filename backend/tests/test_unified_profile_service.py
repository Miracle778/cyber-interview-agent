from __future__ import annotations

from pathlib import Path

import pytest

from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.profile.errors import (
    ProfileClaimNotFound,
    ProfileClaimVersionConflict,
    ProfileValueInvalid,
)
from app.profile.models import ProfileRelationSpec
from app.profile.repository import ProfileRepository
from app.profile.service import ProfileService
from app.profile.storage import MaterialStorage


@pytest.fixture
def service(tmp_path: Path) -> ProfileService:
    root = tmp_path / "workspace"
    root.mkdir()
    connection = connect_runtime_database(root)
    return ProfileService(
        workspace_id="w1",
        root=root,
        repository=ProfileRepository(connection),
        storage=MaterialStorage(root),
        product_repository=ProductRepository(connection),
    )


def test_empty_and_manual_profile_projects_user_language(
    service: ProfileService,
) -> None:
    empty = service.unified_profile()
    assert empty.is_usable is False
    assert empty.projects == ()

    experience = service.create_profile_card(
        claim_type="experience",
        value={"organization": "Example", "title": "Backend Engineer"},
        command_id="experience-1",
    )
    project = service.create_profile_card(
        claim_type="project",
        value={
            "name": "Cyber Interview Agent",
            "background": "AI interview learning workspace",
            "tech_stack": ["Python", "LangGraph"],
        },
        relations=(
            ProfileRelationSpec(
                relation_type="belongs_to",
                target_claim_id=experience.claim_id,
            ),
        ),
        command_id="project-1",
    )
    skill = service.create_profile_card(
        claim_type="skill",
        value={"name": "Python"},
        relations=(
            ProfileRelationSpec(
                relation_type="used_in",
                target_claim_id=project.claim_id,
            ),
        ),
        command_id="skill-1",
    )

    profile = service.unified_profile()
    assert profile.is_usable is True
    assert profile.projects[0].title == "Cyber Interview Agent"
    assert profile.projects[0].sources[0].label == "本人补充"
    assert profile.projects[0].linked_to[0].claim_id == experience.claim_id
    assert profile.skills[0].claim_id == skill.claim_id
    assert profile.skills[0].used_in[0].claim_id == project.claim_id
    assert {item.message for item in profile.actionable_gaps} == {
        "项目缺少结果或量化成果",
        "项目缺少你的角色或职责",
        "工作经历缺少起止时间",
    }


def test_manual_cards_are_strict_versioned_restorable_and_logically_deleted(
    service: ProfileService,
) -> None:
    with pytest.raises(ProfileValueInvalid):
        service.create_profile_card(
            claim_type="project",
            value={"name": "Project", "unknown": "not allowed"},
            command_id="invalid-project",
        )

    first = service.create_profile_card(
        claim_type="project",
        value={"name": "Original", "role": "Owner", "results": ["Released"]},
        command_id="project-create",
    )
    second = service.update_profile_card(
        first.claim_id,
        value={"name": "Updated", "role": "Owner", "results": ["Released"]},
        expected_version=1,
        command_id="project-update",
    )
    with pytest.raises(ProfileClaimVersionConflict):
        service.update_profile_card(
            first.claim_id,
            value={"name": "Stale"},
            expected_version=1,
            command_id="project-stale",
        )

    restored = service.restore_profile_card_version(
        first.claim_id,
        first.id,
        expected_version=2,
        command_id="project-restore",
    )
    assert restored.version == 3
    assert restored.value["name"] == "Original"
    assert [item.status for item in service.repository.list_claim_versions(first.claim_id)] == [
        "confirmed",
        "superseded",
        "superseded",
    ]

    service.delete_profile_card(
        first.claim_id,
        expected_version=3,
        command_id="project-delete",
    )
    assert service.unified_profile().projects == ()
    with pytest.raises(ProfileClaimNotFound):
        service.repository.get_claim(first.claim_id)
    assert second.claim_id == first.claim_id


def test_projection_exposes_pending_count_source_state_and_manual_context(
    service: ProfileService,
) -> None:
    certification = service.create_profile_card(
        claim_type="certification",
        value={"name": "Cloud Certification", "issuer": "Example"},
        command_id="certification-1",
    )
    service.repository.connection.execute(
        "UPDATE profile_claim_sources SET status = 'source_deleted' "
        "WHERE claim_version_id = ?",
        (certification.id,),
    )
    service.repository.connection.execute(
        "INSERT INTO profile_claim_proposals "
        "(id, workspace_id, proposal_type, proposed_value_json, reason) "
        "VALUES ('pending-1', 'w1', 'create', "
        "'{\"category\":\"skill\",\"name\":\"Redis\"}', '对话中提到')"
    )
    service.repository.connection.commit()

    profile = service.unified_profile()
    assert profile.pending_count == 1
    assert profile.certifications[0].sources[0].label == "原来源已删除，本人保留"
    service.repository.connection.execute(
        "UPDATE profile_claim_sources "
        "SET status = 'active', source_kind = 'resume_extraction' "
        "WHERE claim_version_id = ?",
        (certification.id,),
    )
    service.repository.connection.commit()
    service.repository.mark_claim_unsupported(
        certification.claim_id, reason="resume version deleted"
    )
    profile = service.unified_profile()
    assert profile.certifications[0].support_status == "unsupported"
    assert profile.certifications[0].sources[0].status == "active"
    assert profile.certifications[0].sources[0].label == "简历提取"

    context = service.confirmed_profile_context(
        purpose="job_target_analysis",
        claim_types=("certification",),
    )
    assert context.items[0].claim_id == certification.claim_id
    assert context.items[0].evidence_ids == ()
