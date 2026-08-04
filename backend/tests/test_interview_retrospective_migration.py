from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db.app_database import connect_app_database
from app.infrastructure.runtime_database import connect_runtime_database


RETROSPECTIVE_TABLES = {
    "interview_retrospectives",
    "interview_source_versions",
    "interview_cleanup_versions",
    "interview_cleanup_work_items",
    "interview_segments",
    "interview_question_units",
    "interview_analysis_runs",
    "interview_analysis_work_items",
    "interview_question_analyses",
    "interview_gaps",
    "interview_asset_candidates",
    "interview_action_items",
    "interview_write_receipts",
    "interview_retrospective_corrections",
    "interview_corrections",
    "interview_transcript_review_issues",
}


def test_runtime_migration_adds_versioned_retrospective_domain(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    try:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        migrations = [
            row["version"]
            for row in connection.execute(
                "SELECT version FROM runtime_schema_migrations ORDER BY version"
            )
        ]
        source_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(interview_source_versions)"
            )
        }
    finally:
        connection.close()

    assert RETROSPECTIVE_TABLES <= tables
    assert migrations == list(range(1, 54))
    assert "recording_coverage" in source_columns


def test_runtime_migration_adds_clean_transcript_document_artifact(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    try:
        cleanup_columns = {
            row["name"]: row
            for row in connection.execute(
                "PRAGMA table_info(interview_cleanup_versions)"
            )
        }
        issue_columns = {
            row["name"]: row
            for row in connection.execute(
                "PRAGMA table_info(interview_transcript_review_issues)"
            )
        }
        issue_foreign_keys = {
            (row["from"], row["table"], row["on_delete"])
            for row in connection.execute(
                "PRAGMA foreign_key_list(interview_transcript_review_issues)"
            )
        }
    finally:
        connection.close()

    assert {"document_body", "document_sha256"} <= cleanup_columns.keys()
    assert {
        "cleanup_version_id",
        "ordinal",
        "document_start",
        "document_end",
        "excerpt",
        "suggestion",
        "issue_kind",
        "reason",
        "confidence",
        "decision",
    } <= issue_columns.keys()
    assert (
        "cleanup_version_id",
        "interview_cleanup_versions",
        "CASCADE",
    ) in issue_foreign_keys


def test_runtime_migration_adds_cleanup_correction_audit_fields(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    try:
        columns = {
            row["name"]: row
            for row in connection.execute("PRAGMA table_info(interview_corrections)")
        }
        foreign_keys = {
            (row["from"], row["table"], row["on_delete"])
            for row in connection.execute("PRAGMA foreign_key_list(interview_corrections)")
        }
    finally:
        connection.close()

    assert {
        "cleanup_version_id",
        "segment_id",
        "source_start",
        "source_end",
        "original_text",
        "suggested_text",
        "adopted_text",
        "change_type",
        "risk_level",
        "reason",
        "confidence",
        "decision",
    } <= columns.keys()
    assert (
        "cleanup_version_id",
        "interview_cleanup_versions",
        "CASCADE",
    ) in foreign_keys
    assert ("segment_id", "interview_segments", "CASCADE") in foreign_keys


def test_app_migration_backfills_retrospective_model_roles(
    tmp_path: Path,
) -> None:
    _create_app_database_at_version_8(tmp_path)

    connection = connect_app_database(tmp_path)
    try:
        bindings = dict(
            connection.execute(
                "SELECT role, provider_model_id FROM workspace_model_bindings "
                "WHERE workspace_id = 'w1'"
            )
        )
    finally:
        connection.close()

    assert bindings == {
        "agent_chat": "m-chat",
        "job_analysis": "m-analysis",
        "project_deep_dive": "m-chat",
        "retrospective_analysis": "m-analysis",
        "retrospective_chat": "m-chat",
    }


def _create_app_database_at_version_8(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(data_dir / "app.sqlite")
    migrations_dir = Path(__file__).parents[1] / "app" / "db" / "migrations" / "app"
    connection.execute(
        "CREATE TABLE schema_migrations ("
        "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    for migration in sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(migration.name.split("_", 1)[0])
        if version > 8:
            continue
        connection.executescript(migration.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (?, CURRENT_TIMESTAMP)",
            (version,),
        )
    connection.execute(
        "INSERT INTO workspaces(id, root_path, available) VALUES ('w1', '/tmp/w1', 1)"
    )
    connection.execute(
        "INSERT INTO providers("
        "id, name, api_format, base_url, secret_source, secret_ref, enabled"
        ") VALUES ("
        "'p1', 'Provider', 'openai-compatible', 'https://example.test/v1', "
        "'keyring', 'provider-ref', 1)"
    )
    connection.execute(
        "INSERT INTO provider_models("
        "id, provider_id, model_id, display_name, enabled, max_input_tokens"
        ") VALUES "
        "('m-analysis', 'p1', 'analysis', 'Analysis', 1, 128000), "
        "('m-chat', 'p1', 'chat', 'Chat', 1, 128000)"
    )
    connection.executemany(
        "INSERT INTO workspace_model_bindings("
        "workspace_id, role, provider_model_id"
        ") VALUES ('w1', ?, ?)",
        (
            ("agent_chat", "m-chat"),
            ("job_analysis", "m-analysis"),
            ("project_deep_dive", "m-chat"),
        ),
    )
    connection.commit()
    connection.close()
