import sqlite3
from pathlib import Path

from app.agents.context import AgentContext
from app.application.session_service import ProductRepository
from app.application.workspace_runtime import SqliteMiddlewareProjection
from app.middleware.usage import ContextUsageProjection

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
    "review_curation_command_receipts",
    "review_curation_sessions",
    "review_question_source_links",
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
    ] == [1, 2, 3, 4, 5, 6, 7]
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
    ] == [1, 2, 3, 4, 5, 6, 7]
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
