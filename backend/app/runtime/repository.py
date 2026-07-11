import json
import sqlite3
from collections.abc import Callable
from typing import Any, TypeVar, cast
from uuid import uuid4

from app.runtime.models import (
    EventRecord,
    MessageRecord,
    MessageRole,
    RunRecord,
    RunStatus,
    SessionRecord,
    SessionStatus,
)


class RuntimeRepositoryError(RuntimeError):
    pass


class RuntimeRecordNotFoundError(RuntimeRepositoryError):
    pass


class SessionBusyError(RuntimeRepositoryError):
    pass


class InvalidRunTransitionError(RuntimeRepositoryError):
    pass


_T = TypeVar("_T")


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class RuntimeRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def _transaction(self, operation: Callable[[], _T]) -> _T:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
            self._connection.commit()
            return result
        except Exception:
            self._connection.rollback()
            raise

    def create_session(
        self,
        *,
        workspace_id: str,
        graph_id: str,
        graph_version: int,
        title: str,
        parent_session_id: str | None = None,
        session_id: str | None = None,
    ) -> SessionRecord:
        record_id = session_id or str(uuid4())

        def insert() -> SessionRecord:
            self._connection.execute(
                "INSERT INTO agent_sessions "
                "(id, workspace_id, graph_id, graph_version, title, parent_session_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record_id,
                    workspace_id,
                    graph_id,
                    graph_version,
                    title,
                    parent_session_id,
                ),
            )
            return self._require_session(record_id)

        return self._transaction(insert)

    def get_session(self, session_id: str) -> SessionRecord:
        return self._require_session(session_id)

    def create_run(
        self,
        session_id: str,
        *,
        input: dict[str, Any],
        model_bindings: dict[str, str],
        run_id: str | None = None,
    ) -> RunRecord:
        record_id = run_id or str(uuid4())

        def insert() -> RunRecord:
            self._require_session(session_id)
            try:
                self._connection.execute(
                    "INSERT INTO agent_runs "
                    "(id, session_id, input_json, model_bindings_json) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        record_id,
                        session_id,
                        _canonical_json(input),
                        _canonical_json(model_bindings),
                    ),
                )
            except sqlite3.IntegrityError as error:
                if "agent_runs.session_id" in str(error):
                    raise SessionBusyError(
                        f"session {session_id!r} already has an active run"
                    ) from error
                raise
            self._connection.execute(
                "UPDATE agent_sessions SET last_run_id = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (record_id, session_id),
            )
            return self._require_run(record_id)

        return self._transaction(insert)

    def get_run(self, run_id: str) -> RunRecord:
        return self._require_run(run_id)

    def transition_run(
        self,
        run_id: str,
        *,
        expected: RunStatus,
        target: RunStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> RunRecord:
        def transition() -> RunRecord:
            current = self._require_run(run_id)
            if current.status != expected:
                raise InvalidRunTransitionError(
                    f"run {run_id!r} expected {expected!r}, got {current.status!r}"
                )
            started_at_sql = (
                "COALESCE(started_at, CURRENT_TIMESTAMP)"
                if target == "running"
                else "started_at"
            )
            finished_at_sql = (
                "CURRENT_TIMESTAMP"
                if target in {"completed", "failed", "cancelled"}
                else "finished_at"
            )
            cursor = self._connection.execute(
                "UPDATE agent_runs SET status = ?, error_code = ?, "
                f"error_message = ?, started_at = {started_at_sql}, "
                f"finished_at = {finished_at_sql} WHERE id = ? AND status = ?",
                (target, error_code, error_message, run_id, expected),
            )
            if cursor.rowcount != 1:
                raise InvalidRunTransitionError(
                    f"run {run_id!r} changed during transition"
                )
            session_status = self._session_status_for_run(target)
            self._connection.execute(
                "UPDATE agent_sessions SET status = ?, last_run_id = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_status, run_id, current.session_id),
            )
            return self._require_run(run_id)

        return self._transaction(transition)

    def resume_run(self, run_id: str, *, expected: RunStatus) -> RunRecord:
        def resume() -> RunRecord:
            current = self._require_run(run_id)
            if current.status != expected:
                raise InvalidRunTransitionError(
                    f"run {run_id!r} expected {expected!r}, got {current.status!r}"
                )
            self._connection.execute(
                "UPDATE agent_runs SET status = 'queued', "
                "resume_count = resume_count + 1, "
                "last_resumed_at = CURRENT_TIMESTAMP, error_code = NULL, "
                "error_message = NULL, finished_at = NULL "
                "WHERE id = ? AND status = ?",
                (run_id, expected),
            )
            self._connection.execute(
                "UPDATE agent_sessions SET status = 'active', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (current.session_id,),
            )
            return self._require_run(run_id)

        return self._transaction(resume)

    def interrupt_running_runs(self) -> tuple[str, ...]:
        def interrupt() -> tuple[str, ...]:
            rows = self._connection.execute(
                "SELECT id, session_id FROM agent_runs WHERE status = 'running' "
                "ORDER BY created_at, id"
            ).fetchall()
            if not rows:
                return ()
            run_ids = tuple(row["id"] for row in rows)
            self._connection.executemany(
                "UPDATE agent_runs SET status = 'interrupted' WHERE id = ?",
                ((run_id,) for run_id in run_ids),
            )
            self._connection.executemany(
                "UPDATE agent_sessions SET status = 'interrupted', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ((row["session_id"],) for row in rows),
            )
            return run_ids

        return self._transaction(interrupt)

    def append_message(
        self,
        session_id: str,
        *,
        run_id: str | None,
        role: MessageRole,
        content: str,
        message_id: str | None = None,
    ) -> MessageRecord:
        record_id = message_id or str(uuid4())

        def insert() -> MessageRecord:
            self._connection.execute(
                "INSERT INTO agent_messages "
                "(id, session_id, run_id, role, content) VALUES (?, ?, ?, ?, ?)",
                (record_id, session_id, run_id, role, content),
            )
            return self._require_message(record_id)

        return self._transaction(insert)

    def list_messages(self, session_id: str) -> tuple[MessageRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM agent_messages WHERE session_id = ? ORDER BY rowid",
            (session_id,),
        ).fetchall()
        return tuple(self._message_from_row(row) for row in rows)

    def append_event(
        self,
        session_id: str,
        run_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> EventRecord:
        def insert() -> EventRecord:
            cursor = self._connection.execute(
                "INSERT INTO agent_events "
                "(session_id, run_id, type, payload_json) VALUES (?, ?, ?, ?)",
                (session_id, run_id, event_type, _canonical_json(payload)),
            )
            return self._require_event(cast(int, cursor.lastrowid))

        return self._transaction(insert)

    def get_event(self, event_id: int) -> EventRecord:
        return self._require_event(event_id)

    def list_events(
        self, session_id: str, *, after_id: int | None = None
    ) -> tuple[EventRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM agent_events WHERE session_id = ? AND id > ? ORDER BY id",
            (session_id, after_id or 0),
        ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def _require_session(self, session_id: str) -> SessionRecord:
        row = self._connection.execute(
            "SELECT * FROM agent_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise RuntimeRecordNotFoundError(f"session {session_id!r} not found")
        return self._session_from_row(row)

    def _require_run(self, run_id: str) -> RunRecord:
        row = self._connection.execute(
            "SELECT * FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RuntimeRecordNotFoundError(f"run {run_id!r} not found")
        return self._run_from_row(row)

    def _require_message(self, message_id: str) -> MessageRecord:
        row = self._connection.execute(
            "SELECT * FROM agent_messages WHERE id = ?", (message_id,)
        ).fetchone()
        if row is None:
            raise RuntimeRecordNotFoundError(f"message {message_id!r} not found")
        return self._message_from_row(row)

    def _require_event(self, event_id: int) -> EventRecord:
        row = self._connection.execute(
            "SELECT * FROM agent_events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise RuntimeRecordNotFoundError(f"event {event_id!r} not found")
        return self._event_from_row(row)

    def _session_status_for_run(self, status: RunStatus) -> SessionStatus:
        if status == "waiting_for_approval":
            return "waiting_for_approval"
        if status == "interrupted":
            return "interrupted"
        return "active"

    def _session_from_row(self, row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            graph_id=row["graph_id"],
            graph_version=row["graph_version"],
            title=row["title"],
            status=row["status"],
            parent_session_id=row["parent_session_id"],
            summary=row["summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_run_id=row["last_run_id"],
        )

    def _run_from_row(self, row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            id=row["id"],
            session_id=row["session_id"],
            status=row["status"],
            input=json.loads(row["input_json"]),
            model_bindings=json.loads(row["model_bindings_json"]),
            resume_count=row["resume_count"],
            last_resumed_at=row["last_resumed_at"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    def _message_from_row(self, row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(
            id=row["id"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
        )

    def _event_from_row(self, row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            id=row["id"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            type=row["type"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
        )
