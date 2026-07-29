from __future__ import annotations

from pathlib import Path

from app.observability.cleanup import TraceCleanupService
from app.observability.repository import TraceIndexRepository
from test_agent_trace_retention import _service


def _cleanup(tmp_path):
    connection, retention = _service(tmp_path)
    retention.replace_policy(body_policy="metadata_only")
    cleanup = TraceCleanupService(
        retention=retention,
        repository=TraceIndexRepository(connection),
    )
    return connection, retention, cleanup


def _trace(tmp_path: Path) -> Path:
    return (
        tmp_path
        / ".cyber-interview-agent"
        / "agent-traces"
        / "session-1"
        / "run-1.jsonl"
    )


def test_cleanup_plan_quarantines_verifies_and_finalizes_with_receipt(
    tmp_path,
) -> None:
    connection, retention, cleanup = _cleanup(tmp_path)
    try:
        plan = retention.create_plan()
        result = cleanup.confirm(plan.id)
        event = connection.execute(
            "SELECT event_type, payload_sha256, body_state "
            "FROM agent_trace_events LIMIT 1"
        ).fetchone()
        assert result.status == "completed"
        assert result.items[0].status == "finalized"
        assert not _trace(tmp_path).exists()
        assert tuple(event) == ("model.response", event["payload_sha256"], "deleted")
        assert cleanup.confirm(plan.id).status == "completed"
    finally:
        connection.close()


def test_hash_mismatch_is_partial_failure_and_never_deletes_source(tmp_path) -> None:
    connection, retention, cleanup = _cleanup(tmp_path)
    try:
        plan = retention.create_plan()
        _trace(tmp_path).write_text("changed\n", encoding="utf-8")
        result = cleanup.confirm(plan.id)
        assert result.status == "partial_failure"
        assert result.items[0].error_code == "trace_quarantine_failed"
        assert _trace(tmp_path).exists()
        assert connection.execute(
            "SELECT body_state FROM agent_trace_events LIMIT 1"
        ).fetchone()[0] == "available"
    finally:
        connection.close()


def test_symlink_source_is_denied_and_recorded(tmp_path) -> None:
    connection, retention, cleanup = _cleanup(tmp_path)
    try:
        plan = retention.create_plan()
        trace = _trace(tmp_path)
        original = trace.with_suffix(".saved")
        trace.rename(original)
        trace.symlink_to(original)
        result = cleanup.confirm(plan.id)
        assert result.status == "partial_failure"
        assert trace.is_symlink()
        assert original.exists()
    finally:
        connection.close()


def test_restart_resumes_quarantined_cleanup_deterministically(tmp_path) -> None:
    connection, retention, cleanup = _cleanup(tmp_path)
    try:
        plan = retention.create_plan()
        cleanup._set_run_status(plan.id, "quarantining", confirmed=True)
        cleanup._quarantine(plan.id, plan.items[0])
        cleanup._set_run_status(plan.id, "quarantined")

        restarted = TraceCleanupService(
            retention=retention,
            repository=TraceIndexRepository(connection),
        )
        recovered = restarted.resume_incomplete()

        assert len(recovered) == 1
        assert recovered[0].status == "completed"
        assert recovered[0].items[0].status == "finalized"
        assert not _trace(tmp_path).exists()
        assert restarted.resume_incomplete() == ()
    finally:
        connection.close()
