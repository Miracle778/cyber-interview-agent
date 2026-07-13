from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

ExecutionStatus = Literal[
    "running",
    "waiting_for_approval",
    "interrupted",
    "completed",
    "failed",
    "cancelled",
]


class ProductRecordNotFoundError(RuntimeError):
    pass


class SessionBusyError(RuntimeError):
    pass


class InvalidExecutionTransitionError(RuntimeError):
    pass


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


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    id: str
    session_id: str
    status: ExecutionStatus
    input: dict[str, Any]
    resume_count: int
    error_code: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class MessageRecord:
    id: str
    execution_id: str | None
    role: str
    content: str
    created_at: str


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
    ) -> SessionRecord:
        session_id = session_id or str(uuid4())
        self.connection.execute(
            "INSERT INTO agent_sessions "
            "(id, workspace_id, graph_id, graph_version, title, title_source) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (session_id, workspace_id, kind, title, title_source),
        )
        self.connection.commit()
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> SessionRecord:
        row = self.connection.execute(
            "SELECT * FROM agent_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise ProductRecordNotFoundError("Agent Session 不存在")
        return _session(row)

    def list_sessions(self, workspace_id: str) -> tuple[SessionRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM agent_sessions WHERE workspace_id = ? "
            "ORDER BY updated_at DESC, rowid DESC",
            (workspace_id,),
        ).fetchall()
        return tuple(_session(row) for row in rows)

    def create_execution(
        self,
        session_id: str,
        *,
        input: dict[str, Any],
        model_bindings: dict[str, str],
        execution_id: str | None = None,
    ) -> ExecutionRecord:
        execution_id = execution_id or str(uuid4())
        try:
            self.connection.execute(
                "INSERT INTO agent_runs "
                "(id, session_id, status, input_json, model_bindings_json, started_at) "
                "VALUES (?, ?, 'running', ?, ?, CURRENT_TIMESTAMP)",
                (
                    execution_id,
                    session_id,
                    _json(input),
                    _json(model_bindings),
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

    def get_execution(self, execution_id: str) -> ExecutionRecord:
        row = self.connection.execute(
            "SELECT * FROM agent_runs WHERE id = ?", (execution_id,)
        ).fetchone()
        if row is None:
            raise ProductRecordNotFoundError("Agent Execution 不存在")
        return _execution(row)

    def latest_execution(self, session_id: str) -> ExecutionRecord | None:
        row = self.connection.execute(
            "SELECT * FROM agent_runs WHERE session_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return None if row is None else _execution(row)

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
        terminal = target in {"completed", "failed", "cancelled"}
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
            self.transition_execution(
                execution_id, expected=("running",), target="interrupted"
            )
        return ids

    def append_message(
        self,
        session_id: str,
        *,
        execution_id: str | None,
        role: str,
        content: str,
    ) -> MessageRecord:
        message_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO agent_messages(id, session_id, run_id, role, content) "
            "VALUES (?, ?, ?, ?, ?)",
            (message_id, session_id, execution_id, role, content),
        )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT * FROM agent_messages WHERE id = ?", (message_id,)
        ).fetchone()
        return MessageRecord(
            id=row["id"],
            execution_id=row["run_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
        )

    def list_messages(self, session_id: str) -> tuple[MessageRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM agent_messages WHERE session_id = ? ORDER BY rowid",
            (session_id,),
        ).fetchall()
        return tuple(
            MessageRecord(
                id=row["id"],
                execution_id=row["run_id"],
                role=row["role"],
                content=row["content"],
                created_at=row["created_at"],
            )
            for row in rows
        )

    def append_event(
        self,
        session_id: str,
        execution_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> EventRecord:
        cursor = self.connection.execute(
            "INSERT INTO agent_events(session_id, run_id, type, payload_json) "
            "VALUES (?, ?, ?, ?)",
            (session_id, execution_id, event_type, _json(payload)),
        )
        self.connection.commit()
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
            "execution.started",
            "assistant.delta",
            "approval.required",
            "approval.resolved",
            "artifact.changed",
            "publication.changed",
            "execution.warning",
            "execution.interrupted",
            "execution.completed",
            "execution.failed",
            "execution.cancelled",
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
        event = self._repository.append_event(
            session_id, execution_id, event_type, safe
        )
        condition = self._conditions.setdefault(session_id, asyncio.Condition())
        async with condition:
            condition.notify_all()
        return event

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
        self, *, workspace_id: str, kind: str, title: str | None
    ) -> SessionRecord:
        clean_title = (title or "").strip()
        session = self.repository.create_session(
            workspace_id=workspace_id,
            kind=kind,
            title=clean_title or "新会话",
            title_source="user" if clean_title else "placeholder",
        )
        await self.events.publish(
            session.id, None, "session.created", {"title": session.title, "kind": kind}
        )
        return session

    def list(self, workspace_id: str) -> tuple[SessionRecord, ...]:
        return self.repository.list_sessions(workspace_id)

    def get(self, session_id: str) -> SessionRecord:
        return self.repository.get_session(session_id)


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
    return SessionRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        kind=row["graph_id"],
        title=row["title"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        latest_execution_id=row["last_run_id"],
    )


def _execution(row) -> ExecutionRecord:
    return ExecutionRecord(
        id=row["id"],
        session_id=row["session_id"],
        status=row["status"],
        input=json.loads(row["input_json"]),
        resume_count=row["resume_count"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
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


_SECRET_KEYS = {"api_key", "apiKey", "secret", "authorization", "access_token"}


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items() if key not in _SECRET_KEYS}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value
