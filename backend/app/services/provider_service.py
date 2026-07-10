from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager

from app.core.errors import (
    ProviderModelInUseError,
    ProviderModelNotFoundError,
    ProviderNotFoundError,
)
from app.providers.base import ERROR_MESSAGES, ProviderErrorCode, ProviderTestResult
from app.repositories.provider_repository import ProviderRepository
from app.schemas.settings import (
    CreateProviderCommand,
    CreateProviderModelCommand,
    ProviderModelResource,
    ProviderResource,
    UpdateProviderCommand,
    UpdateProviderModelCommand,
)
from app.services.secrets import SecretNotFoundError, SecretStore


class ProviderService:
    """CRUD + connection testing for providers and their models.

    Writes the keyring secret before the DB row and compensates on failure;
    never reads secrets into returned resources; delegates connection tests to
    per-format adapters. The service owns the transaction boundary: every
    mutating path commits on success and rolls back (with secret compensation
    where a secret side-effect preceded the DB write) on failure.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        secret_stores: dict[str, SecretStore],
        adapters: dict,
    ) -> None:
        self._connection = connection
        self.secret_stores = secret_stores
        self.adapters = adapters
        self.providers = ProviderRepository(connection)

    @contextmanager
    def _transaction(self):
        try:
            yield
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def create_provider(self, command: CreateProviderCommand) -> ProviderResource:
        provider_id = str(uuid.uuid4())
        if command.secret_source == "keyring":
            if not command.api_key:
                raise ValueError("api_key is required for keyring secrets")
            secret_ref = f"provider:{provider_id}"
            self.secret_stores["keyring"].set(secret_ref, command.api_key)
            try:
                with self._transaction():
                    record = self.providers.create_provider(
                        provider_id=provider_id,
                        name=command.name,
                        api_format=command.api_format,
                        base_url=command.base_url,
                        secret_source="keyring",
                        secret_ref=secret_ref,
                    )
            except Exception:
                self._safe_delete_secret("keyring", secret_ref)
                raise
        elif command.secret_source == "environment":
            if not command.secret_ref:
                raise ValueError("secret_ref is required for environment secrets")
            with self._transaction():
                record = self.providers.create_provider(
                    provider_id=provider_id,
                    name=command.name,
                    api_format=command.api_format,
                    base_url=command.base_url,
                    secret_source="environment",
                    secret_ref=command.secret_ref,
                )
        else:
            raise ValueError(f"unsupported secret_source: {command.secret_source!r}")
        return self._to_provider_resource(record)

    def list_providers(self) -> list[ProviderResource]:
        return [self._to_provider_resource(r) for r in self.providers.list_providers()]

    def get_provider(self, provider_id: str) -> ProviderResource:
        record = self.providers.get_provider(provider_id)
        if record is None:
            raise ProviderNotFoundError(provider_id)
        return self._to_provider_resource(record)

    def update_provider(
        self, provider_id: str, command: UpdateProviderCommand
    ) -> ProviderResource:
        current = self.providers.get_provider(provider_id)
        if current is None:
            raise ProviderNotFoundError(provider_id)

        new_name = command.name if command.name is not None else current.name
        new_api_format = (
            command.api_format if command.api_format is not None else current.api_format
        )
        new_base_url = (
            command.base_url if command.base_url is not None else current.base_url
        )
        status_reset_needed = (
            (command.base_url is not None and command.base_url != current.base_url)
            or (
                command.api_format is not None
                and command.api_format != current.api_format
            )
            or command.api_key is not None
        )

        secret_changed = (
            command.api_key is not None and current.secret_source == "keyring"
        )
        old_secret: str | None = None
        had_secret = False
        if secret_changed:
            try:
                old_secret = self.secret_stores["keyring"].get(current.secret_ref)
                had_secret = True
            except SecretNotFoundError:
                had_secret = False
            self.secret_stores["keyring"].set(current.secret_ref, command.api_key)

        try:
            with self._transaction():
                record = self.providers.update_provider(
                    provider_id,
                    name=new_name,
                    api_format=new_api_format,
                    base_url=new_base_url,
                )
                if status_reset_needed:
                    self.providers.reset_model_statuses(provider_id)
                    record = self.providers.get_provider(provider_id)
        except Exception:
            if secret_changed:
                self._restore_secret(
                    current.secret_source,
                    current.secret_ref,
                    had_secret,
                    old_secret,
                )
            raise
        return self._to_provider_resource(record)

    def delete_provider(self, provider_id: str) -> None:
        current = self.providers.get_provider(provider_id)
        if current is None:
            raise ProviderNotFoundError(provider_id)
        # Check in-use first so a bound provider never loses its secret.
        if self.providers.provider_has_bound_models(provider_id):
            raise ProviderModelInUseError(provider_id)

        old_secret: str | None = None
        had_secret = False
        if current.secret_source == "keyring":
            try:
                old_secret = self.secret_stores["keyring"].get(current.secret_ref)
                had_secret = True
            except SecretNotFoundError:
                had_secret = False
            # Delete the secret before the DB row. A backend failure here leaves
            # the provider intact (nothing committed) and propagates.
            try:
                self.secret_stores["keyring"].delete(current.secret_ref)
            except SecretNotFoundError:
                pass

        try:
            with self._transaction():
                self.providers.delete_provider(provider_id)
        except sqlite3.IntegrityError as exc:
            self._restore_secret(current.secret_source, current.secret_ref, had_secret, old_secret)
            raise ProviderModelInUseError(provider_id) from exc
        except Exception:
            self._restore_secret(current.secret_source, current.secret_ref, had_secret, old_secret)
            raise

    def create_provider_model(
        self, provider_id: str, command: CreateProviderModelCommand
    ) -> ProviderModelResource:
        with self._transaction():
            if self.providers.get_provider(provider_id) is None:
                raise ProviderNotFoundError(provider_id)
            record = self.providers.create_model(
                provider_id,
                command.model_id,
                command.display_name,
                enabled=command.enabled,
            )
        return self._to_model_resource(record)

    def update_provider_model(
        self, model_id: str, command: UpdateProviderModelCommand
    ) -> ProviderModelResource:
        current = self.providers.get_model(model_id)
        if current is None:
            raise ProviderModelNotFoundError(model_id)
        new_model_id = (
            command.model_id if command.model_id is not None else current.model_id
        )
        new_display_name = (
            command.display_name if command.display_name is not None else current.display_name
        )
        new_enabled = command.enabled if command.enabled is not None else current.enabled
        model_id_changed = (
            command.model_id is not None and command.model_id != current.model_id
        )
        with self._transaction():
            self.providers.update_model(
                model_id,
                real_model_id=new_model_id,
                display_name=new_display_name,
                enabled=new_enabled,
            )
            if model_id_changed:
                self.providers.reset_model_status(model_id)
        return self._to_model_resource(self.providers.get_model(model_id))

    def delete_provider_model(self, model_id: str) -> None:
        if self.providers.get_model(model_id) is None:
            raise ProviderModelNotFoundError(model_id)
        try:
            with self._transaction():
                self.providers.delete_model(model_id)
        except sqlite3.IntegrityError as exc:
            raise ProviderModelInUseError(model_id) from exc

    async def test_model(self, model_id: str) -> ProviderModelResource:
        model = self.providers.get_model(model_id)
        if model is None:
            raise ProviderModelNotFoundError(model_id)
        provider = self.providers.get_provider(model.provider_id)
        if provider is None:
            raise ProviderNotFoundError(model.provider_id)
        adapter = self.adapters.get(provider.api_format)
        if adapter is None:
            raise ValueError(
                f"no adapter registered for api_format {provider.api_format!r}"
            )

        try:
            api_key = self.secret_stores[provider.secret_source].get(provider.secret_ref)
        except SecretNotFoundError:
            api_key = None

        if not api_key:
            result = ProviderTestResult(
                status=ProviderErrorCode.SECRET_MISSING,
                latency_ms=0,
                message=ERROR_MESSAGES[ProviderErrorCode.SECRET_MISSING],
            )
        else:
            result = await adapter.test_connection(
                base_url=provider.base_url,
                model_id=model.model_id,
                api_key=api_key,
            )

        error_code = (
            None if result.status == ProviderErrorCode.OK else result.status.value
        )
        with self._transaction():
            self.providers.update_model_status(
                model.id,
                connectivity_status=result.status.value,
                latency_ms=result.latency_ms,
                error_code=error_code,
            )
            self.providers.record_test_run(
                model.id,
                status=result.status.value,
                latency_ms=result.latency_ms,
                error_code=error_code,
                message=ERROR_MESSAGES[result.status],
            )
        return self._to_model_resource(self.providers.get_model(model.id))

    def _safe_delete_secret(self, source: str, ref: str) -> None:
        try:
            self.secret_stores[source].delete(ref)
        except SecretNotFoundError:
            pass

    def _restore_secret(
        self, secret_source: str, secret_ref: str, had_secret: bool, old_secret: str | None
    ) -> None:
        """Compensate a failed DB write that followed a secret change.

        Restores the previous value when known, otherwise removes the new value.
        The old value is never returned or logged.
        """
        if secret_source != "keyring":
            return
        if had_secret and old_secret is not None:
            self.secret_stores["keyring"].set(secret_ref, old_secret)
        else:
            self._safe_delete_secret("keyring", secret_ref)

    def _to_provider_resource(self, record) -> ProviderResource:
        return ProviderResource(
            id=record.id,
            name=record.name,
            api_format=record.api_format,
            base_url=record.base_url,
            secret_source=record.secret_source,
            has_secret=True,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
            models=[self._to_model_resource(m) for m in record.models],
        )

    def _to_model_resource(self, record) -> ProviderModelResource:
        return ProviderModelResource(
            id=record.id,
            provider_id=record.provider_id,
            model_id=record.model_id,
            display_name=record.display_name,
            enabled=record.enabled,
            connectivity_status=record.connectivity_status,
            last_tested_at=record.last_tested_at,
            last_error_code=record.last_error_code,
            last_latency_ms=record.last_latency_ms,
        )
