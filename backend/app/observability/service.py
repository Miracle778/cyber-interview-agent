from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Any

from app.observability.indexer import TraceLedgerIndexer, TraceSyncResult
from app.observability.registry import AGENT_OBSERVABILITY_REGISTRY
from app.observability.repository import TraceIndexRepository
from app.observability.summary import ExecutionSummaryAssembler
from app.schemas.observability import (
    ExecutionSummaryPageResource,
    ExecutionSummaryResource,
    OperationSummaryListResource,
)


class InvalidExecutionCursorError(ValueError):
    pass


class AgentExecutionNotFoundError(LookupError):
    pass


class AgentObservabilityService:
    def __init__(
        self,
        *,
        workspace_id: str,
        connection,
        trace_repository: TraceIndexRepository,
        indexer: TraceLedgerIndexer,
    ) -> None:
        self.workspace_id = workspace_id
        self.connection = connection
        self.trace_repository = trace_repository
        self.indexer = indexer
        self.assembler = ExecutionSummaryAssembler(
            workspace_id=workspace_id,
            connection=connection,
            trace_repository=trace_repository,
        )

    def sync(self) -> TraceSyncResult:
        return self.indexer.sync_workspace()

    def list_executions(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        agent: str | None = None,
        started_from: str | None = None,
        started_to: str | None = None,
        include_system_agents: bool = False,
        cursor: str | None = None,
        limit: int = 50,
    ) -> ExecutionSummaryPageResource:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        cursor_value = _decode_cursor(cursor) if cursor is not None else None
        rows = [
            dict(row)
            for row in self.connection.execute(
                "SELECT run.*, session.workspace_id, session.graph_id, "
                "session.title, session.visibility "
                "FROM agent_runs run JOIN agent_sessions session "
                "ON session.id = run.session_id "
                "WHERE session.workspace_id = ? "
                "ORDER BY run.created_at DESC, run.id DESC",
                (self.workspace_id,),
            )
        ]
        filtered = [
            row
            for row in rows
            if self._matches(
                row,
                keyword=keyword,
                status=status,
                agent=agent,
                started_from=started_from,
                started_to=started_to,
                include_system_agents=include_system_agents,
            )
        ]
        total = len(filtered)
        if cursor_value is not None:
            filtered = [
                row
                for row in filtered
                if (row["created_at"], row["id"]) < cursor_value
            ]
        selected = filtered[:limit]
        next_cursor = (
            _encode_cursor(selected[-1]["created_at"], selected[-1]["id"])
            if len(filtered) > limit
            else None
        )
        return ExecutionSummaryPageResource(
            items=[self.assembler.assemble(row) for row in selected],
            next_cursor=next_cursor,
            total=total,
        )

    def get_execution(self, run_id: str) -> ExecutionSummaryResource:
        row = self._run(run_id)
        return self.assembler.assemble(row)

    def list_operations(self, run_id: str) -> OperationSummaryListResource:
        self._run(run_id)
        return OperationSummaryListResource(
            items=list(self.assembler.operations(run_id))
        )

    def _run(self, run_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT run.*, session.workspace_id, session.graph_id, "
            "session.title, session.visibility "
            "FROM agent_runs run JOIN agent_sessions session "
            "ON session.id = run.session_id "
            "WHERE run.id = ? AND session.workspace_id = ?",
            (run_id, self.workspace_id),
        ).fetchone()
        if row is None:
            raise AgentExecutionNotFoundError("Agent Execution 不存在")
        return dict(row)

    @staticmethod
    def _matches(
        row: dict[str, Any],
        *,
        keyword: str | None,
        status: str | None,
        agent: str | None,
        started_from: str | None,
        started_to: str | None,
        include_system_agents: bool,
    ) -> bool:
        registration = AGENT_OBSERVABILITY_REGISTRY.get(row["graph_id"])
        if registration is None:
            return False
        if not include_system_agents and (
            registration.system or row["visibility"] == "system"
        ):
            return False
        if status and row["status"] != status:
            return False
        if agent:
            normalized_agent = agent.casefold()
            if normalized_agent not in {
                row["graph_id"].casefold(),
                registration.display_name.casefold(),
            }:
                return False
        if keyword:
            haystack = " ".join(
                (
                    row["title"],
                    row["graph_id"],
                    registration.display_name,
                )
            ).casefold()
            if keyword.casefold().strip() not in haystack:
                return False
        started_at = row["started_at"] or row["created_at"]
        if started_from and _parse_time(started_at) < _parse_time(started_from):
            return False
        if started_to and _parse_time(started_at) > _parse_time(started_to):
            return False
        return True


def _encode_cursor(created_at: str, run_id: str) -> str:
    payload = json.dumps(
        {"createdAt": created_at, "id": run_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
        )
        created_at = payload["createdAt"]
        run_id = payload["id"]
    except (
        ValueError,
        UnicodeDecodeError,
        KeyError,
        TypeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as error:
        raise InvalidExecutionCursorError("invalid execution cursor") from error
    if not isinstance(created_at, str) or not isinstance(run_id, str):
        raise InvalidExecutionCursorError("invalid execution cursor")
    return created_at, run_id


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid execution time filter") from error
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
