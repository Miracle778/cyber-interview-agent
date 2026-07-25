import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.core.errors import (
    ProviderModelNotFoundError,
    WorkspaceBindingError,
    WorkspaceBusyError,
    WorkspaceConflictError,
    WorkspaceNotFoundError,
)
from app.infrastructure.runtime_database import runtime_database_path
from app.repositories.provider_repository import ProviderRepository
from app.repositories.workspace_repository import WorkspaceRecord, WorkspaceRepository
from app.schemas.settings import (
    MODEL_ROLES,
    WorkspaceDeletionImpactResource,
    WorkspaceModelBindingsResource,
    WorkspaceResource,
)
from app.services.vault import initialize_vault
from app.services.workspace import WorkspaceError, resolve_workspace


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

    def register(
        self, root_path: str, display_name: str | None = None
    ) -> WorkspaceResource:
        root = resolve_workspace(root_path)
        initialize_vault(root)
        resolved_name = (display_name or root.name or str(root)).strip()
        if not resolved_name:
            raise WorkspaceConflictError("请输入工作区名称")
        with self._transaction():
            record = self.workspaces.get_by_root_path(str(root))
            if record is None:
                record = self.workspaces.register(
                    root_path=str(root), display_name=resolved_name
                )
            else:
                record = self.workspaces.update_available(record.id, True)
                if record.lifecycle_status == "recycled":
                    record = self.workspaces.restore(record.id)
                if not record.display_name:
                    record = self.workspaces.rename(record.id, resolved_name)
            self.workspaces.select(record.id)
        return self._to_resource(record)

    def list_workspaces(
        self, *, lifecycle_status: str | None = "active"
    ) -> list[WorkspaceResource]:
        if lifecycle_status not in {"active", "recycled", None}:
            raise WorkspaceConflictError("不支持的工作区状态")
        return [
            self._to_resource(record)
            for record in self.workspaces.list_workspaces(
                lifecycle_status=lifecycle_status
            )
        ]

    def get_current(self) -> WorkspaceResource | None:
        record = self.workspaces.get_current()
        return None if record is None else self._to_resource(record)

    def resolve_root(self, workspace_id: str) -> Path:
        record = self._require_workspace(workspace_id)
        if record.lifecycle_status != "active":
            raise WorkspaceNotFoundError(workspace_id)
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

    def update(
        self,
        workspace_id: str,
        *,
        available: bool | None = None,
        display_name: str | None = None,
    ) -> WorkspaceResource:
        self._require_workspace(workspace_id)
        resource: WorkspaceResource | None = None
        if display_name is not None:
            resource = self.rename(workspace_id, display_name)
        if available is not None:
            return self.update_available(workspace_id, available)
        return resource or self._to_resource(self._require_workspace(workspace_id))

    def select(self, workspace_id: str) -> WorkspaceResource:
        record = self._require_workspace(workspace_id)
        if record.lifecycle_status != "active":
            raise WorkspaceConflictError("回收站中的工作区不能切换，请先恢复")
        if not record.available or not Path(record.root_path).is_dir():
            raise WorkspaceConflictError("工作区路径不可用，请先重新关联")
        with self._transaction():
            record = self.workspaces.select(workspace_id)
        return self._to_resource(record)

    def rename(self, workspace_id: str, display_name: str) -> WorkspaceResource:
        name = display_name.strip()
        if not name:
            raise WorkspaceConflictError("工作区名称不能为空")
        if len(name) > 80:
            raise WorkspaceConflictError("工作区名称不能超过 80 个字符")
        self._require_workspace(workspace_id)
        with self._transaction():
            record = self.workspaces.rename(workspace_id, name)
        return self._to_resource(record)

    def recycle(self, workspace_id: str) -> WorkspaceResource:
        record = self._require_workspace(workspace_id)
        if record.lifecycle_status == "recycled":
            return self._to_resource(record)
        if self.active_execution_count(workspace_id):
            raise WorkspaceBusyError("工作区仍有任务运行，请先暂停或终止")
        current = self.workspaces.get_current()
        other_active = [
            item
            for item in self.workspaces.list_workspaces(lifecycle_status="active")
            if item.id != workspace_id
        ]
        if current is not None and current.id == workspace_id and other_active:
            raise WorkspaceConflictError("请先切换到其他工作区，再删除当前工作区")
        with self._transaction():
            record = self.workspaces.recycle(workspace_id)
        return self._to_resource(record)

    def restore(self, workspace_id: str) -> WorkspaceResource:
        record = self._require_workspace(workspace_id)
        if record.lifecycle_status == "active":
            return self._to_resource(record)
        with self._transaction():
            record = self.workspaces.restore(workspace_id)
            if self.workspaces.get_current() is None:
                self.workspaces.select(workspace_id)
        return self._to_resource(record)

    def deletion_impact(self, workspace_id: str) -> WorkspaceDeletionImpactResource:
        record = self._require_workspace(workspace_id)
        counts = self._runtime_counts(Path(record.root_path), record.id)
        return WorkspaceDeletionImpactResource(
            workspace_id=record.id,
            display_name=record.display_name or Path(record.root_path).name,
            active_execution_count=counts["active_executions"],
            session_count=counts["sessions"],
            material_count=counts["materials"],
            question_count=counts["questions"],
            job_target_count=counts["job_targets"],
        )

    def permanently_delete(self, workspace_id: str) -> None:
        record = self._require_workspace(workspace_id)
        if record.lifecycle_status != "recycled":
            raise WorkspaceConflictError("请先将工作区移入回收站")
        if self.active_execution_count(workspace_id):
            raise WorkspaceBusyError("工作区仍有任务运行，暂时不能永久删除")
        root = Path(record.root_path)
        self._validate_application_files(root)
        self._delete_application_files(root)
        with self._transaction():
            self.workspaces.delete(workspace_id)

    def active_execution_count(self, workspace_id: str) -> int:
        record = self._require_workspace(workspace_id)
        return self._runtime_counts(Path(record.root_path), record.id)[
            "active_executions"
        ]

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
            raise WorkspaceBindingError("请为全部 8 种任务分配模型")

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

    def _to_resource(self, record: WorkspaceRecord) -> WorkspaceResource:
        root = Path(record.root_path)
        current = self.workspaces.get_current()
        return WorkspaceResource(
            id=record.id,
            root_path=record.root_path,
            display_name=record.display_name or root.name or record.root_path,
            vault_path=str((root / "knowledge-vault").resolve()),
            available=record.available and root.is_dir(),
            lifecycle_status=record.lifecycle_status,
            is_current=current is not None and current.id == record.id,
            recycled_at=record.recycled_at,
            active_execution_count=self.active_execution_count(record.id),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _runtime_counts(root: Path, workspace_id: str) -> dict[str, int]:
        result = {
            "active_executions": 0,
            "sessions": 0,
            "materials": 0,
            "questions": 0,
            "job_targets": 0,
        }
        database = runtime_database_path(root)
        if not database.is_file():
            return result
        connection = sqlite3.connect(
            f"file:{database.as_posix()}?mode=ro",
            uri=True,
            timeout=1,
        )
        try:
            queries = {
                "active_executions": (
                    "SELECT COUNT(*) FROM agent_runs r "
                    "JOIN agent_sessions s ON s.id = r.session_id "
                    "WHERE s.workspace_id = ? "
                    "AND r.status IN ('queued', 'running', 'waiting_for_approval')"
                ),
                "sessions": "SELECT COUNT(*) FROM agent_sessions WHERE workspace_id = ?",
                "materials": "SELECT COUNT(*) FROM profile_materials WHERE workspace_id = ?",
                "questions": "SELECT COUNT(*) FROM review_question_catalog WHERE workspace_id = ?",
                "job_targets": "SELECT COUNT(*) FROM job_targets WHERE workspace_id = ?",
            }
            for key, query in queries.items():
                try:
                    row = connection.execute(query, (workspace_id,)).fetchone()
                except sqlite3.OperationalError:
                    continue
                result[key] = int(row[0]) if row else 0
        finally:
            connection.close()
        return result

    @staticmethod
    def _delete_application_files(root: Path) -> None:
        for child_name in (".cyber-interview-agent", "artifacts"):
            target = root / child_name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()

    @staticmethod
    def _validate_application_files(root: Path) -> None:
        for child_name in (".cyber-interview-agent", "artifacts"):
            if (root / child_name).is_symlink():
                raise WorkspaceConflictError(
                    f"应用数据目录 {child_name} 是符号链接，已停止删除"
                )
