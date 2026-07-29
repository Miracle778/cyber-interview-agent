from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.diagnostics.agent_trace import (
    AgentTraceWriter,
    TraceIdentity,
    initialize_agent_trace_directory,
)
from app.infrastructure.runtime_database import connect_runtime_database
from app.observability.indexer import TraceLedgerIndexer
from app.observability.repository import TraceIndexRepository


def _identity(root: Path) -> TraceIdentity:
    return TraceIdentity(
        workspace_id="workspace-1",
        workspace_root=root,
        session_id="session-1",
        run_id="run-1",
        agent_role="answer_evaluation",
        agent_name="review_answer_evaluation",
        invocation_id="invocation-1",
    )


def _indexer(root: Path) -> tuple[TraceLedgerIndexer, TraceIndexRepository]:
    connection = connect_runtime_database(root)
    repository = TraceIndexRepository(connection)
    return (
        TraceLedgerIndexer(
            workspace_id="workspace-1",
            workspace_root=root,
            repository=repository,
        ),
        repository,
    )


def _write_rows(root: Path, rows: list[dict], *, trailer: bytes = b"") -> Path:
    trace_root = initialize_agent_trace_directory(root)
    path = trace_root / "session-1" / "run-1.jsonl"
    path.parent.mkdir(mode=0o700)
    content = b"".join(
        (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        for row in rows
    )
    path.write_bytes(content + trailer)
    return path


def test_indexes_v2_rows_idempotently_and_grows_from_saved_offset(
    tmp_path: Path,
) -> None:
    writer = AgentTraceWriter()
    writer.append(_identity(tmp_path), "model.request", {"messages": ["hello"]})
    indexer, repository = _indexer(tmp_path)

    first = indexer.sync_workspace()
    repeated = indexer.sync_workspace()
    writer.append(_identity(tmp_path), "model.response", {"answer": "ok"})
    grown = indexer.sync_workspace()

    assert first.indexed_events == 1
    assert repeated.indexed_events == 0
    assert grown.indexed_events == 1
    execution = repository.get_execution("run-1")
    assert execution is not None
    assert execution["indexed_event_count"] == 2
    assert execution["trace_health"] == "complete"
    operations = repository.list_operations("run-1")
    assert [row["kind"] for row in operations] == ["execution", "agent", "model"]
    assert operations[2]["status"] == "completed"


def test_indexes_v3_parent_child_operation_without_rewriting_identity(
    tmp_path: Path,
) -> None:
    _write_rows(
        tmp_path,
        [
            {
                "schema_version": 3,
                "workspace_id": "workspace-1",
                "session_id": "session-1",
                "run_id": "run-1",
                "event_id": "event-1",
                "operation_id": "model-operation",
                "parent_operation_id": "agent-operation",
                "operation_kind": "model",
                "agent_role": "answer_evaluation",
                "agent_name": "answer_evaluation",
                "event_type": "model.request",
                "timestamp": "2026-07-29T12:00:00+00:00",
                "sequence": 1,
                "payload": {"messages": []},
            },
            {
                "schema_version": 3,
                "workspace_id": "workspace-1",
                "session_id": "session-1",
                "run_id": "run-1",
                "event_id": "event-2",
                "operation_id": "model-operation",
                "parent_operation_id": "agent-operation",
                "operation_kind": "model",
                "agent_role": "answer_evaluation",
                "agent_name": "answer_evaluation",
                "event_type": "model.response",
                "timestamp": "2026-07-29T12:00:01+00:00",
                "sequence": 2,
                "payload": {"answer": "ok"},
            },
        ],
    )
    indexer, repository = _indexer(tmp_path)

    indexer.sync_workspace()

    operations = {
        row["operation_id"]: row
        for row in repository.list_operations("run-1")
    }
    assert operations["model-operation"]["parent_operation_id"] == "agent-operation"
    assert operations["agent-operation"]["kind"] == "agent"
    assert operations["model-operation"]["status"] == "completed"


def test_waits_for_crash_torn_trailer_then_indexes_it_when_completed(
    tmp_path: Path,
) -> None:
    complete = {
        "schema_version": 2,
        "workspace_id": "workspace-1",
        "session_id": "session-1",
        "run_id": "run-1",
        "event_id": "event-1",
        "invocation_id": "invocation-1",
        "agent_role": "answer_evaluation",
        "agent_name": "answer_evaluation",
        "event_type": "model.request",
        "timestamp": "2026-07-29T12:00:00+00:00",
        "sequence": 1,
        "payload": {},
    }
    pending = {**complete, "event_id": "event-2", "sequence": 2}
    trailer = json.dumps(pending).encode("utf-8")
    path = _write_rows(tmp_path, [complete], trailer=trailer)
    indexer, repository = _indexer(tmp_path)

    first = indexer.sync_workspace()
    assert first.indexed_events == 1
    assert repository.get_file("session-1/run-1.jsonl")["health"] == "partial"

    with path.open("ab") as stream:
        stream.write(b"\n")
    second = indexer.sync_workspace()

    assert second.indexed_events == 1
    assert repository.get_execution("run-1")["indexed_event_count"] == 2
    assert repository.get_file("session-1/run-1.jsonl")["health"] == "complete"


def test_malformed_completed_row_becomes_gap_without_aborting_valid_rows(
    tmp_path: Path,
) -> None:
    valid = {
        "schema_version": 2,
        "workspace_id": "workspace-1",
        "session_id": "session-1",
        "run_id": "run-1",
        "event_id": "event-1",
        "invocation_id": "invocation-1",
        "event_type": "model.request",
        "timestamp": "2026-07-29T12:00:00+00:00",
        "sequence": 1,
        "payload": {},
    }
    path = _write_rows(tmp_path, [valid])
    with path.open("ab") as stream:
        stream.write(b"{not-json}\n")
    indexer, repository = _indexer(tmp_path)

    result = indexer.sync_workspace()

    assert result.indexed_events == 2
    assert result.malformed_rows == 1
    file_row = repository.get_file("session-1/run-1.jsonl")
    assert file_row["health"] == "partial"
    assert file_row["malformed_rows"] == 1
    events = repository.list_events("run-1")
    gap = events[-1]
    assert gap["event_type"] == "trace.index_gap"
    assert gap["payload_sha256"] == hashlib.sha256(b"{not-json}").hexdigest()


def test_missing_file_marks_trace_missing_without_deleting_metadata(
    tmp_path: Path,
) -> None:
    path = _write_rows(
        tmp_path,
        [
            {
                "schema_version": 1,
                "event_type": "model.request",
                "sequence": 1,
            }
        ],
    )
    indexer, repository = _indexer(tmp_path)
    indexer.sync_workspace()
    path.unlink()

    result = indexer.sync_workspace()

    assert result.missing_files == 1
    assert repository.get_file("session-1/run-1.jsonl")["health"] == "missing"
    assert repository.get_execution("run-1")["trace_health"] == "missing"
    assert repository.list_events("run-1")


def test_symlinked_trace_file_is_ignored_and_cannot_escape_workspace(
    tmp_path: Path,
) -> None:
    trace_root = initialize_agent_trace_directory(tmp_path)
    session = trace_root / "session-1"
    session.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text('{"event_type":"model.request"}\n', encoding="utf-8")
    (session / "run-1.jsonl").symlink_to(outside)
    indexer, repository = _indexer(tmp_path)

    result = indexer.sync_workspace()

    assert result.indexed_events == 0
    assert repository.get_execution("run-1") is None


def test_rebuild_replaces_only_trace_index_tables(tmp_path: Path) -> None:
    writer = AgentTraceWriter()
    writer.append(_identity(tmp_path), "model.request", {})
    indexer, repository = _indexer(tmp_path)
    indexer.sync_workspace()
    repository.connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('business-session', 'workspace-1', 'review.round', 1, 'Review')"
    )
    repository.connection.commit()

    rebuilt = indexer.rebuild_workspace()

    assert rebuilt.indexed_events == 1
    assert repository.get_execution("run-1")["indexed_event_count"] == 1
    assert (
        repository.connection.execute(
            "SELECT COUNT(*) FROM agent_sessions WHERE id = 'business-session'"
        ).fetchone()[0]
        == 1
    )
