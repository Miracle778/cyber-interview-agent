from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from hashlib import sha256
from typing import Any, Iterator, Sequence
from uuid import uuid4

from app.profile.errors import (
    ProfileActionPlanNotFound,
    ProfileAssessmentNotFound,
    ProfileClaimNotFound,
    ProfileClaimSelectedForPublication,
    ProfileClaimVersionConflict,
    ProfileDeletionPlanConflict,
    ProfileDeletionPlanNotFound,
    ProfileDomainError,
    ProfileEvidenceMismatch,
    ProfileIdempotencyConflict,
    ProfileMaterialNotFound,
    ProfileMaterialRoleConflict,
    ProfileMaterialVersionHasPendingProposals,
    ProfileMaterialVersionNotFound,
    ProfileProposalAlreadyDecided,
    ProfileProposalNotFound,
    ProfilePublicationSelectionNotFound,
    ProfileSnapshotChanged,
)
from app.profile.claim_values import (
    canonical_claim_value,
    claim_identity,
    merge_claim_values,
    proposal_confidence,
)
from app.profile.models import (
    ActionPlanItemRecord,
    ActionPlanItemSpec,
    AppendConfirmedClaimCommand,
    BatchClaimDecisionResult,
    ClaimConflictRecord,
    ClaimDecisionResult,
    ClaimProposalRecord,
    ConfirmedClaimEntry,
    ConfirmedProfileSnapshot,
    CreateActionPlanCommand,
    CreateClaimProposalSpec,
    CreateMaterialCommand,
    CreatePublicationSelectionCommand,
    DecideProposalCommand,
    DeletionItemReceipt,
    DuplicateProposalConsolidationResult,
    DuplicateProposalGroup,
    DuplicateProposalPreview,
    EvidenceRecord,
    ProfileActionPlanRecord,
    ProfileAgentFocus,
    ProfileAssessmentRecord,
    ProfileClaimRecord,
    ProfileClaimRelationRecord,
    ProfileClaimSourceRecord,
    ProfileClaimVersionRecord,
    ProfileMaterialRecord,
    ProfileMaterialVersionRecord,
    ProfilePresentationRecord,
    ProfileRelationSpec,
    MaterialDeletionPlanRecord,
    PublicationSelectionRecord,
    SaveAssessmentCommand,
    UpdateProfilePresentationCommand,
)

_TERMINAL_PROPOSAL_STATUSES = frozenset({"accepted", "rejected", "superseded"})


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _new_id() -> str:
    return uuid4().hex


