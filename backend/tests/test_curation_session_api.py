from pathlib import Path
from dataclasses import replace
import asyncio
import json

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
from app.review.errors import ReviewConflictError


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


class BlockingSummarizer(RecordingSummarizer):
    def __init__(self, *, entered: asyncio.Event, release: asyncio.Event, order) -> None:
        super().__init__()
        self.entered = entered
        self.release = release
        self.order = order

    async def summarize(self, *, prior_summary, overflow_turns, context):
        self.order.append("summary")
        self.entered.set()
        await self.release.wait()
        return await super().summarize(
            prior_summary=prior_summary,
            overflow_turns=overflow_turns,
            context=context,
        )


class SignallingResponder(RecordingResponder):
    def __init__(self, *, entered: asyncio.Event, order) -> None:
        super().__init__()
        self.entered = entered
        self.order = order

    async def astream(self, rendered_context, *, context):
        self.calls.append((rendered_context, context))
        self.order.append("responder")
        self.entered.set()
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
            CurationCommandPlan()
        )
        app.locate_review_session(session_id).curation_command_agents = models

        accepted = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "为什么推荐这道题？请给我一些分析建议",
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
        assert models.classifier.calls == []
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


@pytest.mark.asyncio
async def test_ambiguous_side_effect_still_uses_classifier_without_streaming_reply(
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
            CurationCommandPlan(clarification="请明确要处理的题号")
        )
        app.locate_review_session(session_id).curation_command_agents = models

        accepted = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "把合适的处理一下",
                "summaryVersion": detail["summaryVersion"],
                "idempotencyKey": "classified-side-effect-1",
            },
        )
        result = await completed_command(app, session_id, accepted)

        assert result["result"]["clarification"] == "请明确要处理的题号"
        assert len(models.classifier.calls) == 1
        assert models.responder.calls == []


@pytest.mark.asyncio
async def test_conversation_stream_starts_before_overflow_summary_finishes(
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
        latest = review.sessions.repository.latest_execution(session_id)
        for index in range(16):
            review.sessions.repository.append_message(
                session_id,
                execution_id=None if latest is None else latest.id,
                role="user" if index % 2 == 0 else "assistant",
                content=(f"第 {index} 条早期历史 " + "上下文 " * 20),
                message_kind="text" if index % 2 == 0 else "command_receipt",
            )
        summary_entered = asyncio.Event()
        summary_release = asyncio.Event()
        responder_entered = asyncio.Event()
        call_order = []
        models = RecordingCurationModels(CurationCommandPlan())
        models.summarizer = BlockingSummarizer(
            entered=summary_entered, release=summary_release, order=call_order
        )
        models.responder = SignallingResponder(
            entered=responder_entered, order=call_order
        )
        review.curation_command_agents = models
        detail = (
            await client.get(f"/api/review/curation-sessions/{session_id}")
        ).json()

        accepted = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "为什么推荐这些题？",
                "summaryVersion": detail["summaryVersion"],
                "idempotencyKey": "stream-before-summary-1",
            },
        )
        try:
            await asyncio.wait_for(responder_entered.wait(), timeout=0.2)
            assert call_order[0] == "responder"
        finally:
            summary_release.set()
        await app.wait_execution(accepted.json()["executionId"])
        assert len(models.summarizer.calls) == 1


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
async def test_rejected_finalization_never_projects_success_or_leaks_stage(
    api, application, monkeypatch
) -> None:
    app, source_ids = application
    review = app.review("w1")

    def reject_finalization(*_args, **_kwargs):
        raise ReviewConflictError("revision base changed")

    monkeypatch.setattr(
        review.repository,
        "finalize_curation_candidates",
        reject_finalization,
    )
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/review/curation-sessions",
            json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
        )
        resource = created.json()
        terminal = await app.wait_execution(resource["executionId"])

    messages = review.sessions.repository.list_messages(resource["id"])
    events = review.sessions.repository.list_events(
        resource["id"], after_id=None
    )
    curation = review.repository.get_curation_session(resource["id"])

    assert terminal.status == "failed"
    assert curation.stage == "failed"
    assert all(
        message.content != "正在合并相似题并整理来源"
        and message.message_kind != "curation_summary"
        for message in messages
    )
    assert "execution.completed" not in {event.type for event in events}
    assert "curation.summary.ready" not in {event.type for event in events}
    assert not list(
        (review.workspace_root / "artifacts/review/drafts").glob("*.md")
    )


