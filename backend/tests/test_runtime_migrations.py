import sqlite3
from pathlib import Path

import pytest

from app.agents.context import AgentContext
from app.application.session_service import ProductRepository
from app.application.workspace_runtime import SqliteMiddlewareProjection
from app.infrastructure import runtime_database
from app.infrastructure.runtime_database import (
    connect_runtime_database,
    runtime_database_path,
)
from app.middleware.usage_projection_middleware import ContextUsageProjection


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
    "review_question_assistance",
    "review_auxiliary_turn_receipts",
    "review_round_control_receipts",
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
    "review_curation_batch_candidates",
    "review_curation_control_receipts",
    "review_curation_finalizations",
    "review_curation_staged_drafts",
    "review_curation_work_items",
    "review_curation_seed_tasks",
    "review_curation_seed_retry_receipts",
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
    "profile_agent_context",
}

JOB_TARGET_TABLES = {
    "job_targets",
    "job_document_versions",
    "job_requirements",
    "job_requirement_evidence_links",
    "job_analysis_runs",
    "job_analysis_work_items",
    "job_target_project_priorities",
    "project_deep_dives",
    "project_narrative_sections",
    "project_deep_dive_artifacts",
    "project_gaps",
    "project_question_candidates",
}

OBSERVABILITY_TABLES = {
    "agent_trace_files",
    "agent_trace_executions",
    "agent_trace_operations",
    "agent_trace_events",
    "agent_trace_retention_policy",
    "agent_trace_cleanup_runs",
    "agent_trace_cleanup_items",
    "agent_trace_projection_deliveries",
}

EVALUATION_TABLES = {
    "agent_eval_runs",
    "agent_eval_dimension_results",
    "agent_eval_human_feedback",
    "agent_eval_regression_cases",
    "agent_eval_daily_counters",
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


def _seed_version_24_committed_revision(connection) -> None:
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-revision', 'w1', 'question.revise', 1, 'Revision')"
    )
    connection.executemany(
        "INSERT INTO agent_runs (id, session_id, status) VALUES (?, ?, ?)",
        (
            ("run-origin", "session-revision", "interrupted"),
            ("run-rewrite", "session-revision", "completed"),
        ),
    )
    connection.execute(
        "INSERT INTO review_question_batches "
        "(id, workspace_id, session_id, origin_session_id, run_id, "
        "source_refs_json, status) VALUES "
        "('batch-origin', 'w1', 'session-revision', 'session-revision', "
        "'run-origin', '[\"source-1\"]', 'review_pending')"
    )
    connection.execute(
        "INSERT INTO review_question_batches "
        "(id, workspace_id, session_id, origin_session_id, run_id, "
        "source_refs_json, rewrite_of_batch_id, status) VALUES "
        "('batch-rewrite', 'w1', 'session-revision', 'session-revision', "
        "'run-rewrite', '[\"source-1\"]', 'batch-origin', "
        "'review_pending')"
    )
    connection.execute(
        "INSERT INTO knowledge_drafts "
        "(id, workspace_id, session_id, run_id, domain, document_type, "
        "document_id, title, content_path, content_hash, status, version) "
        "VALUES ('draft-revision', 'w1', 'session-revision', 'run-rewrite', "
        "'review', 'question', 'doc-revision', 'Revision', "
        "'artifacts/review/drafts/draft-revision.md', ?, "
        "'review_pending', 2)",
        ("a" * 64,),
    )
    connection.execute(
        "INSERT INTO review_question_candidates "
        "(id, batch_id, draft_id, question_json, status) VALUES "
        "('candidate-revision', 'batch-origin', 'draft-revision', '{}', "
        "'review_pending')"
    )
    connection.execute(
        "INSERT INTO review_curation_finalizations "
        "(batch_id, execution_id, batch_version, state, "
        "candidate_ids_json) VALUES "
        "('batch-rewrite', 'run-rewrite', 1, 'committed', "
        "'[\"candidate-revision\"]')"
    )
    connection.commit()


