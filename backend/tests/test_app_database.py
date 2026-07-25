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
    assert [row["version"] for row in rows] == [1, 2, 3, 4, 5]


def test_app_database_accepts_eight_model_roles(tmp_path):
    connection = connect_app_database(tmp_path)
    connection.execute(
        "INSERT INTO workspaces (id, root_path, available) "
        "VALUES ('w', '/tmp/ws', 1)"
    )
    connection.execute(
        "INSERT INTO providers (id, name, api_format, base_url, secret_source, "
        "secret_ref, enabled) "
        "VALUES ('p', 'P', 'openai-compatible', 'https://example.test/v1', "
        "'keyring', 'ref', 1)"
    )
    connection.execute(
        "INSERT INTO provider_models (id, provider_id, model_id, display_name, "
        "enabled, max_input_tokens) "
        "VALUES ('m', 'p', 'model-a', 'A', 1, 64000)"
    )
    for role in (
        "question_generation",
        "answer_evaluation",
        "report_summarization",
        "agent_chat",
        "profile_extraction",
        "profile_assessment",
        "job_analysis",
        "project_deep_dive",
    ):
        connection.execute(
            "INSERT INTO workspace_model_bindings "
            "(workspace_id, role, provider_model_id) VALUES ('w', ?, 'm')",
            (role,),
        )
    connection.commit()
    connection.close()
