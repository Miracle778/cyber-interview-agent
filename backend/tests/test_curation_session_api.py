from pathlib import Path
from dataclasses import replace
import asyncio

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_agent_application
from app.api.routes_review import router as review_router
from app.application.workspace_runtime import AgentApplication
from app.agents.context_assembly import ContextSummary
from app.knowledge.source_registry import KnowledgeSourceService
from app.knowledge.drafts import CreateDraftCommand
from app.graphs.publication import create_publication_graph
from tests.test_review_api_v2 import _graph_factory
from app.review.curation_command_contracts import CurationCommandPlan


def _session_graph_factory(kind, **dependencies):
    if kind == "knowledge.publish":
        return create_publication_graph(
            request_action=dependencies["create_action"],
            checkpointer=dependencies["checkpointer"],
        )
    return _graph_factory(kind, **dependencies)


class RecordingClassifier:
    def __init__(self, plan: CurationCommandPlan) -> None:
        self.plan = plan
        self.calls = []

    async def classify(self, assembled, *, context):
        self.calls.append((assembled, context))
        return self.plan


class BlockingClassifier(RecordingClassifier):
    def __init__(
        self,
        plan: CurationCommandPlan,
        *,
        entered: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        super().__init__(plan)
        self.entered = entered
        self.release = release

    async def classify(self, assembled, *, context):
        self.calls.append((assembled, context))
        self.entered.set()
        await self.release.wait()
        return self.plan


class RecordingSummarizer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = []

    async def summarize(self, *, prior_summary, overflow_turns, context):
        self.calls.append((prior_summary, overflow_turns, context))
        if self.fail:
            raise RuntimeError("summary unavailable")
        return ContextSummary(
            text="已压缩早期整理对话",
            resource_refs=("candidate:remembered",),
            decisions=("保留已确认焦点",),
            open_items=("等待后续命令",),
            through_message_id=overflow_turns[-1].messages[-1].id,
        )


class RecordingResponder:
    def __init__(self, chunks=("真实", "回复")) -> None:
        self.chunks = chunks
        self.calls = []

    async def astream(self, rendered_context, *, context):
        self.calls.append((rendered_context, context))
        for chunk in self.chunks:
            yield chunk


class RecordingCurationModels:
    def __init__(
        self, plan: CurationCommandPlan, *, fail_summary: bool = False
    ) -> None:
        self.classifier = RecordingClassifier(plan)
        self.summarizer = RecordingSummarizer(fail=fail_summary)
        self.responder = RecordingResponder()
        self.context_limit_tokens = 180
        self.token_counter = lambda text: max(1, len(text) // 12)


async def completed_command(app, session_id: str, response) -> dict:
    payload = response.json()
    await app.wait_execution(payload["executionId"])
    review = app.locate_review_session(session_id)
    receipt = review.repository.get_curation_command_receipt(
        payload["commandId"]
    )
    return review._curation_command_resource(receipt)


@pytest.mark.asyncio
async def test_free_form_response_streams_real_chunks_and_persists_joined_text(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/api/review/curation-sessions",
                json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
            )
        ).json()
        await app.wait_execution(created["executionId"])
        session_id = created["id"]
        detail = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()
        models = RecordingCurationModels(
            CurationCommandPlan(response="分类器占位文本")
        )
        app.locate_review_session(session_id).curation_command_models = models

        accepted = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "请给我建议",
                "summaryVersion": detail["summaryVersion"],
                "idempotencyKey": "stream-command-1",
            },
        )
        result = await completed_command(app, session_id, accepted)
        events = app.replay_events(session_id, after_id=None)
        deltas = [
            item.payload["text"]
            for item in events
            if item.type == "assistant.delta"
            and item.execution_id == accepted.json()["executionId"]
        ]

        assert deltas == ["真实", "回复"]
        assert result["result"]["clarification"] == "真实回复"
        detail = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()
        assert any(
            message["role"] == "assistant"
            and message["executionId"] == accepted.json()["executionId"]
            and message["content"] == "真实回复"
            for message in detail["messages"]
        )
        assert models.responder.calls


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
async def test_curation_command_returns_accepted_before_classifier_finishes(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/api/review/curation-sessions",
                json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
            )
        ).json()
        await app.wait_execution(created["executionId"])
        session_id = created["id"]
        detail = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()
        entered = asyncio.Event()
        release = asyncio.Event()
        models = RecordingCurationModels(CurationCommandPlan())
        models.classifier = BlockingClassifier(
            CurationCommandPlan(response="已理解"),
            entered=entered,
            release=release,
        )
        app.locate_review_session(session_id).curation_command_models = models

        response = await asyncio.wait_for(
            client.post(
                f"/api/review/curation-sessions/{session_id}/commands",
                json={
                    "text": "请结合刚才的上下文给出建议",
                    "summaryVersion": detail["summaryVersion"],
                    "idempotencyKey": "async-command-1",
                    "providerModelId": "model-1",
                    "reasoningEffort": "medium",
                },
            ),
            timeout=0.2,
        )

        assert response.status_code == 202, response.text
        assert response.json()["status"] == "accepted"
        assert response.json()["commandId"]
        assert response.json()["executionId"]
        await asyncio.wait_for(entered.wait(), timeout=0.2)
        release.set()
        terminal = await app.wait_execution(response.json()["executionId"])
        assert terminal.status == "completed"
        assert terminal.configuration.provider_model_id == "model-1"
        assert terminal.configuration.reasoning_effort == "medium"
        restored = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()
        assert restored["preferredModelId"] == "model-1"
        assert restored["preferredReasoningEffort"] == "medium"
        assert restored["latestCommand"] == {
            "commandId": response.json()["commandId"],
            "executionId": response.json()["executionId"],
            "lifecycleStatus": "completed",
            "retryCount": 0,
        }


