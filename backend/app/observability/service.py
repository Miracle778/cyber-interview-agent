from __future__ import annotations

import asyncio
import base64
import binascii
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any, AsyncIterator

from app.observability.content_reader import (
    InvalidTraceContentRangeError,
    TraceContentNotFoundError,
    TraceContentPage,
    TraceContentReader,
    TraceContentUnavailableError,
)
from app.observability.indexer import TraceLedgerIndexer, TraceSyncResult
from app.observability.export_service import (
    TraceExportConflictError,
    TraceExportGenerationError,
    TraceExportNotFoundError,
    TraceExportRecord,
    TraceExportService,
)
from app.observability.registry import AGENT_OBSERVABILITY_REGISTRY
from app.observability.repository import TraceIndexRepository
from app.observability.summary import ExecutionSummaryAssembler
from app.schemas.observability import (
    ExecutionSummaryPageResource,
    ExecutionSummaryResource,
    ExecutionChangedEventResource,
    OperationSummaryListResource,
)


class InvalidExecutionCursorError(ValueError):
    pass


class AgentExecutionNotFoundError(LookupError):
    pass


class AdvancedDiagnosticsDisabledError(RuntimeError):
    pass


class AgentObservabilityService:
    def __init__(
        self,
        *,
        workspace_id: str,
        workspace_root: Path | None = None,
        connection,
        trace_repository: TraceIndexRepository,
        indexer: TraceLedgerIndexer,
        advanced_diagnostics_enabled: Callable[[], bool] | None = None,
    ) -> None:
        self.workspace_id = workspace_id
        self.connection = connection
        self.trace_repository = trace_repository
        self.indexer = indexer
        self.advanced_diagnostics_enabled = (
            advanced_diagnostics_enabled or (lambda: False)
        )
        self.content_reader = TraceContentReader(
            workspace_id=workspace_id,
            workspace_root=workspace_root or indexer.workspace_root,
            repository=trace_repository,
        )
        self.export_service = TraceExportService(
            workspace_id=workspace_id,
            workspace_root=workspace_root or indexer.workspace_root,
            repository=trace_repository,
            content_reader=self.content_reader,
        )
        self.assembler = ExecutionSummaryAssembler(
            workspace_id=workspace_id,
            connection=connection,
            trace_repository=trace_repository,
        )
        self._sync_lock = threading.Lock()
        self._last_sync_at = 0.0

    def sync(self) -> TraceSyncResult:
        return self.indexer.sync_workspace()

    def sync_if_due(self, *, minimum_interval_seconds: float = 1.0) -> None:
        now = time.monotonic()
        if now - self._last_sync_at < minimum_interval_seconds:
            return
        with self._sync_lock:
            now = time.monotonic()
            if now - self._last_sync_at < minimum_interval_seconds:
                return
            self._last_sync_at = now
            try:
                self.indexer.sync_workspace()
            except Exception:
                # The trace index is diagnostic infrastructure. Business runs
                # remain queryable when indexing is temporarily unavailable.
                return

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
        if started_from is not None:
            _parse_time(started_from)
        if started_to is not None:
            _parse_time(started_to)
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

    def get_event_content(
        self,
        run_id: str,
        event_id: str,
        *,
        offset: int,
        limit: int,
    ) -> TraceContentPage:
        if not self.advanced_diagnostics_enabled():
            raise AdvancedDiagnosticsDisabledError(
                "advanced diagnostics are disabled"
            )
        self._run(run_id)
        return self.content_reader.read(
            run_id=run_id,
            event_id=event_id,
            offset=offset,
            limit=limit,
        )

    def create_export(
        self,
        run_id: str,
        *,
        idempotency_key: str,
        metadata_only: bool,
        include_stored_bodies: bool,
    ) -> TraceExportRecord:
        if metadata_only and include_stored_bodies:
            raise ValueError(
                "metadata-only exports cannot include stored bodies"
            )
        if include_stored_bodies and not self.advanced_diagnostics_enabled():
            raise AdvancedDiagnosticsDisabledError(
                "advanced diagnostics are disabled"
            )
        execution = self.get_execution(run_id)
        operations = self.list_operations(run_id)
        events = list(self.trace_repository.list_events(run_id))
        return self.export_service.create(
            run_id=run_id,
            idempotency_key=idempotency_key,
            metadata_only=metadata_only,
            include_stored_bodies=include_stored_bodies,
            execution=execution.model_dump(by_alias=True, mode="json"),
            operations=[
                item.model_dump(by_alias=True, mode="json")
                for item in operations.items
            ],
            events=events,
        )

    def get_export(self, export_id: str) -> TraceExportRecord:
        return self.export_service.get(export_id)

    def get_export_artifact(self, export_id: str) -> Path:
        return self.export_service.artifact(export_id)

    def replay_changes(
        self, *, after_event_id: int | None
    ) -> tuple[ExecutionChangedEventResource, ...]:
        rows = self.connection.execute(
            "SELECT MAX(event.id) AS event_id, event.run_id "
            "FROM agent_events event "
            "JOIN agent_sessions session ON session.id = event.session_id "
            "WHERE session.workspace_id = ? AND event.id > ? "
            "AND event.run_id IS NOT NULL "
            "GROUP BY event.run_id ORDER BY event_id",
            (self.workspace_id, after_event_id or 0),
        ).fetchall()
        changes: list[ExecutionChangedEventResource] = []
        for row in rows:
            try:
                execution = self.get_execution(row["run_id"])
            except AgentExecutionNotFoundError:
                continue
            changes.append(
                ExecutionChangedEventResource(
                    event_id=str(row["event_id"]),
                    execution=execution,
                )
            )
        return tuple(changes)

    async def changes(
        self,
        *,
        after_event_id: int | None,
        poll_interval_seconds: float = 0.25,
        keepalive_seconds: float = 15.0,
    ) -> AsyncIterator[ExecutionChangedEventResource | None]:
        cursor = after_event_id
        next_keepalive = time.monotonic() + keepalive_seconds
        while True:
            self.sync_if_due()
            changes = self.replay_changes(after_event_id=cursor)
            if changes:
                for change in changes:
                    cursor = int(change.event_id)
                    yield change
                next_keepalive = time.monotonic() + keepalive_seconds
                continue
            now = time.monotonic()
            if now >= next_keepalive:
                yield None
                next_keepalive = now + keepalive_seconds
            await asyncio.sleep(poll_interval_seconds)

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
        result = dict(row)
        registration = AGENT_OBSERVABILITY_REGISTRY.get(result["graph_id"])
        if registration is None or not registration.run_center_visible:
            raise AgentExecutionNotFoundError("Agent Execution 不存在")
        return result

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
        if registration is None or not registration.run_center_visible:
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
