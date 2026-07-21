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

R2_PROGRESSIVE_CURATION_TABLES = {
    "review_curation_batch_attempts",
    "review_curation_control_receipts",
    "review_curation_finalizations",
    "review_curation_work_items",
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
    "profile_idempotency_receipts",
}


def _tables(connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _create_runtime_at_version(workspace_root: Path, version: int) -> sqlite3.Connection:
    path = runtime_database_path(workspace_root)
    path.parent.mkdir(parents=True)
    migrations = Path(__file__).parents[1] / "app/db/migrations/runtime"
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript((migrations / "001_current.sql").read_text(encoding="utf-8"))
    connection.execute(
        "CREATE TABLE runtime_schema_migrations ("
        "version INTEGER PRIMARY KEY CHECK (version > 0), "
        "name TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    connection.execute(
        "INSERT INTO runtime_schema_migrations(version, name) VALUES (1, '001_current.sql')"
    )
    connection.commit()
    for migration in sorted(migrations.glob("[0-9][0-9][0-9]_*.sql")):
        migration_version = int(migration.name.split("_", 1)[0])
        if migration_version <= 1 or migration_version > version:
            continue
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.executescript(
            "BEGIN IMMEDIATE;\n"
            f"{migration.read_text(encoding='utf-8')}\n"
            "INSERT INTO runtime_schema_migrations(version, name) "
            f"VALUES ({migration_version}, '{migration.name}');\n"
            "COMMIT;"
        )
        connection.execute("PRAGMA foreign_keys = ON")
    return connection


def test_fresh_database_applies_all_runtime_migrations(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)

    assert R2_TABLES | R2_SESSION_EXPERIENCE_TABLES | R2_PROGRESSIVE_CURATION_TABLES <= _tables(connection)
    assert [
        row[0]
        for row in connection.execute(
            "SELECT version FROM runtime_schema_migrations ORDER BY version"
        )
        ] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
    assert "agent_context_usage" in _tables(connection)
    connection.close()


def test_migration_019_adds_durable_batch_control_and_recovery_state(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)

    batch_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(review_question_batches)"
        )
    }
    work_item_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(review_curation_work_items)"
        )
    }
    assert {"version", "control_intent", "concurrency_limit"} <= batch_columns
    assert work_item_columns == {
        "id",
        "batch_id",
        "stage",
        "unit_index",
        "input_digest",
        "source_refs_json",
        "processor_kind",
        "status",
        "output_json",
        "attempt_count",
        "last_error_code",
        "created_at",
        "updated_at",
    }
    indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }
    assert {
        "idx_review_question_batches_workspace_status",
        "idx_review_question_batches_origin_session",
        "idx_review_curation_sessions_workspace_updated",
        "idx_review_curation_work_items_batch_stage_status",
        "idx_review_curation_batch_attempts_batch_ordinal",
        "idx_review_curation_control_receipts_batch_created",
    } <= indexes
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_migration_020_adds_private_curation_finalization_claims(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)

    assert {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(review_curation_finalizations)"
        )
    } == {
        "batch_id",
        "execution_id",
        "batch_version",
        "state",
        "candidate_ids_json",
        "created_at",
        "updated_at",
    }
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_migration_019_preserves_version_18_batch_session_and_work_item_rows(
    tmp_path: Path,
) -> None:
    connection = _create_runtime_at_version(tmp_path, 18)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s', 'w1', 'question.curate', 1, 'S')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('r', 's', 'completed')"
    )
    connection.execute(
        "INSERT INTO review_question_batches "
        "(id, workspace_id, session_id, origin_session_id, run_id, "
        "source_refs_json, status) "
        "VALUES ('b', 'w1', 's', 's', 'r', '[\"source-1\"]', 'completed')"
    )
    connection.execute(
        "INSERT INTO review_curation_sessions "
        "(session_id, workspace_id, source_refs_json, active_batch_id, stage) "
        "VALUES ('s', 'w1', '[\"source-1\"]', 'b', 'completed')"
    )
    connection.execute(
        "INSERT INTO review_curation_work_items "
        "(id, batch_id, stage, unit_index, input_digest, source_refs_json, "
        "status, output_json, attempt_count) "
        "VALUES ('wi', 'b', 'discovery', 0, ?, '[\"source-1#section-0001\"]', "
        "'completed', '{\"seeds\":[]}', 1)",
        ("a" * 64,),
    )
    connection.execute(
        "INSERT INTO review_question_candidates "
        "(id, batch_id, question_json, status) "
        "VALUES ('candidate', 'b', '{}', 'draft')"
    )
    connection.execute(
        "INSERT INTO review_question_source_links "
        "(id, question_id, source_id, batch_id, session_id, origin_session_id, "
        "evidence_ref, merge_reason) VALUES "
        "('link', 'question-1', 'source-1', 'b', 's', 's', 'source-1#1', 'keep')"
    )
    connection.commit()
    connection.close()

    reopened = connect_runtime_database(tmp_path)

    assert tuple(
        reopened.execute(
            "SELECT id, status, version, control_intent, concurrency_limit "
            "FROM review_question_batches WHERE id = 'b'"
        ).fetchone()
    ) == ("b", "completed", 1, None, 3)
    assert tuple(
        reopened.execute(
            "SELECT id, processor_kind, status, output_json, attempt_count "
            "FROM review_curation_work_items WHERE id = 'wi'"
        ).fetchone()
    ) == ("wi", "model", "completed", '{"seeds":[]}', 1)
    assert reopened.execute(
        "SELECT stage FROM review_curation_sessions WHERE session_id = 's'"
    ).fetchone()[0] == "completed"
    assert reopened.execute(
        "SELECT COUNT(*) FROM review_question_candidates WHERE batch_id = 'b'"
    ).fetchone()[0] == 1
    assert reopened.execute(
        "SELECT COUNT(*) FROM review_question_source_links WHERE batch_id = 'b'"
    ).fetchone()[0] == 1
    assert reopened.execute("PRAGMA foreign_key_check").fetchall() == []
    reopened.close()


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

    assert R2_TABLES | R2_SESSION_EXPERIENCE_TABLES | R2_PROGRESSIVE_CURATION_TABLES <= _tables(reopened)
    assert reopened.execute(
        "SELECT title FROM agent_sessions WHERE id = 'keep'"
    ).fetchone()[0] == "keep me"
    assert [
        row[0]
        for row in reopened.execute(
            "SELECT version FROM runtime_schema_migrations ORDER BY version"
        )
        ] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
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
    connection = _create_runtime_at_version(tmp_path, 15)
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