@pytest.mark.asyncio
async def test_curation_command_cancel_keeps_user_message_without_final_reply(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/api/review/curation-sessions",
                json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
            )
        ).json()
        await app.wait_execution(created["executionId"])
        session_id = created["id"]
        detail = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()
        entered = asyncio.Event()
        release = asyncio.Event()
        models = RecordingCurationModels(CurationCommandPlan())
        models.classifier = BlockingClassifier(
            CurationCommandPlan(response="不应完成"),
            entered=entered,
            release=release,
        )
        review = app.locate_review_session(session_id)
        review.curation_command_models = models

        response = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "请分析这批候选题",
                "summaryVersion": detail["summaryVersion"],
                "idempotencyKey": "cancel-command-1",
                "providerModelId": "model-1",
                "reasoningEffort": "low",
            },
        )
        accepted = response.json()
        await asyncio.wait_for(entered.wait(), timeout=0.2)

        cancelled = await app.cancel_execution(accepted["executionId"])
        receipt = review.repository.get_curation_command_receipt(
            accepted["commandId"]
        )
        restored = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()

        assert cancelled.status == "cancelled"
        assert receipt.lifecycle_status == "cancelled"
        assert any(
            message["role"] == "user"
            and message["content"] == "请分析这批候选题"
            for message in restored["messages"]
        )
        assert not any(
            message["role"] == "assistant"
            and message["executionId"] == accepted["executionId"]
            for message in restored["messages"]
        )
        assert [
            event.type
            for event in app.replay_events(session_id, after_id=None)
        ][-3:] == [
            "curation.command.interpreting",
            "execution.cancelling",
            "execution.cancelled",
        ]


@pytest.mark.asyncio
async def test_async_rewrite_finishes_command_before_starting_child_execution(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/api/review/curation-sessions",
                json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
            )
        ).json()
        await app.wait_execution(created["executionId"])
        detail = (
            await client.get(f"/api/review/curation-sessions/{created['id']}")
        ).json()

        accepted = await client.post(
            f"/api/review/curation-sessions/{created['id']}/commands",
            json={
                "text": "重写第 1 题：补充边界条件",
                "summaryVersion": detail["summaryVersion"],
                "idempotencyKey": "rewrite-command-1",
            },
        )
        receipt = await completed_command(app, created["id"], accepted)
        child_execution_id = receipt["result"]["executionId"]

        assert receipt["status"] == "completed"
        assert child_execution_id != accepted.json()["executionId"]
        await app.wait_execution(child_execution_id)


