import sqlite3
from pathlib import Path

import pytest

from app.db.app_database import connect_app_database
from app.repositories.provider_repository import ProviderRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.core.errors import WorkspaceConflictError
from app.services.workspace_service import WorkspaceService


@pytest.fixture
def app_connection(tmp_path):
    connection = connect_app_database(tmp_path)
    try:
        yield connection
    finally:
        connection.close()


def _create_provider_with_model(app_connection):
    providers = ProviderRepository(app_connection)
    provider = providers.create_provider(
        name="P",
        api_format="openai-compatible",
        base_url="https://example.test/v1",
        secret_source="environment",
        secret_ref="KEY",
    )
    model = providers.create_model(provider.id, "m1", "M1")
    return providers, provider, model


def test_workspace_register_returns_record_with_id(app_connection, tmp_path):
    workspaces = WorkspaceRepository(app_connection)
    record = workspaces.register(root_path=str(tmp_path / "vault"))
    assert record.id
    assert record.root_path == str(tmp_path / "vault")

    loaded = workspaces.get(record.id)
    assert loaded is not None
    assert loaded.id == record.id
    assert loaded.root_path == str(tmp_path / "vault")


def test_workspace_persists_across_restart_and_relinks(app_connection, tmp_path):
    workspaces = WorkspaceRepository(app_connection)
    original = workspaces.register(root_path=str(tmp_path / "vault"))
    app_connection.commit()

    reopened = connect_app_database(tmp_path)
    try:
        workspaces2 = WorkspaceRepository(reopened)
        loaded = workspaces2.get(original.id)
        assert loaded is not None
        assert loaded.id == original.id
        assert loaded.root_path == str(tmp_path / "vault")

        relinked = workspaces2.relink(original.id, str(tmp_path / "moved"))
        assert relinked.id == original.id
        assert relinked.root_path == str(tmp_path / "moved")
        reopened.commit()
    finally:
        reopened.close()


def test_workspace_binds_answer_evaluation_model(app_connection, tmp_path):
    _providers, _provider, model = _create_provider_with_model(app_connection)
    workspaces = WorkspaceRepository(app_connection)
    workspace = workspaces.register(root_path=str(tmp_path / "ws"))

    binding = workspaces.set_model_binding(workspace.id, "answer_evaluation", model.id)

    assert binding.workspace_id == workspace.id
    assert binding.role == "answer_evaluation"
    assert binding.provider_model_id == model.id

    bindings = workspaces.get_model_bindings(workspace.id)
    assert {b.role: b.provider_model_id for b in bindings} == {"answer_evaluation": model.id}


def test_delete_bound_model_raises_integrity_error(app_connection, tmp_path):
    _providers, _provider, model = _create_provider_with_model(app_connection)
    workspaces = WorkspaceRepository(app_connection)
    workspace = workspaces.register(root_path=str(tmp_path / "ws"))
    workspaces.set_model_binding(workspace.id, "answer_evaluation", model.id)

    with pytest.raises(sqlite3.IntegrityError):
        ProviderRepository(app_connection).delete_model(model.id)


def test_workspace_selection_and_recycle_are_explicit(app_connection, tmp_path):
    service = WorkspaceService(app_connection)
    first = service.register(str(tmp_path / "first"))
    second = service.register(str(tmp_path / "second"), "面试准备")

    assert service.get_current().id == second.id
    assert second.display_name == "面试准备"
    with pytest.raises(WorkspaceConflictError, match="先切换"):
        service.recycle(second.id)

    service.select(first.id)
    recycled = service.recycle(second.id)
    assert recycled.lifecycle_status == "recycled"
    assert [item.id for item in service.list_workspaces()] == [first.id]
    assert service.restore(second.id).lifecycle_status == "active"


def test_permanent_workspace_delete_preserves_vault(app_connection, tmp_path):
    service = WorkspaceService(app_connection)
    workspace = service.register(str(tmp_path / "only"), "测试空间")
    root = Path(workspace.root_path)
    (root / ".cyber-interview-agent").mkdir()
    (root / ".cyber-interview-agent" / "runtime.sqlite").write_bytes(b"")
    (root / "artifacts").mkdir()
    (root / "artifacts" / "private.txt").write_text("private")

    service.recycle(workspace.id)
    service.permanently_delete(workspace.id)

    assert service.list_workspaces(lifecycle_status=None) == []
    assert (root / "knowledge-vault").is_dir()
    assert not (root / ".cyber-interview-agent").exists()
    assert not (root / "artifacts").exists()
