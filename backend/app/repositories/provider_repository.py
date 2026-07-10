import sqlite3
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderModelRecord:
    id: str
    provider_id: str
    model_id: str
    display_name: str
    enabled: bool
    connectivity_status: str
    last_tested_at: str | None
    last_error_code: str | None
    last_latency_ms: int | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ProviderRecord:
    id: str
    name: str
    api_format: str
    base_url: str
    secret_source: str
    secret_ref: str
    enabled: bool
    created_at: str
    updated_at: str
    models: tuple[ProviderModelRecord, ...] = ()


_PROVIDER_COLUMNS = (
    "id, name, api_format, base_url, secret_source, secret_ref, "
    "enabled, created_at, updated_at"
)
_MODEL_COLUMNS = (
    "id, provider_id, model_id, display_name, enabled, connectivity_status, "
    "last_tested_at, last_error_code, last_latency_ms, created_at, updated_at"
)


class ProviderRepository:
    """Persists providers and their models.

    Executes parameterized SQL only; never commits (the service owns the
    transaction boundary) and never reads the SecretStore.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create_provider(
        self,
        *,
        name: str,
        api_format: str,
        base_url: str,
        secret_source: str,
        secret_ref: str,
        enabled: bool = True,
        provider_id: str | None = None,
    ) -> ProviderRecord:
        provider_id = provider_id or str(uuid.uuid4())
        self._connection.execute(
            "INSERT INTO providers (id, name, api_format, base_url, "
            "secret_source, secret_ref, enabled) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                provider_id,
                name,
                api_format,
                base_url,
                secret_source,
                secret_ref,
                1 if enabled else 0,
            ),
        )
        return self._require_provider(provider_id)

    def get_provider(self, provider_id: str) -> ProviderRecord | None:
        row = self._connection.execute(
            f"SELECT {_PROVIDER_COLUMNS} FROM providers WHERE id = ?",
            (provider_id,),
        ).fetchone()
        if row is None:
            return None
        return self._provider_from_row(row)

    def create_model(
        self,
        provider_id: str,
        model_id: str,
        display_name: str,
        enabled: bool = True,
    ) -> ProviderModelRecord:
        model_pk = str(uuid.uuid4())
        self._connection.execute(
            "INSERT INTO provider_models (id, provider_id, model_id, "
            "display_name, enabled) VALUES (?, ?, ?, ?, ?)",
            (model_pk, provider_id, model_id, display_name, 1 if enabled else 0),
        )
        return self._require_model(model_pk)

    def delete_model(self, model_id: str) -> None:
        """Delete a provider model by its internal stable id.

        Raises sqlite3.IntegrityError when the model is still bound to a
        workspace (ON DELETE RESTRICT); the service translates that to 409.
        """
        self._connection.execute(
            "DELETE FROM provider_models WHERE id = ?", (model_id,)
        )

    def get_model(self, model_id: str) -> ProviderModelRecord | None:
        row = self._connection.execute(
            f"SELECT {_MODEL_COLUMNS} FROM provider_models WHERE id = ?",
            (model_id,),
        ).fetchone()
        if row is None:
            return None
        return self._model_from_row(row)

    def update_model_status(
        self,
        model_id: str,
        *,
        connectivity_status: str,
        latency_ms: int | None,
        error_code: str | None,
    ) -> ProviderModelRecord:
        self._connection.execute(
            "UPDATE provider_models SET connectivity_status = ?, "
            "last_latency_ms = ?, last_error_code = ?, "
            "last_tested_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (connectivity_status, latency_ms, error_code, model_id),
        )
        return self._require_model(model_id)

    def record_test_run(
        self,
        model_id: str,
        *,
        status: str,
        latency_ms: int | None,
        error_code: str | None,
        message: str,
    ) -> None:
        run_id = str(uuid.uuid4())
        self._connection.execute(
            "INSERT INTO provider_test_runs "
            "(id, provider_model_id, status, latency_ms, error_code, message) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, model_id, status, latency_ms, error_code, message),
        )

    def update_provider(
        self,
        provider_id: str,
        *,
        name: str,
        api_format: str,
        base_url: str,
    ) -> ProviderRecord:
        self._connection.execute(
            "UPDATE providers SET name = ?, api_format = ?, base_url = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (name, api_format, base_url, provider_id),
        )
        return self._require_provider(provider_id)

    def delete_provider(self, provider_id: str) -> None:
        """Delete a provider. Raises sqlite3.IntegrityError when a bound model
        exists (ON DELETE RESTRICT via workspace_model_bindings)."""
        self._connection.execute(
            "DELETE FROM providers WHERE id = ?", (provider_id,)
        )

    def reset_model_statuses(self, provider_id: str) -> None:
        self._connection.execute(
            "UPDATE provider_models SET connectivity_status = 'unknown', "
            "last_tested_at = NULL, last_error_code = NULL, last_latency_ms = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE provider_id = ?",
            (provider_id,),
        )

    def reset_model_status(self, model_id: str) -> None:
        self._connection.execute(
            "UPDATE provider_models SET connectivity_status = 'unknown', "
            "last_tested_at = NULL, last_error_code = NULL, last_latency_ms = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (model_id,),
        )

    def list_providers(self) -> list[ProviderRecord]:
        rows = self._connection.execute(
            f"SELECT {_PROVIDER_COLUMNS} FROM providers ORDER BY rowid"
        ).fetchall()
        return [self._provider_from_row(row) for row in rows]

    def update_model(
        self,
        model_id: str,
        *,
        real_model_id: str,
        display_name: str,
        enabled: bool,
    ) -> ProviderModelRecord:
        self._connection.execute(
            "UPDATE provider_models SET model_id = ?, display_name = ?, "
            "enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (real_model_id, display_name, 1 if enabled else 0, model_id),
        )
        return self._require_model(model_id)

    def provider_has_bound_models(self, provider_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM workspace_model_bindings b "
            "JOIN provider_models m ON m.id = b.provider_model_id "
            "WHERE m.provider_id = ? LIMIT 1",
            (provider_id,),
        ).fetchone()
        return row is not None

    def list_model_bindings(
        self, model_id: str
    ) -> tuple[tuple[str, str], ...]:
        rows = self._connection.execute(
            "SELECT workspace_id, role FROM workspace_model_bindings "
            "WHERE provider_model_id = ? ORDER BY workspace_id, role",
            (model_id,),
        ).fetchall()
        return tuple((row["workspace_id"], row["role"]) for row in rows)

    def list_provider_bindings(
        self, provider_id: str
    ) -> tuple[tuple[str, str], ...]:
        rows = self._connection.execute(
            "SELECT b.workspace_id, b.role FROM workspace_model_bindings b "
            "JOIN provider_models m ON m.id = b.provider_model_id "
            "WHERE m.provider_id = ? ORDER BY b.workspace_id, b.role",
            (provider_id,),
        ).fetchall()
        return tuple((row["workspace_id"], row["role"]) for row in rows)

    def _require_provider(self, provider_id: str) -> ProviderRecord:
        record = self.get_provider(provider_id)
        if record is None:
            raise LookupError(f"provider {provider_id!r} not found")
        return record

    def _require_model(self, model_pk: str) -> ProviderModelRecord:
        row = self._connection.execute(
            f"SELECT {_MODEL_COLUMNS} FROM provider_models WHERE id = ?",
            (model_pk,),
        ).fetchone()
        if row is None:
            raise LookupError(f"provider model {model_pk!r} not found")
        return self._model_from_row(row)

    def _provider_from_row(self, row: sqlite3.Row) -> ProviderRecord:
        return ProviderRecord(
            id=row["id"],
            name=row["name"],
            api_format=row["api_format"],
            base_url=row["base_url"],
            secret_source=row["secret_source"],
            secret_ref=row["secret_ref"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            models=self._list_models(row["id"]),
        )

    def _list_models(self, provider_id: str) -> tuple[ProviderModelRecord, ...]:
        rows = self._connection.execute(
            f"SELECT {_MODEL_COLUMNS} FROM provider_models WHERE provider_id = ? "
            "ORDER BY rowid",
            (provider_id,),
        ).fetchall()
        return tuple(self._model_from_row(row) for row in rows)

    def _model_from_row(self, row: sqlite3.Row) -> ProviderModelRecord:
        return ProviderModelRecord(
            id=row["id"],
            provider_id=row["provider_id"],
            model_id=row["model_id"],
            display_name=row["display_name"],
            enabled=bool(row["enabled"]),
            connectivity_status=row["connectivity_status"],
            last_tested_at=row["last_tested_at"],
            last_error_code=row["last_error_code"],
            last_latency_ms=row["last_latency_ms"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
