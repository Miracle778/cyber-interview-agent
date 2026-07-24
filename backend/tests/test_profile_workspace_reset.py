from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.runtime_database import (
    connect_runtime_database,
    runtime_database_path,
)
from app.profile.models import AppendConfirmedClaimCommand
from app.profile.repository import ProfileRepository
from app.profile.storage import MaterialStorage
from scripts.reset_profile_workspace import (
    ProfileResetRefused,
    build_reset_plan,
    execute_reset,
    validate_paths,
)


def _claim(repository: ProfileRepository, workspace_id: str, key: str) -> None:
    repository.append_confirmed_claim(
        AppendConfirmedClaimCommand(
            workspace_id=workspace_id,
            claim_type="skill",
            value={"name": "Python"},
            source_kind="user_input",
            source_ref={"commandId": key},
            expected_claim_version=0,
            idempotency_key=key,
        )
    )


def _material(
    repository: ProfileRepository,
    storage: MaterialStorage,
    *,
    workspace_id: str,
    material_id: str,
    version_id: str,
    shared_upload: bytes,
) -> tuple[str, str]:
    blob = storage.persist_upload(file_name="resume.txt", content=shared_upload)
    text_ref = storage.write_text(version_id=version_id, text=workspace_id)
    repository.connection.execute(
        "INSERT INTO profile_materials "
        "(id, workspace_id, type, title, primary_role, current_version_id) "
        "VALUES (?, ?, 'resume', ?, ?, ?)",
        (
            material_id,
            workspace_id,
            f"{workspace_id} resume",
            f"resume-{workspace_id}",
            version_id,
        ),
    )
    repository.connection.execute(
        "INSERT INTO profile_material_versions "
        "(id, material_id, version_number, source_type, file_name, mime_type, "
        "content_sha256, storage_ref, text_ref, processing_status) "
        "VALUES (?, ?, 1, 'upload', 'resume.txt', 'text/plain', ?, ?, ?, 'ready')",
        (
            version_id,
            material_id,
            blob.content_sha256,
            blob.storage_ref,
            text_ref,
        ),
    )
    repository.connection.commit()
    return blob.storage_ref, text_ref


def test_reset_is_exact_workspace_and_preserves_shared_and_review_data(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    repository = ProfileRepository(connection)
    (tmp_path / "artifacts" / "profile" / "materials" / "blobs").mkdir(
        parents=True
    )
    (tmp_path / "artifacts" / "profile" / "materials" / "text").mkdir()
    storage = MaterialStorage(tmp_path)
    shared_ref, w1_text_ref = _material(
        repository,
        storage,
        workspace_id="w1",
        material_id="m1",
        version_id="v1",
        shared_upload=b"shared resume",
    )
    _material(
        repository,
        storage,
        workspace_id="w2",
        material_id="m2",
        version_id="v2",
        shared_upload=b"shared resume",
    )
    _claim(repository, "w1", "w1-skill")
    _claim(repository, "w2", "w2-skill")
    connection.executemany(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title, visibility) "
        "VALUES (?, ?, ?, 1, ?, ?)",
        (
            ("manage-w1", "w1", "profile.manage", "Profile", "user"),
            ("v1", "w1", "profile.ingest", "Ingest", "system"),
            ("manage-w2", "w2", "profile.manage", "Profile", "user"),
            ("review-w1", "w1", "question.curate", "Review", "user"),
        ),
    )
    connection.execute(
        "INSERT INTO review_curation_sessions "
        "(session_id, workspace_id, source_refs_json) VALUES ('review-w1', 'w1', '[]')"
    )
    connection.commit()

    preview = build_reset_plan(connection, "w1")
    assert preview.table_counts["profile_materials"] == 1
    assert preview.table_counts["profile_sessions"] == 2
    assert repository.list_claims("w1")

    plan, deleted_refs = execute_reset(
        connection,
        workspace_root=tmp_path,
        workspace_id="w1",
        confirmation="RESET PROFILE w1",
    )

    assert plan.workspace_id == "w1"
    assert w1_text_ref in deleted_refs
    assert shared_ref not in deleted_refs
    assert storage.blob_exists(shared_ref)
    assert not storage.blob_exists(w1_text_ref)
    assert repository.list_materials("w1") == ()
    assert repository.list_claims("w1") == ()
    assert len(repository.list_materials("w2")) == 1
    assert len(repository.list_claims("w2")) == 1
    assert connection.execute(
        "SELECT 1 FROM agent_sessions WHERE id = 'review-w1'"
    ).fetchone()
    assert connection.execute(
        "SELECT 1 FROM review_curation_sessions WHERE session_id = 'review-w1'"
    ).fetchone()
    assert connection.execute(
        "SELECT 1 FROM agent_sessions WHERE id = 'manage-w2'"
    ).fetchone()


def test_reset_refuses_wrong_path_confirmation_and_active_run(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)
    repository = ProfileRepository(connection)
    _claim(repository, "w1", "w1-skill")
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('manage-w1', 'w1', 'profile.manage', 1, 'Profile')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('run-1', 'manage-w1', 'running')"
    )
    connection.commit()

    with pytest.raises(ProfileResetRefused):
        validate_paths(Path("relative.db"), tmp_path)
    assert validate_paths(runtime_database_path(tmp_path), tmp_path)

    with pytest.raises(ProfileResetRefused):
        execute_reset(
            connection,
            workspace_root=tmp_path,
            workspace_id="w1",
            confirmation="wrong",
        )
    with pytest.raises(ProfileResetRefused, match="active Profile run"):
        execute_reset(
            connection,
            workspace_root=tmp_path,
            workspace_id="w1",
            confirmation="RESET PROFILE w1",
        )