def test_fresh_database_applies_all_runtime_migrations(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)

    assert (
        R2_TABLES
        | R2_SESSION_EXPERIENCE_TABLES
        | R2_PROGRESSIVE_CURATION_TABLES
        | JOB_TARGET_TABLES
        | OBSERVABILITY_TABLES
        | EVALUATION_TABLES
        <= _tables(connection)
    )
    assert [
        row[0]
        for row in connection.execute(
            "SELECT version FROM runtime_schema_migrations ORDER BY version"
        )
        ] == list(range(1, 44))
    assert "agent_context_usage" in _tables(connection)
    assert "profile_deletion_plans" in _tables(connection)
    assert "deleted_at" in {
        row[1] for row in connection.execute("PRAGMA table_info(profile_materials)")
    }
    connection.close()


def test_migration_034_repairs_review_assistance_tables_missing_from_applied_031(
    tmp_path: Path,
) -> None:
    legacy = _create_runtime_at_version(tmp_path, 33)
    legacy.execute("DROP TABLE review_auxiliary_turn_receipts")
    legacy.execute("DROP TABLE review_question_assistance")
    legacy.commit()
    legacy.close()

    repaired = connect_runtime_database(tmp_path)

    assert {
        "review_question_assistance",
        "review_auxiliary_turn_receipts",
    } <= _tables(repaired)
    assert repaired.execute(
        "SELECT name FROM runtime_schema_migrations WHERE version = 34"
    ).fetchone()[0] == "034_repair_review_assistance_tables.sql"
    repaired.close()


def test_migration_041_adds_v2_evaluation_fields_without_rewriting_v1_rows(
    tmp_path: Path,
) -> None:
    legacy = _create_runtime_at_version(tmp_path, 40)
    legacy.execute(
        "INSERT INTO agent_eval_runs "
        "(id, workspace_id, execution_id, eval_pack_id, eval_pack_version, "
        "trigger, frozen_input_hash, snapshot_json, idempotency_key) "
        "VALUES ('eval-v1', 'workspace-1', 'execution-1', 'review.v1', 1, "
        "'manual', ?, '{\"safe\":true}', 'manual-v1')",
        ("a" * 64,),
    )
    legacy.execute(
        "INSERT INTO agent_eval_dimension_results "
        "(eval_run_id, dimension_id, source, status, score, confidence, summary) "
        "VALUES ('eval-v1', 'key_point_coverage', 'judge', 'scored', 80, 0.8, "
        "'legacy result')"
    )
    legacy.commit()
    legacy.close()

    migrated = connect_runtime_database(tmp_path)
    run = migrated.execute(
        "SELECT evaluation_contract_version, task_type, run_kind, "
        "business_outcome_hash, judge_data_scope_json "
        "FROM agent_eval_runs WHERE id = 'eval-v1'"
    ).fetchone()
    dimension = migrated.execute(
        "SELECT applicability, rating, severity, evidence_gaps_json "
        "FROM agent_eval_dimension_results WHERE eval_run_id = 'eval-v1'"
    ).fetchone()

    assert tuple(run) == (1, "legacy", "historical_review", None, "{}")
    assert tuple(dimension) == ("applicable", None, None, "[]")
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
    migrated.close()


def test_current_runtime_schema_opens_while_another_writer_is_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialized = connect_runtime_database(tmp_path)
    initialized.close()
    database_path = runtime_database_path(tmp_path)
    writer = sqlite3.connect(database_path)
    writer.execute("BEGIN IMMEDIATE")
    original_open = runtime_database._open_connection

    def open_with_short_timeout(path: Path) -> sqlite3.Connection:
        connection = original_open(path)
        connection.execute("PRAGMA busy_timeout = 1")
        return connection

    monkeypatch.setattr(
        runtime_database, "_open_connection", open_with_short_timeout
    )
    try:
        checked = connect_runtime_database(tmp_path)
        assert checked.execute("SELECT 1").fetchone()[0] == 1
        checked.close()
    finally:
        writer.rollback()
        writer.close()


