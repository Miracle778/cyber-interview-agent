from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Iterator, Literal, cast
from uuid import uuid4

from app.review.errors import (
    InputAlreadyResolvedError,
    ReviewConflictError,
    ReviewRoundNotFoundError,
)
from app.review.models import (
    AttemptStatus,
    BulkPublicationItemRecord,
    BulkPublicationRecord,
    CurationAttemptReason,
    CurationBatchAttemptRecord,
    CurationBatchStatus,
    CurationBatchTiming,
    CurationContextRecord,
    CurationControlIntent,
    CurationControlOperation,
    CurationControlReceiptRecord,
    CurationProcessorKind,
    CurationWorkItemRecord,
    CurationWorkStage,
    CurationWorkStatus,
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

    def save_curation_preference(
        self,
        session_id: str,
        *,
        provider_model_id: str,
        reasoning_effort: ReasoningEffort,
    ) -> CurationSessionRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_curation_sessions "
                "SET preferred_model_id = ?, preferred_reasoning_effort = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (provider_model_id, reasoning_effort, session_id),
            )
            if cursor.rowcount != 1:
                raise LookupError(session_id)
        return self.get_curation_session(session_id)

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
            # The logical identity is question + source + evidence.  A later
            # curation session may rediscover the same evidence; its candidate
            # retains that run's audit trail, while the question-source edge is
            # intentionally idempotent.
            return self._question_source_link_record(existing)
        identifier = link_id or str(uuid4())
        with self._transaction():
            self._connection.execute(
                "INSERT INTO review_question_source_links "
                "(id, question_id, source_id, batch_id, session_id, origin_session_id, "
                "evidence_ref, merge_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    question_id,
                    source_id,
                    batch_id,
                    session_id,
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
                "(id, session_id, idempotency_key, text_hash, original_text, "
                "summary_version, command_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    session_id,
                    idempotency_key,
                    text_hash,
                    text,
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

    def latest_curation_command_receipt(
        self, session_id: str
    ) -> CurationCommandReceiptRecord | None:
        row = self._connection.execute(
            "SELECT * FROM review_curation_command_receipts "
            "WHERE session_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return None if row is None else self._curation_command_receipt(row)

    def attach_curation_command_execution(
        self, receipt_id: str, execution_id: str
    ) -> CurationCommandReceiptRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_curation_command_receipts SET execution_id = ? "
                "WHERE id = ? AND execution_id IS NULL",
                (execution_id, receipt_id),
            )
            if cursor.rowcount != 1:
                current = self.get_curation_command_receipt(receipt_id)
                if current.execution_id != execution_id:
                    raise ReviewConflictError(
                        "curation command already has an execution"
                    )
        return self.get_curation_command_receipt(receipt_id)

    def requeue_curation_command(
        self, receipt_id: str, execution_id: str
    ) -> CurationCommandReceiptRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_curation_command_receipts "
                "SET execution_id = ?, lifecycle_status = 'accepted', "
                "retry_count = retry_count + 1, completed_at = NULL "
                "WHERE id = ? AND lifecycle_status IN ('interrupted', 'failed')",
                (execution_id, receipt_id),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError(
                    "curation command cannot be retried"
                )
        return self.get_curation_command_receipt(receipt_id)

    def replace_curation_command_plan(
        self, receipt_id: str, command: dict[str, object]
    ) -> CurationCommandReceiptRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_curation_command_receipts SET command_json = ? "
                "WHERE id = ? AND lifecycle_status IN ('accepted', 'running')",
                (_canonical_json(command), receipt_id),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError(
                    "curation command plan can no longer change"
                )
        return self.get_curation_command_receipt(receipt_id)

    def transition_curation_command_lifecycle(
        self,
        receipt_id: str,
        *,
        expected: tuple[str, ...],
        target: str,
    ) -> CurationCommandReceiptRecord:
        supported = {
            "accepted",
            "running",
            "completed",
            "partial_failure",
            "failed",
            "cancelled",
            "interrupted",
        }
        if target not in supported:
            raise ValueError("unsupported curation command lifecycle status")
        placeholders = ",".join("?" for _item in expected)
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_curation_command_receipts "
                "SET lifecycle_status = ? WHERE id = ? "
                f"AND lifecycle_status IN ({placeholders})",
                (target, receipt_id, *expected),
            )
            if cursor.rowcount != 1:
                current = self.get_curation_command_receipt(receipt_id)
                if current.lifecycle_status != target:
                    raise ReviewConflictError(
                        "curation command lifecycle changed"
                    )
        return self.get_curation_command_receipt(receipt_id)

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
                "status = ?, lifecycle_status = ?, "
                "completed_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'processing'",
                (_canonical_json(result), status, status, receipt_id),
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
                "(id, workspace_id, session_id, origin_session_id, run_id, source_refs_json, "
                "rewrite_of_batch_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    workspace_id,
                    session_id,
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

    def update_batch_status(
        self,
        batch_id: str,
        status: Literal["completed", "failed"],
        *,
        expected_run_id: str | None = None,
    ) -> QuestionBatchRecord:
        if status not in {"completed", "failed"}:
            raise ValueError("unsupported question batch terminal status")
        with self._transaction():
            row = self._connection.execute(
                "SELECT * FROM review_question_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
            if row is None:
                raise LookupError(batch_id)
            current = self._batch_record(row)
            if (
                expected_run_id is not None
                and current.run_id != expected_run_id
            ):
                raise ReviewConflictError("question batch current run changed")
            if (
                current.status != "generating"
                or current.control_intent is not None
            ):
                return current
            cursor = self._connection.execute(
                "UPDATE review_question_batches SET status = ?, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'generating' AND version = ? "
                "AND control_intent IS NULL "
                "AND (? IS NULL OR run_id = ?)",
                (
                    status,
                    batch_id,
                    current.version,
                    expected_run_id,
                    expected_run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("question batch terminal state changed")
        return self.get_batch(batch_id)

    def claim_curation_finalization(
        self, batch_id: str, execution_id: str
    ) -> tuple[str, str, int, str, tuple[str, ...]]:
        """Durably bind candidate preparation to the current batch owner."""
        with self._transaction():
            existing = self._connection.execute(
                "SELECT * FROM review_curation_finalizations WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if (
                existing is not None
                and existing["execution_id"] == execution_id
            ):
                return (
                    batch_id,
                    execution_id,
                    int(existing["batch_version"]),
                    str(existing["state"]),
                    tuple(json.loads(existing["candidate_ids_json"])),
                )

            row = self._connection.execute(
                "SELECT * FROM review_question_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
            if row is None:
                raise LookupError(batch_id)
            batch = self._batch_record(row)
            if (
                batch.run_id != execution_id
                or batch.status != "generating"
                or batch.control_intent is not None
            ):
                raise ReviewConflictError(
                    "question batch cannot be finalized by this execution"
                )
            if existing is None:
                self._connection.execute(
                    "INSERT INTO review_curation_finalizations "
                    "(batch_id, execution_id, batch_version) VALUES (?, ?, ?)",
                    (batch_id, execution_id, batch.version),
                )
            else:
                self._connection.execute(
                    "UPDATE review_curation_finalizations SET execution_id = ?, "
                    "batch_version = ?, state = 'preparing', "
                    "candidate_ids_json = '[]', updated_at = CURRENT_TIMESTAMP "
                    "WHERE batch_id = ?",
                    (execution_id, batch.version, batch_id),
                )
            return (batch_id, execution_id, batch.version, "preparing", ())

    def finalize_curation_candidates(
        self,
        batch_id: str,
        execution_id: str,
        *,
        candidates: tuple[dict[str, object], ...],
    ) -> tuple[QuestionCandidateRecord, ...]:
        """Publish staged curation output and complete its batch atomically."""
        candidate_ids = tuple(str(item["candidate_id"]) for item in candidates)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("curation candidate ids must be unique")
        with self._transaction():
            claim = self._connection.execute(
                "SELECT * FROM review_curation_finalizations WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if claim is None or claim["execution_id"] != execution_id:
                raise ReviewConflictError("curation finalization owner changed")
            if claim["state"] == "committed":
                committed_ids = tuple(json.loads(claim["candidate_ids_json"]))
                if committed_ids != candidate_ids:
                    raise ReviewConflictError(
                        "committed curation candidate set changed"
                    )
                return tuple(self.get_candidate(value) for value in committed_ids)

            batch_row = self._connection.execute(
                "SELECT * FROM review_question_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
            if batch_row is None:
                raise LookupError(batch_id)
            batch = self._batch_record(batch_row)
            if (
                batch.run_id != execution_id
                or batch.status != "generating"
                or batch.control_intent is not None
                or batch.version != int(claim["batch_version"])
            ):
                raise ReviewConflictError("question batch finalization state changed")

            for item in candidates:
                draft_id = str(item["draft_id"])
                question = item["question"]
                if not isinstance(question, QuestionSnapshot):
                    raise TypeError("curation question must be a QuestionSnapshot")
                draft = cast(dict[str, object], item["draft"])
                if self._connection.execute(
                    "SELECT 1 FROM knowledge_drafts WHERE id = ?",
                    (draft_id,),
                ).fetchone() is not None:
                    raise ReviewConflictError(
                        "curation draft became formal before finalization"
                    )
                if (
                    draft["workspace_id"] != batch.workspace_id
                    or draft["session_id"] != batch.session_id
                    or draft["run_id"] != execution_id
                    or draft["domain"] != "review"
                    or draft["document_type"] != "question"
                    or draft["document_id"] != question.document_id
                    or draft["content_hash"] != question.content_hash
                    or str(draft["content_path"])
                    != f"artifacts/review/drafts/{draft_id}.md"
                ):
                    raise ReviewConflictError(
                        "staged curation draft changed before finalization"
                    )

            for item in candidates:
                candidate_id = str(item["candidate_id"])
                draft_id = str(item["draft_id"])
                draft = cast(dict[str, object], item["draft"])
                question = cast(QuestionSnapshot, item["question"])
                source_refs = tuple(str(value) for value in item["source_refs"])
                self._connection.execute(
                    "INSERT INTO knowledge_drafts "
                    "(id, workspace_id, session_id, run_id, agent_type, domain, "
                    "document_type, document_id, title, content_path, "
                    "source_refs_json, relation_refs_json, status, version, "
                    "content_hash) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "'review_pending', ?, ?)",
                    (
                        draft_id,
                        draft["workspace_id"],
                        draft["session_id"],
                        draft["run_id"],
                        draft.get("agent_type"),
                        draft["domain"],
                        draft["document_type"],
                        draft["document_id"],
                        draft["title"],
                        draft["content_path"],
                        _canonical_json(tuple(draft["source_refs"])),
                        _canonical_json(tuple(draft["relation_refs"])),
                        int(draft.get("version", 1)),
                        draft["content_hash"],
                    ),
                )
                revision_candidate_id = item.get("revision_candidate_id")
                if revision_candidate_id is None:
                    self._connection.execute(
                        "INSERT INTO review_question_candidates "
                        "(id, batch_id, draft_id, question_json, source_refs_json, "
                        "correction_note, duplicate_of_question_id, status) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 'review_pending')",
                        (
                            candidate_id,
                            batch_id,
                            draft_id,
                            _canonical_json(asdict(question)),
                            _canonical_json(source_refs),
                            str(item.get("correction_note", "")),
                            item.get("duplicate_of_question_id"),
                        ),
                    )
                else:
                    if str(revision_candidate_id) != candidate_id:
                        raise ValueError(
                            "revision finalization must retain its candidate id"
                        )
                    cursor = self._connection.execute(
                        "UPDATE review_question_candidates SET draft_id = ?, "
                        "question_json = ?, source_refs_json = ?, "
                        "status = 'review_pending', updated_at = CURRENT_TIMESTAMP "
                        "WHERE id = ? AND (batch_id = ? OR batch_id = ?)",
                        (
                            draft_id,
                            _canonical_json(asdict(question)),
                            _canonical_json(source_refs),
                            candidate_id,
                            batch_id,
                            batch.rewrite_of_batch_id,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise LookupError(candidate_id)
                for link in cast(tuple[dict[str, object], ...], item["source_links"]):
                    self._connection.execute(
                        "INSERT OR IGNORE INTO review_question_source_links "
                        "(id, question_id, source_id, batch_id, session_id, "
                        "origin_session_id, evidence_ref, merge_reason) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(link["link_id"]),
                            str(link["question_id"]),
                            str(link["source_id"]),
                            batch_id,
                            batch.session_id,
                            batch.origin_session_id,
                            str(link["evidence_ref"]),
                            str(link["merge_reason"]),
                        ),
                    )
            if batch.session_id is not None:
                summary = CurationSummary(
                    items=tuple(
                        {
                            "ordinal": index,
                            "candidateId": str(item["candidate_id"]),
                            "title": cast(QuestionSnapshot, item["question"]).title,
                            "topics": cast(QuestionSnapshot, item["question"]).topics,
                            "difficulty": cast(
                                QuestionSnapshot, item["question"]
                            ).difficulty,
                            "sourceCount": len(tuple(item["source_refs"])),
                            "recommendation": (
                                "link_existing"
                                if item.get("duplicate_of_question_id")
                                else "recommend_confirm"
                            ),
                            "reason": (
                                "与已发布题目相同，建议确认来源关联"
                                if item.get("duplicate_of_question_id")
                                else "结构完整且来源明确"
                            ),
                        }
                        for index, item in enumerate(candidates, start=1)
                    )
                )
                cursor = self._connection.execute(
                    "UPDATE review_curation_sessions SET "
                    "stage = 'waiting_for_command', completed_units = 1, "
                    "total_units = 1, summary_json = ?, "
                    "summary_version = summary_version + 1, "
                    "updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                    (
                        _canonical_json({"items": summary.items}),
                        batch.session_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise LookupError(batch.session_id)
            cursor = self._connection.execute(
                "UPDATE review_question_batches SET status = 'completed', "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND run_id = ? AND status = 'generating' "
                "AND version = ? AND control_intent IS NULL",
                (batch_id, execution_id, batch.version),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("question batch finalization state changed")
            self._connection.execute(
                "UPDATE review_curation_finalizations SET state = 'committed', "
                "candidate_ids_json = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE batch_id = ? AND execution_id = ? AND state = 'preparing'",
                (_canonical_json(candidate_ids), batch_id, execution_id),
            )
        return tuple(self.get_candidate(value) for value in candidate_ids)

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

    def curation_batch_input(self, batch_id: str) -> dict[str, Any]:
        batch = self.get_batch(batch_id)
        if batch.run_id is None:
            raise ReviewConflictError("question batch has no bound execution input")
        _execution, input_value, _normalized = (
            self._require_curation_execution_ownership(batch, batch.run_id)
        )
        return input_value

    def reattach_batch_run(
        self, batch_id: str, run_id: str
    ) -> QuestionBatchRecord:
        batch = self.get_batch(batch_id)
        if batch.status != "failed" or batch.control_intent is not None:
            raise ReviewConflictError("question batch cannot be retried")
        return self.resume_curation_batch(
            batch_id,
            execution_id=run_id,
            idempotency_key=f"legacy-retry:{run_id}",
            expected_version=batch.version,
            reason="failed",
        )

    def request_batch_control(
        self,
        batch_id: str,
        *,
        operation: Literal["pause", "terminate"],
        idempotency_key: str,
        expected_version: int,
    ) -> CurationControlReceiptRecord:
        if operation not in {"pause", "terminate"}:
            raise ValueError("unsupported curation control operation")
        self._validate_control_request(idempotency_key, expected_version)
        digest = self._control_request_digest(
            {
                "operation": operation,
                "expectedVersion": expected_version,
            }
        )
        with self._transaction():
            existing = self._connection.execute(
                "SELECT * FROM review_curation_control_receipts "
                "WHERE batch_id = ? AND idempotency_key = ?",
                (batch_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                receipt = self._curation_control_receipt_record(existing)
                if receipt.request_digest != digest:
                    raise ReviewConflictError("control request changed")
                return receipt

            row = self._connection.execute(
                "SELECT status, version, control_intent "
                "FROM review_question_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
            if row is None:
                raise LookupError(batch_id)
            if row["version"] != expected_version:
                raise ReviewConflictError("question batch version changed")
            allowed = (
                {"generating"}
                if operation == "pause"
                else {"generating", "paused", "interrupted", "failed"}
            )
            if row["status"] not in allowed or row["control_intent"] is not None:
                raise ReviewConflictError("question batch cannot be controlled")

            receipt_id = str(uuid4())
            cursor = self._connection.execute(
                "UPDATE review_question_batches SET control_intent = ?, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND version = ? AND status = ? "
                "AND control_intent IS NULL",
                (operation, batch_id, expected_version, row["status"]),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("question batch version changed")
            self._connection.execute(
                "INSERT INTO review_curation_control_receipts "
                "(id, batch_id, idempotency_key, operation, request_digest, "
                "result_status) VALUES (?, ?, ?, ?, ?, 'requested')",
                (receipt_id, batch_id, idempotency_key, operation, digest),
            )
            created = self._connection.execute(
                "SELECT * FROM review_curation_control_receipts WHERE id = ?",
                (receipt_id,),
            ).fetchone()
            assert created is not None
            return self._curation_control_receipt_record(created)

    def finalize_batch_control(self, receipt_id: str) -> QuestionBatchRecord:
        with self._transaction():
            receipt_row = self._connection.execute(
                "SELECT * FROM review_curation_control_receipts WHERE id = ?",
                (receipt_id,),
            ).fetchone()
            if receipt_row is None:
                raise LookupError(receipt_id)
            receipt = self._curation_control_receipt_record(receipt_row)
            if receipt.operation not in {"pause", "terminate"}:
                raise ReviewConflictError("control receipt cannot be finalized")
            target = "paused" if receipt.operation == "pause" else "terminated"
            batch_row = self._connection.execute(
                "SELECT * FROM review_question_batches WHERE id = ?",
                (receipt.batch_id,),
            ).fetchone()
            if batch_row is None:
                raise LookupError(receipt.batch_id)
            batch = self._batch_record(batch_row)
            if (
                receipt.result_status == target
                and batch.status == target
                and batch.control_intent is None
            ):
                return batch
            allowed = (
                {"generating"}
                if receipt.operation == "pause"
                else {"generating", "paused", "interrupted", "failed"}
            )
            if batch.status not in allowed or batch.control_intent != receipt.operation:
                raise ReviewConflictError("question batch control state changed")
            cursor = self._connection.execute(
                "UPDATE review_question_batches SET status = ?, control_intent = NULL, "
                "version = version + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND version = ? AND status = ? AND control_intent = ?",
                (target, batch.id, batch.version, batch.status, receipt.operation),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("question batch control state changed")
            self._connection.execute(
                "UPDATE review_curation_control_receipts SET result_status = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? "
                "AND result_status = 'requested'",
                (target, receipt.id),
            )
            self._connection.execute(
                "UPDATE review_curation_sessions SET stage = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE active_batch_id = ?",
                (target, batch.id),
            )
        return self.get_batch(receipt.batch_id)

    def resume_curation_batch(
        self,
        batch_id: str,
        *,
        execution_id: str,
        idempotency_key: str,
        expected_version: int,
        reason: Literal["paused", "failed", "interrupted"],
    ) -> QuestionBatchRecord:
        if reason not in {"paused", "failed", "interrupted"}:
            raise ValueError("unsupported curation resume reason")
        self._validate_control_request(idempotency_key, expected_version)
        if not execution_id.strip():
            raise ValueError("execution id must not be empty")
        digest = self._control_request_digest(
            {
                "operation": "resume",
                "executionId": execution_id,
                "expectedVersion": expected_version,
                "reason": reason,
            }
        )
        with self._transaction():
            existing = self._connection.execute(
                "SELECT * FROM review_curation_control_receipts "
                "WHERE batch_id = ? AND idempotency_key = ?",
                (batch_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                receipt = self._curation_control_receipt_record(existing)
                if receipt.request_digest != digest:
                    raise ReviewConflictError("control request changed")
                return self.get_batch(batch_id)
            row = self._connection.execute(
                "SELECT * FROM review_question_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
            if row is None:
                raise LookupError(batch_id)
            batch = self._batch_record(row)
            if batch.version != expected_version:
                raise ReviewConflictError("question batch version changed")
            if batch.status != reason or batch.control_intent is not None:
                raise ReviewConflictError("question batch cannot be resumed")
            if batch.run_id is None or batch.run_id == execution_id:
                raise ReviewConflictError(
                    "question batch has no prior execution input to resume"
                )
            _bound_execution, _bound_input, bound_normalized = (
                self._require_curation_execution_ownership(
                    batch, batch.run_id
                )
            )
            execution, _execution_input, execution_normalized = (
                self._require_curation_execution_ownership(
                    batch, execution_id
                )
            )
            if execution["status"] not in {"queued", "running"}:
                raise ReviewConflictError("execution cannot resume curation")
            if _canonical_json(execution_normalized) != _canonical_json(
                bound_normalized
            ):
                raise ReviewConflictError(
                    "curation execution immutable input changed"
                )
            active = self._connection.execute(
                "SELECT 1 FROM review_curation_batch_attempts attempt "
                "JOIN agent_runs run ON run.id = attempt.execution_id "
                "WHERE attempt.batch_id = ? AND run.status IN "
                "('queued', 'running', 'waiting_for_input', 'waiting_for_approval') "
                "LIMIT 1",
                (batch_id,),
            ).fetchone()
            if active is not None:
                raise ReviewConflictError(
                    "question batch already has an active curation attempt"
                )
            cursor = self._connection.execute(
                "UPDATE review_question_batches SET run_id = ?, status = 'generating', "
                "control_intent = NULL, version = version + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND version = ? "
                "AND status = ? AND control_intent IS NULL",
                (execution_id, batch_id, expected_version, reason),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("question batch cannot be resumed")
            self._connection.execute(
                "UPDATE review_curation_work_items SET status = 'interrupted', "
                "last_error_code = 'curation_interrupted', "
                "updated_at = CURRENT_TIMESTAMP WHERE batch_id = ? "
                "AND status = 'running'",
                (batch_id,),
            )
            self._connection.execute(
                "INSERT INTO review_curation_control_receipts "
                "(id, batch_id, idempotency_key, operation, request_digest, "
                "execution_id, result_status) VALUES (?, ?, ?, 'resume', ?, ?, 'generating')",
                (str(uuid4()), batch_id, idempotency_key, digest, execution_id),
            )
            self._insert_curation_attempt(
                batch_id=batch_id,
                execution_id=execution_id,
                reason=reason,
            )
            self._connection.execute(
                "UPDATE review_curation_sessions SET stage = 'generating', "
                "updated_at = CURRENT_TIMESTAMP WHERE active_batch_id = ?",
                (batch_id,),
            )
        return self.get_batch(batch_id)

    def record_curation_attempt(
        self,
        batch_id: str,
        execution_id: str,
        *,
        reason: CurationAttemptReason,
    ) -> CurationBatchAttemptRecord:
        if reason not in {"initial", "paused", "failed", "interrupted"}:
            raise ValueError("unsupported curation attempt reason")
        with self._transaction():
            existing = self._connection.execute(
                "SELECT * FROM review_curation_batch_attempts WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if existing is not None:
                attempt = self._curation_batch_attempt_record(existing)
                if attempt.batch_id != batch_id or attempt.reason != reason:
                    raise ReviewConflictError("curation attempt changed")
                return attempt
            batch_row = self._connection.execute(
                "SELECT * FROM review_question_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if batch_row is None:
                raise LookupError(batch_id)
            batch = self._batch_record(batch_row)
            self._require_curation_execution_ownership(batch, execution_id)
            bound = batch.run_id == execution_id
            resumed = self._connection.execute(
                "SELECT 1 FROM review_curation_control_receipts "
                "WHERE batch_id = ? AND execution_id = ? "
                "AND operation = 'resume' AND result_status = 'generating'",
                (batch_id, execution_id),
            ).fetchone()
            if not bound and resumed is None:
                raise ReviewConflictError(
                    "curation execution is not bound to question batch"
                )
            active = self._connection.execute(
                "SELECT 1 FROM review_curation_batch_attempts attempt "
                "JOIN agent_runs run ON run.id = attempt.execution_id "
                "WHERE attempt.batch_id = ? AND run.status IN "
                "('queued', 'running', 'waiting_for_input', 'waiting_for_approval') "
                "LIMIT 1",
                (batch_id,),
            ).fetchone()
            if active is not None:
                raise ReviewConflictError(
                    "question batch already has an active curation attempt"
                )
            return self._insert_curation_attempt(
                batch_id=batch_id,
                execution_id=execution_id,
                reason=reason,
            )

    def curation_batch_timing(self, batch_id: str) -> CurationBatchTiming:
        if self._connection.execute(
            "SELECT 1 FROM review_question_batches WHERE id = ?", (batch_id,)
        ).fetchone() is None:
            raise LookupError(batch_id)
        rows = self._connection.execute(
            "SELECT run.started_at, run.finished_at "
            "FROM review_curation_batch_attempts attempt "
            "JOIN agent_runs run ON run.id = attempt.execution_id "
            "WHERE attempt.batch_id = ? ORDER BY attempt.ordinal, attempt.id",
            (batch_id,),
        ).fetchall()
        now = datetime.now(timezone.utc)
        durations: list[int] = []
        for row in rows:
            if row["started_at"] is None:
                durations.append(0)
                continue
            started_at = self._utc_datetime(row["started_at"])
            finished_at = (
                now
                if row["finished_at"] is None
                else self._utc_datetime(row["finished_at"])
            )
            durations.append(
                max(0, int((finished_at - started_at).total_seconds() * 1000))
            )
        return CurationBatchTiming(
            current_elapsed_ms=durations[-1] if durations else 0,
            cumulative_elapsed_ms=sum(durations),
        )

    def append_curation_warning(
        self, session_id: str, warning: dict[str, object]
    ) -> CurationSessionRecord:
        canonical = cast(dict[str, object], json.loads(_canonical_json(warning)))
        with self._transaction():
            row = self._connection.execute(
                "SELECT warning_json FROM review_curation_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise LookupError(session_id)
            warnings = list(json.loads(row["warning_json"]))
            if canonical in warnings:
                return self.get_curation_session(session_id)
            warnings.append(canonical)
            self._connection.execute(
                "UPDATE review_curation_sessions SET warning_json = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (_canonical_json(warnings), session_id),
            )
        return self.get_curation_session(session_id)

    def plan_curation_work_item(
        self,
        *,
        batch_id: str,
        stage: CurationWorkStage,
        unit_index: int,
        input_digest: str,
        source_refs: tuple[str, ...],
        processor_kind: CurationProcessorKind = "model",
        work_item_id: str | None = None,
    ) -> CurationWorkItemRecord:
        self._validate_work_item_plan(
            stage, unit_index, input_digest, source_refs, processor_kind
        )
        with self._transaction():
            existing = self._connection.execute(
                "SELECT * FROM review_curation_work_items "
                "WHERE batch_id = ? AND stage = ? AND unit_index = ?",
                (batch_id, stage, unit_index),
            ).fetchone()
            if existing is not None:
                record = self._curation_work_item_record(existing)
                if (
                    record.input_digest != input_digest
                    or record.source_refs != source_refs
                    or record.processor_kind != processor_kind
                ):
                    raise ReviewConflictError("curation work item input changed")
                return record
            try:
                self._connection.execute(
                    "INSERT INTO review_curation_work_items "
                    "(id, batch_id, stage, unit_index, input_digest, source_refs_json, "
                    "processor_kind) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        work_item_id or str(uuid4()),
                        batch_id,
                        stage,
                        unit_index,
                        input_digest,
                        _canonical_json(source_refs),
                        processor_kind,
                    ),
                )
            except sqlite3.IntegrityError as error:
                if "FOREIGN KEY" in str(error).upper():
                    raise LookupError(batch_id) from error
                raise
        return self._get_curation_work_item_by_identity(
            batch_id, stage, unit_index
        )

    def list_curation_work_items(
        self, batch_id: str, *, stage: CurationWorkStage | None = None
    ) -> tuple[CurationWorkItemRecord, ...]:
        clauses = ["batch_id = ?"]
        values: list[object] = [batch_id]
        if stage is not None:
            if stage not in {"discovery", "enrichment"}:
                raise ValueError("unsupported curation work item stage")
            clauses.append("stage = ?")
            values.append(stage)
        rows = self._connection.execute(
            "SELECT * FROM review_curation_work_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY stage, unit_index, rowid",
            tuple(values),
        ).fetchall()
        return tuple(self._curation_work_item_record(row) for row in rows)

    def start_curation_work_item(self, work_item_id: str) -> CurationWorkItemRecord:
        with self._transaction():
            row = self._connection.execute(
                "SELECT * FROM review_curation_work_items WHERE id = ?",
                (work_item_id,),
            ).fetchone()
            if row is None:
                raise LookupError(work_item_id)
            record = self._curation_work_item_record(row)
            if record.status == "completed":
                return record
            cursor = self._connection.execute(
                "UPDATE review_curation_work_items SET status = 'running', "
                "attempt_count = attempt_count + 1, last_error_code = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? "
                "AND status IN ('pending', 'failed', 'interrupted')",
                (work_item_id,),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("curation work item cannot be started")
        return self.get_curation_work_item(work_item_id)

    def complete_curation_work_item(
        self, work_item_id: str, *, output: dict[str, object]
    ) -> CurationWorkItemRecord:
        with self._transaction():
            row = self._connection.execute(
                "SELECT * FROM review_curation_work_items WHERE id = ?",
                (work_item_id,),
            ).fetchone()
            if row is None:
                raise LookupError(work_item_id)
            record = self._curation_work_item_record(row)
            validated = self._validate_curation_work_item_output(record.stage, output)
            if record.status == "completed":
                if record.output == validated:
                    return record
                raise ReviewConflictError("curation work item output changed")
            if record.status != "running":
                raise ReviewConflictError("curation work item is not running")
            cursor = self._connection.execute(
                "UPDATE review_curation_work_items SET status = 'completed', "
                "output_json = ?, last_error_code = NULL, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'running'",
                (_canonical_json(validated), work_item_id),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("curation work item is not running")
        return self.get_curation_work_item(work_item_id)

    def fail_curation_work_item(
        self, work_item_id: str, *, error_code: str
    ) -> CurationWorkItemRecord:
        self._validate_curation_error_code(error_code)
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_curation_work_items SET status = 'failed', "
                "last_error_code = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'running'",
                (error_code, work_item_id),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("curation work item is not running")
        return self.get_curation_work_item(work_item_id)

    def requeue_running_curation_work_items(self, batch_id: str) -> int:
        with self._transaction():
            return self._connection.execute(
                "UPDATE review_curation_work_items SET status = 'failed', "
                "last_error_code = 'curation_interrupted', updated_at = CURRENT_TIMESTAMP "
                "WHERE batch_id = ? AND status = 'running'",
                (batch_id,),
            ).rowcount

    def interrupt_running_curation_work_items(
        self, batch_id: str, *, error_code: str
    ) -> int:
        self._validate_curation_error_code(error_code)
        with self._transaction():
            return self._connection.execute(
                "UPDATE review_curation_work_items SET status = 'interrupted', "
                "last_error_code = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE batch_id = ? AND status = 'running'",
                (error_code, batch_id),
            ).rowcount

    def get_curation_work_item(self, work_item_id: str) -> CurationWorkItemRecord:
        row = self._connection.execute(
            "SELECT * FROM review_curation_work_items WHERE id = ?",
            (work_item_id,),
        ).fetchone()
        if row is None:
            raise LookupError(work_item_id)
        return self._curation_work_item_record(row)

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
            self._connection.execute(
                "UPDATE review_curation_command_receipts SET lifecycle_status = "
                "CASE (SELECT status FROM agent_runs WHERE id = execution_id) "
                "WHEN 'cancelled' THEN 'cancelled' "
                "WHEN 'failed' THEN 'failed' ELSE 'interrupted' END "
                "WHERE lifecycle_status IN ('accepted', 'running') "
                "AND execution_id IN (SELECT id FROM agent_runs WHERE status IN "
                "('interrupted', 'failed', 'cancelled', 'completed'))"
            )
            self._connection.execute(
                "UPDATE review_bulk_publications SET status = "
                "CASE (SELECT status FROM agent_runs WHERE id = execution_id) "
                "WHEN 'cancelled' THEN 'cancelled' "
                "WHEN 'failed' THEN 'failed' ELSE 'interrupted' END "
                "WHERE status IN ('accepted', 'running') "
                "AND execution_id IN (SELECT id FROM agent_runs WHERE status IN "
                "('interrupted', 'failed', 'cancelled', 'completed'))"
            )
        return batches, rounds

    def create_bulk_publication(
        self,
        *,
        session_id: str,
        summary_version: int,
        idempotency_key: str,
        candidate_ids: tuple[str, ...],
        operation_id: str | None = None,
    ) -> tuple[BulkPublicationRecord, bool]:
        existing = self._connection.execute(
            "SELECT * FROM review_bulk_publications "
            "WHERE session_id = ? AND idempotency_key = ?",
            (session_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            operation = self._bulk_publication(existing)
            stored = tuple(
                item.candidate_id
                for item in self.list_bulk_publication_items(operation.id)
            )
            if (
                operation.summary_version != summary_version
                or stored != candidate_ids
            ):
                raise ReviewConflictError(
                    "bulk publication idempotency key changed"
                )
            return operation, False
        identifier = operation_id or str(uuid4())
        with self._transaction():
            self._connection.execute(
                "INSERT INTO review_bulk_publications "
                "(id, session_id, summary_version, idempotency_key) "
                "VALUES (?, ?, ?, ?)",
                (identifier, session_id, summary_version, idempotency_key),
            )
            for candidate_id in candidate_ids:
                self._connection.execute(
                    "INSERT INTO review_bulk_publication_items "
                    "(id, operation_id, candidate_id, idempotency_key) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        identifier,
                        candidate_id,
                        f"bulk-publish:{identifier}:{candidate_id}",
                    ),
                )
        return self.get_bulk_publication(identifier), True

    def get_bulk_publication(
        self, operation_id: str
    ) -> BulkPublicationRecord:
        row = self._connection.execute(
            "SELECT * FROM review_bulk_publications WHERE id = ?",
            (operation_id,),
        ).fetchone()
        if row is None:
            raise LookupError(operation_id)
        return self._bulk_publication(row)

    def reconcile_bulk_publication(
        self, operation_id: str
    ) -> BulkPublicationRecord:
        operation = self.get_bulk_publication(operation_id)
        if operation.status not in {"accepted", "running"}:
            return operation
        if operation.execution_id is None:
            return operation
        execution = self._connection.execute(
            "SELECT status FROM agent_runs WHERE id = ?",
            (operation.execution_id,),
        ).fetchone()
        if execution is None or execution["status"] in {
            "running",
            "waiting_for_input",
            "waiting_for_approval",
        }:
            return operation
        target = (
            "cancelled"
            if execution["status"] == "cancelled"
            else "failed"
            if execution["status"] == "failed"
            else "interrupted"
        )
        return self.transition_bulk_publication(
            operation.id,
            expected=("accepted", "running"),
            target=target,
        )

    def list_bulk_publication_items(
        self, operation_id: str
    ) -> tuple[BulkPublicationItemRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM review_bulk_publication_items "
            "WHERE operation_id = ? ORDER BY created_at, rowid",
            (operation_id,),
        ).fetchall()
        return tuple(self._bulk_publication_item(row) for row in rows)

    def attach_bulk_publication_execution(
        self, operation_id: str, execution_id: str
    ) -> BulkPublicationRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_bulk_publications SET execution_id = ? "
                "WHERE id = ? AND execution_id IS NULL",
                (execution_id, operation_id),
            )
            if cursor.rowcount != 1:
                current = self.get_bulk_publication(operation_id)
                if current.execution_id != execution_id:
                    raise ReviewConflictError(
                        "bulk publication already has an execution"
                    )
        return self.get_bulk_publication(operation_id)

    def transition_bulk_publication(
        self,
        operation_id: str,
        *,
        expected: tuple[str, ...],
        target: str,
    ) -> BulkPublicationRecord:
        placeholders = ",".join("?" for _item in expected)
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_bulk_publications SET status = ?, "
                "completed_at = CASE WHEN ? IN "
                "('completed', 'partial_failure', 'failed', 'cancelled') "
                "THEN CURRENT_TIMESTAMP ELSE completed_at END "
                "WHERE id = ? "
                f"AND status IN ({placeholders})",
                (target, target, operation_id, *expected),
            )
            if cursor.rowcount != 1:
                current = self.get_bulk_publication(operation_id)
                if current.status != target:
                    raise ReviewConflictError(
                        "bulk publication lifecycle changed"
                    )
        return self.get_bulk_publication(operation_id)

    def transition_bulk_publication_item(
        self,
        item_id: str,
        *,
        expected: tuple[str, ...],
        target: str,
        error_code: str | None = None,
    ) -> BulkPublicationItemRecord:
        placeholders = ",".join("?" for _item in expected)
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_bulk_publication_items SET status = ?, "
                "error_code = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? "
                f"AND status IN ({placeholders})",
                (target, error_code, item_id, *expected),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError(
                    "bulk publication item lifecycle changed"
                )
        row = self._connection.execute(
            "SELECT * FROM review_bulk_publication_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise LookupError(item_id)
        return self._bulk_publication_item(row)

    def complete_bulk_publication_from_items(
        self, operation_id: str
    ) -> BulkPublicationRecord:
        items = self.list_bulk_publication_items(operation_id)
        completed = sum(item.status == "completed" for item in items)
        failed = sum(item.status == "failed" for item in items)
        if failed and completed:
            target = "partial_failure"
        elif failed:
            target = "failed"
        else:
            target = "completed"
        return self.transition_bulk_publication(
            operation_id, expected=("running",), target=target
        )

    def reset_running_bulk_publication_items(
        self, operation_id: str
    ) -> None:
        with self._transaction():
            self._connection.execute(
                "UPDATE review_bulk_publication_items SET status = 'pending', "
                "error_code = NULL, updated_at = CURRENT_TIMESTAMP "
                "WHERE operation_id = ? AND status = 'running'",
                (operation_id,),
            )

    def requeue_bulk_publication(
        self,
        operation_id: str,
        *,
        execution_id: str,
        idempotency_key: str,
    ) -> tuple[BulkPublicationRecord, bool]:
        current = self.get_bulk_publication(operation_id)
        if current.retry_idempotency_key == idempotency_key:
            return current, False
        if current.status not in {
            "partial_failure",
            "failed",
            "cancelled",
            "interrupted",
        }:
            raise ReviewConflictError("bulk publication cannot be retried")
        with self._transaction():
            self._connection.execute(
                "UPDATE review_bulk_publication_items SET status = 'pending', "
                "error_code = NULL, updated_at = CURRENT_TIMESTAMP "
                "WHERE operation_id = ? AND status IN ('failed', 'running')",
                (operation_id,),
            )
            self._connection.execute(
                "UPDATE review_bulk_publications SET execution_id = ?, "
                "retry_idempotency_key = ?, retry_count = retry_count + 1, "
                "status = 'accepted', completed_at = NULL WHERE id = ?",
                (execution_id, idempotency_key, operation_id),
            )
        return self.get_bulk_publication(operation_id), True

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

    def prepare_candidate_revision(
        self,
        *,
        workspace_id: str,
        candidate_id: str,
        target_question_id: str,
        expected_active_hash: str,
    ) -> QuestionCandidateRecord:
        candidate = self.get_candidate(candidate_id)
        batch = self.get_batch(candidate.batch_id)
        target = self.get_active_question(target_question_id)
        if batch.workspace_id != workspace_id or target.workspace_id != workspace_id:
            raise LookupError(candidate_id)
        if (
            candidate.status == "published"
            and candidate.revision_of_question_id == target_question_id
            and target.draft_id == candidate.draft_id
        ):
            return candidate
        if target.snapshot.content_hash != expected_active_hash:
            raise ReviewConflictError(
                "active question changed before revision was requested"
            )
        if candidate.status != "review_pending" or candidate.draft_id is None:
            raise ReviewConflictError(
                "only a pending candidate can update the active question"
            )
        from app.review.question_similarity import same_question

        if not same_question(
            candidate.question.question_text,
            target.snapshot.question_text,
            left_topics=candidate.question.topics,
            right_topics=target.snapshot.topics,
            threshold=0.78,
        ):
            raise ReviewConflictError(
                "candidate does not belong to the target logical question"
            )
        revised = replace(candidate.question, question_id=target_question_id)
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_question_candidates SET question_json = ?, "
                "duplicate_of_question_id = ?, revision_of_question_id = ?, "
                "revision_base_hash = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'review_pending'",
                (
                    _canonical_json(asdict(revised)),
                    target_question_id,
                    target_question_id,
                    target.snapshot.content_hash,
                    candidate_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("candidate revision state changed")
        return self.get_candidate(candidate_id)

    def list_candidates(
        self,
        workspace_id: str,
        *,
        query: str | None = None,
        topic: str | None = None,
        difficulty: str | None = None,
        source_id: str | None = None,
        status: str | None = None,
        deleted_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[QuestionCandidateRecord, ...]:
        rows = self._connection.execute(
            "SELECT c.* FROM review_question_candidates c "
            "JOIN review_question_batches b ON b.id = c.batch_id "
            "WHERE b.workspace_id = ? AND "
            + ("c.deleted_at IS NOT NULL " if deleted_only else "c.deleted_at IS NULL ")
            + "ORDER BY c.updated_at DESC, c.rowid DESC",
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

    def delete_candidates(
        self,
        workspace_id: str,
        *,
        items: tuple[tuple[str, int | None], ...],
        idempotency_key: str,
        reason: str = "",
    ) -> dict[str, object]:
        request = {"items": items, "reason": reason}
        request_hash = sha256(_canonical_json(request).encode()).hexdigest()
        existing = self._connection.execute(
            "SELECT request_hash, result_json FROM review_question_deletion_receipts "
            "WHERE workspace_id = ? AND idempotency_key = ?",
            (workspace_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise ReviewConflictError("question deletion idempotency key changed")
            return json.loads(existing["result_json"])
        results: list[dict[str, object]] = []
        with self._transaction():
            for candidate_id, expected_version in items:
                row = self._connection.execute(
                    "SELECT c.*, d.version AS draft_version FROM review_question_candidates c "
                    "JOIN review_question_batches b ON b.id = c.batch_id "
                    "LEFT JOIN knowledge_drafts d ON d.id = c.draft_id "
                    "WHERE c.id = ? AND b.workspace_id = ?",
                    (candidate_id, workspace_id),
                ).fetchone()
                if row is None:
                    results.append({"candidateId": candidate_id, "status": "failed", "reason": "not_found"})
                    continue
                if row["deleted_at"] is not None:
                    results.append({"candidateId": candidate_id, "status": "already_deleted", "reason": None})
                    continue
                if expected_version is not None and row["draft_version"] != expected_version:
                    results.append({"candidateId": candidate_id, "status": "blocked", "reason": "version_conflict"})
                    continue
                self._connection.execute(
                    "UPDATE review_question_candidates SET deleted_at = CURRENT_TIMESTAMP, "
                    "deletion_reason = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (reason, candidate_id),
                )
                if row["status"] == "published":
                    self._connection.execute(
                        "UPDATE review_question_catalog SET active = 0, updated_at = CURRENT_TIMESTAMP "
                        "WHERE question_id = ?",
                        (self._snapshot(row["question_json"]).question_id,),
                    )
                results.append({"candidateId": candidate_id, "status": "deleted", "reason": None})
            result: dict[str, object] = {"items": results}
            self._connection.execute(
                "INSERT INTO review_question_deletion_receipts "
                "(id, workspace_id, idempotency_key, request_hash, result_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid4()), workspace_id, idempotency_key, request_hash, _canonical_json(result)),
            )
        return result

    def restore_candidate(self, workspace_id: str, candidate_id: str) -> QuestionCandidateRecord:
        with self._transaction():
            row = self._connection.execute(
                "SELECT c.* FROM review_question_candidates c "
                "JOIN review_question_batches b ON b.id = c.batch_id "
                "WHERE c.id = ? AND b.workspace_id = ?",
                (candidate_id, workspace_id),
            ).fetchone()
            if row is None:
                raise LookupError(candidate_id)
            self._connection.execute(
                "UPDATE review_question_candidates SET deleted_at = NULL, deletion_reason = '', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (candidate_id,),
            )
            if row["status"] == "published":
                self._connection.execute(
                    "UPDATE review_question_catalog SET active = 1, updated_at = CURRENT_TIMESTAMP "
                    "WHERE question_id = ?",
                    (self._snapshot(row["question_json"]).question_id,),
                )
        return self.get_candidate(candidate_id)

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
                "status = COALESCE(?, status), "
                "rejection_reason = CASE WHEN ? = 'review_pending' "
                "THEN NULL ELSE rejection_reason END, "
                "rejected_at = CASE WHEN ? = 'review_pending' "
                "THEN NULL ELSE rejected_at END, "
                "rejection_action_id = CASE WHEN ? = 'review_pending' "
                "THEN NULL ELSE rejection_action_id END, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (
                    _canonical_json(asdict(question)),
                    status,
                    status,
                    status,
                    status,
                    candidate_id,
                ),
            )
            if cursor.rowcount != 1:
                raise LookupError(candidate_id)
        return self.get_candidate(candidate_id)

    def replace_candidate_draft(
        self,
        candidate_id: str,
        *,
        draft_id: str,
        question: QuestionSnapshot,
    ) -> QuestionCandidateRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_question_candidates SET draft_id = ?, question_json = ?, "
                "status = 'review_pending', rejection_reason = NULL, rejected_at = NULL, "
                "rejection_action_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (draft_id, _canonical_json(asdict(question)), candidate_id),
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

    def reject_candidate_for_draft(
        self,
        draft_id: str,
        *,
        reason: str,
        rejected_at: str,
        action_id: str,
    ) -> QuestionCandidateRecord | None:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_question_candidates SET status = 'rejected', "
                "rejection_reason = ?, rejected_at = ?, rejection_action_id = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE draft_id = ?",
                (reason, rejected_at, action_id, draft_id),
            )
        if cursor.rowcount == 0:
            return None
        return self.get_candidate_by_draft(draft_id)

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
                "WHERE question_id = ? OR draft_id = ? OR publication_id = ?",
                (candidate.question.question_id, draft_id, publication_id),
            ).fetchone()
            if existing is None:
                if candidate.revision_of_question_id is not None:
                    raise ReviewConflictError(
                        "active question disappeared before revision publication"
                    )
                from app.review.question_similarity import same_question

                active_rows = self._connection.execute(
                    "SELECT question_json FROM review_question_catalog "
                    "WHERE workspace_id = ? AND active = 1",
                    (workspace_id,),
                ).fetchall()
                if any(
                    same_question(
                        candidate.question.question_text,
                        self._snapshot(row["question_json"]).question_text,
                        left_topics=candidate.question.topics,
                        right_topics=self._snapshot(row["question_json"]).topics,
                        threshold=0.9,
                    )
                    for row in active_rows
                ):
                    raise ReviewConflictError(
                        "an equivalent logical question is already active"
                    )
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
                if existing["question_id"] != candidate.question.question_id:
                    raise ReviewConflictError("publication already projects different question facts")
                if (
                    candidate.revision_of_question_id is not None
                    and existing["content_hash"] != candidate.revision_base_hash
                    and existing["draft_id"] != draft_id
                ):
                    raise ReviewConflictError(
                        "active question changed before revision publication"
                    )
                self._connection.execute(
                    "UPDATE review_question_catalog SET document_id = ?, draft_id = ?, "
                    "publication_id = ?, question_json = ?, content_hash = ?, active = 1, "
                    "published_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
                    "WHERE question_id = ?",
                    (
                        document_id,
                        draft_id,
                        publication_id,
                        candidate_row["question_json"],
                        content_hash,
                        candidate.question.question_id,
                    ),
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
            "SELECT r.*, s.deleted_at AS archived_at FROM review_rounds r "
            "JOIN agent_sessions s ON s.id = r.session_id WHERE r.id = ?", (round_id,)
        ).fetchone()
        if row is None:
            raise ReviewRoundNotFoundError(round_id)
        return self._round_record(row)

    def get_round_by_session(self, session_id: str) -> ReviewRoundRecord:
        row = self._connection.execute(
            "SELECT r.*, s.deleted_at AS archived_at FROM review_rounds r "
            "JOIN agent_sessions s ON s.id = r.session_id WHERE r.session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise ReviewRoundNotFoundError(session_id)
        return self._round_record(row)

    def list_rounds(self, workspace_id: str) -> tuple[ReviewRoundRecord, ...]:
        rows = self._connection.execute(
            "SELECT r.*, s.deleted_at AS archived_at FROM review_rounds r "
            "JOIN agent_sessions s ON s.id = r.session_id "
            "WHERE r.workspace_id = ? ORDER BY r.updated_at DESC, r.rowid DESC",
            (workspace_id,),
        ).fetchall()
        return tuple(self._round_record(row) for row in rows)

    def find_discussion_session(
        self, *, parent_session_id: str, attempt_id: str
    ) -> str | None:
        row = self._connection.execute(
            "SELECT s.id FROM agent_sessions s "
            "JOIN agent_runs r ON r.session_id = s.id "
            "WHERE s.parent_session_id = ? AND s.graph_id = 'review.discussion' "
            "AND json_extract(r.input_json, '$.attempt_evidence.attemptId') = ? "
            "ORDER BY s.updated_at DESC, r.rowid ASC LIMIT 1",
            (parent_session_id, attempt_id),
        ).fetchone()
        return None if row is None else str(row["id"])

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

    def get_input_receipt(self, request_id: str) -> ReviewInputReceipt | None:
        row = self._connection.execute(
            "SELECT * FROM review_input_receipts WHERE input_request_id = ?",
            (request_id,),
        ).fetchone()
        return None if row is None else self._input_receipt(row)

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
        answer_model_id: str | None = None,
        reasoning_effort: str | None = None,
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

            if answer_model_id is not None and reasoning_effort is not None:
                settings = json.loads(round_row["settings_json"])
                settings["answer_model_id"] = answer_model_id
                settings["reasoning_effort"] = reasoning_effort
                self._connection.execute(
                    "UPDATE review_rounds SET settings_json = ? WHERE id = ?",
                    (_canonical_json(settings), request["round_id"]),
                )

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

    def complete_attempt_without_follow_up(
        self, attempt_id: str
    ) -> ReviewAttemptRecord:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE review_attempts SET status = 'completed', "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'waiting_for_follow_up'",
                (attempt_id,),
            )
            if cursor.rowcount != 1:
                raise ReviewConflictError("attempt is not waiting for follow-up")
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

    def _get_curation_work_item_by_identity(
        self, batch_id: str, stage: CurationWorkStage, unit_index: int
    ) -> CurationWorkItemRecord:
        row = self._connection.execute(
            "SELECT * FROM review_curation_work_items "
            "WHERE batch_id = ? AND stage = ? AND unit_index = ?",
            (batch_id, stage, unit_index),
        ).fetchone()
        if row is None:
            raise LookupError((batch_id, stage, unit_index))
        return self._curation_work_item_record(row)

    def _require_curation_execution_ownership(
        self, batch: QuestionBatchRecord, execution_id: str
    ) -> tuple[sqlite3.Row, dict[str, Any], dict[str, Any]]:
        execution = self._connection.execute(
            "SELECT run.status, run.session_id, run.input_json, "
            "session.workspace_id, session.graph_id "
            "FROM agent_runs run JOIN agent_sessions session "
            "ON session.id = run.session_id WHERE run.id = ?",
            (execution_id,),
        ).fetchone()
        if execution is None:
            raise LookupError(execution_id)
        try:
            input_value = json.loads(execution["input_json"])
        except (TypeError, ValueError):
            input_value = None
        if (
            batch.session_id is None
            or execution["session_id"] != batch.session_id
            or execution["workspace_id"] != batch.workspace_id
            or execution["graph_id"] not in {"question.curate", "question.revise"}
            or not isinstance(input_value, dict)
        ):
            raise ReviewConflictError(
                "curation execution does not belong to question batch"
            )
        associations = [
            input_value[key]
            for key in ("batchId", "batch_id")
            if key in input_value
        ]
        if not associations or any(value != batch.id for value in associations):
            raise ReviewConflictError(
                "curation execution does not belong to question batch"
            )
        source_ref_values = [
            input_value[key]
            for key in ("sourceRefs", "source_refs")
            if key in input_value
        ]
        if any(
            not isinstance(value, list)
            or tuple(value) != batch.source_refs
            for value in source_ref_values
        ):
            raise ReviewConflictError(
                "curation execution immutable input changed"
            )
        normalized = dict(input_value)
        for key in ("batchId", "batch_id", "sourceRefs", "source_refs"):
            normalized.pop(key, None)
        normalized["batchId"] = batch.id
        normalized["sourceRefs"] = list(batch.source_refs)
        return execution, input_value, normalized

    def _insert_curation_attempt(
        self,
        *,
        batch_id: str,
        execution_id: str,
        reason: CurationAttemptReason,
    ) -> CurationBatchAttemptRecord:
        ordinal = self._connection.execute(
            "SELECT COALESCE(MAX(ordinal), 0) + 1 "
            "FROM review_curation_batch_attempts WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()[0]
        attempt_id = str(uuid4())
        self._connection.execute(
            "INSERT INTO review_curation_batch_attempts "
            "(id, batch_id, execution_id, ordinal, reason) "
            "VALUES (?, ?, ?, ?, ?)",
            (attempt_id, batch_id, execution_id, ordinal, reason),
        )
        row = self._connection.execute(
            "SELECT * FROM review_curation_batch_attempts WHERE id = ?",
            (attempt_id,),
        ).fetchone()
        assert row is not None
        return self._curation_batch_attempt_record(row)

    @staticmethod
    def _validate_work_item_plan(
        stage: CurationWorkStage,
        unit_index: int,
        input_digest: str,
        source_refs: tuple[str, ...],
        processor_kind: CurationProcessorKind,
    ) -> None:
        if stage not in {"discovery", "enrichment"}:
            raise ValueError("unsupported curation work item stage")
        if unit_index < 0:
            raise ValueError("curation work item unit index must not be negative")
        if re.fullmatch(r"[0-9a-f]{64}", input_digest) is None:
            raise ValueError("curation work item input digest must be a sha256 digest")
        if not source_refs or any(not ref.strip() for ref in source_refs):
            raise ValueError("curation work item source refs must not be empty")
        if processor_kind not in {"deterministic", "model"}:
            raise ValueError("unsupported curation work item processor kind")

    @staticmethod
    def _validate_control_request(idempotency_key: str, expected_version: int) -> None:
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ValueError("idempotency key must be non-empty and bounded")
        if expected_version < 1:
            raise ValueError("expected version must be positive")

    @staticmethod
    def _control_request_digest(payload: dict[str, object]) -> str:
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _utc_datetime(value: str) -> datetime:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _validate_curation_error_code(error_code: str) -> None:
        if re.fullmatch(r"[a-z][a-z0-9_]{0,99}", error_code) is None:
            raise ValueError("curation error code must be stable and bounded")

    @staticmethod
    def _validate_curation_work_item_output(
        stage: CurationWorkStage, output: dict[str, object]
    ) -> dict[str, object]:
        """Reject unbounded or non-contract output before it becomes durable state."""
        try:
            from app.agents.question_curation_contracts import (
                QuestionCandidateChunk,
                QuestionSeedChunk,
            )
        except ImportError:
            # Task 1 and this persistence foundation can land independently.
            # Keep the same narrow wire contract until the strict Pydantic
            # chunks are available, then delegate validation to them above.
            expected_key = "seeds" if stage == "discovery" else "candidates"
            maximum = 6 if stage == "discovery" else 3
            if set(output) != {expected_key}:
                raise ValueError("curation work item output has an invalid shape")
            values = output[expected_key]
            if not isinstance(values, list) or len(values) > maximum:
                raise ValueError("curation work item output exceeds its bound")
            if stage == "discovery":
                if any(
                    not isinstance(value, dict)
                    or set(value) != {"question_text", "source_ref"}
                    or any(
                        not isinstance(item, str) or not item.strip()
                        for item in value.values()
                    )
                    for value in values
                ):
                    raise ValueError("invalid discovery work item output")
            else:
                required = {
                    "title", "question_text", "reference_answer", "topics",
                    "difficulty", "key_points", "follow_ups", "source_refs",
                    "correction_note",
                }
                if any(
                    not isinstance(value, dict)
                    or set(value) != required
                    or not all(
                        isinstance(value[key], list)
                        for key in {"topics", "key_points", "follow_ups", "source_refs"}
                    )
                    or not all(
                        isinstance(value[key], str) and value[key].strip()
                        for key in required
                        - {"topics", "key_points", "follow_ups", "source_refs", "difficulty"}
                    )
                    or value["difficulty"] not in {"easy", "medium", "hard"}
                    or not all(
                        isinstance(entry, str) and entry.strip()
                        for key in {"topics", "key_points", "source_refs"}
                        for entry in value[key]
                    )
                    or not all(isinstance(entry, str) for entry in value["follow_ups"])
                    for value in values
                ):
                    raise ValueError("invalid enrichment work item output")
            validated = output
        else:
            contract = (
                QuestionSeedChunk if stage == "discovery" else QuestionCandidateChunk
            )
            validated = contract.model_validate(output).model_dump(mode="json")
        encoded = _canonical_json(validated)
        if len(encoded.encode("utf-8")) > 100_000:
            raise ValueError("curation work item output exceeds its byte bound")
        return cast(dict[str, object], json.loads(encoded))

    @staticmethod
    def _curation_work_item_record(row: sqlite3.Row) -> CurationWorkItemRecord:
        output = row["output_json"]
        return CurationWorkItemRecord(
            id=row["id"],
            batch_id=row["batch_id"],
            stage=cast(CurationWorkStage, row["stage"]),
            unit_index=row["unit_index"],
            input_digest=row["input_digest"],
            source_refs=tuple(json.loads(row["source_refs_json"])),
            processor_kind=cast(CurationProcessorKind, row["processor_kind"]),
            status=cast(CurationWorkStatus, row["status"]),
            output=None if output is None else cast(dict[str, object], json.loads(output)),
            attempt_count=row["attempt_count"],
            last_error_code=row["last_error_code"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _curation_batch_attempt_record(
        row: sqlite3.Row,
    ) -> CurationBatchAttemptRecord:
        return CurationBatchAttemptRecord(
            id=row["id"],
            batch_id=row["batch_id"],
            execution_id=row["execution_id"],
            ordinal=row["ordinal"],
            reason=cast(CurationAttemptReason, row["reason"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _curation_control_receipt_record(
        row: sqlite3.Row,
    ) -> CurationControlReceiptRecord:
        return CurationControlReceiptRecord(
            id=row["id"],
            batch_id=row["batch_id"],
            idempotency_key=row["idempotency_key"],
            operation=cast(CurationControlOperation, row["operation"]),
            request_digest=row["request_digest"],
            execution_id=row["execution_id"],
            result_status=row["result_status"],
            created_at=row["created_at"],
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
            origin_session_id=row["origin_session_id"],
            run_id=row["run_id"],
            source_refs=tuple(json.loads(row["source_refs_json"])),
            rewrite_of_batch_id=row["rewrite_of_batch_id"],
            status=cast(CurationBatchStatus, row["status"]),
            version=row["version"],
            control_intent=cast(
                CurationControlIntent | None, row["control_intent"]
            ),
            concurrency_limit=row["concurrency_limit"],
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
            rejection_reason=row["rejection_reason"],
            rejected_at=row["rejected_at"],
            rejection_action_id=row["rejection_action_id"],
            duplicate_of_question_id=row["duplicate_of_question_id"],
            revision_of_question_id=row["revision_of_question_id"],
            revision_base_hash=row["revision_base_hash"],
            status=row["status"],
            deleted_at=row["deleted_at"],
            deletion_reason=row["deletion_reason"],
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
            preferred_model_id=row["preferred_model_id"],
            preferred_reasoning_effort=cast(
                ReasoningEffort, row["preferred_reasoning_effort"]
            ),
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
            origin_session_id=row["origin_session_id"],
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
            original_text=row["original_text"],
            summary_version=row["summary_version"],
            command=json.loads(row["command_json"]),
            result=json.loads(row["result_json"]),
            status=row["status"],
            execution_id=row["execution_id"],
            lifecycle_status=row["lifecycle_status"],
            retry_count=row["retry_count"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _bulk_publication(row: sqlite3.Row) -> BulkPublicationRecord:
        return BulkPublicationRecord(
            id=row["id"],
            session_id=row["session_id"],
            execution_id=row["execution_id"],
            summary_version=row["summary_version"],
            idempotency_key=row["idempotency_key"],
            retry_idempotency_key=row["retry_idempotency_key"],
            retry_count=row["retry_count"],
            status=row["status"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _bulk_publication_item(
        row: sqlite3.Row,
    ) -> BulkPublicationItemRecord:
        return BulkPublicationItemRecord(
            id=row["id"],
            operation_id=row["operation_id"],
            candidate_id=row["candidate_id"],
            idempotency_key=row["idempotency_key"],
            status=row["status"],
            error_code=row["error_code"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
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
            archived_at=row["archived_at"],
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
