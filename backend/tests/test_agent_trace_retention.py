from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.diagnostics.agent_trace import AgentTraceWriter, TraceIdentity
from app.infrastructure.runtime_database import connect_runtime_database
from app.observability.indexer import TraceLedgerIndexer
from app.observability.repository import TraceIndexRepository
from app.observability.retention import TraceRetentionService


def _service(tmp_path, *, workspace_id="workspace-1", status="completed"):
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-1', ?, 'review.single', 1, '复习')",
        (workspace_id,),
    )
    connection.execute(
        "INSERT INTO agent_runs "
        "(id, session_id, status, input_json, model_bindings_json, "
        "configuration_json) VALUES ('run-1', 'session-1', ?, '{}', '{}', '{}')",
        (status,),
    )
    connection.commit()
    AgentTraceWriter().append(
        TraceIdentity(
            workspace_id=workspace_id,
            workspace_root=tmp_path,
            session_id="session-1",
            run_id="run-1",
            agent_role="answer_evaluation",
            agent_name="review",
            invocation_id="invocation-1",
        ),
        "model.response",
        {"private": "resume and answer"},
        terminal=True,
    )
    repository = TraceIndexRepository(connection)
    TraceLedgerIndexer(
        workspace_id=workspace_id,
        workspace_root=tmp_path,
        repository=repository,
    ).sync_workspace()
    service = TraceRetentionService(
        connection=connection,
        workspace_id=workspace_id,
        workspace_root=tmp_path,
        now=lambda: datetime(2026, 7, 30, tzinfo=timezone.utc),
    )
    return connection, service


def test_default_and_all_retention_policy_choices(tmp_path) -> None:
    connection, service = _service(tmp_path)
    try:
        default = service.get_policy()
        assert (default.body_policy, default.body_days) == ("days", 90)
        assert service.replace_policy(body_policy="permanent").body_days is None
        assert service.replace_policy(body_policy="metadata_only").body_days is None
        changed = service.replace_policy(body_policy="days", body_days=30)
        assert (changed.body_policy, changed.body_days) == ("days", 30)
        with pytest.raises(ValueError):
            service.replace_policy(body_policy="days", body_days=0)
        with pytest.raises(ValueError):
            service.replace_policy(body_policy="permanent", body_days=90)
    finally:
        connection.close()


def test_metadata_only_plan_is_dry_run_idempotent_and_preserves_file(tmp_path) -> None:
    connection, service = _service(tmp_path)
    try:
        service.replace_policy(body_policy="metadata_only")
        first = service.create_plan()
        replay = service.create_plan()
        trace = (
            tmp_path
            / ".cyber-interview-agent"
            / "agent-traces"
            / "session-1"
            / "run-1.jsonl"
        )
        assert first.id == replay.id
        assert first.file_count == 1
        assert first.event_count == 1
        assert first.total_bytes == trace.stat().st_size
        assert trace.exists()
    finally:
        connection.close()


def test_active_execution_is_protected_from_cleanup_plan(tmp_path) -> None:
    connection, service = _service(tmp_path, status="running")
    try:
        service.replace_policy(body_policy="metadata_only")
        plan = service.create_plan()
        assert plan.file_count == 0
        assert plan.protected_active_runs == 1
    finally:
        connection.close()
