from __future__ import annotations

from pathlib import Path
from time import perf_counter

from app.infrastructure.runtime_database import connect_runtime_database
from app.observability.indexer import TraceLedgerIndexer
from app.observability.repository import TraceIndexRepository
from app.observability.service import AgentObservabilityService


EXECUTION_COUNT = 10_000
EVENT_COUNT = 1_000


def _service(root: Path) -> tuple[AgentObservabilityService, object]:
    connection = connect_runtime_database(root)
    repository = TraceIndexRepository(connection)
    return (
        AgentObservabilityService(
            workspace_id="workspace-performance",
            connection=connection,
            trace_repository=repository,
            indexer=TraceLedgerIndexer(
                workspace_id="workspace-performance",
                workspace_root=root,
                repository=repository,
            ),
        ),
        connection,
    )


def _seed_large_workspace(connection) -> str:
    sessions = []
    runs = []
    for index in range(EXECUTION_COUNT):
        run_id = f"run-{index:05d}"
        session_id = f"session-{index:05d}"
        created_at = f"2026-07-{1 + index // 86400:02d}T{index % 24:02d}:00:00+00:00"
        sessions.append(
            (
                session_id,
                "workspace-performance",
                "review.round",
                1,
                f"性能样本 {index}",
                "user",
                created_at,
                created_at,
            )
        )
        runs.append(
            (
                run_id,
                session_id,
                "completed",
                created_at,
                created_at,
                created_at,
            )
        )
    connection.executemany(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title, visibility, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        sessions,
    )
    connection.executemany(
        "INSERT INTO agent_runs "
        "(id, session_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        runs,
    )

    target_run = "run-09999"
    target_session = "session-09999"
    relative_path = ".cyber-interview-agent/agent-traces/session-09999/run-09999.jsonl"
    connection.execute(
        "INSERT INTO agent_trace_files "
        "(relative_path, scanned_bytes, last_sequence, file_size, file_mtime_ns) "
        "VALUES (?, 100000, ?, 100000, 1)",
        (relative_path, EVENT_COUNT),
    )
    connection.execute(
        "INSERT INTO agent_trace_executions "
        "(run_id, workspace_id, session_id, first_event_at, last_event_at, "
        "trace_health, indexed_event_count) "
        "VALUES (?, 'workspace-performance', ?, "
        "'2026-07-29T12:00:00+00:00', '2026-07-29T12:00:01+00:00', "
        "'complete', ?)",
        (target_run, target_session, EVENT_COUNT),
    )
    connection.execute(
        "INSERT INTO agent_trace_operations "
        "(operation_id, run_id, kind, name, status, started_at, finished_at, "
        "latency_ms, retry_count) "
        "VALUES ('execution:run-09999', ?, 'execution', 'review.round', "
        "'completed', '2026-07-29T12:00:00+00:00', "
        "'2026-07-29T12:00:01+00:00', 1000, 0)",
        (target_run,),
    )
    connection.executemany(
        "INSERT INTO agent_trace_events "
        "(event_id, run_id, operation_id, event_type, observed_at, relative_path, "
        "byte_start, byte_length, payload_sha256, sequence) "
        "VALUES (?, ?, 'execution:run-09999', 'execution.progress', "
        "'2026-07-29T12:00:00+00:00', ?, ?, 100, ?, ?)",
        (
            (
                f"event-{sequence:04d}",
                target_run,
                relative_path,
                sequence * 100,
                f"{sequence:064x}",
                sequence,
            )
            for sequence in range(1, EVENT_COUNT + 1)
        ),
    )
    connection.commit()
    return target_run


def _measure(call):
    started = perf_counter()
    result = call()
    return result, (perf_counter() - started) * 1_000


def test_large_workspace_queries_stay_within_development_budgets(
    tmp_path: Path,
) -> None:
    service, connection = _service(tmp_path)
    target_run = _seed_large_workspace(connection)

    first_page, first_page_ms = _measure(lambda: service.list_executions(limit=50))
    filtered, filtered_ms = _measure(
        lambda: service.list_executions(status="completed", limit=50)
    )
    summary, summary_ms = _measure(lambda: service.get_execution(target_run))
    operations, operations_ms = _measure(
        lambda: service.list_operations(target_run)
    )

    assert first_page.total == EXECUTION_COUNT
    assert len(first_page.items) == 50
    assert filtered.total == EXECUTION_COUNT
    assert summary.id == target_run
    assert len(operations.items) == 1
    assert operations.items[0].event_count == EVENT_COUNT

    print(
        "observability performance (ms): "
        f"first_page={first_page_ms:.1f}, filter={filtered_ms:.1f}, "
        f"summary={summary_ms:.1f}, operation_tree={operations_ms:.1f}"
    )
    assert first_page_ms < 800, f"Run Center first page took {first_page_ms:.1f}ms"
    assert filtered_ms < 300, f"Run Center filter took {filtered_ms:.1f}ms"
    assert summary_ms < 500, f"Execution summary took {summary_ms:.1f}ms"
    assert operations_ms < 500, f"Operation tree took {operations_ms:.1f}ms"
