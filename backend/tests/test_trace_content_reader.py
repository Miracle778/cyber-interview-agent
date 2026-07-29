from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.diagnostics.agent_trace import initialize_agent_trace_directory
from app.infrastructure.runtime_database import connect_runtime_database
from app.observability.indexer import TraceLedgerIndexer
from app.observability.repository import TraceIndexRepository
from app.observability.service import (
    AdvancedDiagnosticsDisabledError,
    AgentObservabilityService,
    InvalidTraceContentRangeError,
    TraceContentNotFoundError,
    TraceContentUnavailableError,
)


def _trace_service(
    root: Path,
    *,
    payload: object,
    advanced_enabled: bool = True,
    raw_row: bytes | None = None,
) -> tuple[AgentObservabilityService, object, Path, str]:
    connection = connect_runtime_database(root)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-1', 'workspace-1', 'review.round', 1, '复习')"
    )
    connection.execute(
        "INSERT INTO agent_runs "
        "(id, session_id, status, input_json, model_bindings_json, "
        "configuration_json) "
        "VALUES ('run-1', 'session-1', 'completed', '{}', '{}', '{}')"
    )
    connection.commit()

    trace_root = initialize_agent_trace_directory(root)
    path = trace_root / "session-1" / "run-1.jsonl"
    path.parent.mkdir(mode=0o700, exist_ok=True)
    row = {
        "schema_version": 3,
        "workspace_id": "workspace-1",
        "session_id": "session-1",
        "run_id": "run-1",
        "event_id": "event-1",
        "operation_id": "model-1",
        "parent_operation_id": "agent-1",
        "operation_kind": "model",
        "event_type": "model.request",
        "timestamp": "2026-07-29T12:00:00+00:00",
        "sequence": 1,
        "payload": payload,
    }
    path.write_bytes(
        raw_row
        if raw_row is not None
        else (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    )
    repository = TraceIndexRepository(connection)
    indexer = TraceLedgerIndexer(
        workspace_id="workspace-1",
        workspace_root=root,
        repository=repository,
    )
    indexer.sync_workspace()
    service = AgentObservabilityService(
        workspace_id="workspace-1",
        workspace_root=root,
        connection=connection,
        trace_repository=repository,
        indexer=indexer,
        advanced_diagnostics_enabled=lambda: advanced_enabled,
    )
    event_id = repository.list_events("run-1")[0]["event_id"]
    return service, connection, path, event_id


def test_trace_content_is_disabled_by_default(tmp_path: Path) -> None:
    service, connection, _path, event_id = _trace_service(
        tmp_path,
        payload={"messages": ["private"]},
        advanced_enabled=False,
    )
    try:
        with pytest.raises(AdvancedDiagnosticsDisabledError):
            service.get_event_content("run-1", event_id, offset=0, limit=65536)
    finally:
        connection.close()


def test_trace_content_validates_pointer_and_returns_reasoning_only_when_stored(
    tmp_path: Path,
) -> None:
    service, connection, _path, event_id = _trace_service(
        tmp_path,
        payload={"messages": ["你好"], "reasoning": "provider field"},
    )
    try:
        page = service.get_event_content(
            "run-1", event_id, offset=0, limit=65536
        )
    finally:
        connection.close()

    assert json.loads(page.content)["messages"] == ["你好"]
    assert page.reasoning == "provider field"
    assert page.complete is True
    assert page.next_offset is None
    assert page.redactions_applied is True


def test_trace_content_omits_absent_reasoning(tmp_path: Path) -> None:
    service, connection, _path, event_id = _trace_service(
        tmp_path,
        payload={"answer": "ok"},
    )
    try:
        page = service.get_event_content(
            "run-1", event_id, offset=0, limit=65536
        )
    finally:
        connection.close()

    assert page.reasoning is None


def test_trace_content_paginates_large_utf8_body_without_splitting_codepoint(
    tmp_path: Path,
) -> None:
    service, connection, _path, event_id = _trace_service(
        tmp_path,
        payload={"content": "测" * 30_000},
    )
    try:
        first = service.get_event_content(
            "run-1", event_id, offset=0, limit=65536
        )
        second = service.get_event_content(
            "run-1",
            event_id,
            offset=first.next_offset,
            limit=65536,
        )
    finally:
        connection.close()

    assert len(first.content.encode("utf-8")) <= 65536
    assert first.complete is False
    assert first.next_offset is not None
    assert second.offset == first.next_offset
    assert second.complete is True
    assert json.loads(first.content + second.content)["content"].startswith("测")


@pytest.mark.parametrize(
    ("offset", "limit"),
    ((-1, 10), (0, 0), (0, 65537), (999999, 10)),
)
def test_trace_content_rejects_invalid_ranges(
    tmp_path: Path, offset: int, limit: int
) -> None:
    service, connection, _path, event_id = _trace_service(
        tmp_path,
        payload={"answer": "ok"},
    )
    try:
        with pytest.raises(InvalidTraceContentRangeError):
            service.get_event_content(
                "run-1", event_id, offset=offset, limit=limit
            )
    finally:
        connection.close()


def test_trace_content_rejects_missing_pointer(tmp_path: Path) -> None:
    service, connection, _path, _event_id = _trace_service(
        tmp_path,
        payload={"answer": "ok"},
    )
    try:
        with pytest.raises(TraceContentNotFoundError):
            service.get_event_content(
                "run-1", "missing-event", offset=0, limit=10
            )
    finally:
        connection.close()


def test_trace_content_rejects_changed_payload_hash(tmp_path: Path) -> None:
    service, connection, path, event_id = _trace_service(
        tmp_path,
        payload={"answer": "one"},
    )
    original = path.read_text(encoding="utf-8")
    path.write_text(original.replace('"one"', '"two"'), encoding="utf-8")
    try:
        with pytest.raises(TraceContentUnavailableError):
            service.get_event_content("run-1", event_id, offset=0, limit=10)
    finally:
        connection.close()


def test_trace_content_rejects_symlink_escape_after_indexing(tmp_path: Path) -> None:
    service, connection, path, event_id = _trace_service(
        tmp_path,
        payload={"answer": "ok"},
    )
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    try:
        with pytest.raises(TraceContentUnavailableError):
            service.get_event_content("run-1", event_id, offset=0, limit=10)
    finally:
        connection.close()


def test_trace_content_rejects_malformed_historical_row(tmp_path: Path) -> None:
    service, connection, _path, event_id = _trace_service(
        tmp_path,
        payload=None,
        raw_row=b"{not-json}\n",
    )
    try:
        with pytest.raises(TraceContentUnavailableError):
            service.get_event_content("run-1", event_id, offset=0, limit=10)
    finally:
        connection.close()
