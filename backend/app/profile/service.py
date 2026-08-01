from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.application.session_service import (
    ProductRepository,
    SessionBusyError,
)
from app.profile.models import (
    AppendConfirmedClaimCommand,
    BatchClaimDecisionResult,
    ClaimReviewDetail,
    ClaimReviewSnapshot,
    ConfirmedProfileContext,
    ConfirmedProfileContextItem,
    CreateActionPlanCommand,
    CreateClaimProposalSpec,
    CreateMaterialCommand,
    CreatePublicationSelectionCommand,
    DecideProposalCommand,
    DeletionItemReceipt,
    EvidenceRecord,
    MaterialDeletionPlanRecord,
    MaterialDeletionResult,
    ProfileMaterialRecord,
    ProfileMaterialVersionRecord,
    ProfileActionPlanRecord,
    ProfileAssessmentRecord,
    ProfileClaimVersionRecord,
    ProfileRelationSpec,
    SaveAssessmentCommand,
    UpdateProfilePresentationCommand,
)
from app.profile.projection import (
    UnifiedProfile,
    project_unified_profile,
    validate_profile_value,
)
from app.profile.repository import ProfileRepository
from app.profile.privacy import redact_profile_text
from app.profile.storage import MaterialStorage
from app.profile.errors import (
    ProfileActionPlanInvalid,
    ProfileActionPlanNotFound,
    ProfileAssessmentNotFound,
    ProfileClaimNotFound,
    ProfileClaimVersionConflict,
    ProfileContextRequestInvalid,
    ProfileDomainError,
    ProfileDeletionPlanConflict,
    ProfileDeletionPlanExpired,
    ProfileDocumentNotReady,
    ProfileMaterialNotFound,
    ProfileMaterialVersionHasPendingProposals,
    ProfileMaterialVersionConflict,
    ProfileProposalNotFound,
    ProfilePublicationRevocationRequired,
    ProfilePublicationRevocationUnavailable,
    ProfileValueInvalid,
)

_ACTIVE_EXECUTION_STATUSES = frozenset(
    {"queued", "running", "waiting_for_input", "waiting_for_approval"}
)
_ACTION_PLAN_OPERATIONS = frozenset(
    {
        "propose_claim_create",
        "propose_claim_update",
        "propose_claim_reject",
        "propose_material_derived_version",
        "request_reassessment",
    }
)
_CONFIRMED_PROFILE_PURPOSES = frozenset(
    {
        "job_target_analysis",
        "project_deep_dive",
        "interview_training",
        "interview_retrospective",
    }
)
_CLAIM_TYPES = frozenset(
    {
        "skill",
        "project",
        "experience",
        "education",
        "certification",
        "achievement",
        "link",
    }
)
_SENSITIVE_VALUE_KEYS = frozenset(
    {
        "address",
        "contact",
        "contact_info",
        "email",
        "mobile",
        "phone",
        "qq",
        "wechat",
    }
)


@dataclass(frozen=True, slots=True)
class MaterialUploadResult:
    material: ProfileMaterialRecord
    version: ProfileMaterialVersionRecord
    execution_id: str
    session_id: str
    accepted_processing_status: str


