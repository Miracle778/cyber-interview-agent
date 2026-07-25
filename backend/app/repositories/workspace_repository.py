import sqlite3
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceRecord:
    id: str
    root_path: str
    display_name: str
    available: bool
    lifecycle_status: str
    recycled_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkspaceModelBindingRecord:
    workspace_id: str
    role: str
    provider_model_id: str
    created_at: str
    updated_at: str


_WORKSPACE_COLUMNS = (
    "id, root_path, display_name, available, lifecycle_status, recycled_at, "
    "created_at, updated_at"
)
_BINDING_COLUMNS = (
    "workspace_id, role, provider_model_id, created_at, updated_at"
)


class WorkspaceRepository:
    """Persists workspace registry entries and model-role bindings.

    Executes parameterized SQL only; never commits (the service owns the
    transaction boundary) and never reads the SecretStore.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def register(
        self,
        *,
        root_path: str,
        display_name: str = "",
        available: bool = True,
    ) -> WorkspaceRecord:
        workspace_id = str(uuid.uuid4())
        self._connection.execute(
            "INSERT INTO workspaces "
            "(id, root_path, display_name, available) VALUES (?, ?, ?, ?)",
            (workspace_id, root_path, display_name, 1 if available else 0),
        )
        return self._require_workspace(workspace_id)

    def get(self, workspace_id: str) -> WorkspaceRecord | None:
        row = self._connection.execute(
            f"SELECT {_WORKSPACE_COLUMNS} FROM workspaces WHERE id = ?",
            (workspace_id,),
        ).fetchone()
        if row is None:
            return None
        return self._workspace_from_row(row)

    def get_by_root_path(self, root_path: str) -> WorkspaceRecord | None:
        row = self._connection.execute(
            f"SELECT {_WORKSPACE_COLUMNS} FROM workspaces WHERE root_path = ?",
            (root_path,),
        ).fetchone()
        return None if row is None else self._workspace_from_row(row)

    def get_current(self) -> WorkspaceRecord | None:
        row = self._connection.execute(
            f"SELECT {_WORKSPACE_COLUMNS} FROM workspaces "
            "WHERE id = (SELECT current_workspace_id FROM workspace_preferences "
            "WHERE singleton_id = 1) AND lifecycle_status = 'active'"
        ).fetchone()
        return None if row is None else self._workspace_from_row(row)

    def list_workspaces(
        self, *, lifecycle_status: str | None = None
    ) -> tuple[WorkspaceRecord, ...]:
        where = ""
        parameters: tuple[str, ...] = ()
        if lifecycle_status is not None:
            where = " WHERE lifecycle_status = ?"
            parameters = (lifecycle_status,)
        rows = self._connection.execute(
            f"SELECT {_WORKSPACE_COLUMNS} FROM workspaces{where} "
            "ORDER BY updated_at DESC, rowid DESC",
            parameters,
        ).fetchall()
        return tuple(self._workspace_from_row(row) for row in rows)

    def select(self, workspace_id: str) -> WorkspaceRecord:
        self._connection.execute(
            "INSERT INTO workspace_preferences "
            "(singleton_id, current_workspace_id, updated_at) "
            "VALUES (1, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(singleton_id) DO UPDATE SET "
            "current_workspace_id = excluded.current_workspace_id, "
            "updated_at = CURRENT_TIMESTAMP",
            (workspace_id,),
        )
        return self._require_workspace(workspace_id)

    def rename(self, workspace_id: str, display_name: str) -> WorkspaceRecord:
        self._connection.execute(
            "UPDATE workspaces SET display_name = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (display_name, workspace_id),
        )
        return self._require_workspace(workspace_id)

    def recycle(self, workspace_id: str) -> WorkspaceRecord:
        self._connection.execute(
            "UPDATE workspaces SET lifecycle_status = 'recycled', "
            "recycled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (workspace_id,),
        )
        self._connection.execute(
            "UPDATE workspace_preferences SET current_workspace_id = NULL, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE singleton_id = 1 AND current_workspace_id = ?",
            (workspace_id,),
        )
        return self._require_workspace(workspace_id)

    def restore(self, workspace_id: str) -> WorkspaceRecord:
        self._connection.execute(
            "UPDATE workspaces SET lifecycle_status = 'active', recycled_at = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (workspace_id,),
        )
        return self._require_workspace(workspace_id)

    def delete(self, workspace_id: str) -> None:
        self._connection.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))

    def relink(self, workspace_id: str, root_path: str) -> WorkspaceRecord:
        self._connection.execute(
            "UPDATE workspaces SET root_path = ?, available = 1, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (root_path, workspace_id),
        )
        return self._require_workspace(workspace_id)

    def update_available(
        self, workspace_id: str, available: bool
    ) -> WorkspaceRecord:
        self._connection.execute(
            "UPDATE workspaces SET available = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (1 if available else 0, workspace_id),
        )
        return self._require_workspace(workspace_id)

    def set_model_binding(
        self,
        workspace_id: str,
        role: str,
        provider_model_id: str,
    ) -> WorkspaceModelBindingRecord:
        self._connection.execute(
            "INSERT INTO workspace_model_bindings "
            "(workspace_id, role, provider_model_id) VALUES (?, ?, ?) "
            "ON CONFLICT(workspace_id, role) DO UPDATE SET "
            "provider_model_id = excluded.provider_model_id, "
            "updated_at = CURRENT_TIMESTAMP",
            (workspace_id, role, provider_model_id),
        )
        return self._require_binding(workspace_id, role)

    def get_model_bindings(
        self, workspace_id: str
    ) -> tuple[WorkspaceModelBindingRecord, ...]:
        rows = self._connection.execute(
            f"SELECT {_BINDING_COLUMNS} FROM workspace_model_bindings "
            "WHERE workspace_id = ? ORDER BY rowid",
            (workspace_id,),
        ).fetchall()
        return tuple(self._binding_from_row(row) for row in rows)

    def _require_workspace(self, workspace_id: str) -> WorkspaceRecord:
        record = self.get(workspace_id)
        if record is None:
            raise LookupError(f"workspace {workspace_id!r} not found")
        return record

    def _require_binding(
        self, workspace_id: str, role: str
    ) -> WorkspaceModelBindingRecord:
        row = self._connection.execute(
            f"SELECT {_BINDING_COLUMNS} FROM workspace_model_bindings "
            "WHERE workspace_id = ? AND role = ?",
            (workspace_id, role),
        ).fetchone()
        if row is None:
            raise LookupError(
                f"binding for workspace {workspace_id!r} role {role!r} not found"
            )
        return self._binding_from_row(row)

    def _workspace_from_row(self, row: sqlite3.Row) -> WorkspaceRecord:
        return WorkspaceRecord(
            id=row["id"],
            root_path=row["root_path"],
            display_name=row["display_name"],
            available=bool(row["available"]),
            lifecycle_status=row["lifecycle_status"],
            recycled_at=row["recycled_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _binding_from_row(self, row: sqlite3.Row) -> WorkspaceModelBindingRecord:
        return WorkspaceModelBindingRecord(
            workspace_id=row["workspace_id"],
            role=row["role"],
            provider_model_id=row["provider_model_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