@pytest.mark.asyncio
async def test_immediate_abandon_cancels_command_and_releases_session(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/api/review/curation-sessions",
                json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
            )
        ).json()
        await app.wait_execution(created["executionId"])
        session_id = created["id"]
        detail = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()
        entered = asyncio.Event()
        review = app.locate_review_session(session_id)
        models = RecordingCurationModels(CurationCommandPlan())
        models.classifier = BlockingClassifier(
            CurationCommandPlan(response="不应完成"),
            entered=entered,
            release=asyncio.Event(),
        )
        review.curation_command_models = models
        accepted = (
            await client.post(
                f"/api/review/curation-sessions/{session_id}/commands",
                json={
                    "text": "分析所有候选题",
                    "summaryVersion": detail["summaryVersion"],
                    "idempotencyKey": "abandon-command-1",
                },
            )
        ).json()

        abandoned = await client.post(
            f"/api/review/curation-commands/{accepted['commandId']}/abandon"
        )
        receipt = review.repository.get_curation_command_receipt(
            accepted["commandId"]
        )
        assert abandoned.status_code == 204
        assert receipt.lifecycle_status == "cancelled"

        next_command = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "重新总结",
                "summaryVersion": detail["summaryVersion"],
                "idempotencyKey": "after-abandon-1",
            },
        )
        assert next_command.status_code == 202, next_command.text
        assert (
            await app.wait_execution(next_command.json()["executionId"])
        ).status == "completed"


@pytest.mark.asyncio
async def test_bulk_preflight_uses_server_candidate_state(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/api/review/curation-sessions",
                json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
            )
        ).json()
        await app.wait_execution(created["executionId"])
        review = app.locate_review_session(created["id"])
        curation = review.repository.get_curation_session(created["id"])
        recommended = review.repository.get_candidate(
            str(curation.summary.items[0]["candidateId"])
        )
        fixtures = (
            ("duplicate", "review_pending", "link_existing"),
            ("rejected", "rejected", "suggest_reject"),
            ("published", "published", "recommend_confirm"),
            ("blocked", "review_pending", "recommend_confirm"),
        )
        items = [dict(curation.summary.items[0])]
        items[0]["recommendation"] = "recommend_confirm"
        for index, (identifier, candidate_status, recommendation) in enumerate(
            fixtures, start=1
        ):
            draft_id = None
            if identifier != "blocked":
                draft = await review.drafts.create(
                    CreateDraftCommand(
                        domain="review",
                        document_type="question",
                        title=identifier,
                        markdown=f"# {identifier}",
                        source_refs=(source_ids[0],),
                        relation_refs=(),
                        session_id=created["id"],
                        document_id=f"doc-{identifier}",
                    )
                )
                draft_id = draft.id
            review.repository.save_candidate(
                batch_id=recommended.batch_id,
                question=replace(
                    recommended.question,
                    question_id=identifier,
                    document_id=f"doc-{identifier}",
                    content_hash=f"{index:064x}",
                    title=identifier,
                ),
                draft_id=draft_id,
                status=candidate_status,
                candidate_id=identifier,
            )
            items.append(
                {
                    "ordinal": len(items) + 1,
                    "candidateId": identifier,
                    "title": identifier,
                    "recommendation": recommendation,
                }
            )
        review.repository.replace_curation_summary(
            created["id"],
            expected_version=curation.summary_version,
            summary=type(curation.summary)(items=tuple(items)),
        )

        response = await client.get(
            f"/api/review/curation-sessions/{created['id']}"
            "/bulk-publication/preflight"
        )

        assert response.status_code == 200, response.text
        assert response.json()["publishable"] == [recommended.id]
        assert response.json()["alreadyPublished"] == ["published"]
        assert set(response.json()["needsReview"]) == {
            "duplicate",
            "rejected",
        }
        assert response.json()["blocked"] == ["blocked"]


