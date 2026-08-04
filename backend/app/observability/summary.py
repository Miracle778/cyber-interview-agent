from __future__ import annotations

from datetime import datetime
from typing import Any

from app.observability.models import ObservabilityCapability, TraceHealth
from app.agents.definition_registry import (
    AgentDefinition,
    resolve_agent_definition,
)
from app.observability.repository import TraceIndexRepository
from app.schemas.observability import (
    AgentDefinitionSnapshotResource,
    ExecutionDetailResource,
    ExecutionSummaryResource,
    OperationSummaryResource,
)
from app.agents.definition_snapshot import AgentDefinitionSnapshot


class ExecutionSummaryAssembler:
    """Merge domain/runtime truth with metadata-only trace projections."""

    def __init__(
        self,
        *,
        workspace_id: str,
        connection,
        trace_repository: TraceIndexRepository,
    ) -> None:
        self.workspace_id = workspace_id
        self.connection = connection
        self.trace_repository = trace_repository

    def assemble(self, run: dict[str, Any]) -> ExecutionSummaryResource:
        registration = resolve_agent_definition(
            run["graph_id"], include_historical=True
        )
        assert registration is not None
        trace = self.trace_repository.get_execution(run["id"])
        operations = self.trace_repository.list_operations(run["id"])
        usage = self._usage(run["id"])
        context = self._context_usage(run["id"])
        trace_health = (
            TraceHealth.MISSING if trace is None else TraceHealth(trace["trace_health"])
        )
        model_call_count = sum(
            1 for operation in operations if operation["kind"] == "model"
        )
        system_operation_count = sum(
            1 for operation in operations if operation["kind"] != "execution"
        )
        retry_count = sum(int(operation["retry_count"]) for operation in operations)
        latency_ms = self._latency_ms(trace, operations)
        return ExecutionSummaryResource(
            id=run["id"],
            session_id=run["session_id"],
            workspace_id=self.workspace_id,
            graph_id=run["graph_id"],
            display_name=registration.display_name,
            system=registration.system,
            title=run["title"],
            status=run["status"],
            trace_health=trace_health,
            capabilities=_runtime_capabilities(
                registration,
                status=run["status"],
                trace_health=trace_health,
            ),
            route=registration.route_template,
            system_operation_count=system_operation_count,
            model_call_count=model_call_count,
            total_tokens=usage["total_tokens"],
            context_current_tokens=context["current_tokens"],
            context_threshold_tokens=context["threshold_tokens"],
            latency_ms=latency_ms,
            retry_count=retry_count,
            created_at=run["created_at"],
            started_at=run["started_at"],
            finished_at=run["finished_at"],
            error_code=run["error_code"],
        )

    def assemble_detail(self, run: dict[str, Any]) -> ExecutionDetailResource:
        summary = self.assemble(run)
        raw_snapshot = run.get("agent_definition_snapshot_json")
        snapshot = AgentDefinitionSnapshot.from_json(
            raw_snapshot
            if isinstance(raw_snapshot, str)
            else AgentDefinitionSnapshot.legacy_snapshot().to_json()
        )
        return ExecutionDetailResource(
            **summary.model_dump(),
            definition_snapshot=AgentDefinitionSnapshotResource(
                **snapshot.to_payload()
            ),
        )

    def operations(self, run_id: str) -> tuple[OperationSummaryResource, ...]:
        return tuple(
            OperationSummaryResource(
                id=row["operation_id"],
                run_id=row["run_id"],
                parent_operation_id=row["parent_operation_id"],
                kind=row["kind"],
                name=row["name"],
                agent_role=row["agent_role"],
                status=row["status"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                latency_ms=row["latency_ms"],
                retry_count=row["retry_count"],
                error_code=row["error_code"],
                event_count=row["event_count"],
            )
            for row in self.trace_repository.list_operations(run_id)
        )

    def _usage(self, run_id: str) -> dict[str, int]:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) AS total_tokens "
            "FROM model_invocation_usage WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return {"total_tokens": int(row["total_tokens"])}

    def _context_usage(self, run_id: str) -> dict[str, int]:
        row = self.connection.execute(
            "SELECT current_tokens, threshold_tokens FROM agent_context_usage "
            "WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return {"current_tokens": 0, "threshold_tokens": 0}
        return {
            "current_tokens": int(row["current_tokens"]),
            "threshold_tokens": int(row["threshold_tokens"]),
        }

    @staticmethod
    def _latency_ms(
        trace: dict[str, Any] | None,
        operations: tuple[dict[str, Any], ...],
    ) -> int | None:
        execution = next(
            (operation for operation in operations if operation["kind"] == "execution"),
            None,
        )
        if execution is not None and execution["latency_ms"] is not None:
            return int(execution["latency_ms"])
        if trace is None:
            return None
        return _elapsed_ms(trace["first_event_at"], trace["last_event_at"])


def _runtime_capabilities(
    registration: AgentDefinition,
    *,
    status: str,
    trace_health: TraceHealth,
) -> list[ObservabilityCapability]:
    available = set(registration.capabilities)
    if status not in {
        "queued",
        "running",
        "waiting_for_input",
        "waiting_for_approval",
    }:
        available.discard("cancel")
    if status != "interrupted":
        available.discard("resume")
    if status not in {"failed", "cancelled", "interrupted"}:
        available.discard("retry")
    if status != "completed":
        available.discard("manual_judge")
    if trace_health not in {TraceHealth.COMPLETE, TraceHealth.PARTIAL}:
        available.discard("export_trace")
    order: tuple[ObservabilityCapability, ...] = (
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
    )
    return [capability for capability in order if capability in available]


def _elapsed_ms(started_at: str | None, finished_at: str | None) -> int | None:
    if not started_at or not finished_at:
        return None
    try:
        delta = datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
    except ValueError:
        return None
    return max(int(delta.total_seconds() * 1000), 0)
