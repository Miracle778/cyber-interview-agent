from __future__ import annotations

import os
from typing import Protocol

import keyring
from keyring.errors import PasswordDeleteError

KEYRING_SERVICE_NAME = "cyber-interview-agent"


class SecretNotFoundError(LookupError):
    """The referenced secret is not present in the store."""


class SecretStoreUnavailableError(RuntimeError):
    """The secret store backend rejected the operation or is unavailable."""


class SecretStore(Protocol):
    def get(self, ref: str) -> str: ...
    def set(self, ref: str, value: str) -> None: ...
    def delete(self, ref: str) -> None: ...


class KeyringSecretStore:
    """SecretStore backed by the operating-system keyring."""

    def __init__(self, service_name: str = KEYRING_SERVICE_NAME) -> None:
        self._service_name = service_name

    def get(self, ref: str) -> str:
        try:
            value = keyring.get_password(self._service_name, ref)
        except Exception as exc:
            raise SecretStoreUnavailableError("keyring get failed") from exc
        if value is None:
            raise SecretNotFoundError(ref)
        return value

    def set(self, ref: str, value: str) -> None:
        try:
            keyring.set_password(self._service_name, ref, value)
        except Exception as exc:
            raise SecretStoreUnavailableError("keyring set failed") from exc

    def delete(self, ref: str) -> None:
        try:
            keyring.delete_password(self._service_name, ref)
        except PasswordDeleteError as exc:
            raise SecretNotFoundError(ref) from exc
        except Exception as exc:
            raise SecretStoreUnavailableError("keyring delete failed") from exc


class EnvironmentSecretStore:
    """Read-only SecretStore backed by process environment variables.

    ``ref`` is the environment variable name. Environment secrets are managed
    outside the application, so writes are unsupported.
    """

    def get(self, ref: str) -> str:
        try:
            return os.environ[ref]
        except KeyError:
            raise SecretNotFoundError(ref) from None

    def set(self, ref: str, value: str) -> None:
        raise SecretStoreUnavailableError("EnvironmentSecretStore is read-only")

    def delete(self, ref: str) -> None:
        raise SecretStoreUnavailableError("EnvironmentSecretStore is read-only")


class FakeSecretStore:
    """In-memory SecretStore for tests; never exposes values in its repr."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def get(self, ref: str) -> str:
        try:
            return self._secrets[ref]
        except KeyError:
            raise SecretNotFoundError(ref) from None

    def set(self, ref: str, value: str) -> None:
        self._secrets[ref] = value

    def delete(self, ref: str) -> None:
        try:
            del self._secrets[ref]
        except KeyError:
            raise SecretNotFoundError(ref) from None

    def __repr__(self) -> str:
        return f"FakeSecretStore(refs={sorted(self._secrets)})"
