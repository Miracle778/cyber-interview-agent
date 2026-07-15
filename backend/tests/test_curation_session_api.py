from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_agent_application
from app.api.routes_review import router as review_router
from app.application.workspace_runtime import AgentApplication
from app.knowledge.source_registry import KnowledgeSourceService
from app.graphs.publication import create_publication_graph
from tests.test_review_api_v2 import _graph_factory


def _session_graph_factory(kind, **dependencies):
    if kind == "knowledge.publish":
        return create_publication_graph(
            request_action=dependencies["create_action"],
            checkpointer=dependencies["checkpointer"],
        )
    return _graph_factory(kind, **dependencies)


@pytest_asyncio.fixture
async def application(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = AgentApplication(
        workspace_resolver=lambda _workspace_id: workspace,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=_session_graph_factory,
    )
    sources = KnowledgeSourceService(workspace, workspace_id="w1")
    first = await sources.create(
        original_filename="redis.md",
        content_type="text/markdown",
        content=b"# Redis\n\n1. Explain cache penetration.",
    )
    second = await sources.create(
        original_filename="mysql.md",
        content_type="text/markdown",
        content=b"# MySQL\n\n1. Explain MVCC.",
    )
    try:
        yield app, (first.id, second.id)
    finally:
        await app.close()


@pytest.fixture
def api(application):
    app, _sources = application
    api = FastAPI()
    api.include_router(review_router)
    api.dependency_overrides[get_agent_application] = lambda: app
    return api


@pytest.mark.asyncio
async def test_curation_session_api_projects_progress_summary_and_timeline(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/review/curation-sessions",
            json={"workspaceId": "w1", "sourceRefs": list(source_ids)},
        )

        assert created.status_code == 202, created.text
        resource = created.json()
        assert resource["sourceRefs"] == list(source_ids)
        assert resource["stage"] in {"generating", "waiting_for_command"}
        assert {item["filename"] for item in resource["sources"]} == {
            "redis.md",
            "mysql.md",
        }
        execution_id = resource["executionId"]
        await app.wait_execution(execution_id)

        restored = await client.get(
            f"/api/review/curation-sessions/{resource['id']}"
        )
        assert restored.status_code == 200, restored.text
        detail = restored.json()
        assert detail["stage"] == "waiting_for_command"
        assert detail["executionStartedAt"] is not None
        assert detail["executionFinishedAt"] is not None
        assert detail["executionErrorCode"] is None
        assert detail["contextCompacted"] is False
        assert detail["summaryVersion"] == 1
        assert detail["candidateCount"] == 1
        assert detail["pendingCount"] == 1
        assert detail["summary"]["items"][0]["candidateId"]
        assert {message["messageKind"] for message in detail["messages"]} >= {
            "stage",
            "curation_summary",
        }
        assert all(
            "source_excerpts" not in message["content"]
            for message in detail["messages"]
        )
        assert all(
            not (message["role"] == "user" and message["content"].startswith("{"))
            for message in detail["messages"]
        )

        review = app.locate_review_session(resource["id"])
        stored = review.sessions.repository.list_messages(resource["id"])
        assert all("source_excerpts" not in message.content for message in stored)

        # Databases created before this fix may already contain an execution input
        # projected as a user text message. Keep it out of the product timeline.
        review.sessions.repository.append_message(
            resource["id"],
            execution_id=execution_id,
            role="user",
            content='{"source_excerpts": ["private source body"]}',
        )
        filtered = await client.get(
            f"/api/review/curation-sessions/{resource['id']}"
        )
        assert "private source body" not in filtered.text

        listed = await client.get(
            "/api/review/curation-sessions?workspaceId=w1"
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [resource["id"]]


@pytest.mark.asyncio
async def test_candidate_rewrite_resumes_its_original_curation_session(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = (await client.post(
            "/api/review/curation-sessions",
            json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
        )).json()
        await app.wait_execution(created["executionId"])
        detail = (await client.get(
            f"/api/review/curation-sessions/{created['id']}"
        )).json()
        candidate_id = detail["summary"]["items"][0]["candidateId"]

        rewritten = await client.post(
            f"/api/review/question-candidates/{candidate_id}/rewrite",
            json={"feedback": "增加线上排障场景"},
        )

        assert rewritten.status_code == 202, rewritten.text
        assert rewritten.json()["id"] == created["id"]
        assert rewritten.json()["executionId"] != created["executionId"]
        assert any(
            message["role"] == "user" and "线上排障场景" in message["content"]
            for message in rewritten.json()["messages"]
        )
        candidate = (await client.get(
            f"/api/review/question-candidates/{candidate_id}"
        )).json()
        assert candidate["curationSessionId"] == created["id"]


@pytest.mark.asyncio
async def test_failed_curation_session_can_retry_in_the_same_session(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/review/curation-sessions",
            json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
        )
        session_id = created.json()["id"]
        first_execution_id = created.json()["executionId"]
        await app.wait_execution(first_execution_id)

        review = app.locate_review_session(session_id)
        connection = review.sessions.repository.connection
        connection.execute(
            "UPDATE agent_runs SET status = 'failed', error_code = 'provider_error', "
            "error_message = 'Agent 执行失败', finished_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (first_execution_id,),
        )
        connection.commit()
        current = review.repository.get_curation_session(session_id)
        review.repository.update_curation_progress(
            session_id,
            stage="failed",
            completed_units=current.completed_units,
            total_units=current.total_units,
        )

        failed = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()
        assert failed["executionErrorCode"] == "provider_error"

        retried = await client.post(
            f"/api/review/curation-sessions/{session_id}/retry"
        )

        assert retried.status_code == 202, retried.text
        assert retried.json()["id"] == session_id
        assert retried.json()["executionId"] != first_execution_id
        assert retried.json()["stage"] in {"generating", "waiting_for_command"}


@pytest.mark.asyncio
async def test_reused_sources_warn_but_do_not_block_new_session(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/review/curation-sessions",
            json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
        )
        assert first.status_code == 202
        await app.wait_execution(first.json()["executionId"])

        repeated = await client.post(
            "/api/review/curation-sessions",
            json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
        )

        assert repeated.status_code == 202, repeated.text
        assert repeated.json()["id"] != first.json()["id"]
        assert repeated.json()["warnings"] == [
            {"sourceId": source_ids[0], "code": "source_previously_curated"}
        ]


@pytest.mark.asyncio
async def test_ambiguous_and_reject_commands_are_durable_and_idempotent(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/review/curation-sessions",
            json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
        )
        await app.wait_execution(created.json()["executionId"])
        session_id = created.json()["id"]
        detail = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()
        version = detail["summaryVersion"]

        command = {
            "text": "看着办",
            "summaryVersion": version,
            "idempotencyKey": "clarify-command-1",
        }
        first = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json=command,
        )
        second = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json=command,
        )

        assert first.status_code == 202, first.text
        assert second.json()["id"] == first.json()["id"]
        assert first.json()["kind"] == "clarify"
        assert first.json()["status"] == "completed"
        messages = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()["messages"]
        assert sum(message["content"] == "看着办" for message in messages) == 1

        rejected = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "拒绝第 1 题",
                "summaryVersion": version,
                "idempotencyKey": "reject-command-1",
            },
        )
        assert rejected.status_code == 202, rejected.text
        candidate_id = detail["summary"]["items"][0]["candidateId"]
        candidate = await client.get(
            f"/api/review/question-candidates/{candidate_id}"
        )
        assert candidate.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_explicit_confirm_command_publishes_without_second_decision(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/review/curation-sessions",
            json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
        )
        await app.wait_execution(created.json()["executionId"])
        session_id = created.json()["id"]
        detail = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()

        confirmed = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "确认全部推荐题",
                "summaryVersion": detail["summaryVersion"],
                "idempotencyKey": "confirm-command-1",
            },
        )

        assert confirmed.status_code == 202, confirmed.text
        assert confirmed.json()["status"] == "completed"
        assert confirmed.json()["result"]["publishedCount"] == 1
        candidate_id = detail["summary"]["items"][0]["candidateId"]
        candidate = await client.get(
            f"/api/review/question-candidates/{candidate_id}"
        )
        assert candidate.json()["status"] == "published"
        questions = await client.get("/api/review/questions?workspaceId=w1")
        assert len(questions.json()) == 1


@pytest.mark.asyncio
async def test_curation_session_and_summary_restore_after_application_restart(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def build() -> AgentApplication:
        return AgentApplication(
            workspace_resolver=lambda _workspace_id: workspace,
            workspace_ids=lambda: ("w1",),
            model_bindings=lambda _workspace_id: {},
            graph_factory=_session_graph_factory,
        )

    first = build()
    source = await KnowledgeSourceService(
        workspace, workspace_id="w1"
    ).create(
        original_filename="restart.md",
        content_type="text/markdown",
        content=b"# Restart\n\n1. Explain durable sessions.",
    )
    created = await first.review("w1").create_curation_session(
        source_refs=(source.id,)
    )
    await first.wait_execution(created["execution_id"])
    before = await first.review("w1").curation_resource(created["id"])
    await first.close()

    second = build()
    try:
        await second.recover()
        restored = await second.review("w1").curation_resource(created["id"])
        assert restored["stage"] == "waiting_for_command"
        assert restored["summary_version"] == before["summary_version"]
        assert restored["summary"] == before["summary"]
        assert restored["messages"] == before["messages"]
    finally:
        await second.close()
