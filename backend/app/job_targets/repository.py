from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from uuid import uuid4

from app.job_targets.errors import (
    JobDocumentVersionNotFound,
    JobRequirementNotFound,
    JobTargetConflict,
    JobTargetNotFound,
)
from app.job_targets.models import (
    JobDocumentVersionRecord,
    JobRequirementRecord,
    JobTargetRecord,
)


class JobTargetRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_target(
        self,
        *,
        workspace_id: str,
        role_name: str,
        seniority: str,
        company_name: str | None,
        source_url: str | None,
    ) -> JobTargetRecord:
        target_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO job_targets "
            "(id, workspace_id, company_name, role_name, seniority, source_url) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                target_id,
                workspace_id,
                company_name,
                role_name,
                seniority,
                source_url,
            ),
        )
        self.connection.commit()
        return self.get_target(target_id)

    def get_target(
        self, target_id: str, *, include_recycled: bool = True
    ) -> JobTargetRecord:
        row = self.connection.execute(
            "SELECT * FROM job_targets WHERE id = ?", (target_id,)
        ).fetchone()
        if row is None or (
            not include_recycled and row["lifecycle_status"] == "recycled"
        ):
            raise JobTargetNotFound(target_id)
        return _target(row)

    def list_targets(
        self,
        workspace_id: str,
        *,
        include_archived: bool = False,
        recycled_only: bool = False,
    ) -> tuple[JobTargetRecord, ...]:
        if recycled_only:
            clause = "lifecycle_status = 'recycled'"
        elif include_archived:
            clause = "lifecycle_status IN ('active', 'archived')"
        else:
            clause = "lifecycle_status = 'active'"
        rows = self.connection.execute(
            "SELECT * FROM job_targets WHERE workspace_id = ? "
            f"AND {clause} ORDER BY updated_at DESC, rowid DESC",
            (workspace_id,),
        ).fetchall()
        return tuple(_target(row) for row in rows)

    def update_target(
        self,
        target_id: str,
        *,
        expected_version: int,
        values: dict[str, object],
    ) -> JobTargetRecord:
        allowed = {"company_name", "role_name", "seniority", "source_url"}
        if not values or set(values) - allowed:
            raise ValueError("unsupported target metadata")
        assignments = ", ".join(f"{key} = ?" for key in values)
        cursor = self.connection.execute(
            f"UPDATE job_targets SET {assignments}, version = version + 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND version = ?",
            (*values.values(), target_id, expected_version),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            self._raise_target_conflict(target_id)
        self.connection.commit()
        return self.get_target(target_id)

    def transition_lifecycle(
        self,
        target_id: str,
        *,
        expected_version: int,
        expected_states: tuple[str, ...],
        target_state: str,
    ) -> JobTargetRecord:
        placeholders = ", ".join("?" for _ in expected_states)
        cursor = self.connection.execute(
            "UPDATE job_targets SET lifecycle_status = ?, version = version + 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND version = ? "
            f"AND lifecycle_status IN ({placeholders})",
            (target_state, target_id, expected_version, *expected_states),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            self._raise_target_conflict(target_id)
        self.connection.commit()
        return self.get_target(target_id)

    def increment_target_version(
        self, target_id: str, *, expected_version: int
    ) -> JobTargetRecord:
        cursor = self.connection.execute(
            "UPDATE job_targets SET version = version + 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND version = ?",
            (target_id, expected_version),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            self._raise_target_conflict(target_id)
        self.connection.commit()
        return self.get_target(target_id)

    def create_document_version(
        self,
        target_id: str,
        *,
        source_kind: str,
        body: str,
        content_hash: str,
    ) -> JobDocumentVersionRecord:
        self.get_target(target_id)
        ordinal = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 "
                "FROM job_document_versions WHERE job_target_id = ?",
                (target_id,),
            ).fetchone()[0]
        )
        version_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO job_document_versions "
            "(id, job_target_id, ordinal, source_kind, body, content_hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (version_id, target_id, ordinal, source_kind, body, content_hash),
        )
        self.connection.commit()
        return self.get_document_version(version_id)

    def get_document_version(self, version_id: str) -> JobDocumentVersionRecord:
        row = self.connection.execute(
            "SELECT * FROM job_document_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise JobDocumentVersionNotFound(version_id)
        return _document(row)

    def list_document_versions(
        self, target_id: str
    ) -> tuple[JobDocumentVersionRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM job_document_versions WHERE job_target_id = ? "
            "ORDER BY ordinal DESC",
            (target_id,),
        ).fetchall()
        return tuple(_document(row) for row in rows)

    def confirm_document_version(
        self,
        target_id: str,
        version_id: str,
        *,
        expected_version: int,
    ) -> JobTargetRecord:
        document = self.get_document_version(version_id)
        if document.job_target_id != target_id:
            raise JobDocumentVersionNotFound(version_id)
        try:
            self.connection.execute(
                "UPDATE job_document_versions SET is_current = 0 "
                "WHERE job_target_id = ?",
                (target_id,),
            )
            self.connection.execute(
                "UPDATE job_document_versions SET is_current = 1 WHERE id = ?",
                (version_id,),
            )
            cursor = self.connection.execute(
                "UPDATE job_targets SET current_document_version_id = ?, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND version = ?",
                (version_id, target_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise JobTargetConflict("求职目标已发生变化")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_target(target_id)

    def replace_requirement_suggestions(
        self,
        target_id: str,
        document_version_id: str,
        suggestions: tuple[dict[str, object], ...],
    ) -> tuple[JobRequirementRecord, ...]:
        document = self.get_document_version(document_version_id)
        if document.job_target_id != target_id:
            raise JobDocumentVersionNotFound(document_version_id)
        existing = self.list_requirements(
            target_id, document_version_id=document_version_id
        )
        # Model output is a fresh suggestion snapshot.  The model's own stable key
        # cannot be trusted across runs, so reconcile by a server-owned canonical
        # text key.  A prior user decision always wins over a fresh suggestion.
        existing_by_identity: dict[str, JobRequirementRecord] = {}
        for requirement in existing:
            identity = _requirement_identity(requirement.text)
            current = existing_by_identity.get(identity)
            if current is None or (
                current.confirmation_status == "pending"
                and requirement.confirmation_status != "pending"
            ):
                existing_by_identity[identity] = requirement

        fresh: dict[str, dict[str, object]] = {}
        for item in suggestions:
            identity = _requirement_identity(str(item.get("text") or ""))
            if not identity:
                continue
            # When the Agent emits the same requirement twice, prefer a source
            # backed, non-inferred suggestion rather than creating two rows.
            current = fresh.get(identity)
            if current is None or (
                bool(current.get("inferred")) and not bool(item.get("inferred"))
            ):
                fresh[identity] = item

        active_keys: set[str] = set()
        try:
            for identity, item in fresh.items():
                matched = existing_by_identity.get(identity)
                stable_key = (
                    matched.stable_key
                    if matched is not None
                    else _stable_requirement_key(identity)
                )
                active_keys.add(stable_key)
                self.connection.execute(
                    "INSERT INTO job_requirements "
                    "(id, job_target_id, document_version_id, stable_key, "
                    "requirement_type, priority, text, source_quote, source_start, "
                    "source_end, inferred) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(document_version_id, stable_key) DO UPDATE SET "
                    "requirement_type = excluded.requirement_type, "
                    "priority = excluded.priority, text = excluded.text, "
                    "source_quote = excluded.source_quote, "
                    "source_start = excluded.source_start, "
                    "source_end = excluded.source_end, inferred = excluded.inferred, "
                    "version = job_requirements.version + 1, "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE job_requirements.confirmation_status = 'pending'",
                    (
                        str(uuid4()),
                        target_id,
                        document_version_id,
                        stable_key,
                        str(item["requirement_type"]),
                        str(item["priority"]),
                        str(item["text"]),
                        str(item.get("source_quote", "")),
                        item.get("source_start"),
                        item.get("source_end"),
                        int(bool(item.get("inferred", False))),
                    ),
                )
            # Pending rows are provisional model output, not a user decision.
            # Remove suggestions absent from this run so repeated analysis does
            # not keep accumulating stale or differently-keyed candidates.
            if active_keys:
                placeholders = ", ".join("?" for _ in active_keys)
                self.connection.execute(
                    "DELETE FROM job_requirements "
                    "WHERE job_target_id = ? AND document_version_id = ? "
                    "AND confirmation_status = 'pending' "
                    f"AND stable_key NOT IN ({placeholders})",
                    (target_id, document_version_id, *sorted(active_keys)),
                )
            else:
                self.connection.execute(
                    "DELETE FROM job_requirements "
                    "WHERE job_target_id = ? AND document_version_id = ? "
                    "AND confirmation_status = 'pending'",
                    (target_id, document_version_id),
                )
            self.connection.commit()
        except sqlite3.Error:
            self.connection.rollback()
            raise
        return self.list_requirements(
            target_id, document_version_id=document_version_id
        )

    def list_requirements(
        self,
        target_id: str,
        *,
        document_version_id: str | None = None,
    ) -> tuple[JobRequirementRecord, ...]:
        query = "SELECT * FROM job_requirements WHERE job_target_id = ?"
        values: list[object] = [target_id]
        if document_version_id is not None:
            query += " AND document_version_id = ?"
            values.append(document_version_id)
        query += " ORDER BY inferred, created_at, rowid"
        return tuple(
            _requirement(row)
            for row in self.connection.execute(query, values).fetchall()
        )

    def set_requirement_confirmation(
        self,
        requirement_id: str,
        *,
        expected_version: int,
        status: str,
    ) -> JobRequirementRecord:
        cursor = self.connection.execute(
            "UPDATE job_requirements SET confirmation_status = ?, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND version = ?",
            (status, requirement_id, expected_version),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            row = self.connection.execute(
                "SELECT 1 FROM job_requirements WHERE id = ?", (requirement_id,)
            ).fetchone()
            if row is None:
                raise JobRequirementNotFound(requirement_id)
            raise JobTargetConflict("岗位要求已发生变化")
        self.connection.commit()
        return self.get_requirement(requirement_id)

    def get_requirement(self, requirement_id: str) -> JobRequirementRecord:
        row = self.connection.execute(
            "SELECT * FROM job_requirements WHERE id = ?", (requirement_id,)
        ).fetchone()
        if row is None:
            raise JobRequirementNotFound(requirement_id)
        return _requirement(row)

    def replace_project_priorities(
        self,
        target_id: str,
        *,
        core_project_id: str,
        supplementary_project_ids: tuple[str, ...],
    ) -> None:
        try:
            self.connection.execute(
                "DELETE FROM job_target_project_priorities "
                "WHERE job_target_id = ?",
                (target_id,),
            )
            self.connection.execute(
                "INSERT INTO job_target_project_priorities "
                "(job_target_id, project_claim_id, priority_kind, ordinal) "
                "VALUES (?, ?, 'core', 0)",
                (target_id, core_project_id),
            )
            self.connection.executemany(
                "INSERT INTO job_target_project_priorities "
                "(job_target_id, project_claim_id, priority_kind, ordinal) "
                "VALUES (?, ?, 'supplementary', ?)",
                tuple(
                    (target_id, project_id, ordinal)
                    for ordinal, project_id in enumerate(
                        supplementary_project_ids, start=1
                    )
                ),
            )
            self.connection.commit()
        except sqlite3.Error:
            self.connection.rollback()
            raise

    def active_execution_count(self, target_id: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM agent_runs run "
            "JOIN job_analysis_runs analysis ON analysis.execution_id = run.id "
            "WHERE analysis.job_target_id = ? "
            "AND run.status IN ('running', 'waiting_for_input', 'waiting_for_approval')",
            (target_id,),
        ).fetchone()
        return int(row[0])

    def deletion_impact(self, target_id: str) -> dict[str, int]:
        self.get_target(target_id)
        counts = {}
        for key, table in (
            ("documents", "job_document_versions"),
            ("requirements", "job_requirements"),
            ("analyses", "job_analysis_runs"),
            ("deep_dives", "project_deep_dives"),
            ("question_candidates", "project_question_candidates"),
        ):
            if table == "project_question_candidates":
                row = self.connection.execute(
                    "SELECT COUNT(*) FROM project_question_candidates candidate "
                    "JOIN project_deep_dives dive ON dive.id = candidate.deep_dive_id "
                    "WHERE dive.job_target_id = ?",
                    (target_id,),
                ).fetchone()
            else:
                row = self.connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE job_target_id = ?",
                    (target_id,),
                ).fetchone()
            counts[key] = int(row[0])
        return counts

    def delete_target(self, target_id: str) -> None:
        target = self.get_target(target_id)
        if target.lifecycle_status != "recycled":
            raise JobTargetConflict("只有回收站中的求职目标可以永久删除")
        if self.active_execution_count(target_id):
            raise JobTargetConflict("求职目标仍有运行中的任务")
        self.connection.execute("DELETE FROM job_targets WHERE id = ?", (target_id,))
        self.connection.commit()

    def receipt(
        self, workspace_id: str, operation: str, idempotency_key: str
    ) -> dict[str, object] | None:
        row = self.connection.execute(
            "SELECT result_json FROM job_target_idempotency_receipts "
            "WHERE workspace_id = ? AND operation = ? AND idempotency_key = ?",
            (workspace_id, operation, idempotency_key),
        ).fetchone()
        return None if row is None else json.loads(row["result_json"])

    def save_receipt(
        self,
        *,
        workspace_id: str,
        operation: str,
        idempotency_key: str,
        request_digest: str,
        result: dict[str, object],
    ) -> None:
        self.connection.execute(
            "INSERT INTO job_target_idempotency_receipts "
            "(id, workspace_id, operation, idempotency_key, request_digest, result_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                workspace_id,
                operation,
                idempotency_key,
                request_digest,
                json.dumps(result, ensure_ascii=False, sort_keys=True),
            ),
        )
        self.connection.commit()

    def create_analysis_run(
        self,
        target_id: str,
        document_version_id: str,
        *,
        profile_version: int,
        input_digest: str,
    ) -> str:
        run_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO job_analysis_runs "
            "(id, job_target_id, document_version_id, profile_version, input_digest, "
            "status, stage, latest_progress_at) "
            "VALUES (?, ?, ?, ?, ?, 'running', 'extracting_requirements', CURRENT_TIMESTAMP)",
            (run_id, target_id, document_version_id, profile_version, input_digest),
        )
        self.connection.commit()
        return run_id

    def bind_analysis_execution(self, run_id: str, execution_id: str) -> None:
        self.connection.execute(
            "UPDATE job_analysis_runs SET execution_id = ?, status = 'running', "
            "latest_progress_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (execution_id, run_id),
        )
        self.connection.commit()

    def current_analysis_run(self, target_id: str):
        return self.connection.execute(
            "SELECT * FROM job_analysis_runs WHERE job_target_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (target_id,),
        ).fetchone()

    def get_analysis_run(self, run_id: str):
        row = self.connection.execute(
            "SELECT * FROM job_analysis_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise JobTargetNotFound(run_id)
        return row

    def create_analysis_work_items(
        self, run_id: str, items: tuple[tuple[str, str], ...]
    ) -> None:
        self.connection.executemany(
            "INSERT OR IGNORE INTO job_analysis_work_items "
            "(id, analysis_run_id, work_key, input_digest) VALUES (?, ?, ?, ?)",
            tuple((str(uuid4()), run_id, key, digest) for key, digest in items),
        )
        self.connection.commit()

    def list_analysis_work_items(self, run_id: str):
        return self.connection.execute(
            "SELECT * FROM job_analysis_work_items WHERE analysis_run_id = ? "
            "ORDER BY created_at, rowid",
            (run_id,),
        ).fetchall()

    def complete_analysis_work_item(
        self, item_id: str, output: dict[str, object]
    ) -> None:
        self.connection.execute(
            "UPDATE job_analysis_work_items SET status = 'completed', "
            "attempt_count = attempt_count + 1, output_json = ?, "
            "last_error_code = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(output, ensure_ascii=False), item_id),
        )
        self.connection.commit()

    def fail_analysis_work_item(self, item_id: str, error_code: str) -> None:
        self.connection.execute(
            "UPDATE job_analysis_work_items SET status = 'retryable', "
            "attempt_count = attempt_count + 1, last_error_code = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (error_code[:120], item_id),
        )
        self.connection.commit()

    def retry_analysis_work_item(self, item_id: str) -> None:
        self.connection.execute(
            "UPDATE job_analysis_work_items SET status = 'pending', "
            "last_error_code = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ? "
            "AND status IN ('retryable', 'interrupted')",
            (item_id,),
        )
        self.connection.commit()

    def transition_analysis(
        self,
        run_id: str,
        *,
        status: str,
        stage: str | None = None,
        control_intent: str | None = None,
    ) -> None:
        self.connection.execute(
            "UPDATE job_analysis_runs SET status = ?, stage = COALESCE(?, stage), "
            "control_intent = ?, latest_progress_at = CURRENT_TIMESTAMP, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, stage, control_intent, run_id),
        )
        self.connection.commit()

    def create_deep_dive(
        self, target_id: str, project_claim_id: str, session_id: str
    ) -> str:
        dive_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO project_deep_dives "
            "(id, job_target_id, project_claim_id, session_id, waiting_for_input) "
            "VALUES (?, ?, ?, ?, 1)",
            (dive_id, target_id, project_claim_id, session_id),
        )
        self.connection.commit()
        return dive_id

    def current_deep_dive(self, target_id: str, project_claim_id: str):
        return self.connection.execute(
            "SELECT * FROM project_deep_dives WHERE job_target_id = ? "
            "AND project_claim_id = ? AND status != 'archived' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (target_id, project_claim_id),
        ).fetchone()

    def get_deep_dive(self, dive_id: str):
        row = self.connection.execute(
            "SELECT * FROM project_deep_dives WHERE id = ?", (dive_id,)
        ).fetchone()
        if row is None:
            from app.job_targets.errors import ProjectDeepDiveNotFound
            raise ProjectDeepDiveNotFound(dive_id)
        return row

    def advance_deep_dive(
        self,
        dive_id: str,
        *,
        current_stage: str,
        completed_stage_ids: tuple[str, ...],
        waiting_for_input: bool,
        status: str = "active",
    ) -> None:
        self.connection.execute(
            "UPDATE project_deep_dives SET current_stage = ?, "
            "completed_stage_ids_json = ?, waiting_for_input = ?, status = ?, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (
                current_stage,
                json.dumps(completed_stage_ids),
                int(waiting_for_input),
                status,
                dive_id,
            ),
        )
        self.connection.commit()

    def transition_deep_dive(self, dive_id: str, status: str) -> None:
        self.connection.execute(
            "UPDATE project_deep_dives SET status = ?, version = version + 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, dive_id),
        )
        self.connection.commit()

    def archive_deep_dive(self, dive_id: str) -> None:
        """Keep a finished attempt in history while allowing a fresh attempt."""
        self.transition_deep_dive(dive_id, "archived")

    def create_artifact(
        self,
        dive_id: str,
        *,
        artifact_kind: str,
        payload: dict[str, object],
        execution_id: str | None = None,
        message_id: str | None = None,
    ) -> str:
        artifact_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO project_deep_dive_artifacts "
            "(id, deep_dive_id, artifact_kind, source_execution_id, "
            "source_message_id, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                artifact_id,
                dive_id,
                artifact_kind,
                execution_id,
                message_id,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        self.connection.commit()
        return artifact_id

    def list_artifacts(self, dive_id: str):
        return self.connection.execute(
            "SELECT * FROM project_deep_dive_artifacts WHERE deep_dive_id = ? "
            "ORDER BY created_at, rowid",
            (dive_id,),
        ).fetchall()

    def get_artifact(self, artifact_id: str):
        row = self.connection.execute(
            "SELECT * FROM project_deep_dive_artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise JobTargetNotFound(artifact_id)
        return row

    def confirm_narrative_sections(
        self,
        *,
        workspace_id: str,
        project_claim_id: str,
        artifact_id: str,
        sections: dict[str, str],
        source_session_id: str,
        source_message_id: str | None,
    ) -> None:
        try:
            for kind, content in sections.items():
                self.connection.execute(
                    "UPDATE project_narrative_sections SET status = 'superseded' "
                    "WHERE project_claim_id = ? AND section_kind = ? AND status = 'confirmed'",
                    (project_claim_id, kind),
                )
                version = self.connection.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM project_narrative_sections "
                    "WHERE project_claim_id = ? AND section_kind = ?",
                    (project_claim_id, kind),
                ).fetchone()[0]
                self.connection.execute(
                    "INSERT INTO project_narrative_sections "
                    "(id, workspace_id, project_claim_id, section_kind, content, "
                    "source_session_id, source_message_id, version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        workspace_id,
                        project_claim_id,
                        kind,
                        content,
                        source_session_id,
                        source_message_id,
                        version,
                    ),
                )
            self.connection.execute(
                "UPDATE project_deep_dive_artifacts SET status = 'partially_confirmed', "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (artifact_id,),
            )
            self.connection.commit()
        except sqlite3.Error:
            self.connection.rollback()
            raise

    def create_gap(
        self, dive_id: str, *, kind: str, summary: str, source_artifact_id: str | None
    ) -> str:
        gap_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO project_gaps "
            "(id, deep_dive_id, gap_kind, summary, source_artifact_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (gap_id, dive_id, kind, summary, source_artifact_id),
        )
        self.connection.commit()
        return gap_id

    def list_gaps(self, dive_id: str):
        return self.connection.execute(
            "SELECT * FROM project_gaps WHERE deep_dive_id = ? "
            "ORDER BY created_at, rowid",
            (dive_id,),
        ).fetchall()

    def get_gap(self, gap_id: str):
        row = self.connection.execute(
            "SELECT gap.*, dive.project_claim_id, dive.job_target_id "
            "FROM project_gaps gap JOIN project_deep_dives dive "
            "ON dive.id = gap.deep_dive_id WHERE gap.id = ?",
            (gap_id,),
        ).fetchone()
        if row is None:
            raise JobTargetNotFound(gap_id)
        return row

    def resolve_gap(self, gap_id: str, *, status: str, resolution_ref: str) -> None:
        self.connection.execute(
            "UPDATE project_gaps SET status = ?, resolution_ref = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, resolution_ref, gap_id),
        )
        self.connection.commit()

    def create_project_question_candidate(
        self,
        dive_id: str,
        project_claim_id: str,
        *,
        dimension: str,
        question: dict[str, object],
    ) -> str:
        return self.create_project_question_candidates(
            dive_id,
            project_claim_id,
            candidates=((dimension, question),),
        )[0]

    def create_project_question_candidates(
        self,
        dive_id: str,
        project_claim_id: str,
        *,
        candidates: tuple[tuple[str, dict[str, object]], ...],
    ) -> tuple[str, ...]:
        candidate_ids: list[str] = []
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            for dimension, question in candidates:
                encoded = json.dumps(question, ensure_ascii=False, sort_keys=True)
                existing = self.connection.execute(
                    "SELECT id FROM project_question_candidates "
                    "WHERE deep_dive_id = ? AND project_claim_id = ? "
                    "AND dimension = ? AND question_json = ?",
                    (dive_id, project_claim_id, dimension, encoded),
                ).fetchone()
                if existing is not None:
                    candidate_ids.append(existing["id"])
                    continue
                candidate_id = str(uuid4())
                self.connection.execute(
                    "INSERT INTO project_question_candidates "
                    "(id, deep_dive_id, project_claim_id, dimension, question_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        candidate_id,
                        dive_id,
                        project_claim_id,
                        dimension,
                        encoded,
                    ),
                )
                candidate_ids.append(candidate_id)
        except Exception:
            self.connection.rollback()
            raise
        self.connection.commit()
        return tuple(candidate_ids)

    def list_project_question_candidates(self, dive_id: str):
        return self.connection.execute(
            "SELECT * FROM project_question_candidates WHERE deep_dive_id = ? "
            "ORDER BY created_at, rowid",
            (dive_id,),
        ).fetchall()

    def get_project_question_candidate(self, candidate_id: str):
        row = self.connection.execute(
            "SELECT candidate.*, dive.job_target_id FROM project_question_candidates candidate "
            "JOIN project_deep_dives dive ON dive.id = candidate.deep_dive_id "
            "WHERE candidate.id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise JobTargetNotFound(candidate_id)
        return row

    def decide_project_question_candidate(self, candidate_id: str, status: str) -> None:
        self.connection.execute(
            "UPDATE project_question_candidates SET status = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, candidate_id),
        )
        self.connection.commit()

    def batch_decide_project_question_candidates(
        self, candidate_ids: tuple[str, ...], *, status: str
    ) -> None:
        if not candidate_ids:
            return
        placeholders = ", ".join("?" for _ in candidate_ids)
        self.connection.execute(
            "UPDATE project_question_candidates SET status = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id IN ("
            f"{placeholders}) AND status = 'review_pending'",
            (status, *candidate_ids),
        )
        self.connection.commit()

    def update_project_question_candidate(
        self, candidate_id: str, *, title: str, question: str
    ) -> None:
        row = self.get_project_question_candidate(candidate_id)
        if row["status"] != "review_pending":
            raise JobTargetConflict("只有待确认的候选题可以编辑")
        payload = json.loads(row["question_json"])
        payload["title"] = title
        payload["question"] = question
        self.connection.execute(
            "UPDATE project_question_candidates SET question_json = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True), candidate_id),
        )
        self.connection.commit()

    def list_project_priorities(self, target_id: str):
        return self.connection.execute(
            "SELECT * FROM job_target_project_priorities WHERE job_target_id = ? "
            "ORDER BY ordinal",
            (target_id,),
        ).fetchall()

    def _raise_target_conflict(self, target_id: str) -> None:
        row = self.connection.execute(
            "SELECT 1 FROM job_targets WHERE id = ?", (target_id,)
        ).fetchone()
        if row is None:
            raise JobTargetNotFound(target_id)
        raise JobTargetConflict("求职目标已发生变化")


def _target(row) -> JobTargetRecord:
    return JobTargetRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        company_name=row["company_name"],
        role_name=row["role_name"],
        seniority=row["seniority"],
        source_url=row["source_url"],
        lifecycle_status=row["lifecycle_status"],
        current_document_version_id=row["current_document_version_id"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _document(row) -> JobDocumentVersionRecord:
    return JobDocumentVersionRecord(
        id=row["id"],
        job_target_id=row["job_target_id"],
        ordinal=row["ordinal"],
        source_kind=row["source_kind"],
        body=row["body"],
        content_hash=row["content_hash"],
        is_current=bool(row["is_current"]),
        created_at=row["created_at"],
    )


def _requirement(row) -> JobRequirementRecord:
    return JobRequirementRecord(
        id=row["id"],
        job_target_id=row["job_target_id"],
        document_version_id=row["document_version_id"],
        stable_key=row["stable_key"],
        requirement_type=row["requirement_type"],
        priority=row["priority"],
        text=row["text"],
        source_quote=row["source_quote"],
        source_start=row["source_start"],
        source_end=row["source_end"],
        inferred=bool(row["inferred"]),
        confirmation_status=row["confirmation_status"],
        preparation_status=row["preparation_status"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _requirement_identity(text: str) -> str:
    """Make cosmetic model variations resolve to the same JD requirement."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = normalized.replace("或者", "或")
    return re.sub(r"[\s\W_]+", "", normalized)


def _stable_requirement_key(identity: str) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
