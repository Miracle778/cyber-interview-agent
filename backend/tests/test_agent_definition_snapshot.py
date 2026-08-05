from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.agents.definition_registry import require_agent_definition
from app.agents.definition_snapshot import (
    AgentDefinitionSnapshot,
    build_agent_definition_snapshot,
)
from app.application.session_service import ProductRepository
from app.application.execution_service import AgentExecutionService
from app.application.session_service import ProductEventStream
from app.infrastructure.runtime_database import connect_runtime_database


def test_builds_canonical_snapshot_from_definition_and_actual_bindings() -> None:
    definition = require_agent_definition("review.single")

    snapshot = build_agent_definition_snapshot(
        definition=definition,
        graph_version=3,
        model_bindings={
            "answer_evaluation": "model-evaluator",
            "report_summarization": "model-reporter",
            "unrelated_role": "must-not-affect-snapshot",
        },
    )

    assert snapshot.legacy is False
    assert snapshot.agent_id == "review.single"
    assert snapshot.agent_definition_version == definition.definition_version
    assert snapshot.graph_version == 3
    assert snapshot.eval_pack_id == "review-single.v2"
    assert snapshot.eval_pack_version == 2
    assert snapshot.model_roles == tuple(sorted(definition.model_roles))
    assert snapshot.child_components == tuple(sorted(definition.child_components))
    assert snapshot.model_binding_digest == build_agent_definition_snapshot(
        definition=definition,
        graph_version=3,
        model_bindings={
            "report_summarization": "model-reporter",
            "answer_evaluation": "model-evaluator",
            "another_unrelated_role": "ignored",
        },
    ).model_binding_digest
    assert len(snapshot.toolset_digest or "") == 64
    assert AgentDefinitionSnapshot.from_json(snapshot.to_json()) == snapshot


def test_new_execution_persists_snapshot_and_database_rejects_mutation(
    tmp_path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    repository = ProductRepository(connection)
    session = repository.create_session(
        workspace_id="workspace-1",
        kind="review.single",
        title="单题复习",
    )
    snapshot = build_agent_definition_snapshot(
        definition=require_agent_definition(session.kind),
        graph_version=session.graph_version,
        model_bindings={"answer_evaluation": "model-1"},
    )

    execution = repository.create_execution(
        session.id,
        input={"questionId": "question-1"},
        model_bindings={"answer_evaluation": "model-1"},
        definition_snapshot=snapshot,
    )

    assert execution.definition_snapshot == snapshot
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "UPDATE agent_runs SET agent_definition_snapshot_json = ? WHERE id = ?",
            (AgentDefinitionSnapshot.legacy_snapshot().to_json(), execution.id),
        )
    connection.rollback()
    assert repository.get_execution(execution.id).definition_snapshot == snapshot
    connection.close()


def test_legacy_execution_is_explicit_and_never_infers_current_definition(
    tmp_path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    repository = ProductRepository(connection)
    session = repository.create_session(
        workspace_id="workspace-1",
        kind="review.single",
        title="历史单题复习",
    )

    execution = repository.create_execution(
        session.id,
        input={},
        model_bindings={},
    )

    assert execution.definition_snapshot == AgentDefinitionSnapshot.legacy_snapshot()
    assert execution.definition_snapshot.agent_id is None
    assert execution.definition_snapshot.eval_pack_id is None
    connection.close()


@pytest.mark.asyncio
async def test_execution_service_freezes_registered_definition_before_run(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    repository = ProductRepository(connection)
    session = repository.create_session(
        workspace_id="workspace-1",
        kind="review.single",
        title="单题复习",
    )
    service = AgentExecutionService(
        workspace_id="workspace-1",
        workspace_root=tmp_path,
        repository=repository,
        events=ProductEventStream(repository, workspace_root=tmp_path),
        graph_factory=lambda *_args, **_kwargs: None,
        model_bindings=lambda: {"answer_evaluation": "model-1"},
        create_action=lambda _command: None,
        create_draft=lambda _command: None,
        mark_draft_review_pending=lambda *_args, **_kwargs: None,
    )

    execution = await service.prepare(
        session,
        input={"questionId": "question-1"},
        project_input_message=False,
    )

    assert execution.definition_snapshot.legacy is False
    assert execution.definition_snapshot.agent_id == "review.single"
    assert execution.definition_snapshot.agent_definition_version == "1"
    assert execution.definition_snapshot.eval_pack_id == "review-single.v2"
    assert execution.definition_snapshot.model_binding_digest is not None
    connection.close()
