from fastapi.testclient import TestClient

from app.api.dependencies import get_workspace_service
from app.db.app_database import connect_app_database
from app.main import app
from app.services.workspace_service import WorkspaceService


def test_agent_diagnostics_defaults_off_and_updates(tmp_path):
    connection = connect_app_database(tmp_path / "app-data")
    app.dependency_overrides[get_workspace_service] = lambda: WorkspaceService(
        connection
    )
    try:
        with TestClient(app) as client:
            response = client.get("/api/settings/agent-diagnostics")
            assert response.status_code == 200
            assert response.json() == {
                "advancedEnabled": False,
                "updatedAt": response.json()["updatedAt"],
            }

            response = client.put(
                "/api/settings/agent-diagnostics",
                json={"advancedEnabled": True},
            )
            assert response.status_code == 200
            assert response.json()["advancedEnabled"] is True
    finally:
        app.dependency_overrides.clear()
        connection.close()


def test_agent_diagnostics_persists_across_app_database_restart(tmp_path):
    data_dir = tmp_path / "app-data"
    connection = connect_app_database(data_dir)
    service = WorkspaceService(connection)
    service.replace_agent_diagnostics_settings(advanced_enabled=True)
    connection.close()

    reopened = connect_app_database(data_dir)
    try:
        resource = WorkspaceService(reopened).get_agent_diagnostics_settings()
    finally:
        reopened.close()

    assert resource.advanced_enabled is True


def test_agent_diagnostics_rejects_non_boolean_body(tmp_path):
    connection = connect_app_database(tmp_path / "app-data")
    app.dependency_overrides[get_workspace_service] = lambda: WorkspaceService(
        connection
    )
    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/settings/agent-diagnostics",
                json={"advancedEnabled": "yes"},
            )
    finally:
        app.dependency_overrides.clear()
        connection.close()

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
