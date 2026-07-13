from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.runtime.middleware.types import ModelUsage


@dataclass(frozen=True, slots=True)
class SessionUsageAggregate:
    call_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    context_tokens: int
    estimated_count: int


@dataclass(frozen=True, slots=True)
class GuardState:
    observation_count: int
    last_sequence: int
    last_fingerprint: str | None
    last_state_hash: str | None


@dataclass(frozen=True, slots=True)
class TraceSegment:
    run_id: str
    segment_sequence: int
    trace_id: str
    span_id: str
    created_at: str
    finished_at: str | None


class RuntimeMiddlewareRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def record_usage(
        self,
        *,
        workspace_id: str,
        session_id: str,
        run_id: str,
        operation_key: str,
        role: str,
        provider_id: str,
        provider_model_id: str,
        usage: ModelUsage,
        status: str,
        error_code: str | None = None,
    ) -> bool:
        cursor = self._connection.execute(
            "INSERT INTO model_invocation_usage "
            "(workspace_id, session_id, run_id, operation_key, role, provider_id, "
            "provider_model_id, input_tokens, output_tokens, total_tokens, "
            "context_tokens, latency_ms, estimated, status, error_code) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, operation_key) DO NOTHING",
            (
                workspace_id,
                session_id,
                run_id,
                operation_key,
                role,
                provider_id,
                provider_model_id,
                usage.input_tokens,
                usage.output_tokens,
                usage.total_tokens,
                usage.context_tokens,
                usage.latency_ms,
                int(usage.estimated),
                status,
                error_code,
            ),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def aggregate_session_usage(self, session_id: str) -> SessionUsageAggregate:
        row = self._connection.execute(
            "SELECT COUNT(*) AS call_count, COALESCE(SUM(input_tokens), 0) AS input_tokens, "
            "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
            "COALESCE(SUM(total_tokens), 0) AS total_tokens, "
            "COALESCE(SUM(context_tokens), 0) AS context_tokens, "
            "COALESCE(SUM(estimated), 0) AS estimated_count "
            "FROM model_invocation_usage WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return SessionUsageAggregate(**dict(row))

    def record_guard_observation(
        self,
        run_id: str,
        *,
        kind: str,
        fingerprint: str,
        state_hash: str | None = None,
        error_code: str | None = None,
    ) -> int:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            sequence = self._connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM runtime_guard_observations "
                "WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            self._connection.execute(
                "INSERT INTO runtime_guard_observations "
                "(run_id, sequence, kind, fingerprint, state_hash, error_code) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, sequence, kind, fingerprint, state_hash, error_code),
            )
            self._connection.commit()
            return sequence
        except Exception:
            self._connection.rollback()
            raise

    def guard_state(self, run_id: str) -> GuardState:
        count = self._connection.execute(
            "SELECT COUNT(*) FROM runtime_guard_observations WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
        row = self._connection.execute(
            "SELECT sequence, fingerprint, state_hash FROM runtime_guard_observations "
            "WHERE run_id = ? ORDER BY sequence DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        return GuardState(
            observation_count=count,
            last_sequence=0 if row is None else row["sequence"],
            last_fingerprint=None if row is None else row["fingerprint"],
            last_state_hash=None if row is None else row["state_hash"],
        )

    def start_trace_segment(self, run_id: str, trace_id: str, span_id: str) -> int:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            sequence = self._connection.execute(
                "SELECT COALESCE(MAX(segment_sequence), 0) + 1 "
                "FROM runtime_trace_segments WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            self._connection.execute(
                "INSERT INTO runtime_trace_segments "
                "(run_id, segment_sequence, trace_id, span_id) VALUES (?, ?, ?, ?)",
                (run_id, sequence, trace_id, span_id),
            )
            self._connection.commit()
            return sequence
        except Exception:
            self._connection.rollback()
            raise

    def finish_trace_segment(self, run_id: str, segment_sequence: int) -> None:
        self._connection.execute(
            "UPDATE runtime_trace_segments SET finished_at = CURRENT_TIMESTAMP "
            "WHERE run_id = ? AND segment_sequence = ?",
            (run_id, segment_sequence),
        )
        self._connection.commit()

    def latest_trace_segment(self, run_id: str) -> TraceSegment | None:
        row = self._connection.execute(
            "SELECT * FROM runtime_trace_segments WHERE run_id = ? "
            "ORDER BY segment_sequence DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return TraceSegment(
            run_id=row["run_id"],
            segment_sequence=row["segment_sequence"],
            trace_id=row["trace_id"],
            span_id=row["span_id"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
        )