@pytest.mark.parametrize(
    ("operation", "batch_status"),
    (("pause", "paused"), ("terminate", "terminated")),
)
@pytest.mark.asyncio
async def test_control_winning_finalization_cancels_execution_without_success(
    api, application, monkeypatch, operation: str, batch_status: str
) -> None:
    app, source_ids = application
    review = app.review("w1")

    def reject_after_control(batch_id, execution_id, **_kwargs):
        batch = review.repository.get_batch(batch_id)
        receipt = review.repository.request_batch_control(
            batch_id,
            operation=operation,
            idempotency_key=f"{operation}-during-finalization",
            expected_version=batch.version,
        )
        review.repository.finalize_batch_control(receipt.id)
        raise ReviewConflictError("control won finalization")

    monkeypatch.setattr(
        review.repository,
        "finalize_curation_candidates",
        reject_after_control,
    )
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        resource = (
            await client.post(
                "/api/review/curation-sessions",
                json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
            )
        ).json()
        terminal = await app.wait_execution(resource["executionId"])

    batch_id = review.repository.get_curation_session(
        resource["id"]
    ).active_batch_id
    assert batch_id is not None
    assert terminal.status == "cancelled"
    assert review.repository.get_batch(batch_id).status == batch_status
    assert "execution.completed" not in {
        event.type
        for event in review.sessions.repository.list_events(
            resource["id"], after_id=None
        )
    }


