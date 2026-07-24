from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.infrastructure.runtime_database import connect_runtime_database
from app.profile.errors import (
    ProfileClaimVersionConflict,
    ProfileIdempotencyConflict,
)
from app.profile.models import (
    AppendConfirmedClaimCommand,
    ProfileRelationSpec,
    UpdateProfilePresentationCommand,
)
from app.profile.repository import ProfileRepository


@pytest.fixture
def repository(tmp_path: Path) -> ProfileRepository:
    return ProfileRepository(connect_runtime_database(tmp_path))


def _append(
    repository: ProfileRepository,
    *,
    workspace_id: str = "w1",
    claim_type: str = "project",
    value: dict[str, object] | None = None,
    key: str = "create-1",
    claim_id: str | None = None,
    expected: int = 0,
):
    return repository.append_confirmed_claim(
        AppendConfirmedClaimCommand(
            workspace_id=workspace_id,
            claim_type=claim_type,  # type: ignore[arg-type]
            value=value or {"name": "Cyber Interview Agent"},
            source_kind="user_input",
            source_ref={"commandId": key},
            expected_claim_version=expected,
            idempotency_key=key,
            claim_id=claim_id,
        )
    )


def test_direct_user_write_appends_confirmed_version_without_evidence(
    repository: ProfileRepository,
) -> None:
    version = _append(repository)
    claim = repository.get_claim(version.claim_id)

    assert version.status == "confirmed"
    assert version.evidence_ids == ()
    assert version.source == "user_input"
    assert claim.current_confirmed_version_id == version.id
    assert repository.list_claim_sources(version.id)[0].source_ref == {
        "commandId": "create-1"
    }


def test_direct_update_is_versioned_idempotent_and_optimistic(
    repository: ProfileRepository,
) -> None:
    first = _append(repository)
    replay = _append(repository)
    assert replay.id == first.id

    second = _append(
        repository,
        key="update-1",
        claim_id=first.claim_id,
        expected=1,
        value={"name": "Cyber Interview Agent", "result": "released"},
    )
    assert second.version == 2
    assert [item.status for item in repository.list_claim_versions(first.claim_id)] == [
        "confirmed",
        "superseded",
    ]

    with pytest.raises(ProfileClaimVersionConflict):
        _append(
            repository,
            key="stale-update",
            claim_id=first.claim_id,
            expected=1,
        )
    with pytest.raises(ProfileIdempotencyConflict):
        _append(repository, value={"name": "different"})


def test_relations_require_same_workspace_and_replace_atomically(
    repository: ProfileRepository,
) -> None:
    project = _append(repository, key="project")
    skill = _append(
        repository,
        key="skill",
        claim_type="skill",
        value={"name": "Python"},
    )
    foreign = _append(
        repository,
        workspace_id="w2",
        key="foreign",
        claim_type="experience",
        value={"organization": "Other"},
    )

    relations = repository.replace_claim_relations(
        "w1",
        skill.claim_id,
        (ProfileRelationSpec(relation_type="used_in", target_claim_id=project.claim_id),),
    )
    assert [(item.relation_type, item.to_claim_id) for item in relations] == [
        ("used_in", project.claim_id)
    ]

    with pytest.raises(ProfileClaimVersionConflict):
        repository.replace_claim_relations(
            "w1",
            project.claim_id,
            (
                ProfileRelationSpec(
                    relation_type="belongs_to",
                    target_claim_id=foreign.claim_id,
                ),
            ),
        )
    assert repository.list_claim_relations("w1", from_claim_id=project.claim_id) == ()


def test_presentation_preserves_featured_order_and_rejects_stale_version(
    repository: ProfileRepository,
) -> None:
    highlight = _append(
        repository,
        key="highlight",
        claim_type="highlight",
        value={"text": "Built a recoverable Agent runtime"},
    )
    direction = _append(
        repository,
        key="direction",
        claim_type="direction",
        value={"name": "Agent 应用工程"},
    )
    presentation = repository.update_profile_presentation(
        UpdateProfilePresentationCommand(
            workspace_id="w1",
            summary_claim_id=None,
            primary_direction_claim_id=direction.claim_id,
            featured_claim_ids=(highlight.claim_id,),
            expected_version=0,
            idempotency_key="presentation-1",
        )
    )
    assert presentation.primary_direction_claim_id == direction.claim_id
    assert presentation.featured_claim_ids == (highlight.claim_id,)
    assert presentation.version == 1

    with pytest.raises(ProfileClaimVersionConflict):
        repository.update_profile_presentation(
            UpdateProfilePresentationCommand(
                workspace_id="w1",
                summary_claim_id=None,
                primary_direction_claim_id=None,
                featured_claim_ids=(),
                expected_version=0,
                idempotency_key="presentation-stale",
            )
        )


def test_snapshot_includes_sources_and_excludes_deleted_claims(
    repository: ProfileRepository,
) -> None:
    version = _append(repository)
    snapshot = repository.profile_snapshot("w1")
    assert snapshot.claims[0].sources[0].source_kind == "user_input"

    repository.connection.execute(
        "UPDATE profile_claims SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
        (version.claim_id,),
    )
    repository.connection.commit()
    assert repository.profile_snapshot("w1").claims == ()
