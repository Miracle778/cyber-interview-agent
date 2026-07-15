from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
from typing import Any, Iterator, cast
from uuid import uuid4

from app.review.errors import (
    InputAlreadyResolvedError,
    ReviewConflictError,
    ReviewRoundNotFoundError,
)
from app.review.models import (
    AttemptStatus,
    CurationContextRecord,
    CurationSessionRecord,
    CurationStage,
    CurationSummary,
    CurationCommandReceiptRecord,
    Difficulty,
    InputKind,
    MasteryEntry,
    MasteryProjection,
    QuestionBatchRecord,
    QuestionCandidateRecord,
    QuestionCatalogRecord,
    QuestionSnapshot,
    QuestionSourceLinkRecord,
    ReasoningEffort,
    ReportProposalRecord,
    ReviewAttemptRecord,
    ReviewAnswerReceipt,
    ReviewInputReceipt,
    ReviewInputRequestRecord,
    ReviewMode,
    ReviewRoundRecord,
    ReviewRoundSettings,
    RoundStatus,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


class ReviewRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row

    def create_curation_session(
        self,
        *,
        workspace_id: str,
        session_id: str,
        source_refs: tuple[str, ...],
        warnings: tuple[dict[str, object], ...] = (),
    ) -> CurationSessionRecord:
        if not source_refs:
            raise ValueError("curation session requires at least one source")
        with self._transaction():
            self._connection.execute(
                "INSERT INTO review_curation_sessions "
                "(session_id, workspace_id, source_refs_json, warning_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    session_id,
                    workspace_id,
                    _canonical_json(source_refs),
                    _canonical_json(warnings),
                ),
            )
        return self.get_curation_session(session_id)

    def get_curation_session(self, session_id: str) -> CurationSessionRecord:
        row = self._connection.execute(
            "SELECT * FROM review_curation_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise LookupError(session_id)
        return self._curation_session_record(row)

    def list_curation_sessions(
        self,
        workspace_id: str,
        *,
        deleted_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[CurationSessionRecord, ...]:
        rows = self._connection.execute(
            "SELECT c.* FROM review_curation_sessions c "
            "JOIN agent_sessions s ON s.id = c.session_id "
            "WHERE c.workspace_id = ? AND s.deleted_at IS "
            + ("NOT NULL " if deleted_only else "NULL ")
            + "ORDER BY c.updated_at DESC, c.rowid DESC LIMIT ? OFFSET ?",
            (workspace_id, limit, offset),
        ).fetchall()
        return tuple(self._curation_session_record(row) for row in rows)

    def update_curation_progress(
        self,
        session_id: str,
        *,
        stage: CurationStage,
        completed_units: int,
        total_units: int,
        active_batch_id: str | None = None,
    ) -> CurationSessionRecord:
        if completed_units < 0 or total_units < 0 or (
            total_units and completed_units > total_units
        ):
            raise ValueError("invalid curation progress")
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_curation_sessions SET stage = ?, "
                "completed_units = ?, total_units = ?, "
                "active_batch_id = COALESCE(?, active_batch_id), "
                "updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (
                    stage,
                    completed_units,
                    total_units,
                    active_batch_id,
                    session_id,
                ),
            )
            if cursor.rowcount != 1:
                raise LookupError(session_id)
        return self.get_curation_session(session_id)

    def replace_curation_summary(
        self,
        session_id: str,
        *,
        expected_version: int,
        summary: CurationSummary,
    ) -> CurationSessionRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_curation_sessions SET summary_json = ?, "
                "summary_version = summary_version + 1, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE session_id = ? AND summary_version = ?",
                (
                    _canonical_json({"items": summary.items}),
                    session_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("curation summary version changed")
        return self.get_curation_session(session_id)

    def upsert_question_source_link(
        self,
        *,
        question_id: str,
        source_id: str,
        batch_id: str,
        session_id: str,
        evidence_ref: str,
        merge_reason: str,
        link_id: str | None = None,
    ) -> QuestionSourceLinkRecord:
        existing = self._connection.execute(
            "SELECT * FROM review_question_source_links "
            "WHERE question_id = ? AND source_id = ? AND evidence_ref = ?",
            (question_id, source_id, evidence_ref),
        ).fetchone()
        if existing is not None:
            record = self._question_source_link_record(existing)
            if (
                record.batch_id != batch_id
                or record.session_id != session_id
                or record.merge_reason != merge_reason
            ):
                raise ReviewConflictError("question source link identity changed")
            return record
        identifier = link_id or str(uuid4())
        with self._transaction():
            self._connection.execute(
                "INSERT INTO review_question_source_links "
                "(id, question_id, source_id, batch_id, session_id, "
                "evidence_ref, merge_reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    question_id,
                    source_id,
                    batch_id,
                    session_id,
                    evidence_ref,
                    merge_reason,
                ),
            )
        return self._require_question_source_link(identifier)

    def list_question_source_links(
        self, question_id: str
    ) -> tuple[QuestionSourceLinkRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM review_question_source_links WHERE question_id = ? "
            "ORDER BY created_at, rowid",
            (question_id,),
        ).fetchall()
        return tuple(self._question_source_link_record(row) for row in rows)

    def get_or_create_curation_context(
        self, session_id: str
    ) -> CurationContextRecord:
        with self._transaction():
            self._connection.execute(
                "INSERT OR IGNORE INTO review_curation_context(session_id) "
                "VALUES (?)",
                (session_id,),
            )
        row = self._connection.execute(
            "SELECT * FROM review_curation_context WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise LookupError(session_id)
        return self._curation_context_record(row)

    def replace_curation_context(
        self,
        session_id: str,
        *,
        expected_version: int,
        focused_candidate_ids: tuple[str, ...],
        last_intent: str | None,
        last_result_candidate_ids: tuple[str, ...],
        dialogue_summary: dict[str, object],
        summarized_through_message_id: str | None,
    ) -> CurationContextRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_curation_context SET version = version + 1, "
                "focused_candidate_ids_json = ?, last_intent = ?, "
                "last_result_candidate_ids_json = ?, dialogue_summary_json = ?, "
                "summarized_through_message_id = ?, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE session_id = ? AND version = ?",
                (
                    _canonical_json(focused_candidate_ids),
                    last_intent,
                    _canonical_json(last_result_candidate_ids),
                    _canonical_json(dialogue_summary),
                    summarized_through_message_id,
                    session_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("curation context version changed")
        return self.get_or_create_curation_context(session_id)

    def find_curation_command_receipt(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        text: str,
        summary_version: int,
    ) -> CurationCommandReceiptRecord | None:
        row = self._connection.execute(
            "SELECT * FROM review_curation_command_receipts "
            "WHERE session_id = ? AND idempotency_key = ?",
            (session_id, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        record = self._curation_command_receipt(row)
        if (
            record.text_hash != sha256(text.encode("utf-8")).hexdigest()
            or record.summary_version != summary_version
        ):
            raise ReviewConflictError(
                "curation command idempotency key changed"
            )
        return record

    def begin_curation_command(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        text: str,
        summary_version: int,
        command: dict[str, object],
        receipt_id: str | None = None,
    ) -> tuple[CurationCommandReceiptRecord, bool]:
        text_hash = sha256(text.encode("utf-8")).hexdigest()
        existing = self.find_curation_command_receipt(
            session_id=session_id,
            idempotency_key=idempotency_key,
            text=text,
            summary_version=summary_version,
        )
        if existing is not None:
            return existing, False
        identifier = receipt_id or str(uuid4())
        with self._transaction():
            self._connection.execute(
                "INSERT INTO review_curation_command_receipts "
                "(id, session_id, idempotency_key, text_hash, "
                "summary_version, command_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    session_id,
                    idempotency_key,
                    text_hash,
                    summary_version,
                    _canonical_json(command),
                ),
            )
        return self.get_curation_command_receipt(identifier), True

    def get_curation_command_receipt(
        self, receipt_id: str
    ) -> CurationCommandReceiptRecord:
        row = self._connection.execute(
            "SELECT * FROM review_curation_command_receipts WHERE id = ?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise LookupError(receipt_id)
        return self._curation_command_receipt(row)

    def complete_curation_command(
        self,
        receipt_id: str,
        *,
        result: dict[str, object],
        status: str = "completed",
    ) -> CurationCommandReceiptRecord:
        if status not in {"completed", "partial_failure", "failed"}:
            raise ValueError("unsupported curation command terminal status")
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_curation_command_receipts SET result_json = ?, "
                "status = ?, completed_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'processing'",
                (_canonical_json(result), status, receipt_id),
            )
            if cursor.rowcount != 1:
                current = self.get_curation_command_receipt(receipt_id)
                if current.status != status or current.result != result:
                    raise ReviewConflictError(
                        "curation command receipt already completed"
                    )
        return self.get_curation_command_receipt(receipt_id)

    def create_batch(
        self,
        *,
        workspace_id: str,
        session_id: str,
        run_id: str | None,
        source_refs: tuple[str, ...],
        rewrite_of_batch_id: str | None = None,
        status: str = "generating",
        batch_id: str | None = None,
    ) -> QuestionBatchRecord:
        identifier = batch_id or str(uuid4())
        with self._transaction():
            self._connection.execute(
                "INSERT INTO review_question_batches "
                "(id, workspace_id, session_id, run_id, source_refs_json, "
                "rewrite_of_batch_id, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    workspace_id,
                    session_id,
                    run_id,
                    _canonical_json(source_refs),
                    rewrite_of_batch_id,
                    status,
                ),
            )
        return self.get_batch(identifier)

    def get_batch(self, batch_id: str) -> QuestionBatchRecord:
        row = self._connection.execute(
            "SELECT * FROM review_question_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if row is None:
            raise LookupError(batch_id)
        return self._batch_record(row)

    def list_batches(
        self, workspace_id: str, *, status: str | None = None
    ) -> tuple[QuestionBatchRecord, ...]:
        clauses = ["workspace_id = ?"]
        values: list[object] = [workspace_id]
        if status is not None:
            clauses.append("status = ?")
            values.append(status)
        rows = self._connection.execute(
            "SELECT * FROM review_question_batches WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC, rowid DESC",
            tuple(values),
        ).fetchall()
        return tuple(self._batch_record(row) for row in rows)

    def update_batch_status(self, batch_id: str, status: str) -> QuestionBatchRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_question_batches SET status = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, batch_id),
            )
            if cursor.rowcount != 1:
                raise LookupError(batch_id)
        return self.get_batch(batch_id)

    def attach_batch_run(
        self, batch_id: str, run_id: str
    ) -> QuestionBatchRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_question_batches SET run_id = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND run_id IS NULL",
                (run_id, batch_id),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("question batch already has a run")
        return self.get_batch(batch_id)

    def reconcile_abandoned_work(self) -> tuple[int, int]:
        """Close domain work whose owning execution cannot continue after restart."""
        with self._transaction():
            batches = self._connection.execute(
                "UPDATE review_question_batches SET status = 'failed', "
                "updated_at = CURRENT_TIMESTAMP WHERE status = 'generating' "
                "AND run_id IN (SELECT id FROM agent_runs WHERE status IN "
                "('interrupted', 'failed', 'cancelled'))"
            ).rowcount
            rounds = self._connection.execute(
                "UPDATE review_rounds SET status = 'failed', "
                "updated_at = CURRENT_TIMESTAMP WHERE status = 'running' "
                "AND execution_id IN (SELECT id FROM agent_runs WHERE status IN "
                "('interrupted', 'failed', 'cancelled')) "
                "AND NOT EXISTS (SELECT 1 FROM review_attempts attempt "
                "WHERE attempt.round_id = review_rounds.id "
                "AND attempt.status IN ('evaluating', 'evaluation_failed'))"
            ).rowcount
        return batches, rounds

    def list_evaluating_attempts(self) -> tuple[ReviewAttemptRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM review_attempts WHERE status = 'evaluating' "
            "ORDER BY created_at, id"
        ).fetchall()
        return tuple(self._attempt_record(row) for row in rows)

    def resolved_input_for_attempt(
        self, attempt: ReviewAttemptRecord
    ) -> tuple[ReviewInputRequestRecord, ReviewAnswerReceipt]:
        kind = "follow_up" if attempt.follow_up_answer is not None else "answer"
        request_row = self._connection.execute(
            "SELECT * FROM review_input_requests WHERE round_id = ? "
            "AND ordinal = ? AND kind = ? AND status = 'resolved' "
            "ORDER BY version DESC, created_at DESC LIMIT 1",
            (attempt.round_id, attempt.ordinal, kind),
        ).fetchone()
        if request_row is None:
            raise LookupError(attempt.id)
        receipt_row = self._connection.execute(
            "SELECT * FROM review_input_receipts WHERE input_request_id = ?",
            (request_row["id"],),
        ).fetchone()
        if receipt_row is None:
            raise LookupError(attempt.id)
        return (
            self._input_request_record(request_row),
            self._answer_receipt(receipt_row),
        )

    def save_candidate(
        self,
        *,
        batch_id: str,
        question: QuestionSnapshot,
        draft_id: str | None,
        source_refs: tuple[str, ...] = (),
        correction_note: str = "",
        duplicate_of_question_id: str | None = None,
        status: str = "draft",
        candidate_id: str | None = None,
    ) -> QuestionCandidateRecord:
        identifier = candidate_id or str(uuid4())
        with self._transaction():
            self._connection.execute(
                "INSERT INTO review_question_candidates "
                "(id, batch_id, draft_id, question_json, source_refs_json, "
                "correction_note, duplicate_of_question_id, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    batch_id,
                    draft_id,
                    _canonical_json(asdict(question)),
                    _canonical_json(source_refs),
                    correction_note,
                    duplicate_of_question_id,
                    status,
                ),
            )
        return self.get_candidate(identifier)

    def get_candidate(self, candidate_id: str) -> QuestionCandidateRecord:
        row = self._connection.execute(
            "SELECT * FROM review_question_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise LookupError(candidate_id)
        return self._candidate_record(row)

    def get_candidate_by_draft(
        self, draft_id: str
    ) -> QuestionCandidateRecord | None:
        row = self._connection.execute(
            "SELECT * FROM review_question_candidates WHERE draft_id = ?",
            (draft_id,),
        ).fetchone()
        return None if row is None else self._candidate_record(row)

    def list_candidates(
        self,
        workspace_id: str,
        *,
        query: str | None = None,
        topic: str | None = None,
        difficulty: str | None = None,
        source_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[QuestionCandidateRecord, ...]:
        rows = self._connection.execute(
            "SELECT c.* FROM review_question_candidates c "
            "JOIN review_question_batches b ON b.id = c.batch_id "
            "WHERE b.workspace_id = ? ORDER BY c.updated_at DESC, c.rowid DESC",
            (workspace_id,),
        ).fetchall()
        records = [self._candidate_record(row) for row in rows]
        if query:
            needle = query.casefold()
            records = [
                item
                for item in records
                if needle in item.question.title.casefold()
                or needle in item.question.question_text.casefold()
            ]
        if topic:
            records = [item for item in records if topic in item.question.topics]
        if difficulty:
            records = [
                item for item in records if item.question.difficulty == difficulty
            ]
        if source_id:
            records = [
                item
                for item in records
                if source_id in item.source_refs
            ]
        if status:
            records = [item for item in records if item.status == status]
        return tuple(records[offset : offset + limit])

    def update_candidate(
        self,
        candidate_id: str,
        *,
        question: QuestionSnapshot,
        status: str | None = None,
    ) -> QuestionCandidateRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_question_candidates SET question_json = ?, "
                "status = COALESCE(?, status), updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (_canonical_json(asdict(question)), status, candidate_id),
            )
            if cursor.rowcount != 1:
                raise LookupError(candidate_id)
        return self.get_candidate(candidate_id)

    def update_candidate_status(
        self, candidate_id: str, *, status: str
    ) -> QuestionCandidateRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_question_candidates SET status = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, candidate_id),
            )
            if cursor.rowcount != 1:
                raise LookupError(candidate_id)
        return self.get_candidate(candidate_id)

    def update_candidate_review_note(
        self, candidate_id: str, *, review_note: str
    ) -> QuestionCandidateRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_question_candidates SET review_note = ?, "
                "review_note_updated_at = CURRENT_TIMESTAMP, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (review_note, candidate_id),
            )
            if cursor.rowcount != 1:
                raise LookupError(candidate_id)
        return self.get_candidate(candidate_id)

    def activate_question(
        self,
        *,
        candidate_id: str,
        workspace_id: str,
        document_id: str,
        draft_id: str,
        publication_id: str,
        content_hash: str,
    ) -> QuestionCatalogRecord:
        with self._transaction():
            candidate_row = self._connection.execute(
                "SELECT * FROM review_question_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
            if candidate_row is None:
                raise LookupError(candidate_id)
            candidate = self._candidate_record(candidate_row)
            if candidate.draft_id != draft_id:
                raise ReviewConflictError("candidate draft does not match")

            existing = self._connection.execute(
                "SELECT * FROM review_question_catalog "
                "WHERE draft_id = ? OR publication_id = ?",
                (draft_id, publication_id),
            ).fetchone()
            if existing is None:
                self._connection.execute(
                    "INSERT INTO review_question_catalog "
                    "(question_id, workspace_id, document_id, draft_id, "
                    "publication_id, question_json, content_hash, active) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                    (
                        candidate.question.question_id,
                        workspace_id,
                        document_id,
                        draft_id,
                        publication_id,
                        candidate_row["question_json"],
                        content_hash,
                    ),
                )
            else:
                if (
                    existing["question_id"] != candidate.question.question_id
                    or existing["draft_id"] != draft_id
                    or existing["publication_id"] != publication_id
                    or existing["content_hash"] != content_hash
                ):
                    raise ReviewConflictError(
                        "publication already projects different question facts"
                    )
            self._connection.execute(
                "UPDATE review_question_candidates SET status = 'published', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (candidate_id,),
            )
        return self._require_catalog(candidate.question.question_id)

    def list_active_questions(
        self,
        workspace_id: str,
        *,
        topic: str | None = None,
        difficulty: str | None = None,
    ) -> tuple[QuestionCatalogRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM review_question_catalog "
            "WHERE workspace_id = ? AND active = 1 "
            "ORDER BY published_at, rowid",
            (workspace_id,),
        ).fetchall()
        records = tuple(self._catalog_record(row) for row in rows)
        if topic is not None:
            records = tuple(
                item for item in records if topic in item.snapshot.topics
            )
        if difficulty is not None:
            records = tuple(
                item
                for item in records
                if item.snapshot.difficulty == difficulty
            )
        return records

    def get_active_question(self, question_id: str) -> QuestionCatalogRecord:
        record = self._require_catalog(question_id)
        if not record.active:
            raise LookupError(question_id)
        return record

    def create_round(
        self,
        *,
        workspace_id: str,
        session_id: str,
        execution_id: str | None,
        settings: ReviewRoundSettings,
        question_snapshots: tuple[QuestionSnapshot, ...],
        mastery_before: MasteryProjection,
        round_id: str | None = None,
    ) -> ReviewRoundRecord:
        identifier = round_id or str(uuid4())
        with self._transaction():
            self._connection.execute(
                "INSERT INTO review_rounds "
                "(id, workspace_id, session_id, execution_id, settings_json, "
                "question_snapshots_json, mastery_before_json, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'waiting_for_input')",
                (
                    identifier,
                    workspace_id,
                    session_id,
                    execution_id,
                    _canonical_json(asdict(settings)),
                    _canonical_json(
                        [asdict(snapshot) for snapshot in question_snapshots]
                    ),
                    _canonical_json(asdict(mastery_before)),
                ),
            )
        return self.get_round(identifier)

    def get_round(self, round_id: str) -> ReviewRoundRecord:
        row = self._connection.execute(
            "SELECT * FROM review_rounds WHERE id = ?", (round_id,)
        ).fetchone()
        if row is None:
            raise ReviewRoundNotFoundError(round_id)
        return self._round_record(row)

    def get_round_by_session(self, session_id: str) -> ReviewRoundRecord:
        row = self._connection.execute(
            "SELECT * FROM review_rounds WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise ReviewRoundNotFoundError(session_id)
        return self._round_record(row)

    def list_rounds(self, workspace_id: str) -> tuple[ReviewRoundRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM review_rounds WHERE workspace_id = ? "
            "ORDER BY updated_at DESC, rowid DESC",
            (workspace_id,),
        ).fetchall()
        return tuple(self._round_record(row) for row in rows)

    def pending_input(self, round_id: str) -> ReviewInputRequestRecord | None:
        row = self._connection.execute(
            "SELECT * FROM review_input_requests "
            "WHERE round_id = ? AND status = 'pending' "
            "ORDER BY version DESC, rowid DESC LIMIT 1",
            (round_id,),
        ).fetchone()
        return None if row is None else self._input_request_record(row)

    def create_input_request(
        self,
        *,
        round_id: str,
        ordinal: int,
        kind: InputKind,
        prompt: str,
        version: int = 1,
        request_id: str | None = None,
    ) -> ReviewInputRequestRecord:
        identifier = request_id or str(uuid4())
        with self._transaction():
            self._connection.execute(
                "INSERT INTO review_input_requests "
                "(id, round_id, ordinal, kind, prompt, version) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (identifier, round_id, ordinal, kind, prompt, version),
            )
        return self.get_input_request(identifier)

    def ensure_input_request(
        self,
        *,
        round_id: str,
        ordinal: int,
        kind: InputKind,
        prompt: str,
        version: int,
    ) -> ReviewInputRequestRecord:
        row = self._connection.execute(
            "SELECT * FROM review_input_requests "
            "WHERE round_id = ? AND ordinal = ? AND kind = ? AND version = ?",
            (round_id, ordinal, kind, version),
        ).fetchone()
        if row is not None:
            existing = self._input_request_record(row)
            if existing.prompt != prompt:
                raise ReviewConflictError(
                    "input request identity has different prompt"
                )
            return existing
        return self.create_input_request(
            round_id=round_id,
            ordinal=ordinal,
            kind=kind,
            prompt=prompt,
            version=version,
        )

    def get_input_request(self, request_id: str) -> ReviewInputRequestRecord:
        row = self._connection.execute(
            "SELECT * FROM review_input_requests WHERE id = ?", (request_id,)
        ).fetchone()
        if row is None:
            raise LookupError(request_id)
        return self._input_request_record(row)

    def resolve_input(
        self,
        request_id: str,
        *,
        idempotency_key: str,
        value: str,
        receipt: dict[str, object],
        receipt_id: str | None = None,
    ) -> ReviewInputReceipt:
        with self._transaction():
            request = self._connection.execute(
                "SELECT * FROM review_input_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if request is None:
                raise LookupError(request_id)
            existing = self._connection.execute(
                "SELECT * FROM review_input_receipts "
                "WHERE input_request_id = ?",
                (request_id,),
            ).fetchone()
            if existing is not None:
                if existing["idempotency_key"] != idempotency_key:
                    raise InputAlreadyResolvedError(
                        f"input request {request_id!r} is already resolved"
                    )
                if existing["value_hash"] != sha256(
                    value.encode("utf-8")
                ).hexdigest():
                    raise InputAlreadyResolvedError(
                        f"input request {request_id!r} has different content"
                    )
                return self._input_receipt(existing)
            if request["status"] != "pending":
                raise InputAlreadyResolvedError(
                    f"input request {request_id!r} is {request['status']!r}"
                )
            identifier = receipt_id or str(uuid4())
            self._connection.execute(
                "INSERT INTO review_input_receipts "
                "(id, input_request_id, idempotency_key, value_hash, "
                "receipt_json) VALUES (?, ?, ?, ?, ?)",
                (
                    identifier,
                    request_id,
                    idempotency_key,
                    sha256(value.encode("utf-8")).hexdigest(),
                    _canonical_json(receipt),
                ),
            )
            self._connection.execute(
                "UPDATE review_input_requests SET status = 'resolved', "
                "resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                (request_id,),
            )
            row = self._connection.execute(
                "SELECT * FROM review_input_receipts WHERE id = ?",
                (identifier,),
            ).fetchone()
            assert row is not None
            return self._input_receipt(row)

    def accept_review_answer(
        self,
        *,
        request_id: str,
        expected_version: int,
        idempotency_key: str,
        value: str,
        receipt_id: str | None = None,
        attempt_id: str | None = None,
        message_id: str | None = None,
    ) -> ReviewAnswerReceipt:
        value_hash = sha256(value.encode("utf-8")).hexdigest()
        with self._transaction():
            request = self._connection.execute(
                "SELECT * FROM review_input_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if request is None:
                raise LookupError(request_id)
            if int(request["version"]) != expected_version:
                raise ReviewConflictError("input request version changed")

            existing = self._connection.execute(
                "SELECT * FROM review_input_receipts "
                "WHERE input_request_id = ?",
                (request_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["idempotency_key"] != idempotency_key
                    or existing["value_hash"] != value_hash
                ):
                    raise InputAlreadyResolvedError(
                        f"input request {request_id!r} is already resolved"
                    )
                return self._answer_receipt(existing)
            if request["status"] != "pending":
                raise InputAlreadyResolvedError(
                    f"input request {request_id!r} is {request['status']!r}"
                )

            round_row = self._connection.execute(
                "SELECT * FROM review_rounds WHERE id = ?",
                (request["round_id"],),
            ).fetchone()
            if round_row is None:
                raise ReviewRoundNotFoundError(str(request["round_id"]))
            execution_id = round_row["execution_id"]
            if execution_id is None:
                raise ReviewConflictError("round has no execution")

            execution = self._connection.execute(
                "SELECT status FROM agent_runs WHERE id = ?",
                (execution_id,),
            ).fetchone()
            if execution is None or execution["status"] not in {
                "waiting_for_input",
                "interrupted",
            }:
                raise ReviewConflictError("round execution is not resumable")

            ordinal = int(request["ordinal"])
            snapshots = json.loads(round_row["question_snapshots_json"])
            if not 1 <= ordinal <= len(snapshots):
                raise ReviewConflictError("input ordinal has no frozen question")

            attempt_row = self._connection.execute(
                "SELECT * FROM review_attempts "
                "WHERE round_id = ? AND ordinal = ?",
                (request["round_id"], ordinal),
            ).fetchone()
            if request["kind"] == "answer":
                if attempt_row is not None:
                    raise ReviewConflictError("answer attempt already exists")
                resolved_attempt_id = attempt_id or str(uuid4())
                self._connection.execute(
                    "INSERT INTO review_attempts "
                    "(id, round_id, ordinal, question_snapshot_json, answer, "
                    "status, evaluation_started_at) "
                    "VALUES (?, ?, ?, ?, ?, 'evaluating', CURRENT_TIMESTAMP)",
                    (
                        resolved_attempt_id,
                        request["round_id"],
                        ordinal,
                        _canonical_json(snapshots[ordinal - 1]),
                        value,
                    ),
                )
            else:
                if attempt_row is None:
                    raise ReviewConflictError(
                        "follow-up input requires an existing attempt"
                    )
                resolved_attempt_id = str(attempt_row["id"])
                self._connection.execute(
                    "UPDATE review_attempts SET follow_up_answer = ?, "
                    "status = 'evaluating', evaluation_error_code = NULL, "
                    "evaluation_started_at = CURRENT_TIMESTAMP, "
                    "evaluation_completed_at = NULL, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (value, resolved_attempt_id),
                )

            resolved_message_id = message_id or str(uuid4())
            message_payload = {
                "roundId": request["round_id"],
                "attemptId": resolved_attempt_id,
                "inputRequestId": request_id,
                "ordinal": ordinal,
            }
            self._connection.execute(
                "INSERT INTO agent_messages "
                "(id, session_id, run_id, role, content, message_kind, "
                "payload_json) VALUES (?, ?, ?, 'user', ?, "
                "'review_answer', ?)",
                (
                    resolved_message_id,
                    round_row["session_id"],
                    execution_id,
                    value,
                    _canonical_json(message_payload),
                ),
            )
            resolved_receipt_id = receipt_id or str(uuid4())
            receipt_payload = {
                "roundId": request["round_id"],
                "attemptId": resolved_attempt_id,
                "messageId": resolved_message_id,
                "status": "evaluating",
                "version": int(round_row["version"]),
            }
            self._connection.execute(
                "INSERT INTO review_input_receipts "
                "(id, input_request_id, idempotency_key, value_hash, "
                "receipt_json) VALUES (?, ?, ?, ?, ?)",
                (
                    resolved_receipt_id,
                    request_id,
                    idempotency_key,
                    value_hash,
                    _canonical_json(receipt_payload),
                ),
            )
            self._connection.execute(
                "UPDATE review_input_requests SET status = 'resolved', "
                "resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                (request_id,),
            )
            cursor = self._connection.execute(
                "UPDATE agent_runs SET status = 'running', "
                "resume_count = resume_count + 1, "
                "last_resumed_at = CURRENT_TIMESTAMP, finished_at = NULL "
                "WHERE id = ? AND status IN ('waiting_for_input', 'interrupted')",
                (execution_id,),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("round execution changed before resume")
            self._connection.execute(
                "UPDATE agent_sessions SET status = 'active', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (round_row["session_id"],),
            )
            receipt_row = self._connection.execute(
                "SELECT * FROM review_input_receipts WHERE id = ?",
                (resolved_receipt_id,),
            ).fetchone()
            assert receipt_row is not None
            return self._answer_receipt(receipt_row)

    def save_attempt(
        self,
        *,
        round_id: str,
        ordinal: int,
        question_snapshot: QuestionSnapshot,
        answer: str | None,
        evaluation: dict[str, object] | None,
        mastery_suggestion: str | None,
        follow_up_answer: str | None = None,
        skipped: bool = False,
        attempt_id: str | None = None,
    ) -> str:
        identifier = attempt_id or str(uuid4())
        with self._transaction():
            existing = self._connection.execute(
                "SELECT id FROM review_attempts "
                "WHERE round_id = ? AND ordinal = ?",
                (round_id, ordinal),
            ).fetchone()
            if existing is not None:
                if existing["id"] != identifier:
                    raise ReviewConflictError(
                        f"attempt {ordinal} already exists for round {round_id}"
                    )
                return str(existing["id"])
            self._connection.execute(
                "INSERT INTO review_attempts "
                "(id, round_id, ordinal, question_snapshot_json, answer, "
                "follow_up_answer, evaluation_json, mastery_suggestion, skipped) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    round_id,
                    ordinal,
                    _canonical_json(asdict(question_snapshot)),
                    answer,
                    follow_up_answer,
                    None if evaluation is None else _canonical_json(evaluation),
                    mastery_suggestion,
                    1 if skipped else 0,
                ),
            )
        return identifier

    def list_attempts(self, round_id: str) -> tuple[ReviewAttemptRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM review_attempts WHERE round_id = ? "
            "ORDER BY ordinal, id",
            (round_id,),
        ).fetchall()
        return tuple(self._attempt_record(row) for row in rows)

    def get_attempt(self, attempt_id: str) -> ReviewAttemptRecord:
        row = self._connection.execute(
            "SELECT * FROM review_attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
        if row is None:
            raise LookupError(attempt_id)
        return self._attempt_record(row)

    def complete_attempt_evaluation(
        self,
        attempt_id: str,
        *,
        evaluation: dict[str, object],
        mastery_suggestion: str,
        needs_follow_up: bool,
    ) -> ReviewAttemptRecord:
        target = "waiting_for_follow_up" if needs_follow_up else "completed"
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_attempts SET evaluation_json = ?, "
                "mastery_suggestion = ?, status = ?, "
                "evaluation_error_code = NULL, "
                "evaluation_completed_at = CURRENT_TIMESTAMP, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'evaluating'",
                (
                    _canonical_json(evaluation),
                    mastery_suggestion,
                    target,
                    attempt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("attempt is not awaiting evaluation")
        return self.get_attempt(attempt_id)

    def fail_attempt_evaluation(
        self, attempt_id: str, *, error_code: str
    ) -> ReviewAttemptRecord:
        if not error_code or len(error_code) > 100:
            raise ValueError("evaluation error code must be stable and bounded")
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_attempts SET status = 'evaluation_failed', "
                "evaluation_error_code = ?, "
                "evaluation_completed_at = CURRENT_TIMESTAMP, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'evaluating'",
                (error_code, attempt_id),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("attempt is not awaiting evaluation")
        return self.get_attempt(attempt_id)

    def retry_attempt_evaluation(
        self, attempt_id: str, *, idempotency_key: str
    ) -> ReviewAnswerReceipt:
        with self._transaction():
            existing = self._connection.execute(
                "SELECT * FROM review_evaluation_retry_receipts "
                "WHERE attempt_id = ? AND idempotency_key = ?",
                (attempt_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                return self._retry_answer_receipt(existing)
            attempt = self._connection.execute(
                "SELECT * FROM review_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if attempt is None:
                raise LookupError(attempt_id)
            if attempt["status"] != "evaluation_failed":
                raise ReviewConflictError("attempt is not retryable")
            kind = "follow_up" if attempt["follow_up_answer"] is not None else "answer"
            request = self._connection.execute(
                "SELECT * FROM review_input_requests WHERE round_id = ? "
                "AND ordinal = ? AND kind = ? AND status = 'resolved' "
                "ORDER BY version DESC, created_at DESC LIMIT 1",
                (attempt["round_id"], attempt["ordinal"], kind),
            ).fetchone()
            if request is None:
                raise ReviewConflictError("retry input receipt is missing")
            round_row = self._connection.execute(
                "SELECT * FROM review_rounds WHERE id = ?",
                (attempt["round_id"],),
            ).fetchone()
            if round_row is None or round_row["execution_id"] is None:
                raise ReviewConflictError("round execution is missing")
            execution = self._connection.execute(
                "SELECT status FROM agent_runs WHERE id = ?",
                (round_row["execution_id"],),
            ).fetchone()
            if execution is None or execution["status"] != "interrupted":
                raise ReviewConflictError("evaluation execution is not retryable")
            self._connection.execute(
                "UPDATE review_attempts SET status = 'evaluating', "
                "evaluation_error_code = NULL, "
                "evaluation_started_at = CURRENT_TIMESTAMP, "
                "evaluation_completed_at = NULL, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (attempt_id,),
            )
            self._connection.execute(
                "UPDATE agent_runs SET status = 'running', error_code = NULL, "
                "error_message = NULL, resume_count = resume_count + 1, "
                "last_resumed_at = CURRENT_TIMESTAMP, finished_at = NULL "
                "WHERE id = ?",
                (round_row["execution_id"],),
            )
            self._connection.execute(
                "UPDATE agent_sessions SET status = 'active', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (round_row["session_id"],),
            )
            identifier = str(uuid4())
            payload = {
                "roundId": attempt["round_id"],
                "attemptId": attempt_id,
                "inputRequestId": request["id"],
                "status": "evaluating",
                "version": int(round_row["version"]),
            }
            self._connection.execute(
                "INSERT INTO review_evaluation_retry_receipts "
                "(id, attempt_id, input_request_id, idempotency_key, receipt_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    identifier,
                    attempt_id,
                    request["id"],
                    idempotency_key,
                    _canonical_json(payload),
                ),
            )
            row = self._connection.execute(
                "SELECT * FROM review_evaluation_retry_receipts WHERE id = ?",
                (identifier,),
            ).fetchone()
            assert row is not None
            return self._retry_answer_receipt(row)

    def find_evaluation_retry_receipt(
        self, round_id: str, *, idempotency_key: str
    ) -> ReviewAnswerReceipt | None:
        row = self._connection.execute(
            "SELECT receipt.* FROM review_evaluation_retry_receipts receipt "
            "JOIN review_attempts attempt ON attempt.id = receipt.attempt_id "
            "WHERE attempt.round_id = ? AND receipt.idempotency_key = ? "
            "ORDER BY receipt.created_at DESC, receipt.rowid DESC LIMIT 1",
            (round_id, idempotency_key),
        ).fetchone()
        return self._retry_answer_receipt(row) if row is not None else None

    def advance_round(
        self,
        round_id: str,
        *,
        expected_version: int,
        current_index: int,
        status: RoundStatus,
    ) -> ReviewRoundRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_rounds SET current_index = ?, status = ?, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP, "
                "completed_at = CASE WHEN ? = 'completed' "
                "THEN CURRENT_TIMESTAMP ELSE completed_at END "
                "WHERE id = ? AND version = ?",
                (current_index, status, status, round_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError(
                    f"round {round_id!r} changed before advance"
                )
        return self.get_round(round_id)

    def cancel_round(self, round_id: str) -> ReviewRoundRecord:
        current = self.get_round(round_id)
        if current.status == "cancelled":
            return current
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_rounds SET status = 'cancelled', "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP, "
                "completed_at = CURRENT_TIMESTAMP WHERE id = ? AND version = ?",
                (round_id, current.version),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError(
                    f"round {round_id!r} changed before cancellation"
                )
        return self.get_round(round_id)

    def get_mastery(self, workspace_id: str) -> MasteryProjection:
        row = self._connection.execute(
            "SELECT * FROM review_mastery_projection WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        if row is None:
            return MasteryProjection(
                workspace_id=workspace_id,
                version=0,
                entries=(),
                evidence_refs=(),
            )
        return self._mastery_record(row)

    def save_report_proposal(
        self,
        *,
        draft_id: str,
        round_id: str,
        report_kind: str,
        projection: MasteryProjection | None,
        expected_mastery_version: int | None,
    ) -> ReportProposalRecord:
        if report_kind == "mastery_report" and projection is None:
            raise ValueError("mastery reports require a structured projection")
        payload = None if projection is None else asdict(projection)
        with self._transaction():
            self._connection.execute(
                "INSERT INTO review_report_proposals "
                "(draft_id, round_id, report_kind, proposal_json, "
                "expected_mastery_version) VALUES (?, ?, ?, ?, ?)",
                (
                    draft_id,
                    round_id,
                    report_kind,
                    _canonical_json(payload),
                    expected_mastery_version,
                ),
            )
        return self.get_report_proposal(draft_id)

    def get_report_proposal(self, draft_id: str) -> ReportProposalRecord:
        row = self._connection.execute(
            "SELECT * FROM review_report_proposals WHERE draft_id = ?",
            (draft_id,),
        ).fetchone()
        if row is None:
            raise LookupError(draft_id)
        payload = json.loads(row["proposal_json"])
        return ReportProposalRecord(
            draft_id=row["draft_id"],
            round_id=row["round_id"],
            report_kind=row["report_kind"],
            projection=None if payload is None else self._mastery(payload),
            expected_mastery_version=row["expected_mastery_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def find_report_proposal(
        self, round_id: str, report_kind: str
    ) -> ReportProposalRecord | None:
        row = self._connection.execute(
            "SELECT draft_id FROM review_report_proposals "
            "WHERE round_id = ? AND report_kind = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (round_id, report_kind),
        ).fetchone()
        if row is None:
            return None
        return self.get_report_proposal(row["draft_id"])

    def update_mastery(
        self,
        projection: MasteryProjection,
        *,
        expected_version: int,
    ) -> MasteryProjection:
        if projection.version != expected_version + 1:
            raise ValueError("mastery proposal version must increment by one")
        with self._transaction():
            current = self._connection.execute(
                "SELECT version FROM review_mastery_projection "
                "WHERE workspace_id = ?",
                (projection.workspace_id,),
            ).fetchone()
            current_version = 0 if current is None else int(current["version"])
            if current_version != expected_version:
                raise ReviewConflictError("mastery projection version changed")
            if current is None:
                self._connection.execute(
                    "INSERT INTO review_mastery_projection "
                    "(workspace_id, version, projection_json, "
                    "evidence_refs_json) VALUES (?, ?, ?, ?)",
                    (
                        projection.workspace_id,
                        projection.version,
                        _canonical_json(
                            [asdict(entry) for entry in projection.entries]
                        ),
                        _canonical_json(projection.evidence_refs),
                    ),
                )
            else:
                cursor = self._connection.execute(
                    "UPDATE review_mastery_projection SET version = ?, "
                    "projection_json = ?, evidence_refs_json = ?, "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE workspace_id = ? AND version = ?",
                    (
                        projection.version,
                        _canonical_json(
                            [asdict(entry) for entry in projection.entries]
                        ),
                        _canonical_json(projection.evidence_refs),
                        projection.workspace_id,
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ReviewConflictError(
                        "mastery projection version changed"
                    )
        return self.get_mastery(projection.workspace_id)

    def _require_catalog(self, question_id: str) -> QuestionCatalogRecord:
        row = self._connection.execute(
            "SELECT * FROM review_question_catalog WHERE question_id = ?",
            (question_id,),
        ).fetchone()
        if row is None:
            raise LookupError(question_id)
        return self._catalog_record(row)

    def _require_question_source_link(
        self, link_id: str
    ) -> QuestionSourceLinkRecord:
        row = self._connection.execute(
            "SELECT * FROM review_question_source_links WHERE id = ?",
            (link_id,),
        ).fetchone()
        if row is None:
            raise LookupError(link_id)
        return self._question_source_link_record(row)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    @staticmethod
    def _snapshot(value: str | dict[str, Any]) -> QuestionSnapshot:
        data = json.loads(value) if isinstance(value, str) else value
        return QuestionSnapshot(
            question_id=str(data["question_id"]),
            document_id=str(data["document_id"]),
            content_hash=str(data["content_hash"]),
            title=str(data["title"]),
            question_text=str(data["question_text"]),
            reference_answer=str(data["reference_answer"]),
            topics=tuple(data["topics"]),
            difficulty=cast(Difficulty, data["difficulty"]),
            key_points=tuple(data["key_points"]),
            follow_ups=tuple(data["follow_ups"]),
        )

    @staticmethod
    def _settings(value: str) -> ReviewRoundSettings:
        data = json.loads(value)
        return ReviewRoundSettings(
            topics=tuple(data["topics"]),
            difficulties=tuple(data["difficulties"]),
            mode=cast(ReviewMode, data["mode"]),
            question_count=int(data["question_count"]),
            allow_follow_up=bool(data["allow_follow_up"]),
            seed=int(data["seed"]),
            answer_model_id=str(data["answer_model_id"]),
            reasoning_effort=cast(
                ReasoningEffort, data["reasoning_effort"]
            ),
        )

    @staticmethod
    def _mastery(value: str | dict[str, Any]) -> MasteryProjection:
        data = json.loads(value) if isinstance(value, str) else value
        return MasteryProjection(
            workspace_id=str(data["workspace_id"]),
            version=int(data["version"]),
            entries=tuple(MasteryEntry(**entry) for entry in data["entries"]),
            evidence_refs=tuple(data["evidence_refs"]),
        )

    def _batch_record(self, row: sqlite3.Row) -> QuestionBatchRecord:
        return QuestionBatchRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            source_refs=tuple(json.loads(row["source_refs_json"])),
            rewrite_of_batch_id=row["rewrite_of_batch_id"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _candidate_record(self, row: sqlite3.Row) -> QuestionCandidateRecord:
        return QuestionCandidateRecord(
            id=row["id"],
            batch_id=row["batch_id"],
            draft_id=row["draft_id"],
            question=self._snapshot(row["question_json"]),
            source_refs=tuple(json.loads(row["source_refs_json"])),
            correction_note=row["correction_note"],
            review_note=row["review_note"],
            review_note_updated_at=row["review_note_updated_at"],
            duplicate_of_question_id=row["duplicate_of_question_id"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _curation_session_record(row: sqlite3.Row) -> CurationSessionRecord:
        summary = json.loads(row["summary_json"])
        return CurationSessionRecord(
            session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            source_refs=tuple(json.loads(row["source_refs_json"])),
            active_batch_id=row["active_batch_id"],
            stage=cast(CurationStage, row["stage"]),
            completed_units=row["completed_units"],
            total_units=row["total_units"],
            summary=CurationSummary(items=tuple(summary.get("items", ()))),
            summary_version=row["summary_version"],
            warnings=tuple(json.loads(row["warning_json"])),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _curation_context_record(row: sqlite3.Row) -> CurationContextRecord:
        return CurationContextRecord(
            session_id=row["session_id"],
            version=row["version"],
            focused_candidate_ids=tuple(
                json.loads(row["focused_candidate_ids_json"])
            ),
            last_intent=row["last_intent"],
            last_result_candidate_ids=tuple(
                json.loads(row["last_result_candidate_ids_json"])
            ),
            dialogue_summary=json.loads(row["dialogue_summary_json"]),
            summarized_through_message_id=row[
                "summarized_through_message_id"
            ],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _question_source_link_record(
        row: sqlite3.Row,
    ) -> QuestionSourceLinkRecord:
        return QuestionSourceLinkRecord(
            id=row["id"],
            question_id=row["question_id"],
            source_id=row["source_id"],
            batch_id=row["batch_id"],
            session_id=row["session_id"],
            evidence_ref=row["evidence_ref"],
            merge_reason=row["merge_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _curation_command_receipt(
        row: sqlite3.Row,
    ) -> CurationCommandReceiptRecord:
        return CurationCommandReceiptRecord(
            id=row["id"],
            session_id=row["session_id"],
            idempotency_key=row["idempotency_key"],
            text_hash=row["text_hash"],
            summary_version=row["summary_version"],
            command=json.loads(row["command_json"]),
            result=json.loads(row["result_json"]),
            status=row["status"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    def _catalog_record(self, row: sqlite3.Row) -> QuestionCatalogRecord:
        return QuestionCatalogRecord(
            snapshot=self._snapshot(row["question_json"]),
            workspace_id=row["workspace_id"],
            draft_id=row["draft_id"],
            publication_id=row["publication_id"],
            active=bool(row["active"]),
            published_at=row["published_at"],
        )

    def _round_record(self, row: sqlite3.Row) -> ReviewRoundRecord:
        snapshots = tuple(
            self._snapshot(item)
            for item in json.loads(row["question_snapshots_json"])
        )
        return ReviewRoundRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            execution_id=row["execution_id"],
            settings=self._settings(row["settings_json"]),
            question_snapshots=snapshots,
            mastery_before=self._mastery(row["mastery_before_json"]),
            current_index=row["current_index"],
            status=cast(RoundStatus, row["status"]),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _input_request_record(
        row: sqlite3.Row,
    ) -> ReviewInputRequestRecord:
        return ReviewInputRequestRecord(
            id=row["id"],
            round_id=row["round_id"],
            ordinal=row["ordinal"],
            kind=cast(InputKind, row["kind"]),
            prompt=row["prompt"],
            version=row["version"],
            status=row["status"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )

    @staticmethod
    def _input_receipt(row: sqlite3.Row) -> ReviewInputReceipt:
        return ReviewInputReceipt(
            id=row["id"],
            input_request_id=row["input_request_id"],
            idempotency_key=row["idempotency_key"],
            value_hash=row["value_hash"],
            receipt=json.loads(row["receipt_json"]),
            created_at=row["created_at"],
        )

    def _attempt_record(self, row: sqlite3.Row) -> ReviewAttemptRecord:
        evaluation = (
            None
            if row["evaluation_json"] is None
            else json.loads(row["evaluation_json"])
        )
        return ReviewAttemptRecord(
            id=row["id"],
            round_id=row["round_id"],
            ordinal=row["ordinal"],
            question_snapshot=self._snapshot(row["question_snapshot_json"]),
            answer=row["answer"],
            follow_up_answer=row["follow_up_answer"],
            evaluation=evaluation,
            mastery_suggestion=row["mastery_suggestion"],
            skipped=bool(row["skipped"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            status=cast(AttemptStatus, row["status"]),
            evaluation_error_code=row["evaluation_error_code"],
            evaluation_started_at=row["evaluation_started_at"],
            evaluation_completed_at=row["evaluation_completed_at"],
        )

    @staticmethod
    def _answer_receipt(row: sqlite3.Row) -> ReviewAnswerReceipt:
        payload = json.loads(row["receipt_json"])
        return ReviewAnswerReceipt(
            id=row["id"],
            round_id=str(payload["roundId"]),
            attempt_id=str(payload["attemptId"]),
            input_request_id=row["input_request_id"],
            message_id=str(payload["messageId"]),
            status=cast(AttemptStatus, payload["status"]),
            version=int(payload["version"]),
            accepted_at=row["created_at"],
        )

    @staticmethod
    def _retry_answer_receipt(row: sqlite3.Row) -> ReviewAnswerReceipt:
        payload = json.loads(row["receipt_json"])
        return ReviewAnswerReceipt(
            id=row["id"],
            round_id=str(payload["roundId"]),
            attempt_id=str(payload["attemptId"]),
            input_request_id=row["input_request_id"],
            message_id="",
            status=cast(AttemptStatus, payload["status"]),
            version=int(payload["version"]),
            accepted_at=row["created_at"],
        )

    @staticmethod
    def _mastery_record(row: sqlite3.Row) -> MasteryProjection:
        return MasteryProjection(
            workspace_id=row["workspace_id"],
            version=row["version"],
            entries=tuple(
                MasteryEntry(**entry)
                for entry in json.loads(row["projection_json"])
            ),
            evidence_refs=tuple(json.loads(row["evidence_refs_json"])),
        )