def test_job_target_migration_adds_attempt_and_project_question_fields(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    run_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(agent_runs)")
    }
    message_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(agent_messages)")
    }
    catalog_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(review_question_catalog)"
        )
    }
    candidate_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(review_question_candidates)"
        )
    }

    assert {"input_message_id", "retry_of_execution_id"} <= run_columns
    assert {"replaces_message_id", "resolution_status"} <= message_columns
    project_fields = {
        "question_type",
        "project_claim_id",
        "project_dimension",
        "source_job_target_id",
        "source_deep_dive_id",
    }
    assert project_fields <= catalog_columns
    assert project_fields <= candidate_columns


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


def test_migration_024_adds_stable_resume_execution_reservation(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)

    receipt_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(review_curation_control_receipts)"
        )
    }
    assert "reserved_execution_id" in receipt_columns
    indexes = {
        row[1]
        for row in connection.execute(
            "PRAGMA index_list(review_curation_control_receipts)"
        )
    }
    assert "idx_review_curation_control_receipts_reserved_execution" in indexes
    connection.close()


def test_migration_025_backfills_candidate_batch_revision_membership(
    tmp_path: Path,
) -> None:
    connection = _create_runtime_at_version(tmp_path, 24)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-membership', 'w1', 'question.revise', 1, 'Revision')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('run-membership', 'session-membership', 'completed')"
    )
    connection.execute(
        "INSERT INTO review_question_batches "
        "(id, workspace_id, session_id, origin_session_id, run_id, "
        "source_refs_json, status) VALUES "
        "('batch-membership', 'w1', 'session-membership', "
        "'session-membership', 'run-membership', '[\"source-1\"]', "
        "'review_pending')"
    )
    connection.execute(
        "INSERT INTO knowledge_drafts "
        "(id, workspace_id, session_id, run_id, domain, document_type, "
        "document_id, title, content_path, content_hash, status) "
        "VALUES ('draft-membership', 'w1', 'session-membership', "
        "'run-membership', 'review', 'question', 'doc-membership', "
        "'Membership', 'artifacts/review/drafts/draft-membership.md', ?, "
        "'review_pending')",
        ("b" * 64,),
    )
    connection.execute(
        "INSERT INTO review_question_candidates "
        "(id, batch_id, draft_id, question_json, status) VALUES "
        "('candidate-membership', 'batch-membership', "
        "'draft-membership', '{}', "
        "'review_pending')"
    )
    connection.commit()
    connection.close()

    migrated = connect_runtime_database(tmp_path)

    assert tuple(migrated.execute(
        "SELECT batch_id, candidate_id, draft_id "
        "FROM review_curation_batch_candidates"
    ).fetchone()) == (
        "batch-membership",
        "candidate-membership",
        "draft-membership",
    )
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
    migrated.close()


def test_migration_025_recovers_committed_revision_without_reassigning_origin(
    tmp_path: Path,
) -> None:
    connection = _create_runtime_at_version(tmp_path, 24)
    _seed_version_24_committed_revision(connection)
    connection.close()

    migrated = connect_runtime_database(tmp_path)

    assert [tuple(row) for row in migrated.execute(
        "SELECT batch_id, candidate_id, draft_id "
        "FROM review_curation_batch_candidates "
        "WHERE candidate_id = 'candidate-revision' ORDER BY batch_id"
    )] == [
        ("batch-rewrite", "candidate-revision", "draft-revision")
    ]
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
    migrated.close()


def test_migration_025_does_not_infer_membership_after_session_hard_delete(
    tmp_path: Path,
) -> None:
    connection = _create_runtime_at_version(tmp_path, 24)
    _seed_version_24_committed_revision(connection)

    connection.execute(
        "DELETE FROM agent_sessions WHERE id = 'session-revision'"
    )
    connection.commit()

    assert connection.execute(
        "SELECT COUNT(*) FROM review_curation_finalizations"
    ).fetchone()[0] == 0
    assert [tuple(row) for row in connection.execute(
        "SELECT id, run_id FROM review_question_batches ORDER BY id"
    )] == [
        ("batch-origin", None),
        ("batch-rewrite", None),
    ]
    assert connection.execute(
        "SELECT run_id FROM knowledge_drafts WHERE id = 'draft-revision'"
    ).fetchone()[0] is None
    connection.close()

    migrated = connect_runtime_database(tmp_path)

    assert migrated.execute(
        "SELECT COUNT(*) FROM review_curation_batch_candidates "
        "WHERE candidate_id = 'candidate-revision'"
    ).fetchone()[0] == 0
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
    migrated.close()


