from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.application.session_service import (
    ProductRepository,
    SessionBusyError,
)
from app.profile.models import (
    CreateMaterialCommand,
    ProfileMaterialRecord,
    ProfileMaterialVersionRecord,
)
from app.profile.repository import ProfileRepository
from app.profile.storage import MaterialStorage

_ACTIVE_EXECUTION_STATUSES = frozenset(
    {"queued", "running", "waiting_for_input", "waiting_for_approval"}
)


@dataclass(frozen=True, slots=True)
class MaterialUploadResult:
    material: ProfileMaterialRecord
    version: ProfileMaterialVersionRecord
    execution_id: str
    session_id: str


class ProfileService:
    """Owns the material lifecycle and the hidden ``profile.ingest`` system
    sessions. Reuses the shared Runtime session/execution infrastructure; it
    never creates user-visible upload messages and never opens a second
    database handle."""

    def __init__(
        self,
        *,
        workspace_id: str,
        root: Path,
        repository: ProfileRepository,
        storage: MaterialStorage,
        product_repository: ProductRepository,
    ) -> None:
        self.workspace_id = workspace_id
        self.root = root
        self.repository = repository
        self.storage = storage
        self.product_repository = product_repository
        self.connection: sqlite3.Connection = repository._connection  # type: ignore[attr-defined]

    def upload_material(
        self,
        *,
        file_name: str,
        content: bytes,
        title: str,
        primary_role: str = "resume",
    ) -> MaterialUploadResult:
        stored = self.storage.persist_upload(file_name=file_name, content=content)
        material = self.repository.create_material(
            CreateMaterialCommand(
                workspace_id=self.workspace_id,
                type="resume",
                title=title,
                primary_role=primary_role,
            )
        )
        version = self.repository.add_material_version(
            material_id=material.id,
            source_type="upload",
            file_name=file_name,
            mime_type=stored.mime_type,
            content_sha256=stored.content_sha256,
            storage_ref=stored.storage_ref,
            text_ref="",
        )
        execution_id = self._start_ingest_execution(material.id, version, file_name)
        return MaterialUploadResult(
            material=material,
            version=version,
            execution_id=execution_id,
            session_id=version.id,
        )

    def add_material_version(
        self, *, material_id: str, file_name: str, content: bytes
    ) -> MaterialUploadResult:
        stored = self.storage.persist_upload(file_name=file_name, content=content)
        material = self.repository.get_material(material_id)
        version = self.repository.add_material_version(
            material_id=material.id,
            source_type="upload",
            file_name=file_name,
            mime_type=stored.mime_type,
            content_sha256=stored.content_sha256,
            storage_ref=stored.storage_ref,
            text_ref="",
        )
        execution_id = self._start_ingest_execution(material.id, version, file_name)
        return MaterialUploadResult(
            material=material,
            version=version,
            execution_id=execution_id,
            session_id=version.id,
        )

    def _start_ingest_execution(
        self,
        material_id: str,
        version: ProfileMaterialVersionRecord,
        file_name: str,
    ) -> str:
        # Hidden system session id == material version id. It never appears in
        # generic session lists/detail and stores no user chat messages.
        self.product_repository.create_session(
            workspace_id=self.workspace_id,
            kind="profile.ingest",
            title=f"ingest:{version.id}",
            session_id=version.id,
            visibility="system",
        )
        # Execution input carries IDs/locators only (no source content).
        execution = self.product_repository.create_execution(
            version.id,
            input={
                "materialId": material_id,
                "versionId": version.id,
                "storageRef": version.storage_ref,
                "mimeType": version.mime_type,
                "fileName": file_name,
            },
            model_bindings={},
            configuration={},
        )
        return execution.id

    def retry_version_ingest(self, version_id: str) -> object:
        version = self.repository.get_material_version(version_id)
        latest = self.product_repository.latest_execution(version_id)
        if latest is not None and latest.status in _ACTIVE_EXECUTION_STATUSES:
            raise SessionBusyError("该材料版本仍有进行中的摄入任务，请稍后重试")
        self.repository.set_version_processing_status(version_id, "parsing")
        execution = self.product_repository.create_execution(
            version_id,
            input={
                "materialId": version.material_id,
                "versionId": version.id,
                "storageRef": version.storage_ref,
                "mimeType": version.mime_type,
                "fileName": version.file_name,
                "retry": True,
            },
            model_bindings={},
            configuration={},
        )
        return execution

    def record_ingest_failure(
        self, version_id: str, *, processing_status: str, error_code: str
    ) -> None:
        self.repository.set_version_processing_status(version_id, processing_status)
        latest = self.product_repository.latest_execution(version_id)
        if latest is not None and latest.status in _ACTIVE_EXECUTION_STATUSES:
            self.product_repository.transition_execution(
                latest.id,
                expected=tuple(_ACTIVE_EXECUTION_STATUSES),
                target="failed",
                error_code=error_code,
            )

    def record_ingest_success(self, version_id: str) -> None:
        self.repository.set_version_processing_status(version_id, "ready")
        latest = self.product_repository.latest_execution(version_id)
        if latest is not None and latest.status in _ACTIVE_EXECUTION_STATUSES:
            self.product_repository.transition_execution(
                latest.id,
                expected=tuple(_ACTIVE_EXECUTION_STATUSES),
                target="completed",
            )

    def archive_material(self, material_id: str) -> ProfileMaterialRecord:
        return self.repository.archive_material(material_id)

    def restore_material(self, material_id: str) -> ProfileMaterialRecord:
        return self.repository.restore_material(material_id)

    def set_primary_version(
        self, material_id: str, version_id: str
    ) -> ProfileMaterialRecord:
        return self.repository.set_primary_version(material_id, version_id)