@pytest.mark.asyncio
async def test_bulk_publication_cancel_then_retry_skips_completed_item(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/api/review/curation-sessions",
                json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
            )
        ).json()
        await app.wait_execution(created["executionId"])
        review = app.locate_review_session(created["id"])
        curation = review.repository.get_curation_session(created["id"])
        first = review.repository.get_candidate(
            str(curation.summary.items[0]["candidateId"])
        )
        second_draft = await review.drafts.create(
            CreateDraftCommand(
                domain="review",
                document_type="question",
                title="bulk second",
                markdown="# bulk second",
                source_refs=(source_ids[0],),
                relation_refs=(),
                session_id=created["id"],
                document_id="doc-bulk-second",
            )
        )
        second = review.repository.save_candidate(
            batch_id=first.batch_id,
            question=replace(
                first.question,
                question_id="bulk-second",
                document_id="doc-bulk-second",
                content_hash="b" * 64,
                title="bulk second",
            ),
            draft_id=second_draft.id,
            status="review_pending",
            candidate_id="bulk-second",
        )
        summary = type(curation.summary)(
            items=(
                dict(curation.summary.items[0])
                | {"recommendation": "recommend_confirm"},
                {
                    "ordinal": 2,
                    "candidateId": second.id,
                    "title": second.question.title,
                    "recommendation": "recommend_confirm",
                },
            )
        )
        updated = review.repository.replace_curation_summary(
            created["id"],
            expected_version=curation.summary_version,
            summary=summary,
        )
        entered = asyncio.Event()
        release = asyncio.Event()
        calls: list[tuple[str, str]] = []

        async def fake_publish(candidate_id, *, idempotency_key):
            calls.append((candidate_id, idempotency_key))
            if candidate_id == first.id and not release.is_set():
                entered.set()
                await release.wait()
            review.repository.update_candidate_status(
                candidate_id, status="published"
            )

        review._publish_curation_candidate = fake_publish
        accepted = (
            await client.post(
                f"/api/review/curation-sessions/{created['id']}"
                "/bulk-publications",
                json={
                    "summaryVersion": updated.summary_version,
                    "idempotencyKey": "bulk-start-1",
                    "candidateIds": [first.id, second.id],
                },
            )
        ).json()
        await asyncio.wait_for(entered.wait(), timeout=0.2)
        requested = await app.cancel_execution(accepted["executionId"])
        assert requested.cancellation_requested is True
        release.set()
        assert (
            await app.wait_execution(accepted["executionId"])
        ).status == "cancelled"
        cancelled = (
            await client.get(
                f"/api/review/bulk-publications/{accepted['operationId']}"
            )
        ).json()
        assert [item["status"] for item in cancelled["items"]] == [
            "completed",
            "pending",
        ]

        retried = await client.post(
            f"/api/review/bulk-publications/{accepted['operationId']}/retry",
            json={"idempotencyKey": "bulk-retry-1"},
        )
        assert retried.status_code == 202, retried.text
        await app.wait_execution(retried.json()["executionId"])
        completed = (
            await client.get(
                f"/api/review/bulk-publications/{accepted['operationId']}"
            )
        ).json()

        assert completed["status"] == "completed"
        assert [candidate_id for candidate_id, _key in calls] == [
            first.id,
            second.id,
        ]
        assert all(
            key.startswith(
                f"bulk-publish:{accepted['operationId']}:"
            )
            for _candidate_id, key in calls
        )


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
        assert detail["contextUsage"] == {
            "currentTokens": 0,
            "thresholdTokens": 0,
            "estimated": True,
        }
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
async def test_deleted_curation_session_is_listed_only_in_trash(
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
        app.delete_session(created["id"])

        visible = await client.get(
            "/api/review/curation-sessions?workspaceId=w1"
        )
        trash = await client.get(
            "/api/review/curation-sessions?workspaceId=w1&deletedOnly=true"
        )

        assert visible.json() == []
        assert [item["id"] for item in trash.json()] == [created["id"]]
        assert trash.json()[0]["deletedAt"] is not None


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
        assert second.json()["commandId"] == first.json()["commandId"]
        result = await completed_command(app, session_id, first)
        assert result["kind"] == "clarify"
        assert result["status"] == "completed"
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
        await completed_command(app, session_id, rejected)
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
        review = app.locate_review_session(session_id)
        models = RecordingCurationModels(
            CurationCommandPlan(response="不应调用模型")
        )
        review.curation_command_models = models
        context_before = review.repository.get_or_create_curation_context(
            session_id
        )
        candidate_id = detail["summary"]["items"][0]["candidateId"]
        messages_before_note = len(detail["messages"])
        noted = await client.put(
            f"/api/review/question-candidates/{candidate_id}/note",
            json={"note": "补充失败恢复场景"},
        )
        assert noted.status_code == 200, noted.text
        assert noted.json()["reviewNote"] == "补充失败恢复场景"
        unchanged = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()
        assert len(unchanged["messages"]) == messages_before_note

        confirmed = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "确认全部推荐题",
                "summaryVersion": detail["summaryVersion"],
                "idempotencyKey": "confirm-command-1",
            },
        )

        assert confirmed.status_code == 202, confirmed.text
        confirmed_result = await completed_command(app, session_id, confirmed)
        assert confirmed_result["status"] == "completed"
        assert confirmed_result["result"]["publishedCount"] == 1
        context_after = review.repository.get_or_create_curation_context(
            session_id
        )
        repeated = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "确认全部推荐题",
                "summaryVersion": detail["summaryVersion"],
                "idempotencyKey": "confirm-command-1",
            },
        )
        context_repeated = review.repository.get_or_create_curation_context(
            session_id
        )
        assert repeated.json()["commandId"] == confirmed.json()["commandId"]
        assert models.classifier.calls == []
        assert models.summarizer.calls == []
        assert context_after.version == context_before.version + 1
        assert context_repeated.version == context_after.version
        candidate = await client.get(
            f"/api/review/question-candidates/{candidate_id}"
        )
        assert candidate.json()["status"] == "published"
        questions = await client.get("/api/review/questions?workspaceId=w1")
        assert len(questions.json()) == 1
        republished = await client.post(
            f"/api/review/question-candidates/{candidate_id}/publish",
            json={"idempotencyKey": "direct-publish-repeat-1"},
        )
        assert republished.status_code == 200, republished.text
        assert republished.json()["status"] == "published"


