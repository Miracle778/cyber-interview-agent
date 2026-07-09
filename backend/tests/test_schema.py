from app.schemas.settings import ProviderConfig

def test_provider_schema_accepts_camel_case_json() -> None:
    provider = ProviderConfig.model_validate({
        "id": "p1",
        "name": "OpenAI Compatible",
        "apiFormat": "openai-compatible",
        "baseUrl": "https://api.example.com/v1",
        "modelIds": ["model-a"],
        "activeModelId": "model-a",
        "connectivityStatus": "unknown",
    })
    assert provider.api_format == "openai-compatible"
    assert provider.model_dump(by_alias=True)["activeModelId"] == "model-a"
