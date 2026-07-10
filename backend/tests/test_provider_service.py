import sqlite3

import pytest
from pydantic import ValidationError

from app.core.errors import (
    ProviderModelInUseError,
    ProviderModelNotFoundError,
    ProviderNotFoundError,
)
from app.db.app_database import connect_app_database
from app.providers.base import (
    ERROR_MESSAGES,
    FakeProviderAdapter,
    ProviderErrorCode,
    ProviderTestResult,
)
from app.repositories.provider_repository import ProviderRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.settings import (
    CreateProviderCommand,
    CreateProviderModelCommand,
    UpdateProviderCommand,
    UpdateProviderModelCommand,
)
from app.services.provider_service import ProviderService
from app.services.secrets import (
    FakeSecretStore,
    SecretNotFoundError,
    SecretStoreUnavailableError,
)


@pytest.fixture
def app_connection(tmp_path):
    connection = connect_app_database(tmp_path)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def fake_adapter():
    return FakeProviderAdapter()


@pytest.fixture
def provider_service(app_connection, fake_adapter):
    return ProviderService(
        connection=app_connection,
        secret_stores={"keyring": FakeSecretStore(), "environment": FakeSecretStore()},
        adapters={"openai-compatible": fake_adapter, "anthropic-compatible": fake_adapter},
    )


def _seed_model(connection, provider_id, *, model_pk="model-1", model_id="model-1"):
    connection.execute(
        "INSERT INTO provider_models (id, provider_id, model_id, display_name) "
        "VALUES (?, ?, ?, 'Model 1')",
        (model_pk, provider_id, model_id),
    )


def test_provider_repository_round_trips_multiple_models(app_connection):
    repository = ProviderRepository(app_connection)
    provider = repository.create_provider(name="Local", api_format="openai-compatible", base_url="http://127.0.0.1:11434/v1", secret_source="environment", secret_ref="OLLAMA_KEY")
    first = repository.create_model(provider.id, "model-a", "Model A")
    second = repository.create_model(provider.id, "model-b", "Model B")
    loaded = repository.get_provider(provider.id)
    assert [model.model_id for model in loaded.models] == [first.model_id, second.model_id]


def test_provider_response_is_redacted(provider_service):
    created = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))
    assert created.has_secret is True
    assert not hasattr(created, "api_key")
    assert "sk-secret" not in created.model_dump_json()


@pytest.mark.asyncio
async def test_model_test_records_auth_failure(provider_service, fake_adapter, app_connection):
    provider = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))
    _seed_model(app_connection, provider.id)
    fake_adapter.next_result = ProviderTestResult(status="auth_failed", latency_ms=12, message="认证失败")
    result = await provider_service.test_model("model-1")
    assert result.connectivity_status == "auth_failed"
    assert result.last_latency_ms == 12


@pytest.mark.asyncio
async def test_test_model_records_secret_missing_when_no_key(provider_service, app_connection):
    provider = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))
    _seed_model(app_connection, provider.id)
    provider_service.secret_stores["keyring"].delete(f"provider:{provider.id}")
    result = await provider_service.test_model("model-1")
    assert result.connectivity_status == "secret_missing"


@pytest.mark.asyncio
async def test_test_model_unknown_raises(provider_service, app_connection):
    with pytest.raises(ProviderModelNotFoundError):
        await provider_service.test_model("does-not-exist")


def test_create_provider_writes_secret_before_db_and_compensates(provider_service, monkeypatch):
    keyring_store = provider_service.secret_stores["keyring"]

    def boom(*args, **kwargs):
        # secret must already be written before the DB write is attempted
        assert len(keyring_store._secrets) == 1, "secret should be written before DB write"
        raise RuntimeError("db down")

    monkeypatch.setattr(provider_service.providers, "create_provider", boom)

    with pytest.raises(RuntimeError):
        provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))

    assert keyring_store._secrets == {}, "secret must be compensated (deleted) after DB failure"


def test_create_environment_provider_saves_only_variable_name(provider_service):
    created = provider_service.create_provider(CreateProviderCommand(
        name="Env",
        api_format="openai-compatible",
        base_url="https://example.test/v1",
        secret_source="environment",
        secret_ref="MY_API_KEY",
    ))
    assert created.has_secret is True
    assert created.secret_source == "environment"
    # no secret value written to any store
    assert provider_service.secret_stores["keyring"]._secrets == {}
    assert provider_service.secret_stores["environment"]._secrets == {}
    # the variable name is stored on the provider record, not exposed via the resource
    record = provider_service.providers.get_provider(created.id)
    assert record.secret_source == "environment"
    assert record.secret_ref == "MY_API_KEY"
    assert "MY_API_KEY" not in created.model_dump_json()


