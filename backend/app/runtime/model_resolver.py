from __future__ import annotations

from app.providers.base import ProviderErrorCode
from app.providers.chat_gateway import (
    ProviderInvocationError,
    ResolvedModelBinding,
)
from app.repositories.provider_repository import ProviderRepository
from app.services.secrets import SecretNotFoundError, SecretStore


class ModelBindingResolver:
    def __init__(
        self,
        providers: ProviderRepository,
        secret_stores: dict[str, SecretStore],
    ) -> None:
        self._providers = providers
        self._secret_stores = secret_stores

    def resolve(
        self, *, role: str, provider_model_id: str
    ) -> ResolvedModelBinding:
        model = self._providers.get_model(provider_model_id)
        if model is None or not model.enabled:
            raise ProviderInvocationError(ProviderErrorCode.MODEL_NOT_FOUND)
        provider = self._providers.get_provider(model.provider_id)
        if provider is None or not provider.enabled:
            raise ProviderInvocationError(ProviderErrorCode.MODEL_NOT_FOUND)
        try:
            store = self._secret_stores[provider.secret_source]
            api_key = store.get(provider.secret_ref)
        except (KeyError, SecretNotFoundError) as error:
            raise ProviderInvocationError(
                ProviderErrorCode.SECRET_MISSING
            ) from error
        return ResolvedModelBinding(
            role=role,
            provider_id=provider.id,
            provider_model_id=model.id,
            api_format=provider.api_format,
            base_url=provider.base_url,
            model_id=model.model_id,
            api_key=api_key,
        )
