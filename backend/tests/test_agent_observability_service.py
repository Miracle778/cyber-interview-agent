from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.runtime_database import connect_runtime_database
from app.observability.indexer import TraceLedgerIndexer
from app.observability.repository import TraceIndexRepository
from app.observability.service import (
    AgentExecutionNotFoundError,
    AgentObservabilityService,
    InvalidExecutionCursorError,
)


def _service(root: Path) -> tuple[AgentObservabilityService, object]:
    connection = connect_runtime_database(root)
    trace_repository = TraceIndexRepository(connection)
    indexer = TraceLedgerIndexer(
        workspace_id="workspace-1",
        workspace_root=root,
        repository=trace_repository,
    )
    return (
        AgentObservabilityService(
            workspace_id="workspace-1",
            connection=connection,
            trace_repository=trace_repository,
            indexer=indexer,
        ),
        connection,
    )


def _insert_run(
    connection,
    *,
    run_id: str,
    graph_id: str,
    status: str,
    created_at: str,
    visibility: str = "user",
    title: str | None = None,
    trace_health: str | None = "complete",
) -> None:
    session_id = f"session-{run_id}"
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title, visibility) "
        "VALUES (?, 'workspace-1', ?, 1, ?, ?)",
        (session_id, graph_id, title or run_id, visibility),
    )
    connection.execute(
        "INSERT INTO agent_runs "
        "(id, session_id, status, created_at, started_at, finished_at, error_code) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            session_id,
            status,
            created_at,
            created_at,
            created_at if status in {"completed", "failed", "cancelled"} else None,
            "provider_error" if status == "failed" else None,
        ),
    )
    if trace_health is not None:
        connection.execute(
            "INSERT INTO agent_trace_executions "
            "(run_id, workspace_id, session_id, first_event_at, last_event_at, "
            "trace_health, indexed_event_count) VALUES (?, 'workspace-1', ?, ?, ?, ?, 4)",
            (
                run_id,
                session_id,
                created_at,
                "2026-07-29T12:00:03+00:00",
                trace_health,
            ),
        )
        connection.execute(
            "INSERT INTO agent_trace_operations "
            "(operation_id, run_id, parent_operation_id, kind, name, agent_role, "
            "status, started_at, finished_at, latency_ms, retry_count) "
            "VALUES (?, ?, NULL, 'execution', ?, NULL, ?, ?, ?, 3000, 0)",
            (
                f"execution:{run_id}",
                run_id,
                run_id,
                status,
                created_at,
                "2026-07-29T12:00:03+00:00",
            ),
        )
    connection.commit()


def _seed_six_states(connection) -> None:
    states = (
        ("run-completed", "review.round", "completed", "2026-07-29T12:00:06+00:00", "complete"),
        ("run-running", "question.curate", "running", "2026-07-29T12:00:05+00:00", "complete"),
        ("run-failed", "project.deep_dive", "failed", "2026-07-29T12:00:04+00:00", "complete"),
        ("run-cancelled", "job.analysis", "cancelled", "2026-07-29T12:00:03+00:00", "complete"),
        ("run-missing", "profile.manage", "completed", "2026-07-29T12:00:02+00:00", None),
        ("run-partial", "review.single", "completed", "2026-07-29T12:00:01+00:00", "partial"),
    )
    for run_id, graph_id, status, created_at, trace_health in states:
        _insert_run(
            connection,
            run_id=run_id,
            graph_id=graph_id,
            status=status,
            created_at=created_at,
            trace_health=trace_health,
        )


def test_lists_one_summary_per_business_run_across_runtime_states(
    tmp_path: Path,
) -> None:
    service, connection = _service(tmp_path)
    _seed_six_states(connection)
    connection.execute(
        "INSERT INTO agent_trace_operations "
        "(operation_id, run_id, parent_operation_id, kind, name, status, "
        "latency_ms, retry_count) VALUES "
        "('model-1', 'run-completed', 'execution:run-completed', 'model', "
        "'answer_evaluation', 'completed', 1200, 0), "
        "('tool-1', 'run-completed', 'execution:run-completed', 'tool', "
        "'read_question', 'completed', 50, 0)"
    )
    connection.commit()

    page = service.list_executions(limit=50)

    assert page.total == 6
    assert len(page.items) == 6
    assert {item.status for item in page.items} == {
        "completed",
        "running",
        "failed",
        "cancelled",
    }
    by_id = {item.id: item for item in page.items}
    assert by_id["run-missing"].trace_health == "missing"
    assert by_id["run-partial"].trace_health == "partial"
    assert by_id["run-completed"].model_call_count == 1
    assert by_id["run-completed"].system_operation_count == 2


def test_assembles_usage_context_latency_retry_and_runtime_capabilities(
    tmp_path: Path,
) -> None:
    service, connection = _service(tmp_path)
    _insert_run(
        connection,
        run_id="run-1",
        graph_id="review.round",
        status="completed",
        created_at="2026-07-29T12:00:00+00:00",
        title="第 8 轮复习",
    )
    connection.execute(
        "INSERT INTO model_invocation_usage "
        "(workspace_id, session_id, run_id, operation_key, input_tokens, "
        "output_tokens, total_tokens, estimated) VALUES "
        "('workspace-1', 'session-run-1', 'run-1', 'call-1', 700, 300, 1000, 0), "
        "('workspace-1', 'session-run-1', 'run-1', 'call-2', 800, 200, 1000, 0)"
    )
    connection.execute(
        "INSERT INTO agent_context_usage "
        "(session_id, run_id, current_tokens, threshold_tokens, estimated) "
        "VALUES ('session-run-1', 'run-1', 12000, 90000, 0)"
    )
    connection.execute(
        "INSERT INTO agent_trace_operations "
        "(operation_id, run_id, parent_operation_id, kind, name, status, "
        "latency_ms, retry_count) VALUES "
        "('model-1', 'run-1', 'execution:run-1', 'model', "
        "'answer_evaluation', 'completed', 1200, 2)"
    )
    connection.commit()

    summary = service.get_execution("run-1")

    assert summary.title == "第 8 轮复习"
    assert summary.total_tokens == 2000
    assert summary.model_call_count == 1
    assert summary.context_current_tokens == 12000
    assert summary.context_threshold_tokens == 90000
    assert summary.latency_ms == 3000
    assert summary.retry_count == 2
    assert "manual_judge" in summary.capabilities
    assert "cancel" not in summary.capabilities
    assert "resume" not in summary.capabilities


