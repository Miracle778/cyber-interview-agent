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
    ProfileClaimVersionConflict,
    ProfileDomainError,
    ProfileEvidenceMismatch,
    ProfileMaterialNotFound,
    ProfileMaterialVersionNotFound,
    ProfileProposalAlreadyDecided,
    ProfileProposalNotFound,
    ProfilePublicationSelectionNotFound,
    ProfileSnapshotChanged,
)
from app.profile.models import (
    ActionPlanItemRecord,
    ActionPlanItemSpec,
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
    EvidenceRecord,
    ProfileActionPlanRecord,
    ProfileAssessmentRecord,
    ProfileClaimRecord,
    ProfileClaimVersionRecord,
    ProfileMaterialRecord,
    ProfileMaterialVersionRecord,
    PublicationSelectionRecord,
    SaveAssessmentCommand,
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
                raise ProfileDomainError(
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
            "SELECT * FROM profile_materials WHERE id = ?", (material_id,)
        ).fetchone()
        if row is None:
            raise ProfileMaterialNotFound(material_id, workspace_id=workspace_id)
        if workspace_id is not None and row["workspace_id"] != workspace_id:
            raise ProfileMaterialNotFound(material_id, workspace_id=workspace_id)
        return self._material_record(row)

    def list_materials(self, workspace_id: str) -> tuple[ProfileMaterialRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM profile_materials "
            "WHERE workspace_id = ? AND lifecycle_status = 'active' "
            "ORDER BY updated_at DESC, id",
            (workspace_id,),
        ).fetchall()
        return tuple(self._material_record(row) for row in rows)

    def archive_material(self, material_id: str) -> ProfileMaterialRecord:
        with self._transaction():
            self._require_material(material_id)
            self._connection.execute(
                "UPDATE profile_materials SET lifecycle_status = 'archived', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (material_id,),
            )
        return self.get_material(material_id)

    def restore_material(self, material_id: str) -> ProfileMaterialRecord:
        with self._transaction():
            self._require_material(material_id)
            self._connection.execute(
                "UPDATE profile_materials SET lifecycle_status = 'active', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
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
                "WHERE id = ? AND material_id = ?",
                (version_id, material_id),
            ).fetchone()
            if version is None:
                raise ProfileMaterialVersionNotFound(version_id)
            self._connection.execute(
                "UPDATE profile_materials SET current_version_id = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (version_id, material_id),
            )
        return self.get_material(material_id)

    def _require_material(self, material_id: str) -> None:
        row = self._connection.execute(
            "SELECT id FROM profile_materials WHERE id = ?", (material_id,)
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
            "WHERE material_id = ? ORDER BY version_number DESC, id",
            (material_id,),
        ).fetchall()
        return tuple(self._version_record(row) for row in rows)

    def mark_version_parsed(
        self, version_id: str, *, text_path: str, content_sha256: str
    ) -> ProfileMaterialVersionRecord:
        with self._transaction():
            self._connection.execute(
                "UPDATE profile_material_versions "
                "SET processing_status = 'parsed', text_ref = ? "
                "WHERE id = ? AND processing_status IN ('uploaded', 'parsing', 'parse_failed')",
                (text_path, version_id),
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

    def _evidence_ids_for_version(self, version_id: str) -> set[str]:
        return {
            row["id"]
            for row in self._connection.execute(
                "SELECT id FROM profile_evidence "
                "WHERE material_version_id = ? AND tombstoned_at IS NULL",
                (version_id,),
            ).fetchall()
        }

    # --- Claim proposals ---

    def create_claim_proposals(
        self,
        version_id: str,
        proposals: Sequence[CreateClaimProposalSpec],
    ) -> tuple[ClaimProposalRecord, ...]:
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
            valid_evidence = self._evidence_ids_for_version(version_id)

            created: list[ClaimProposalRecord] = []
            for spec in proposals:
                unknown = set(spec.evidence_ids) - valid_evidence
                if unknown:
                    raise ProfileEvidenceMismatch(
                        "proposal references evidence outside its material version"
                    )
                # An update against an already-confirmed claim records a conflict
                # edge but never overwrites the confirmed version.
                proposal_id = _new_id()
                self._connection.execute(
                    "INSERT INTO profile_claim_proposals "
                    "(id, workspace_id, proposal_type, target_claim_id, "
                    "base_claim_version_id, proposed_value_json, reason, "
                    "evidence_ids_json, status, created_by_execution_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL)",
                    (
                        proposal_id,
                        workspace_id,
                        spec.proposal_type,
                        spec.target_claim_id,
                        spec.base_claim_version_id,
                        _canonical_json(spec.proposed_value),
                        spec.reason,
                        _canonical_json(list(spec.evidence_ids)),
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

    # --- Claim decision ---

    def decide_proposal(
        self, proposal_id: str, command: DecideProposalCommand
    ) -> ClaimDecisionResult:
        with self._transaction():
            row = self._connection.execute(
                "SELECT * FROM profile_claim_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise ProfileProposalNotFound(proposal_id)
            current_status = row["status"]
            if current_status != command.expected_status:
                if current_status in _TERMINAL_PROPOSAL_STATUSES:
                    raise ProfileProposalAlreadyDecided(
                        f"proposal {proposal_id} already decided"
                    )
                raise ProfileClaimVersionConflict(
                    f"proposal {proposal_id} status {current_status!r} != expected {command.expected_status!r}"
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
                return ClaimDecisionResult(proposal_id=proposal_id, status="rejected")

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
            return ClaimDecisionResult(
                proposal_id=proposal_id,
                status="accepted",
                claim_id=claim_id,
                claim_version_id=version_id,
                support_status=support,
            )

    def batch_decide_proposals(
        self, commands: Sequence[DecideProposalCommand]
    ) -> tuple[ClaimDecisionResult, ...]:
        completed: list[ClaimDecisionResult] = []
        for command in commands:
            try:
                completed.append(self.decide_proposal(command.proposal_id, command))
            except (ProfileProposalAlreadyDecided, ProfileClaimVersionConflict):
                continue
        return tuple(completed)

    # --- Claim read ---

    def get_claim(self, claim_id: str) -> ProfileClaimRecord:
        row = self._connection.execute(
            "SELECT * FROM profile_claims WHERE id = ?", (claim_id,)
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
            "WHERE c.workspace_id = ? "
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
                "version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, plan_id),
            )
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
            if row["status"] != "pending":
                raise ProfileDomainError(
                    f"action plan item {item_id} already {row['status']}"
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

    # --- Publication selection ---

    def create_publication_selection(
        self, command: CreatePublicationSelectionCommand
    ) -> PublicationSelectionRecord:
        with self._transaction():
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
        return self.get_publication_selection(selection_id)

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

    # --- Record mappers ---

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
