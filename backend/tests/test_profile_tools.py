from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from app.agents.context import AgentContext
from app.infrastructure.runtime_database import connect_runtime_database
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.profile.models import (
    CreateClaimProposalSpec,
    CreateMaterialCommand,
    DecideProposalCommand,
)
from app.profile.repository import ProfileRepository
from app.profile.storage import MaterialStorage
from app.tools.profile_tools import (
    PROFILE_CHAT_BUDGET,
    PROFILE_TOOL_NAMES,
    compare_material_versions,
    create_profile_tools,
    get_profile_claim_evidence,
    get_profile_claims,
    get_profile_publication_status,
    list_personal_materials,
    read_personal_evidence,
    read_personal_evidence_batch,
    search_personal_materials,
)


@pytest.fixture
def connection(tmp_path: Path) -> sqlite3.Connection:
    root = tmp_path / "ws"
    root.mkdir()
    initialize_knowledge_artifacts(root, domain="profile")
    return connect_runtime_database(root)


@pytest.fixture
def repository(connection: sqlite3.Connection) -> ProfileRepository:
    return ProfileRepository(connection)


@pytest.fixture
def context(tmp_path: Path) -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=tmp_path / "ws",
        session_id="s1",
        run_id="r1",
        allowed_tools=frozenset(PROFILE_TOOL_NAMES),
        allowed_scopes=frozenset({"profile.materials"}),
        agent_role="profile_chat",
    )


def _seed_resume(repository: ProfileRepository, role: str = "resume"):
    material = repository.create_material(
        CreateMaterialCommand(workspace_id="w1", type="resume", title="R", primary_role=role)
    )
    version = repository.add_material_version(
        material_id=material.id,
        source_type="upload",
        file_name="r.txt",
        mime_type="text/plain",
        content_sha256="a" * 64,
        storage_ref="blobs/aa/aaa.txt",
        text_ref="text/v1.txt",
    )
    repository.mark_version_parsed(version.id, text_path="text/v1.txt", content_sha256="a" * 64)
    evidence = repository.replace_version_evidence(
        version.id,
        (
            {
                "section": "experience",
                "start_offset": 0,
                "end_offset": 12,
                "sanitized_text": "Led team of five",
                "content_sha256": "c" * 64,
                "sensitivity": "normal",
            },
        ),
    )[0]
    return material, version, evidence


def _confirm_claim(repository: ProfileRepository, version_id: str, evidence_id: str):
    proposal = repository.create_claim_proposals(
        version_id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="mentioned",
                evidence_ids=(evidence_id,),
            ),
        ),
    )[0]
    return repository.decide_proposal(
        proposal.id,
        DecideProposalCommand(proposal_id=proposal.id, decision="accepted", expected_status="pending"),
    )


def test_list_personal_materials_returns_active_with_versions(
    repository: ProfileRepository, context: AgentContext
) -> None:
    material, version, _evidence = _seed_resume(repository)
    repository.set_primary_version(material.id, version.id)

    result = list_personal_materials(repository, context)

    assert result["status"] == "ok"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["id"] == material.id
    assert item["primaryRole"] is True
    assert item["versions"][0]["processingStatus"] == "parsed"


def test_list_personal_materials_isolates_workspace(
    repository: ProfileRepository, context: AgentContext
) -> None:
    _seed_resume(repository)  # workspace w1
    repository.create_material(
        CreateMaterialCommand(workspace_id="w2", type="resume", title="Other", primary_role="resume")
    )

    result = list_personal_materials(repository, context)
    assert {item["workspaceId"] for item in result["items"]} == {"w1"}


def test_read_personal_evidence_returns_bounded_excerpt(
    repository: ProfileRepository, context: AgentContext
) -> None:
    _material, version, evidence = _seed_resume(repository)

    result = read_personal_evidence(repository, context, evidence_id=evidence.id)
    assert result["status"] == "ok"
    assert result["items"][0]["id"] == evidence.id
    assert result["items"][0]["sanitizedText"] == "Led team of five"
    assert result["items"][0]["materialVersionId"] == version.id


def test_read_personal_evidence_rejects_foreign_workspace(
    repository: ProfileRepository, context: AgentContext
) -> None:
    _material, _version, evidence = _seed_resume(repository)
    other_context = AgentContext(
        workspace_id="w2",
        workspace_root=context.workspace_root,
        session_id="s2",
        run_id="r2",
        allowed_tools=frozenset(PROFILE_TOOL_NAMES),
        allowed_scopes=frozenset({"profile.materials"}),
        agent_role="profile_chat",
    )
    result = read_personal_evidence(repository, other_context, evidence_id=evidence.id)
    assert result["status"] == "error"
    assert result["errorCode"] == "profile_evidence_mismatch"


