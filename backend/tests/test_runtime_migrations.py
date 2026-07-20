import sqlite3
from pathlib import Path

import pytest

from app.agents.context import AgentContext
from app.application.session_service import ProductRepository
from app.application.workspace_runtime import SqliteMiddlewareProjection
from app.middleware.usage_projection_middleware import ContextUsageProjection

from app.infrastructure.runtime_database import (
    connect_runtime_database,
    runtime_database_path,
)


R2_TABLES = {
    "review_question_batches",
    "review_question_candidates",
    "review_question_catalog",
    "review_rounds",
    "review_report_proposals",
    "review_attempts",
    "review_input_requests",
    "review_input_receipts",
    "review_mastery_projection",
}

R2_SESSION_EXPERIENCE_TABLES = {
    "review_bulk_publication_items",
    "review_bulk_publications",
    "review_curation_command_receipts",
    "review_curation_context",
    "review_curation_sessions",
    "review_question_source_links",
}

R3_TABLES = {
    "profile_materials",
    "profile_material_versions",
    "profile_evidence",
    "profile_claims",
    "profile_claim_versions",
    "profile_claim_proposals",
    "profile_claim_conflicts",
    "profile_assessments",
    "profile_action_plans",
    "profile_action_plan_items",
    "profile_publication_selections",
    "profile_publication_selection_items",
    "profile_publications",
}


def _tables(connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def test_fresh_database_applies_all_runtime_migrations(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)

    assert R2_TABLES | R2_SESSION_EXPERIENCE_TABLES <= _tables(connection)
    assert [
        row[0]
        for row in connection.execute(
            "SELECT version FROM runtime_schema_migrations ORDER BY version"
        )
        ] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
    assert "agent_context_usage" in _tables(connection)
    connection.close()


def test_existing_generation_two_database_applies_r2_migration(
    tmp_path: Path,
) -> None:
    path = runtime_database_path(tmp_path)
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    schema = (
        Path(__file__).parents[1]
        / "app"
        / "db"
        / "migrations"
        / "runtime"
        / "001_current.sql"
    )
    connection.executescript(schema.read_text(encoding="utf-8"))
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('keep', 'w1', 'review.single', 1, 'keep me')"
    )
    connection.commit()

    connection.close()

    reopened = connect_runtime_database(tmp_path)

    assert R2_TABLES | R2_SESSION_EXPERIENCE_TABLES <= _tables(reopened)
    assert reopened.execute(
        "SELECT title FROM agent_sessions WHERE id = 'keep'"
    ).fetchone()[0] == "keep me"
    assert [
        row[0]
        for row in reopened.execute(
            "SELECT version FROM runtime_schema_migrations ORDER BY version"
        )
        ] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
    reopened.close()


def test_r2_migration_adds_waiting_for_input_status(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title, status) "
        "VALUES ('round', 'w1', 'review.round', 1, 'Round', 'waiting_for_input')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('execution', 'round', 'waiting_for_input')"
    )
    connection.commit()

    assert connection.execute(
        "SELECT status FROM agent_runs WHERE id = 'execution'"
    ).fetchone()[0] == "waiting_for_input"
    connection.close()


def test_session_experience_migration_adds_structured_messages_and_attempt_state(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)

    message_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(agent_messages)")
    }
    attempt_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(review_attempts)")
    }

    assert {"message_kind", "payload_json"} <= message_columns
    assert {
        "status",
        "evaluation_error_code",
        "evaluation_started_at",
        "evaluation_completed_at",
    } <= attempt_columns
    connection.close()


def test_cancellable_interaction_migration_adds_execution_state(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)

    run_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(agent_runs)")
    }
    command_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(review_curation_command_receipts)"
        )
    }
    session_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(review_curation_sessions)"
        )
    }

    assert {"configuration_json", "cancel_requested_at"} <= run_columns
    assert {
        "execution_id",
        "lifecycle_status",
        "original_text",
        "retry_count",
    } <= command_columns
    assert {
        "preferred_model_id",
        "preferred_reasoning_effort",
    } <= session_columns
    connection.close()