def test_migration_026_adds_seed_state_and_backfills_candidate_quality(
    tmp_path: Path,
) -> None:
    connection = _create_runtime_at_version(tmp_path, 25)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s26', 'w1', 'question.curate', 1, 'Curation')"
    )
    connection.execute(
        "INSERT INTO review_question_batches "
        "(id, workspace_id, session_id, origin_session_id, source_refs_json, status) "
        "VALUES ('b26', 'w1', 's26', 's26', '[\"source-1\"]', 'review_pending')"
    )
    connection.execute(
        "INSERT INTO review_curation_work_items "
        "(id, batch_id, stage, unit_index, input_digest, source_refs_json, "
        "processor_kind, status, output_json) VALUES "
        "('wi26', 'b26', 'discovery', 0, ?, '[\"source-1#section-1\"]', "
        "'model', 'completed', '{\"seeds\":[]}')",
        ("a" * 64,),
    )
    connection.execute(
        "INSERT INTO review_question_candidates "
        "(id, batch_id, question_json, status) "
        "VALUES ('candidate26', 'b26', '{}', 'review_pending')"
    )
    connection.commit()
    connection.close()

    migrated = connect_runtime_database(tmp_path)

    assert {
        "review_curation_seed_tasks",
        "review_curation_seed_retry_receipts",
    } <= _tables(migrated)
    seed_columns = {
        row[1]
        for row in migrated.execute("PRAGMA table_info(review_curation_seed_tasks)")
    }
    assert {
        "id",
        "batch_id",
        "discovery_work_item_id",
        "seed_key",
        "seed_ordinal",
        "question_text",
        "primary_source_ref",
        "source_refs_json",
        "input_digest",
        "status",
        "automatic_attempt_count",
        "manual_attempt_count",
        "candidate_json",
        "answer_basis",
        "material_support",
        "needs_review",
        "normalization_issues_json",
        "source_answer",
        "supplemental_answer",
        "last_error_code",
        "version",
        "created_at",
        "updated_at",
    } == seed_columns
    receipt_columns = {
        row[1]
        for row in migrated.execute(
            "PRAGMA table_info(review_curation_seed_retry_receipts)"
        )
    }
    assert receipt_columns == {
        "id",
        "seed_task_id",
        "idempotency_key",
        "request_digest",
        "execution_id",
        "result_status",
        "created_at",
        "updated_at",
    }
    candidate_columns = {
        row[1]
        for row in migrated.execute("PRAGMA table_info(review_question_candidates)")
    }
    assert {
        "seed_task_id",
        "answer_basis",
        "material_support",
        "needs_review",
        "normalization_issues_json",
    } <= candidate_columns
    assert tuple(
        migrated.execute(
            "SELECT seed_task_id, answer_basis, material_support, needs_review, "
            "normalization_issues_json FROM review_question_candidates "
            "WHERE id = 'candidate26'"
        ).fetchone()
    ) == (None, "unknown", "unknown", 1, '["legacy_quality_unknown"]')
    indexes = {
        row[0]
        for row in migrated.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }
    assert {
        "ux_review_curation_seed_tasks_batch_key",
        "idx_review_curation_seed_tasks_batch_status_ordinal",
        "idx_review_curation_seed_retry_receipts_seed_created",
        "ux_review_question_candidates_seed_task",
    } <= indexes
    migrated.execute(
        "INSERT INTO review_curation_seed_tasks "
        "(id, batch_id, discovery_work_item_id, seed_key, seed_ordinal, "
        "question_text, primary_source_ref, source_refs_json, input_digest) "
        "VALUES ('seed26', 'b26', 'wi26', ?, 0, 'Q', "
        "'source-1#section-1', '[\"source-1#section-1\"]', ?)",
        ("d" * 64, "e" * 64),
    )
    migrated.execute(
        "UPDATE review_question_candidates SET seed_task_id = 'seed26' "
        "WHERE id = 'candidate26'"
    )
    migrated.execute("DELETE FROM review_curation_seed_tasks WHERE id = 'seed26'")
    assert migrated.execute(
        "SELECT seed_task_id FROM review_question_candidates "
        "WHERE id = 'candidate26'"
    ).fetchone()[0] is None
    assert migrated.execute(
        "SELECT COUNT(*) FROM review_curation_work_items WHERE id = 'wi26'"
    ).fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute(
            "INSERT INTO review_curation_seed_tasks "
            "(id, batch_id, discovery_work_item_id, seed_key, seed_ordinal, "
            "question_text, primary_source_ref, source_refs_json, input_digest, status) "
            "VALUES ('invalid26', 'b26', 'wi26', ?, 0, 'Q', 'source-1#section-1', "
            "'[]', ?, 'unknown')",
            ("b" * 64, "c" * 64),
        )
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute(
            "UPDATE review_question_candidates SET answer_basis = 'claimed_source' "
            "WHERE id = 'candidate26'"
        )
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
    migrated.close()


