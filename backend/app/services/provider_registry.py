from app.schemas.settings import ProviderConfig

def test_provider_connection(provider: ProviderConfig) -> ProviderConfig:
    status = "ok" if provider.base_url.startswith("http") and provider.active_model_id else "failed"
    return provider.model_copy(update={"connectivity_status": status})
