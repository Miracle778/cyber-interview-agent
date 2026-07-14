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
    Difficulty,
    InputKind,
    MasteryEntry,
    MasteryProjection,
    QuestionBatchRecord,
    QuestionCandidateRecord,
    QuestionCatalogRecord,
    QuestionSnapshot,
    ReasoningEffort,
    ReportProposalRecord,
    ReviewAttemptRecord,
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
            duplicate_of_question_id=row["duplicate_of_question_id"],
            status=row["status"],
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
