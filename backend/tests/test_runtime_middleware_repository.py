from app.db.runtime_database import connect_runtime_database
from app.runtime.middleware.repository import RuntimeMiddlewareRepository
from app.runtime.middleware.types import ModelUsage
from app.runtime.repository import RuntimeRepository


def create_run(connection):
    runtime = RuntimeRepository(connection)
    session = runtime.create_session(
        workspace_id="w1",
        graph_id="review.single",
        graph_version=1,
        title="新会话",
    )
    run = runtime.create_run(session.id, input={}, model_bindings={})
    return runtime, session, run


def test_usage_operation_is_idempotent_and_aggregates_by_session(tmp_path):
    connection = connect_runtime_database(tmp_path)
    _, session, run = create_run(connection)
    repository = RuntimeMiddlewareRepository(connection)
    usage = ModelUsage(10, 5, 15, 10, 42, False)

    assert repository.record_usage(
        workspace_id="w1",
        session_id=session.id,
        run_id=run.id,
        operation_key="evaluate:1",
        role="agent_chat",
        provider_id="p1",
        provider_model_id="m1",
        usage=usage,
        status="completed",
    )
    assert not repository.record_usage(
        workspace_id="w1",
        session_id=session.id,
        run_id=run.id,
        operation_key="evaluate:1",
        role="agent_chat",
        provider_id="p1",
        provider_model_id="m1",
        usage=usage,
        status="completed",
    )

    aggregate = repository.aggregate_session_usage(session.id)
    assert aggregate.call_count == 1
    assert aggregate.input_tokens == 10
    assert aggregate.output_tokens == 5
    assert aggregate.total_tokens == 15
    assert aggregate.context_tokens == 10
    assert aggregate.estimated_count == 0


def test_guard_and_trace_sequences_survive_reopening(tmp_path):
    connection = connect_runtime_database(tmp_path)
    _, _, run = create_run(connection)
    repository = RuntimeMiddlewareRepository(connection)
    assert repository.record_guard_observation(
        run.id, kind="tool", fingerprint="safe-hash", state_hash="state-1"
    ) == 1
    assert repository.start_trace_segment(run.id, "trace-1", "span-1") == 1
    connection.close()

    reopened = connect_runtime_database(tmp_path)
    repository = RuntimeMiddlewareRepository(reopened)
    assert repository.record_guard_observation(
        run.id, kind="tool", fingerprint="safe-hash", state_hash="state-1"
    ) == 2
    assert repository.guard_state(run.id).observation_count == 2
    assert repository.start_trace_segment(run.id, "trace-2", "span-2") == 2
    assert repository.latest_trace_segment(run.id).trace_id == "trace-2"


def test_title_compare_and_set_and_summary_do_not_overwrite_user_title(tmp_path):
    connection = connect_runtime_database(tmp_path)
    runtime, session, _ = create_run(connection)

    assert runtime.compare_and_set_session_title(
        session.id, expected="新会话", title="Python 并发复习"
    )
    assert not runtime.compare_and_set_session_title(
        session.id, expected="新会话", title="错误覆盖"
    )
    updated = runtime.update_session_summary(session.id, summary="已掌握线程与协程。")
    assert updated.title == "Python 并发复习"
    assert updated.summary == "已掌握线程与协程。"
