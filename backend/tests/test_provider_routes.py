import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_provider_service, get_workspace_service
from app.db.app_database import connect_app_database
from app.main import app
from app.providers.base import FakeProviderAdapter
from app.services.provider_service import ProviderService
from app.services.secrets import FakeSecretStore
from app.services.workspace_service import WorkspaceService


@pytest.fixture
def client(tmp_path):
    connection = connect_app_database(tmp_path / "app-data")
    provider_service = ProviderService(
        connection=connection,
        secret_stores={
            "keyring": FakeSecretStore(),
            "environment": FakeSecretStore(),
        },
        adapters={
            "openai-compatible": FakeProviderAdapter(),
            "anthropic-compatible": FakeProviderAdapter(),
        },
    )
    app.dependency_overrides[get_provider_service] = lambda: provider_service
    app.dependency_overrides[get_workspace_service] = lambda: WorkspaceService(
        connection
    )
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        connection.close()


def _create_provider(client: TestClient) -> dict:
    response = client.post(
        "/api/settings/providers",
        json={
            "name": "P",
            "apiFormat": "openai-compatible",
            "baseUrl": "https://example.test/v1",
            "apiKey": "sk-secret",
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_model(client: TestClient, provider_id: str) -> dict:
    response = client.post(
        f"/api/settings/providers/{provider_id}/models",
        json={"modelId": "model-a", "displayName": "Model A"},
    )
    assert response.status_code == 201
    return response.json()


def test_create_provider_returns_redacted_camel_case_resource(client):
    provider = _create_provider(client)

    assert provider["hasSecret"] is True
    assert provider["apiFormat"] == "openai-compatible"
    assert provider["baseUrl"] == "https://example.test/v1"
    assert "apiKey" not in provider
    assert "secretRef" not in provider
    assert "sk-secret" not in str(provider)

    response = client.get("/api/settings/providers")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [provider["id"]]


def test_provider_model_resource_workflow_and_not_found(client):
    provider = _create_provider(client)
    model = _create_model(client, provider["id"])

    response = client.patch(
        f"/api/settings/provider-models/{model['id']}",
        json={"displayName": "Renamed"},
    )
    assert response.status_code == 200
    assert response.json()["displayName"] == "Renamed"

    response = client.post(f"/api/settings/provider-models/{model['id']}/test")
    assert response.status_code == 200
    assert response.json()["connectivityStatus"] == "ok"

    response = client.delete("/api/settings/provider-models/missing")
    assert response.status_code == 404
    assert response.json()["code"] == "provider_model_not_found"


def test_delete_bound_model_returns_conflict(client, tmp_path):
    provider = _create_provider(client)
    model = _create_model(client, provider["id"])
    workspace = client.post(
        "/api/settings/workspaces",
        json={"rootPath": str(tmp_path / "workspace")},
    ).json()
    bindings = {
        "question_generation": model["id"],
        "answer_evaluation": model["id"],
        "report_summarization": model["id"],
        "agent_chat": model["id"],
    }
    response = client.put(
        f"/api/settings/workspaces/{workspace['id']}/model-bindings",
        json={"bindings": bindings},
    )
    assert response.status_code == 200

    response = client.delete(f"/api/settings/provider-models/{model['id']}")
    assert response.status_code == 409
    assert response.json()["code"] == "resource_in_use"
    assert workspace["id"] in response.json()["message"]
    assert "answer_evaluation" in response.json()["message"]


def test_workspace_register_relink_and_replace_bindings(client, tmp_path):
    provider = _create_provider(client)
    first_model = _create_model(client, provider["id"])
    second_model = client.post(
        f"/api/settings/providers/{provider['id']}/models",
        json={"modelId": "model-b", "displayName": "Model B"},
    ).json()

    root = tmp_path / "workspace"
    response = client.post(
        "/api/settings/workspaces", json={"rootPath": str(root)}
    )
    assert response.status_code == 201
    workspace = response.json()
    assert workspace["rootPath"] == str(root.resolve())
    assert workspace["vaultPath"] == str((root / "knowledge-vault").resolve())
    assert workspace["available"] is True

    repeated = client.post(
        "/api/settings/workspaces", json={"rootPath": str(root)}
    ).json()
    assert repeated["id"] == workspace["id"]

    response = client.get("/api/settings/workspaces")
    assert [item["id"] for item in response.json()] == [workspace["id"]]

    initial = {
        "question_generation": first_model["id"],
        "answer_evaluation": first_model["id"],
        "report_summarization": first_model["id"],
        "agent_chat": first_model["id"],
    }
    response = client.put(
        f"/api/settings/workspaces/{workspace['id']}/model-bindings",
        json={"bindings": initial},
    )
    assert response.status_code == 200
    assert response.json()["bindings"] == initial

    replacement = {**initial, "agent_chat": second_model["id"]}
    response = client.put(
        f"/api/settings/workspaces/{workspace['id']}/model-bindings",
        json={"bindings": replacement},
    )
    assert response.status_code == 200
    assert response.json()["bindings"] == replacement

    moved = tmp_path / "moved"
    response = client.post(
        f"/api/settings/workspaces/{workspace['id']}/relink",
        json={"rootPath": str(moved)},
    )
    assert response.status_code == 200
    assert response.json()["id"] == workspace["id"]
    assert response.json()["rootPath"] == str(moved.resolve())


def test_legacy_workspace_endpoints_use_persistent_service(client, tmp_path):
    root = tmp_path / "legacy"
    response = client.post(
        "/api/settings/workspace", json={"workspacePath": str(root)}
    )
    assert response.status_code == 200
    created = response.json()
    assert created["id"]
    assert created["workspacePath"] == str(root.resolve())
    assert created["vaultPath"] == str((root / "knowledge-vault").resolve())

    response = client.get("/api/settings/workspace")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["workspacePath"] == str(root.resolve())


def test_workspace_bindings_require_all_four_roles(client, tmp_path):
    workspace = client.post(
        "/api/settings/workspaces",
        json={"rootPath": str(tmp_path / "workspace")},
    ).json()

    response = client.put(
        f"/api/settings/workspaces/{workspace['id']}/model-bindings",
        json={"bindings": {"agent_chat": "model-1"}},
    )
    assert response.status_code == 422