def test_update_provider_resets_model_status_to_unknown(provider_service, app_connection):
    provider = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))
    app_connection.execute(
        "INSERT INTO provider_models (id, provider_id, model_id, display_name, "
        "connectivity_status, last_latency_ms, last_tested_at) "
        "VALUES ('model-1', ?, 'model-1', 'M1', 'ok', 10, '2026-01-01 00:00:00')",
        (provider.id,),
    )
    updated = provider_service.update_provider(provider.id, UpdateProviderCommand(base_url="https://changed.test/v1"))
    model = next(m for m in updated.models if m.id == "model-1")
    assert model.connectivity_status == "unknown"
    assert model.last_latency_ms is None
    assert model.last_tested_at is None


def test_delete_provider_removes_keyring_secret(provider_service):
    keyring_store = provider_service.secret_stores["keyring"]
    created = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))
    assert len(keyring_store._secrets) == 1

    provider_service.delete_provider(created.id)

    assert keyring_store._secrets == {}
    with pytest.raises(ProviderNotFoundError):
        provider_service.get_provider(created.id)


def test_delete_provider_with_bound_model_raises_in_use(provider_service, app_connection, tmp_path):
    created = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))
    _seed_model(app_connection, created.id)
    workspaces = WorkspaceRepository(app_connection)
    workspace = workspaces.register(root_path=str(tmp_path / "ws"))
    workspaces.set_model_binding(workspace.id, "answer_evaluation", "model-1")

    with pytest.raises(ProviderModelInUseError):
        provider_service.delete_provider(created.id)

    # provider and its secret are retained (consistent deletion)
    assert provider_service.providers.get_provider(created.id) is not None
    assert len(provider_service.secret_stores["keyring"]._secrets) == 1


def test_create_provider_model_returns_resource(provider_service):
    provider = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))
    model = provider_service.create_provider_model(provider.id, CreateProviderModelCommand(model_id="gpt-x", display_name="GPT X"))
    assert model.model_id == "gpt-x"
    assert model.connectivity_status == "unknown"


# --- Finding 1: missing CRUD (list providers, update/delete provider-model) ---

def test_list_providers_returns_all(app_connection):
    service = ProviderService(
        connection=app_connection,
        secret_stores={"keyring": FakeSecretStore(), "environment": FakeSecretStore()},
        adapters={"openai-compatible": FakeProviderAdapter()},
    )
    service.create_provider(CreateProviderCommand(name="A", api_format="openai-compatible", base_url="https://a.test/v1", api_key="ka"))
    service.create_provider(CreateProviderCommand(name="B", api_format="anthropic-compatible", base_url="https://b.test/v1", api_key="kb"))
    names = [p.name for p in service.list_providers()]
    assert names == ["A", "B"]


def test_delete_provider_model_raises_in_use_when_bound(provider_service, app_connection, tmp_path):
    provider = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))
    model = provider_service.create_provider_model(provider.id, CreateProviderModelCommand(model_id="m1", display_name="M1"))
    workspaces = WorkspaceRepository(app_connection)
    workspace = workspaces.register(root_path=str(tmp_path / "ws"))
    workspaces.set_model_binding(workspace.id, "answer_evaluation", model.id)

    with pytest.raises(ProviderModelInUseError):
        provider_service.delete_provider_model(model.id)

    # model still exists
    assert provider_service.providers.get_model(model.id) is not None


def test_update_provider_model_resets_status_when_model_id_changes(provider_service, app_connection):
    provider = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))
    model = provider_service.create_provider_model(provider.id, CreateProviderModelCommand(model_id="m1", display_name="M1"))
    app_connection.execute(
        "UPDATE provider_models SET connectivity_status='ok', last_latency_ms=10, "
        "last_tested_at='2026-01-01 00:00:00' WHERE id=?",
        (model.id,),
    )
    updated = provider_service.update_provider_model(
        model.id, UpdateProviderModelCommand(model_id="m2")
    )
    assert updated.model_id == "m2"
    assert updated.connectivity_status == "unknown"
    assert updated.last_latency_ms is None
    assert updated.last_tested_at is None


# --- Finding 5: base_url validation ---

