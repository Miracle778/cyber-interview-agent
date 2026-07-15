from app.db.app_database import connect_app_database


def test_app_database_applies_initial_schema(tmp_path):
    connection = connect_app_database(tmp_path)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "providers",
        "provider_models",
        "workspaces",
        "workspace_model_bindings",
        "provider_test_runs",
    } <= tables
    model_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(provider_models)")
    }
    assert "max_input_tokens" in model_columns


def test_app_database_reopens_without_reapplying_migration(tmp_path):
    connect_app_database(tmp_path).close()
    connection = connect_app_database(tmp_path)
    rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
    assert [row["version"] for row in rows] == [1, 2]
