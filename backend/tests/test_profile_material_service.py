from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from langgraph.graph import END, START, StateGraph

from app.application.workspace_runtime import AgentApplication
from app.application.session_service import (
    ProductRecordNotFoundError,
    ProductRepository,
    SessionBusyError,
)
from app.infrastructure.runtime_database import connect_runtime_database
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.profile.repository import ProfileRepository
from app.profile.errors import ProfileMaterialNotFound
from app.profile.models import CreateMaterialCommand
from app.profile.service import MaterialUploadResult, ProfileService
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


def test_upload_material_creates_immutable_version_and_hidden_session(
    service: ProfileService, connection: sqlite3.Connection
) -> None:
    result = service.upload_material(
        file_name="resume.txt", content=b"hello resume", title="My Resume"
    )

    assert isinstance(result, MaterialUploadResult)
    assert result.version.version_number == 1
    assert result.version.source_type == "upload"
    assert result.execution_id is not None

    # Hidden system session id == version id.
    row = connection.execute(
        "SELECT visibility, graph_id FROM agent_sessions WHERE id = ?",
        (result.version.id,),
    ).fetchone()
    assert row["visibility"] == "system"
    assert row["graph_id"] == "profile.ingest"

    # Execution input carries IDs/locators only, no source content.
    execution = ProductRepository(connection).get_execution(result.execution_id)
    assert execution.input["versionId"] == result.version.id
    assert execution.input["materialId"] == result.material.id
    assert "hello resume" not in str(execution.input)

    # No user-visible upload/chat message is created.
    messages = connection.execute(
        "SELECT COUNT(*) FROM agent_messages WHERE session_id = ?",
        (result.version.id,),
    ).fetchone()[0]
    assert messages == 0


def test_add_material_version_increments_monotonically(service: ProfileService) -> None:
    first = service.upload_material(
        file_name="resume.txt", content=b"v1", title="Resume"
    )
    second = service.add_material_version(
        material_id=first.material.id, file_name="resume-v2.txt", content=b"v2"
    )

    assert second.version.version_number == 2
    assert second.version.material_id == first.material.id


def test_material_service_rejects_cross_workspace_material_id(
    service: ProfileService,
) -> None:
    foreign = service.repository.create_material(
        CreateMaterialCommand(
            workspace_id="w2",
            type="resume",
            title="Foreign resume",
            primary_role="resume",
        )
    )

    with pytest.raises(ProfileMaterialNotFound):
        service.add_material_version(
            material_id=foreign.id,
            file_name="foreign.txt",
            content=b"must not cross workspace",
        )


def test_duplicate_content_reuses_blob_but_creates_new_version(
    service: ProfileService, connection: sqlite3.Connection
) -> None:
    first = service.upload_material(
        file_name="resume.txt", content=b"same bytes", title="Resume"
    )
    second = service.add_material_version(
        material_id=first.material.id, file_name="resume-copy.txt", content=b"same bytes"
    )

    assert first.version.content_sha256 == second.version.content_sha256
    assert first.version.storage_ref == second.version.storage_ref
    assert first.version.id != second.version.id
    assert second.version.version_number == 2


def test_retry_after_parse_failure_creates_new_execution(
    service: ProfileService, connection: sqlite3.Connection
) -> None:
    result = service.upload_material(
        file_name="resume.txt", content=b"bad pdf", title="Resume"
    )
    service.record_ingest_failure(
        result.version.id, processing_status="parse_failed", error_code="profile_parse_failed"
    )

    retry = service.retry_version_ingest(result.version.id)

    assert retry.id != result.execution_id
    assert retry.session_id == result.version.id
    version = service.repository.get_material_version(result.version.id)
    assert version.processing_status == "parsing"


def test_retry_refused_while_execution_active(service: ProfileService) -> None:
    result = service.upload_material(
        file_name="resume.txt", content=b"live", title="Resume"
    )
    with pytest.raises(SessionBusyError):
        service.retry_version_ingest(result.version.id)


def test_archive_restore_and_primary_selection(service: ProfileService) -> None:
    result = service.upload_material(
        file_name="resume.txt", content=b"v1", title="Resume"
    )
    second = service.add_material_version(
        material_id=result.material.id, file_name="r2.txt", content=b"v2"
    )

    service.set_primary_version(result.material.id, second.version.id)
    material = service.repository.get_material(result.material.id)
    assert material.current_version_id == second.version.id

    service.archive_material(result.material.id)
    active = service.repository.list_materials("w1")
    assert result.material.id not in {m.id for m in active}

    service.restore_material(result.material.id)
    active = service.repository.list_materials("w1")
    assert result.material.id in {m.id for m in active}


def test_hidden_session_excluded_from_generic_list_and_detail(
    service: ProfileService, connection: sqlite3.Connection
) -> None:
    result = service.upload_material(
        file_name="resume.txt", content=b"x", title="Resume"
    )
    product_repository = ProductRepository(connection)

    # Generic list excludes the hidden system session.
    listed = product_repository.list_sessions("w1")
    assert result.version.id not in {s.id for s in listed}

    # Internal include_system path still sees it.
    listed_with_system = product_repository.list_sessions("w1", include_system=True)
    assert result.version.id in {s.id for s in listed_with_system}

    # The hidden session is still retrievable by id for internal Runtime use.
    session = product_repository.get_session(result.version.id)
    assert session.visibility == "system"


def test_restart_recovers_material_and_hidden_session(
    service: ProfileService, tmp_path: Path
) -> None:
    result = service.upload_material(
        file_name="resume.txt", content=b"persist me", title="Resume"
    )
    service.connection.close()

    # Reopen the same database (simulates process restart).
    reopened = connect_runtime_database(tmp_path / "ws")
    product_repository = ProductRepository(reopened)
    profile_repository = ProfileRepository(reopened)

    material = profile_repository.get_material(result.material.id)
    assert material.id == result.material.id
    session = product_repository.get_session(result.version.id)
    assert session.visibility == "system"
    assert session.kind == "profile.ingest"
    reopened.close()


@pytest.mark.asyncio
async def test_workspace_runtime_initializes_profile_artifacts_before_upload(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime-workspace"
    root.mkdir()

    def graph_factory(_kind: str, **_dependencies):
        graph = StateGraph(dict)
        graph.add_node("done", lambda state: state)
        graph.add_edge(START, "done")
        graph.add_edge("done", END)
        return graph.compile()

    application = AgentApplication(
        workspace_resolver=lambda _workspace_id: root,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=graph_factory,
    )
    try:
        context = application._context("w1")
        result = context.profile.upload_material(
            file_name="resume.txt", content=b"hello", title="Resume"
        )
        assert result.version.storage_ref.startswith("blobs/")
        execution = await context.executions.wait(result.execution_id)
        assert execution.status == "completed"
    finally:
        await application.close()