def test_create_provider_rejects_ftp_base_url():
    with pytest.raises(ValidationError):
        CreateProviderCommand(name="P", api_format="openai-compatible", base_url="ftp://host/v1", api_key="k")


def test_create_provider_rejects_relative_base_url():
    with pytest.raises(ValidationError):
        CreateProviderCommand(name="P", api_format="openai-compatible", base_url="example.test/v1", api_key="k")


def test_create_provider_rejects_credentials_in_base_url():
    with pytest.raises(ValidationError):
        CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://user:pass@host/v1", api_key="k")


def test_create_provider_allows_localhost_and_private_network():
    cmd = CreateProviderCommand(name="P", api_format="openai-compatible", base_url="http://192.168.1.1:11434/v1", api_key="k")
    assert cmd.base_url == "http://192.168.1.1:11434/v1"
    cmd2 = CreateProviderCommand(name="P", api_format="openai-compatible", base_url="http://localhost:11434/v1", api_key="k")
    assert cmd2.base_url == "http://localhost:11434/v1"


def test_update_provider_command_validates_base_url():
    with pytest.raises(ValidationError):
        UpdateProviderCommand(base_url="ftp://host/v1")


# --- Finding 2: update_provider secret compensation ---

def test_update_provider_restores_old_secret_on_db_failure(provider_service, monkeypatch):
    keyring_store = provider_service.secret_stores["keyring"]
    created = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="original-secret"))
    assert keyring_store.get(f"provider:{created.id}") == "original-secret"

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("db down")

    monkeypatch.setattr(provider_service.providers, "update_provider", boom)

    with pytest.raises(sqlite3.OperationalError):
        provider_service.update_provider(created.id, UpdateProviderCommand(api_key="new-secret"))

    # old secret restored, new secret not retained
    assert keyring_store.get(f"provider:{created.id}") == "original-secret"
    assert "new-secret" not in repr(keyring_store)


def test_update_provider_deletes_new_secret_when_no_old_secret(provider_service, monkeypatch):
    keyring_store = provider_service.secret_stores["keyring"]
    created = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="original-secret"))
    # remove the old secret externally -> no old value to restore
    keyring_store.delete(f"provider:{created.id}")

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("db down")

    monkeypatch.setattr(provider_service.providers, "update_provider", boom)

    with pytest.raises(sqlite3.OperationalError):
        provider_service.update_provider(created.id, UpdateProviderCommand(api_key="new-secret"))

    # new secret compensated (deleted) since there was no old value
    with pytest.raises(SecretNotFoundError):
        keyring_store.get(f"provider:{created.id}")


# --- Finding 3: all mutating paths roll back on DB exception ---

class _CommitFailingConn:
    """Wraps a real connection but raises on commit(), to exercise rollback."""

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real

    def execute(self, *args, **kwargs):
        return self._real.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self._real.executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        return self._real.executescript(*args, **kwargs)

    @property
    def row_factory(self):
        return self._real.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._real.row_factory = value

    @property
    def in_transaction(self):
        return self._real.in_transaction

    def rollback(self):
        return self._real.rollback()

    def commit(self):
        raise sqlite3.OperationalError("commit failed")

    def close(self):
        return self._real.close()


@pytest.fixture
def failing_commit_service(tmp_path):
    real = connect_app_database(tmp_path)
    service = ProviderService(
        connection=_CommitFailingConn(real),
        secret_stores={"keyring": FakeSecretStore(), "environment": FakeSecretStore()},
        adapters={"openai-compatible": FakeProviderAdapter()},
    )
    yield service
    real.close()


def test_create_environment_provider_rolls_back_on_commit_failure(failing_commit_service):
    with pytest.raises(sqlite3.OperationalError):
        failing_commit_service.create_provider(CreateProviderCommand(
            name="Env", api_format="openai-compatible", base_url="https://example.test/v1",
            secret_source="environment", secret_ref="MY_VAR",
        ))
    # nothing persisted (commit failed -> rollback)
    real = failing_commit_service._connection._real
    assert real.execute("SELECT count(*) FROM providers").fetchone()[0] == 0


