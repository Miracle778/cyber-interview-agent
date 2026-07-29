from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass


class EvaluationIdempotencyConflictError(RuntimeError):
    pass


class ImmutableEvaluationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EvaluationRunRecord:
    id: str
    workspace_id: str
    execution_id: str
    eval_pack_id: str
    eval_pack_version: int
    trigger: str
    status: str
    frozen_input_hash: str
    snapshot_json: str
    deterministic_result_json: str | None
    judge_provider_model_id: str | None
    judge_trace_run_id: str | None
    judge_result_json: str | None
    error_code: str | None
    idempotency_key: str
    created_at: str
    started_at: str | None
    completed_at: str | None


@dataclass(frozen=True, slots=True)
class HumanFeedbackRecord:
    id: str
    workspace_id: str
    eval_run_id: str
    version: int
    verdict: str
    dimension_id: str | None
    reason: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class RegressionCaseRecord:
    id: str
    workspace_id: str
    source_eval_run_id: str | None
    execution_id: str
    eval_pack_id: str
    eval_pack_version: int
    version: int
    supersedes_case_id: str | None
    snapshot_hash: str
    snapshot_json: str
    expected_invariants_json: str
    contains_private_bodies: bool
    redaction_summary: str
    created_at: str


class AgentEvaluationRepository:
    def __init__(
        self, connection: sqlite3.Connection, workspace_id: str
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id

    @contextmanager
    def _transaction(self):
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def create_run(
        self,
        *,
        eval_run_id: str,
        execution_id: str,
        eval_pack_id: str,
        eval_pack_version: int,
        trigger: str,
        frozen_input_hash: str,
        snapshot_json: str,
        idempotency_key: str,
        judge_provider_model_id: str | None = None,
    ) -> EvaluationRunRecord:
        existing = self._by_idempotency_key(idempotency_key)
        if existing is not None:
            if (
                existing.execution_id != execution_id
                or existing.eval_pack_id != eval_pack_id
                or existing.eval_pack_version != eval_pack_version
                or existing.trigger != trigger
                or existing.frozen_input_hash != frozen_input_hash
            ):
                raise EvaluationIdempotencyConflictError(
                    "evaluation idempotency key conflict"
                )
            return existing
        with self._transaction():
            self.connection.execute(
                "INSERT INTO agent_eval_runs "
                "(id, workspace_id, execution_id, eval_pack_id, "
                "eval_pack_version, trigger, frozen_input_hash, snapshot_json, "
                "judge_provider_model_id, idempotency_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    eval_run_id,
                    self.workspace_id,
                    execution_id,
                    eval_pack_id,
                    eval_pack_version,
                    trigger,
                    frozen_input_hash,
                    snapshot_json,
                    judge_provider_model_id,
                    idempotency_key,
                ),
            )
        return self._require_run(eval_run_id)

    def get_run(self, eval_run_id: str) -> EvaluationRunRecord | None:
        row = self.connection.execute(
            "SELECT * FROM agent_eval_runs WHERE id = ? AND workspace_id = ?",
            (eval_run_id, self.workspace_id),
        ).fetchone()
        return None if row is None else self._run(row)

    def list_runs(self) -> tuple[EvaluationRunRecord, ...]:
        return tuple(
            self._run(row)
            for row in self.connection.execute(
                "SELECT * FROM agent_eval_runs WHERE workspace_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (self.workspace_id,),
            )
        )

    def mark_running(self, eval_run_id: str) -> EvaluationRunRecord:
        with self._transaction():
            updated = self.connection.execute(
                "UPDATE agent_eval_runs SET status = 'running', "
                "started_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND workspace_id = ? AND status = 'pending'",
                (eval_run_id, self.workspace_id),
            )
            if updated.rowcount != 1:
                raise ImmutableEvaluationError(
                    "evaluation run cannot enter running state"
                )
        return self._require_run(eval_run_id)

    def complete_run(
        self,
        eval_run_id: str,
        *,
        deterministic_result_json: str,
        judge_result_json: str | None,
        status: str,
        error_code: str | None = None,
        judge_trace_run_id: str | None = None,
    ) -> EvaluationRunRecord:
        with self._transaction():
            updated = self.connection.execute(
                "UPDATE agent_eval_runs SET status = ?, "
                "deterministic_result_json = ?, judge_result_json = ?, "
                "judge_trace_run_id = ?, error_code = ?, "
                "completed_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND workspace_id = ? "
                "AND status IN ('pending', 'running')",
                (
                    status,
                    deterministic_result_json,
                    judge_result_json,
                    judge_trace_run_id,
                    error_code,
                    eval_run_id,
                    self.workspace_id,
                ),
            )
            if updated.rowcount != 1:
                raise ImmutableEvaluationError(
                    "completed evaluation inputs and results are immutable"
                )
        return self._require_run(eval_run_id)

    def add_feedback(
        self,
        *,
        eval_run_id: str,
        feedback_id: str,
        verdict: str,
        dimension_id: str | None,
        reason: str | None,
    ) -> HumanFeedbackRecord:
        self._require_run(eval_run_id)
        with self._transaction():
            version = self.connection.execute(
                "SELECT COALESCE(MAX(feedback_version), 0) + 1 "
                "FROM agent_eval_human_feedback "
                "WHERE workspace_id = ? AND eval_run_id = ?",
                (self.workspace_id, eval_run_id),
            ).fetchone()[0]
            self.connection.execute(
                "INSERT INTO agent_eval_human_feedback "
                "(id, workspace_id, eval_run_id, feedback_version, verdict, "
                "dimension_id, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    feedback_id,
                    self.workspace_id,
                    eval_run_id,
                    version,
                    verdict,
                    dimension_id,
                    reason,
                ),
            )
        return self._feedback(
            self.connection.execute(
                "SELECT * FROM agent_eval_human_feedback WHERE id = ?",
                (feedback_id,),
            ).fetchone()
        )

    def list_feedback(
        self, eval_run_id: str
    ) -> tuple[HumanFeedbackRecord, ...]:
        return tuple(
            self._feedback(row)
            for row in self.connection.execute(
                "SELECT * FROM agent_eval_human_feedback "
                "WHERE workspace_id = ? AND eval_run_id = ? "
                "ORDER BY feedback_version",
                (self.workspace_id, eval_run_id),
            )
        )

    def create_regression_case(
        self,
        *,
        case_id: str,
        source_eval_run_id: str | None,
        execution_id: str,
        eval_pack_id: str,
        eval_pack_version: int,
        snapshot_hash: str,
        snapshot_json: str,
        expected_invariants_json: str,
        contains_private_bodies: bool,
        redaction_summary: str,
        supersedes_case_id: str | None = None,
    ) -> RegressionCaseRecord:
        version = 1
        if supersedes_case_id is not None:
            previous = self._require_case(supersedes_case_id)
            version = previous.version + 1
        with self._transaction():
            self.connection.execute(
                "INSERT INTO agent_eval_regression_cases "
                "(id, workspace_id, source_eval_run_id, execution_id, "
                "eval_pack_id, eval_pack_version, case_version, "
                "supersedes_case_id, snapshot_hash, snapshot_json, "
                "expected_invariants_json, contains_private_bodies, "
                "redaction_summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    case_id,
                    self.workspace_id,
                    source_eval_run_id,
                    execution_id,
                    eval_pack_id,
                    eval_pack_version,
                    version,
                    supersedes_case_id,
                    snapshot_hash,
                    snapshot_json,
                    expected_invariants_json,
                    int(contains_private_bodies),
                    redaction_summary,
                ),
            )
        return self._require_case(case_id)

    def list_regression_cases(self) -> tuple[RegressionCaseRecord, ...]:
        return tuple(
            self._case(row)
            for row in self.connection.execute(
                "SELECT * FROM agent_eval_regression_cases "
                "WHERE workspace_id = ? ORDER BY created_at DESC, id DESC",
                (self.workspace_id,),
            )
        )

    def reserve_daily_slot(self, counter_date: str, *, cap: int) -> bool:
        if cap <= 0:
            return False
        with self._transaction():
            row = self.connection.execute(
                "INSERT INTO agent_eval_daily_counters "
                "(workspace_id, counter_date, automatic_count) VALUES (?, ?, 1) "
                "ON CONFLICT(workspace_id, counter_date) DO UPDATE SET "
                "automatic_count = automatic_count + 1, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE automatic_count < ? "
                "RETURNING automatic_count",
                (self.workspace_id, counter_date, cap),
            ).fetchone()
        return row is not None

    def daily_count(self, counter_date: str) -> int:
        row = self.connection.execute(
            "SELECT automatic_count FROM agent_eval_daily_counters "
            "WHERE workspace_id = ? AND counter_date = ?",
            (self.workspace_id, counter_date),
        ).fetchone()
        return 0 if row is None else int(row[0])

    def _by_idempotency_key(
        self, idempotency_key: str
    ) -> EvaluationRunRecord | None:
        row = self.connection.execute(
            "SELECT * FROM agent_eval_runs "
            "WHERE workspace_id = ? AND idempotency_key = ?",
            (self.workspace_id, idempotency_key),
        ).fetchone()
        return None if row is None else self._run(row)

    def _require_run(self, eval_run_id: str) -> EvaluationRunRecord:
        record = self.get_run(eval_run_id)
        if record is None:
            raise LookupError("evaluation run not found")
        return record

    def _require_case(self, case_id: str) -> RegressionCaseRecord:
        row = self.connection.execute(
            "SELECT * FROM agent_eval_regression_cases "
            "WHERE id = ? AND workspace_id = ?",
            (case_id, self.workspace_id),
        ).fetchone()
        if row is None:
            raise LookupError("regression case not found")
        return self._case(row)

    @staticmethod
    def _run(row) -> EvaluationRunRecord:
        return EvaluationRunRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            execution_id=row["execution_id"],
            eval_pack_id=row["eval_pack_id"],
            eval_pack_version=row["eval_pack_version"],
            trigger=row["trigger"],
            status=row["status"],
            frozen_input_hash=row["frozen_input_hash"],
            snapshot_json=row["snapshot_json"],
            deterministic_result_json=row["deterministic_result_json"],
            judge_provider_model_id=row["judge_provider_model_id"],
            judge_trace_run_id=row["judge_trace_run_id"],
            judge_result_json=row["judge_result_json"],
            error_code=row["error_code"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _feedback(row) -> HumanFeedbackRecord:
        return HumanFeedbackRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            eval_run_id=row["eval_run_id"],
            version=row["feedback_version"],
            verdict=row["verdict"],
            dimension_id=row["dimension_id"],
            reason=row["reason"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _case(row) -> RegressionCaseRecord:
        return RegressionCaseRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            source_eval_run_id=row["source_eval_run_id"],
            execution_id=row["execution_id"],
            eval_pack_id=row["eval_pack_id"],
            eval_pack_version=row["eval_pack_version"],
            version=row["case_version"],
            supersedes_case_id=row["supersedes_case_id"],
            snapshot_hash=row["snapshot_hash"],
            snapshot_json=row["snapshot_json"],
            expected_invariants_json=row["expected_invariants_json"],
            contains_private_bodies=bool(row["contains_private_bodies"]),
            redaction_summary=row["redaction_summary"],
            created_at=row["created_at"],
        )