def test_cursor_filters_and_system_agent_visibility_are_stable(
    tmp_path: Path,
) -> None:
    service, connection = _service(tmp_path)
    _seed_six_states(connection)
    _insert_run(
        connection,
        run_id="run-system",
        graph_id="profile.ingest",
        status="completed",
        created_at="2026-07-29T12:00:07+00:00",
        visibility="system",
    )
    _insert_run(
        connection,
        run_id="run-publication",
        graph_id="knowledge.publish",
        status="completed",
        created_at="2026-07-29T12:00:08+00:00",
        title="发布题目：不会进入运行中心",
    )
    _insert_run(
        connection,
        run_id="run-diagnostic",
        graph_id="diagnostic.echo",
        status="completed",
        created_at="2026-07-29T12:00:09+00:00",
        visibility="system",
    )

    first = service.list_executions(limit=2)
    second = service.list_executions(limit=2, cursor=first.next_cursor)
    failed = service.list_executions(status="failed", limit=50)
    curation = service.list_executions(agent="题库整理", limit=50)
    searched = service.list_executions(keyword="画像助手", limit=50)
    system = service.list_executions(include_system_agents=True, limit=50)
    time_window = service.list_executions(
        started_from="2026-07-29T12:00:03+00:00",
        started_to="2026-07-29T12:00:04+00:00",
        limit=50,
    )

    assert [item.id for item in first.items] == ["run-completed", "run-running"]
    assert [item.id for item in second.items] == ["run-failed", "run-cancelled"]
    assert first.total == second.total == 6
    assert [item.id for item in failed.items] == ["run-failed"]
    assert {item.display_name for item in curation.items} == {"题库整理"}
    assert "画像助手" in curation.agent_counts
    assert "复习助手" in curation.agent_counts
    assert [item.id for item in searched.items] == ["run-missing"]
    assert system.total == 7
    assert system.items[0].id == "run-system"
    assert system.items[0].system is True
    assert next(item for item in system.items if item.id == "run-completed").system is False
    assert "run-publication" not in {item.id for item in system.items}
    assert "run-diagnostic" not in {item.id for item in system.items}
    assert {item.id for item in time_window.items} == {
        "run-failed",
        "run-cancelled",
    }

    with pytest.raises(InvalidExecutionCursorError):
        service.list_executions(cursor="not-a-cursor")

    with pytest.raises(AgentExecutionNotFoundError):
        service.get_execution("run-publication")


def test_business_agent_stays_visible_when_its_session_is_internal(
    tmp_path: Path,
) -> None:
    service, connection = _service(tmp_path)
    _insert_run(
        connection,
        run_id="run-retrospective",
        graph_id="interview.retrospective",
        status="running",
        created_at="2026-08-02T05:00:15+00:00",
        visibility="system",
        title="复盘分析：示例公司后端二面",
    )

    page = service.list_executions(limit=50)

    assert [item.id for item in page.items] == ["run-retrospective"]
    assert page.items[0].display_name == "面试复盘"
    assert page.items[0].system is False
    connection.close()


def test_legacy_retrospective_graph_alias_remains_observable(
    tmp_path: Path,
) -> None:
    service, connection = _service(tmp_path)
    _insert_run(
        connection,
        run_id="run-retrospective-legacy",
        graph_id="interview.retrospective.analysis",
        status="failed",
        created_at="2026-08-02T05:01:47+00:00",
        visibility="system",
        title="复盘分析：示例公司后端二面",
    )

    page = service.list_executions(limit=50)
    canonical_filter = service.list_executions(
        agent="interview.retrospective", limit=50
    )

    assert [item.id for item in page.items] == ["run-retrospective-legacy"]
    assert [item.id for item in canonical_filter.items] == [
        "run-retrospective-legacy"
    ]
    assert service.get_execution("run-retrospective-legacy").display_name == "面试复盘"
    connection.close()


def test_status_filters_group_internal_runtime_states(
    tmp_path: Path,
) -> None:
    service, connection = _service(tmp_path)
    for index, status in enumerate(
        (
            "queued",
            "waiting_for_input",
            "waiting_for_approval",
            "failed",
            "interrupted",
            "cancelled",
            "running",
        )
    ):
        _insert_run(
            connection,
            run_id=f"run-{status}",
            graph_id="question.curate",
            status=status,
            created_at=f"2026-07-29T12:00:0{index}+00:00",
        )

    waiting = service.list_executions(status="waiting", limit=50)
    attention = service.list_executions(status="attention", limit=50)
    stopped = service.list_executions(status="stopped", limit=50)

    assert {item.status for item in waiting.items} == {
        "queued",
        "waiting_for_input",
        "waiting_for_approval",
    }
    assert {item.status for item in attention.items} == {"failed"}
    assert {item.status for item in stopped.items} == {
        "interrupted",
        "cancelled",
    }
    assert waiting.status_counts == attention.status_counts == stopped.status_counts
    assert waiting.status_counts["running"] == 1