@pytest.mark.asyncio
async def test_superseded_finalization_interrupts_old_execution(
    api, application, monkeypatch
) -> None:
    app, source_ids = application
    review = app.review("w1")

    def supersede(batch_id, execution_id, **_kwargs):
        connection = review.sessions.repository.connection
        connection.execute(
            "INSERT INTO review_question_batches "
            "(id, workspace_id, session_id, origin_session_id, run_id, "
            "source_refs_json, status) SELECT 'newer-batch', workspace_id, "
            "session_id, origin_session_id, run_id, source_refs_json, "
            "'generating' FROM review_question_batches WHERE id = ?",
            (batch_id,),
        )
        connection.execute(
            "UPDATE review_curation_sessions SET active_batch_id = 'newer-batch' "
            "WHERE active_batch_id = ?",
            (batch_id,),
        )
        connection.commit()
        raise ReviewConflictError("newer active batch won")

    monkeypatch.setattr(
        review.repository,
        "finalize_curation_candidates",
        supersede,
    )
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        resource = (
            await client.post(
                "/api/review/curation-sessions",
                json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
            )
        ).json()
        terminal = await app.wait_execution(resource["executionId"])

    assert terminal.status == "interrupted"
    assert review.repository.get_curation_session(
        resource["id"]
    ).active_batch_id == "newer-batch"
    assert "execution.completed" not in {
        event.type
        for event in review.sessions.repository.list_events(
            resource["id"], after_id=None
        )
    }


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
            CurationCommandPlan(clarification="请明确要处理的题号"),
            entered=entered,
            release=release,
        )
        app.locate_review_session(session_id).curation_command_agents = models

        response = await asyncio.wait_for(
            client.post(
                f"/api/review/curation-sessions/{session_id}/commands",
                json={
                    "text": "把合适的按刚才方式处理一下",
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
            CurationCommandPlan(clarification="不应完成"),
            entered=entered,
            release=release,
        )
        review = app.locate_review_session(session_id)
        review.curation_command_agents = models

        response = await client.post(
            f"/api/review/curation-sessions/{session_id}/commands",
            json={
                "text": "把这批候选题按之前方式处理一下",
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
            and message["content"] == "把这批候选题按之前方式处理一下"
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
            CurationCommandPlan(clarification="不应完成"),
            entered=entered,
            release=asyncio.Event(),
        )
        review.curation_command_agents = models
        accepted = (
            await client.post(
                f"/api/review/curation-sessions/{session_id}/commands",
                json={
                    "text": "把所有候选题处理一下",
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
        original = (await client.get(
            f"/api/review/question-candidates/{candidate_id}"
        )).json()

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
        revision_execution = app.review(
            "w1"
        ).sessions.repository.get_execution(rewritten.json()["executionId"])
        assert revision_execution.input["expected_revision_draft_id"] == (
            original["draft"]["id"]
        )
        assert revision_execution.input["expected_revision_draft_version"] == (
            original["draft"]["version"]
        )
        assert revision_execution.input["expected_revision_draft_hash"] == (
            original["draft"]["contentHash"]
        )
        candidate = (await client.get(
            f"/api/review/question-candidates/{candidate_id}"
        )).json()
        assert candidate["curationSessionId"] == created["id"]


@pytest.mark.asyncio
async def test_duplicate_generation_links_evidence_to_published_question_and_blocks_republish(
    api, application
) -> None:
    app, source_ids = application
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        first = (await client.post(
            "/api/review/curation-sessions",
            json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
        )).json()
        await app.wait_execution(first["executionId"])
        first_detail = (await client.get(
            f"/api/review/curation-sessions/{first['id']}"
        )).json()
        first_candidate_id = first_detail["summary"]["items"][0]["candidateId"]
        published = await client.post(
            f"/api/review/question-candidates/{first_candidate_id}/publish",
            json={"idempotencyKey": "publish-original-question"},
        )
        assert published.status_code == 200, published.text
        published_question_id = published.json()["question"]["questionId"]

        duplicate_session = (await client.post(
            "/api/review/curation-sessions",
            json={"workspaceId": "w1", "sourceRefs": [source_ids[0]]},
        )).json()
        await app.wait_execution(duplicate_session["executionId"])
        duplicate_detail = (await client.get(
            f"/api/review/curation-sessions/{duplicate_session['id']}"
        )).json()
        duplicate_id = duplicate_detail["summary"]["items"][0]["candidateId"]
        duplicate = (await client.get(
            f"/api/review/question-candidates/{duplicate_id}"
        )).json()

        assert duplicate["duplicateOfQuestionId"] == published_question_id
        assert app.review("w1").repository.list_question_source_links(
            published_question_id
        )
        with pytest.raises(ReviewConflictError, match="duplicate candidate"):
            await client.post(
                f"/api/review/question-candidates/{duplicate_id}/publish",
                json={"idempotencyKey": "do-not-republish-duplicate"},
            )

        edited = await client.patch(
            f"/api/review/question-candidates/{duplicate_id}",
            json={
                "version": duplicate["draft"]["version"],
                "referenceAnswer": "这是更新后的参考答案，保留旧版用于历史追溯。",
            },
        )
        assert edited.status_code == 200, edited.text
        updated = await client.post(
            f"/api/review/question-candidates/{duplicate_id}/update-active-version",
            json={
                "targetQuestionId": published_question_id,
                "expectedActiveHash": published.json()["question"]["contentHash"],
                "idempotencyKey": "promote-duplicate-as-revision",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["question"]["questionId"] == published_question_id
        assert updated.json()["revisionOfQuestionId"] == published_question_id
        assert updated.json()["isActiveVersion"] is True

        old_version = await client.get(
            f"/api/review/question-candidates/{first_candidate_id}"
        )
        assert old_version.json()["status"] == "published"
        assert old_version.json()["isActiveVersion"] is False
        active = app.review("w1").repository.list_active_questions("w1")
        assert len(active) == 1
        assert active[0].snapshot.question_id == published_question_id
        assert active[0].snapshot.reference_answer.startswith("这是更新后的")
        repeated_update = await client.post(
            f"/api/review/question-candidates/{duplicate_id}/update-active-version",
            json={
                "targetQuestionId": published_question_id,
                "expectedActiveHash": published.json()["question"]["contentHash"],
                "idempotencyKey": "promote-duplicate-as-revision",
            },
        )
        assert repeated_update.status_code == 200, repeated_update.text
        assert repeated_update.json()["isActiveVersion"] is True


@pytest.mark.asyncio
async def test_hard_deleted_origin_session_preserves_question_and_creates_revision_session(
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
        before = (await client.get(
            f"/api/review/question-candidates/{candidate_id}"
        )).json()

        app.delete_session(created["id"], hard=True)
        preserved = (await client.get(
            f"/api/review/question-candidates/{candidate_id}"
        )).json()
        assert preserved["curationSessionId"] == created["id"]
        assert preserved["liveCurationSessionId"] is None
        source_links = app.review("w1").repository.list_question_source_links(
            preserved["question"]["questionId"]
        )
        assert source_links
        assert source_links[0].session_id is None
        assert source_links[0].origin_session_id == created["id"]
        origin = (await client.get(
            f"/api/review/question-candidates/{candidate_id}/origin-session"
        )).json()
        assert origin == {
            "status": "missing",
            "sessionId": created["id"],
            "session": None,
        }

        rewritten = await client.post(
            f"/api/review/question-candidates/{candidate_id}/rewrite",
            json={"feedback": "只增加一次线上排障场景"},
        )
        assert rewritten.status_code == 202, rewritten.text
        assert rewritten.json()["id"] != created["id"]
        revision_session = app.list_sessions("w1")[0]
        assert revision_session.kind == "question.revise"
        await app.wait_execution(rewritten.json()["executionId"])
        after = (await client.get(
            f"/api/review/question-candidates/{candidate_id}"
        )).json()
        assert after["question"]["questionId"] == before["question"]["questionId"]
        assert after["draft"]["version"] == before["draft"]["version"] + 1


@pytest.mark.asyncio
async def test_question_delete_bulk_receipt_and_restore_are_consistent(
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
        candidate = (await client.get(
            "/api/review/question-candidates?workspaceId=w1"
        )).json()[0]
        command = {
            "idempotencyKey": "delete-question-1",
            "expectedVersion": candidate["draft"]["version"],
            "reason": "测试删除",
        }
        first = await client.post(
            f"/api/review/question-candidates/{candidate['id']}/delete",
            json=command,
        )
        repeated = await client.post(
            f"/api/review/question-candidates/{candidate['id']}/delete",
            json=command,
        )
        assert first.status_code == repeated.status_code == 200
        assert first.json() == repeated.json()
        assert first.json()["items"][0]["status"] == "deleted"
        assert (await client.get(
            "/api/review/question-candidates?workspaceId=w1"
        )).json() == []
        trash = (await client.get(
            "/api/review/question-candidates?workspaceId=w1&deletedOnly=true"
        )).json()
        assert trash[0]["deletionReason"] == "测试删除"

        restored = await client.post(
            f"/api/review/question-candidates/{candidate['id']}/restore"
        )
        assert restored.status_code == 200
        bulk = await client.post(
            "/api/review/question-candidates/bulk-delete",
            json={
                "workspaceId": "w1",
                "idempotencyKey": "bulk-delete-question-1",
                "items": [
                    {"candidateId": candidate["id"], "expectedVersion": candidate["draft"]["version"]},
                    {"candidateId": "missing-candidate", "expectedVersion": None},
                ],
            },
        )
        assert bulk.status_code == 200, bulk.text
        assert [item["status"] for item in bulk.json()["items"]] == [
            "deleted",
            "failed",
        ]


@pytest.mark.asyncio
async def test_candidate_origin_session_reports_available_recycled_and_missing_projection(
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
        origin_url = f"/api/review/question-candidates/{candidate_id}/origin-session"

        available = await client.get(origin_url)
        assert available.status_code == 200
        assert available.json()["status"] == "available"
        assert available.json()["session"]["id"] == created["id"]

        app.delete_session(created["id"])
        recycled = await client.get(origin_url)
        assert recycled.status_code == 200
        assert recycled.json()["status"] == "recycled"
        assert recycled.json()["session"]["deletedAt"] is not None

        app.restore_session(created["id"])
        review = app.locate_review_candidate(candidate_id)
        review.repository._connection.execute(
            "DELETE FROM review_curation_sessions WHERE session_id = ?",
            (created["id"],),
        )
        review.repository._connection.commit()
        missing_projection = await client.get(origin_url)
        assert missing_projection.status_code == 200
        assert missing_projection.json() == {
            "status": "projection_missing",
            "sessionId": created["id"],
            "session": None,
        }


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
        failed_batch_id = failed["activeBatchId"]
        original_input = json.loads(
            connection.execute(
                "SELECT input_json FROM agent_runs WHERE id = ?",
                (first_execution_id,),
            ).fetchone()[0]
        )
        connection.execute(
            "UPDATE review_question_batches SET status = 'failed', "
            "version = version + 1 WHERE id = ?",
            (failed_batch_id,),
        )
        connection.execute(
            "UPDATE review_curation_sessions "
            "SET source_refs_json = ? "
            "WHERE session_id = ?",
            (json.dumps([source_ids[1]]), session_id),
        )
        connection.commit()

        retried = await client.post(
            f"/api/review/curation-sessions/{session_id}/retry"
        )

        assert retried.status_code == 202, retried.text
        assert retried.json()["id"] == session_id
        assert retried.json()["executionId"] != first_execution_id
        assert retried.json()["activeBatchId"] == failed_batch_id
        assert retried.json()["stage"] in {"generating", "waiting_for_command"}
        resumed_input = json.loads(
            connection.execute(
                "SELECT input_json FROM agent_runs WHERE id = ?",
                (retried.json()["executionId"],),
            ).fetchone()[0]
        )
        assert resumed_input == original_input


@pytest.mark.asyncio
async def test_legacy_retry_cannot_reopen_completed_batch(
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
        execution_id = created.json()["executionId"]
        await app.wait_execution(execution_id)
        review = app.locate_review_session(session_id)
        batch_id = review.repository.get_curation_session(
            session_id
        ).active_batch_id
        assert batch_id is not None
        completed = review.repository.get_batch(batch_id)
        assert completed.status == "completed"

        connection = review.sessions.repository.connection
        connection.execute(
            "UPDATE agent_runs SET status = 'failed', error_code = 'late_failure', "
            "finished_at = CURRENT_TIMESTAMP WHERE id = ?",
            (execution_id,),
        )
        connection.commit()
        curation = review.repository.get_curation_session(session_id)
        review.repository.update_curation_progress(
            session_id,
            stage="failed",
            completed_units=curation.completed_units,
            total_units=curation.total_units,
        )

        with pytest.raises(
            ReviewConflictError, match="only failed question batches can retry"
        ):
            await client.post(
                f"/api/review/curation-sessions/{session_id}/retry"
            )
        assert review.repository.get_batch(batch_id) == completed
        assert review.repository.get_curation_session(session_id).stage == "failed"


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
            CurationCommandPlan(clarification="不应调用模型")
        )
        review.curation_command_agents = models
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
            CurationCommandPlan(clarification="已识别复杂命令"),
            fail_summary=summary_fails,
        )
        review.curation_command_agents = models
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