def test_migration_026_rejects_invalid_counts_json_receipts_and_seed_links(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s26-checks', 'w1', 'question.curate', 1, 'Curation')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('run26-checks', 's26-checks', 'completed')"
    )
    connection.execute(
        "INSERT INTO review_question_batches "
        "(id, workspace_id, session_id, origin_session_id, source_refs_json, status) "
        "VALUES ('b26-checks', 'w1', 's26-checks', 's26-checks', '[]', "
        "'review_pending')"
    )
    connection.execute(
        "INSERT INTO review_curation_work_items "
        "(id, batch_id, stage, unit_index, input_digest, source_refs_json, status) "
        "VALUES ('wi26-checks', 'b26-checks', 'discovery', 0, ?, '[]', "
        "'completed')",
        ("a" * 64,),
    )
    connection.execute(
        "INSERT INTO review_curation_seed_tasks "
        "(id, batch_id, discovery_work_item_id, seed_key, seed_ordinal, "
        "question_text, primary_source_ref, source_refs_json, input_digest, "
        "status) VALUES ('seed26-checks', 'b26-checks', 'wi26-checks', ?, 0, "
        "'Q', 'source#1', '[\"source#1\"]', ?, 'skipped')",
        ("b" * 64, "c" * 64),
    )
    connection.executemany(
        "INSERT INTO review_question_candidates "
        "(id, batch_id, question_json, status) VALUES (?, 'b26-checks', '{}', "
        "'review_pending')",
        (("candidate26-a",), ("candidate26-b",)),
    )
    connection.commit()

    for column, invalid_value in (
        ("automatic_attempt_count", -1),
        ("automatic_attempt_count", 3),
        ("manual_attempt_count", -1),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"UPDATE review_curation_seed_tasks SET {column} = ? "
                "WHERE id = 'seed26-checks'",
                (invalid_value,),
            )
    for column in (
        "source_refs_json",
        "candidate_json",
        "normalization_issues_json",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"UPDATE review_curation_seed_tasks SET {column} = 'not-json' "
                "WHERE id = 'seed26-checks'"
            )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE review_question_candidates "
            "SET normalization_issues_json = 'not-json' "
            "WHERE id = 'candidate26-a'"
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO review_curation_seed_retry_receipts "
            "(id, seed_task_id, idempotency_key, request_digest, execution_id) "
            "VALUES ('receipt26-bad-digest', 'seed26-checks', 'key-1', 'bad', "
            "'run26-checks')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO review_curation_seed_retry_receipts "
            "(id, seed_task_id, idempotency_key, request_digest, execution_id, "
            "result_status) VALUES ('receipt26-bad-status', 'seed26-checks', "
            "'key-2', ?, 'run26-checks', 'unknown')",
            ("d" * 64,),
        )
    connection.execute(
        "UPDATE review_question_candidates SET seed_task_id = 'seed26-checks' "
        "WHERE id = 'candidate26-a'"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE review_question_candidates SET seed_task_id = 'seed26-checks' "
            "WHERE id = 'candidate26-b'"
        )
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


