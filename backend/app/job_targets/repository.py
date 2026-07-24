from __future__ import annotations

import json
import sqlite3
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
        try:
            for item in suggestions:
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
                        str(item["stable_key"]),
                        str(item["requirement_type"]),
                        str(item["priority"]),
                        str(item["text"]),
                        str(item.get("source_quote", "")),
                        item.get("source_start"),
                        item.get("source_end"),
                        int(bool(item.get("inferred", False))),
                    ),
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
