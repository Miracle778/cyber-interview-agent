import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.core.errors import (
    ProviderModelNotFoundError,
    WorkspaceBindingError,
    WorkspaceNotFoundError,
)
from app.repositories.provider_repository import ProviderRepository
from app.repositories.workspace_repository import WorkspaceRecord, WorkspaceRepository
from app.schemas.settings import (
    MODEL_ROLES,
    WorkspaceModelBindingsResource,
    WorkspaceResource,
)
from app.services.vault import initialize_vault
from app.services.workspace import resolve_workspace


class WorkspaceService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self.workspaces = WorkspaceRepository(connection)
        self.providers = ProviderRepository(connection)

    @contextmanager
    def _transaction(self):
        try:
            yield
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def register(self, root_path: str) -> WorkspaceResource:
        root = resolve_workspace(root_path)
        initialize_vault(root)
        with self._transaction():
            record = self.workspaces.get_by_root_path(str(root))
            if record is None:
                record = self.workspaces.register(root_path=str(root))
            else:
                record = self.workspaces.update_available(record.id, True)
        return self._to_resource(record)

    def list_workspaces(self) -> list[WorkspaceResource]:
        return [self._to_resource(record) for record in self.workspaces.list_workspaces()]

    def get_current(self) -> WorkspaceResource | None:
        record = self.workspaces.get_current()
        return None if record is None else self._to_resource(record)

    def resolve_root(self, workspace_id: str) -> Path:
        record = self._require_workspace(workspace_id)
        root = Path(record.root_path)
        if not record.available or not root.is_dir():
            raise WorkspaceError("Workspace 路径不可用，请重新关联")
        return root

    def update_available(
        self, workspace_id: str, available: bool
    ) -> WorkspaceResource:
        self._require_workspace(workspace_id)
        with self._transaction():
            record = self.workspaces.update_available(workspace_id, available)
        return self._to_resource(record)

    def relink(self, workspace_id: str, root_path: str) -> WorkspaceResource:
        self._require_workspace(workspace_id)
        root = resolve_workspace(root_path)
        initialize_vault(root)
        with self._transaction():
            record = self.workspaces.relink(workspace_id, str(root))
        return self._to_resource(record)

    def get_model_bindings(
        self, workspace_id: str
    ) -> WorkspaceModelBindingsResource:
        self._require_workspace(workspace_id)
        records = self.workspaces.get_model_bindings(workspace_id)
        return WorkspaceModelBindingsResource(
            workspace_id=workspace_id,
            bindings={record.role: record.provider_model_id for record in records},
        )

    def replace_model_bindings(
        self, workspace_id: str, bindings: dict[str, str]
    ) -> WorkspaceModelBindingsResource:
        self._require_workspace(workspace_id)
        if set(bindings) != MODEL_ROLES:
            raise WorkspaceBindingError("all four model roles are required")

        for model_id in bindings.values():
            model = self.providers.get_model(model_id)
            if model is None:
                raise ProviderModelNotFoundError(model_id)
            provider = self.providers.get_provider(model.provider_id)
            if not model.enabled or provider is None or not provider.enabled:
                raise WorkspaceBindingError("bindings require enabled provider models")
            if not provider.secret_ref:
                raise WorkspaceBindingError("bindings require configured provider secrets")

        with self._transaction():
            for role, model_id in bindings.items():
                self.workspaces.set_model_binding(workspace_id, role, model_id)
        return self.get_model_bindings(workspace_id)

    def _require_workspace(self, workspace_id: str) -> WorkspaceRecord:
        record = self.workspaces.get(workspace_id)
        if record is None:
            raise WorkspaceNotFoundError(workspace_id)
        return record

    @staticmethod
    def _to_resource(record: WorkspaceRecord) -> WorkspaceResource:
        root = Path(record.root_path)
        return WorkspaceResource(
            id=record.id,
            root_path=record.root_path,
            vault_path=str((root / "knowledge-vault").resolve()),
            available=record.available and root.is_dir(),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
