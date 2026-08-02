from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from typing import Protocol
from uuid import uuid4

from app.interview_retrospectives.errors import (
    RetrospectiveNotFound,
    RetrospectiveVersionConflict,
)
from app.interview_retrospectives.models import (
    ActionItemRecord,
    AnalysisRunRecord,
    AnalysisWorkItemRecord,
    AssetCandidateRecord,
    CleanupVersionRecord,
    CleanupWorkItemRecord,
    CorrectionProposalRecord,
    GapRecord,
    QuestionAnalysisRecord,
    QuestionUnitRecord,
    RetrospectiveRecord,
    SegmentRecord,
    SourceVersionRecord,
)


class CleanupWindow(Protocol):
    source_start: int
    source_end: int
    body: str

    @property
    def work_key(self) -> str: ...


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

    def retrospective_by_create_key(
        self, *, workspace_id: str, idempotency_key: str
    ) -> RetrospectiveRecord | None:
        row = self.connection.execute(
            "SELECT * FROM interview_retrospectives "
            "WHERE workspace_id = ? AND create_idempotency_key = ?",
            (workspace_id, idempotency_key),
        ).fetchone()
        return None if row is None else _retrospective(row)

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

    def update_retrospective(
        self,
        retrospective_id: str,
        *,
        title: str,
        round_label: str,
        interview_date: str | None,
        outcome: str,
        note: str,
        expected_version: int,
    ) -> RetrospectiveRecord:
        cursor = self.connection.execute(
            "UPDATE interview_retrospectives SET title = ?, round_label = ?, "
            "interview_date = ?, outcome = ?, note = ?, version = version + 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND version = ?",
            (
                title,
                round_label,
                interview_date,
                outcome,
                note,
                retrospective_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("复盘版本已更新")
        self.connection.commit()
        return self.get_retrospective(retrospective_id)

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

    def latest_cleanup_version(
        self, retrospective_id: str
    ) -> CleanupVersionRecord | None:
        row = self.connection.execute(
            "SELECT * FROM interview_cleanup_versions "
            "WHERE retrospective_id = ? ORDER BY ordinal DESC, rowid DESC LIMIT 1",
            (retrospective_id,),
        ).fetchone()
        return _cleanup(row) if row is not None else None

    def insert_cleanup_run(
        self,
        retrospective_id: str,
        *,
        source_version_id: str,
        input_digest: str,
        windows: Iterable[CleanupWindow],
    ) -> CleanupVersionRecord:
        ordinal = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 "
                "FROM interview_cleanup_versions WHERE retrospective_id = ?",
                (retrospective_id,),
            ).fetchone()[0]
        )
        cleanup_id = str(uuid4())
        try:
            self.connection.execute(
                "INSERT INTO interview_cleanup_versions("
                "id, retrospective_id, source_version_id, ordinal, input_digest, "
                "status, stage) VALUES (?, ?, ?, ?, ?, 'queued', 'normalizing')",
                (
                    cleanup_id,
                    retrospective_id,
                    source_version_id,
                    ordinal,
                    input_digest,
                ),
            )
            for window in windows:
                digest = hashlib.sha256(window.body.encode("utf-8")).hexdigest()
                self.connection.execute(
                    "INSERT INTO interview_cleanup_work_items("
                    "id, cleanup_version_id, work_key, source_start, source_end, "
                    "input_digest) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        cleanup_id,
                        window.work_key,
                        window.source_start,
                        window.source_end,
                        digest,
                    ),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_cleanup_version(cleanup_id)

    def list_cleanup_work_items(
        self, cleanup_id: str
    ) -> tuple[CleanupWorkItemRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM interview_cleanup_work_items "
            "WHERE cleanup_version_id = ? ORDER BY source_start, rowid",
            (cleanup_id,),
        ).fetchall()
        return tuple(_cleanup_work_item(row) for row in rows)

    def list_resumable_cleanup_work_items(
        self, cleanup_id: str
    ) -> tuple[CleanupWorkItemRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM interview_cleanup_work_items "
            "WHERE cleanup_version_id = ? "
            "AND status IN ('pending', 'retryable', 'interrupted') "
            "ORDER BY source_start, rowid",
            (cleanup_id,),
        ).fetchall()
        return tuple(_cleanup_work_item(row) for row in rows)

    def claim_cleanup_work_item(self, item_id: str) -> CleanupWorkItemRecord:
        cursor = self.connection.execute(
            "UPDATE interview_cleanup_work_items SET status = 'running', "
            "attempt_count = attempt_count + 1, last_error_code = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? "
            "AND status IN ('pending', 'retryable', 'interrupted')",
            (item_id,),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("整理窗口已被处理")
        self.connection.commit()
        return self.get_cleanup_work_item(item_id)

    def get_cleanup_work_item(self, item_id: str) -> CleanupWorkItemRecord:
        row = self.connection.execute(
            "SELECT * FROM interview_cleanup_work_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise RetrospectiveNotFound(item_id)
        return _cleanup_work_item(row)

    def complete_cleanup_work_item(
        self, item_id: str, *, output: dict[str, object]
    ) -> CleanupWorkItemRecord:
        cursor = self.connection.execute(
            "UPDATE interview_cleanup_work_items SET status = 'completed', "
            "output_json = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'running'",
            (json.dumps(output, ensure_ascii=False, sort_keys=True), item_id),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("整理窗口状态已更新")
        self.connection.commit()
        return self.get_cleanup_work_item(item_id)

    def stop_cleanup(self, cleanup_id: str) -> CleanupVersionRecord:
        try:
            self.connection.execute(
                "UPDATE interview_cleanup_work_items SET status = 'interrupted', "
                "updated_at = CURRENT_TIMESTAMP WHERE cleanup_version_id = ? "
                "AND status IN ('pending', 'running', 'retryable')",
                (cleanup_id,),
            )
            cursor = self.connection.execute(
                "UPDATE interview_cleanup_versions SET status = 'stopped', "
                "stage = 'stopped', control_intent = 'stop', version = version + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? "
                "AND status IN ('queued', 'running', 'stopping')",
                (cleanup_id,),
            )
            if cursor.rowcount != 1:
                raise RetrospectiveVersionConflict("整理任务已结束")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_cleanup_version(cleanup_id)

    def attach_cleanup_execution(
        self, cleanup_id: str, *, execution_id: str
    ) -> CleanupVersionRecord:
        cursor = self.connection.execute(
            "UPDATE interview_cleanup_versions SET execution_id = ?, "
            "status = 'running', stage = 'cleaning', version = version + 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'queued'",
            (execution_id, cleanup_id),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("整理任务已经启动")
        self.connection.commit()
        return self.get_cleanup_version(cleanup_id)

    def rearm_cleanup(self, cleanup_id: str) -> CleanupVersionRecord:
        try:
            self.connection.execute(
                "UPDATE interview_cleanup_work_items SET status = 'interrupted', "
                "updated_at = CURRENT_TIMESTAMP WHERE cleanup_version_id = ? "
                "AND status = 'running'",
                (cleanup_id,),
            )
            cursor = self.connection.execute(
                "UPDATE interview_cleanup_versions SET status = 'queued', "
                "stage = 'cleaning', control_intent = NULL, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status IN ('stopped', 'failed')",
                (cleanup_id,),
            )
            if cursor.rowcount != 1:
                raise RetrospectiveVersionConflict("整理任务不能继续")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_cleanup_version(cleanup_id)

    def mark_cleanup_review_pending(self, cleanup_id: str) -> CleanupVersionRecord:
        cursor = self.connection.execute(
            "UPDATE interview_cleanup_versions SET status = 'review_pending', "
            "stage = 'waiting_for_review', control_intent = NULL, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'running'",
            (cleanup_id,),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("整理任务状态已更新")
        self.connection.commit()
        return self.get_cleanup_version(cleanup_id)

    def fail_cleanup(self, cleanup_id: str, *, error_code: str) -> None:
        self.connection.execute(
            "UPDATE interview_cleanup_work_items SET status = 'retryable', "
            "last_error_code = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE cleanup_version_id = ? AND status = 'running'",
            (error_code, cleanup_id),
        )
        self.connection.execute(
            "UPDATE interview_cleanup_versions SET status = 'failed', "
            "stage = 'failed', version = version + 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'running'",
            (cleanup_id,),
        )
        self.connection.commit()

    def reconcile_interrupted_cleanup_runs(self) -> tuple[str, ...]:
        rows = self.connection.execute(
            "SELECT c.id FROM interview_cleanup_versions c "
            "JOIN agent_runs r ON r.id = c.execution_id "
            "WHERE c.status IN ('queued', 'running', 'stopping') "
            "AND r.status IN ('interrupted', 'cancelled') "
            "ORDER BY c.created_at, c.id"
        ).fetchall()
        cleanup_ids = tuple(str(row["id"]) for row in rows)
        try:
            for cleanup_id in cleanup_ids:
                self.connection.execute(
                    "UPDATE interview_cleanup_work_items "
                    "SET status = 'interrupted', updated_at = CURRENT_TIMESTAMP "
                    "WHERE cleanup_version_id = ? AND status = 'running'",
                    (cleanup_id,),
                )
                self.connection.execute(
                    "UPDATE interview_cleanup_versions SET status = 'stopped', "
                    "stage = 'stopped', control_intent = 'stop', "
                    "version = version + 1, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (cleanup_id,),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return cleanup_ids

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

    def insert_analysis_run(
        self,
        retrospective_id: str,
        *,
        cleanup_version_id: str,
        input_digest: str,
        context_snapshot: dict[str, object],
        retry_of_analysis_run_id: str | None = None,
    ) -> AnalysisRunRecord:
        run_id = str(uuid4())
        try:
            self.connection.execute(
                "INSERT INTO interview_analysis_runs("
                "id, retrospective_id, cleanup_version_id, "
                "retry_of_analysis_run_id, input_digest, context_snapshot_json, "
                "total_items) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (
                    run_id,
                    retrospective_id,
                    cleanup_version_id,
                    retry_of_analysis_run_id,
                    input_digest,
                    json.dumps(context_snapshot, ensure_ascii=False, sort_keys=True),
                ),
            )
            self.connection.execute(
                "INSERT INTO interview_analysis_work_items("
                "id, analysis_run_id, work_key, input_digest) VALUES (?, ?, ?, ?)",
                (str(uuid4()), run_id, "question_extraction", input_digest),
            )
            self.connection.execute(
                "UPDATE interview_retrospectives SET active_analysis_run_id = ?, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (run_id, retrospective_id),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_analysis_run(run_id)

    def get_analysis_run(self, run_id: str) -> AnalysisRunRecord:
        row = self.connection.execute(
            "SELECT * FROM interview_analysis_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RetrospectiveNotFound(run_id)
        return _analysis_run(row)

    def current_analysis_run(self, retrospective_id: str) -> AnalysisRunRecord | None:
        row = self.connection.execute(
            "SELECT * FROM interview_analysis_runs WHERE retrospective_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (retrospective_id,),
        ).fetchone()
        return None if row is None else _analysis_run(row)

    def analysis_run_by_digest(
        self,
        retrospective_id: str,
        *,
        cleanup_version_id: str,
        input_digest: str,
    ) -> AnalysisRunRecord | None:
        row = self.connection.execute(
            "SELECT * FROM interview_analysis_runs WHERE retrospective_id = ? "
            "AND cleanup_version_id = ? AND input_digest = ? "
            "AND retry_of_analysis_run_id IS NULL "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (retrospective_id, cleanup_version_id, input_digest),
        ).fetchone()
        return None if row is None else _analysis_run(row)

    def list_analysis_work_items(
        self, run_id: str
    ) -> tuple[AnalysisWorkItemRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM interview_analysis_work_items WHERE analysis_run_id = ? "
            "ORDER BY CASE work_key WHEN 'question_extraction' THEN 0 "
            "WHEN 'gap_verification' THEN 2 WHEN 'candidate_generation' THEN 3 "
            "WHEN 'final_projection' THEN 4 ELSE 1 END, created_at, rowid",
            (run_id,),
        ).fetchall()
        return tuple(_analysis_work_item(row) for row in rows)

    def replace_question_units(
        self,
        run_id: str,
        *,
        questions: tuple[dict[str, object], ...],
    ) -> tuple[QuestionUnitRecord, ...]:
        run = self.get_analysis_run(run_id)
        segment_ids = {
            row["id"]
            for row in self.connection.execute(
                "SELECT id FROM interview_segments WHERE cleanup_version_id = ? "
                "AND ignored = 0",
                (run.cleanup_version_id,),
            ).fetchall()
        }
        existing = {
            row["stable_key"]: row
            for row in self.connection.execute(
                "SELECT * FROM interview_question_units WHERE cleanup_version_id = ?",
                (run.cleanup_version_id,),
            ).fetchall()
        }
        current_ids: list[str] = []
        try:
            self.connection.execute(
                "UPDATE interview_question_units SET ordinal = ordinal + 1000000, "
                "decision_status = 'superseded', updated_at = CURRENT_TIMESTAMP "
                "WHERE cleanup_version_id = ?",
                (run.cleanup_version_id,),
            )
            for item in questions:
                question_segments = tuple(item["question_segment_ids"])
                answer_segments = tuple(item["answer_segment_ids"])
                if set(question_segments + answer_segments) - segment_ids:
                    raise RetrospectiveVersionConflict(
                        "问题引用了当前整理版本之外的片段"
                    )
                origin = str(item["origin"])
                question_text = str(item["question_text"]).strip()
                stable_key = hashlib.sha256(
                    json.dumps(
                        {
                            "origin": origin,
                            "question": question_text,
                            "questionSegments": question_segments,
                            "answerSegments": answer_segments,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest()
                previous = existing.get(stable_key)
                if previous is None:
                    question_id = str(uuid4())
                    self.connection.execute(
                        "INSERT INTO interview_question_units("
                        "id, retrospective_id, cleanup_version_id, stable_key, ordinal, "
                        "question_kind, origin, question_text, "
                        "question_segment_ids_json, answer_segment_ids_json, "
                        "inference_basis, confidence, decision_status) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            question_id,
                            run.retrospective_id,
                            run.cleanup_version_id,
                            stable_key,
                            int(item["ordinal"]),
                            str(item["question_kind"]),
                            origin,
                            question_text,
                            json.dumps(question_segments),
                            json.dumps(answer_segments),
                            str(item.get("inference_basis", "")),
                            float(item["confidence"]),
                            "confirmed" if origin == "original" else "pending",
                        ),
                    )
                else:
                    question_id = previous["id"]
                    decision = previous["decision_status"]
                    if decision == "superseded":
                        decision = "confirmed" if origin == "original" else "pending"
                    self.connection.execute(
                        "UPDATE interview_question_units SET ordinal = ?, "
                        "question_kind = ?, origin = ?, question_segment_ids_json = ?, "
                        "answer_segment_ids_json = ?, inference_basis = ?, confidence = ?, "
                        "decision_status = ?, version = version + 1, "
                        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (
                            int(item["ordinal"]),
                            str(item["question_kind"]),
                            origin,
                            json.dumps(question_segments),
                            json.dumps(answer_segments),
                            str(item.get("inference_basis", "")),
                            float(item["confidence"]),
                            decision,
                            question_id,
                        ),
                    )
                current_ids.append(question_id)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return tuple(self.get_question(question_id) for question_id in current_ids)

    def get_question(self, question_id: str) -> QuestionUnitRecord:
        row = self.connection.execute(
            "SELECT * FROM interview_question_units WHERE id = ?", (question_id,)
        ).fetchone()
        if row is None:
            raise RetrospectiveNotFound(question_id)
        return _question(row)

    def list_questions(
        self,
        retrospective_id: str,
        *,
        cleanup_version_id: str | None = None,
    ) -> tuple[QuestionUnitRecord, ...]:
        clause = "retrospective_id = ?"
        values: list[object] = [retrospective_id]
        if cleanup_version_id is not None:
            clause += " AND cleanup_version_id = ?"
            values.append(cleanup_version_id)
        rows = self.connection.execute(
            f"SELECT * FROM interview_question_units WHERE {clause} "
            "ORDER BY ordinal, rowid",
            values,
        ).fetchall()
        return tuple(_question(row) for row in rows)

    def schedule_analysis_work_items(
        self,
        run_id: str,
        *,
        question_ids: tuple[str, ...],
        include_finalizers: bool = True,
    ) -> tuple[AnalysisWorkItemRecord, ...]:
        run = self.get_analysis_run(run_id)
        keys = [
            (f"question_analysis:{question_id}", question_id)
            for question_id in question_ids
        ]
        if include_finalizers:
            keys.extend(
                (
                    ("gap_verification", None),
                    ("candidate_generation", None),
                    ("final_projection", None),
                )
            )
        try:
            for work_key, question_id in keys:
                digest = hashlib.sha256(
                    f"{run.input_digest}:{work_key}".encode("utf-8")
                ).hexdigest()
                self.connection.execute(
                    "INSERT INTO interview_analysis_work_items("
                    "id, analysis_run_id, question_unit_id, work_key, input_digest) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(analysis_run_id, work_key) "
                    "DO UPDATE SET status = CASE "
                    "WHEN interview_analysis_work_items.status = 'running' "
                    "THEN 'running' ELSE 'pending' END, output_json = CASE "
                    "WHEN interview_analysis_work_items.status = 'running' "
                    "THEN interview_analysis_work_items.output_json ELSE NULL END, "
                    "last_error_code = CASE "
                    "WHEN interview_analysis_work_items.status = 'running' "
                    "THEN 'rerun_requested' ELSE NULL END, "
                    "updated_at = CURRENT_TIMESTAMP",
                    (str(uuid4()), run_id, question_id, work_key, digest),
                )
            count = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM interview_analysis_work_items "
                    "WHERE analysis_run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            )
            completed = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM interview_analysis_work_items "
                    "WHERE analysis_run_id = ? AND status = 'completed'",
                    (run_id,),
                ).fetchone()[0]
            )
            self.connection.execute(
                "UPDATE interview_analysis_runs SET total_items = ?, "
                "completed_items = ?, "
                "status = CASE WHEN status IN ('completed','review_pending','stopped','failed') "
                "THEN 'queued' ELSE status END, stage = 'analyzing_questions', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (count, completed, run_id),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.list_analysis_work_items(run_id)

    def decide_question(
        self,
        question_id: str,
        *,
        decision: str,
        edited_text: str | None,
        expected_version: int,
    ) -> QuestionUnitRecord:
        values: list[object] = [decision]
        assignment = "decision_status = ?"
        if edited_text is not None:
            assignment += ", question_text = ?"
            values.append(edited_text)
        cursor = self.connection.execute(
            f"UPDATE interview_question_units SET {assignment}, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND version = ?",
            (*values, question_id, expected_version),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("问题版本已更新")
        self.connection.commit()
        return self.get_question(question_id)

    def attach_analysis_execution(
        self, run_id: str, *, execution_id: str
    ) -> AnalysisRunRecord:
        cursor = self.connection.execute(
            "UPDATE interview_analysis_runs SET execution_id = ?, status = 'running', "
            "control_intent = NULL, latest_progress_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? "
            "AND status IN ('queued', 'stopped', 'failed', 'review_pending')",
            (execution_id, run_id),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("分析运行状态已更新")
        self.connection.commit()
        return self.get_analysis_run(run_id)

    def list_resumable_analysis_work_items(
        self, run_id: str
    ) -> tuple[AnalysisWorkItemRecord, ...]:
        return tuple(
            item
            for item in self.list_analysis_work_items(run_id)
            if item.status in {"pending", "retryable", "interrupted"}
        )

    def claim_analysis_work_item(self, item_id: str) -> AnalysisWorkItemRecord:
        cursor = self.connection.execute(
            "UPDATE interview_analysis_work_items SET status = 'running', "
            "attempt_count = attempt_count + 1, last_error_code = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? "
            "AND status IN ('pending', 'retryable', 'interrupted')",
            (item_id,),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("分析工作项已被处理")
        row = self.connection.execute(
            "SELECT analysis_run_id, work_key FROM interview_analysis_work_items "
            "WHERE id = ?",
            (item_id,),
        ).fetchone()
        stage = "analyzing_questions"
        if row["work_key"] == "question_extraction":
            stage = "question_extraction"
        elif row["work_key"] == "gap_verification":
            stage = "verifying_gaps"
        elif row["work_key"] == "candidate_generation":
            stage = "generating_candidates"
        elif row["work_key"] == "final_projection":
            stage = "finalizing"
        self.connection.execute(
            "UPDATE interview_analysis_runs SET status = 'running', "
            "stage = ?, current_work_key = ?, latest_progress_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (stage, row["work_key"], row["analysis_run_id"]),
        )
        self.connection.commit()
        return self.get_analysis_work_item(item_id)

    def get_analysis_work_item(self, item_id: str) -> AnalysisWorkItemRecord:
        row = self.connection.execute(
            "SELECT * FROM interview_analysis_work_items WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise RetrospectiveNotFound(item_id)
        return _analysis_work_item(row)

    def complete_analysis_work_item(
        self, item_id: str, *, output: dict[str, object]
    ) -> AnalysisWorkItemRecord:
        item = self.get_analysis_work_item(item_id)
        cursor = self.connection.execute(
            "UPDATE interview_analysis_work_items SET status = CASE "
            "WHEN last_error_code = 'rerun_requested' THEN 'pending' "
            "ELSE 'completed' END, output_json = CASE "
            "WHEN last_error_code = 'rerun_requested' THEN NULL ELSE ? END, "
            "last_error_code = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ? "
            "AND status = 'running'",
            (json.dumps(output, ensure_ascii=False, sort_keys=True), item_id),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("分析工作项未处于运行状态")
        completed = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM interview_analysis_work_items "
                "WHERE analysis_run_id = ? AND status = 'completed'",
                (item.analysis_run_id,),
            ).fetchone()[0]
        )
        self.connection.execute(
            "UPDATE interview_analysis_runs SET completed_items = ?, "
            "current_work_key = NULL, latest_progress_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (completed, item.analysis_run_id),
        )
        self.connection.commit()
        return self.get_analysis_work_item(item_id)

    def save_question_analysis(
        self,
        run_id: str,
        question_id: str,
        *,
        output: dict[str, object],
        source_excerpt: str,
        result_status: str = "formal",
    ) -> QuestionAnalysisRecord:
        analysis_id = str(uuid4())
        source_hash = (
            hashlib.sha256(source_excerpt.encode("utf-8")).hexdigest()
            if source_excerpt
            else None
        )
        existing = self.connection.execute(
            "SELECT id FROM interview_question_analyses "
            "WHERE analysis_run_id = ? AND question_unit_id = ?",
            (run_id, question_id),
        ).fetchone()
        if existing is not None:
            analysis_id = existing["id"]
        try:
            self.connection.execute(
                "INSERT INTO interview_question_analyses("
                "id, analysis_run_id, question_unit_id, verdict, strengths_json, "
                "improvements_json, omissions_json, evidence_level, confidence, "
                "improvement_outline_json, suggested_answer, source_excerpt, "
                "source_excerpt_sha256, source_available, result_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?) "
                "ON CONFLICT(analysis_run_id, question_unit_id) DO UPDATE SET "
                "verdict = excluded.verdict, strengths_json = excluded.strengths_json, "
                "improvements_json = excluded.improvements_json, "
                "omissions_json = excluded.omissions_json, "
                "evidence_level = excluded.evidence_level, "
                "confidence = excluded.confidence, "
                "improvement_outline_json = excluded.improvement_outline_json, "
                "suggested_answer = excluded.suggested_answer, "
                "source_excerpt = excluded.source_excerpt, "
                "source_excerpt_sha256 = excluded.source_excerpt_sha256, "
                "source_available = 1, result_status = excluded.result_status, "
                "version = interview_question_analyses.version + 1, "
                "updated_at = CURRENT_TIMESTAMP",
                (
                    analysis_id,
                    run_id,
                    question_id,
                    str(output["verdict"]),
                    json.dumps(output.get("strengths", []), ensure_ascii=False),
                    json.dumps(output.get("improvements", []), ensure_ascii=False),
                    json.dumps(output.get("omissions", []), ensure_ascii=False),
                    str(output["evidenceLevel"]),
                    float(output["confidence"]),
                    json.dumps(
                        output.get("improvementOutline", []), ensure_ascii=False
                    ),
                    str(output.get("suggestedAnswer", "")),
                    source_excerpt,
                    source_hash,
                    result_status,
                ),
            )
            self.connection.execute(
                "DELETE FROM interview_gaps WHERE analysis_run_id = ? "
                "AND question_unit_id = ?",
                (run_id, question_id),
            )
            for gap in output.get("gaps", []):
                self.connection.execute(
                    "INSERT INTO interview_gaps("
                    "id, analysis_run_id, question_analysis_id, question_unit_id, "
                    "gap_kind, summary, evidence_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        run_id,
                        analysis_id,
                        question_id,
                        str(gap["kind"]),
                        str(gap["summary"]),
                        json.dumps(
                            gap.get("evidenceSegmentIds", []),
                            ensure_ascii=False,
                        ),
                    ),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_question_analysis(run_id, question_id)

    def get_question_analysis(
        self, run_id: str, question_id: str
    ) -> QuestionAnalysisRecord:
        row = self.connection.execute(
            "SELECT * FROM interview_question_analyses "
            "WHERE analysis_run_id = ? AND question_unit_id = ?",
            (run_id, question_id),
        ).fetchone()
        if row is None:
            raise RetrospectiveNotFound(question_id)
        return _question_analysis(row)

    def list_question_analyses(self, run_id: str) -> tuple[QuestionAnalysisRecord, ...]:
        rows = self.connection.execute(
            "SELECT a.* FROM interview_question_analyses a "
            "JOIN interview_question_units q ON q.id = a.question_unit_id "
            "WHERE a.analysis_run_id = ? ORDER BY q.ordinal, a.rowid",
            (run_id,),
        ).fetchall()
        return tuple(_question_analysis(row) for row in rows)

    def list_gaps(self, run_id: str) -> tuple[GapRecord, ...]:
        rows = self.connection.execute(
            "SELECT g.* FROM interview_gaps g "
            "JOIN interview_question_units q ON q.id = g.question_unit_id "
            "WHERE g.analysis_run_id = ? ORDER BY q.ordinal, g.rowid",
            (run_id,),
        ).fetchall()
        return tuple(_gap(row) for row in rows)

    def create_correction_proposal(
        self,
        retrospective_id: str,
        *,
        chat_message_id: str | None,
        proposal_type: str,
        target_question_id: str | None,
        source_cleanup_version_id: str,
        source_analysis_run_id: str | None,
        before: dict[str, object],
        after: dict[str, object],
        rationale: str,
        expected_version: int,
    ) -> CorrectionProposalRecord:
        proposal_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO interview_retrospective_corrections("
            "id, retrospective_id, chat_message_id, proposal_type, "
            "target_question_id, source_cleanup_version_id, source_analysis_run_id, "
            "before_json, after_json, rationale, expected_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                proposal_id,
                retrospective_id,
                chat_message_id,
                proposal_type,
                target_question_id,
                source_cleanup_version_id,
                source_analysis_run_id,
                json.dumps(before, ensure_ascii=False, sort_keys=True),
                json.dumps(after, ensure_ascii=False, sort_keys=True),
                rationale,
                expected_version,
            ),
        )
        self.connection.commit()
        return self.get_correction_proposal(proposal_id)

    def get_correction_proposal(self, proposal_id: str) -> CorrectionProposalRecord:
        row = self.connection.execute(
            "SELECT * FROM interview_retrospective_corrections WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            raise RetrospectiveNotFound(proposal_id)
        return _correction_proposal(row)

    def list_correction_proposals(
        self, retrospective_id: str
    ) -> tuple[CorrectionProposalRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM interview_retrospective_corrections "
            "WHERE retrospective_id = ? ORDER BY created_at, rowid",
            (retrospective_id,),
        ).fetchall()
        return tuple(_correction_proposal(row) for row in rows)

    def decide_correction_proposal(
        self,
        proposal_id: str,
        *,
        status: str,
        resulting_cleanup_version_id: str | None = None,
        resulting_analysis_run_id: str | None = None,
    ) -> CorrectionProposalRecord:
        cursor = self.connection.execute(
            "UPDATE interview_retrospective_corrections SET status = ?, "
            "resulting_cleanup_version_id = ?, resulting_analysis_run_id = ?, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'pending'",
            (
                status,
                resulting_cleanup_version_id,
                resulting_analysis_run_id,
                proposal_id,
            ),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("纠正建议已经处理")
        self.connection.commit()
        return self.get_correction_proposal(proposal_id)

    def apply_question_correction(
        self,
        question_id: str,
        *,
        expected_version: int,
        question_text: str | None = None,
        question_segment_ids: tuple[str, ...] | None = None,
        answer_segment_ids: tuple[str, ...] | None = None,
    ) -> QuestionUnitRecord:
        question = self.get_question(question_id)
        segment_ids = {
            item.id for item in self.list_segments(question.cleanup_version_id)
        }
        requested = (question_segment_ids or ()) + (answer_segment_ids or ())
        if set(requested) - segment_ids:
            raise RetrospectiveVersionConflict("问题引用了当前整理版本之外的片段")
        next_text = (
            question.question_text if question_text is None else question_text.strip()
        )
        if not next_text:
            raise ValueError("问题正文不能为空")
        next_question_segments = (
            question.question_segment_ids
            if question_segment_ids is None
            else question_segment_ids
        )
        next_answer_segments = (
            question.answer_segment_ids
            if answer_segment_ids is None
            else answer_segment_ids
        )
        if not next_answer_segments:
            raise ValueError("问题必须至少关联一个回答片段")
        if question.origin == "original" and not next_question_segments:
            raise ValueError("原文问题必须至少关联一个问题片段")
        cursor = self.connection.execute(
            "UPDATE interview_question_units SET question_text = ?, "
            "question_segment_ids_json = ?, answer_segment_ids_json = ?, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND version = ?",
            (
                next_text,
                json.dumps(next_question_segments),
                json.dumps(next_answer_segments),
                question_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("问题版本已更新")
        self.connection.commit()
        return self.get_question(question_id)

    def insert_local_reanalysis_run(
        self,
        retrospective_id: str,
        *,
        source_run_id: str,
        question_id: str,
        input_digest: str,
        context_snapshot: dict[str, object],
    ) -> AnalysisRunRecord:
        source = self.get_analysis_run(source_run_id)
        question = self.get_question(question_id)
        if (
            source.retrospective_id != retrospective_id
            or question.retrospective_id != retrospective_id
            or question.cleanup_version_id != source.cleanup_version_id
        ):
            raise RetrospectiveVersionConflict("局部重算来源不属于当前复盘版本")
        run_id = str(uuid4())
        keys = (
            (f"question_analysis:{question_id}", question_id),
            ("gap_verification", None),
            ("candidate_generation", None),
            ("final_projection", None),
        )
        try:
            self.connection.execute(
                "INSERT INTO interview_analysis_runs("
                "id, retrospective_id, cleanup_version_id, retry_of_analysis_run_id, "
                "input_digest, context_snapshot_json, total_items, stage) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'analyzing_questions')",
                (
                    run_id,
                    retrospective_id,
                    source.cleanup_version_id,
                    source_run_id,
                    input_digest,
                    json.dumps(context_snapshot, ensure_ascii=False, sort_keys=True),
                    len(keys),
                ),
            )
            for work_key, target_question_id in keys:
                digest = hashlib.sha256(
                    f"{input_digest}:{work_key}".encode("utf-8")
                ).hexdigest()
                self.connection.execute(
                    "INSERT INTO interview_analysis_work_items("
                    "id, analysis_run_id, question_unit_id, work_key, input_digest) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(uuid4()), run_id, target_question_id, work_key, digest),
                )
            self.connection.execute(
                "UPDATE interview_retrospectives SET active_analysis_run_id = ?, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (run_id, retrospective_id),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        gaps_by_question: dict[str, list[GapRecord]] = {}
        for gap in self.list_gaps(source_run_id):
            gaps_by_question.setdefault(gap.question_unit_id, []).append(gap)
        for analysis in self.list_question_analyses(source_run_id):
            if analysis.question_unit_id == question_id:
                continue
            self.save_question_analysis(
                run_id,
                analysis.question_unit_id,
                output={
                    "verdict": analysis.verdict,
                    "strengths": list(analysis.strengths),
                    "improvements": list(analysis.improvements),
                    "omissions": list(analysis.omissions),
                    "evidenceLevel": analysis.evidence_level,
                    "confidence": analysis.confidence,
                    "improvementOutline": list(analysis.improvement_outline),
                    "suggestedAnswer": analysis.suggested_answer,
                    "gaps": [
                        {
                            "kind": gap.gap_kind,
                            "summary": gap.summary,
                            "evidenceSegmentIds": list(gap.evidence),
                        }
                        for gap in gaps_by_question.get(analysis.question_unit_id, [])
                    ],
                },
                source_excerpt=analysis.source_excerpt,
                result_status=analysis.result_status,
            )
        return self.get_analysis_run(run_id)

    def upsert_asset_candidate(
        self,
        retrospective_id: str,
        *,
        analysis_run_id: str,
        question_unit_id: str | None,
        candidate_kind: str,
        fingerprint: str,
        payload: dict[str, object],
        matches: tuple[dict[str, object], ...] = (),
    ) -> AssetCandidateRecord:
        identifier = str(uuid4())
        self.connection.execute(
            "INSERT INTO interview_asset_candidates("
            "id, retrospective_id, analysis_run_id, question_unit_id, "
            "candidate_kind, fingerprint, payload_json, match_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(retrospective_id, candidate_kind, fingerprint) DO NOTHING",
            (
                identifier,
                retrospective_id,
                analysis_run_id,
                question_unit_id,
                candidate_kind,
                fingerprint,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                json.dumps(matches, ensure_ascii=False, sort_keys=True),
            ),
        )
        row = self.connection.execute(
            "SELECT id FROM interview_asset_candidates "
            "WHERE retrospective_id = ? AND candidate_kind = ? AND fingerprint = ?",
            (retrospective_id, candidate_kind, fingerprint),
        ).fetchone()
        self.connection.commit()
        return self.get_asset_candidate(str(row["id"]))

    def get_asset_candidate(self, candidate_id: str) -> AssetCandidateRecord:
        row = self.connection.execute(
            "SELECT * FROM interview_asset_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise RetrospectiveNotFound(candidate_id)
        return _asset_candidate(row)

    def list_asset_candidates(
        self, retrospective_id: str, *, status: str | None = None
    ) -> tuple[AssetCandidateRecord, ...]:
        query = "SELECT * FROM interview_asset_candidates WHERE retrospective_id = ?"
        values: list[object] = [retrospective_id]
        if status is not None:
            query += " AND status = ?"
            values.append(status)
        rows = self.connection.execute(
            query + " ORDER BY created_at, rowid", values
        ).fetchall()
        return tuple(_asset_candidate(row) for row in rows)

    def transition_asset_candidate(
        self,
        candidate_id: str,
        *,
        status: str,
        target_resource_type: str | None,
        target_resource_id: str | None,
        last_error_code: str | None,
        expected_version: int,
    ) -> AssetCandidateRecord:
        current = self.get_asset_candidate(candidate_id)
        if (
            current.status == status
            and current.target_resource_type == target_resource_type
            and current.target_resource_id == target_resource_id
            and current.last_error_code == last_error_code
        ):
            return current
        cursor = self.connection.execute(
            "UPDATE interview_asset_candidates SET status = ?, "
            "target_resource_type = ?, target_resource_id = ?, last_error_code = ?, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND version = ? AND status IN ('pending','blocked','failed')",
            (
                status,
                target_resource_type,
                target_resource_id,
                last_error_code,
                candidate_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("候选项版本已更新")
        self.connection.commit()
        return self.get_asset_candidate(candidate_id)

    def upsert_action_item(
        self,
        retrospective_id: str,
        *,
        analysis_run_id: str,
        question_unit_id: str | None,
        gap_id: str | None,
        action_kind: str,
        title: str,
        detail: str,
    ) -> ActionItemRecord:
        row = self.connection.execute(
            "SELECT id FROM interview_action_items WHERE retrospective_id = ? "
            "AND question_unit_id IS ? AND action_kind = ? AND title = ?",
            (retrospective_id, question_unit_id, action_kind, title),
        ).fetchone()
        if row is None:
            identifier = str(uuid4())
            self.connection.execute(
                "INSERT INTO interview_action_items("
                "id, retrospective_id, analysis_run_id, question_unit_id, gap_id, "
                "action_kind, title, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    retrospective_id,
                    analysis_run_id,
                    question_unit_id,
                    gap_id,
                    action_kind,
                    title,
                    detail,
                ),
            )
            self.connection.commit()
            row = {"id": identifier}
        return self.get_action_item(str(row["id"]))

    def get_action_item(self, action_id: str) -> ActionItemRecord:
        row = self.connection.execute(
            "SELECT * FROM interview_action_items WHERE id = ?", (action_id,)
        ).fetchone()
        if row is None:
            raise RetrospectiveNotFound(action_id)
        return _action_item(row)

    def list_action_items(self, retrospective_id: str) -> tuple[ActionItemRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM interview_action_items WHERE retrospective_id = ? "
            "ORDER BY created_at, rowid",
            (retrospective_id,),
        ).fetchall()
        return tuple(_action_item(row) for row in rows)

    def decide_action_item(
        self, action_id: str, *, decision: str, expected_version: int
    ) -> ActionItemRecord:
        current = self.get_action_item(action_id)
        if current.status == decision:
            return current
        cursor = self.connection.execute(
            "UPDATE interview_action_items SET status = ?, "
            "completed_at = CASE WHEN ? = 'completed' THEN CURRENT_TIMESTAMP ELSE NULL END, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND version = ? AND status = 'pending'",
            (decision, decision, action_id, expected_version),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise RetrospectiveVersionConflict("行动项版本已更新")
        self.connection.commit()
        return self.get_action_item(action_id)

    def mark_analysis_completed(
        self, run_id: str, *, summary: dict[str, object]
    ) -> AnalysisRunRecord:
        self.connection.execute(
            "UPDATE interview_analysis_runs SET status = 'completed', "
            "stage = 'completed', control_intent = NULL, current_work_key = NULL, "
            "summary_json = ?, latest_progress_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(summary, ensure_ascii=False, sort_keys=True), run_id),
        )
        self.connection.commit()
        return self.get_analysis_run(run_id)

    def stop_analysis(self, run_id: str) -> AnalysisRunRecord:
        try:
            self.connection.execute(
                "UPDATE interview_analysis_work_items SET status = 'interrupted', "
                "updated_at = CURRENT_TIMESTAMP WHERE analysis_run_id = ? "
                "AND status = 'running'",
                (run_id,),
            )
            self.connection.execute(
                "UPDATE interview_analysis_runs SET status = 'stopped', "
                "stage = 'stopped', control_intent = NULL, current_work_key = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? "
                "AND status IN ('queued','running','stopping')",
                (run_id,),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_analysis_run(run_id)

    def request_analysis_stop(self, run_id: str) -> AnalysisRunRecord:
        self.connection.execute(
            "UPDATE interview_analysis_runs SET status = 'stopping', "
            "control_intent = 'stop', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status IN ('queued','running')",
            (run_id,),
        )
        self.connection.commit()
        return self.get_analysis_run(run_id)

    def rearm_analysis(self, run_id: str) -> AnalysisRunRecord:
        try:
            self.connection.execute(
                "UPDATE interview_analysis_work_items SET status = 'pending', "
                "updated_at = CURRENT_TIMESTAMP WHERE analysis_run_id = ? "
                "AND status IN ('interrupted','retryable')",
                (run_id,),
            )
            self.connection.execute(
                "UPDATE interview_analysis_runs SET status = 'queued', "
                "stage = CASE WHEN completed_items = 0 THEN 'question_extraction' "
                "ELSE 'analyzing_questions' END, control_intent = NULL, "
                "current_work_key = NULL, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status IN ('stopped','failed')",
                (run_id,),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_analysis_run(run_id)

    def fail_analysis(self, run_id: str, *, error_code: str) -> AnalysisRunRecord:
        self.connection.execute(
            "UPDATE interview_analysis_work_items SET status = 'retryable', "
            "last_error_code = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE analysis_run_id = ? AND status = 'running'",
            (error_code, run_id),
        )
        self.connection.execute(
            "UPDATE interview_analysis_runs SET status = 'failed', stage = 'failed', "
            "control_intent = NULL, current_work_key = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (run_id,),
        )
        self.connection.commit()
        return self.get_analysis_run(run_id)

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

    def target_summary(self, job_target_id: str) -> dict[str, object]:
        rows = self.connection.execute(
            "SELECT id, title, round_label, interview_date, outcome, "
            "lifecycle_status, created_at FROM interview_retrospectives "
            "WHERE job_target_id = ? AND lifecycle_status != 'recycled' "
            "ORDER BY COALESCE(interview_date, created_at) DESC, created_at DESC, id",
            (job_target_id,),
        ).fetchall()
        gap_rows = self.connection.execute(
            "SELECT g.gap_kind, COUNT(*) AS count FROM interview_gaps g "
            "JOIN interview_retrospectives r ON r.active_analysis_run_id = g.analysis_run_id "
            "WHERE r.job_target_id = ? AND r.lifecycle_status != 'recycled' "
            "AND g.status = 'open' GROUP BY g.gap_kind ORDER BY g.gap_kind",
            (job_target_id,),
        ).fetchall()
        action_row = self.connection.execute(
            "SELECT COUNT(*) FROM interview_action_items a "
            "JOIN interview_retrospectives r ON r.id = a.retrospective_id "
            "WHERE r.job_target_id = ? AND r.lifecycle_status != 'recycled' "
            "AND a.status = 'pending'",
            (job_target_id,),
        ).fetchone()

        def timeline_item(row) -> dict[str, object]:
            return {
                "retrospectiveId": row["id"],
                "title": row["title"],
                "roundLabel": row["round_label"],
                "interviewDate": row["interview_date"],
                "outcome": row["outcome"],
                "lifecycleStatus": row["lifecycle_status"],
            }

        timeline = [timeline_item(row) for row in rows]
        return {
            "retrospectiveCount": len(timeline),
            "latest": timeline[0] if timeline else None,
            "unresolvedActionCount": int(action_row[0]),
            "gapCounts": {row["gap_kind"]: int(row["count"]) for row in gap_rows},
            "timeline": timeline,
        }

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


def _cleanup_work_item(row: sqlite3.Row) -> CleanupWorkItemRecord:
    return CleanupWorkItemRecord(
        id=row["id"],
        cleanup_version_id=row["cleanup_version_id"],
        work_key=row["work_key"],
        source_start=row["source_start"],
        source_end=row["source_end"],
        input_digest=row["input_digest"],
        status=row["status"],
        output=(None if row["output_json"] is None else json.loads(row["output_json"])),
        attempt_count=row["attempt_count"],
        last_error_code=row["last_error_code"],
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


def _analysis_run(row: sqlite3.Row) -> AnalysisRunRecord:
    return AnalysisRunRecord(
        id=row["id"],
        retrospective_id=row["retrospective_id"],
        cleanup_version_id=row["cleanup_version_id"],
        execution_id=row["execution_id"],
        retry_of_analysis_run_id=row["retry_of_analysis_run_id"],
        input_digest=row["input_digest"],
        context_snapshot_json=row["context_snapshot_json"],
        status=row["status"],
        stage=row["stage"],
        control_intent=row["control_intent"],
        completed_items=row["completed_items"],
        total_items=row["total_items"],
        current_work_key=row["current_work_key"],
        cumulative_elapsed_ms=row["cumulative_elapsed_ms"],
        latest_progress_at=row["latest_progress_at"],
        summary_json=row["summary_json"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _analysis_work_item(row: sqlite3.Row) -> AnalysisWorkItemRecord:
    return AnalysisWorkItemRecord(
        id=row["id"],
        analysis_run_id=row["analysis_run_id"],
        question_unit_id=row["question_unit_id"],
        work_key=row["work_key"],
        input_digest=row["input_digest"],
        status=row["status"],
        output=None if row["output_json"] is None else json.loads(row["output_json"]),
        attempt_count=row["attempt_count"],
        last_error_code=row["last_error_code"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _correction_proposal(row: sqlite3.Row) -> CorrectionProposalRecord:
    return CorrectionProposalRecord(
        id=row["id"],
        retrospective_id=row["retrospective_id"],
        chat_message_id=row["chat_message_id"],
        proposal_type=row["proposal_type"],
        target_question_id=row["target_question_id"],
        source_cleanup_version_id=row["source_cleanup_version_id"],
        source_analysis_run_id=row["source_analysis_run_id"],
        before=json.loads(row["before_json"]),
        after=json.loads(row["after_json"]),
        rationale=row["rationale"],
        expected_version=row["expected_version"],
        status=row["status"],
        resulting_cleanup_version_id=row["resulting_cleanup_version_id"],
        resulting_analysis_run_id=row["resulting_analysis_run_id"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _question(row: sqlite3.Row) -> QuestionUnitRecord:
    return QuestionUnitRecord(
        id=row["id"],
        retrospective_id=row["retrospective_id"],
        cleanup_version_id=row["cleanup_version_id"],
        stable_key=row["stable_key"],
        ordinal=row["ordinal"],
        question_kind=row["question_kind"],
        origin=row["origin"],
        question_text=row["question_text"],
        question_segment_ids=tuple(json.loads(row["question_segment_ids_json"])),
        answer_segment_ids=tuple(json.loads(row["answer_segment_ids_json"])),
        inference_basis=row["inference_basis"],
        confidence=row["confidence"],
        decision_status=row["decision_status"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _question_analysis(row: sqlite3.Row) -> QuestionAnalysisRecord:
    return QuestionAnalysisRecord(
        id=row["id"],
        analysis_run_id=row["analysis_run_id"],
        question_unit_id=row["question_unit_id"],
        verdict=row["verdict"],
        strengths=tuple(json.loads(row["strengths_json"])),
        improvements=tuple(json.loads(row["improvements_json"])),
        omissions=tuple(json.loads(row["omissions_json"])),
        evidence_level=row["evidence_level"],
        confidence=row["confidence"],
        improvement_outline=tuple(json.loads(row["improvement_outline_json"])),
        suggested_answer=row["suggested_answer"],
        source_excerpt=row["source_excerpt"],
        source_excerpt_sha256=row["source_excerpt_sha256"],
        source_available=bool(row["source_available"]),
        result_status=row["result_status"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _asset_candidate(row: sqlite3.Row) -> AssetCandidateRecord:
    return AssetCandidateRecord(
        id=row["id"],
        retrospective_id=row["retrospective_id"],
        analysis_run_id=row["analysis_run_id"],
        question_unit_id=row["question_unit_id"],
        candidate_kind=row["candidate_kind"],
        fingerprint=row["fingerprint"],
        payload_json=row["payload_json"],
        match_json=row["match_json"],
        status=row["status"],
        target_resource_type=row["target_resource_type"],
        target_resource_id=row["target_resource_id"],
        last_error_code=row["last_error_code"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _action_item(row: sqlite3.Row) -> ActionItemRecord:
    return ActionItemRecord(
        id=row["id"],
        retrospective_id=row["retrospective_id"],
        analysis_run_id=row["analysis_run_id"],
        question_unit_id=row["question_unit_id"],
        gap_id=row["gap_id"],
        action_kind=row["action_kind"],
        title=row["title"],
        detail=row["detail"],
        status=row["status"],
        version=row["version"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _gap(row: sqlite3.Row) -> GapRecord:
    return GapRecord(
        id=row["id"],
        analysis_run_id=row["analysis_run_id"],
        question_analysis_id=row["question_analysis_id"],
        question_unit_id=row["question_unit_id"],
        gap_kind=row["gap_kind"],
        summary=row["summary"],
        evidence=tuple(json.loads(row["evidence_json"])),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