@pytest.mark.asyncio
async def test_curation_focus_survives_more_than_eight_messages_and_projects_timing(
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
        review = app.locate_review_session(session_id)
        detail = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()
        version = detail["summaryVersion"]
        first = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "第 1 题是什么？",
                "summaryVersion": version,
                "idempotencyKey": "inspect-context-command-1",
            },
        )
        await completed_command(app, session_id, first)
        latest = review.sessions.repository.latest_execution(session_id)
        for index in range(10):
            review.sessions.repository.append_message(
                session_id,
                execution_id=None if latest is None else latest.id,
                role="user" if index % 2 == 0 else "assistant",
                content=f"无关的历史消息 {index}",
                message_kind="text" if index % 2 == 0 else "command_receipt",
            )
        second = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "这题发布吧",
                "summaryVersion": version,
                "idempotencyKey": "inspect-context-command-2",
            },
        )

        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        second_result = await completed_command(app, session_id, second)
        assert second_result["kind"] == "confirm"
        assert second_result["result"]["publishedCount"] == 1
        candidate_id = detail["summary"]["items"][0]["candidateId"]
        assert (
            await client.get(f"/api/review/question-candidates/{candidate_id}")
        ).json()["status"] == "published"
        restored = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()
        command_messages = [
            item
            for item in restored["messages"]
            if item["messageKind"] in {"text", "command_receipt"}
        ]
        assert command_messages[-2]["payload"]["submittedAt"].endswith(
            "+00:00"
        )
        assert command_messages[-1]["payload"]["startedAt"].endswith(
            "+00:00"
        )