def test_migration_021_tracks_private_staged_draft_files(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)

    assert {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(review_curation_staged_drafts)"
        )
    } == {
        "draft_id",
        "batch_id",
        "execution_id",
        "content_path",
        "content_hash",
        "created_at",
    }
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_migration_022_preserves_drafts_and_references_and_adds_superseded(
    tmp_path: Path,
) -> None:
    connection = _create_runtime_at_version(tmp_path, 21)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s22', 'w1', 'question.curate', 1, 'S')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('r22', 's22', 'completed')"
    )
    connection.execute(
        "INSERT INTO review_question_batches "
        "(id, workspace_id, session_id, origin_session_id, run_id, "
        "source_refs_json, status) "
        "VALUES ('b22', 'w1', 's22', 's22', 'r22', '[]', 'completed')"
    )
    connection.execute(
        "INSERT INTO knowledge_drafts "
        "(id, workspace_id, session_id, run_id, domain, document_type, "
        "document_id, title, content_path, content_hash, status) "
        "VALUES ('d22', 'w1', 's22', 'r22', 'review', 'question', "
        "'q22', 'Q', 'artifacts/review/drafts/d22.md', ?, 'review_pending')",
        ("a" * 64,),
    )
    connection.execute(
        "INSERT INTO review_question_candidates "
        "(id, batch_id, draft_id, question_json, status) "
        "VALUES ('c22', 'b22', 'd22', '{}', 'review_pending')"
    )
    connection.execute(
        "INSERT INTO pending_actions "
        "(id, workspace_id, session_id, run_id, action_type, payload_json, "
        "preview_json, status, idempotency_key) "
        "VALUES ('a22', 'w1', 's22', 'r22', 'knowledge.publish', '{}', "
        "'{}', 'approved', 'publish-d22')"
    )
    connection.execute(
        "INSERT INTO publication_runs "
        "(id, action_id, draft_id, expected_draft_version, "
        "expected_content_hash, document_id, target_path, state) "
        "VALUES ('p22', 'a22', 'd22', 1, ?, 'q22', "
        "'10_question_bank/q22.md', 'completed')",
        ("a" * 64,),
    )
    connection.commit()
    connection.close()

    reopened = connect_runtime_database(tmp_path)
    reopened.execute(
        "UPDATE knowledge_drafts SET status = 'superseded' WHERE id = 'd22'"
    )
    reopened.commit()

    assert tuple(reopened.execute(
        "SELECT id, status, content_hash FROM knowledge_drafts WHERE id = 'd22'"
    ).fetchone()) == ("d22", "superseded", "a" * 64)
    assert reopened.execute(
        "SELECT draft_id FROM review_question_candidates WHERE id = 'c22'"
    ).fetchone()[0] == "d22"
    assert reopened.execute(
        "SELECT draft_id FROM publication_runs WHERE id = 'p22'"
    ).fetchone()[0] == "d22"
    assert reopened.execute("PRAGMA foreign_key_check").fetchall() == []
    reopened.close()


def test_migration_023_preserves_publications_and_adds_transient_claim_states(
    tmp_path: Path,
) -> None:
    connection = _create_runtime_at_version(tmp_path, 22)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s23', 'w1', 'knowledge.publish', 1, 'S')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('r23', 's23', 'completed')"
    )
    connection.execute(
        "INSERT INTO knowledge_drafts "
        "(id, workspace_id, session_id, run_id, domain, document_type, "
        "document_id, title, content_path, content_hash) VALUES "
        "('d23', 'w1', 's23', 'r23', 'review', 'question', 'q23', 'Q', "
        "'artifacts/review/drafts/d23.md', 'hash23')"
    )
    connection.execute(
        "INSERT INTO pending_actions "
        "(id, workspace_id, session_id, run_id, action_type, payload_json, "
        "preview_json, status, idempotency_key) VALUES "
        "('a23', 'w1', 's23', 'r23', 'knowledge.publish', '{}', '{}', "
        "'approved', 'publish-d23')"
    )
    connection.execute(
        "INSERT INTO publication_runs "
        "(id, action_id, draft_id, expected_draft_version, "
        "expected_content_hash, document_id, target_path, state) VALUES "
        "('p23', 'a23', 'd23', 1, 'hash23', 'q23', "
        "'10_question_bank/q23.md', 'file_written')"
    )
    connection.commit()
    connection.close()

    reopened = connect_runtime_database(tmp_path)
    reopened.execute(
        "UPDATE publication_runs SET state = 'committing' WHERE id = 'p23'"
    )
    reopened.execute(
        "UPDATE publication_runs SET state = 'compensating' WHERE id = 'p23'"
    )
    reopened.commit()

    assert tuple(reopened.execute(
        "SELECT draft_id, state FROM publication_runs WHERE id = 'p23'"
    ).fetchone()) == ("d23", "compensating")
    assert reopened.execute("PRAGMA foreign_key_check").fetchall() == []
    reopened.close()


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
        ] == list(range(1, 44))
    reopened.close()


