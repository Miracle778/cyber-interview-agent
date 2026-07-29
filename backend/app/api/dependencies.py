import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Query, Request

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
from app.application.workspace_runtime import AgentApplication
from app.observability.service import AgentObservabilityService
from app.evaluation.service import AgentEvaluationService
from app.observability.retention import TraceRetentionService
from app.observability.cleanup import TraceCleanupService


def get_agent_application(request: Request) -> AgentApplication:
    return request.app.state.agent_application


def get_agent_observability_service(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
) -> AgentObservabilityService:
    return application.agent_observability(workspace_id)


def get_agent_evaluation_service(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
) -> AgentEvaluationService:
    return application.agent_evaluation(workspace_id)


def get_trace_retention_service(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
) -> TraceRetentionService:
    return application.trace_retention(workspace_id)


def get_trace_cleanup_service(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
) -> TraceCleanupService:
    return application.trace_cleanup(workspace_id)


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
