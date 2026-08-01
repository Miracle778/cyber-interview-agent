from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

from app.interview_retrospectives.errors import (
    RetrospectiveNotFound,
    RetrospectiveVersionConflict,
)
from app.interview_retrospectives.models import (
    CleanupVersionRecord,
    RetrospectiveRecord,
    SegmentRecord,
    SourceVersionRecord,
)


class InterviewRetrospectiveRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_retrospective(
        self,
        *,
        workspace_id: str,
        job_target_id: str,
        title: str,
        round_label: str,
        interview_date: str | None,
        outcome: str,
        note: str,
        analysis_session_id: str,
        chat_session_id: str,
        create_idempotency_key: str,
    ) -> RetrospectiveRecord:
        replay = self.connection.execute(
            "SELECT id FROM interview_retrospectives "
            "WHERE workspace_id = ? AND create_idempotency_key = ?",
            (workspace_id, create_idempotency_key),
        ).fetchone()
        if replay is not None:
            return self.get_retrospective(replay["id"])
        retrospective_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO interview_retrospectives("
            "id, workspace_id, job_target_id, title, round_label, interview_date, "
            "outcome, note, analysis_session_id, chat_session_id, "
            "create_idempotency_key"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                retrospective_id,
                workspace_id,
                job_target_id,
                title,
                round_label,
                interview_date,
                outcome,
                note,
                analysis_session_id,
                chat_session_id,
                create_idempotency_key,
            ),
        )
        self.connection.commit()
        return self.get_retrospective(retrospective_id)

    def get_retrospective(self, retrospective_id: str) -> RetrospectiveRecord:
        row = self.connection.execute(
            "SELECT * FROM interview_retrospectives WHERE id = ?",
            (retrospective_id,),
        ).fetchone()
        if row is None:
            raise RetrospectiveNotFound(retrospective_id)
        return _retrospective(row)

    def list_retrospectives(
        self, *, workspace_id: str, lifecycle_status: str
    ) -> tuple[RetrospectiveRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM interview_retrospectives "
            "WHERE workspace_id = ? AND lifecycle_status = ? "
            "ORDER BY interview_date DESC, created_at DESC, rowid DESC",
            (workspace_id, lifecycle_status),
        ).fetchall()
        return tuple(_retrospective(row) for row in rows)

    def insert_source_version(
        self,
        retrospective_id: str,
        *,
        source_kind: str,
        file_name: str | None,
        body: str,
        content_sha256: str,
    ) -> SourceVersionRecord:
        ordinal = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 "
                "FROM interview_source_versions WHERE retrospective_id = ?",
                (retrospective_id,),
            ).fetchone()[0]
        )
        version_id = str(uuid4())
        try:
            self.connection.execute(
                "INSERT INTO interview_source_versions("
                "id, retrospective_id, ordinal, source_kind, file_name, body, "
                "content_sha256) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    version_id,
                    retrospective_id,
                    ordinal,
                    source_kind,
                    file_name,
                    body,
                    content_sha256,
                ),
            )
            self.connection.execute(
                "UPDATE interview_retrospectives SET active_source_version_id = ?, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (version_id, retrospective_id),
            )
            self.connection.commit()
        except sqlite3.Error:
            self.connection.rollback()
            raise
        return self.get_source_version(version_id)

    def get_source_version(self, version_id: str) -> SourceVersionRecord:
        row = self.connection.execute(
            "SELECT * FROM interview_source_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise RetrospectiveNotFound(version_id)
        return _source(row)

    def insert_cleanup_version(
        self,
        retrospective_id: str,
        *,
        source_version_id: str,
        input_digest: str,
    ) -> CleanupVersionRecord:
        ordinal = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 "
                "FROM interview_cleanup_versions WHERE retrospective_id = ?",
                (retrospective_id,),
            ).fetchone()[0]
        )
        cleanup_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO interview_cleanup_versions("
            "id, retrospective_id, source_version_id, ordinal, input_digest, "
            "status, stage) VALUES (?, ?, ?, ?, ?, 'review_pending', "
            "'waiting_for_review')",
            (
                cleanup_id,
                retrospective_id,
                source_version_id,
                ordinal,
                input_digest,
            ),
        )
        self.connection.commit()
        return self.get_cleanup_version(cleanup_id)

    def get_cleanup_version(self, cleanup_id: str) -> CleanupVersionRecord:
        row = self.connection.execute(
            "SELECT * FROM interview_cleanup_versions WHERE id = ?", (cleanup_id,)
        ).fetchone()
        if row is None:
            raise RetrospectiveNotFound(cleanup_id)
        return _cleanup(row)

    def replace_segments(
        self,
        cleanup_id: str,
        *,
        expected_version: int,
        segments: tuple[dict[str, object], ...],
    ) -> CleanupVersionRecord:
        current = self.get_cleanup_version(cleanup_id)
        if current.version != expected_version:
            raise RetrospectiveVersionConflict("整理版本已更新")
        try:
            self.connection.execute(
                "DELETE FROM interview_segments WHERE cleanup_version_id = ?",
                (cleanup_id,),
            )
            for ordinal, segment in enumerate(segments, start=1):
                self.connection.execute(
                    "INSERT INTO interview_segments("
                    "id, cleanup_version_id, ordinal, speaker_role, "
                    "raw_speaker_label, display_name, body, source_start, "
                    "source_end, confidence, uncertainty_reason, ignored"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        cleanup_id,
                        ordinal,
                        segment["speaker_role"],
                        segment["raw_speaker_label"],
                        segment["display_name"],
                        segment["body"],
                        segment["source_start"],
                        segment["source_end"],
                        segment["confidence"],
                        segment["uncertainty_reason"],
                        int(bool(segment["ignored"])),
                    ),
                )
            cursor = self.connection.execute(
                "UPDATE interview_cleanup_versions SET version = version + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND version = ?",
                (cleanup_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise RetrospectiveVersionConflict("整理版本已更新")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_cleanup_version(cleanup_id)

    def list_segments(self, cleanup_id: str) -> tuple[SegmentRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM interview_segments WHERE cleanup_version_id = ? "
            "ORDER BY ordinal, rowid",
            (cleanup_id,),
        ).fetchall()
        return tuple(_segment(row) for row in rows)

    def confirm_cleanup(
        self, retrospective_id: str, cleanup_id: str, *, expected_version: int
    ) -> CleanupVersionRecord:
        cursor = self.connection.execute(
            "UPDATE interview_cleanup_versions SET status = 'confirmed', "
            "stage = 'confirmed', confirmed_at = CURRENT_TIMESTAMP, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND retrospective_id = ? AND version = ? "
            "AND status = 'review_pending'",
            (cleanup_id, retrospective_id, expected_version),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("整理版本已更新或不可确认")
        self.connection.execute(
            "UPDATE interview_retrospectives SET active_cleanup_version_id = ?, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (cleanup_id, retrospective_id),
        )
        self.connection.commit()
        return self.get_cleanup_version(cleanup_id)

    def clear_source(
        self,
        retrospective_id: str,
        source_version_id: str,
        *,
        expected_version: int,
    ) -> SourceVersionRecord:
        try:
            cursor = self.connection.execute(
                "UPDATE interview_retrospectives SET version = version + 1, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND version = ?",
                (retrospective_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise RetrospectiveVersionConflict("复盘版本已更新")
            cursor = self.connection.execute(
                "UPDATE interview_source_versions SET body = '', "
                "cleared_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND retrospective_id = ? AND cleared_at IS NULL",
                (source_version_id, retrospective_id),
            )
            if cursor.rowcount != 1:
                raise RetrospectiveVersionConflict("原始记录已清除或不存在")
            self.connection.execute(
                "UPDATE interview_segments SET body = '', raw_speaker_label = NULL, "
                "uncertainty_reason = NULL, version = version + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE cleanup_version_id IN ("
                "SELECT id FROM interview_cleanup_versions "
                "WHERE source_version_id = ?)",
                (source_version_id,),
            )
            self.connection.execute(
                "UPDATE interview_cleanup_work_items SET output_json = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE cleanup_version_id IN ("
                "SELECT id FROM interview_cleanup_versions "
                "WHERE source_version_id = ?)",
                (source_version_id,),
            )
            self.connection.execute(
                "UPDATE interview_question_analyses SET source_excerpt = '', "
                "source_available = 0, version = version + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE question_unit_id IN ("
                "SELECT q.id FROM interview_question_units q "
                "JOIN interview_cleanup_versions c "
                "ON c.id = q.cleanup_version_id WHERE c.source_version_id = ?)",
                (source_version_id,),
            )
            self.connection.execute(
                "UPDATE interview_analysis_work_items SET output_json = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE analysis_run_id IN ("
                "SELECT a.id FROM interview_analysis_runs a "
                "JOIN interview_cleanup_versions c "
                "ON c.id = a.cleanup_version_id WHERE c.source_version_id = ?)",
                (source_version_id,),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_source_version(source_version_id)

    def active_execution_count(self, retrospective_id: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM agent_runs r "
            "JOIN interview_retrospectives i ON "
            "r.session_id IN (i.analysis_session_id, i.chat_session_id) "
            "WHERE i.id = ? AND r.status IN ("
            "'queued', 'running', 'waiting_for_approval')",
            (retrospective_id,),
        ).fetchone()
        return int(row[0])

    def deletion_impact(self, retrospective_id: str) -> dict[str, int]:
        self.get_retrospective(retrospective_id)
        counts: dict[str, int] = {}
        for key, table in (
            ("sourceVersions", "interview_source_versions"),
            ("cleanupVersions", "interview_cleanup_versions"),
            ("analysisRuns", "interview_analysis_runs"),
            ("candidates", "interview_asset_candidates"),
            ("actionItems", "interview_action_items"),
        ):
            counts[key] = int(
                self.connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE retrospective_id = ?",
                    (retrospective_id,),
                ).fetchone()[0]
            )
        return counts

    def transition_lifecycle(
        self,
        retrospective_id: str,
        *,
        expected_version: int,
        expected_states: tuple[str, ...],
        target_state: str,
    ) -> RetrospectiveRecord:
        placeholders = ", ".join("?" for _ in expected_states)
        cursor = self.connection.execute(
            "UPDATE interview_retrospectives SET lifecycle_status = ?, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND version = ? "
            f"AND lifecycle_status IN ({placeholders})",
            (
                target_state,
                retrospective_id,
                expected_version,
                *expected_states,
            ),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("复盘状态或版本已更新")
        self.connection.commit()
        return self.get_retrospective(retrospective_id)

    def delete_permanently(self, retrospective_id: str) -> None:
        retrospective = self.get_retrospective(retrospective_id)
        try:
            self.connection.execute(
                "DELETE FROM interview_retrospectives WHERE id = ?",
                (retrospective_id,),
            )
            self.connection.execute(
                "DELETE FROM agent_sessions WHERE id IN (?, ?)",
                (
                    retrospective.analysis_session_id,
                    retrospective.chat_session_id,
                ),
            )
            self.connection.commit()
        except sqlite3.Error:
            self.connection.rollback()
            raise

    def receipt(
        self, retrospective_id: str, scope: str, idempotency_key: str
    ) -> tuple[str, dict[str, object]] | None:
        row = self.connection.execute(
            "SELECT request_hash, result_json FROM interview_write_receipts "
            "WHERE retrospective_id = ? AND scope = ? AND idempotency_key = ?",
            (retrospective_id, scope, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        return row["request_hash"], json.loads(row["result_json"])

    def save_receipt(
        self,
        retrospective_id: str,
        *,
        scope: str,
        idempotency_key: str,
        request_hash: str,
        result: dict[str, object],
    ) -> None:
        self.connection.execute(
            "INSERT INTO interview_write_receipts("
            "id, retrospective_id, scope, idempotency_key, request_hash, result_json"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                retrospective_id,
                scope,
                idempotency_key,
                request_hash,
                json.dumps(result, ensure_ascii=False, sort_keys=True),
            ),
        )
        self.connection.commit()


def _retrospective(row: sqlite3.Row) -> RetrospectiveRecord:
    return RetrospectiveRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        job_target_id=row["job_target_id"],
        title=row["title"],
        round_label=row["round_label"],
        interview_date=row["interview_date"],
        outcome=row["outcome"],
        note=row["note"],
        lifecycle_status=row["lifecycle_status"],
        active_source_version_id=row["active_source_version_id"],
        active_cleanup_version_id=row["active_cleanup_version_id"],
        active_analysis_run_id=row["active_analysis_run_id"],
        analysis_session_id=row["analysis_session_id"],
        chat_session_id=row["chat_session_id"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _source(row: sqlite3.Row) -> SourceVersionRecord:
    return SourceVersionRecord(
        id=row["id"],
        retrospective_id=row["retrospective_id"],
        ordinal=row["ordinal"],
        source_kind=row["source_kind"],
        file_name=row["file_name"],
        body=row["body"],
        content_sha256=row["content_sha256"],
        cleared_at=row["cleared_at"],
        created_at=row["created_at"],
    )


def _cleanup(row: sqlite3.Row) -> CleanupVersionRecord:
    return CleanupVersionRecord(
        id=row["id"],
        retrospective_id=row["retrospective_id"],
        source_version_id=row["source_version_id"],
        ordinal=row["ordinal"],
        execution_id=row["execution_id"],
        input_digest=row["input_digest"],
        status=row["status"],
        stage=row["stage"],
        control_intent=row["control_intent"],
        confirmed_at=row["confirmed_at"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _segment(row: sqlite3.Row) -> SegmentRecord:
    return SegmentRecord(
        id=row["id"],
        cleanup_version_id=row["cleanup_version_id"],
        ordinal=row["ordinal"],
        speaker_role=row["speaker_role"],
        raw_speaker_label=row["raw_speaker_label"],
        display_name=row["display_name"],
        body=row["body"],
        source_start=row["source_start"],
        source_end=row["source_end"],
        confidence=row["confidence"],
        uncertainty_reason=row["uncertainty_reason"],
        ignored=bool(row["ignored"]),
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
