from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from hashlib import sha256

from app.evaluation.outcomes import (
    BusinessOutcomePayload,
    BusinessOutcomeProjection,
    OutcomeCounters,
    OutcomeIdentity,
    OutcomeInput,
    OutcomeItem,
    OutcomeProvenance,
    OutcomeUnit,
    OutcomeUserDecision,
    freeze_business_outcome,
)
from app.review.models import QuestionCandidateRecord
from app.review.repository import ReviewRepository


class OutcomeProjectionAmbiguousError(RuntimeError):
    pass


class QuestionCurationOutcomeAdapter:
    task_type = "question_curation"

    def __init__(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
    ) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.workspace_id = workspace_id
        self.review = ReviewRepository(connection)

    def build(self, execution_id: str) -> BusinessOutcomeProjection:
        execution = self._execution(execution_id)
        batch_id = self._batch_id(execution_id)
        batch = self.review.get_batch(batch_id)
        candidates = self._candidates(batch_id)
        work_items = self.review.list_curation_work_items(batch_id)
        seed_tasks = self.review.list_curation_seed_tasks(batch_id)

        items: list[OutcomeItem] = []
        evidence_gaps: list[str] = []
        for candidate in candidates:
            item, gaps = self._candidate(candidate)
            items.append(item)
            evidence_gaps.extend(gaps)

        units = tuple(
            OutcomeUnit(
                unit_id=item.id,
                unit_type=f"curation_{item.stage}_work_item",
                status=item.status,
                error_code=item.last_error_code,
            )
            for item in work_items
        ) + tuple(
            OutcomeUnit(
                unit_id=item.id,
                unit_type="curation_seed_task",
                status=item.status,
                error_code=item.last_error_code,
            )
            for item in seed_tasks
        )

        raw_input = self._json_object(execution["input_json"])
        input_hash = sha256(
            json.dumps(
                raw_input,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        payload = BusinessOutcomePayload(
            task_type=self.task_type,
            identity=OutcomeIdentity(
                workspace_id=self.workspace_id,
                session_id=str(execution["session_id"]),
                execution_id=execution_id,
                graph_id=str(execution["graph_id"]),
                domain_refs={"batchId": batch_id},
            ),
            input=OutcomeInput(
                source_refs=batch.source_refs,
                input_hash=input_hash,
                requested_scope={
                    "batchId": batch_id,
                    "sourceCount": len(batch.source_refs),
                    "isRevision": batch.rewrite_of_batch_id is not None,
                },
            ),
            execution_status=str(execution["status"]),
            terminal_state=batch.status,
            items=tuple(items),
            units=units,
            unit_counters={
                "workItems": self._work_counters(work_items),
                "seedTasks": self._seed_counters(seed_tasks),
                "candidates": self._candidate_counters(candidates),
            },
            evidence_gaps=tuple(dict.fromkeys(evidence_gaps)),
            runtime_versions={
                "graph": f"{execution['graph_id']}@{execution['graph_version']}"
            },
        )
        return freeze_business_outcome(payload)

    def _execution(self, execution_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT run.id, run.session_id, run.status, run.input_json, "
            "session.graph_id, session.graph_version "
            "FROM agent_runs run JOIN agent_sessions session "
            "ON session.id = run.session_id "
            "WHERE run.id = ? AND session.workspace_id = ? "
            "AND session.graph_id IN ('question.curate', 'question.revise')",
            (execution_id, self.workspace_id),
        ).fetchone()
        if row is None:
            raise LookupError(execution_id)
        return row

    def _batch_id(self, execution_id: str) -> str:
        rows = self.connection.execute(
            "SELECT DISTINCT batch.id, "
            "CASE WHEN batch.run_id = ? THEN 0 ELSE 1 END AS priority "
            "FROM review_question_batches batch "
            "LEFT JOIN review_curation_batch_attempts attempt "
            "ON attempt.batch_id = batch.id "
            "WHERE batch.workspace_id = ? "
            "AND (batch.run_id = ? OR attempt.execution_id = ?) "
            "ORDER BY priority, batch.updated_at DESC, batch.id",
            (execution_id, self.workspace_id, execution_id, execution_id),
        ).fetchall()
        identities = tuple(dict.fromkeys(str(row["id"]) for row in rows))
        if not identities:
            raise LookupError(execution_id)
        if len(identities) > 1:
            raise OutcomeProjectionAmbiguousError(
                "one execution is associated with multiple question batches"
            )
        return identities[0]

    def _candidates(self, batch_id: str) -> tuple[QuestionCandidateRecord, ...]:
        rows = self.connection.execute(
            "SELECT DISTINCT candidate.id, candidate.created_at "
            "FROM review_question_candidates candidate "
            "LEFT JOIN review_curation_batch_candidates membership "
            "ON membership.candidate_id = candidate.id "
            "WHERE candidate.batch_id = ? OR membership.batch_id = ? "
            "ORDER BY candidate.created_at, candidate.id",
            (batch_id, batch_id),
        ).fetchall()
        return tuple(self.review.get_candidate(str(row["id"])) for row in rows)

    @staticmethod
    def _candidate(
        candidate: QuestionCandidateRecord,
    ) -> tuple[OutcomeItem, tuple[str, ...]]:
        provenance = [
            OutcomeProvenance(
                field_path="content.questionText",
                support_type="normalized",
                source_refs=candidate.source_refs,
            )
        ]
        gaps: list[str] = []
        if candidate.answer_basis == "source":
            provenance.append(
                OutcomeProvenance(
                    field_path="content.referenceAnswer",
                    support_type="direct",
                    source_refs=candidate.source_refs,
                )
            )
        elif candidate.answer_basis == "model":
            provenance.append(
                OutcomeProvenance(
                    field_path="content.referenceAnswer",
                    support_type="inferred",
                    source_refs=candidate.source_refs,
                    note="model_supplement_only",
                )
            )
        elif candidate.answer_basis == "mixed":
            provenance.extend(
                (
                    OutcomeProvenance(
                        field_path="content.referenceAnswer",
                        support_type="direct",
                        source_refs=candidate.source_refs,
                        note="merged_source_component",
                    ),
                    OutcomeProvenance(
                        field_path="content.referenceAnswer",
                        support_type="inferred",
                        source_refs=candidate.source_refs,
                        note="merged_model_component",
                    ),
                )
            )
            gaps.append("source_supplemental_answer_not_separated")
        else:
            provenance.append(
                OutcomeProvenance(
                    field_path="content.referenceAnswer",
                    support_type="unsupported",
                    source_refs=candidate.source_refs,
                    note="legacy_answer_basis_unknown",
                )
            )
            gaps.append("answer_basis_unknown")

        decision = OutcomeUserDecision(status="pending")
        if candidate.deleted_at is not None:
            decision = OutcomeUserDecision(
                status="ignored",
                version=candidate.confirmation_version,
                occurred_at=candidate.deleted_at,
                reason=candidate.deletion_reason or None,
            )
        elif candidate.status == "rejected":
            decision = OutcomeUserDecision(
                status="rejected",
                version=candidate.confirmation_version,
                occurred_at=candidate.rejected_at,
                reason=candidate.rejection_reason,
            )
        elif (
            candidate.confirmation_status == "confirmed"
            or candidate.status == "published"
        ):
            decision = OutcomeUserDecision(
                status="accepted",
                version=candidate.confirmation_version,
                occurred_at=candidate.confirmed_at,
            )

        content = asdict(candidate.question)
        content.update(
            {
                "answer_basis": candidate.answer_basis,
                "material_support": candidate.material_support,
                "needs_review": candidate.needs_review,
                "normalization_issues": candidate.normalization_issues,
                "source_refs": candidate.source_refs,
            }
        )
        return (
            OutcomeItem(
                item_id=candidate.id,
                item_type="question_candidate",
                status=candidate.status,
                domain_version=candidate.confirmation_version,
                content=content,
                provenance=tuple(provenance),
                user_decision=decision,
            ),
            tuple(gaps),
        )

    @staticmethod
    def _work_counters(items) -> OutcomeCounters:
        statuses = [item.status for item in items]
        return QuestionCurationOutcomeAdapter._counters(
            statuses,
            completed={"completed"},
            failed={"failed"},
            skipped=set(),
        )

    @staticmethod
    def _seed_counters(items) -> OutcomeCounters:
        statuses = [item.status for item in items]
        return QuestionCurationOutcomeAdapter._counters(
            statuses,
            completed={"completed", "degraded"},
            failed=set(),
            skipped={"skipped"},
        )

    @staticmethod
    def _candidate_counters(items) -> OutcomeCounters:
        statuses: list[str] = []
        for item in items:
            if item.deleted_at is not None or item.status == "rejected":
                statuses.append("skipped")
            elif (
                item.confirmation_status == "confirmed"
                or item.status == "published"
            ):
                statuses.append("completed")
            else:
                statuses.append("pending")
        return QuestionCurationOutcomeAdapter._counters(
            statuses,
            completed={"completed"},
            failed=set(),
            skipped={"skipped"},
        )

    @staticmethod
    def _counters(
        statuses: list[str],
        *,
        completed: set[str],
        failed: set[str],
        skipped: set[str],
    ) -> OutcomeCounters:
        completed_count = sum(status in completed for status in statuses)
        failed_count = sum(status in failed for status in statuses)
        skipped_count = sum(status in skipped for status in statuses)
        pending_count = len(statuses) - completed_count - failed_count - skipped_count
        return OutcomeCounters(
            total=len(statuses),
            completed=completed_count,
            failed=failed_count,
            skipped=skipped_count,
            pending=pending_count,
        )

    @staticmethod
    def _json_object(value: str | None) -> dict[str, object]:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
