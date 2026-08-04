from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.definition_registry import (
    AGENT_DEFINITION_REGISTRY,
    AgentDefinition,
    AgentDefinitionRegistry,
)
from app.application.graph_factory import ProductionGraphFactory
from app.observability.models import OperationSummary, TraceHealth
from app.observability.registry import (
    AGENT_OBSERVABILITY_REGISTRY,
    AgentRegistrationError,
    require_registration,
)
from app.schemas.observability import (
    ExecutionSummaryResource,
    OperationSummaryResource,
)


def test_agent_definition_is_the_single_observability_source() -> None:
    assert set(AGENT_OBSERVABILITY_REGISTRY) == set(AGENT_DEFINITION_REGISTRY.agent_ids)
    assert AGENT_OBSERVABILITY_REGISTRY[
        "review.round"
    ] is AGENT_DEFINITION_REGISTRY.require("review.round")


def test_factory_builder_catalog_matches_agent_definitions() -> None:
    factory = ProductionGraphFactory(None)

    assert factory.builder_keys == AGENT_DEFINITION_REGISTRY.builder_keys


def test_registry_rejects_missing_and_orphaned_builders() -> None:
    registry = AgentDefinitionRegistry(
        (
            AgentDefinition(
                agent_id="test.agent",
                definition_version="1",
                builder_key="test_builder",
                display_name="Test",
                route_template="/test",
                capabilities=frozenset(),
                eval_pack_id=None,
                system_components=(),
            ),
        )
    )

    with pytest.raises(RuntimeError, match="missing=test_builder"):
        registry.validate_builder_catalog(set())

    with pytest.raises(RuntimeError, match="unknown=orphan_builder"):
        registry.validate_builder_catalog({"test_builder", "orphan_builder"})


def test_registry_rejects_active_definition_without_builder() -> None:
    with pytest.raises(RuntimeError, match="Active Agent definition has no builder"):
        AgentDefinitionRegistry(
            (
                AgentDefinition(
                    agent_id="test.agent",
                    definition_version="1",
                    builder_key=None,
                    display_name="Test",
                    route_template="/test",
                    capabilities=frozenset(),
                    eval_pack_id=None,
                    system_components=(),
                ),
            )
        )


def test_graph_factory_rejects_unknown_agent_before_building() -> None:
    factory = ProductionGraphFactory(None)

    with pytest.raises(AgentRegistrationError) as error:
        factory("unknown.agent")

    assert error.value.code == "agent_not_registered"


def test_system_graphs_do_not_expose_business_navigation() -> None:
    for graph_id in (
        "profile.ingest",
        "profile.assess",
        "knowledge.publish",
        "diagnostic.echo",
        "diagnostic.approval",
        "diagnostic.security",
    ):
        registration = AGENT_OBSERVABILITY_REGISTRY[graph_id]
        assert registration.system is True
        assert registration.route_template == ""
        assert "open_business" not in registration.capabilities


def test_non_agent_workflows_are_not_visible_in_the_agent_run_center() -> None:
    for graph_id in (
        "knowledge.publish",
        "diagnostic.echo",
        "diagnostic.approval",
        "diagnostic.security",
    ):
        assert AGENT_OBSERVABILITY_REGISTRY[graph_id].run_center_visible is False

    for graph_id in ("profile.ingest", "profile.assess"):
        assert AGENT_OBSERVABILITY_REGISTRY[graph_id].run_center_visible is True


def test_interview_retrospective_is_registered_as_business_agent() -> None:
    registration = AGENT_OBSERVABILITY_REGISTRY["interview.retrospective"]

    assert registration.display_name == "面试复盘"
    assert registration.route_template == "/retrospectives"
    assert registration.system is False
    assert {"open_business", "cancel", "retry", "resume", "export_trace"} <= set(
        registration.capabilities
    )
    assert registration.system_components == ("retrospective_analysis",)


def test_registration_gate_rejects_unknown_and_system_only_agents() -> None:
    registration = require_registration("review.round", for_user_creation=True)

    assert registration.graph_id == "review.round"

    with pytest.raises(AgentRegistrationError) as unknown:
        require_registration("unknown.agent", for_user_creation=True)
    assert unknown.value.code == "agent_not_registered"

    with pytest.raises(AgentRegistrationError) as system_only:
        require_registration("knowledge.publish", for_user_creation=True)
    assert system_only.value.code == "agent_not_user_creatable"


def test_execution_summary_resource_uses_camel_case_contract() -> None:
    resource = ExecutionSummaryResource(
        id="run-1",
        session_id="session-1",
        workspace_id="workspace-1",
        graph_id="review.round",
        display_name="复习助手",
        system=False,
        title="随机复习",
        status="completed",
        trace_health=TraceHealth.COMPLETE,
        capabilities=["open_business", "manual_judge"],
        route="/review",
        system_operation_count=2,
        model_call_count=3,
        total_tokens=12_345,
        context_current_tokens=4_000,
        context_threshold_tokens=90_000,
        latency_ms=1_200,
        retry_count=1,
        created_at="2026-07-29T12:00:00+00:00",
        started_at="2026-07-29T12:00:01+00:00",
        finished_at="2026-07-29T12:00:02+00:00",
    )

    payload = resource.model_dump(by_alias=True)

    assert payload["sessionId"] == "session-1"
    assert payload["workspaceId"] == "workspace-1"
    assert payload["graphId"] == "review.round"
    assert payload["system"] is False
    assert payload["traceHealth"] == "complete"
    assert payload["systemOperationCount"] == 2
    assert payload["modelCallCount"] == 3
    assert "session_id" not in payload


def test_operation_resource_preserves_parent_and_safe_metadata_only() -> None:
    operation = OperationSummary(
        id="operation-1",
        run_id="run-1",
        parent_operation_id="root",
        kind="model",
        name="answer_evaluation",
        agent_role="answer_evaluation",
        status="completed",
        started_at="2026-07-29T12:00:00+00:00",
        finished_at="2026-07-29T12:00:01+00:00",
        latency_ms=1_000,
        retry_count=0,
        error_code=None,
        event_count=2,
    )

    payload = OperationSummaryResource.model_validate(operation).model_dump(
        by_alias=True
    )

    assert payload["parentOperationId"] == "root"
    assert payload["eventCount"] == 2
    assert "payload" not in payload


def test_trace_health_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        ExecutionSummaryResource(
            id="run-1",
            session_id="session-1",
            workspace_id="workspace-1",
            graph_id="review.round",
            display_name="复习助手",
            title="随机复习",
            status="completed",
            trace_health="mystery",
            capabilities=[],
            route="/review",
            system_operation_count=0,
            model_call_count=0,
            total_tokens=0,
            context_current_tokens=0,
            context_threshold_tokens=0,
            latency_ms=None,
            retry_count=0,
            created_at="2026-07-29T12:00:00+00:00",
            started_at=None,
            finished_at=None,
        )