def test_create_provider_model_rolls_back_on_commit_failure(failing_commit_service, tmp_path):
    # create a provider using a separate healthy connection to the same db
    healthy = connect_app_database(tmp_path)
    try:
        healthy_service = ProviderService(
            connection=healthy,
            secret_stores={"keyring": failing_commit_service.secret_stores["keyring"], "environment": FakeSecretStore()},
            adapters={"openai-compatible": FakeProviderAdapter()},
        )
        provider = healthy_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="k"))
    finally:
        healthy.close()

    with pytest.raises(sqlite3.OperationalError):
        failing_commit_service.create_provider_model(provider.id, CreateProviderModelCommand(model_id="m1", display_name="M1"))
    real = failing_commit_service._connection._real
    assert real.execute("SELECT count(*) FROM provider_models").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_test_model_rolls_back_on_db_failure(provider_service, fake_adapter, app_connection, monkeypatch):
    provider = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))
    _seed_model(app_connection, provider.id)
    app_connection.commit()  # persist setup so service rollback only undoes its own writes
    fake_adapter.next_result = ProviderTestResult(status="ok", latency_ms=5, message="ok")

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("db down")

    monkeypatch.setattr(provider_service.providers, "record_test_run", boom)

    with pytest.raises(sqlite3.OperationalError):
        await provider_service.test_model("model-1")
    # update_model_status must be rolled back (no half-updated state)
    model = provider_service.providers.get_model("model-1")
    assert model is not None
    assert model.connectivity_status == "unknown"
    assert model.last_latency_ms is None


# --- Finding 4: delete_provider consistent ordering + compensation ---

def test_delete_provider_not_deleted_when_secret_backend_fails(app_connection, monkeypatch):
    real = app_connection
    keyring_store = FakeSecretStore()

    class _FailingDeleteStore(FakeSecretStore):
        def delete(self, ref):
            raise SecretStoreUnavailableError("keyring backend down")

    # seed the secret so get() works but delete() fails
    service = ProviderService(
        connection=real,
        secret_stores={"keyring": _FailingDeleteStore(), "environment": FakeSecretStore()},
        adapters={"openai-compatible": FakeProviderAdapter()},
    )
    created = service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))

    with pytest.raises(SecretStoreUnavailableError):
        service.delete_provider(created.id)

    # provider NOT deleted because secret deletion failed first
    assert service.providers.get_provider(created.id) is not None


def test_delete_provider_restores_secret_on_db_failure(provider_service, monkeypatch):
    keyring_store = provider_service.secret_stores["keyring"]
    created = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))
    assert keyring_store.get(f"provider:{created.id}") == "sk-secret"

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("db down")

    monkeypatch.setattr(provider_service.providers, "delete_provider", boom)

    with pytest.raises(sqlite3.OperationalError):
        provider_service.delete_provider(created.id)

    # secret restored (DB delete failed) and provider still exists
    assert keyring_store.get(f"provider:{created.id}") == "sk-secret"
    assert provider_service.providers.get_provider(created.id) is not None


def test_update_provider_without_api_key_preserves_secret_on_db_failure(
    provider_service, monkeypatch
):
    keyring_store = provider_service.secret_stores["keyring"]
    created = provider_service.create_provider(
        CreateProviderCommand(
            name="P",
            api_format="openai-compatible",
            base_url="https://example.test/v1",
            api_key="original-secret",
        )
    )

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("db down")

    monkeypatch.setattr(provider_service.providers, "update_provider", boom)

    with pytest.raises(sqlite3.OperationalError):
        provider_service.update_provider(created.id, UpdateProviderCommand(name="Renamed"))

    assert keyring_store.get(f"provider:{created.id}") == "original-secret"


@pytest.mark.asyncio
async def test_model_test_persists_only_canonical_redacted_message(
    provider_service, fake_adapter, app_connection
):
    provider = provider_service.create_provider(
        CreateProviderCommand(
            name="P",
            api_format="openai-compatible",
            base_url="https://example.test/v1",
            api_key="sk-secret",
        )
    )
    _seed_model(app_connection, provider.id)
    fake_adapter.next_result = ProviderTestResult(
        status="auth_failed",
        latency_ms=12,
        message="backend echoed sk-secret",
    )

    await provider_service.test_model("model-1")

    message = app_connection.execute(
        "SELECT message FROM provider_test_runs ORDER BY rowid DESC LIMIT 1"
    ).fetchone()["message"]
    assert message == ERROR_MESSAGES[ProviderErrorCode.AUTH_FAILED]
    assert "sk-secret" not in message


def test_provider_commands_reject_empty_embedded_username():
    with pytest.raises(ValidationError):
        CreateProviderCommand(
            name="P",
            api_format="openai-compatible",
            base_url="https://@host/v1",
            api_key="k",
        )
    with pytest.raises(ValidationError):
        UpdateProviderCommand(base_url="https://@host/v1")
