from app.db.app_database import connect_app_database


def test_app_migration_007_creates_local_agent_diagnostics_singleton(tmp_path):
    connection = connect_app_database(tmp_path)
    try:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(agent_diagnostics_settings)"
            )
        }
        row = connection.execute(
            "SELECT advanced_enabled FROM agent_diagnostics_settings "
            "WHERE singleton = 1"
        ).fetchone()
        migration = connection.execute(
            "SELECT version FROM schema_migrations WHERE version = 7"
        ).fetchone()
    finally:
        connection.close()

    assert columns == {"singleton", "advanced_enabled", "updated_at"}
    assert row is not None
    assert row["advanced_enabled"] == 0
    assert migration is not None


def test_app_migration_008_creates_quality_evaluation_settings(tmp_path):
    connection = connect_app_database(tmp_path)
    try:
        row = connection.execute(
            "SELECT enabled, automatic_sample_percent, automatic_daily_cap, "
            "judge_provider_model_id FROM agent_quality_eval_settings "
            "WHERE singleton = 1"
        ).fetchone()
        migration = connection.execute(
            "SELECT version FROM schema_migrations WHERE version = 8"
        ).fetchone()
    finally:
        connection.close()

    assert dict(row) == {
        "enabled": 0,
        "automatic_sample_percent": 5,
        "automatic_daily_cap": 20,
        "judge_provider_model_id": None,
    }
    assert migration is not None


def test_app_migration_009_disables_regression_input_capture_by_default(tmp_path):
    connection = connect_app_database(tmp_path)
    try:
        row = connection.execute(
            "SELECT capture_regression_inputs FROM agent_quality_eval_settings "
            "WHERE singleton = 1"
        ).fetchone()
        migration = connection.execute(
            "SELECT version FROM schema_migrations WHERE version = 9"
        ).fetchone()
    finally:
        connection.close()

    assert row["capture_regression_inputs"] == 0
    assert migration is not None