def test_batch_read_returns_eight_evidence_items_in_one_tool_call(
    repository: ProfileRepository, context: AgentContext
) -> None:
    _material, version, _evidence = _seed_resume(repository)
    evidence = repository.replace_version_evidence(
        version.id,
        tuple(
            {
                "section": "experience",
                "start_offset": index * 20,
                "end_offset": index * 20 + 12,
                "sanitized_text": f"Backend evidence {index}",
                "content_sha256": f"{index + 1:064x}",
                "sensitivity": "normal",
            }
            for index in range(8)
        ),
    )

    result = read_personal_evidence_batch(
        repository,
        context,
        evidence_ids=[item.id for item in evidence],
    )

    assert result["status"] == "ok"
    assert [item["id"] for item in result["items"]] == [
        item.id for item in evidence
    ]
    assert result["missingIds"] == []


def test_batch_read_keeps_available_evidence_when_one_id_is_missing(
    repository: ProfileRepository, context: AgentContext
) -> None:
    _material, _version, evidence = _seed_resume(repository)

    result = read_personal_evidence_batch(
        repository,
        context,
        evidence_ids=[evidence.id, "missing"],
    )

    assert result["status"] == "partial"
    assert [item["id"] for item in result["items"]] == [evidence.id]
    assert result["missingIds"] == ["missing"]


def test_get_profile_claims_returns_confirmed_only(
    repository: ProfileRepository, context: AgentContext
) -> None:
    _material, version, evidence = _seed_resume(repository)
    _confirm_claim(repository, version.id, evidence.id)

    result = get_profile_claims(repository, context)
    assert result["status"] == "ok"
    assert len(result["items"]) == 1
    assert result["items"][0]["value"]["text"] == "Python"
    assert result["items"][0]["supportStatus"] == "supported"


def test_get_profile_claim_evidence_returns_refs(
    repository: ProfileRepository, context: AgentContext
) -> None:
    _material, version, evidence = _seed_resume(repository)
    accepted = _confirm_claim(repository, version.id, evidence.id)

    result = get_profile_claim_evidence(repository, context, claim_id=accepted.claim_id)
    assert result["status"] == "ok"
    assert result["evidenceRefs"][0]["id"] == evidence.id


def test_search_personal_materials_returns_excerpt_refs(
    repository: ProfileRepository, context: AgentContext
) -> None:
    _material, _version, _evidence = _seed_resume(repository)

    result = search_personal_materials(repository, context, query="team")
    assert result["status"] == "ok"
    assert len(result["items"]) == 1
    assert "team" in result["items"][0]["excerpt"].lower()


def test_compare_material_versions_returns_summary(
    repository: ProfileRepository, context: AgentContext
) -> None:
    material, version_a, _evidence = _seed_resume(repository)
    version_b = repository.add_material_version(
        material_id=material.id,
        source_type="upload",
        file_name="r2.txt",
        mime_type="text/plain",
        content_sha256="d" * 64,
        storage_ref="blobs/dd/ddd.txt",
        text_ref="text/v2.txt",
    )

    result = compare_material_versions(
        repository, context, version_a_id=version_a.id, version_b_id=version_b.id
    )
    assert result["status"] == "ok"
    assert result["items"][0]["versionA"] == version_a.version_number
    assert result["items"][0]["versionB"] == version_b.version_number


def test_get_profile_publication_status_default_empty(
    repository: ProfileRepository, context: AgentContext
) -> None:
    # The legacy read helper remains compatible with existing stored data, but
    # it is no longer part of the current Profile Agent's exposed tool set.
    result = get_profile_publication_status(
        repository,
        replace(
            context,
            allowed_tools=context.allowed_tools
            | frozenset({"get_profile_publication_status"}),
        ),
    )
    assert result["status"] == "ok"
    assert result["items"] == []
    assert result["state"] == "unpublished"


def test_absent_records_return_safe_empty(
    repository: ProfileRepository, context: AgentContext
) -> None:
    assert read_personal_evidence(repository, context, evidence_id="missing")["status"] == "error"
    assert get_profile_claim_evidence(repository, context, claim_id="missing")["status"] == "error"
    assert compare_material_versions(
        repository, context, version_a_id="missing", version_b_id="missing"
    )["status"] == "error"


def test_tool_factory_exposes_only_read_only_tools(
    repository: ProfileRepository, tmp_path: Path
) -> None:
    storage = MaterialStorage(tmp_path / "ws")
    tools = create_profile_tools(repository=repository, storage=storage)

    names = tuple(tool.name for tool in tools)
    assert names == PROFILE_TOOL_NAMES
    assert len(names) == 7
    assert "search_active_knowledge" not in names
    assert "get_profile_publication_status" not in names
    forbidden = {"create", "update", "delete", "publish", "accept", "apply", "archive", "restore"}
    for name in names:
        assert not any(verb in name for verb in forbidden), name