def test_execution_configuration_and_cancel_request_round_trip(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    repository = ProductRepository(connection)
    session = repository.create_session(
        workspace_id="w1",
        kind="question.curate",
        title="Cancellable command",
    )
    execution = repository.create_execution(
        session.id,
        input={"operation": "curation.command"},
        model_bindings={},
        configuration={
            "providerModelId": "model-1",
            "reasoningEffort": "medium",
        },
    )

    first = repository.request_execution_cancel(execution.id)
    repeated = repository.request_execution_cancel(execution.id)

    assert first.configuration.provider_model_id == "model-1"
    assert first.configuration.reasoning_effort == "medium"
    assert first.cancel_requested_at is not None
    assert repeated.cancel_requested_at == first.cancel_requested_at
    connection.close()


def test_context_usage_projection_round_trips_real_token_threshold(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions (id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session', 'w1', 'question.curate', 1, 'Context')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) VALUES ('run', 'session', 'running')"
    )
    connection.commit()
    projection = SqliteMiddlewareProjection(connection)
    context = AgentContext(
        workspace_id="w1",
        workspace_root=tmp_path,
        session_id="session",
        run_id="run",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )

    projection.record_context_usage(
        context,
        ContextUsageProjection(current_tokens=42000, threshold_tokens=89600),
    )

    assert ProductRepository(connection).context_usage("session") == {
        "currentTokens": 42000,
        "thresholdTokens": 89600,
        "estimated": True,
    }
    connection.close()


def test_session_experience_migration_preserves_existing_r2_rows(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s-existing', 'w1', 'review.round', 1, 'Existing')"
    )
    connection.execute(
        "INSERT INTO agent_messages "
        "(id, session_id, role, content) "
        "VALUES ('m-existing', 's-existing', 'assistant', 'Keep me')"
    )
    connection.commit()
    connection.close()

    reopened = connect_runtime_database(tmp_path)
    row = reopened.execute(
        "SELECT content, message_kind, payload_json FROM agent_messages "
        "WHERE id = 'm-existing'"
    ).fetchone()

    assert tuple(row) == ("Keep me", "text", "{}")
    reopened.close()


def test_r3_migration_creates_profile_tables(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)

    assert R3_TABLES <= _tables(connection)
    connection.close()


def test_r3_migration_adds_session_visibility(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)

    columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_sessions)")}
    assert "visibility" in columns

    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title, visibility) "
        "VALUES ('sys', 'w1', 'profile.ingest', 1, 'hidden', 'system')"
    )
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('usr', 'w1', 'profile.manage', 1, 'user session')"
    )
    connection.commit()

    rows = connection.execute(
        "SELECT id, visibility FROM agent_sessions ORDER BY id"
    ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [("sys", "system"), ("usr", "user")]
    connection.close()


def test_r3_migration_rejects_invalid_session_visibility(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO agent_sessions "
            "(id, workspace_id, graph_id, graph_version, title, visibility) "
            "VALUES ('bad', 'w1', 'profile.ingest', 1, 'hidden', 'public')"
        )
    connection.close()


def test_r3_migration_extends_tool_audits_with_denied_and_correlation(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions (id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s', 'w1', 'profile.manage', 1, 'S')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) VALUES ('r', 's', 'running')"
    )
    connection.execute(
        "INSERT INTO tool_audits "
        "(id, session_id, run_id, tool_name, status, tool_call_id, agent_role, "
        "input_digest, result_digest) "
        "VALUES ('a', 's', 'r', 'read_personal_evidence', 'denied', 'call-1', "
        "'profile_chat', 'abc', 'def')"
    )
    connection.commit()

    columns = {row[1] for row in connection.execute("PRAGMA table_info(tool_audits)")}
    assert {"tool_call_id", "agent_role", "input_digest", "result_digest"} <= columns
    row = connection.execute(
        "SELECT status, tool_call_id, agent_role, input_digest, result_digest "
        "FROM tool_audits WHERE id = 'a'"
    ).fetchone()
    assert tuple(row) == ("denied", "call-1", "profile_chat", "abc", "def")
    connection.close()


def test_r3_migration_adds_profile_card_message_kinds(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions (id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s', 'w1', 'profile.manage', 1, 'S')"
    )
    for index, kind in enumerate(
        (
            "claim_card",
            "proposal_card",
            "assessment_card",
            "action_plan_card",
            "receipt",
        )
    ):
        connection.execute(
            "INSERT INTO agent_messages "
            "(id, session_id, role, content, message_kind, payload_json) "
            "VALUES (?, 's', 'assistant', ?, ?, ?)",
            (f"m{index}", kind, kind, '{"id":"x"}'),
        )
    connection.commit()
    connection.close()


def test_r3_migration_allows_profile_knowledge_drafts(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions (id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s', 'w1', 'profile.manage', 1, 'S')"
    )
    connection.execute(
        "INSERT INTO knowledge_drafts "
        "(id, workspace_id, session_id, domain, document_type, document_id, title, "
        "content_path, content_hash) "
        "VALUES ('d', 'w1', 's', 'profile', 'profile', 'profile-1', 'Profile', "
        "'50_profile/profile-1.md', 'hash')"
    )
    connection.commit()
    connection.close()


def test_r3_migration_adds_revocable_publication_state(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions (id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s', 'w1', 'knowledge.publish', 1, 'S')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) VALUES ('r', 's', 'running')"
    )
    connection.execute(
        "INSERT INTO pending_actions "
        "(id, workspace_id, session_id, run_id, action_type, payload_json, "
        "preview_json, idempotency_key) "
        "VALUES ('pa', 'w1', 's', 'r', 'publish', '{}', '{}', 'k-1')"
    )
    connection.execute(
        "INSERT INTO knowledge_drafts "
        "(id, workspace_id, domain, document_type, document_id, title, content_path, "
        "content_hash) "
        "VALUES ('d', 'w1', 'profile', 'profile', 'p1', 'P', '50_profile/p1.md', 'h')"
    )
    connection.execute(
        "INSERT INTO publication_runs "
        "(id, action_id, draft_id, expected_draft_version, expected_content_hash, "
        "document_id, target_path, state) "
        "VALUES ('pr', 'pa', 'd', 1, 'h', 'p1', '50_profile/p1.md', 'revoked')"
    )
    connection.commit()
    connection.close()


def test_r3_migration_preserves_existing_tool_audits_and_messages(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions (id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s', 'w1', 'review.single', 1, 'S')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) VALUES ('r', 's', 'running')"
    )
    connection.execute(
        "INSERT INTO tool_audits "
        "(id, session_id, run_id, tool_name, status, resource_scope) "
        "VALUES ('a', 's', 'r', 'legacy_tool', 'completed', 'review.sources')"
    )
    connection.execute(
        "INSERT INTO agent_messages "
        "(id, session_id, role, content, message_kind, payload_json) "
        "VALUES ('m', 's', 'assistant', 'keep', 'question_card', '{}')"
    )
    connection.commit()
    connection.close()

    reopened = connect_runtime_database(tmp_path)
    audit = reopened.execute(
        "SELECT status, resource_scope, tool_call_id, agent_role FROM tool_audits "
        "WHERE id = 'a'"
    ).fetchone()
    assert tuple(audit) == ("completed", "review.sources", None, None)
    message = reopened.execute(
        "SELECT content, message_kind FROM agent_messages WHERE id = 'm'"
    ).fetchone()
    assert tuple(message) == ("keep", "question_card")
    reopened.close()