def test_published_candidates_are_backfilled_as_confirmed(
    tmp_path: Path,
) -> None:
    connection = _create_runtime_at_version(tmp_path, 32)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('legacy-session', 'w1', 'question.curate', 1, 'Legacy')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('legacy-run', 'legacy-session', 'completed')"
    )
    connection.execute(
        "INSERT INTO review_question_batches "
        "(id, workspace_id, session_id, origin_session_id, run_id, "
        "source_refs_json, status) "
        "VALUES ('legacy-batch', 'w1', 'legacy-session', 'legacy-session', 'legacy-run', "
        "'[\"source-1\"]', 'completed')"
    )
    connection.executemany(
        "INSERT INTO review_question_candidates "
        "(id, batch_id, question_json, status) VALUES (?, 'legacy-batch', '{}', ?)",
        (
            ("published-candidate", "published"),
            ("pending-candidate", "review_pending"),
        ),
    )
    connection.commit()
    connection.close()

    reopened = connect_runtime_database(tmp_path)

    published = reopened.execute(
        "SELECT confirmation_status, confirmation_version, confirmed_at "
        "FROM review_question_candidates WHERE id = 'published-candidate'"
    ).fetchone()
    pending = reopened.execute(
        "SELECT confirmation_status, confirmation_version, confirmed_at "
        "FROM review_question_candidates WHERE id = 'pending-candidate'"
    ).fetchone()
    assert tuple(published)[:2] == ("confirmed", 1)
    assert published["confirmed_at"] is not None
    assert tuple(pending) == ("pending", 0, None)
    assert reopened.execute(
        "SELECT COUNT(*) FROM review_question_candidates"
    ).fetchone()[0] == 2
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


def test_agent_trace_index_migration_is_repeatable(tmp_path: Path) -> None:
    first = connect_runtime_database(tmp_path)
    assert OBSERVABILITY_TABLES <= _tables(first)
    versions = {
        int(row[0])
        for row in first.execute(
            "SELECT version FROM runtime_schema_migrations"
        )
    }
    assert 37 in versions
    first.close()

    reopened = connect_runtime_database(tmp_path)
    assert OBSERVABILITY_TABLES <= _tables(reopened)
    assert (
        reopened.execute(
            "SELECT COUNT(*) FROM runtime_schema_migrations WHERE version = 37"
        ).fetchone()[0]
        == 1
    )
    reopened.close()


def test_agent_trace_export_migration_creates_receipt_table(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    try:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(agent_trace_exports)"
            )
        }
        migration = connection.execute(
            "SELECT name FROM runtime_schema_migrations WHERE version = 38"
        ).fetchone()
    finally:
        connection.close()

    assert {
        "id",
        "workspace_id",
        "run_id",
        "idempotency_key",
        "request_hash",
        "status",
        "artifact_relative_path",
        "artifact_sha256",
        "metadata_only",
        "includes_bodies",
        "error_code",
        "created_at",
        "completed_at",
    } <= columns
    assert migration["name"] == "038_agent_trace_exports.sql"


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


def test_profile_material_version_deletion_migration_extends_deletion_plans(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)

    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(profile_deletion_plans)")
    }
    assert {"target_kind", "target_version_id"} <= columns
    version_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(profile_material_versions)")
    }
    assert "deleted_at" in version_columns
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