class ProfileRepository:
    """Persists profile domain facts in the Runtime SQLite database.

    Every mutation runs inside a ``BEGIN IMMEDIATE`` transaction and uses
    explicit state/version predicates. Material, Evidence, Claim, Proposal,
    Plan and publication state never live in checkpoints.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    # --- Agent session focus (stable IDs only; no conversational content) ---

    def get_agent_focus(
        self, session_id: str, *, workspace_id: str
    ) -> ProfileAgentFocus | None:
        row = self._connection.execute(
            "SELECT * FROM profile_agent_context "
            "WHERE session_id = ? AND workspace_id = ?",
            (session_id, workspace_id),
        ).fetchone()
        return None if row is None else self._agent_focus_record(row)

    def save_agent_focus(
        self,
        session_id: str,
        *,
        workspace_id: str,
        material_id: str | None = None,
        material_version_id: str | None = None,
        claim_id: str | None = None,
        proposal_id: str | None = None,
    ) -> ProfileAgentFocus:
        with self._transaction():
            self._connection.execute(
                "INSERT INTO profile_agent_context "
                "(session_id, workspace_id, material_id, material_version_id, "
                "claim_id, proposal_id) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "workspace_id = excluded.workspace_id, "
                "material_id = excluded.material_id, "
                "material_version_id = excluded.material_version_id, "
                "claim_id = excluded.claim_id, proposal_id = excluded.proposal_id, "
                "version = profile_agent_context.version + 1, "
                "updated_at = CURRENT_TIMESTAMP",
                (
                    session_id,
                    workspace_id,
                    material_id,
                    material_version_id,
                    claim_id,
                    proposal_id,
                ),
            )
        return self.get_agent_focus(session_id, workspace_id=workspace_id)  # type: ignore[return-value]

    @staticmethod
    def _agent_focus_record(row: sqlite3.Row) -> ProfileAgentFocus:
        return ProfileAgentFocus(
            session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            material_id=row["material_id"],
            material_version_id=row["material_version_id"],
            claim_id=row["claim_id"],
            proposal_id=row["proposal_id"],
            version=int(row["version"]),
            updated_at=row["updated_at"],
        )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    # --- Material ---

    def create_material(self, command: CreateMaterialCommand) -> ProfileMaterialRecord:
        with self._transaction():
            existing = self._connection.execute(
                "SELECT id FROM profile_materials "
                "WHERE workspace_id = ? AND primary_role = ? AND lifecycle_status = 'active'",
                (command.workspace_id, command.primary_role),
            ).fetchone()
            if existing is not None:
                raise ProfileMaterialRoleConflict(
                    f"active material already exists for role {command.primary_role!r}"
                )
            material_id = _new_id()
            self._connection.execute(
                "INSERT INTO profile_materials "
                "(id, workspace_id, type, title, primary_role, lifecycle_status) "
                "VALUES (?, ?, ?, ?, ?, 'active')",
                (
                    material_id,
                    command.workspace_id,
                    command.type,
                    command.title,
                    command.primary_role,
                ),
            )
        return self.get_material(material_id)

    def get_material(
        self, material_id: str, *, workspace_id: str | None = None
    ) -> ProfileMaterialRecord:
        row = self._connection.execute(
            "SELECT * FROM profile_materials WHERE id = ? AND deleted_at IS NULL",
            (material_id,),
        ).fetchone()
        if row is None:
            raise ProfileMaterialNotFound(material_id, workspace_id=workspace_id)
        if workspace_id is not None and row["workspace_id"] != workspace_id:
            raise ProfileMaterialNotFound(material_id, workspace_id=workspace_id)
        return self._material_record(row)

    def list_materials(
        self, workspace_id: str, *, include_archived: bool = False
    ) -> tuple[ProfileMaterialRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM profile_materials "
            "WHERE workspace_id = ? AND deleted_at IS NULL "
            + ("" if include_archived else "AND lifecycle_status = 'active' ")
            + "ORDER BY updated_at DESC, id",
            (workspace_id,),
        ).fetchall()
        return tuple(self._material_record(row) for row in rows)

    def archive_material(self, material_id: str) -> ProfileMaterialRecord:
        with self._transaction():
            self._require_material(material_id)
            self._connection.execute(
                "UPDATE profile_materials SET lifecycle_status = 'archived', "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (material_id,),
            )
        return self.get_material(material_id)

    def restore_material(self, material_id: str) -> ProfileMaterialRecord:
        with self._transaction():
            material = self._connection.execute(
                "SELECT * FROM profile_materials WHERE id = ? AND deleted_at IS NULL",
                (material_id,),
            ).fetchone()
            if material is None:
                raise ProfileMaterialNotFound(material_id)
            if material["lifecycle_status"] == "active":
                return self._material_record(material)
            occupied = self._connection.execute(
                "SELECT id FROM profile_materials WHERE workspace_id = ? "
                "AND primary_role = ? AND lifecycle_status = 'active' AND id != ?",
                (material["workspace_id"], material["primary_role"], material_id),
            ).fetchone()
            if occupied is not None:
                raise ProfileMaterialRoleConflict(
                    "another active material already owns this workspace role"
                )
            self._connection.execute(
                "UPDATE profile_materials SET lifecycle_status = 'active', "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (material_id,),
            )
        return self.get_material(material_id)

    def set_primary_version(
        self, material_id: str, version_id: str
    ) -> ProfileMaterialRecord:
        with self._transaction():
            self._require_material(material_id)
            version = self._connection.execute(
                "SELECT id FROM profile_material_versions "
                "WHERE id = ? AND material_id = ? AND deleted_at IS NULL",
                (version_id, material_id),
            ).fetchone()
            if version is None:
                raise ProfileMaterialVersionNotFound(version_id)
            self._connection.execute(
                "UPDATE profile_materials SET current_version_id = ?, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (version_id, material_id),
            )
        return self.get_material(material_id)

    def _require_material(self, material_id: str) -> None:
        row = self._connection.execute(
            "SELECT id FROM profile_materials WHERE id = ? AND deleted_at IS NULL",
            (material_id,),
        ).fetchone()
        if row is None:
            raise ProfileMaterialNotFound(material_id)

    # --- Material version ---

    def add_material_version(
        self,
        *,
        material_id: str,
        source_type: str,
        file_name: str,
        mime_type: str,
        content_sha256: str,
        storage_ref: str,
        text_ref: str,
        created_by: str | None = None,
        derived_from_version_id: str | None = None,
    ) -> ProfileMaterialVersionRecord:
        with self._transaction():
            self._require_material(material_id)
            if derived_from_version_id is not None:
                source = self._connection.execute(
                    "SELECT id FROM profile_material_versions "
                    "WHERE id = ? AND material_id = ?",
                    (derived_from_version_id, material_id),
                ).fetchone()
                if source is None:
                    raise ProfileMaterialVersionNotFound(derived_from_version_id)
            next_number = self._next_version_number(material_id)
            version_id = _new_id()
            self._connection.execute(
                "INSERT INTO profile_material_versions "
                "(id, material_id, version_number, source_type, file_name, "
                "mime_type, content_sha256, storage_ref, text_ref, "
                "processing_status, derived_from_version_id, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?, ?)",
                (
                    version_id,
                    material_id,
                    next_number,
                    source_type,
                    file_name,
                    mime_type,
                    content_sha256,
                    storage_ref,
                    text_ref,
                    derived_from_version_id,
                    created_by,
                ),
            )
        return self.get_material_version(version_id)

    def _next_version_number(self, material_id: str) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(version_number), 0) AS max_no "
            "FROM profile_material_versions WHERE material_id = ?",
            (material_id,),
        ).fetchone()
        return int(row["max_no"]) + 1

    def get_material_version(
        self, version_id: str
    ) -> ProfileMaterialVersionRecord:
        row = self._connection.execute(
            "SELECT * FROM profile_material_versions "
            "WHERE id = ? AND deleted_at IS NULL",
            (version_id,),
        ).fetchone()
        if row is None:
            raise ProfileMaterialVersionNotFound(version_id)
        return self._version_record(row)

    def get_material_version_for_audit(
        self, version_id: str
    ) -> ProfileMaterialVersionRecord:
        row = self._connection.execute(
            "SELECT * FROM profile_material_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise ProfileMaterialVersionNotFound(version_id)
        return self._version_record(row)

    def list_material_versions(
        self, material_id: str
    ) -> tuple[ProfileMaterialVersionRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM profile_material_versions "
            "WHERE material_id = ? AND deleted_at IS NULL "
            "ORDER BY version_number DESC, id",
            (material_id,),
        ).fetchall()
        return tuple(self._version_record(row) for row in rows)

    def find_material_version_by_creator(
        self, material_id: str, created_by: str
    ) -> ProfileMaterialVersionRecord | None:
        row = self._connection.execute(
            "SELECT * FROM profile_material_versions "
            "WHERE material_id = ? AND created_by = ? AND deleted_at IS NULL "
            "ORDER BY version_number, id LIMIT 1",
            (material_id, created_by),
        ).fetchone()
        return None if row is None else self._version_record(row)

    def count_material_versions(self, material_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS total FROM profile_material_versions "
            "WHERE material_id = ? AND deleted_at IS NULL",
            (material_id,),
        ).fetchone()
        return int(row["total"])

    def mark_version_parsed(
        self, version_id: str, *, text_path: str, content_sha256: str
    ) -> ProfileMaterialVersionRecord:
        with self._transaction():
            version = self._connection.execute(
                "SELECT content_sha256 FROM profile_material_versions WHERE id = ?",
                (version_id,),
            ).fetchone()
            if version is None:
                raise ProfileMaterialVersionNotFound(version_id)
            if version["content_sha256"] != content_sha256:
                raise ProfileClaimVersionConflict(
                    "material version content hash changed before parse commit"
                )
            cursor = self._connection.execute(
                "UPDATE profile_material_versions "
                "SET processing_status = 'parsed', text_ref = ? "
                "WHERE id = ? AND processing_status IN ('uploaded', 'parsing', 'parse_failed')",
                (text_path, version_id),
            )
            if cursor.rowcount != 1:
                raise ProfileClaimVersionConflict(
                    "material version processing state changed before parse commit"
                )
        return self.get_material_version(version_id)

    def set_version_processing_status(
        self, version_id: str, status: str
    ) -> ProfileMaterialVersionRecord:
        with self._transaction():
            self._connection.execute(
                "UPDATE profile_material_versions SET processing_status = ? "
                "WHERE id = ?",
                (status, version_id),
            )
        return self.get_material_version(version_id)

    # --- Evidence ---

    def replace_version_evidence(
        self,
        version_id: str,
        evidence: Sequence[dict[str, Any]],
    ) -> tuple[EvidenceRecord, ...]:
        with self._transaction():
            # Tombstone existing live evidence (immutable: never edit in place).
            self._connection.execute(
                "UPDATE profile_evidence SET tombstoned_at = CURRENT_TIMESTAMP, "
                "sanitized_text = '' "
                "WHERE material_version_id = ? AND tombstoned_at IS NULL",
                (version_id,),
            )
            created: list[EvidenceRecord] = []
            for item in evidence:
                evidence_id = _new_id()
                self._connection.execute(
                    "INSERT INTO profile_evidence "
                    "(id, material_version_id, section, start_offset, end_offset, "
                    "sanitized_text, content_sha256, sensitivity) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        evidence_id,
                        version_id,
                        item["section"],
                        int(item["start_offset"]),
                        int(item["end_offset"]),
                        item["sanitized_text"],
                        item["content_sha256"],
                        item.get("sensitivity", "normal"),
                    ),
                )
                created.append(self._evidence_record(
                    self._connection.execute(
                        "SELECT * FROM profile_evidence WHERE id = ?", (evidence_id,)
                    ).fetchone()
                ))
        return tuple(created)

    def get_evidence(self, evidence_id: str) -> EvidenceRecord:
        row = self._connection.execute(
            "SELECT * FROM profile_evidence WHERE id = ?", (evidence_id,)
        ).fetchone()
        if row is None:
            raise ProfileDomainError(f"evidence not found: {evidence_id}")
        return self._evidence_record(row)

    def list_evidence_for_version(
        self, version_id: str
    ) -> tuple[EvidenceRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM profile_evidence "
            "WHERE material_version_id = ? AND tombstoned_at IS NULL "
            "ORDER BY start_offset, id",
            (version_id,),
        ).fetchall()
        return tuple(self._evidence_record(row) for row in rows)

    def proposal_counts_for_version(self, version_id: str) -> dict[str, int]:
        rows = self._connection.execute(
            "SELECT p.status, COUNT(DISTINCT p.id) AS total "
            "FROM profile_claim_proposals p "
            "JOIN json_each(p.evidence_ids_json) refs "
            "JOIN profile_evidence e ON e.id = refs.value "
            "WHERE e.material_version_id = ? GROUP BY p.status",
            (version_id,),
        ).fetchall()
        counts = {"pending": 0, "accepted": 0, "rejected": 0, "superseded": 0}
        for row in rows:
            counts[str(row["status"])] = int(row["total"])
        counts["total"] = sum(counts.values())
        return counts

    def load_operation_receipt(
        self,
        *,
        workspace_id: str,
        operation: str,
        idempotency_key: str,
        request: object,
    ) -> dict[str, Any] | None:
        request_hash = sha256(_canonical_json(request).encode("utf-8")).hexdigest()
        return self._load_idempotency_receipt(
            workspace_id, operation, idempotency_key, request_hash
        )

    def store_operation_receipt(
        self,
        *,
        workspace_id: str,
        operation: str,
        idempotency_key: str,
        request: object,
        result: object,
    ) -> None:
        request_hash = sha256(_canonical_json(request).encode("utf-8")).hexdigest()
        with self._transaction():
            existing = self._load_idempotency_receipt(
                workspace_id, operation, idempotency_key, request_hash
            )
            if existing is None:
                self._store_idempotency_receipt(
                    workspace_id,
                    operation,
                    idempotency_key,
                    request_hash,
                    result,
                )

    def _evidence_ids_for_version(self, version_id: str) -> set[str]:
        return {
            row["id"]
            for row in self._connection.execute(
                "SELECT id FROM profile_evidence "
                "WHERE material_version_id = ? AND tombstoned_at IS NULL",
                (version_id,),
            ).fetchall()
        }

    def _validate_live_evidence(
        self, workspace_id: str, evidence_ids: Sequence[str]
    ) -> None:
        if not evidence_ids:
            return
        placeholders = ",".join("?" for _ in evidence_ids)
        rows = self._connection.execute(
            "SELECT e.id FROM profile_evidence e "
            "JOIN profile_material_versions v ON v.id = e.material_version_id "
            "JOIN profile_materials m ON m.id = v.material_id "
            f"WHERE e.id IN ({placeholders}) AND e.tombstoned_at IS NULL "
            "AND m.workspace_id = ? AND m.deleted_at IS NULL",
            (*evidence_ids, workspace_id),
        ).fetchall()
        if {row["id"] for row in rows} != set(evidence_ids):
            raise ProfileEvidenceMismatch(
                "claim decision references missing or tombstoned evidence"
            )

    # --- Claim proposals ---

    def create_claim_proposals(
        self,
        version_id: str,
        proposals: Sequence[CreateClaimProposalSpec],
        *,
        idempotency_key: str | None = None,
        created_by_execution_id: str | None = None,
    ) -> tuple[ClaimProposalRecord, ...]:
        request = {
            "versionId": version_id,
            "proposals": [
                {
                    "proposalType": item.proposal_type,
                    "targetClaimId": item.target_claim_id,
                    "baseClaimVersionId": item.base_claim_version_id,
                    "proposedValue": item.proposed_value,
                    "reason": item.reason,
                    "evidenceIds": list(item.evidence_ids),
                    "source": item.source,
                    "sourceKind": item.source_kind,
                    "sourceRef": item.source_ref,
                }
                for item in proposals
            ],
        }
        request_hash = self._request_hash(request)
        receipt_key = idempotency_key
        operation = f"claim_proposals.create:{version_id}"
        with self._transaction():
            version = self._connection.execute(
                "SELECT m.workspace_id AS workspace_id "
                "FROM profile_material_versions v "
                "JOIN profile_materials m ON m.id = v.material_id "
                "WHERE v.id = ?",
                (version_id,),
            ).fetchone()
            if version is None:
                raise ProfileMaterialVersionNotFound(version_id)
            workspace_id = version["workspace_id"]
            if receipt_key is not None:
                existing = self._load_idempotency_receipt(
                    workspace_id, operation, receipt_key, request_hash
                )
                if existing is not None:
                    return tuple(
                        self._proposal_record(
                            self._connection.execute(
                                "SELECT * FROM profile_claim_proposals WHERE id = ?",
                                (proposal_id,),
                            ).fetchone()
                        )
                        for proposal_id in existing["proposalIds"]
                    )
            valid_evidence = self._evidence_ids_for_version(version_id)

            created: list[ClaimProposalRecord] = []
            for spec in proposals:
                unknown = set(spec.evidence_ids) - valid_evidence
                if unknown:
                    raise ProfileEvidenceMismatch(
                        "proposal references evidence outside its material version"
                    )
                self._validate_proposal_target(
                    workspace_id=workspace_id,
                    proposal_type=spec.proposal_type,
                    target_claim_id=spec.target_claim_id,
                    base_claim_version_id=spec.base_claim_version_id,
                )
                # An update against an already-confirmed claim records a conflict
                # edge but never overwrites the confirmed version.
                proposal_id = _new_id()
                self._connection.execute(
                    "INSERT INTO profile_claim_proposals "
                    "(id, workspace_id, proposal_type, target_claim_id, "
                    "base_claim_version_id, proposed_value_json, reason, "
                    "evidence_ids_json, status, created_by_execution_id, "
                    "source_kind, source_ref_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                    (
                        proposal_id,
                        workspace_id,
                        spec.proposal_type,
                        spec.target_claim_id,
                        spec.base_claim_version_id,
                        _canonical_json(spec.proposed_value),
                        spec.reason,
                        _canonical_json(list(spec.evidence_ids)),
                        created_by_execution_id,
                        spec.source_kind,
                        _canonical_json(spec.source_ref),
                    ),
                )
                if spec.target_claim_id is not None:
                    self._link_pending_conflict(proposal_id, spec.target_claim_id)
                created.append(self._proposal_record(
                    self._connection.execute(
                        "SELECT * FROM profile_claim_proposals WHERE id = ?",
                        (proposal_id,),
                    ).fetchone()
                ))
            if receipt_key is not None:
                self._store_idempotency_receipt(
                    workspace_id,
                    operation,
                    receipt_key,
                    request_hash,
                    {"proposalIds": [item.id for item in created]},
                )
        return tuple(created)

    def _validate_proposal_target(
        self,
        *,
        workspace_id: str,
        proposal_type: str,
        target_claim_id: str | None,
        base_claim_version_id: str | None,
    ) -> None:
        if proposal_type == "create":
            if target_claim_id is not None or base_claim_version_id is not None:
                raise ProfileClaimVersionConflict(
                    "create proposal cannot target an existing claim version"
                )
            return
        if target_claim_id is None:
            raise ProfileClaimVersionConflict(
                "non-create proposal requires a target claim"
            )
        claim = self._connection.execute(
            "SELECT workspace_id FROM profile_claims WHERE id = ?",
            (target_claim_id,),
        ).fetchone()
        if claim is None or claim["workspace_id"] != workspace_id:
            raise ProfileClaimVersionConflict(
                "proposal target claim is outside the material workspace"
            )
        if base_claim_version_id is not None:
            base = self._connection.execute(
                "SELECT claim_id FROM profile_claim_versions WHERE id = ?",
                (base_claim_version_id,),
            ).fetchone()
            if base is None or base["claim_id"] != target_claim_id:
                raise ProfileClaimVersionConflict(
                    "proposal base version does not belong to its target claim"
                )

    def create_workspace_claim_proposals(
        self,
        workspace_id: str,
        proposals: Sequence[CreateClaimProposalSpec],
        *,
        idempotency_key: str,
        created_by_execution_id: str | None = None,
    ) -> tuple[ClaimProposalRecord, ...]:
        """Create non-material proposals such as explicit conversation updates."""
        request = {
            "workspaceId": workspace_id,
            "proposals": [
                {
                    "proposalType": item.proposal_type,
                    "targetClaimId": item.target_claim_id,
                    "baseClaimVersionId": item.base_claim_version_id,
                    "proposedValue": item.proposed_value,
                    "reason": item.reason,
                    "sourceKind": item.source_kind,
                    "sourceRef": item.source_ref,
                }
                for item in proposals
            ],
        }
        request_hash = self._request_hash(request)
        operation = "claim_proposals.workspace.create"
        with self._transaction():
            existing = self._load_idempotency_receipt(
                workspace_id, operation, idempotency_key, request_hash
            )
            if existing is not None:
                return tuple(
                    self._proposal_record(
                        self._connection.execute(
                            "SELECT * FROM profile_claim_proposals WHERE id = ?",
                            (proposal_id,),
                        ).fetchone()
                    )
                    for proposal_id in existing["proposalIds"]
                )
            created: list[ClaimProposalRecord] = []
            for spec in proposals:
                if spec.evidence_ids:
                    raise ProfileEvidenceMismatch(
                        "workspace proposal cannot reference material evidence"
                    )
                self._validate_proposal_target(
                    workspace_id=workspace_id,
                    proposal_type=spec.proposal_type,
                    target_claim_id=spec.target_claim_id,
                    base_claim_version_id=spec.base_claim_version_id,
                )
                proposal_id = _new_id()
                self._connection.execute(
                    "INSERT INTO profile_claim_proposals "
                    "(id, workspace_id, proposal_type, target_claim_id, "
                    "base_claim_version_id, proposed_value_json, reason, "
                    "evidence_ids_json, status, created_by_execution_id, "
                    "source_kind, source_ref_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, '[]', 'pending', ?, ?, ?)",
                    (
                        proposal_id,
                        workspace_id,
                        spec.proposal_type,
                        spec.target_claim_id,
                        spec.base_claim_version_id,
                        _canonical_json(spec.proposed_value),
                        spec.reason,
                        created_by_execution_id,
                        spec.source_kind,
                        _canonical_json(spec.source_ref),
                    ),
                )
                if spec.target_claim_id is not None:
                    self._link_pending_conflict(proposal_id, spec.target_claim_id)
                created.append(
                    self._proposal_record(
                        self._connection.execute(
                            "SELECT * FROM profile_claim_proposals WHERE id = ?",
                            (proposal_id,),
                        ).fetchone()
                    )
                )
            self._store_idempotency_receipt(
                workspace_id,
                operation,
                idempotency_key,
                request_hash,
                {"proposalIds": [item.id for item in created]},
            )
        return tuple(created)

    def _link_pending_conflict(self, proposal_id: str, claim_id: str) -> None:
        row = self._connection.execute(
            "SELECT current_confirmed_version_id FROM profile_claims WHERE id = ?",
            (claim_id,),
        ).fetchone()
        if row is None or row["current_confirmed_version_id"] is None:
            return
        self._connection.execute(
            "INSERT OR IGNORE INTO profile_claim_conflicts "
            "(id, workspace_id, claim_id, proposal_id, conflicting_claim_version_id) "
            "VALUES (?, "
            "(SELECT workspace_id FROM profile_claims WHERE id = ?), ?, ?, ?)",
            (
                _new_id(),
                claim_id,
                claim_id,
                proposal_id,
                row["current_confirmed_version_id"],
            ),
        )

    def list_proposals(
        self, workspace_id: str, *, status: str | None = None
    ) -> tuple[ClaimProposalRecord, ...]:
        if status is None:
            rows = self._connection.execute(
                "SELECT * FROM profile_claim_proposals "
                "WHERE workspace_id = ? ORDER BY created_at DESC, id",
                (workspace_id,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM profile_claim_proposals "
                "WHERE workspace_id = ? AND status = ? ORDER BY created_at DESC, id",
                (workspace_id, status),
            ).fetchall()
        return tuple(self._proposal_record(row) for row in rows)

    def get_proposal(self, proposal_id: str) -> ClaimProposalRecord:
        row = self._connection.execute(
            "SELECT * FROM profile_claim_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            raise ProfileProposalNotFound(proposal_id)
        return self._proposal_record(row)

    def duplicate_proposal_preview(
        self, workspace_id: str
    ) -> DuplicateProposalPreview:
        proposals = self.list_proposals(workspace_id, status="pending")
        by_identity: dict[str, list[ClaimProposalRecord]] = {}
        for proposal in proposals:
            if proposal.proposal_type != "create":
                continue
            category = proposal.proposed_value.get("category")
            if not isinstance(category, str):
                continue
            identity = claim_identity(category, proposal.proposed_value)
            if identity is not None:
                by_identity.setdefault(identity, []).append(proposal)

        groups: list[DuplicateProposalGroup] = []
        for identity, duplicates in by_identity.items():
            if len(duplicates) < 2:
                continue
            ordered = sorted(
                duplicates,
                key=lambda item: (
                    -proposal_confidence(item.proposed_value),
                    item.created_at,
                    item.id,
                ),
            )
            canonical = ordered[0]
            category = str(canonical.proposed_value["category"])
            merged_value = canonical_claim_value(
                category, canonical.proposed_value
            )
            evidence_ids: list[str] = list(canonical.evidence_ids)
            for proposal in ordered[1:]:
                merged_value = merge_claim_values(
                    merged_value,
                    canonical_claim_value(category, proposal.proposed_value),
                )
                evidence_ids.extend(proposal.evidence_ids)
            label = self._duplicate_proposal_label(category, merged_value)
            groups.append(
                DuplicateProposalGroup(
                    category=category,
                    identity=identity,
                    label=label,
                    canonical_proposal_id=canonical.id,
                    proposal_ids=tuple(sorted(item.id for item in duplicates)),
                    merged_value=merged_value,
                    evidence_count=len(set(evidence_ids)),
                )
            )
        groups.sort(key=lambda item: (item.category, item.label, item.identity))
        return DuplicateProposalPreview(
            workspace_id=workspace_id,
            groups=tuple(groups),
        )

    def consolidate_duplicate_proposals(
        self,
        workspace_id: str,
        *,
        expected_groups: Sequence[Sequence[str]],
        idempotency_key: str,
    ) -> DuplicateProposalConsolidationResult:
        normalized_groups = tuple(
            tuple(sorted(dict.fromkeys(group))) for group in expected_groups
        )
        request = {
            "workspaceId": workspace_id,
            "groups": [list(group) for group in normalized_groups],
        }
        request_hash = self._request_hash(request)
        operation = "claim_proposals.consolidate_duplicates"
        with self._transaction():
            existing = self._load_idempotency_receipt(
                workspace_id, operation, idempotency_key, request_hash
            )
            if existing is not None:
                return DuplicateProposalConsolidationResult(
                    workspace_id=workspace_id,
                    canonical_proposal_ids=tuple(existing["canonicalProposalIds"]),
                    superseded_proposal_ids=tuple(existing["supersededProposalIds"]),
                )

            preview = self.duplicate_proposal_preview(workspace_id)
            current_groups = {
                tuple(sorted(group.proposal_ids)): group for group in preview.groups
            }
            if not normalized_groups or set(normalized_groups) != set(current_groups):
                raise ProfileClaimVersionConflict(
                    "duplicate proposal preview changed"
                )

            canonical_ids: list[str] = []
            superseded_ids: list[str] = []
            for proposal_ids in normalized_groups:
                group = current_groups[proposal_ids]
                rows = self._connection.execute(
                    "SELECT * FROM profile_claim_proposals "
                    f"WHERE workspace_id = ? AND id IN ({','.join('?' for _ in proposal_ids)})",
                    (workspace_id, *proposal_ids),
                ).fetchall()
                if len(rows) != len(proposal_ids):
                    raise ProfileClaimVersionConflict(
                        "duplicate proposal set changed"
                    )
                proposals = [self._proposal_record(row) for row in rows]
                ordered = sorted(
                    proposals,
                    key=lambda item: (
                        -proposal_confidence(item.proposed_value),
                        item.created_at,
                        item.id,
                    ),
                )
                canonical = ordered[0]
                if canonical.id != group.canonical_proposal_id:
                    raise ProfileClaimVersionConflict(
                        "duplicate proposal priority changed"
                    )
                merged_evidence = list(canonical.evidence_ids)
                reasons = [canonical.reason]
                merged_sources = [
                    {
                        "sourceKind": canonical.source_kind,
                        "sourceRef": canonical.source_ref,
                    }
                ]
                for proposal in ordered[1:]:
                    merged_evidence.extend(proposal.evidence_ids)
                    if proposal.reason not in reasons:
                        reasons.append(proposal.reason)
                    source = {
                        "sourceKind": proposal.source_kind,
                        "sourceRef": proposal.source_ref,
                    }
                    if source not in merged_sources:
                        merged_sources.append(source)
                source_ref = dict(canonical.source_ref)
                source_ref["mergedSources"] = merged_sources
                self._connection.execute(
                    "UPDATE profile_claim_proposals SET "
                    "proposed_value_json = ?, reason = ?, evidence_ids_json = ?, "
                    "source_ref_json = ? WHERE id = ? AND status = 'pending'",
                    (
                        _canonical_json(group.merged_value),
                        "；".join(reasons),
                        _canonical_json(list(dict.fromkeys(merged_evidence))),
                        _canonical_json(source_ref),
                        canonical.id,
                    ),
                )
                duplicate_ids = [item.id for item in ordered[1:]]
                self._connection.execute(
                    "UPDATE profile_claim_proposals SET status = 'superseded', "
                    "decided_at = CURRENT_TIMESTAMP "
                    f"WHERE id IN ({','.join('?' for _ in duplicate_ids)}) "
                    "AND status = 'pending'",
                    tuple(duplicate_ids),
                )
                canonical_ids.append(canonical.id)
                superseded_ids.extend(duplicate_ids)

            result = DuplicateProposalConsolidationResult(
                workspace_id=workspace_id,
                canonical_proposal_ids=tuple(canonical_ids),
                superseded_proposal_ids=tuple(superseded_ids),
            )
            self._store_idempotency_receipt(
                workspace_id,
                operation,
                idempotency_key,
                request_hash,
                {
                    "canonicalProposalIds": list(result.canonical_proposal_ids),
                    "supersededProposalIds": list(result.superseded_proposal_ids),
                },
            )
            return result

    @staticmethod
    def _duplicate_proposal_label(
        category: str, value: dict[str, object]
    ) -> str:
        keys_by_category = {
            "skill": ("name",),
            "project": ("name",),
            "experience": ("organization", "title"),
            "education": ("school", "major"),
            "certification": ("name",),
            "achievement": ("title",),
            "link": ("label", "url"),
        }
        parts = [
            str(value[key]).strip()
            for key in keys_by_category.get(category, ())
            if value.get(key)
        ]
        return " · ".join(parts) or category

    # --- Claim decision ---

    def decide_proposal(
        self, proposal_id: str, command: DecideProposalCommand
    ) -> ClaimDecisionResult:
        request = {
            "proposalId": proposal_id,
            "decision": command.decision,
            "expectedStatus": command.expected_status,
            "expectedClaimVersion": command.expected_claim_version,
            "editedValue": command.edited_value,
        }
        request_hash = self._request_hash(request)
        receipt_key = command.idempotency_key
        operation = f"claim_proposal.decision:{proposal_id}"
        with self._transaction():
            row = self._connection.execute(
                "SELECT * FROM profile_claim_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise ProfileProposalNotFound(proposal_id)
            if receipt_key is not None:
                existing = self._load_idempotency_receipt(
                    row["workspace_id"], operation, receipt_key, request_hash
                )
                if existing is not None:
                    return ClaimDecisionResult(
                        proposal_id=existing["proposalId"],
                        status=existing["status"],
                        claim_id=existing.get("claimId"),
                        claim_version_id=existing.get("claimVersionId"),
                        support_status=existing.get("supportStatus"),
                    )
            current_status = row["status"]
            if current_status != command.expected_status:
                if current_status in _TERMINAL_PROPOSAL_STATUSES:
                    raise ProfileProposalAlreadyDecided(
                        f"proposal {proposal_id} already decided"
                    )
                raise ProfileClaimVersionConflict(
                    f"proposal {proposal_id} status {current_status!r} != expected {command.expected_status!r}"
                )

            target_claim = None
            if row["target_claim_id"] is not None:
                target_claim = self._connection.execute(
                    "SELECT * FROM profile_claims WHERE id = ? AND workspace_id = ?",
                    (row["target_claim_id"], row["workspace_id"]),
                ).fetchone()
                if target_claim is None:
                    raise ProfileClaimNotFound(row["target_claim_id"])
                if (
                    command.expected_claim_version is not None
                    and int(target_claim["version"]) != command.expected_claim_version
                ):
                    raise ProfileClaimVersionConflict("claim version changed")
            elif command.expected_claim_version not in {None, 0}:
                raise ProfileClaimVersionConflict(
                    "create proposal expected claim version must be zero"
                )

            value = (
                command.edited_value
                if command.edited_value is not None
                else json.loads(row["proposed_value_json"])
            )
            evidence_ids = tuple(json.loads(row["evidence_ids_json"]))
            support = "supported" if evidence_ids else "unsupported"
            source = "extraction" if row["proposal_type"] == "create" else "assessment"

            if command.decision == "rejected":
                self._connection.execute(
                    "UPDATE profile_claim_proposals SET status = 'rejected', "
                    "decided_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (proposal_id,),
                )
                result = ClaimDecisionResult(
                    proposal_id=proposal_id, status="rejected"
                )
                if receipt_key is not None:
                    self._store_decision_receipt(
                        row["workspace_id"], operation, receipt_key, request_hash, result
                    )
                return result

            self._validate_live_evidence(row["workspace_id"], evidence_ids)

            # Acceptance path.
            if row["proposal_type"] == "create":
                claim_id = _new_id()
                claim_type = str(value.get("category", "skill"))
                self._connection.execute(
                    "INSERT INTO profile_claims "
                    "(id, workspace_id, claim_type, current_confirmed_version_id, version) "
                    "VALUES (?, ?, ?, NULL, 1)",
                    (claim_id, row["workspace_id"], claim_type),
                )
                version_id = _new_id()
                self._connection.execute(
                    "INSERT INTO profile_claim_versions "
                    "(id, claim_id, version, value_json, status, support_status, "
                    "evidence_ids_json, source, confirmed_at) "
                    "VALUES (?, ?, 1, ?, 'confirmed', ?, ?, ?, CURRENT_TIMESTAMP)",
                    (
                        version_id,
                        claim_id,
                        _canonical_json(value),
                        support,
                        _canonical_json(list(evidence_ids)),
                        source,
                    ),
                )
                self._connection.execute(
                    "UPDATE profile_claims SET current_confirmed_version_id = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (version_id, claim_id),
                )
            else:
                # update / reject-proposal acceptance: append a new confirmed version.
                claim_id = row["target_claim_id"]
                if claim_id is None:
                    raise ProfileDomainError("update proposal missing target claim")
                claim = self._connection.execute(
                    "SELECT * FROM profile_claims WHERE id = ?", (claim_id,)
                ).fetchone()
                if claim is None:
                    raise ProfileClaimNotFound(claim_id)
                if (
                    row["base_claim_version_id"] is not None
                    and row["base_claim_version_id"] != claim["current_confirmed_version_id"]
                ):
                    raise ProfileClaimVersionConflict("base claim version changed")
                next_version = int(claim["version"]) + 1
                version_id = _new_id()
                self._connection.execute(
                    "UPDATE profile_claim_versions SET status = 'superseded' "
                    "WHERE id = ?",
                    (claim["current_confirmed_version_id"],),
                )
                self._connection.execute(
                    "INSERT INTO profile_claim_versions "
                    "(id, claim_id, version, value_json, status, support_status, "
                    "evidence_ids_json, source, expected_previous_version, confirmed_at) "
                    "VALUES (?, ?, ?, ?, 'confirmed', ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                    (
                        version_id,
                        claim_id,
                        next_version,
                        _canonical_json(value),
                        support,
                        _canonical_json(list(evidence_ids)),
                        source,
                        int(claim["version"]),
                    ),
                )
                self._connection.execute(
                    "UPDATE profile_claims SET current_confirmed_version_id = ?, "
                    "version = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (version_id, next_version, claim_id),
                )

            self._connection.execute(
                "UPDATE profile_claim_proposals SET status = 'accepted', "
                "decided_at = CURRENT_TIMESTAMP WHERE id = ?",
                (proposal_id,),
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO profile_claim_sources "
                "(id, workspace_id, claim_version_id, source_kind, source_ref_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    _new_id(),
                    row["workspace_id"],
                    version_id,
                    row["source_kind"],
                    row["source_ref_json"],
                ),
            )
            result = ClaimDecisionResult(
                proposal_id=proposal_id,
                status="accepted",
                claim_id=claim_id,
                claim_version_id=version_id,
                support_status=support,
            )
            if receipt_key is not None:
                self._store_decision_receipt(
                    row["workspace_id"], operation, receipt_key, request_hash, result
                )
            return result

    def batch_decide_proposals(
        self, commands: Sequence[DecideProposalCommand]
    ) -> BatchClaimDecisionResult:
        completed: list[ClaimDecisionResult] = []
        conflicts: list[str] = []
        failed: list[str] = []
        for command in commands:
            try:
                completed.append(self.decide_proposal(command.proposal_id, command))
            except (ProfileProposalAlreadyDecided, ProfileClaimVersionConflict):
                conflicts.append(command.proposal_id)
            except ProfileDomainError:
                failed.append(command.proposal_id)
        return BatchClaimDecisionResult(
            completed=tuple(completed),
            conflicts=tuple(conflicts),
            failed=tuple(failed),
        )

    # --- Direct confirmed profile cards ---

    def append_confirmed_claim(
        self, command: AppendConfirmedClaimCommand
    ) -> ProfileClaimVersionRecord:
        request = {
            "workspaceId": command.workspace_id,
            "claimId": command.claim_id,
            "claimType": command.claim_type,
            "value": command.value,
            "sourceKind": command.source_kind,
            "sourceRef": command.source_ref,
            "expectedClaimVersion": command.expected_claim_version,
        }
        request_hash = self._request_hash(request)
        operation = f"profile_card.append:{command.claim_id or 'new'}"
        with self._transaction():
            existing = self._load_idempotency_receipt(
                command.workspace_id,
                operation,
                command.idempotency_key,
                request_hash,
            )
            if existing is not None:
                return self.get_claim_version(existing["claimVersionId"])

            if command.claim_id is None:
                if command.expected_claim_version != 0:
                    raise ProfileClaimVersionConflict(
                        "new profile card expects version zero"
                    )
                claim_id = _new_id()
                self._connection.execute(
                    "INSERT INTO profile_claims "
                    "(id, workspace_id, claim_type, version) "
                    "VALUES (?, ?, ?, 1)",
                    (claim_id, command.workspace_id, command.claim_type),
                )
                next_version = 1
                previous_version_id = None
            else:
                claim = self._connection.execute(
                    "SELECT * FROM profile_claims "
                    "WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
                    (command.claim_id, command.workspace_id),
                ).fetchone()
                if claim is None:
                    raise ProfileClaimNotFound(command.claim_id)
                if claim["claim_type"] != command.claim_type:
                    raise ProfileClaimVersionConflict(
                        "profile card category cannot change"
                    )
                if int(claim["version"]) != command.expected_claim_version:
                    raise ProfileClaimVersionConflict(
                        "profile card version changed"
                    )
                claim_id = command.claim_id
                next_version = int(claim["version"]) + 1
                previous_version_id = claim["current_confirmed_version_id"]
                if previous_version_id is not None:
                    self._connection.execute(
                        "UPDATE profile_claim_versions SET status = 'superseded' "
                        "WHERE id = ?",
                        (previous_version_id,),
                    )

            version_id = _new_id()
            self._connection.execute(
                "INSERT INTO profile_claim_versions "
                "(id, claim_id, version, value_json, status, support_status, "
                "evidence_ids_json, source, expected_previous_version, confirmed_at) "
                "VALUES (?, ?, ?, ?, 'confirmed', 'unsupported', '[]', ?, ?, "
                "CURRENT_TIMESTAMP)",
                (
                    version_id,
                    claim_id,
                    next_version,
                    _canonical_json(command.value),
                    command.source_kind,
                    None
                    if previous_version_id is None
                    else command.expected_claim_version,
                ),
            )
            self._connection.execute(
                "INSERT INTO profile_claim_sources "
                "(id, workspace_id, claim_version_id, source_kind, source_ref_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    _new_id(),
                    command.workspace_id,
                    version_id,
                    command.source_kind,
                    _canonical_json(command.source_ref),
                ),
            )
            self._connection.execute(
                "UPDATE profile_claims SET current_confirmed_version_id = ?, "
                "version = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (version_id, next_version, claim_id),
            )
            self._store_idempotency_receipt(
                command.workspace_id,
                operation,
                command.idempotency_key,
                request_hash,
                {"claimId": claim_id, "claimVersionId": version_id},
            )
        return self.get_claim_version(version_id)

    def list_claim_sources(
        self, claim_version_id: str
    ) -> tuple[ProfileClaimSourceRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM profile_claim_sources "
            "WHERE claim_version_id = ? AND status <> 'superseded' "
            "ORDER BY created_at, id",
            (claim_version_id,),
        ).fetchall()
        return tuple(self._claim_source_record(row) for row in rows)

    def attach_claim_source(
        self,
        *,
        workspace_id: str,
        claim_version_id: str,
        source_kind: str,
        source_ref: dict[str, object],
    ) -> tuple[ProfileClaimSourceRecord, bool]:
        with self._transaction():
            version = self._connection.execute(
                "SELECT v.id FROM profile_claim_versions v "
                "JOIN profile_claims c ON c.id = v.claim_id "
                "WHERE v.id = ? AND c.workspace_id = ? AND c.deleted_at IS NULL",
                (claim_version_id, workspace_id),
            ).fetchone()
            if version is None:
                raise ProfileClaimNotFound(claim_version_id)
            canonical_ref = _canonical_json(source_ref)
            existing = self._connection.execute(
                "SELECT * FROM profile_claim_sources "
                "WHERE claim_version_id = ? AND source_kind = ? "
                "AND source_ref_json = ?",
                (claim_version_id, source_kind, canonical_ref),
            ).fetchone()
            if existing is not None:
                return self._claim_source_record(existing), False
            source_id = _new_id()
            self._connection.execute(
                "INSERT INTO profile_claim_sources "
                "(id, workspace_id, claim_version_id, source_kind, source_ref_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    source_id,
                    workspace_id,
                    claim_version_id,
                    source_kind,
                    canonical_ref,
                ),
            )
            created = self._connection.execute(
                "SELECT * FROM profile_claim_sources WHERE id = ?", (source_id,)
            ).fetchone()
            return self._claim_source_record(created), True

    def delete_confirmed_claim(
        self,
        *,
        workspace_id: str,
        claim_id: str,
        expected_claim_version: int,
        idempotency_key: str,
    ) -> None:
        request = {
            "workspaceId": workspace_id,
            "claimId": claim_id,
            "expectedClaimVersion": expected_claim_version,
        }
        request_hash = self._request_hash(request)
        operation = f"profile_card.delete:{claim_id}"
        with self._transaction():
            receipt = self._load_idempotency_receipt(
                workspace_id, operation, idempotency_key, request_hash
            )
            if receipt is not None:
                return
            claim = self._connection.execute(
                "SELECT version FROM profile_claims "
                "WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
                (claim_id, workspace_id),
            ).fetchone()
            if claim is None:
                raise ProfileClaimNotFound(claim_id)
            if int(claim["version"]) != expected_claim_version:
                raise ProfileClaimVersionConflict("profile card version changed")
            self._connection.execute(
                "UPDATE profile_claims SET deleted_at = CURRENT_TIMESTAMP, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (claim_id,),
            )
            self._connection.execute(
                "DELETE FROM profile_claim_relations "
                "WHERE workspace_id = ? "
                "AND (from_claim_id = ? OR to_claim_id = ?)",
                (workspace_id, claim_id, claim_id),
            )
            self._store_idempotency_receipt(
                workspace_id,
                operation,
                idempotency_key,
                request_hash,
                {"claimId": claim_id, "status": "deleted"},
            )

    def replace_claim_relations(
        self,
        workspace_id: str,
        claim_id: str,
        relations: Sequence[ProfileRelationSpec],
    ) -> tuple[ProfileClaimRelationRecord, ...]:
        with self._transaction():
            source = self._connection.execute(
                "SELECT id FROM profile_claims "
                "WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
                (claim_id, workspace_id),
            ).fetchone()
            if source is None:
                raise ProfileClaimNotFound(claim_id)
            target_ids = {item.target_claim_id for item in relations}
            if claim_id in target_ids:
                raise ProfileClaimVersionConflict(
                    "profile card cannot relate to itself"
                )
            if target_ids:
                placeholders = ",".join("?" for _ in target_ids)
                rows = self._connection.execute(
                    "SELECT id FROM profile_claims "
                    f"WHERE id IN ({placeholders}) AND workspace_id = ? "
                    "AND deleted_at IS NULL",
                    (*target_ids, workspace_id),
                ).fetchall()
                if {row["id"] for row in rows} != target_ids:
                    raise ProfileClaimVersionConflict(
                        "profile relation target is outside the workspace"
                    )
            self._connection.execute(
                "DELETE FROM profile_claim_relations "
                "WHERE workspace_id = ? AND from_claim_id = ?",
                (workspace_id, claim_id),
            )
            for item in relations:
                self._connection.execute(
                    "INSERT INTO profile_claim_relations "
                    "(id, workspace_id, from_claim_id, to_claim_id, relation_type) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        _new_id(),
                        workspace_id,
                        claim_id,
                        item.target_claim_id,
                        item.relation_type,
                    ),
                )
        return self.list_claim_relations(workspace_id, from_claim_id=claim_id)

    def list_claim_relations(
        self,
        workspace_id: str,
        *,
        from_claim_id: str | None = None,
        to_claim_id: str | None = None,
    ) -> tuple[ProfileClaimRelationRecord, ...]:
        filters = ["workspace_id = ?"]
        values: list[object] = [workspace_id]
        if from_claim_id is not None:
            filters.append("from_claim_id = ?")
            values.append(from_claim_id)
        if to_claim_id is not None:
            filters.append("to_claim_id = ?")
            values.append(to_claim_id)
        rows = self._connection.execute(
            "SELECT * FROM profile_claim_relations WHERE "
            + " AND ".join(filters)
            + " ORDER BY created_at, id",
            tuple(values),
        ).fetchall()
        return tuple(self._claim_relation_record(row) for row in rows)

    def get_profile_presentation(
        self, workspace_id: str
    ) -> ProfilePresentationRecord:
        row = self._connection.execute(
            "SELECT * FROM profile_presentations WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        if row is None:
            return ProfilePresentationRecord(
                workspace_id=workspace_id,
                summary_claim_id=None,
                primary_direction_claim_id=None,
                featured_claim_ids=(),
                version=0,
                updated_at="",
            )
        return self._profile_presentation_record(row)

    def update_profile_presentation(
        self, command: UpdateProfilePresentationCommand
    ) -> ProfilePresentationRecord:
        request = {
            "workspaceId": command.workspace_id,
            "summaryClaimId": command.summary_claim_id,
            "primaryDirectionClaimId": command.primary_direction_claim_id,
            "featuredClaimIds": list(command.featured_claim_ids),
            "expectedVersion": command.expected_version,
        }
        request_hash = self._request_hash(request)
        operation = "profile_presentation.update"
        with self._transaction():
            receipt = self._load_idempotency_receipt(
                command.workspace_id,
                operation,
                command.idempotency_key,
                request_hash,
            )
            if receipt is not None:
                return self.get_profile_presentation(command.workspace_id)
            current = self._connection.execute(
                "SELECT version FROM profile_presentations WHERE workspace_id = ?",
                (command.workspace_id,),
            ).fetchone()
            current_version = 0 if current is None else int(current["version"])
            if current_version != command.expected_version:
                raise ProfileClaimVersionConflict(
                    "profile presentation version changed"
                )
            self._validate_presentation_claim(
                command.workspace_id, command.summary_claim_id, "summary"
            )
            self._validate_presentation_claim(
                command.workspace_id,
                command.primary_direction_claim_id,
                "direction",
            )
            for claim_id in command.featured_claim_ids:
                self._validate_presentation_claim(
                    command.workspace_id, claim_id, "highlight"
                )
            next_version = current_version + 1
            self._connection.execute(
                "INSERT INTO profile_presentations "
                "(workspace_id, summary_claim_id, primary_direction_claim_id, "
                "featured_claim_ids_json, version) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(workspace_id) DO UPDATE SET "
                "summary_claim_id = excluded.summary_claim_id, "
                "primary_direction_claim_id = excluded.primary_direction_claim_id, "
                "featured_claim_ids_json = excluded.featured_claim_ids_json, "
                "version = excluded.version, updated_at = CURRENT_TIMESTAMP",
                (
                    command.workspace_id,
                    command.summary_claim_id,
                    command.primary_direction_claim_id,
                    _canonical_json(list(command.featured_claim_ids)),
                    next_version,
                ),
            )
            self._store_idempotency_receipt(
                command.workspace_id,
                operation,
                command.idempotency_key,
                request_hash,
                {"version": next_version},
            )
        return self.get_profile_presentation(command.workspace_id)

    def _validate_presentation_claim(
        self, workspace_id: str, claim_id: str | None, expected_type: str
    ) -> None:
        if claim_id is None:
            return
        row = self._connection.execute(
            "SELECT claim_type, current_confirmed_version_id "
            "FROM profile_claims WHERE id = ? AND workspace_id = ? "
            "AND deleted_at IS NULL",
            (claim_id, workspace_id),
        ).fetchone()
        if (
            row is None
            or row["claim_type"] != expected_type
            or row["current_confirmed_version_id"] is None
        ):
            raise ProfileClaimVersionConflict(
                f"profile presentation requires confirmed {expected_type}"
            )

    # --- Claim read ---

    def list_claims(self, workspace_id: str) -> tuple[ProfileClaimRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM profile_claims WHERE workspace_id = ? "
            "AND deleted_at IS NULL "
            "ORDER BY claim_type, updated_at DESC, id",
            (workspace_id,),
        ).fetchall()
        return tuple(self._claim_record(row) for row in rows)

    def get_claim(self, claim_id: str) -> ProfileClaimRecord:
        row = self._connection.execute(
            "SELECT * FROM profile_claims WHERE id = ? AND deleted_at IS NULL",
            (claim_id,),
        ).fetchone()
        if row is None:
            raise ProfileClaimNotFound(claim_id)
        return self._claim_record(row)

    def get_claim_version(
        self, version_id: str
    ) -> ProfileClaimVersionRecord:
        row = self._connection.execute(
            "SELECT * FROM profile_claim_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise ProfileClaimNotFound(version_id)
        return self._claim_version_record(row)

    def list_claim_versions(
        self, claim_id: str
    ) -> tuple[ProfileClaimVersionRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM profile_claim_versions "
            "WHERE claim_id = ? ORDER BY version DESC, id",
            (claim_id,),
        ).fetchall()
        return tuple(self._claim_version_record(row) for row in rows)

    def list_conflicts_for_claim(
        self, claim_id: str
    ) -> tuple[ClaimConflictRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM profile_claim_conflicts "
            "WHERE claim_id = ? ORDER BY created_at, id",
            (claim_id,),
        ).fetchall()
        return tuple(self._conflict_record(row) for row in rows)

    def mark_claim_unsupported(self, claim_id: str, *, reason: str) -> None:
        with self._transaction():
            claim = self._connection.execute(
                "SELECT current_confirmed_version_id FROM profile_claims WHERE id = ?",
                (claim_id,),
            ).fetchone()
            if claim is None:
                raise ProfileClaimNotFound(claim_id)
            if claim["current_confirmed_version_id"] is None:
                return
            self._connection.execute(
                "UPDATE profile_claim_versions SET support_status = 'unsupported' "
                "WHERE id = ?",
                (claim["current_confirmed_version_id"],),
            )

    # --- Profile snapshot ---

    def profile_snapshot(
        self, workspace_id: str
    ) -> ConfirmedProfileSnapshot:
        rows = self._connection.execute(
            "SELECT c.id AS claim_id, c.claim_type, c.current_confirmed_version_id, "
            "c.version AS claim_version_no, v.id AS version_id, v.version, "
            "v.value_json, v.support_status, v.evidence_ids_json "
            "FROM profile_claims c "
            "JOIN profile_claim_versions v ON v.id = c.current_confirmed_version_id "
            "WHERE c.workspace_id = ? AND c.deleted_at IS NULL "
            "ORDER BY c.claim_type, c.id",
            (workspace_id,),
        ).fetchall()
        entries = tuple(
            ConfirmedClaimEntry(
                claim_id=row["claim_id"],
                claim_type=row["claim_type"],
                claim_version_id=row["version_id"],
                version_number=int(row["version"]),
                value=json.loads(row["value_json"]),
                support_status=row["support_status"],
                evidence_ids=tuple(json.loads(row["evidence_ids_json"])),
                sources=self.list_claim_sources(row["version_id"]),
            )
            for row in rows
        )
        materials = self.list_materials(workspace_id)
        return ConfirmedProfileSnapshot(
            workspace_id=workspace_id,
            profile_version=self._compute_profile_version(entries),
            claims=entries,
            materials=materials,
        )

    @staticmethod
    def _compute_profile_version(
        entries: Sequence[ConfirmedClaimEntry],
    ) -> str | None:
        if not entries:
            return None
        digest = sha256()
        for entry in entries:
            digest.update(entry.claim_id.encode("utf-8"))
            digest.update(b":")
            digest.update(str(entry.version_number).encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()

    # --- Assessment ---

    def save_assessment(
        self, command: SaveAssessmentCommand
    ) -> ProfileAssessmentRecord:
        with self._transaction():
            if command.created_by_execution_id is not None:
                existing = self._connection.execute(
                    "SELECT * FROM profile_assessments "
                    "WHERE workspace_id = ? AND created_by_execution_id = ? "
                    "ORDER BY created_at, id LIMIT 1",
                    (command.workspace_id, command.created_by_execution_id),
                ).fetchone()
                if existing is not None:
                    record = ProfileAssessmentRecord(
                        id=existing["id"],
                        workspace_id=existing["workspace_id"],
                        base_profile_version=existing["base_profile_version"],
                        result=json.loads(existing["result_json"]),
                        created_by_execution_id=existing[
                            "created_by_execution_id"
                        ],
                        created_at=existing["created_at"],
                    )
                    if (
                        record.base_profile_version != command.base_profile_version
                        or record.result != command.result
                    ):
                        raise ProfileIdempotencyConflict(
                            "assessment execution was reused with different input"
                        )
                    return record
            assessment_id = _new_id()
            self._connection.execute(
                "INSERT INTO profile_assessments "
                "(id, workspace_id, base_profile_version, result_json, "
                "created_by_execution_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    assessment_id,
                    command.workspace_id,
                    command.base_profile_version,
                    _canonical_json(command.result),
                    command.created_by_execution_id,
                ),
            )
        return self.get_assessment(assessment_id)

    def get_assessment(
        self, assessment_id: str
    ) -> ProfileAssessmentRecord:
        row = self._connection.execute(
            "SELECT * FROM profile_assessments WHERE id = ?", (assessment_id,)
        ).fetchone()
        if row is None:
            raise ProfileAssessmentNotFound(assessment_id)
        return ProfileAssessmentRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            base_profile_version=row["base_profile_version"],
            result=json.loads(row["result_json"]),
            created_by_execution_id=row["created_by_execution_id"],
            created_at=row["created_at"],
        )

    # --- Action plan ---

    def create_action_plan(
        self, command: CreateActionPlanCommand
    ) -> ProfileActionPlanRecord:
        if command.execution_id is not None:
            existing = self._connection.execute(
                "SELECT id FROM profile_action_plans "
                "WHERE execution_id = ? ORDER BY created_at, id LIMIT 1",
                (command.execution_id,),
            ).fetchone()
            if existing is not None:
                plan = self.get_action_plan(existing["id"])
                if not self._action_plan_matches_command(plan, command):
                    raise ProfileIdempotencyConflict(
                        "action plan execution was reused with different input"
                    )
                return plan
        with self._transaction():
            plan_id = _new_id()
            self._connection.execute(
                "INSERT INTO profile_action_plans "
                "(id, workspace_id, session_id, execution_id, request_summary, "
                "base_profile_version, selection_snapshot_json, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed')",
                (
                    plan_id,
                    command.workspace_id,
                    command.session_id,
                    command.execution_id,
                    command.request_summary,
                    command.base_profile_version,
                    _canonical_json(command.selection_snapshot),
                ),
            )
            for spec in command.items:
                self._connection.execute(
                    "INSERT INTO profile_action_plan_items "
                    "(id, plan_id, item_id, ordinal, operation, target_json, "
                    "expected_version, before_json, after_json, evidence_ids_json, "
                    "status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                    (
                        _new_id(),
                        plan_id,
                        spec.item_id,
                        spec.ordinal,
                        spec.operation,
                        _canonical_json(spec.target),
                        spec.expected_version,
                        _canonical_json(spec.before) if spec.before is not None else None,
                        _canonical_json(spec.after),
                        _canonical_json(list(spec.evidence_ids)),
                    ),
                )
        return self.get_action_plan(plan_id)

    @staticmethod
    def _action_plan_matches_command(
        plan: ProfileActionPlanRecord, command: CreateActionPlanCommand
    ) -> bool:
        if (
            plan.workspace_id != command.workspace_id
            or plan.session_id != command.session_id
            or plan.execution_id != command.execution_id
            or plan.request_summary != command.request_summary
            or plan.base_profile_version != command.base_profile_version
            or plan.selection_snapshot != command.selection_snapshot
            or len(plan.items) != len(command.items)
        ):
            return False
        return all(
            (
                current.item_id,
                current.ordinal,
                current.operation,
                current.target,
                current.expected_version,
                current.before,
                current.after,
                current.evidence_ids,
            )
            == (
                proposed.item_id,
                proposed.ordinal,
                proposed.operation,
                proposed.target,
                proposed.expected_version,
                proposed.before,
                proposed.after,
                proposed.evidence_ids,
            )
            for current, proposed in zip(plan.items, command.items, strict=True)
        )

    def get_action_plan(self, plan_id: str) -> ProfileActionPlanRecord:
        row = self._connection.execute(
            "SELECT * FROM profile_action_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            raise ProfileActionPlanNotFound(plan_id)
        items = self._connection.execute(
            "SELECT * FROM profile_action_plan_items "
            "WHERE plan_id = ? ORDER BY ordinal, id",
            (plan_id,),
        ).fetchall()
        return ProfileActionPlanRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            execution_id=row["execution_id"],
            request_summary=row["request_summary"],
            base_profile_version=row["base_profile_version"],
            selection_snapshot=json.loads(row["selection_snapshot_json"]),
            items=tuple(self._action_plan_item_record(item) for item in items),
            status=row["status"],
            version=int(row["version"]),
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            confirmed_at=row["confirmed_at"],
            completed_at=row["completed_at"],
        )

    def validate_action_plan_fresh(self, plan_id: str) -> None:
        plan = self.get_action_plan(plan_id)
        current = self.profile_snapshot(plan.workspace_id).profile_version
        if plan.base_profile_version != (current or ""):
            raise ProfileSnapshotChanged(
                "action plan base profile version is stale"
            )

    def update_action_plan_status(
        self, plan_id: str, *, status: str
    ) -> ProfileActionPlanRecord:
        with self._transaction():
            self._connection.execute(
                "UPDATE profile_action_plans SET status = ?, "
                "version = version + 1 WHERE id = ?",
                (status, plan_id),
            )
        return self.get_action_plan(plan_id)

    def transition_action_plan_status(
        self,
        plan_id: str,
        *,
        expected_version: int,
        from_statuses: tuple[str, ...],
        status: str,
    ) -> ProfileActionPlanRecord:
        if not from_statuses:
            raise ValueError("from_statuses must not be empty")
        placeholders = ",".join("?" for _ in from_statuses)
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE profile_action_plans SET status = ?, version = version + 1, "
                "confirmed_at = CASE WHEN ? = 'executing' THEN "
                "COALESCE(confirmed_at, CURRENT_TIMESTAMP) ELSE confirmed_at END, "
                "completed_at = CASE WHEN ? IN ('completed', 'partially_completed', "
                "'failed', 'cancelled') THEN CURRENT_TIMESTAMP ELSE completed_at END "
                f"WHERE id = ? AND version = ? AND status IN ({placeholders})",
                (status, status, status, plan_id, expected_version, *from_statuses),
            )
            if cursor.rowcount != 1:
                if self._connection.execute(
                    "SELECT 1 FROM profile_action_plans WHERE id = ?", (plan_id,)
                ).fetchone() is None:
                    raise ProfileActionPlanNotFound(plan_id)
                raise ProfileClaimVersionConflict("action plan state or version changed")
        return self.get_action_plan(plan_id)

    def apply_action_plan_item(
        self,
        item_id: str,
        *,
        expected_claim_version: int | None = None,
        status: str = "completed",
        receipt_id: str | None = None,
        error_code: str | None = None,
    ) -> ActionPlanItemRecord:
        with self._transaction():
            row = self._connection.execute(
                "SELECT * FROM profile_action_plan_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise ProfileActionPlanNotFound(item_id)
            if row["status"] not in {"pending", "failed"}:
                raise ProfileDomainError(
                    f"action plan item {item_id} already {row['status']}"
                )
            declared_expected = row["expected_version"]
            if (
                expected_claim_version is not None
                and declared_expected != expected_claim_version
            ):
                raise ProfileClaimVersionConflict(
                    "action plan item expected claim version changed"
                )
            target = json.loads(row["target_json"])
            claim_id = target.get("claimId") or target.get("claim_id")
            if declared_expected is not None:
                if not claim_id:
                    raise ProfileClaimVersionConflict(
                        "versioned action plan item is missing its target claim"
                    )
                claim = self._connection.execute(
                    "SELECT version FROM profile_claims WHERE id = ?",
                    (claim_id,),
                ).fetchone()
                if claim is None or int(claim["version"]) != int(declared_expected):
                    raise ProfileClaimVersionConflict(
                        "target claim changed after action plan creation"
                    )
            self._connection.execute(
                "UPDATE profile_action_plan_items SET status = ?, receipt_id = ?, "
                "error_code = ? WHERE id = ?",
                (status, receipt_id, error_code, row["id"]),
            )
        return self._action_plan_item_record(
            self._connection.execute(
                "SELECT * FROM profile_action_plan_items WHERE id = ?", (row["id"],)
            ).fetchone()
        )

    def record_action_plan_item_failure(
        self, item_id: str, *, error_code: str
    ) -> ActionPlanItemRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE profile_action_plan_items SET status = 'failed', "
                "error_code = ?, receipt_id = NULL WHERE item_id = ? "
                "AND status IN ('pending', 'failed')",
                (error_code, item_id),
            )
            if cursor.rowcount != 1:
                raise ProfileActionPlanNotFound(item_id)
        row = self._connection.execute(
            "SELECT * FROM profile_action_plan_items WHERE item_id = ?", (item_id,)
        ).fetchone()
        return self._action_plan_item_record(row)

    # --- Publication selection ---

    def create_publication_selection(
        self, command: CreatePublicationSelectionCommand
    ) -> PublicationSelectionRecord:
        request = {
            "workspaceId": command.workspace_id,
            "profileVersion": command.profile_version,
            "claimVersionIds": list(command.claim_version_ids),
            "excludedSensitiveFields": list(command.excluded_sensitive_fields),
        }
        request_hash = self._request_hash(request)
        receipt_key = command.idempotency_key
        operation = "publication_selection.create"
        with self._transaction():
            if receipt_key is not None:
                existing = self._load_idempotency_receipt(
                    command.workspace_id, operation, receipt_key, request_hash
                )
                if existing is not None:
                    return self.get_publication_selection(existing["selectionId"])
            for claim_version_id in command.claim_version_ids:
                claim_version = self._connection.execute(
                    "SELECT c.workspace_id, c.current_confirmed_version_id "
                    "FROM profile_claim_versions v "
                    "JOIN profile_claims c ON c.id = v.claim_id WHERE v.id = ?",
                    (claim_version_id,),
                ).fetchone()
                if (
                    claim_version is None
                    or claim_version["workspace_id"] != command.workspace_id
                    or claim_version["current_confirmed_version_id"] != claim_version_id
                ):
                    raise ProfileClaimVersionConflict(
                        "publication selection contains a foreign or unconfirmed claim version"
                    )
            current_profile_version = (
                self.profile_snapshot(command.workspace_id).profile_version or ""
            )
            if current_profile_version != command.profile_version:
                raise ProfileSnapshotChanged(
                    "publication selection profile snapshot is stale"
                )
            next_version = self._next_selection_version(command.workspace_id)
            selection_id = _new_id()
            self._connection.execute(
                "INSERT INTO profile_publication_selections "
                "(id, workspace_id, profile_version, "
                "excluded_sensitive_fields_json, status, version) "
                "VALUES (?, ?, ?, ?, 'draft', ?)",
                (
                    selection_id,
                    command.workspace_id,
                    command.profile_version,
                    _canonical_json(list(command.excluded_sensitive_fields)),
                    next_version,
                ),
            )
            for claim_version_id in command.claim_version_ids:
                self._connection.execute(
                    "INSERT OR IGNORE INTO profile_publication_selection_items "
                    "(selection_id, claim_version_id) VALUES (?, ?)",
                    (selection_id, claim_version_id),
                )
            # Prior drafts are superseded by the new selection.
            self._connection.execute(
                "UPDATE profile_publication_selections SET status = 'superseded', "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE workspace_id = ? AND id != ? AND status = 'draft'",
                (command.workspace_id, selection_id),
            )
            if receipt_key is not None:
                self._store_idempotency_receipt(
                    command.workspace_id,
                    operation,
                    receipt_key,
                    request_hash,
                    {"selectionId": selection_id},
                )
        return self.get_publication_selection(selection_id)

    @staticmethod
    def _request_hash(request: object) -> str:
        return sha256(_canonical_json(request).encode("utf-8")).hexdigest()

    def _load_idempotency_receipt(
        self,
        workspace_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT request_hash, result_json FROM profile_idempotency_receipts "
            "WHERE workspace_id = ? AND operation = ? AND idempotency_key = ?",
            (workspace_id, operation, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise ProfileIdempotencyConflict(
                "profile idempotency key was reused with a different request"
            )
        return json.loads(row["result_json"])

    def _store_idempotency_receipt(
        self,
        workspace_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        result: object,
    ) -> None:
        self._connection.execute(
            "INSERT INTO profile_idempotency_receipts "
            "(id, workspace_id, operation, idempotency_key, request_hash, result_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                _new_id(),
                workspace_id,
                operation,
                idempotency_key,
                request_hash,
                _canonical_json(result),
            ),
        )

    def _store_decision_receipt(
        self,
        workspace_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        result: ClaimDecisionResult,
    ) -> None:
        self._store_idempotency_receipt(
            workspace_id,
            operation,
            idempotency_key,
            request_hash,
            {
                "proposalId": result.proposal_id,
                "status": result.status,
                "claimId": result.claim_id,
                "claimVersionId": result.claim_version_id,
                "supportStatus": result.support_status,
            },
        )

    def _next_selection_version(self, workspace_id: str) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS max_no "
            "FROM profile_publication_selections WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        return int(row["max_no"]) + 1

    def get_publication_selection(
        self, selection_id: str
    ) -> PublicationSelectionRecord:
        row = self._connection.execute(
            "SELECT * FROM profile_publication_selections WHERE id = ?",
            (selection_id,),
        ).fetchone()
        if row is None:
            raise ProfilePublicationSelectionNotFound(selection_id)
        items = self._connection.execute(
            "SELECT claim_version_id FROM profile_publication_selection_items "
            "WHERE selection_id = ? ORDER BY claim_version_id",
            (selection_id,),
        ).fetchall()
        return PublicationSelectionRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            profile_version=row["profile_version"],
            claim_version_ids=tuple(item["claim_version_id"] for item in items),
            excluded_sensitive_fields=tuple(
                json.loads(row["excluded_sensitive_fields_json"])
            ),
            status=row["status"],
            version=int(row["version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Material deletion plans ---

    def build_material_deletion_impact(
        self, material_id: str, *, workspace_id: str
    ) -> dict[str, object]:
        material = self._connection.execute(
            "SELECT * FROM profile_materials "
            "WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (material_id, workspace_id),
        ).fetchone()
        if material is None:
            raise ProfileMaterialNotFound(material_id, workspace_id=workspace_id)
        versions = self._connection.execute(
            "SELECT id, version_number, file_name, storage_ref, text_ref "
            "FROM profile_material_versions "
            "WHERE material_id = ? AND deleted_at IS NULL ORDER BY version_number, id",
            (material_id,),
        ).fetchall()
        impact = self._build_deletion_impact(
            material_id=material_id,
            workspace_id=workspace_id,
            versions=versions,
        )
        impact["targetKind"] = "material"
        impact["targetVersionId"] = None
        return impact

    def build_material_version_deletion_impact(
        self, version_id: str, *, workspace_id: str
    ) -> dict[str, object]:
        version = self._connection.execute(
            "SELECT v.id, v.material_id, v.version_number, v.file_name, "
            "v.storage_ref, v.text_ref, m.current_version_id "
            "FROM profile_material_versions v "
            "JOIN profile_materials m ON m.id = v.material_id "
            "WHERE v.id = ? AND v.deleted_at IS NULL "
            "AND m.workspace_id = ? AND m.deleted_at IS NULL",
            (version_id, workspace_id),
        ).fetchone()
        if version is None:
            raise ProfileMaterialVersionNotFound(version_id)
        replacements = self._connection.execute(
            "SELECT id, version_number, file_name FROM profile_material_versions "
            "WHERE material_id = ? AND id != ? AND deleted_at IS NULL "
            "ORDER BY version_number DESC, id",
            (version["material_id"], version_id),
        ).fetchall()
        impact = self._build_deletion_impact(
            material_id=version["material_id"],
            workspace_id=workspace_id,
            versions=(version,),
        )
        # Version deletion is intentionally more conservative than whole-material
        # deletion. Pending profile information can still reference historical
        # resume evidence indirectly, so no version may be removed until the
        # workspace pending queue has been cleared.
        impact["pendingProposalIds"] = [
            row["id"]
            for row in self._connection.execute(
                "SELECT id FROM profile_claim_proposals "
                "WHERE workspace_id = ? AND status = 'pending' ORDER BY id",
                (workspace_id,),
            ).fetchall()
        ]
        impact.update(
            {
                "targetKind": "material_version",
                "targetVersionId": version_id,
                "targetVersionNumber": int(version["version_number"]),
                "isCurrentVersion": version["current_version_id"] == version_id,
                "replacementVersions": [
                    {
                        "id": row["id"],
                        "versionNumber": int(row["version_number"]),
                        "fileName": row["file_name"],
                    }
                    for row in replacements
                ],
            }
        )
        return impact

    def _build_deletion_impact(
        self,
        *,
        material_id: str,
        workspace_id: str,
        versions: Sequence[sqlite3.Row],
    ) -> dict[str, object]:
        version_ids = [row["id"] for row in versions]
        evidence_rows = []
        if version_ids:
            placeholders = ",".join("?" for _ in version_ids)
            evidence_rows = self._connection.execute(
                "SELECT id FROM profile_evidence "
                f"WHERE material_version_id IN ({placeholders}) "
                "AND tombstoned_at IS NULL ORDER BY id",
                tuple(version_ids),
            ).fetchall()
        evidence_ids = tuple(row["id"] for row in evidence_rows)
        affected = set(evidence_ids)
        claims: list[dict[str, object]] = []
        selection_ids: set[str] = set()
        claim_rows = self._connection.execute(
            "SELECT c.id AS claim_id, c.claim_type, c.version AS claim_version, "
            "v.id AS claim_version_id, v.value_json, v.support_status, "
            "v.evidence_ids_json "
            "FROM profile_claims c JOIN profile_claim_versions v "
            "ON v.id = c.current_confirmed_version_id "
            "WHERE c.workspace_id = ? ORDER BY c.claim_type, c.id",
            (workspace_id,),
        ).fetchall()
        for row in claim_rows:
            claim_evidence = tuple(json.loads(row["evidence_ids_json"]))
            affected_for_claim = tuple(sorted(set(claim_evidence) & affected))
            if not affected_for_claim:
                continue
            selections = self._connection.execute(
                "SELECT s.id FROM profile_publication_selection_items i "
                "JOIN profile_publication_selections s ON s.id = i.selection_id "
                "WHERE i.claim_version_id = ? AND s.status != 'superseded' "
                "ORDER BY s.id",
                (row["claim_version_id"],),
            ).fetchall()
            selected_by = tuple(item["id"] for item in selections)
            selection_ids.update(selected_by)
            claims.append(
                {
                    "claimId": row["claim_id"],
                    "claimType": row["claim_type"],
                    "claimVersion": int(row["claim_version"]),
                    "claimVersionId": row["claim_version_id"],
                    "value": json.loads(row["value_json"]),
                    "supportStatus": row["support_status"],
                    "affectedEvidenceIds": list(affected_for_claim),
                    "remainingEvidenceIds": sorted(set(claim_evidence) - affected),
                    "selectionIds": list(selected_by),
                }
            )
        publications: list[str] = []
        if selection_ids:
            placeholders = ",".join("?" for _ in selection_ids)
            publication_rows = self._connection.execute(
                "SELECT id FROM profile_publications "
                f"WHERE workspace_id = ? AND state = 'published' "
                f"AND selection_id IN ({placeholders}) ORDER BY id",
                (workspace_id, *sorted(selection_ids)),
            ).fetchall()
            publications = [row["id"] for row in publication_rows]
        pending_proposals: list[str] = []
        for row in self._connection.execute(
            "SELECT id, evidence_ids_json FROM profile_claim_proposals "
            "WHERE workspace_id = ? AND status = 'pending' ORDER BY id",
            (workspace_id,),
        ).fetchall():
            if set(json.loads(row["evidence_ids_json"])) & affected:
                pending_proposals.append(row["id"])
        artifact_refs = sorted(
            {
                (kind, row[column])
                for row in versions
                for kind, column in (("blob", "storage_ref"), ("text", "text_ref"))
                if row[column]
            }
        )
        return {
            "versionIds": version_ids,
            "evidenceIds": list(evidence_ids),
            "claims": claims,
            "selectionIds": sorted(selection_ids),
            "publicationIds": publications,
            "pendingProposalIds": pending_proposals,
            "artifactRefs": [
                {"kind": kind, "ref": ref} for kind, ref in artifact_refs
            ],
        }

    def create_material_deletion_plan(
        self,
        *,
        workspace_id: str,
        material_id: str,
        material_version: int,
        impact: dict[str, object],
        expires_at: str,
        target_kind: str = "material",
        target_version_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> MaterialDeletionPlanRecord:
        request = {
            "materialId": material_id,
            "materialVersion": material_version,
            "targetKind": target_kind,
            "targetVersionId": target_version_id,
        }
        request_hash = self._request_hash(request)
        operation = (
            f"material.deletion.preview:{material_id}"
            if target_kind == "material"
            else f"material.version.deletion.preview:{target_version_id}"
        )
        with self._transaction():
            if idempotency_key is not None:
                existing = self._load_idempotency_receipt(
                    workspace_id, operation, idempotency_key, request_hash
                )
                if existing is not None:
                    return self.get_material_deletion_plan(existing["planId"])
            plan_id = _new_id()
            self._connection.execute(
                "INSERT INTO profile_deletion_plans "
                "(id, workspace_id, material_id, material_version, target_kind, "
                "target_version_id, impact_json, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plan_id,
                    workspace_id,
                    material_id,
                    material_version,
                    target_kind,
                    target_version_id,
                    _canonical_json(impact),
                    expires_at,
                ),
            )
            if idempotency_key is not None:
                self._store_idempotency_receipt(
                    workspace_id,
                    operation,
                    idempotency_key,
                    request_hash,
                    {"planId": plan_id},
                )
        return self.get_material_deletion_plan(plan_id)

    def get_material_deletion_plan(
        self, plan_id: str
    ) -> MaterialDeletionPlanRecord:
        row = self._connection.execute(
            "SELECT * FROM profile_deletion_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            raise ProfileDeletionPlanNotFound(plan_id)
        return self._deletion_plan_record(row)

    def set_material_deletion_plan_status(
        self,
        plan_id: str,
        *,
        status: str,
        result: dict[str, object] | None = None,
    ) -> MaterialDeletionPlanRecord:
        with self._transaction():
            current = self._connection.execute(
                "SELECT status FROM profile_deletion_plans WHERE id = ?", (plan_id,)
            ).fetchone()
            if current is None:
                raise ProfileDeletionPlanNotFound(plan_id)
            self._connection.execute(
                "UPDATE profile_deletion_plans SET status = ?, "
                "result_json = COALESCE(?, result_json), updated_at = CURRENT_TIMESTAMP, "
                "completed_at = CASE WHEN ? = 'completed' THEN CURRENT_TIMESTAMP ELSE completed_at END "
                "WHERE id = ?",
                (
                    status,
                    None if result is None else _canonical_json(result),
                    status,
                    plan_id,
                ),
            )
        return self.get_material_deletion_plan(plan_id)

    def apply_material_deletion(
        self,
        *,
        plan_id: str,
        expected_material_version: int,
        claim_choices: dict[str, str],
    ) -> tuple[DeletionItemReceipt, ...]:
        with self._transaction():
            plan_row = self._connection.execute(
                "SELECT * FROM profile_deletion_plans WHERE id = ?", (plan_id,)
            ).fetchone()
            if plan_row is None:
                raise ProfileDeletionPlanNotFound(plan_id)
            impact = json.loads(plan_row["impact_json"])
            material = self._connection.execute(
                "SELECT * FROM profile_materials WHERE id = ? AND workspace_id = ? "
                "AND deleted_at IS NULL",
                (plan_row["material_id"], plan_row["workspace_id"]),
            ).fetchone()
            if material is None:
                raise ProfileMaterialNotFound(
                    plan_row["material_id"], workspace_id=plan_row["workspace_id"]
                )
            if (
                int(material["version"]) != expected_material_version
                or int(plan_row["material_version"]) != expected_material_version
            ):
                raise ProfileDeletionPlanConflict("material changed after deletion preview")

            current_impact = self.build_material_deletion_impact(
                plan_row["material_id"], workspace_id=plan_row["workspace_id"]
            )
            expected_claim_versions = {
                (item["claimId"], item["claimVersionId"])
                for item in impact.get("claims", [])
            }
            current_claim_versions = {
                (item["claimId"], item["claimVersionId"])
                for item in current_impact.get("claims", [])
            }
            if (
                set(impact.get("evidenceIds", []))
                != set(current_impact.get("evidenceIds", []))
                or expected_claim_versions != current_claim_versions
                or set(impact.get("selectionIds", []))
                != set(current_impact.get("selectionIds", []))
                or set(impact.get("publicationIds", []))
                != set(current_impact.get("publicationIds", []))
                or set(impact.get("pendingProposalIds", []))
                != set(current_impact.get("pendingProposalIds", []))
            ):
                raise ProfileDeletionPlanConflict("deletion impact changed")
            expected_claim_ids = {item[0] for item in expected_claim_versions}
            if set(claim_choices) != expected_claim_ids:
                raise ProfileDeletionPlanConflict("claim choices do not match preview")
            for item in current_impact.get("claims", []):
                action = claim_choices[item["claimId"]]
                if action not in {"delete", "retain_unsupported"}:
                    raise ProfileDeletionPlanConflict("unsupported claim deletion choice")
                if action == "delete" and item.get("selectionIds"):
                    raise ProfileClaimSelectedForPublication(
                        "selected claim cannot be deleted before selection is superseded"
                    )

            pending_ids = tuple(impact.get("pendingProposalIds", []))
            if pending_ids:
                placeholders = ",".join("?" for _ in pending_ids)
                self._connection.execute(
                    f"UPDATE profile_claim_proposals SET status = 'superseded', "
                    f"decided_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders}) "
                    "AND status = 'pending'",
                    pending_ids,
                )

            receipts: list[DeletionItemReceipt] = []
            for item in current_impact.get("claims", []):
                claim_id = item["claimId"]
                action = claim_choices[claim_id]
                if action == "delete":
                    self._connection.execute(
                        "DELETE FROM profile_claims WHERE id = ? AND workspace_id = ?",
                        (claim_id, plan_row["workspace_id"]),
                    )
                else:
                    self._connection.execute(
                        "UPDATE profile_claim_versions SET support_status = 'unsupported' "
                        "WHERE id = ?",
                        (item["claimVersionId"],),
                    )
                receipts.append(
                    DeletionItemReceipt(
                        kind="claim", target_id=claim_id, status="completed", action=action
                    )
                )
            for evidence_id in impact.get("evidenceIds", []):
                self._connection.execute(
                    "UPDATE profile_evidence SET sanitized_text = '', "
                    "tombstoned_at = COALESCE(tombstoned_at, CURRENT_TIMESTAMP) WHERE id = ?",
                    (evidence_id,),
                )
                receipts.append(
                    DeletionItemReceipt(
                        kind="evidence",
                        target_id=evidence_id,
                        status="completed",
                        action="tombstone",
                    )
                )
            self._connection.execute(
                "UPDATE profile_material_versions SET storage_ref = '', text_ref = '', "
                "file_name = '[deleted]' WHERE material_id = ?",
                (plan_row["material_id"],),
            )
            self._connection.execute(
                "UPDATE profile_materials SET lifecycle_status = 'archived', "
                "current_version_id = NULL, deleted_at = CURRENT_TIMESTAMP, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (plan_row["material_id"],),
            )
            receipts.append(
                DeletionItemReceipt(
                    kind="material",
                    target_id=plan_row["material_id"],
                    status="completed",
                    action="purge",
                )
            )
        return tuple(receipts)

    def apply_material_version_deletion(
        self,
        *,
        plan_id: str,
        expected_material_version: int,
        replacement_version_id: str | None,
        claim_choices: dict[str, str],
    ) -> tuple[DeletionItemReceipt, ...]:
        with self._transaction():
            plan_row = self._connection.execute(
                "SELECT * FROM profile_deletion_plans WHERE id = ?", (plan_id,)
            ).fetchone()
            if plan_row is None:
                raise ProfileDeletionPlanNotFound(plan_id)
            if (
                plan_row["target_kind"] != "material_version"
                or not plan_row["target_version_id"]
            ):
                raise ProfileDeletionPlanConflict("deletion plan target mismatch")
            impact = json.loads(plan_row["impact_json"])
            material = self._connection.execute(
                "SELECT * FROM profile_materials WHERE id = ? AND workspace_id = ? "
                "AND deleted_at IS NULL",
                (plan_row["material_id"], plan_row["workspace_id"]),
            ).fetchone()
            if material is None:
                raise ProfileMaterialNotFound(
                    plan_row["material_id"], workspace_id=plan_row["workspace_id"]
                )
            if (
                int(material["version"]) != expected_material_version
                or int(plan_row["material_version"]) != expected_material_version
            ):
                raise ProfileDeletionPlanConflict("material changed after deletion preview")

            target_version_id = str(plan_row["target_version_id"])
            current_impact = self.build_material_version_deletion_impact(
                target_version_id, workspace_id=plan_row["workspace_id"]
            )
            expected_claim_versions = {
                (item["claimId"], item["claimVersionId"])
                for item in impact.get("claims", [])
            }
            current_claim_versions = {
                (item["claimId"], item["claimVersionId"])
                for item in current_impact.get("claims", [])
            }
            expected_replacements = {
                item["id"] for item in impact.get("replacementVersions", [])
            }
            current_replacements = {
                item["id"] for item in current_impact.get("replacementVersions", [])
            }
            if current_impact.get("pendingProposalIds"):
                raise ProfileMaterialVersionHasPendingProposals(
                    "workspace has pending profile proposals"
                )
            if (
                set(impact.get("evidenceIds", []))
                != set(current_impact.get("evidenceIds", []))
                or expected_claim_versions != current_claim_versions
                or set(impact.get("selectionIds", []))
                != set(current_impact.get("selectionIds", []))
                or set(impact.get("publicationIds", []))
                != set(current_impact.get("publicationIds", []))
                or set(impact.get("pendingProposalIds", []))
                != set(current_impact.get("pendingProposalIds", []))
                or expected_replacements != current_replacements
                or bool(impact.get("isCurrentVersion"))
                != bool(current_impact.get("isCurrentVersion"))
            ):
                raise ProfileDeletionPlanConflict("deletion impact changed")
            if not current_replacements:
                raise ProfileDeletionPlanConflict(
                    "cannot delete the only material version"
                )
            is_current = bool(current_impact.get("isCurrentVersion"))
            if is_current:
                if replacement_version_id not in current_replacements:
                    raise ProfileDeletionPlanConflict(
                        "valid replacement version is required"
                    )
            elif replacement_version_id is not None:
                raise ProfileDeletionPlanConflict(
                    "replacement version is only valid for current version deletion"
                )

            expected_claim_ids = {item[0] for item in expected_claim_versions}
            if set(claim_choices) != expected_claim_ids:
                raise ProfileDeletionPlanConflict("claim choices do not match preview")
            for item in current_impact.get("claims", []):
                action = claim_choices[item["claimId"]]
                if action not in {"delete", "retain_unsupported"}:
                    raise ProfileDeletionPlanConflict(
                        "unsupported claim deletion choice"
                    )
                if action == "delete" and item.get("selectionIds"):
                    raise ProfileClaimSelectedForPublication(
                        "selected claim cannot be deleted before selection is superseded"
                    )

            receipts: list[DeletionItemReceipt] = []
            for item in current_impact.get("claims", []):
                claim_id = item["claimId"]
                action = claim_choices[claim_id]
                if action == "delete":
                    self._connection.execute(
                        "DELETE FROM profile_claims WHERE id = ? AND workspace_id = ?",
                        (claim_id, plan_row["workspace_id"]),
                    )
                elif not item.get("remainingEvidenceIds"):
                    self._connection.execute(
                        "UPDATE profile_claim_versions SET support_status = 'unsupported' "
                        "WHERE id = ?",
                        (item["claimVersionId"],),
                    )
                receipts.append(
                    DeletionItemReceipt(
                        kind="claim",
                        target_id=claim_id,
                        status="completed",
                        action=action,
                    )
                )
            for evidence_id in impact.get("evidenceIds", []):
                self._connection.execute(
                    "UPDATE profile_evidence SET sanitized_text = '', "
                    "tombstoned_at = COALESCE(tombstoned_at, CURRENT_TIMESTAMP) "
                    "WHERE id = ?",
                    (evidence_id,),
                )
                receipts.append(
                    DeletionItemReceipt(
                        kind="evidence",
                        target_id=evidence_id,
                        status="completed",
                        action="tombstone",
                    )
                )
            self._connection.execute(
                "UPDATE profile_material_versions SET storage_ref = '', text_ref = '', "
                "file_name = '[deleted]', deleted_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND material_id = ? AND deleted_at IS NULL",
                (target_version_id, plan_row["material_id"]),
            )
            if is_current:
                self._connection.execute(
                    "UPDATE profile_materials SET current_version_id = ?, "
                    "version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (replacement_version_id, plan_row["material_id"]),
                )
            else:
                self._connection.execute(
                    "UPDATE profile_materials SET version = version + 1, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (plan_row["material_id"],),
                )
            receipts.append(
                DeletionItemReceipt(
                    kind="material_version",
                    target_id=target_version_id,
                    status="completed",
                    action="purge",
                )
            )
        return tuple(receipts)

    def artifact_reference_count(self, ref: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS total FROM profile_material_versions "
            "WHERE storage_ref = ? OR text_ref = ?",
            (ref, ref),
        ).fetchone()
        return int(row["total"])

    # --- Record mappers ---

    @staticmethod
    def _deletion_plan_record(row: sqlite3.Row) -> MaterialDeletionPlanRecord:
        return MaterialDeletionPlanRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            material_id=row["material_id"],
            material_version=int(row["material_version"]),
            target_kind=row["target_kind"],
            target_version_id=row["target_version_id"],
            status=row["status"],
            impact=json.loads(row["impact_json"]),
            result=json.loads(row["result_json"]),
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _material_record(row: sqlite3.Row) -> ProfileMaterialRecord:
        return ProfileMaterialRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            type=row["type"],
            title=row["title"],
            primary_role=row["primary_role"],
            current_version_id=row["current_version_id"],
            lifecycle_status=row["lifecycle_status"],
            version=int(row["version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _version_record(row: sqlite3.Row) -> ProfileMaterialVersionRecord:
        return ProfileMaterialVersionRecord(
            id=row["id"],
            material_id=row["material_id"],
            version_number=int(row["version_number"]),
            source_type=row["source_type"],
            file_name=row["file_name"],
            mime_type=row["mime_type"],
            content_sha256=row["content_sha256"],
            storage_ref=row["storage_ref"],
            text_ref=row["text_ref"],
            processing_status=row["processing_status"],
            derived_from_version_id=row["derived_from_version_id"],
            created_by=row["created_by"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _evidence_record(row: sqlite3.Row) -> EvidenceRecord:
        return EvidenceRecord(
            id=row["id"],
            material_version_id=row["material_version_id"],
            section=row["section"],
            start_offset=int(row["start_offset"]),
            end_offset=int(row["end_offset"]),
            sanitized_text=row["sanitized_text"],
            content_sha256=row["content_sha256"],
            sensitivity=row["sensitivity"],
            tombstoned_at=row["tombstoned_at"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _claim_record(row: sqlite3.Row) -> ProfileClaimRecord:
        return ProfileClaimRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            claim_type=row["claim_type"],
            current_confirmed_version_id=row["current_confirmed_version_id"],
            version=int(row["version"]),
            deleted_at=row["deleted_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _claim_version_record(row: sqlite3.Row) -> ProfileClaimVersionRecord:
        return ProfileClaimVersionRecord(
            id=row["id"],
            claim_id=row["claim_id"],
            version=int(row["version"]),
            value=json.loads(row["value_json"]),
            status=row["status"],
            support_status=row["support_status"],
            evidence_ids=tuple(json.loads(row["evidence_ids_json"])),
            source=row["source"],
            expected_previous_version=row["expected_previous_version"],
            created_at=row["created_at"],
            confirmed_at=row["confirmed_at"],
        )

    @staticmethod
    def _claim_source_record(row: sqlite3.Row) -> ProfileClaimSourceRecord:
        return ProfileClaimSourceRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            claim_version_id=row["claim_version_id"],
            source_kind=row["source_kind"],
            source_ref=json.loads(row["source_ref_json"]),
            status=row["status"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _claim_relation_record(row: sqlite3.Row) -> ProfileClaimRelationRecord:
        return ProfileClaimRelationRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            from_claim_id=row["from_claim_id"],
            to_claim_id=row["to_claim_id"],
            relation_type=row["relation_type"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _profile_presentation_record(
        row: sqlite3.Row,
    ) -> ProfilePresentationRecord:
        return ProfilePresentationRecord(
            workspace_id=row["workspace_id"],
            summary_claim_id=row["summary_claim_id"],
            primary_direction_claim_id=row["primary_direction_claim_id"],
            featured_claim_ids=tuple(json.loads(row["featured_claim_ids_json"])),
            version=int(row["version"]),
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _proposal_record(row: sqlite3.Row) -> ClaimProposalRecord:
        return ClaimProposalRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            proposal_type=row["proposal_type"],
            target_claim_id=row["target_claim_id"],
            base_claim_version_id=row["base_claim_version_id"],
            proposed_value=json.loads(row["proposed_value_json"]),
            reason=row["reason"],
            evidence_ids=tuple(json.loads(row["evidence_ids_json"])),
            status=row["status"],
            created_by_execution_id=row["created_by_execution_id"],
            decided_at=row["decided_at"],
            created_at=row["created_at"],
            source_kind=row["source_kind"],
            source_ref=json.loads(row["source_ref_json"]),
        )

    @staticmethod
    def _conflict_record(row: sqlite3.Row) -> ClaimConflictRecord:
        return ClaimConflictRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            claim_id=row["claim_id"],
            proposal_id=row["proposal_id"],
            conflicting_claim_version_id=row["conflicting_claim_version_id"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _action_plan_item_record(row: sqlite3.Row) -> ActionPlanItemRecord:
        return ActionPlanItemRecord(
            id=row["id"],
            plan_id=row["plan_id"],
            item_id=row["item_id"],
            ordinal=int(row["ordinal"]),
            operation=row["operation"],
            target=json.loads(row["target_json"]),
            expected_version=row["expected_version"],
            before=json.loads(row["before_json"]) if row["before_json"] is not None else None,
            after=json.loads(row["after_json"]),
            evidence_ids=tuple(json.loads(row["evidence_ids_json"])),
            status=row["status"],
            receipt_id=row["receipt_id"],
            error_code=row["error_code"],
            created_at=row["created_at"],
        )
