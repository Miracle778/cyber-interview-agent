import sqlite3
from collections.abc import Iterator

from fastapi import Depends, Request

from app.db.app_database import connect_app_database
from app.providers.anthropic_compatible import AnthropicCompatibleAdapter
from app.providers.openai_compatible import OpenAICompatibleAdapter
from app.services.provider_service import ProviderService
from app.services.secrets import (
    EnvironmentSecretStore,
    KeyringSecretStore,
    SecretStore,
)
from app.services.workspace_service import WorkspaceService
from app.runtime.service import AgentRuntime


def get_agent_runtime(request: Request) -> AgentRuntime:
    return request.app.state.agent_runtime


def get_app_connection() -> Iterator[sqlite3.Connection]:
    connection = connect_app_database()
    try:
        yield connection
    finally:
        connection.close()


def get_secret_stores() -> dict[str, SecretStore]:
    return {
        "keyring": KeyringSecretStore(),
        "environment": EnvironmentSecretStore(),
    }


def get_provider_adapters() -> dict[str, object]:
    return {
        "openai-compatible": OpenAICompatibleAdapter(),
        "anthropic-compatible": AnthropicCompatibleAdapter(),
    }


def get_provider_service(
    connection: sqlite3.Connection = Depends(get_app_connection),
    secret_stores: dict[str, SecretStore] = Depends(get_secret_stores),
    adapters: dict[str, object] = Depends(get_provider_adapters),
) -> ProviderService:
    return ProviderService(connection, secret_stores, adapters)


def get_workspace_service(
    connection: sqlite3.Connection = Depends(get_app_connection),
) -> WorkspaceService:
    return WorkspaceService(connection)
