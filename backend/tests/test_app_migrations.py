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
