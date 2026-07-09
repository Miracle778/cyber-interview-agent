from app.schemas.settings import ProviderConfig
from app.services import provider_registry

def test_provider_connection_marks_http_provider_ok() -> None:
    provider = ProviderConfig(
        id="p1",
        name="OpenAI Compatible",
        apiFormat="openai-compatible",
        baseUrl="https://api.example.com/v1",
        modelIds=["model-a"],
        activeModelId="model-a",
    )
    checked = provider_registry.test_provider_connection(provider)
    assert checked.connectivity_status == "ok"