def test_profile_chat_budget_constants() -> None:
    assert PROFILE_CHAT_BUDGET.max_calls == 6
    assert PROFILE_CHAT_BUDGET.max_identical_calls == 2


def test_tool_scope_is_checked_inside_read_handler(
    repository: ProfileRepository, context: AgentContext
) -> None:
    denied = replace(context, allowed_scopes=frozenset())

    result = list_personal_materials(repository, denied)

    assert result["status"] == "error"
    assert result["errorCode"] == "tool_scope_denied"


def test_evidence_excerpt_uses_injected_context_limit(
    repository: ProfileRepository, context: AgentContext
) -> None:
    _material, _version, evidence = _seed_resume(repository)
    bounded = replace(context, tool_excerpt_char_limit=8)

    result = read_personal_evidence(repository, bounded, evidence_id=evidence.id)

    assert result["items"][0]["sanitizedText"] == "Led team…"
    assert result["truncated"] is True


def test_material_list_limit_and_order_are_deterministic(
    repository: ProfileRepository, context: AgentContext
) -> None:
    for index in range(3):
        repository.create_material(
            CreateMaterialCommand(
                workspace_id="w1",
                type="project_document",
                title=f"Project {index}",
                primary_role=f"project-{index}",
            )
        )
    bounded = replace(context, tool_result_item_limit=2)

    first = list_personal_materials(repository, bounded)
    second = list_personal_materials(repository, bounded)

    assert len(first["items"]) == 2
    assert first["truncated"] is True
    assert [item["id"] for item in first["items"]] == [
        item["id"] for item in second["items"]
    ]


def test_archived_evidence_is_not_readable(
    repository: ProfileRepository, context: AgentContext
) -> None:
    material, _version, evidence = _seed_resume(repository)
    repository.archive_material(material.id)

    result = read_personal_evidence(repository, context, evidence_id=evidence.id)

    assert result["status"] == "error"
    assert result["errorCode"] == "profile_evidence_mismatch"


def test_tool_schemas_are_strict_and_business_only(
    repository: ProfileRepository, tmp_path: Path
) -> None:
    tools = {tool.name: tool for tool in create_profile_tools(
        repository=repository, storage=MaterialStorage(tmp_path / "ws")
    )}

    assert tools["list_personal_materials"].args == {}
    assert set(tools["read_personal_evidence"].args) == {"evidence_id"}
    assert set(tools["read_personal_evidence_batch"].args) == {"evidence_ids"}
    assert "workspace_id" not in tools["search_personal_materials"].args
    with pytest.raises(Exception):
        tools["read_personal_evidence"].args_schema.model_validate(
            {"evidence_id": "ev", "workspace_id": "foreign"}
        )


@pytest.mark.asyncio
async def test_all_profile_tools_receive_runtime_through_real_tool_node(
    repository: ProfileRepository, context: AgentContext, tmp_path: Path
) -> None:
    material, version, evidence = _seed_resume(repository)
    accepted = _confirm_claim(repository, version.id, evidence.id)
    tools = create_profile_tools(
        repository=repository,
        storage=MaterialStorage(tmp_path / "ws"),
    )
    graph = StateGraph(MessagesState, context_schema=AgentContext)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    calls = [
        {"name": "list_personal_materials", "args": {}, "id": "call-1"},
        {
            "name": "search_personal_materials",
            "args": {"query": "team"},
            "id": "call-2",
        },
        {
            "name": "read_personal_evidence",
            "args": {"evidence_id": evidence.id},
            "id": "call-3",
        },
        {
            "name": "read_personal_evidence_batch",
            "args": {"evidence_ids": [evidence.id]},
            "id": "call-3-batch",
        },
        {"name": "get_profile_claims", "args": {}, "id": "call-4"},
        {
            "name": "get_profile_claim_evidence",
            "args": {"claim_id": accepted.claim_id},
            "id": "call-5",
        },
        {
            "name": "compare_material_versions",
            "args": {
                "version_a_id": version.id,
                "version_b_id": version.id,
            },
            "id": "call-6",
        },
    ]

    result = await graph.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=calls)]},
        context=replace(
            context,
            allowed_scopes=frozenset({"profile.materials", "knowledge.active"}),
        ),
    )

    messages = [item for item in result["messages"] if isinstance(item, ToolMessage)]
    assert len(messages) == len(PROFILE_TOOL_NAMES)
    assert {item.name for item in messages} == set(PROFILE_TOOL_NAMES)
    assert all("missing 1 required positional argument" not in item.content for item in messages)
