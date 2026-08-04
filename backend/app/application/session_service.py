from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from app.agents.definition_snapshot import AgentDefinitionSnapshot

ExecutionStatus = Literal[
    "running",
    "waiting_for_input",
    "waiting_for_approval",
    "interrupted",
    "completed",
    "failed",
    "cancelled",
]
ReasoningEffort = Literal["none", "low", "medium", "high"]
MessageResolutionStatus = Literal[
    "active", "unresolved", "replaced", "abandoned"
]
MessageKind = Literal[
    "text",
    "stage",
    "curation_summary",
    "question_card",
    "review_prompt",
    "review_answer",
    "evaluation_card",
    "command_receipt",
    "claim_card",
    "proposal_card",
    "assessment_card",
    "action_plan_card",
    "receipt",
    "error",
]
_MESSAGE_KINDS = frozenset(
    {
        "text",
        "stage",
        "curation_summary",
        "question_card",
        "review_prompt",
        "review_answer",
        "evaluation_card",
        "command_receipt",
        "claim_card",
        "proposal_card",
        "assessment_card",
        "action_plan_card",
        "receipt",
        "error",
    }
)


class ProductRecordNotFoundError(RuntimeError):
    pass


class SessionBusyError(RuntimeError):
    pass


class InvalidExecutionTransitionError(RuntimeError):
    pass


def _is_transient_sqlite_lock(error: BaseException) -> bool:
    return isinstance(error, sqlite3.OperationalError) and any(
        marker in str(error).lower()
        for marker in ("database is locked", "database table is locked", "database is busy")
    )


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: str
    workspace_id: str
    kind: str
    title: str
    status: str
    created_at: str
    updated_at: str
    latest_execution_id: str | None
    deleted_at: str | None
    parent_session_id: str | None = None
    visibility: str = "user"
    last_message_preview: str | None = None
    latest_execution_status: str | None = None
    pending_action_count: int = 0
    graph_version: int = 1


@dataclass(frozen=True, slots=True)
class ExecutionConfiguration:
    provider_model_id: str | None = None
    reasoning_effort: ReasoningEffort = "none"


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    id: str
    session_id: str
    status: ExecutionStatus
    input: dict[str, Any]
    configuration: ExecutionConfiguration
    cancel_requested_at: str | None
    resume_count: int
    error_code: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    input_message_id: str | None = None
    retry_of_execution_id: str | None = None
    definition_snapshot: AgentDefinitionSnapshot = field(
        default_factory=AgentDefinitionSnapshot.legacy_snapshot
    )

    @property
    def cancellation_requested(self) -> bool:
        return self.cancel_requested_at is not None


@dataclass(frozen=True, slots=True)
class MessageRecord:
    id: str
    execution_id: str | None
    role: str
    content: str
    message_kind: MessageKind
    payload: dict[str, Any]
    created_at: str
    replaces_message_id: str | None = None
    resolution_status: MessageResolutionStatus = "active"


@dataclass(frozen=True, slots=True)
class EventRecord:
    id: int
    session_id: str
    execution_id: str | None
    type: str
    payload: dict[str, Any]
    created_at: str


class ProductRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_session(
        self,
        *,
        workspace_id: str,
        kind: str,
        title: str,
        title_source: str = "user",
        session_id: str | None = None,
        parent_session_id: str | None = None,
        visibility: str = "user",
    ) -> SessionRecord:
        session_id = session_id or str(uuid4())
        self.connection.execute(
            "INSERT INTO agent_sessions "
            "(id, workspace_id, graph_id, graph_version, title, title_source, "
            "parent_session_id, visibility) VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
            (
                session_id,
                workspace_id,
                kind,
                title,
                title_source,
                parent_session_id,
                visibility,
            ),
        )
        self.connection.commit()
        return self.get_session(session_id)

    def get_session(
        self, session_id: str, *, include_deleted: bool = False
    ) -> SessionRecord:
        row = self.connection.execute(
            "SELECT * FROM agent_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None or (row["deleted_at"] is not None and not include_deleted):
            raise ProductRecordNotFoundError("Agent Session 不存在")
        return _session(row)

    def list_sessions(
        self,
        workspace_id: str,
        *,
        include_system: bool = False,
        deleted_only: bool = False,
    ) -> tuple[SessionRecord, ...]:
        deletion_filter = (
            "agent_sessions.deleted_at IS NOT NULL"
            if deleted_only
            else "agent_sessions.deleted_at IS NULL"
        )
        select = (
            "SELECT agent_sessions.*, "
            "(SELECT content FROM agent_messages "
            "WHERE agent_messages.session_id = agent_sessions.id "
            "ORDER BY agent_messages.rowid DESC LIMIT 1) AS last_message_preview, "
            "(SELECT status FROM agent_runs "
            "WHERE agent_runs.id = agent_sessions.last_run_id) "
            "AS latest_execution_status, "
            "(SELECT COUNT(*) FROM pending_actions "
            "WHERE pending_actions.session_id = agent_sessions.id "
            "AND pending_actions.status = 'pending') AS pending_action_count "
            "FROM agent_sessions WHERE agent_sessions.workspace_id = ? "
        )
        if include_system:
            rows = self.connection.execute(
                select
                + f"AND {deletion_filter} "
                "ORDER BY agent_sessions.updated_at DESC, agent_sessions.rowid DESC",
                (workspace_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                select
                + f"AND {deletion_filter} AND agent_sessions.visibility = 'user' "
                "ORDER BY agent_sessions.updated_at DESC, agent_sessions.rowid DESC",
                (workspace_id,),
            ).fetchall()
        return tuple(_session(row) for row in rows)

    def update_session_title(self, session_id: str, title: str) -> SessionRecord:
        self.get_session(session_id)
        self.connection.execute(
            "UPDATE agent_sessions SET title = ?, title_source = 'user', "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (title, session_id),
        )
        self.connection.commit()
        return self.get_session(session_id)

    def delete_session(self, session_id: str, *, hard: bool = False) -> None:
        self.get_session(session_id, include_deleted=True)
        active = self.connection.execute(
            "SELECT COUNT(*) FROM agent_runs WHERE session_id = ? "
            "AND status IN ('queued', 'running', 'waiting_for_input', 'waiting_for_approval')",
            (session_id,),
        ).fetchone()[0]
        if active:
            raise SessionBusyError("会话仍在运行，请先结束任务")
        if not hard:
            self.connection.execute(
                "UPDATE agent_sessions SET deleted_at = CURRENT_TIMESTAMP, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,),
            )
            self.connection.commit()
            return
        self.connection.execute("DELETE FROM agent_sessions WHERE id = ?", (session_id,))
        self.connection.commit()

    def restore_session(self, session_id: str) -> SessionRecord:
        self.get_session(session_id, include_deleted=True)
        self.connection.execute(
            "UPDATE agent_sessions SET deleted_at = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (session_id,),
        )
        self.connection.commit()
        return self.get_session(session_id)

    def complete_idle_session(self, session_id: str) -> SessionRecord:
        current = self.get_session(session_id)
        if current.status == "completed":
            return current
        active = self.connection.execute(
            "SELECT 1 FROM agent_runs WHERE session_id = ? "
            "AND status IN ('queued', 'running', 'waiting_for_input', "
            "'waiting_for_approval') LIMIT 1",
            (session_id,),
        ).fetchone()
        if active is not None:
            raise SessionBusyError("会话仍在运行，不能直接完成")
        cursor = self.connection.execute(
            "UPDATE agent_sessions SET status = 'completed', "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = ?",
            (session_id, current.status),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise InvalidExecutionTransitionError(
                f"session {session_id} completion state changed"
            )
        self.connection.commit()
        return self.get_session(session_id)

    def create_execution(
        self,
        session_id: str,
        *,
        input: dict[str, Any],
        model_bindings: dict[str, str],
        configuration: dict[str, Any] | None = None,
        execution_id: str | None = None,
        input_message_id: str | None = None,
        retry_of_execution_id: str | None = None,
        definition_snapshot: AgentDefinitionSnapshot | None = None,
    ) -> ExecutionRecord:
        execution_id = execution_id or str(uuid4())
        if input_message_id is not None:
            row = self.connection.execute(
                "SELECT session_id FROM agent_messages WHERE id = ?",
                (input_message_id,),
            ).fetchone()
            if row is None or row["session_id"] != session_id:
                raise ValueError("input message must belong to the execution session")
        if retry_of_execution_id is not None:
            retry_parent = self.get_execution(retry_of_execution_id)
            if retry_parent.session_id != session_id:
                raise ValueError("retry execution must belong to the same session")
        try:
            self.connection.execute(
                "INSERT INTO agent_runs "
                "(id, session_id, status, input_json, model_bindings_json, "
                "configuration_json, started_at, input_message_id, "
                "retry_of_execution_id, agent_definition_snapshot_json) "
                "VALUES (?, ?, 'running', ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)",
                (
                    execution_id,
                    session_id,
                    _json(input),
                    _json(model_bindings),
                    _json(configuration or {}),
                    input_message_id,
                    retry_of_execution_id,
                    (definition_snapshot or AgentDefinitionSnapshot.legacy_snapshot()).to_json(),
                ),
            )
        except sqlite3.IntegrityError as error:
            self.connection.rollback()
            if "agent_runs.session_id" in str(error):
                raise SessionBusyError("当前 Session 已有运行中的任务") from error
            raise
        self.connection.execute(
            "UPDATE agent_sessions SET status = 'active', last_run_id = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (execution_id, session_id),
        )
        self.connection.commit()
        return self.get_execution(execution_id)

    def request_execution_cancel(self, execution_id: str) -> ExecutionRecord:
        current = self.get_execution(execution_id)
        if current.status in {"interrupted", "completed", "failed", "cancelled"}:
            return current
        self.connection.execute(
            "UPDATE agent_runs SET cancel_requested_at = "
            "COALESCE(cancel_requested_at, CURRENT_TIMESTAMP) WHERE id = ?",
            (execution_id,),
        )
        self.connection.commit()
        return self.get_execution(execution_id)

    def rearm_unscheduled_execution(self, execution_id: str) -> ExecutionRecord:
        current = self.get_execution(execution_id)
        if current.status not in {"running", "interrupted"}:
            raise InvalidExecutionTransitionError(
                f"execution {execution_id} cannot be re-armed from {current.status}"
            )
        self.connection.execute(
            "UPDATE agent_runs SET status = 'running', cancel_requested_at = NULL, "
            "error_code = NULL, error_message = NULL, started_at = CURRENT_TIMESTAMP, "
            "finished_at = NULL WHERE id = ? AND status IN ('running', 'interrupted')",
            (execution_id,),
        )
        self.connection.execute(
            "UPDATE agent_sessions SET status = 'active', last_run_id = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (execution_id, current.session_id),
        )
        self.connection.commit()
        return self.get_execution(execution_id)

    def get_execution(self, execution_id: str) -> ExecutionRecord:
        row = self.connection.execute(
            "SELECT * FROM agent_runs WHERE id = ?", (execution_id,)
        ).fetchone()
        if row is None:
            raise ProductRecordNotFoundError("Agent Execution 不存在")
        return _execution(row)

    def bind_execution_input_message(
        self, execution_id: str, message_id: str
    ) -> ExecutionRecord:
        execution = self.get_execution(execution_id)
        message = self.connection.execute(
            "SELECT session_id, role FROM agent_messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        if (
            message is None
            or message["session_id"] != execution.session_id
            or message["role"] != "user"
        ):
            raise ValueError("input message must belong to the execution session")
        self.connection.execute(
            "UPDATE agent_runs SET input_message_id = ? WHERE id = ?",
            (message_id, execution_id),
        )
        self.connection.commit()
        return self.get_execution(execution_id)

    def latest_execution(self, session_id: str) -> ExecutionRecord | None:
        row = self.connection.execute(
            "SELECT * FROM agent_runs WHERE session_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return None if row is None else _execution(row)

    def list_executions(self, session_id: str) -> tuple[ExecutionRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM agent_runs WHERE session_id = ? "
            "ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall()
        return tuple(_execution(row) for row in rows)

    def transition_execution(
        self,
        execution_id: str,
        *,
        expected: tuple[str, ...],
        target: ExecutionStatus,
        error_code: str | None = None,
        error_message: str | None = None,
        increment_resume: bool = False,
    ) -> ExecutionRecord:
        current = self.get_execution(execution_id)
        if current.status not in expected:
            raise InvalidExecutionTransitionError(
                f"execution {execution_id} cannot move from {current.status} to {target}"
            )
        terminal = target in {"interrupted", "completed", "failed", "cancelled"}
        self.connection.execute(
            "UPDATE agent_runs SET status = ?, error_code = ?, error_message = ?, "
            "resume_count = resume_count + ?, "
            "last_resumed_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE last_resumed_at END, "
            "finished_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END "
            "WHERE id = ?",
            (
                target,
                error_code,
                error_message,
                int(increment_resume),
                int(increment_resume),
                int(terminal),
                execution_id,
            ),
        )
        session_status = {
            "waiting_for_input": "waiting_for_input",
            "waiting_for_approval": "waiting_for_approval",
            "interrupted": "interrupted",
            "completed": "completed",
        }.get(target, "active")
        self.connection.execute(
            "UPDATE agent_sessions SET status = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (session_status, current.session_id),
        )
        self.connection.commit()
        return self.get_execution(execution_id)

    def interrupt_running(self) -> tuple[str, ...]:
        rows = self.connection.execute(
            "SELECT id FROM agent_runs WHERE status = 'running'"
        ).fetchall()
        ids = tuple(row[0] for row in rows)
        for execution_id in ids:
            current = self.get_execution(execution_id)
            self.transition_execution(
                execution_id,
                expected=("running",),
                target=("cancelled" if current.cancellation_requested else "interrupted"),
            )
        return ids

    def append_message(
        self,
        session_id: str,
        *,
        execution_id: str | None,
        role: str,
        content: str,
        message_kind: MessageKind = "text",
        payload: dict[str, Any] | None = None,
    ) -> MessageRecord:
        if message_kind not in _MESSAGE_KINDS:
            raise ValueError(f"unsupported message kind: {message_kind}")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("message payload must be an object")
        message_id = str(uuid4())
        safe_payload = payload or {}
        self.connection.execute(
            "INSERT INTO agent_messages "
            "(id, session_id, run_id, role, content, message_kind, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                message_id,
                session_id,
                execution_id,
                role,
                content,
                message_kind,
                _json(safe_payload),
            ),
        )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT * FROM agent_messages WHERE id = ?", (message_id,)
        ).fetchone()
        return _message(row)

    def append_user_message(
        self,
        session_id: str,
        *,
        content: str,
        replaces_message_id: str | None = None,
    ) -> MessageRecord:
        clean = content.strip()
        if not clean:
            raise ValueError("user message must not be empty")
        if replaces_message_id is not None:
            row = self.connection.execute(
                "SELECT session_id, resolution_status FROM agent_messages "
                "WHERE id = ? AND role = 'user'",
                (replaces_message_id,),
            ).fetchone()
            if row is None or row["session_id"] != session_id:
                raise ValueError("replaced message must belong to the same session")
            if row["resolution_status"] not in {"active", "unresolved"}:
                raise ValueError("message can no longer be replaced")
        message_id = str(uuid4())
        try:
            self.connection.execute(
                "INSERT INTO agent_messages "
                "(id, session_id, role, content, message_kind, payload_json, "
                "replaces_message_id, resolution_status) "
                "VALUES (?, ?, 'user', ?, 'text', '{}', ?, 'active')",
                (message_id, session_id, clean, replaces_message_id),
            )
            if replaces_message_id is not None:
                self.connection.execute(
                    "UPDATE agent_messages SET resolution_status = 'replaced' "
                    "WHERE id = ?",
                    (replaces_message_id,),
                )
            self.connection.execute(
                "UPDATE agent_sessions SET updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (session_id,),
            )
            self.connection.commit()
        except sqlite3.Error:
            self.connection.rollback()
            raise
        row = self.connection.execute(
            "SELECT * FROM agent_messages WHERE id = ?", (message_id,)
        ).fetchone()
        return _message(row)

    def resolve_message(
        self,
        message_id: str,
        *,
        expected: tuple[MessageResolutionStatus, ...],
        target: MessageResolutionStatus,
    ) -> MessageRecord:
        row = self.connection.execute(
            "SELECT resolution_status FROM agent_messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        if row is None:
            raise ProductRecordNotFoundError("Agent Message 不存在")
        if row["resolution_status"] not in expected:
            raise InvalidExecutionTransitionError(
                f"message {message_id} cannot move from "
                f"{row['resolution_status']} to {target}"
            )
        placeholders = ", ".join("?" for _ in expected)
        cursor = self.connection.execute(
            "UPDATE agent_messages SET resolution_status = ? WHERE id = ? "
            f"AND resolution_status IN ({placeholders})",
            (target, message_id, *expected),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise InvalidExecutionTransitionError(
                f"message {message_id} resolution state changed"
            )
        self.connection.commit()
        updated = self.connection.execute(
            "SELECT * FROM agent_messages WHERE id = ?", (message_id,)
        ).fetchone()
        return _message(updated)

    def list_messages(self, session_id: str) -> tuple[MessageRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM agent_messages WHERE session_id = ? ORDER BY rowid",
            (session_id,),
        ).fetchall()
        return tuple(_message(row) for row in rows)

    def append_event(
        self,
        session_id: str,
        execution_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> EventRecord:
        try:
            cursor = self.connection.execute(
                "INSERT INTO agent_events(session_id, run_id, type, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (session_id, execution_id, event_type, _json(payload)),
            )
            self.connection.commit()
        except sqlite3.Error:
            self.connection.rollback()
            raise
        return self.get_event(int(cursor.lastrowid))

    def get_event(self, event_id: int) -> EventRecord:
        row = self.connection.execute(
            "SELECT * FROM agent_events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise ProductRecordNotFoundError("产品事件不存在")
        return _event(row)

    def list_events(
        self, session_id: str, *, after_id: int | None
    ) -> tuple[EventRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM agent_events WHERE session_id = ? AND id > ? ORDER BY id",
            (session_id, after_id or 0),
        ).fetchall()
        return tuple(_event(row) for row in rows)

    def usage(self, session_id: str) -> dict[str, int]:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0), "
            "COALESCE(SUM(total_tokens), 0), COUNT(*), COALESCE(SUM(estimated), 0) "
            "FROM model_invocation_usage WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return {
            "inputTokens": row[0],
            "outputTokens": row[1],
            "totalTokens": row[2],
            "callCount": row[3],
            "estimatedCount": row[4],
        }

    def context_compacted(self, session_id: str) -> bool:
        row = self.connection.execute(
            "SELECT summary IS NOT NULL FROM agent_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise ProductRecordNotFoundError("Agent Session 不存在")
        return bool(row[0])

    def context_usage(self, session_id: str) -> dict[str, int | bool]:
        row = self.connection.execute(
            "SELECT current_tokens, threshold_tokens, estimated "
            "FROM agent_context_usage WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return {"currentTokens": 0, "thresholdTokens": 0, "estimated": True}
        return {
            "currentTokens": int(row[0]),
            "thresholdTokens": int(row[1]),
            "estimated": bool(row[2]),
        }

    def latest_warning(self, session_id: str) -> dict[str, str] | None:
        row = self.connection.execute(
            "SELECT code FROM runtime_warnings WHERE session_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return None if row is None else {"code": row[0], "message": row[0]}


class ProductEventStream:
    _allowed = frozenset(
        {
            "session.created",
            "session.renamed",
            "session.message.created",
            "curation.stage.changed",
            "curation.progress.changed",
            "curation.summary.ready",
            "curation.command.resolved",
            "curation.command.interpreting",
            "curation.control.changed",
            "curation.seed.changed",
            "execution.started",
            "execution.cancelling",
            "assistant.delta",
            "approval.required",
            "approval.resolved",
            "review.input.required",
            "review.input.resolved",
            "review.turn.responded",
            "review.answer.accepted",
            "review.evaluation.started",
            "review.evaluation.checking_key_points",
            "review.evaluation.deciding_follow_up",
            "review.evaluation.completed",
            "review.evaluation.failed",
            "review.attempt.completed",
            "review.progress.changed",
            "review.report.draft_created",
            "review.round.completed",
            "review.round.cancelled",
            "review.round.started",
            "review.round.failed",
            "artifact.changed",
            "publication.changed",
            "execution.warning",
            "execution.interrupted",
            "execution.completed",
            "execution.failed",
            "execution.cancelled",
            "agent.tool.started",
            "agent.tool.completed",
            "agent.tool.failed",
            "profile.ingest.parsing",
            "profile.ingest.extracting",
            "profile.claims.proposed",
            "profile.action_plan.created",
            "profile.action_plan.item_completed",
        }
    )

    def __init__(
        self,
        repository: ProductRepository,
        *,
        workspace_root: Path,
        keepalive_seconds: float = 15,
    ) -> None:
        self._repository = repository
        del workspace_root
        self._keepalive = keepalive_seconds
        self._conditions: dict[str, asyncio.Condition] = {}
        self._write_tasks: set[asyncio.Task[EventRecord]] = set()

    async def publish(
        self,
        session_id: str,
        execution_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> EventRecord:
        if event_type not in self._allowed:
            raise ValueError(f"unsupported product event: {event_type}")
        safe = _scrub(payload)
        for attempt in range(3):
            try:
                write_task = asyncio.create_task(
                    asyncio.to_thread(
                        self._repository.append_event,
                        session_id,
                        execution_id,
                        event_type,
                        safe,
                    )
                )
                self._write_tasks.add(write_task)
                write_task.add_done_callback(self._write_tasks.discard)
                event = await asyncio.shield(write_task)
                break
            except sqlite3.OperationalError as error:
                if not _is_transient_sqlite_lock(error) or attempt == 2:
                    raise
                await asyncio.sleep(0.05 * (attempt + 1))
        condition = self._conditions.setdefault(session_id, asyncio.Condition())
        async with condition:
            condition.notify_all()
        return event

    async def close(self) -> None:
        """Wait for worker-thread writes before the runtime closes SQLite."""

        while self._write_tasks:
            await asyncio.gather(*tuple(self._write_tasks), return_exceptions=True)

    async def subscribe(
        self, session_id: str, *, after_id: int | None
    ) -> AsyncIterator[EventRecord | None]:
        cursor = after_id or 0
        condition = self._conditions.setdefault(session_id, asyncio.Condition())
        while True:
            events = self._repository.list_events(session_id, after_id=cursor)
            if events:
                for event in events:
                    cursor = event.id
                    yield event
                continue
            async with condition:
                try:
                    await asyncio.wait_for(condition.wait(), timeout=self._keepalive)
                except TimeoutError:
                    yield None


class AgentSessionService:
    def __init__(self, repository: ProductRepository, events: ProductEventStream) -> None:
        self.repository = repository
        self.events = events

    async def create(
        self,
        *,
        workspace_id: str,
        kind: str,
        title: str | None,
        parent_session_id: str | None = None,
        session_id: str | None = None,
        visibility: str = "user",
    ) -> SessionRecord:
        clean_title = (title or "").strip()
        session = self.repository.create_session(
            workspace_id=workspace_id,
            kind=kind,
            title=clean_title or "新会话",
            title_source="user" if clean_title else "placeholder",
            parent_session_id=parent_session_id,
            session_id=session_id,
            visibility=visibility,
        )
        await self.events.publish(
            session.id, None, "session.created", {"title": session.title, "kind": kind}
        )
        return session

    def list(
        self, workspace_id: str, *, deleted_only: bool = False
    ) -> tuple[SessionRecord, ...]:
        return self.repository.list_sessions(workspace_id, deleted_only=deleted_only)

    def get(self, session_id: str) -> SessionRecord:
        return self.repository.get_session(session_id)

    def delete(self, session_id: str, *, hard: bool = False) -> None:
        self.repository.delete_session(session_id, hard=hard)

    def restore(self, session_id: str) -> SessionRecord:
        return self.repository.restore_session(session_id)

    async def rename(self, session_id: str, title: str) -> SessionRecord:
        session = self.repository.update_session_title(session_id, title)
        await self.events.publish(
            session.id, None, "session.renamed", {"title": session.title}
        )
        return session

    def complete_idle(self, session_id: str) -> SessionRecord:
        return self.repository.complete_idle_session(session_id)


def encode_sse_event(event: EventRecord) -> str:
    envelope = {
        "id": event.id,
        "sessionId": event.session_id,
        "executionId": event.execution_id,
        "type": event.type,
        "timestamp": event.created_at,
        "payload": event.payload,
    }
    return (
        f"id: {event.id}\nevent: {event.type}\n"
        f"data: {json.dumps(envelope, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _session(row) -> SessionRecord:
    row_keys = set(row.keys())
    return SessionRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        kind=row["graph_id"],
        title=row["title"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        latest_execution_id=row["last_run_id"],
        deleted_at=row["deleted_at"],
        parent_session_id=row["parent_session_id"],
        visibility=row["visibility"],
        last_message_preview=(
            row["last_message_preview"] if "last_message_preview" in row_keys else None
        ),
        latest_execution_status=(
            row["latest_execution_status"]
            if "latest_execution_status" in row_keys
            else None
        ),
        pending_action_count=(
            int(row["pending_action_count"])
            if "pending_action_count" in row_keys
            else 0
        ),
        graph_version=int(row["graph_version"]),
    )


def _execution(row) -> ExecutionRecord:
    raw_configuration = json.loads(row["configuration_json"])
    if not isinstance(raw_configuration, dict):
        raise ValueError("stored execution configuration must be an object")
    provider_model_id = raw_configuration.get("providerModelId")
    if provider_model_id is not None and not isinstance(provider_model_id, str):
        raise ValueError("stored provider model id must be a string")
    reasoning_effort = raw_configuration.get("reasoningEffort", "none")
    if reasoning_effort not in {"none", "low", "medium", "high"}:
        raise ValueError("stored reasoning effort is invalid")
    return ExecutionRecord(
        id=row["id"],
        session_id=row["session_id"],
        status=row["status"],
        input=json.loads(row["input_json"]),
        configuration=ExecutionConfiguration(
            provider_model_id=provider_model_id,
            reasoning_effort=reasoning_effort,
        ),
        cancel_requested_at=row["cancel_requested_at"],
        resume_count=row["resume_count"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        input_message_id=row["input_message_id"],
        retry_of_execution_id=row["retry_of_execution_id"],
        definition_snapshot=AgentDefinitionSnapshot.from_json(
            row["agent_definition_snapshot_json"]
            if "agent_definition_snapshot_json" in set(row.keys())
            else AgentDefinitionSnapshot.legacy_snapshot().to_json()
        ),
    )


def _event(row) -> EventRecord:
    return EventRecord(
        id=row["id"],
        session_id=row["session_id"],
        execution_id=row["run_id"],
        type=row["type"],
        payload=json.loads(row["payload_json"]),
        created_at=row["created_at"],
    )


def _message(row) -> MessageRecord:
    payload = json.loads(row["payload_json"])
    if not isinstance(payload, dict):
        raise ValueError("stored message payload must be an object")
    return MessageRecord(
        id=row["id"],
        execution_id=row["run_id"],
        role=row["role"],
        content=row["content"],
        message_kind=row["message_kind"],
        payload=payload,
        created_at=row["created_at"],
        replaces_message_id=row["replaces_message_id"],
        resolution_status=row["resolution_status"],
    )


_SECRET_KEYS = {"api_key", "apiKey", "secret", "authorization", "access_token"}


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items() if key not in _SECRET_KEYS}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value