@dataclass(frozen=True, slots=True)
class MaterialDocumentResult:
    version: ProfileMaterialVersionRecord
    original_text: str
    redacted_text: str
    evidence: tuple[EvidenceRecord, ...]


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
        run_ingest: Callable[[object], None] | None = None,
        revoke_publication: Callable[[str], None] | None = None,
        publish_event: Callable[[str, str | None, str, dict[str, object]], None]
        | None = None,
    ) -> None:
        self.workspace_id = workspace_id
        self.root = root
        self.repository = repository
        self.storage = storage
        self.product_repository = product_repository
        self._run_ingest = run_ingest
        self._revoke_publication = revoke_publication
        self._publish_event = publish_event
        self.connection: sqlite3.Connection = repository.connection

    def upload_material(
        self,
        *,
        file_name: str,
        content: bytes,
        title: str,
        primary_role: str = "resume",
        idempotency_key: str | None = None,
    ) -> MaterialUploadResult:
        stored = self.storage.persist_upload(file_name=file_name, content=content)
        request = {
            "fileName": file_name,
            "contentSha256": stored.content_sha256,
            "title": title,
            "primaryRole": primary_role,
        }
        if idempotency_key is not None:
            existing = self.repository.load_operation_receipt(
                workspace_id=self.workspace_id,
                operation="profile.material.upload",
                idempotency_key=idempotency_key,
                request=request,
            )
            if existing is not None:
                return self._upload_result_from_receipt(existing)
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
        result = MaterialUploadResult(
            material=material,
            version=version,
            execution_id=execution_id,
            session_id=version.id,
            accepted_processing_status=version.processing_status,
        )
        self._store_upload_receipt(
            operation="profile.material.upload",
            idempotency_key=idempotency_key,
            request=request,
            result=result,
        )
        return result

    def add_material_version(
        self,
        *,
        material_id: str,
        file_name: str,
        content: bytes,
        idempotency_key: str | None = None,
    ) -> MaterialUploadResult:
        material = self.repository.get_material(
            material_id, workspace_id=self.workspace_id
        )
        stored = self.storage.persist_upload(file_name=file_name, content=content)
        request = {
            "materialId": material.id,
            "fileName": file_name,
            "contentSha256": stored.content_sha256,
        }
        if idempotency_key is not None:
            existing = self.repository.load_operation_receipt(
                workspace_id=self.workspace_id,
                operation="profile.material.version.add",
                idempotency_key=idempotency_key,
                request=request,
            )
            if existing is not None:
                return self._upload_result_from_receipt(existing)
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
        result = MaterialUploadResult(
            material=material,
            version=version,
            execution_id=execution_id,
            session_id=version.id,
            accepted_processing_status=version.processing_status,
        )
        self._store_upload_receipt(
            operation="profile.material.version.add",
            idempotency_key=idempotency_key,
            request=request,
            result=result,
        )
        return result

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
                "material_id": material_id,
                "version_id": version.id,
                "storage_ref": version.storage_ref,
                "mime_type": version.mime_type,
                "file_name": file_name,
            },
            model_bindings={},
            configuration={},
        )
        if self._run_ingest is not None:
            self._run_ingest(execution)
        return execution.id

    def retry_version_ingest(
        self, version_id: str, *, idempotency_key: str | None = None
    ) -> object:
        version = self._require_workspace_version(version_id)
        request = {"versionId": version.id}
        if idempotency_key is not None:
            existing = self.repository.load_operation_receipt(
                workspace_id=self.workspace_id,
                operation="profile.material.version.retry",
                idempotency_key=idempotency_key,
                request=request,
            )
            if existing is not None:
                return self.product_repository.get_execution(
                    str(existing["executionId"])
                )
        latest = self.product_repository.latest_execution(version_id)
        if latest is not None and latest.status in _ACTIVE_EXECUTION_STATUSES:
            raise SessionBusyError("该材料版本仍有进行中的摄入任务，请稍后重试")
        self.repository.set_version_processing_status(version_id, "parsing")
        execution = self.product_repository.create_execution(
            version_id,
            input={
                "material_id": version.material_id,
                "version_id": version.id,
                "storage_ref": version.storage_ref,
                "mime_type": version.mime_type,
                "file_name": version.file_name,
                "retry": True,
            },
            model_bindings={},
            configuration={},
        )
        if self._run_ingest is not None:
            self._run_ingest(execution)
        if idempotency_key is not None:
            self.repository.store_operation_receipt(
                workspace_id=self.workspace_id,
                operation="profile.material.version.retry",
                idempotency_key=idempotency_key,
                request=request,
                result={"executionId": execution.id, "versionId": version.id},
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

    def archive_material(
        self,
        material_id: str,
        *,
        expected_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> ProfileMaterialRecord:
        return self._material_action(
            material_id=material_id,
            operation="profile.material.archive",
            request={"materialId": material_id, "expectedVersion": expected_version},
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            action=lambda: self.repository.archive_material(material_id),
        )

    def restore_material(
        self,
        material_id: str,
        *,
        expected_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> ProfileMaterialRecord:
        return self._material_action(
            material_id=material_id,
            operation="profile.material.restore",
            request={"materialId": material_id, "expectedVersion": expected_version},
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            action=lambda: self.repository.restore_material(material_id),
        )

    def set_primary_version(
        self,
        material_id: str,
        version_id: str,
        *,
        expected_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> ProfileMaterialRecord:
        return self._material_action(
            material_id=material_id,
            operation="profile.material.primary",
            request={
                "materialId": material_id,
                "versionId": version_id,
                "expectedVersion": expected_version,
            },
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            action=lambda: self.repository.set_primary_version(material_id, version_id),
        )

    def get_material(self, material_id: str) -> ProfileMaterialRecord:
        return self.repository.get_material(material_id, workspace_id=self.workspace_id)

    def list_materials(
        self, *, include_archived: bool = False
    ) -> tuple[ProfileMaterialRecord, ...]:
        return self.repository.list_materials(
            self.workspace_id, include_archived=include_archived
        )

    def list_material_versions(
        self, material_id: str
    ) -> tuple[ProfileMaterialVersionRecord, ...]:
        self.get_material(material_id)
        return self.repository.list_material_versions(material_id)

    def get_material_version(self, version_id: str) -> ProfileMaterialVersionRecord:
        return self._require_workspace_version(version_id)

    def read_material_document(self, version_id: str) -> MaterialDocumentResult:
        version = self._require_workspace_version(version_id)
        if not version.text_ref:
            raise ProfileDocumentNotReady(version_id)
        original_text = self.storage.read_text(version.text_ref)
        redacted_text, _ = redact_profile_text(original_text)
        return MaterialDocumentResult(
            version=version,
            original_text=original_text,
            redacted_text=redacted_text,
            evidence=self.repository.list_evidence_for_version(version.id),
        )

    def latest_execution(self, version_id: str):
        self._require_workspace_version(version_id)
        return self.product_repository.latest_execution(version_id)

    # --- Unified profile ---

    def unified_profile(self) -> UnifiedProfile:
        snapshot = self.repository.profile_snapshot(self.workspace_id)
        return project_unified_profile(
            workspace_id=self.workspace_id,
            profile_version=snapshot.profile_version,
            claims=snapshot.claims,
            relations=self.repository.list_claim_relations(self.workspace_id),
            presentation=self.repository.get_profile_presentation(self.workspace_id),
            pending_count=len(
                self.repository.list_proposals(self.workspace_id, status="pending")
            ),
        )

    def update_profile_presentation(
        self,
        *,
        summary_claim_id: str | None,
        primary_direction_claim_id: str | None,
        featured_claim_ids: tuple[str, ...],
        expected_version: int,
        command_id: str,
    ):
        self._require_profile_command_id(command_id)
        if len(featured_claim_ids) != len(set(featured_claim_ids)):
            raise ProfileValueInvalid("featured profile cards must be unique")
        return self.repository.update_profile_presentation(
            UpdateProfilePresentationCommand(
                workspace_id=self.workspace_id,
                summary_claim_id=summary_claim_id,
                primary_direction_claim_id=primary_direction_claim_id,
                featured_claim_ids=featured_claim_ids,
                expected_version=expected_version,
                idempotency_key=command_id,
            )
        )

    def create_conversation_proposals(
        self,
        proposals: Sequence[CreateClaimProposalSpec],
        *,
        execution_id: str,
        user_message_id: str,
        session_id: str,
    ):
        validated_specs: list[CreateClaimProposalSpec] = []
        for spec in proposals:
            category = spec.proposed_value.get("category")
            if not isinstance(category, str):
                raise ProfileValueInvalid("conversation proposal category is required")
            value = {
                key: item
                for key, item in spec.proposed_value.items()
                if key != "category"
            }
            validated = validate_profile_value(category, value)  # type: ignore[arg-type]
            target_claim_id = spec.target_claim_id
            base_version_id = None
            if spec.proposal_type == "update":
                if target_claim_id is None:
                    raise ProfileValueInvalid(
                        "conversation update requires a target profile card"
                    )
                claim = self.repository.get_claim(target_claim_id)
                if (
                    claim.workspace_id != self.workspace_id
                    or claim.claim_type != category
                    or claim.current_confirmed_version_id is None
                ):
                    raise ProfileClaimVersionConflict(
                        "conversation update target is not current"
                    )
                base_version_id = claim.current_confirmed_version_id
            elif spec.proposal_type != "create":
                raise ProfileValueInvalid(
                    "conversation proposal only supports create or update"
                )
            validated_specs.append(
                CreateClaimProposalSpec(
                    proposal_type=spec.proposal_type,
                    target_claim_id=target_claim_id,
                    base_claim_version_id=base_version_id,
                    proposed_value={"category": category, **validated},
                    reason=spec.reason,
                    source="conversation",
                    source_kind="conversation",
                    source_ref={
                        "messageId": user_message_id,
                        "sessionId": session_id,
                    },
                )
            )
        return self.repository.create_workspace_claim_proposals(
            self.workspace_id,
            validated_specs,
            idempotency_key=f"conversation:{execution_id}",
            created_by_execution_id=execution_id,
        )

    def create_profile_card(
        self,
        *,
        claim_type: str,
        value: dict[str, object],
        command_id: str,
        relations: tuple[ProfileRelationSpec, ...] = (),
        session_id: str | None = None,
    ) -> ProfileClaimVersionRecord:
        self._require_profile_command_id(command_id)
        validated = validate_profile_value(claim_type, value)  # type: ignore[arg-type]
        self._validate_profile_relation_targets(relations)
        version = self.repository.append_confirmed_claim(
            AppendConfirmedClaimCommand(
                workspace_id=self.workspace_id,
                claim_type=claim_type,  # type: ignore[arg-type]
                value=validated,
                source_kind="user_input",
                source_ref={"commandId": command_id},
                expected_claim_version=0,
                idempotency_key=command_id,
            )
        )
        if relations:
            self.repository.replace_claim_relations(
                self.workspace_id, version.claim_id, relations
            )
        self._emit_profile_card_event(
            session_id, "profile.card.created", version, claim_type
        )
        return version

    def update_profile_card(
        self,
        claim_id: str,
        *,
        value: dict[str, object],
        expected_version: int,
        command_id: str,
        relations: tuple[ProfileRelationSpec, ...] | None = None,
        session_id: str | None = None,
    ) -> ProfileClaimVersionRecord:
        self._require_profile_command_id(command_id)
        claim = self.repository.get_claim(claim_id)
        if claim.workspace_id != self.workspace_id:
            raise ProfileClaimNotFound(claim_id)
        validated = validate_profile_value(claim.claim_type, value)
        if relations is not None:
            self._validate_profile_relation_targets(relations, claim_id=claim.id)
        version = self.repository.append_confirmed_claim(
            AppendConfirmedClaimCommand(
                workspace_id=self.workspace_id,
                claim_id=claim.id,
                claim_type=claim.claim_type,
                value=validated,
                source_kind="user_input",
                source_ref={"commandId": command_id},
                expected_claim_version=expected_version,
                idempotency_key=command_id,
            )
        )
        if relations is not None:
            self.repository.replace_claim_relations(
                self.workspace_id, claim.id, relations
            )
        self._emit_profile_card_event(
            session_id, "profile.card.updated", version, claim.claim_type
        )
        return version

    def restore_profile_card_version(
        self,
        claim_id: str,
        source_version_id: str,
        *,
        expected_version: int,
        command_id: str,
        session_id: str | None = None,
    ) -> ProfileClaimVersionRecord:
        self._require_profile_command_id(command_id)
        claim = self.repository.get_claim(claim_id)
        if claim.workspace_id != self.workspace_id:
            raise ProfileClaimNotFound(claim_id)
        source = self.repository.get_claim_version(source_version_id)
        if source.claim_id != claim.id:
            raise ProfileClaimNotFound(source_version_id)
        validated = validate_profile_value(claim.claim_type, source.value)
        version = self.repository.append_confirmed_claim(
            AppendConfirmedClaimCommand(
                workspace_id=self.workspace_id,
                claim_id=claim.id,
                claim_type=claim.claim_type,
                value=validated,
                source_kind="user_input",
                source_ref={
                    "commandId": command_id,
                    "restoredFromVersionId": source.id,
                },
                expected_claim_version=expected_version,
                idempotency_key=command_id,
            )
        )
        self._emit_profile_card_event(
            session_id, "profile.card.restored", version, claim.claim_type
        )
        return version

    def delete_profile_card(
        self,
        claim_id: str,
        *,
        expected_version: int,
        command_id: str,
        session_id: str | None = None,
    ) -> None:
        self._require_profile_command_id(command_id)
        claim = self.repository.get_claim(claim_id)
        if claim.workspace_id != self.workspace_id:
            raise ProfileClaimNotFound(claim_id)
        self.repository.delete_confirmed_claim(
            workspace_id=self.workspace_id,
            claim_id=claim.id,
            expected_claim_version=expected_version,
            idempotency_key=command_id,
        )
        if self._publish_event is not None and session_id is not None:
            self._publish_event(
                session_id,
                None,
                "profile.card.deleted",
                {
                    "claimId": claim.id,
                    "claimType": claim.claim_type,
                    "status": "deleted",
                },
            )

    def _validate_profile_relation_targets(
        self,
        relations: tuple[ProfileRelationSpec, ...],
        *,
        claim_id: str | None = None,
    ) -> None:
        for relation in relations:
            if relation.target_claim_id == claim_id:
                raise ProfileClaimVersionConflict(
                    "profile card cannot relate to itself"
                )
            target = self.repository.get_claim(relation.target_claim_id)
            if target.workspace_id != self.workspace_id:
                raise ProfileClaimVersionConflict(
                    "profile relation target is outside the workspace"
                )

    @staticmethod
    def _require_profile_command_id(command_id: str) -> None:
        if not command_id.strip():
            raise ProfileValueInvalid("profile command id is required")

    def _emit_profile_card_event(
        self,
        session_id: str | None,
        event_type: str,
        version: ProfileClaimVersionRecord,
        claim_type: str,
    ) -> None:
        if self._publish_event is not None and session_id is not None:
            self._publish_event(
                session_id,
                None,
                event_type,
                {
                    "claimId": version.claim_id,
                    "claimVersionId": version.id,
                    "claimType": claim_type,
                    "status": version.status,
                },
            )

    # --- Claim review ---

    def claim_review_snapshot(self) -> ClaimReviewSnapshot:
        snapshot = self.repository.profile_snapshot(self.workspace_id)
        return ClaimReviewSnapshot(
            workspace_id=self.workspace_id,
            profile_version=snapshot.profile_version,
            claims=tuple(
                self.get_claim_review(claim.id)
                for claim in self.repository.list_claims(self.workspace_id)
                if claim.current_confirmed_version_id is not None
            ),
            proposals=self.repository.list_proposals(self.workspace_id),
        )

    def get_claim_review(self, claim_id: str) -> ClaimReviewDetail:
        claim = self.repository.get_claim(claim_id)
        if claim.workspace_id != self.workspace_id:
            raise ProfileClaimNotFound(claim_id)
        if claim.current_confirmed_version_id is None:
            raise ProfileClaimNotFound(claim_id)
        versions = self.repository.list_claim_versions(claim.id)
        current = self.repository.get_claim_version(claim.current_confirmed_version_id)
        proposals = tuple(
            item
            for item in self.repository.list_proposals(self.workspace_id)
            if item.target_claim_id == claim.id
        )
        conflicts = self.repository.list_conflicts_for_claim(claim.id)
        evidence = tuple(
            self.repository.get_evidence(evidence_id)
            for evidence_id in current.evidence_ids
        )
        return ClaimReviewDetail(
            claim=claim,
            current_version=current,
            versions=versions,
            proposals=proposals,
            conflicts=conflicts,
            evidence=evidence,
        )

    def confirmed_profile_context(
        self,
        *,
        purpose: str,
        claim_types: tuple[str, ...] = (),
        claim_ids: tuple[str, ...] = (),
        sensitive_data_policy: str = "exclude",
        limit: int = 50,
    ) -> ConfirmedProfileContext:
        if purpose not in _CONFIRMED_PROFILE_PURPOSES:
            raise ProfileContextRequestInvalid("unsupported profile context purpose")
        requested_types = frozenset(claim_types)
        if requested_types - _CLAIM_TYPES:
            raise ProfileContextRequestInvalid("unsupported profile claim type")
        if sensitive_data_policy != "exclude":
            raise ProfileContextRequestInvalid(
                "sensitive profile context is not enabled"
            )
        if limit < 1 or limit > 50:
            raise ProfileContextRequestInvalid("profile context limit is invalid")

        requested_ids = tuple(dict.fromkeys(claim_ids))
        for claim_id in requested_ids:
            claim = self.repository.get_claim(claim_id)
            if claim.workspace_id != self.workspace_id:
                raise ProfileClaimNotFound(claim_id)
        requested_id_set = frozenset(requested_ids)

        snapshot = self.repository.profile_snapshot(self.workspace_id)
        items: list[ConfirmedProfileContextItem] = []
        for claim in snapshot.claims:
            if requested_types and claim.claim_type not in requested_types:
                continue
            if requested_id_set and claim.claim_id not in requested_id_set:
                continue
            visible_evidence_ids = tuple(
                evidence_id
                for evidence_id in claim.evidence_ids
                if self._context_evidence_is_visible(evidence_id)
            )
            if claim.evidence_ids and not visible_evidence_ids:
                continue
            value = self._without_sensitive_profile_fields(claim.value)
            if not value:
                continue
            items.append(
                ConfirmedProfileContextItem(
                    claim_id=claim.claim_id,
                    claim_version_id=claim.claim_version_id,
                    claim_type=claim.claim_type,
                    value=value,
                    support_status=claim.support_status,
                    evidence_ids=visible_evidence_ids,
                )
            )
            if len(items) >= limit:
                break
        return ConfirmedProfileContext(
            workspace_id=self.workspace_id,
            purpose=purpose,
            profile_version=snapshot.profile_version,
            items=tuple(items),
        )

    def decide_claim_proposal(
        self,
        proposal_id: str,
        *,
        decision: str,
        expected_version: int,
        edited_value: dict[str, object] | None = None,
        idempotency_key: str,
    ):
        proposal = self.repository.get_proposal(proposal_id)
        if proposal.workspace_id != self.workspace_id:
            raise ProfileProposalNotFound(proposal_id)
        return self.repository.decide_proposal(
            proposal_id,
            DecideProposalCommand(
                proposal_id=proposal_id,
                decision=decision,
                expected_status="pending",
                expected_claim_version=expected_version,
                edited_value=edited_value,
                idempotency_key=idempotency_key,
            ),
        )

    def batch_decide_claim_proposals(
        self, commands: tuple[DecideProposalCommand, ...]
    ) -> BatchClaimDecisionResult:
        for command in commands:
            proposal = self.repository.get_proposal(command.proposal_id)
            if proposal.workspace_id != self.workspace_id:
                raise ProfileProposalNotFound(command.proposal_id)
        return self.repository.batch_decide_proposals(commands)

    def duplicate_proposal_preview(self):
        return self.repository.duplicate_proposal_preview(self.workspace_id)

    def consolidate_duplicate_proposals(
        self,
        *,
        expected_groups: tuple[tuple[str, ...], ...],
        idempotency_key: str,
    ):
        for group in expected_groups:
            for proposal_id in group:
                proposal = self.repository.get_proposal(proposal_id)
                if proposal.workspace_id != self.workspace_id:
                    raise ProfileProposalNotFound(proposal_id)
        return self.repository.consolidate_duplicate_proposals(
            self.workspace_id,
            expected_groups=expected_groups,
            idempotency_key=idempotency_key,
        )

    # --- Assessment and constrained action plans ---

    def save_assessment(
        self,
        *,
        base_profile_version: str,
        result: dict[str, object],
        created_by_execution_id: str | None = None,
    ) -> ProfileAssessmentRecord:
        snapshot = self.repository.profile_snapshot(self.workspace_id)
        if not snapshot.claims or snapshot.profile_version != base_profile_version:
            raise ProfileClaimVersionConflict(
                "assessment requires the current confirmed profile snapshot"
            )
        evidence_ids = self._assessment_evidence_ids(result)
        if not evidence_ids:
            raise ProfileActionPlanInvalid("assessment must cite evidence")
        self._validate_evidence_ids(evidence_ids)
        return self.repository.save_assessment(
            SaveAssessmentCommand(
                workspace_id=self.workspace_id,
                base_profile_version=base_profile_version,
                result=result,
                created_by_execution_id=created_by_execution_id,
            )
        )

    def get_assessment(self, assessment_id: str) -> ProfileAssessmentRecord:
        assessment = self.repository.get_assessment(assessment_id)
        if assessment.workspace_id != self.workspace_id:
            raise ProfileAssessmentNotFound(assessment_id)
        return assessment

    def get_action_plan(self, plan_id: str) -> ProfileActionPlanRecord:
        return self._workspace_action_plan(plan_id)

    def create_action_plan(
        self, command: CreateActionPlanCommand
    ) -> ProfileActionPlanRecord:
        if command.workspace_id != self.workspace_id:
            raise ProfileActionPlanNotFound("workspace")
        current_version = (
            self.repository.profile_snapshot(self.workspace_id).profile_version or ""
        )
        if command.base_profile_version != current_version:
            raise ProfileClaimVersionConflict("action plan base profile is stale")
        if not command.items:
            raise ProfileActionPlanInvalid("action plan must contain an item")
        if len(command.items) > 50:
            raise ProfileActionPlanInvalid("action plan exceeds 50 items")
        if [item.ordinal for item in command.items] != list(
            range(1, len(command.items) + 1)
        ) or len({item.item_id for item in command.items}) != len(command.items):
            raise ProfileActionPlanInvalid("action plan item order is invalid")
        for item in command.items:
            if item.operation not in _ACTION_PLAN_OPERATIONS:
                raise ProfileActionPlanInvalid(
                    f"unsupported action plan operation: {item.operation}"
                )
            self._validate_action_plan_item(item)
        plan = self.repository.create_action_plan(command)
        if plan.status == "proposed":
            plan = self.repository.update_action_plan_status(
                plan.id, status="validated"
            )
            self._emit_action_plan_event(
                plan,
                "profile.action_plan.created",
                {
                    "planId": plan.id,
                    "itemCount": len(plan.items),
                    "status": plan.status,
                },
            )
        return plan

    def confirm_action_plan(
        self, plan_id: str, *, expected_version: int
    ) -> ProfileActionPlanRecord:
        plan = self._workspace_action_plan(plan_id)
        if plan.status == "completed":
            return plan
        self.repository.validate_action_plan_fresh(plan_id)
        executing = self.repository.transition_action_plan_status(
            plan_id,
            expected_version=expected_version,
            from_statuses=("validated", "awaiting_confirmation"),
            status="executing",
        )
        return self._execute_action_plan(executing)

    def retry_action_plan(self, plan_id: str) -> ProfileActionPlanRecord:
        plan = self._workspace_action_plan(plan_id)
        if plan.status == "completed":
            return plan
        self.repository.validate_action_plan_fresh(plan_id)
        executing = self.repository.transition_action_plan_status(
            plan_id,
            expected_version=plan.version,
            from_statuses=("failed", "partially_completed"),
            status="executing",
        )
        return self._execute_action_plan(executing)

    def cancel_action_plan(
        self, plan_id: str, *, expected_version: int
    ) -> ProfileActionPlanRecord:
        plan = self._workspace_action_plan(plan_id)
        return self.repository.transition_action_plan_status(
            plan_id,
            expected_version=expected_version,
            from_statuses=("proposed", "validated", "awaiting_confirmation"),
            status="cancelled",
        )

    def _execute_action_plan(
        self, plan: ProfileActionPlanRecord
    ) -> ProfileActionPlanRecord:
        for item in plan.items:
            if item.status in {"completed", "skipped"}:
                continue
            try:
                receipt_id = self._dispatch_action_plan_item(plan, item)
                self.repository.apply_action_plan_item(
                    item.item_id,
                    expected_claim_version=item.expected_version,
                    status="completed",
                    receipt_id=receipt_id,
                )
                self._emit_action_plan_event(
                    plan,
                    "profile.action_plan.item_completed",
                    {
                        "planId": plan.id,
                        "itemId": item.item_id,
                        "operation": item.operation,
                        "ordinal": item.ordinal,
                        "status": "completed",
                    },
                )
            except Exception as error:
                error_code = (
                    error.code
                    if isinstance(error, ProfileDomainError)
                    else "profile_action_plan_item_failed"
                )
                self.repository.record_action_plan_item_failure(
                    item.item_id, error_code=error_code
                )
        current = self.repository.get_action_plan(plan.id)
        failed = [item for item in current.items if item.status == "failed"]
        completed = [item for item in current.items if item.status == "completed"]
        final_status = (
            "completed"
            if not failed
            else "partially_completed"
            if completed
            else "failed"
        )
        return self.repository.transition_action_plan_status(
            plan.id,
            expected_version=current.version,
            from_statuses=("executing",),
            status=final_status,
        )

    def _dispatch_action_plan_item(self, plan, item) -> str:
        if item.operation.startswith("propose_claim_"):
            evidence = self._validate_evidence_ids(item.evidence_ids)
            version_id = evidence[0].material_version_id
            proposal_type = {
                "propose_claim_create": "create",
                "propose_claim_update": "update",
                "propose_claim_reject": "reject",
            }[item.operation]
            claim_id = item.target.get("claimId")
            base_version_id = None
            if claim_id is not None:
                claim = self.repository.get_claim(str(claim_id))
                base_version_id = claim.current_confirmed_version_id
            proposal = self.repository.create_claim_proposals(
                version_id,
                (
                    CreateClaimProposalSpec(
                        proposal_type=proposal_type,
                        target_claim_id=None if claim_id is None else str(claim_id),
                        base_claim_version_id=base_version_id,
                        proposed_value=item.after,
                        reason=f"Action Plan {plan.id}",
                        evidence_ids=item.evidence_ids,
                        source="action_plan",
                    ),
                ),
                created_by_execution_id=plan.execution_id,
                idempotency_key=f"action-plan:{plan.id}:{item.item_id}",
            )[0]
            return proposal.id
        if item.operation == "propose_material_derived_version":
            material_id = str(item.target["materialId"])
            source_version_id = str(item.target["sourceVersionId"])
            file_name = str(item.after.get("fileName", "resume-polished.md"))
            content = str(item.after["content"])
            creator = f"action-plan:{plan.id}:{item.item_id}"
            stored = self.storage.persist_upload(
                file_name=file_name, content=content.encode("utf-8")
            )
            version = self.repository.find_material_version_by_creator(
                material_id, creator
            )
            if version is None:
                version = self.repository.add_material_version(
                    material_id=material_id,
                    source_type="derived_draft",
                    file_name=file_name,
                    mime_type=stored.mime_type,
                    content_sha256=stored.content_sha256,
                    storage_ref=stored.storage_ref,
                    text_ref="",
                    created_by=creator,
                    derived_from_version_id=source_version_id,
                )
            elif (
                version.content_sha256 != stored.content_sha256
                or version.derived_from_version_id != source_version_id
            ):
                raise ProfileActionPlanInvalid("derived version receipt input changed")
            if version.processing_status != "ready":
                text_ref = self.storage.write_text(version_id=version.id, text=content)
                if version.processing_status in {"uploaded", "parsing", "parse_failed"}:
                    self.repository.mark_version_parsed(
                        version.id,
                        text_path=text_ref,
                        content_sha256=stored.content_sha256,
                    )
                self.repository.set_version_processing_status(version.id, "ready")
            if self.get_material(material_id).current_version_id != version.id:
                self.repository.set_primary_version(material_id, version.id)
            return version.id
        if item.operation == "set_publication_selection":
            snapshot = self.repository.profile_snapshot(self.workspace_id)
            selection = self.repository.create_publication_selection(
                CreatePublicationSelectionCommand(
                    workspace_id=self.workspace_id,
                    profile_version=snapshot.profile_version or "",
                    claim_version_ids=tuple(
                        str(value) for value in item.after.get("claimVersionIds", [])
                    ),
                    excluded_sensitive_fields=tuple(
                        str(value)
                        for value in item.after.get("excludedSensitiveFields", [])
                    ),
                    idempotency_key=f"action-plan:{plan.id}:{item.item_id}",
                )
            )
            return selection.id
        if item.operation == "request_reassessment":
            return f"reassessment:{plan.id}:{item.item_id}"
        raise ProfileActionPlanInvalid("unsupported action plan operation")

    def _validate_action_plan_item(self, item) -> None:
        if item.operation.startswith("propose_claim_"):
            if not item.evidence_ids:
                raise ProfileActionPlanInvalid("claim proposal item requires evidence")
            self._validate_evidence_ids(item.evidence_ids)
        if item.operation in {"propose_claim_update", "propose_claim_reject"}:
            claim_id = item.target.get("claimId")
            if not claim_id or item.expected_version is None:
                raise ProfileActionPlanInvalid(
                    "claim mutation requires target and version"
                )
            claim = self.repository.get_claim(str(claim_id))
            if (
                claim.workspace_id != self.workspace_id
                or claim.version != item.expected_version
            ):
                raise ProfileClaimVersionConflict("target claim changed")
            current = self.repository.get_claim_version(
                claim.current_confirmed_version_id or ""
            )
            if item.before is not None and item.before != current.value:
                raise ProfileClaimVersionConflict("action plan before snapshot changed")
        elif item.operation == "propose_claim_create" and item.expected_version not in {
            None,
            0,
        }:
            raise ProfileActionPlanInvalid("claim create expected version must be zero")
        elif item.operation == "propose_material_derived_version":
            material = self.get_material(str(item.target.get("materialId", "")))
            source = self.repository.get_material_version(
                str(item.target.get("sourceVersionId", ""))
            )
            if source.material_id != material.id or not str(
                item.after.get("content", "")
            ):
                raise ProfileActionPlanInvalid("derived version input is invalid")
        elif item.operation == "set_publication_selection":
            version_ids = tuple(item.after.get("claimVersionIds", []))
            if not version_ids:
                raise ProfileActionPlanInvalid("publication selection is empty")
            for version_id in version_ids:
                version = self.repository.get_claim_version(str(version_id))
                claim = self.repository.get_claim(version.claim_id)
                if claim.workspace_id != self.workspace_id:
                    raise ProfileClaimNotFound(claim.id)

    def _validate_evidence_ids(self, evidence_ids):
        records = []
        version_ids = set()
        for evidence_id in evidence_ids:
            evidence = self.repository.get_evidence(str(evidence_id))
            if evidence.tombstoned_at is not None:
                raise ProfileActionPlanInvalid("evidence was removed")
            version = self.repository.get_material_version(evidence.material_version_id)
            material = self.repository.get_material(
                version.material_id, workspace_id=self.workspace_id
            )
            if material.workspace_id != self.workspace_id:
                raise ProfileActionPlanInvalid("evidence workspace mismatch")
            records.append(evidence)
            version_ids.add(evidence.material_version_id)
        if len(version_ids) > 1:
            raise ProfileActionPlanInvalid(
                "one proposal item must cite one material version"
            )
        return tuple(records)

    @staticmethod
    def _assessment_evidence_ids(value: object) -> tuple[str, ...]:
        found: list[str] = []
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"evidenceIds", "evidence_ids"} and isinstance(item, list):
                    found.extend(str(entry) for entry in item)
                else:
                    found.extend(ProfileService._assessment_evidence_ids(item))
        elif isinstance(value, list):
            for item in value:
                found.extend(ProfileService._assessment_evidence_ids(item))
        return tuple(dict.fromkeys(found))

    def _workspace_action_plan(self, plan_id: str) -> ProfileActionPlanRecord:
        plan = self.repository.get_action_plan(plan_id)
        if plan.workspace_id != self.workspace_id:
            raise ProfileActionPlanNotFound(plan_id)
        return plan

    def _context_evidence_is_visible(self, evidence_id: str) -> bool:
        evidence = self.repository.get_evidence(evidence_id)
        return evidence.tombstoned_at is None and evidence.sensitivity == "normal"

    @classmethod
    def _without_sensitive_profile_fields(
        cls, value: dict[str, object]
    ) -> dict[str, object]:
        def sanitize(item: object) -> object:
            if isinstance(item, dict):
                return {
                    str(key): sanitize(child)
                    for key, child in item.items()
                    if str(key).strip().lower() not in _SENSITIVE_VALUE_KEYS
                }
            if isinstance(item, list):
                return [sanitize(child) for child in item]
            return item

        sanitized = sanitize(value)
        return sanitized if isinstance(sanitized, dict) else {}

    def _emit_action_plan_event(
        self,
        plan: ProfileActionPlanRecord,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        if self._publish_event is not None and plan.session_id is not None:
            self._publish_event(plan.session_id, plan.execution_id, event_type, payload)

    # --- Permanent deletion ---

    def preview_material_deletion(
        self,
        material_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> MaterialDeletionPlanRecord:
        material = self.get_material(material_id)
        if material.version != expected_version:
            raise ProfileMaterialVersionConflict(
                "profile material changed before deletion preview"
            )
        impact = self.repository.build_material_deletion_impact(
            material_id, workspace_id=self.workspace_id
        )
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        return self.repository.create_material_deletion_plan(
            workspace_id=self.workspace_id,
            material_id=material_id,
            material_version=material.version,
            impact=impact,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
        )

    def preview_material_version_deletion(
        self,
        version_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> MaterialDeletionPlanRecord:
        version = self._require_workspace_version(version_id)
        material = self.get_material(version.material_id)
        if material.version != expected_version:
            raise ProfileMaterialVersionConflict(
                "profile material changed before version deletion preview"
            )
        impact = self.repository.build_material_version_deletion_impact(
            version_id, workspace_id=self.workspace_id
        )
        if impact.get("pendingProposalIds"):
            raise ProfileMaterialVersionHasPendingProposals(
                "workspace has pending profile proposals"
            )
        if not impact.get("replacementVersions"):
            raise ProfileDeletionPlanConflict("cannot delete the only material version")
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        return self.repository.create_material_deletion_plan(
            workspace_id=self.workspace_id,
            material_id=material.id,
            material_version=material.version,
            impact=impact,
            expires_at=expires_at,
            target_kind="material_version",
            target_version_id=version.id,
            idempotency_key=idempotency_key,
        )

    def permanently_delete_material(
        self,
        material_id: str,
        *,
        deletion_plan_id: str,
        expected_version: int,
        claim_choices: dict[str, str],
        active_publication_action: str,
        idempotency_key: str,
    ) -> MaterialDeletionResult:
        request = {
            "materialId": material_id,
            "deletionPlanId": deletion_plan_id,
            "expectedVersion": expected_version,
            "claimChoices": dict(sorted(claim_choices.items())),
            "activePublicationAction": active_publication_action,
        }
        operation = f"profile.material.permanent_delete:{material_id}"
        existing = self.repository.load_operation_receipt(
            workspace_id=self.workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request=request,
        )
        if existing is not None:
            return self._deletion_result(existing)
        plan = self.repository.get_material_deletion_plan(deletion_plan_id)
        if (
            plan.workspace_id != self.workspace_id
            or plan.material_id != material_id
            or plan.target_kind != "material"
        ):
            raise ProfileDeletionPlanConflict("deletion plan target mismatch")
        if plan.status not in {"planned", "failed"}:
            raise ProfileDeletionPlanConflict("deletion plan is no longer executable")
        expires_at = datetime.fromisoformat(plan.expires_at.replace("Z", "+00:00"))
        if expires_at <= datetime.now(timezone.utc):
            self.repository.set_material_deletion_plan_status(plan.id, status="expired")
            raise ProfileDeletionPlanExpired("deletion plan expired")
        if active_publication_action == "cancel" or "cancel" in claim_choices.values():
            cancelled = MaterialDeletionResult(
                plan_id=plan.id, status="cancelled", items=()
            )
            self.repository.set_material_deletion_plan_status(
                plan.id,
                status="cancelled",
                result=self._deletion_result_payload(cancelled),
            )
            return cancelled
        if plan.active_publication_ids:
            if active_publication_action != "revoke":
                raise ProfilePublicationRevocationRequired(
                    "active publication must be revoked before deletion"
                )
            if self._revoke_publication is None:
                raise ProfilePublicationRevocationUnavailable(
                    "publication revocation is not wired yet"
                )
        elif active_publication_action not in {"not_applicable", "revoke"}:
            raise ProfileDeletionPlanConflict("invalid publication deletion choice")

        receipts = [
            self._deletion_receipt(item)
            for item in plan.result.get("items", [])
            if isinstance(item, dict)
        ]
        completed_targets = {
            (item.kind, item.target_id)
            for item in receipts
            if item.status == "completed"
        }
        self.repository.set_material_deletion_plan_status(plan.id, status="executing")
        try:
            for publication_id in plan.active_publication_ids:
                if ("publication", publication_id) in completed_targets:
                    continue
                assert self._revoke_publication is not None
                self._revoke_publication(publication_id)
                receipts.append(
                    DeletionItemReceipt(
                        kind="publication",
                        target_id=publication_id,
                        status="completed",
                        action="revoke",
                    )
                )
            if ("material", material_id) not in completed_targets:
                receipts.extend(
                    self.repository.apply_material_deletion(
                        plan_id=plan.id,
                        expected_material_version=expected_version,
                        claim_choices=claim_choices,
                    )
                )
            for artifact in plan.impact.get("artifactRefs", []):
                if not isinstance(artifact, dict):
                    continue
                ref = str(artifact.get("ref", ""))
                if not ref:
                    continue
                remaining = self.repository.artifact_reference_count(ref)
                deleted = self.storage.delete_ref(ref, remaining_references=remaining)
                receipts.append(
                    DeletionItemReceipt(
                        kind="artifact",
                        target_id=str(artifact.get("kind", "artifact")),
                        status="completed",
                        action=(
                            "retain_shared"
                            if remaining
                            else "delete"
                            if deleted
                            else "already_absent"
                        ),
                    )
                )
            result = MaterialDeletionResult(
                plan_id=plan.id, status="completed", items=tuple(receipts)
            )
            payload = self._deletion_result_payload(result)
            self.repository.set_material_deletion_plan_status(
                plan.id, status="completed", result=payload
            )
            self.repository.store_operation_receipt(
                workspace_id=self.workspace_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request=request,
                result=payload,
            )
            return result
        except Exception:
            self.repository.set_material_deletion_plan_status(
                plan.id,
                status="failed",
                result={"items": [asdict(item) for item in receipts]},
            )
            raise

    def permanently_delete_material_version(
        self,
        version_id: str,
        *,
        deletion_plan_id: str,
        expected_version: int,
        replacement_version_id: str | None,
        claim_choices: dict[str, str],
        active_publication_action: str,
        idempotency_key: str,
    ) -> MaterialDeletionResult:
        request = {
            "versionId": version_id,
            "deletionPlanId": deletion_plan_id,
            "expectedVersion": expected_version,
            "replacementVersionId": replacement_version_id,
            "claimChoices": dict(sorted(claim_choices.items())),
            "activePublicationAction": active_publication_action,
        }
        operation = f"profile.material.version.permanent_delete:{version_id}"
        existing = self.repository.load_operation_receipt(
            workspace_id=self.workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request=request,
        )
        if existing is not None:
            return self._deletion_result(existing)
        plan = self.repository.get_material_deletion_plan(deletion_plan_id)
        if (
            plan.workspace_id != self.workspace_id
            or plan.target_kind != "material_version"
            or plan.target_version_id != version_id
        ):
            raise ProfileDeletionPlanConflict("deletion plan target mismatch")
        if plan.status not in {"planned", "failed"}:
            raise ProfileDeletionPlanConflict("deletion plan is no longer executable")
        expires_at = datetime.fromisoformat(plan.expires_at.replace("Z", "+00:00"))
        if expires_at <= datetime.now(timezone.utc):
            self.repository.set_material_deletion_plan_status(plan.id, status="expired")
            raise ProfileDeletionPlanExpired("deletion plan expired")
        if active_publication_action == "cancel" or "cancel" in claim_choices.values():
            cancelled = MaterialDeletionResult(
                plan_id=plan.id, status="cancelled", items=()
            )
            self.repository.set_material_deletion_plan_status(
                plan.id,
                status="cancelled",
                result=self._deletion_result_payload(cancelled),
            )
            return cancelled
        if plan.active_publication_ids:
            if active_publication_action != "revoke":
                raise ProfilePublicationRevocationRequired(
                    "active publication must be revoked before deletion"
                )
            if self._revoke_publication is None:
                raise ProfilePublicationRevocationUnavailable(
                    "publication revocation is not wired yet"
                )
        elif active_publication_action not in {"not_applicable", "revoke"}:
            raise ProfileDeletionPlanConflict("invalid publication deletion choice")

        receipts = [
            self._deletion_receipt(item)
            for item in plan.result.get("items", [])
            if isinstance(item, dict)
        ]
        completed_targets = {
            (item.kind, item.target_id)
            for item in receipts
            if item.status == "completed"
        }
        self.repository.set_material_deletion_plan_status(plan.id, status="executing")
        try:
            for publication_id in plan.active_publication_ids:
                if ("publication", publication_id) in completed_targets:
                    continue
                assert self._revoke_publication is not None
                self._revoke_publication(publication_id)
                receipts.append(
                    DeletionItemReceipt(
                        kind="publication",
                        target_id=publication_id,
                        status="completed",
                        action="revoke",
                    )
                )
            if ("material_version", version_id) not in completed_targets:
                receipts.extend(
                    self.repository.apply_material_version_deletion(
                        plan_id=plan.id,
                        expected_material_version=expected_version,
                        replacement_version_id=replacement_version_id,
                        claim_choices=claim_choices,
                    )
                )
            for artifact in plan.impact.get("artifactRefs", []):
                if not isinstance(artifact, dict):
                    continue
                ref = str(artifact.get("ref", ""))
                if not ref:
                    continue
                remaining = self.repository.artifact_reference_count(ref)
                deleted = self.storage.delete_ref(ref, remaining_references=remaining)
                receipts.append(
                    DeletionItemReceipt(
                        kind="artifact",
                        target_id=str(artifact.get("kind", "artifact")),
                        status="completed",
                        action=(
                            "retain_shared"
                            if remaining
                            else "delete"
                            if deleted
                            else "already_absent"
                        ),
                    )
                )
            result = MaterialDeletionResult(
                plan_id=plan.id, status="completed", items=tuple(receipts)
            )
            payload = self._deletion_result_payload(result)
            self.repository.set_material_deletion_plan_status(
                plan.id, status="completed", result=payload
            )
            self.repository.store_operation_receipt(
                workspace_id=self.workspace_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request=request,
                result=payload,
            )
            return result
        except Exception:
            self.repository.set_material_deletion_plan_status(
                plan.id,
                status="failed",
                result={"items": [asdict(item) for item in receipts]},
            )
            raise

    @staticmethod
    def _deletion_result_payload(result: MaterialDeletionResult) -> dict[str, object]:
        return {
            "planId": result.plan_id,
            "status": result.status,
            "items": [asdict(item) for item in result.items],
        }

    @staticmethod
    def _deletion_result(value: dict[str, object]) -> MaterialDeletionResult:
        return MaterialDeletionResult(
            plan_id=str(value["planId"]),
            status=str(value["status"]),
            items=tuple(
                ProfileService._deletion_receipt(item)
                for item in value.get("items", [])
                if isinstance(item, dict)
            ),
        )

    @staticmethod
    def _deletion_receipt(item: dict[str, object]) -> DeletionItemReceipt:
        return DeletionItemReceipt(
            kind=str(item["kind"]),
            target_id=str(item["target_id"]),
            status=str(item["status"]),
            action=str(item["action"]),
            error_code=(
                None if item.get("error_code") is None else str(item["error_code"])
            ),
        )

    def _material_action(
        self,
        *,
        material_id: str,
        operation: str,
        request: dict[str, object],
        expected_version: int | None,
        idempotency_key: str | None,
        action: Callable[[], ProfileMaterialRecord],
    ) -> ProfileMaterialRecord:
        if idempotency_key is not None:
            existing = self.repository.load_operation_receipt(
                workspace_id=self.workspace_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request=request,
            )
            if existing is not None:
                return self.get_material(str(existing["materialId"]))
        material = self.get_material(material_id)
        if expected_version is not None and material.version != expected_version:
            raise ProfileMaterialVersionConflict(
                "profile material version changed before operation"
            )
        result = action()
        if idempotency_key is not None:
            self.repository.store_operation_receipt(
                workspace_id=self.workspace_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request=request,
                result={"materialId": result.id, "version": result.version},
            )
        return result

    def _store_upload_receipt(
        self,
        *,
        operation: str,
        idempotency_key: str | None,
        request: dict[str, object],
        result: MaterialUploadResult,
    ) -> None:
        if idempotency_key is None:
            return
        self.repository.store_operation_receipt(
            workspace_id=self.workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request=request,
            result={
                "materialId": result.material.id,
                "versionId": result.version.id,
                "executionId": result.execution_id,
                "processingStatus": result.accepted_processing_status,
            },
        )

    def _upload_result_from_receipt(
        self, receipt: dict[str, object]
    ) -> MaterialUploadResult:
        material = self.get_material(str(receipt["materialId"]))
        version = self._require_workspace_version(str(receipt["versionId"]))
        return MaterialUploadResult(
            material=material,
            version=version,
            execution_id=str(receipt["executionId"]),
            session_id=version.id,
            accepted_processing_status=str(receipt["processingStatus"]),
        )

    def _require_workspace_version(
        self, version_id: str
    ) -> ProfileMaterialVersionRecord:
        version = self.repository.get_material_version(version_id)
        self.repository.get_material(
            version.material_id, workspace_id=self.workspace_id
        )
        return version
