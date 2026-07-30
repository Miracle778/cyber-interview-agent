from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol


class MetadataExporter(Protocol):
    def export(self, payload: dict[str, object]) -> None: ...


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    delivered: int
    skipped: int
    failed: int


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


class TraceMetadataProjector:
    """Fail-open, allowlist-only projection from local immutable metadata."""

    def __init__(
        self,
        *,
        connection,
        workspace_id: str,
        exporter: MetadataExporter,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.exporter = exporter

    def project_execution(self, run_id: str) -> ProjectionResult:
        execution = self.connection.execute(
            "SELECT run.id AS run_id, run.status, run.created_at, "
            "run.started_at, run.finished_at, run.error_code, "
            "session.id AS session_id, session.workspace_id, session.graph_id, "
            "COALESCE((SELECT SUM(total_tokens) FROM model_invocation_usage "
            "WHERE model_invocation_usage.run_id = run.id), 0) AS total_tokens, "
            "COALESCE((SELECT MAX(current_tokens) FROM agent_context_usage "
            "WHERE agent_context_usage.run_id = run.id), 0) AS context_tokens "
            "FROM agent_runs run JOIN agent_sessions session "
            "ON session.id = run.session_id "
            "WHERE run.id = ? AND session.workspace_id = ?",
            (run_id, self.workspace_id),
        ).fetchone()
        if execution is None:
            raise LookupError("execution not found")
        operations = self.connection.execute(
            "SELECT operation_id, kind, name, agent_role, status, started_at, "
            "finished_at, latency_ms, retry_count, error_code "
            "FROM agent_trace_operations WHERE run_id = ? ORDER BY operation_id",
            (run_id,),
        )
        payloads = [
            {
                "workspaceIdHash": _hash_identifier(execution["workspace_id"]),
                "runIdHash": _hash_identifier(execution["run_id"]),
                "sessionIdHash": _hash_identifier(execution["session_id"]),
                "graphId": execution["graph_id"],
                "executionStatus": execution["status"],
                "executionStartedAt": execution["started_at"],
                "executionFinishedAt": execution["finished_at"],
                "executionErrorCode": execution["error_code"],
                "totalTokens": int(execution["total_tokens"]),
                "contextTokens": int(execution["context_tokens"]),
                "operationIdHash": _hash_identifier(operation["operation_id"]),
                "operationKind": operation["kind"],
                "operationName": operation["name"],
                "agentRole": operation["agent_role"],
                "operationStatus": operation["status"],
                "operationStartedAt": operation["started_at"],
                "operationFinishedAt": operation["finished_at"],
                "latencyMs": operation["latency_ms"],
                "retryCount": operation["retry_count"],
                "errorCode": operation["error_code"],
            }
            for operation in operations
        ]
        payloads.extend(self._evaluation_payloads(run_id, execution))
        delivered = skipped = failed = 0
        for payload in payloads:
            payload_json = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            operation_hash = str(payload.get("operationIdHash") or "evaluation")
            key = f"{_hash_identifier(run_id)}:{operation_hash}:{payload_hash}"
            existing = self.connection.execute(
                "SELECT status FROM agent_trace_projection_deliveries "
                "WHERE delivery_key = ?",
                (key,),
            ).fetchone()
            if existing is not None and existing["status"] == "completed":
                skipped += 1
                continue
            self.connection.execute(
                "INSERT INTO agent_trace_projection_deliveries "
                "(delivery_key, workspace_id, run_id, operation_id, "
                "payload_hash, status, attempt_count) "
                "VALUES (?, ?, ?, ?, ?, 'pending', 1) "
                "ON CONFLICT(delivery_key) DO UPDATE SET "
                "status = 'pending', attempt_count = attempt_count + 1, "
                "updated_at = CURRENT_TIMESTAMP",
                (
                    key,
                    self.workspace_id,
                    run_id,
                    operation_hash,
                    payload_hash,
                ),
            )
            self.connection.commit()
            try:
                self.exporter.export(payload)
            except Exception:
                failed += 1
                self.connection.execute(
                    "UPDATE agent_trace_projection_deliveries "
                    "SET status = 'failed', error_code = 'otel_projection_failed', "
                    "updated_at = CURRENT_TIMESTAMP WHERE delivery_key = ?",
                    (key,),
                )
            else:
                delivered += 1
                self.connection.execute(
                    "UPDATE agent_trace_projection_deliveries "
                    "SET status = 'completed', error_code = NULL, "
                    "updated_at = CURRENT_TIMESTAMP WHERE delivery_key = ?",
                    (key,),
                )
            self.connection.commit()
        return ProjectionResult(delivered, skipped, failed)

    def _evaluation_payloads(self, run_id: str, execution):
        rows = self.connection.execute(
            "SELECT eval.eval_pack_id, eval.eval_pack_version, "
            "eval.judge_provider_model_id, dimension.dimension_id, "
            "dimension.source, dimension.status, dimension.score, "
            "dimension.confidence "
            "FROM agent_eval_runs eval JOIN agent_eval_dimension_results dimension "
            "ON dimension.eval_run_id = eval.id "
            "WHERE eval.workspace_id = ? AND eval.execution_id = ? "
            "ORDER BY eval.id, dimension.source, dimension.dimension_id",
            (self.workspace_id, run_id),
        )
        return [
            {
                "workspaceIdHash": _hash_identifier(execution["workspace_id"]),
                "runIdHash": _hash_identifier(execution["run_id"]),
                "sessionIdHash": _hash_identifier(execution["session_id"]),
                "graphId": execution["graph_id"],
                "evalPackId": row["eval_pack_id"],
                "evalPackVersion": row["eval_pack_version"],
                "judgeProviderModelId": row["judge_provider_model_id"],
                "dimensionId": row["dimension_id"],
                "dimensionSource": row["source"],
                "dimensionStatus": row["status"],
                "dimensionScore": row["score"],
                "dimensionConfidence": row["confidence"],
            }
            for row in rows
        ]
