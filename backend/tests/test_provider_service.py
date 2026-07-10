import pytest

from app.db.app_database import connect_app_database
from app.repositories.provider_repository import ProviderRepository


@pytest.fixture
def app_connection(tmp_path):
    connection = connect_app_database(tmp_path)
    try:
        yield connection
    finally:
        connection.close()


def test_provider_repository_round_trips_multiple_models(app_connection):
    repository = ProviderRepository(app_connection)
    provider = repository.create_provider(name="Local", api_format="openai-compatible", base_url="http://127.0.0.1:11434/v1", secret_source="environment", secret_ref="OLLAMA_KEY")
    first = repository.create_model(provider.id, "model-a", "Model A")
    second = repository.create_model(provider.id, "model-b", "Model B")
    loaded = repository.get_provider(provider.id)
    assert [model.model_id for model in loaded.models] == [first.model_id, second.model_id]
