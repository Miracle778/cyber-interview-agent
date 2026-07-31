from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.dependencies import get_workspace_service
from app.db.app_database import connect_app_database
from app.main import app
from app.services.workspace_service import WorkspaceService


def _override(connection):
    app.dependency_overrides[get_workspace_service] = lambda: WorkspaceService(
        connection
    )


def test_quality_eval_settings_defaults_bounds_and_nullable_model(tmp_path) -> None:
    connection = connect_app_database(tmp_path / "app-data")
    _override(connection)
    try:
        with TestClient(app) as client:
            response = client.get("/api/settings/agent-quality-evaluation")
            assert response.status_code == 200
            assert response.json() == {
                "enabled": False,
                "captureRegressionInputs": False,
                "automaticSamplePercent": 5,
                "automaticDailyCap": 20,
                "judgeProviderModelId": None,
                "updatedAt": response.json()["updatedAt"],
            }
            invalid = client.put(
                "/api/settings/agent-quality-evaluation",
                json={
                    "enabled": True,
                    "captureRegressionInputs": True,
                    "automaticSamplePercent": 101,
                    "automaticDailyCap": 20,
                    "judgeProviderModelId": None,
                },
            )
            assert invalid.status_code == 422
    finally:
        app.dependency_overrides.clear()
        connection.close()


def test_quality_eval_settings_validate_model_and_persist_restart(tmp_path) -> None:
    data_dir = tmp_path / "app-data"
    connection = connect_app_database(data_dir)
    service = WorkspaceService(connection)
    with service._transaction():
        provider = service.providers.create_provider(
            name="Judge Provider",
            api_format="openai-compatible",
            base_url="https://example.test/v1",
            secret_source="environment",
            secret_ref="JUDGE_API_KEY",
        )
        model = service.providers.create_model(
            provider.id,
            "judge-model",
            "Judge Model",
        )
    _override(connection)
    try:
        with TestClient(app) as client:
            missing = client.put(
                "/api/settings/agent-quality-evaluation",
                json={
                    "enabled": True,
                    "automaticSamplePercent": 10,
                    "automaticDailyCap": 30,
                    "judgeProviderModelId": "missing-model",
                },
            )
            assert missing.status_code == 404

            saved = client.put(
                "/api/settings/agent-quality-evaluation",
                json={
                    "enabled": True,
                    "captureRegressionInputs": True,
                    "automaticSamplePercent": 10,
                    "automaticDailyCap": 30,
                    "judgeProviderModelId": model.id,
                },
            )
            assert saved.status_code == 200
            assert saved.json()["judgeProviderModelId"] == model.id
            assert saved.json()["captureRegressionInputs"] is True
    finally:
        app.dependency_overrides.clear()
        connection.close()

    reopened = connect_app_database(data_dir)
    try:
        resource = WorkspaceService(
            reopened
        ).get_agent_quality_evaluation_settings()
        assert resource.enabled is True
        assert resource.capture_regression_inputs is True
        assert resource.automatic_sample_percent == 10
        assert resource.automatic_daily_cap == 30
        assert resource.judge_provider_model_id == model.id
    finally:
        reopened.close()
