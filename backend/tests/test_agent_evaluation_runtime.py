from __future__ import annotations

import json
from pathlib import Path

from app.diagnostics.agent_trace import AgentTraceWriter, TraceIdentity
from app.evaluation.registry import get_eval_pack
from app.evaluation.runtime import EvaluationRuntime
from app.infrastructure.runtime_database import connect_runtime_database
from app.observability.indexer import TraceLedgerIndexer
from app.observability.repository import TraceIndexRepository
from app.observability.service import AgentObservabilityService


def _service(root: Path):
    connection = connect_runtime_database(root)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-1', 'workspace-1', 'review.round', 7, '原始标题')"
    )
    connection.execute(
        "INSERT INTO agent_runs "
        "(id, session_id, status, input_json, model_bindings_json, "
        "configuration_json) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "run-1",
            "session-1",
            "completed",
            json.dumps(
                {
                    "answer": "用户回答",
                    "source_hash": "a" * 64,
                }
            ),
            json.dumps({"answer_evaluation": "provider-model-1"}),
            json.dumps(
                {
                    "prompt_version": "review-answer.v3",
                    "tool_versions": {"lookup_question": "2"},
                    "schema_version": "review-evaluation.v4",
                }
            ),
        ),
    )
    connection.commit()
    identity = TraceIdentity(
        workspace_id="workspace-1",
        workspace_root=root,
        session_id="session-1",
        run_id="run-1",
        agent_role="answer_evaluation",
        agent_name="review_answer_evaluation",
        invocation_id="invocation-1",
    )
    writer = AgentTraceWriter()
    writer.append(identity, "model.request", {"messages": ["用户回答"]})
    writer.append(
        identity,
        "model.response",
        {"response": {"structured_response": {"score": 4}}},
    )
    repository = TraceIndexRepository(connection)
    indexer = TraceLedgerIndexer(
        workspace_id="workspace-1",
        workspace_root=root,
        repository=repository,
    )
    indexer.sync_workspace()
    return (
        AgentObservabilityService(
            workspace_id="workspace-1",
            workspace_root=root,
            connection=connection,
            trace_repository=repository,
            indexer=indexer,
        ),
        connection,
    )


def test_snapshot_freezes_execution_trace_artifacts_and_versions(
    tmp_path: Path,
) -> None:
    service, connection = _service(tmp_path)
    pack = get_eval_pack("review.v1")
    try:
        snapshot = service.build_evaluation_snapshot("run-1", pack)
        frozen_json = snapshot.canonical_json()
        frozen_hash = snapshot.frozen_input_hash

        connection.execute(
            "UPDATE agent_sessions SET title = '后来修改的标题' "
            "WHERE id = 'session-1'"
        )
        connection.execute(
            "UPDATE agent_runs SET input_json = '{\"answer\":\"changed\"}' "
            "WHERE id = 'run-1'"
        )
        connection.commit()
        rebuilt = service.build_evaluation_snapshot("run-1", pack)
    finally:
        connection.close()

    assert snapshot.execution["title"] == "原始标题"
    assert len(snapshot.events) == 2
    assert all(event.payload_sha256 for event in snapshot.events)
    assert all(event.available for event in snapshot.events)
    assert snapshot.artifacts[0].sha256 == "a" * 64
    assert snapshot.versions["graph"] == "7"
    assert snapshot.versions["prompt"] == "review-answer.v3"
    assert snapshot.versions["schema"] == "review-evaluation.v4"
    assert snapshot.model_bindings == {
        "answer_evaluation": "provider-model-1"
    }
    assert snapshot.tool_versions == {"lookup_question": "2"}
    assert snapshot.canonical_json() == frozen_json
    assert snapshot.frozen_input_hash == frozen_hash
    assert rebuilt.frozen_input_hash != frozen_hash


def test_evaluation_runtime_has_no_domain_write_or_generic_tool_access(
    tmp_path: Path,
) -> None:
    service, connection = _service(tmp_path)
    try:
        pack = get_eval_pack("review.v1")
        runtime = EvaluationRuntime(
            snapshot=service.build_evaluation_snapshot("run-1", pack),
            pack=pack,
        )
        result = runtime.run_deterministic()
    finally:
        connection.close()

    assert result.status == "passed"
    assert not hasattr(runtime, "domain_service")
    assert not hasattr(runtime, "write_tools")
    assert not hasattr(runtime, "workspace_root")
    assert not hasattr(runtime, "path_policy")


def test_corrupt_trace_is_inconclusive_and_does_not_change_business_run(
    tmp_path: Path,
) -> None:
    service, connection = _service(tmp_path)
    event = service.trace_repository.list_events("run-1")[0]
    trace_path = (
        tmp_path
        / ".cyber-interview-agent"
        / "agent-traces"
        / event["relative_path"]
    )
    trace_path.write_text("changed after indexing\n", encoding="utf-8")
    try:
        pack = get_eval_pack("review.v1")
        snapshot = service.build_evaluation_snapshot("run-1", pack)
        result = EvaluationRuntime(snapshot=snapshot, pack=pack).run_deterministic()
        business_status = connection.execute(
            "SELECT status FROM agent_runs WHERE id = 'run-1'"
        ).fetchone()[0]
    finally:
        connection.close()

    assert any(not item.available for item in snapshot.events)
    assert result.status == "inconclusive"
    assert result.evidence_gaps
    assert business_status == "completed"