@pytest.mark.asyncio
async def test_multi_focus_pronoun_requires_clarification_without_mutation(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/api/review/curation-sessions",
                json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
            )
        ).json()
        await app.wait_execution(created["executionId"])
        session_id = created["id"]
        review = app.locate_review_session(session_id)
        current = review.repository.get_curation_session(session_id)
        first_id = str(current.summary.items[0]["candidateId"])
        first_candidate = review.repository.get_candidate(first_id)
        second = review.repository.save_candidate(
            batch_id=first_candidate.batch_id,
            question=replace(
                first_candidate.question,
                question_id="candidate-question-2",
                document_id="candidate-document-2",
                content_hash="d" * 64,
                title="第二道候选题",
            ),
            draft_id=None,
            source_refs=first_candidate.source_refs,
            status="review_pending",
            candidate_id="candidate-2",
        )
        summary = review.repository.replace_curation_summary(
            session_id,
            expected_version=current.summary_version,
            summary=type(current.summary)(
                items=current.summary.items
                + (
                    {
                        "ordinal": 2,
                        "candidateId": second.id,
                        "title": second.question.title,
                        "recommendation": "recommend_confirm",
                    },
                )
            ),
        )
        context = review.repository.get_or_create_curation_context(session_id)
        review.repository.replace_curation_context(
            session_id,
            expected_version=context.version,
            focused_candidate_ids=(first_id, second.id),
            last_intent="inspect",
            last_result_candidate_ids=(first_id, second.id),
            dialogue_summary={},
            summarized_through_message_id=None,
        )

        response = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "这题发布吧",
                "summaryVersion": summary.summary_version,
                "idempotencyKey": "multi-focus-command-1",
            },
        )

        assert response.status_code == 202, response.text
        result = await completed_command(app, session_id, response)
        assert result["kind"] == "clarify"
        assert "多道题" in result["result"]["clarification"]
        assert review.repository.get_candidate(first_id).status == "review_pending"
        assert review.repository.get_candidate(second.id).status == "review_pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("summary_fails", [False, True])
async def test_budget_overflow_compacts_or_safely_degrades(
    api, application, summary_fails
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/api/review/curation-sessions",
                json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
            )
        ).json()
        await app.wait_execution(created["executionId"])
        session_id = created["id"]
        review = app.locate_review_session(session_id)
        models = RecordingCurationModels(
            CurationCommandPlan(response="已识别复杂命令"),
            fail_summary=summary_fails,
        )
        review.curation_command_models = models
        latest = review.sessions.repository.latest_execution(session_id)
        for index in range(16):
            review.sessions.repository.append_message(
                session_id,
                execution_id=None if latest is None else latest.id,
                role="user" if index % 2 == 0 else "assistant",
                content=(f"第 {index} 条早期历史 " + "上下文 " * 20),
                message_kind="text" if index % 2 == 0 else "command_receipt",
            )
        detail = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()

        response = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "按备注处理，其余按之前说的办",
                "summaryVersion": detail["summaryVersion"],
                "idempotencyKey": f"overflow-command-{summary_fails}",
            },
        )

        assert response.status_code == 202, response.text
        await completed_command(app, session_id, response)
        assert len(models.summarizer.calls) == 1
        assert len(models.classifier.calls) == 1
        assembled = models.classifier.calls[0][0]
        assert assembled.recent_turns
        context = review.repository.get_or_create_curation_context(session_id)
        restored = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()
        assert restored["contextUsage"]["thresholdTokens"] > 0
        if summary_fails:
            assert context.summarized_through_message_id is None
            assert restored["contextCompacted"] is False
            assert review.sessions.repository.latest_warning(session_id) == {
                "code": "curation_context_summary_failed",
                "message": "curation_context_summary_failed",
            }
        else:
            assert context.summarized_through_message_id is not None
            assert context.dialogue_summary["text"] == "已压缩早期整理对话"
            assert restored["contextCompacted"] is True


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
    inspected = await first.review("w1").execute_curation_command(
        created["id"],
        text="第 1 题是什么？",
        summary_version=before["summary_version"],
        idempotency_key="restart-inspect-1",
    )
    assert inspected["kind"] == "clarify"
    await first.close()

    second = build()
    try:
        await second.recover()
        restored = await second.review("w1").curation_resource(created["id"])
        assert restored["stage"] == "waiting_for_command"
        assert restored["summary_version"] == before["summary_version"]
        assert restored["summary"] == before["summary"]
        published = await second.review("w1").execute_curation_command(
            created["id"],
            text="这题发布吧",
            summary_version=restored["summary_version"],
            idempotency_key="restart-publish-pronoun-1",
        )
        assert published["kind"] == "confirm"
        candidate_id = str(restored["summary"]["items"][0]["candidateId"])
        assert (
            await second.review("w1").candidate_resource(candidate_id)
        )["status"] == "published"
    finally:
        await second.close()
