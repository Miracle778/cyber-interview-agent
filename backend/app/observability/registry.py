"""Compatibility facade for the Agent control-plane definition registry.

New product code should import from ``app.agents.definition_registry``.  The
old observability names remain temporarily so existing extensions do not need
to migrate in the same release.
"""

from __future__ import annotations

from app.agents.definition_registry import (
    AGENT_DEFINITIONS,
    AGENT_DEFINITION_REGISTRY,
    AgentDefinition,
    AgentLifecycle,
    AgentRegistrationError,
)


AgentObservabilityRegistration = AgentDefinition
AGENT_OBSERVABILITY_REGISTRY = AGENT_DEFINITIONS


def resolve_observability_registration(
    graph_id: str,
    *,
    include_historical: bool = False,
) -> AgentDefinition | None:
    return AGENT_DEFINITION_REGISTRY.resolve(
        graph_id,
        include_historical=include_historical,
    )


def require_registration(
    graph_id: str,
    *,
    for_user_creation: bool = False,
) -> AgentDefinition:
    return AGENT_DEFINITION_REGISTRY.require(
        graph_id,
        for_user_creation=for_user_creation,
    )


def assert_registry_complete(graph_ids: frozenset[str] | set[str]) -> None:
    """Deprecated compatibility assertion for external callers.

    Production code no longer provides a parallel Graph ID set.  This helper
    remains only to fail older integrations that still compare such a set.
    """

    expected = set(AGENT_DEFINITION_REGISTRY.agent_ids)
    actual = set(graph_ids)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unknown:
            details.append(f"unknown={','.join(unknown)}")
        raise RuntimeError("Agent definition registry mismatch: " + "; ".join(details))


__all__ = [
    "AGENT_DEFINITION_REGISTRY",
    "AGENT_OBSERVABILITY_REGISTRY",
    "AgentLifecycle",
    "AgentObservabilityRegistration",
    "AgentRegistrationError",
    "assert_registry_complete",
    "require_registration",
    "resolve_observability_registration",
]
