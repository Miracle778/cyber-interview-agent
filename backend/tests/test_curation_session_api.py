from pathlib import Path
from dataclasses import replace
from hashlib import sha256
import asyncio
import json
import sqlite3

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_agent_application
from app.api.routes_review import router as review_router
from app.application.workspace_runtime import AgentApplication
from app.agents.context_assembly import ContextSummary
from app.knowledge.source_registry import KnowledgeSourceService
from app.security.workspace_paths import PathPolicyError
from app.knowledge.drafts import (
    CreateDraftCommand,
    DraftNotEditableError,
    KnowledgeDraftService,
    UpdateDraftCommand,
)
from app.graphs.publication import create_publication_graph
from app.graphs.question_curation import create_question_curation_graph
from app.agents.question_curation_contracts import (
    QuestionCandidate,
    QuestionCandidateChunk,
    QuestionSeedChunk,
)
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


@pytest.mark.asyncio
async def test_all_unusable_sources_complete_without_preparing_a_provider_execution(
    application, tmp_path: Path
) -> None:
    app, source_ids = application
    sources = KnowledgeSourceService(tmp_path / "workspace", workspace_id="w1")
    empty = await sources.create(
        original_filename="empty.md",
        content_type="text/markdown",
        content=b" \n\t",
    )
    invalid = await sources.create(
        original_filename="invalid.md",
        content_type="text/markdown",
        content=b"\xff\xfe",
    )
    review = app.review("w1")

    resource = await review.create_curation_session(
        source_refs=(empty.id, invalid.id)
    )

    assert resource["stage"] == "completed"
    assert resource["batch_status"] == "completed"
    assert resource["execution_id"] is None
    assert resource["execution_status"] is None
    assert review.sessions.get(resource["id"]).status == "completed"
    assert resource["warnings"][-2:] == (
        {"sourceId": empty.id, "code": "no_extractable_text"},
        {"sourceId": invalid.id, "code": "unsupported_encoding"},
    )
    assert resource["warnings"][-1]["code"] != "failed"


@pytest.mark.asyncio
async def test_legacy_batch_start_completes_when_all_sources_are_unusable(
    application, tmp_path: Path
) -> None:
    app, _source_ids = application
    sources = KnowledgeSourceService(tmp_path / "workspace", workspace_id="w1")
    empty = await sources.create(
        original_filename="empty.md",
        content_type="text/markdown",
        content=b" \n\t",
    )
    invalid = await sources.create(
        original_filename="invalid.md",
        content_type="text/markdown",
        content=b"\xff\xfe",
    )

    batch = await app.review("w1").create_question_batch(
        source_refs=(empty.id, invalid.id)
    )

    assert batch.status == "completed"
    assert batch.run_id is None
    review = app.review("w1")
    assert review.sessions.get(batch.session_id).status == "completed"
    assert review.repository.get_curation_session(batch.session_id).warnings == (
        {"sourceId": empty.id, "code": "no_extractable_text"},
        {"sourceId": invalid.id, "code": "unsupported_encoding"},
    )


@pytest.mark.asyncio
async def test_rewrite_source_intake_completes_without_execution_when_unusable(
    application, tmp_path: Path
) -> None:
    app, _source_ids = application
    review = app.review("w1")
    sources = KnowledgeSourceService(tmp_path / "workspace", workspace_id="w1")
    empty = await sources.create(
        original_filename="rewrite-empty.md",
        content_type="text/markdown",
        content=b" \n\t",
    )
    session = await review.sessions.create(
        workspace_id="w1", kind="question.curate", title="Rewrite"
    )
    review.repository.create_curation_session(
        workspace_id="w1", session_id=session.id, source_refs=(empty.id,)
    )

    execution = await review._start_curation_execution(
        session_id=session.id,
        source_refs=(empty.id,),
        rewrite_feedback="重新整理",
        rewrite_of_batch_id=None,
    )

    assert execution is None
    assert review.sessions.repository.latest_execution(session.id) is None
    assert review.sessions.get(session.id).status == "completed"
    curation = review.repository.get_curation_session(session.id)
    assert curation.stage == "completed"
    assert curation.warnings == (
        {"sourceId": empty.id, "code": "no_extractable_text"},
    )


@pytest.mark.asyncio
async def test_workspace_escape_is_not_normalized_into_a_source_warning(
    application,
) -> None:
    app, source_ids = application
    review = app.review("w1")
    source_id = source_ids[0]
    review.repository._connection.execute(
        "UPDATE knowledge_sources SET stored_path = ? WHERE id = ?",
        ("../outside-secret.md", source_id),
    )
    review.repository._connection.commit()

    with pytest.raises(PathPolicyError) as error:
        await review.create_curation_session(source_refs=(source_id,))

    assert "outside-secret.md" not in str(error.value)


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


def _api_with_review_conflicts(application: AgentApplication) -> FastAPI:
    api = FastAPI()
    api.include_router(review_router)
    api.dependency_overrides[get_agent_application] = lambda: application

    @api.exception_handler(ReviewConflictError)
    async def review_conflict_handler(_request, _error):
        return JSONResponse(
            status_code=409,
            content={"code": "review_conflict", "message": "conflict"},
        )

    return api


async def _seed_running_curation(review, source_id: str):
    session = await review.sessions.create(
        workspace_id="w1", kind="question.curate", title="Controlled curation"
    )
    review.repository.create_curation_session(
        workspace_id="w1",
        session_id=session.id,
        source_refs=(source_id,),
    )
    batch = review.repository.create_batch(
        workspace_id="w1",
        session_id=session.id,
        run_id=None,
        source_refs=(source_id,),
    )
    execution_input = {
        "batchId": batch.id,
        "batch_id": batch.id,
        "sourceRefs": [source_id],
        "source_refs": [source_id],
        "source_excerpts": [f"{source_id}:source.md\nQuestion?"],
        "similar_questions": [],
        "rewrite_feedback": None,
    }
    execution = await review.executions.prepare(
        session, input=execution_input, project_input_message=False
    )
    batch = review.repository.attach_batch_run(batch.id, execution.id)
    review.repository.record_curation_attempt(
        batch.id, execution.id, reason="initial"
    )
    review.repository.update_curation_progress(
        session.id,
        stage="generating",
        completed_units=0,
        total_units=1,
        active_batch_id=batch.id,
    )
    return session, batch, execution


def _provisional_candidate(title: str, source_ref: str) -> dict[str, object]:
    return {
        "title": title,
        "question_text": f"Explain {title}",
        "reference_answer": f"Reference for {title}",
        "topics": ["runtime"],
        "difficulty": "medium",
        "key_points": ["durability"],
        "follow_ups": [],
        "source_refs": [source_ref],
        "correction_note": "No correction required",
    }


@pytest.mark.asyncio
async def test_six_item_curation_resumes_after_failure_pause_and_runtime_restart(
    tmp_path: Path,
) -> None:
    class ControlledProviderError(RuntimeError):
        code = "provider_error"

    class BarrierCurationAgents:
        def __init__(self) -> None:
            self.phase = "fail"
            self.active = 0
            self.peak = 0
            self.invocations: dict[int, int] = {}
            self.first_wave_started = asyncio.Event()
            self.release_first_wave = asyncio.Event()
            self.pause_wave_started = asyncio.Event()
            self.fail_unit_index: int | None = None

        async def discover(self, *_args, **_kwargs) -> QuestionSeedChunk:
            return QuestionSeedChunk(seeds=[])

        async def enrich(
            self,
            seeds,
            *,
            sections,
            known_questions,
            context,
            config,
            unit_index,
        ) -> QuestionCandidateChunk:
            del sections, known_questions, context, config
            phase = self.phase
            self.invocations[unit_index] = self.invocations.get(unit_index, 0) + 1
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                if phase == "fail":
                    if self.active == 3:
                        self.fail_unit_index = unit_index
                        self.first_wave_started.set()
                    await self.release_first_wave.wait()
                    if unit_index == self.fail_unit_index:
                        raise ControlledProviderError("private provider body")
                elif phase == "pause":
                    if self.active == 3:
                        self.pause_wave_started.set()
                    await asyncio.Event().wait()
                return QuestionCandidateChunk(candidates=[
                    QuestionCandidate(
                        title=f"题目 {unit_index}-{ordinal}",
                        question_text=seed.question_text,
                        reference_answer="确定性 fake Provider 答案",
                        topics=["runtime"],
                        difficulty="medium",
                        key_points=["可恢复"],
                        follow_ups=[],
                        source_refs=list(seed.source_refs),
                        correction_note="fake Provider acceptance",
                    )
                    for ordinal, seed in enumerate(seeds)
                ])
            finally:
                self.active -= 1

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agents = BarrierCurationAgents()

    def build() -> AgentApplication:
        def graph_factory(kind, **dependencies):
            if kind in {"question.curate", "question.revise"}:
                return create_question_curation_graph(
                    agents,
                    repository=dependencies["review_repository"],
                    checkpointer=dependencies["checkpointer"],
                )
            return _session_graph_factory(kind, **dependencies)

        return AgentApplication(
            workspace_resolver=lambda _workspace_id: workspace,
            workspace_ids=lambda: ("w1",),
            model_bindings=lambda _workspace_id: {},
            graph_factory=graph_factory,
        )

    first = build()
    source = await KnowledgeSourceService(
        workspace, workspace_id="w1"
    ).create(
        original_filename="six-items.md",
        content_type="text/markdown",
        content=(
            "# 可恢复整理\n\n"
            + "\n".join(
                f"{index}、问题 {index}？\n答案 {index}"
                for index in range(1, 19)
            )
        ).encode("utf-8"),
    )
    created = await first.review("w1").create_curation_session(
        source_refs=(source.id,)
    )
    session_id = str(created["id"])
    batch_id = str(created["active_batch_id"])

    await asyncio.wait_for(agents.first_wave_started.wait(), timeout=2)
    assert agents.peak == 3
    agents.release_first_wave.set()
    failed_execution = await first.wait_execution(str(created["execution_id"]))
    assert failed_execution.status == "failed"

    first_review = first.review("w1")
    first_items = first_review.repository.list_curation_seed_tasks(batch_id)
    assert len(first_items) == 18
    assert [item.status for item in first_items[:9]] == [
        *(["degraded"] * 6),
        *(["interrupted"] * 3),
    ]
    completed_invocations = {
        item.id: item.automatic_attempt_count
        for item in first_items
        if item.status in {"completed", "degraded"}
    }

    agents.phase = "pause"
    failed_batch = first_review.repository.get_batch(batch_id)
    resumed = await first_review.resume_curation_session(
        session_id,
        expected_batch_version=failed_batch.version,
        idempotency_key="resume-after-partial-failure-0001",
    )
    await asyncio.wait_for(agents.pause_wave_started.wait(), timeout=2)
    assert all(
        first_review.repository.get_curation_seed_task(item_id).automatic_attempt_count
        == count
        for item_id, count in completed_invocations.items()
    )
    generating_batch = first_review.repository.get_batch(batch_id)
    paused = await first_review.pause_curation_session(
        session_id,
        expected_batch_version=generating_batch.version,
        idempotency_key="pause-resumed-attempt-0001",
    )
    assert paused["batch_status"] == "paused"
    assert resumed["execution_id"] != created["execution_id"]
    assert all(item.status != "running" for item in (
        *first_review.repository.list_curation_work_items(batch_id),
        *first_review.repository.list_curation_seed_tasks(batch_id),
    ))
    await first.close()

    agents.phase = "finish"
    second = build()
    try:
        await second.recover()
        second_review = second.review("w1")
        recovered_batch = second_review.repository.get_batch(batch_id)
        assert recovered_batch.status == "paused"
        final_attempt = await second_review.resume_curation_session(
            session_id,
            expected_batch_version=recovered_batch.version,
            idempotency_key="resume-after-runtime-restart-0001",
        )
        await second.wait_execution(str(final_attempt["execution_id"]))

        final_batch = second_review.repository.get_batch(batch_id)
        final_items = second_review.repository.list_curation_work_items(batch_id)
        final_seed_tasks = second_review.repository.list_curation_seed_tasks(batch_id)
        assert agents.peak == 3
        assert all(
            second_review.repository.get_curation_seed_task(item_id).automatic_attempt_count
            == count
            for item_id, count in completed_invocations.items()
        )
        assert final_batch.status == "review_pending"
        assert all(item.status in {"completed", "degraded"} for item in final_seed_tasks)
        assert all(item.status != "running" for item in final_items)
        resource = await second_review.curation_resource(session_id)
        assert resource["seed_progress"] == {
            "total": 18,
            "completed": 0,
            "degraded": 18,
            "retrying": 0,
            "skipped": 0,
            "pending": 0,
        }
        assert resource["quality_summary"] == {
            "source": 0,
            "mixed": 0,
            "model": 0,
            "unknown": 18,
            "needs_review": 18,
        }
        formal_candidates = second_review.repository.list_candidates("w1")
        assert all(item.seed_task_id is not None for item in formal_candidates)
        assert all(item.answer_basis == "unknown" for item in formal_candidates)
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_seed_retry_api_is_idempotent_and_schedules_one_execution(
    application, monkeypatch
) -> None:
    app, source_ids = application
    review = app.review("w1")
    session, batch, execution = await _seed_running_curation(
        review, source_ids[0]
    )
    review.sessions.repository.transition_execution(
        execution.id, expected=("queued", "running"), target="completed"
    )
    source_ref = f"{source_ids[0]}#section-0001"
    discovery = review.repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest="d" * 64,
        source_refs=(source_ref,),
        processor_kind="deterministic",
    )
    review.repository.complete_deterministic_curation_work_item(
        discovery.id,
        output={"seeds": [{
            "question_text": "如何恢复单题？",
            "source_ref": source_ref,
            "source_refs": [source_ref],
        }]},
    )
    seed_task = review.repository.plan_curation_seed_task(
        batch_id=batch.id,
        discovery_work_item_id=discovery.id,
        seed_ordinal=0,
        question_text="如何恢复单题？",
        primary_source_ref=source_ref,
        source_refs=(source_ref,),
        input_digest="e" * 64,
    )
    running = review.repository.claim_curation_seed_tasks(
        batch.id, statuses=("pending",), limit=1
    )[0]
    skipped = review.repository.skip_curation_seed_task(
        running.id,
        expected_version=running.version,
        error_code="missing_answer",
        normalization_issues=("missing_answer",),
    )
    scheduled: list[str] = []
    monkeypatch.setattr(
        review.executions,
        "run_prepared",
        lambda prepared, *, graph_input: scheduled.append(prepared.id),
    )
    api = _api_with_review_conflicts(app)

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        path = (
            f"/api/review/curation-sessions/{session.id}/seed-tasks/"
            f"{seed_task.id}/retry"
        )
        first = await client.post(
            path,
            headers={"Idempotency-Key": "retry-one-seed-0001"},
            json={"expectedVersion": skipped.version},
        )
        repeated = await client.post(
            path,
            headers={"Idempotency-Key": "retry-one-seed-0001"},
            json={"expectedVersion": skipped.version},
        )

    assert first.status_code == repeated.status_code == 202
    assert repeated.json() == first.json()
    assert first.json()["seedTaskId"] == seed_task.id
    assert scheduled == [first.json()["executionId"]]


@pytest.mark.asyncio
async def test_curation_control_api_uses_header_and_resumes_same_batch(
    application, monkeypatch
) -> None:
    app, source_ids = application
    api = _api_with_review_conflicts(app)
    review = app.review("w1")
    session, batch, execution = await _seed_running_curation(
        review, source_ids[0]
    )
    completed_item = review.repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest="d" * 64,
        source_refs=(f"{source_ids[0]}#section-0001",),
        processor_kind="deterministic",
    )
    review.repository.complete_deterministic_curation_work_item(
        completed_item.id,
        output={
            "seeds": [
                {
                    "question_text": "What is durable control?",
                    "source_ref": f"{source_ids[0]}#section-0001",
                    "source_refs": [f"{source_ids[0]}#section-0001"],
                }
            ]
        },
    )
    running_item = review.repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=1,
        input_digest="e" * 64,
        source_refs=(f"{source_ids[0]}#section-0002",),
    )
    review.repository.start_curation_work_item(running_item.id)
    scheduled: list[str] = []
    monkeypatch.setattr(
        review.executions,
        "run_prepared",
        lambda prepared, *, graph_input: scheduled.append(prepared.id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        body_key = await client.post(
            f"/api/review/curation-sessions/{session.id}/pause",
            headers={"Idempotency-Key": "pause-request-body-0001"},
            json={
                "expectedBatchVersion": batch.version,
                "idempotencyKey": "must-not-be-in-body",
            },
        )
        missing_header = await client.post(
            f"/api/review/curation-sessions/{session.id}/pause",
            json={"expectedBatchVersion": batch.version},
        )
        paused = await client.post(
            f"/api/review/curation-sessions/{session.id}/pause",
            headers={"Idempotency-Key": "pause-request-0001"},
            json={"expectedBatchVersion": batch.version},
        )
        repeated_pause = await client.post(
            f"/api/review/curation-sessions/{session.id}/pause",
            headers={"Idempotency-Key": "pause-request-0001"},
            json={"expectedBatchVersion": batch.version},
        )
        stale_pause = await client.post(
            f"/api/review/curation-sessions/{session.id}/pause",
            headers={"Idempotency-Key": "pause-request-stale-0001"},
            json={"expectedBatchVersion": batch.version},
        )
        resumed = await client.post(
            f"/api/review/curation-sessions/{session.id}/resume",
            headers={"Idempotency-Key": "resume-request-0001"},
            json={"expectedBatchVersion": paused.json()["batchVersion"]},
        )
        repeated_resume = await client.post(
            f"/api/review/curation-sessions/{session.id}/resume",
            headers={"Idempotency-Key": "resume-request-0001"},
            json={"expectedBatchVersion": paused.json()["batchVersion"]},
        )

    assert body_key.status_code == 422
    assert missing_header.status_code == 422
    assert paused.status_code == 202, paused.text
    assert paused.json()["batchStatus"] == "paused"
    assert paused.json()["controls"] == {
        "canPause": False,
        "canResume": True,
        "canTerminate": True,
    }
    assert paused.json()["progress"] == {
        "phase": "discovery",
        "completed": 1,
            "total": 2,
            "generatedCandidateCount": 0,
            "activeWorkers": 0,
            "retryableUnits": 1,
            "pendingUnits": 0,
    }
    assert repeated_pause.status_code == 202
    assert repeated_pause.json()["batchVersion"] == paused.json()["batchVersion"]
    assert stale_pause.status_code == 409
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["executionId"] != execution.id
    assert resumed.json()["activeBatchId"] == batch.id
    assert resumed.json()["batchStatus"] == "generating"
    assert repeated_resume.status_code == 202
    assert repeated_resume.json()["executionId"] == resumed.json()["executionId"]
    assert scheduled == [resumed.json()["executionId"]]

    control_event = next(
        event
        for event in app.replay_events(session.id, after_id=None)
        if event.type == "curation.control.changed"
        and event.payload["operation"] == "pause"
    )
    assert control_event.payload == {
        "resourceId": session.id,
        "batchId": batch.id,
        "status": "pausing",
        "operation": "pause",
        "version": batch.version + 1,
    }
    assert control_event.id in {
        event.id
        for event in app.replay_events(session.id, after_id=control_event.id - 1)
    }


@pytest.mark.asyncio
async def test_concurrent_same_key_resume_is_linearized_and_projects_bound_run(
    application, monkeypatch
) -> None:
    app, source_ids = application
    review = app.review("w1")
    session, batch, original_execution = await _seed_running_curation(
        review, source_ids[0]
    )
    paused = await review.pause_curation_session(
        session.id,
        expected_batch_version=batch.version,
        idempotency_key="pause-before-concurrent-resume-0001",
    )
    expected_version = paused["batch_version"]
    original_prepare = review.executions.prepare
    prepare_entered = asyncio.Event()
    release_prepare = asyncio.Event()
    prepare_calls: list[str] = []

    async def prepare_at_barrier(*args, **kwargs):
        prepare_calls.append("entered")
        prepare_entered.set()
        await release_prepare.wait()
        return await original_prepare(*args, **kwargs)

    scheduled: list[str] = []
    monkeypatch.setattr(review.executions, "prepare", prepare_at_barrier)
    monkeypatch.setattr(
        review.executions,
        "run_prepared",
        lambda prepared, *, graph_input: scheduled.append(prepared.id),
    )

    first = asyncio.create_task(
        review.resume_curation_session(
            session.id,
            expected_batch_version=expected_version,
            idempotency_key="concurrent-resume-request-0001",
        )
    )
    await asyncio.wait_for(prepare_entered.wait(), timeout=0.2)
    reservation = review.repository.find_curation_control_receipt(
        batch.id, "concurrent-resume-request-0001"
    )
    assert reservation is not None
    assert reservation.execution_id is None
    assert reservation.result_status == "preparing"
    assert reservation.request_digest == sha256(
        json.dumps(
            {
                "expectedVersion": expected_version,
                "operation": "resume",
                "reason": "paused",
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    second = asyncio.create_task(
        review.resume_curation_session(
            session.id,
            expected_batch_version=expected_version,
            idempotency_key="concurrent-resume-request-0001",
        )
    )
    await asyncio.sleep(0)
    release_prepare.set()
    results = await asyncio.gather(first, second, return_exceptions=True)

    assert all(isinstance(result, dict) for result in results), results
    resources = [result for result in results if isinstance(result, dict)]
    assert resources[0]["active_batch_id"] == batch.id
    assert resources[0]["execution_id"] == resources[1]["execution_id"]
    resumed_execution_id = resources[0]["execution_id"]
    assert prepare_calls == ["entered"]
    assert scheduled == [resumed_execution_id]
    attempts = review.sessions.repository.connection.execute(
        "SELECT execution_id FROM review_curation_batch_attempts "
        "WHERE batch_id = ? ORDER BY ordinal",
        (batch.id,),
    ).fetchall()
    assert [row[0] for row in attempts] == [
        original_execution.id,
        resumed_execution_id,
    ]
    executions = review.sessions.repository.list_executions(session.id)
    assert len(executions) == 2
    assert all(run.status not in {"queued", "cancelled"} for run in executions[1:])

    monkeypatch.setattr(review.executions, "prepare", original_prepare)
    review.sessions.repository.transition_execution(
        resumed_execution_id, expected=("running",), target="completed"
    )
    unrelated = await original_prepare(
        session,
        input={"operation": "unrelated-session-execution"},
        project_input_message=False,
    )
    resource = await review.curation_resource(session.id)

    assert unrelated.id != resumed_execution_id
    assert resource["execution_id"] == resumed_execution_id
    assert resource["execution_status"] == "completed"


@pytest.mark.asyncio
async def test_terminate_preserves_interrupted_execution_end_and_timing(
    application,
) -> None:
    app, source_ids = application
    review = app.review("w1")
    session, batch, execution = await _seed_running_curation(
        review, source_ids[0]
    )
    review.sessions.repository.transition_execution(
        execution.id, expected=("running",), target="interrupted"
    )
    connection = review.sessions.repository.connection
    connection.execute(
        "UPDATE agent_runs SET started_at = datetime('now', '-2 hours'), "
        "finished_at = datetime('now', '-1 hour') WHERE id = ?",
        (execution.id,),
    )
    connection.execute(
        "UPDATE review_question_batches SET status = 'interrupted' WHERE id = ?",
        (batch.id,),
    )
    connection.execute(
        "UPDATE review_curation_sessions SET stage = 'interrupted' "
        "WHERE session_id = ?",
        (session.id,),
    )
    connection.commit()
    before_execution = review.sessions.repository.get_execution(execution.id)
    before_timing = review.repository.curation_batch_timing(batch.id)

    terminated = await review.terminate_curation_session(
        session.id,
        expected_batch_version=batch.version,
        idempotency_key="terminate-after-hour-interrupted-0001",
    )

    after_execution = review.sessions.repository.get_execution(execution.id)
    after_timing = review.repository.curation_batch_timing(batch.id)
    assert terminated["batch_status"] == "terminated"
    assert after_execution.status == "interrupted"
    assert after_execution.finished_at == before_execution.finished_at
    assert after_timing == before_timing


@pytest.mark.asyncio
async def test_concurrent_duplicate_pause_emits_one_control_event_sequence(
    application, monkeypatch
) -> None:
    app, source_ids = application
    review = app.review("w1")
    session, batch, _execution = await _seed_running_curation(
        review, source_ids[0]
    )
    original_publish = review.events.publish
    transient_entered = asyncio.Event()
    release_transient = asyncio.Event()
    transient_calls = 0

    async def publish_at_barrier(session_id, execution_id, event_type, payload):
        nonlocal transient_calls
        if (
            event_type == "curation.control.changed"
            and payload.get("status") == "pausing"
        ):
            transient_calls += 1
            transient_entered.set()
            await release_transient.wait()
        return await original_publish(
            session_id, execution_id, event_type, payload
        )

    monkeypatch.setattr(review.events, "publish", publish_at_barrier)
    first = asyncio.create_task(
        review.pause_curation_session(
            session.id,
            expected_batch_version=batch.version,
            idempotency_key="concurrent-pause-request-0001",
        )
    )
    await asyncio.wait_for(transient_entered.wait(), timeout=0.2)
    second = asyncio.create_task(
        review.pause_curation_session(
            session.id,
            expected_batch_version=batch.version,
            idempotency_key="concurrent-pause-request-0001",
        )
    )
    await asyncio.sleep(0)
    release_transient.set()
    results = await asyncio.gather(first, second, return_exceptions=True)

    assert all(isinstance(result, dict) for result in results), results
    assert transient_calls == 1
    control_events = [
        event
        for event in app.replay_events(session.id, after_id=None)
        if event.type == "curation.control.changed"
        and event.payload["operation"] == "pause"
    ]
    assert [event.payload["status"] for event in control_events] == [
        "pausing",
        "paused",
    ]


@pytest.mark.asyncio
async def test_terminate_is_idempotent_and_cannot_resume(
    application
) -> None:
    app, source_ids = application
    api = _api_with_review_conflicts(app)
    review = app.review("w1")
    session, batch, _execution = await _seed_running_curation(
        review, source_ids[0]
    )

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        terminated = await client.post(
            f"/api/review/curation-sessions/{session.id}/terminate",
            headers={"Idempotency-Key": "terminate-request-0001"},
            json={"expectedBatchVersion": batch.version},
        )
        repeated = await client.post(
            f"/api/review/curation-sessions/{session.id}/terminate",
            headers={"Idempotency-Key": "terminate-request-0001"},
            json={"expectedBatchVersion": batch.version},
        )
        resumed = await client.post(
            f"/api/review/curation-sessions/{session.id}/resume",
            headers={"Idempotency-Key": "resume-terminated-0001"},
            json={"expectedBatchVersion": terminated.json()["batchVersion"]},
        )

    assert terminated.status_code == 202
    assert terminated.json()["batchStatus"] == "terminated"
    assert terminated.json()["controls"] == {
        "canPause": False,
        "canResume": False,
        "canTerminate": False,
    }
    assert repeated.status_code == 202
    assert repeated.json()["batchVersion"] == terminated.json()["batchVersion"]
    assert resumed.status_code == 409


@pytest.mark.asyncio
async def test_natural_completion_wins_late_pause(
    api, application
) -> None:
    app, source_ids = application
    review = app.review("w1")
    session, batch, execution = await _seed_running_curation(
        review, source_ids[0]
    )
    review.sessions.repository.transition_execution(
        execution.id, expected=("running",), target="completed"
    )
    completed = review.repository.update_batch_status(
        batch.id, "completed", expected_run_id=execution.id
    )

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/review/curation-sessions/{session.id}/pause",
            headers={"Idempotency-Key": "pause-after-complete-0001"},
            json={"expectedBatchVersion": batch.version},
        )

    assert response.status_code == 202, response.text
    assert response.json()["batchStatus"] == "completed"
    assert response.json()["batchVersion"] == completed.version
    assert response.json()["controls"] == {
        "canPause": False,
        "canResume": False,
        "canTerminate": False,
    }


@pytest.mark.asyncio
async def test_curation_resource_projects_timing_workers_and_read_only_provisional(
    api, application
) -> None:
    app, source_ids = application
    review = app.review("w1")
    session, batch, execution = await _seed_running_curation(
        review, source_ids[0]
    )
    completed_item = review.repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="enrichment",
        unit_index=0,
        input_digest="a" * 64,
        source_refs=(f"{source_ids[0]}#section-0001",),
    )
    review.repository.complete_curation_work_item(
        review.repository.start_curation_work_item(completed_item.id).id,
        output={
            "candidates": [
                _provisional_candidate(
                    "Durable pause", f"{source_ids[0]}#section-0001"
                ),
                _provisional_candidate(
                    "Durable resume", f"{source_ids[0]}#section-0001"
                ),
            ]
        },
    )
    running_item = review.repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="enrichment",
        unit_index=1,
        input_digest="b" * 64,
        source_refs=(f"{source_ids[0]}#section-0002",),
    )
    review.repository.start_curation_work_item(running_item.id)
    review.sessions.repository.connection.execute(
        "UPDATE agent_runs SET started_at = '2026-07-22 00:00:00', "
        "finished_at = '2026-07-22 00:00:10' WHERE id = ?",
        (execution.id,),
    )
    review.sessions.repository.connection.commit()

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        detail = await client.get(
            f"/api/review/curation-sessions/{session.id}"
        )
        formal_candidates = await client.get(
            "/api/review/question-candidates",
            params={"workspaceId": "w1"},
        )

    assert detail.status_code == 200, detail.text
    resource = detail.json()
    assert resource["batchStatus"] == "generating"
    assert resource["batchVersion"] == batch.version
    assert resource["progress"] == {
        "phase": "enrichment",
        "completed": 1,
        "total": 2,
        "generatedCandidateCount": 2,
        "activeWorkers": 1,
        "retryableUnits": 0,
        "pendingUnits": 0,
    }
    assert resource["timing"] == {
        "currentElapsedMs": 10_000,
        "cumulativeElapsedMs": 10_000,
    }
    assert resource["controls"] == {
        "canPause": True,
        "canResume": False,
        "canTerminate": True,
    }
    assert resource["provisionalCandidates"] == [
        {
            "id": f"{completed_item.id}:0",
            "title": "Durable pause",
            "questionText": "Explain Durable pause",
            "sourceRefs": [f"{source_ids[0]}#section-0001"],
            "seedTaskId": None,
            "answerBasis": "unknown",
            "materialSupport": "unknown",
            "needsReview": True,
            "normalizationIssues": [],
            "status": "completed",
            "version": 0,
            "errorCode": None,
        },
        {
            "id": f"{completed_item.id}:1",
            "title": "Durable resume",
            "questionText": "Explain Durable resume",
            "sourceRefs": [f"{source_ids[0]}#section-0001"],
            "seedTaskId": None,
            "answerBasis": "unknown",
            "materialSupport": "unknown",
            "needsReview": True,
            "normalizationIssues": [],
            "status": "completed",
            "version": 0,
            "errorCode": None,
        },
    ]
    assert formal_candidates.status_code == 200
    assert formal_candidates.json() == []
    assert "draft" not in resource["provisionalCandidates"][0]


@pytest.mark.asyncio
async def test_curation_resource_switches_to_seed_progress_after_discovery(
    application,
) -> None:
    app, source_ids = application
    review = app.review("w1")
    session, batch, _execution = await _seed_running_curation(
        review, source_ids[0]
    )
    source_ref = f"{source_ids[0]}#section-0001"
    discovery = review.repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest="a" * 64,
        source_refs=(source_ref,),
        processor_kind="deterministic",
    )
    review.repository.complete_deterministic_curation_work_item(
        discovery.id,
        output={
            "seeds": [{
                "question_text": "What happens after discovery?",
                "source_ref": source_ref,
                "source_refs": [source_ref],
            }]
        },
    )

    resource = await review.curation_resource(session.id)

    assert resource["progress"] == {
        "phase": "enrichment",
        "completed": 0,
        "total": 1,
        "generated_candidate_count": 0,
        "active_workers": 0,
        "retryable_units": 0,
        "pending_units": 1,
    }


@pytest.mark.asyncio
async def test_provisional_candidates_are_stable_and_capped_at_200(
    application,
) -> None:
    app, source_ids = application
    review = app.review("w1")
    session, batch, _execution = await _seed_running_curation(
        review, source_ids[0]
    )
    source_ref = f"{source_ids[0]}#section-0001"
    for unit_index in range(67):
        item = review.repository.plan_curation_work_item(
            batch_id=batch.id,
            stage="enrichment",
            unit_index=unit_index,
            input_digest=f"{unit_index:064x}",
            source_refs=(source_ref,),
        )
        review.repository.complete_curation_work_item(
            review.repository.start_curation_work_item(item.id).id,
            output={
                "candidates": [
                    _provisional_candidate(
                        f"Candidate {unit_index * 3 + ordinal}", source_ref
                    )
                    for ordinal in range(3)
                ]
            },
        )

    first = await review.curation_resource(session.id)
    second = await review.curation_resource(session.id)

    assert len(first["provisional_candidates"]) == 200
    assert first["provisional_candidates"] == second["provisional_candidates"]
    assert len({item["id"] for item in first["provisional_candidates"]}) == 200


@pytest.mark.asyncio
async def test_graph_failure_atomically_fails_batch_session_and_keeps_completed_work(
    application,
) -> None:
    app, source_ids = application
    review = app.review("w1")
    session, batch, execution = await _seed_running_curation(
        review, source_ids[0]
    )
    item = review.repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest="c" * 64,
        source_refs=(f"{source_ids[0]}#section-0001",),
        processor_kind="deterministic",
    )
    completed = review.repository.complete_deterministic_curation_work_item(
        item.id,
        output={
            "seeds": [
                {
                    "question_text": "What survives failure?",
                    "source_ref": f"{source_ids[0]}#section-0001",
                    "source_refs": [f"{source_ids[0]}#section-0001"],
                }
            ]
        },
    )

    failed = review.repository.fail_curation_batch(
        batch.id, expected_run_id=execution.id
    )

    assert failed.status == "failed"
    assert review.repository.get_curation_session(session.id).stage == "failed"
    assert review.repository.get_curation_work_item(item.id) == completed


@pytest.mark.asyncio
async def test_initial_attempt_and_legacy_retry_reuse_failed_batch(
    api, application, monkeypatch
) -> None:
    app, source_ids = application
    review = app.review("w1")
    created = await review.create_curation_session(source_refs=(source_ids[0],))
    await app.wait_execution(created["execution_id"])
    batch_id = created["active_batch_id"]
    initial_attempts = review.sessions.repository.connection.execute(
        "SELECT execution_id, reason FROM review_curation_batch_attempts "
        "WHERE batch_id = ? ORDER BY ordinal",
        (batch_id,),
    ).fetchall()
    assert [(row[0], row[1]) for row in initial_attempts] == [
        (created["execution_id"], "initial")
    ]

    failed_execution = review.sessions.repository.latest_execution(created["id"])
    assert failed_execution is not None
    review.sessions.repository.connection.execute(
        "UPDATE agent_runs SET status = 'failed', finished_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (failed_execution.id,),
    )
    review.sessions.repository.connection.execute(
        "UPDATE review_question_batches SET status = 'failed', version = version + 1 "
        "WHERE id = ?",
        (batch_id,),
    )
    review.sessions.repository.connection.execute(
        "UPDATE review_curation_sessions SET stage = 'failed' WHERE session_id = ?",
        (created["id"],),
    )
    review.sessions.repository.connection.commit()
    scheduled: list[str] = []
    monkeypatch.setattr(
        review.executions,
        "run_prepared",
        lambda prepared, *, graph_input: scheduled.append(prepared.id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        retried = await client.post(
            f"/api/review/curation-sessions/{created['id']}/retry"
        )
        replayed = await client.post(
            f"/api/review/curation-sessions/{created['id']}/retry"
        )

    assert retried.status_code == 202, retried.text
    assert retried.json()["activeBatchId"] == batch_id
    assert retried.json()["executionId"] != failed_execution.id
    assert replayed.status_code == 202, replayed.text
    assert replayed.json()["activeBatchId"] == batch_id
    assert replayed.json()["executionId"] == retried.json()["executionId"]
    receipt = review.sessions.repository.connection.execute(
        "SELECT idempotency_key FROM review_curation_control_receipts "
        "WHERE batch_id = ? AND operation = 'resume'",
        (batch_id,),
    ).fetchone()
    assert receipt[0] == f"legacy-retry:{failed_execution.id}"
    assert scheduled == [retried.json()["executionId"]]


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


@pytest.mark.asyncio
async def test_cancelling_after_staging_cleans_private_artifact_immediately(
    api, application, monkeypatch
) -> None:
    app, source_ids = application
    review = app.review("w1")
    staged = asyncio.Event()
    original_stage = KnowledgeDraftService.stage_curation_draft

    async def block_after_stage(self, batch_id, command):
        result = await original_stage(self, batch_id, command)
        staged.set()
        await asyncio.Event().wait()
        return result

    monkeypatch.setattr(
        KnowledgeDraftService,
        "stage_curation_draft",
        block_after_stage,
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
        await asyncio.wait_for(staged.wait(), timeout=1)
        execution = review.sessions.repository.get_execution(
            resource["executionId"]
        )
        batch_id = str(execution.input["batch_id"])
        referenced_id = "referenced-draft-during-cancel"
        referenced_path = (
            review.workspace_root
            / "artifacts/review/drafts"
            / f"{referenced_id}.md"
        )
        referenced_path.parent.mkdir(parents=True, exist_ok=True)
        referenced_content = b"# committed reference\n"
        referenced_path.write_bytes(referenced_content)
        referenced_hash = sha256(referenced_content).hexdigest()
        connection = review.sessions.repository.connection
        connection.execute(
            "INSERT INTO review_curation_staged_drafts "
            "(draft_id, batch_id, execution_id, content_path, content_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                referenced_id,
                batch_id,
                execution.id,
                f"artifacts/review/drafts/{referenced_id}.md",
                referenced_hash,
            ),
        )
        connection.execute(
            "INSERT INTO knowledge_drafts "
            "(id, workspace_id, session_id, run_id, domain, document_type, "
            "document_id, title, content_path, content_hash, status) "
            "VALUES (?, 'w1', ?, ?, 'review', 'question', ?, 'Referenced', "
            "?, ?, 'review_pending')",
            (
                referenced_id,
                resource["id"],
                execution.id,
                f"question-{referenced_id}",
                f"artifacts/review/drafts/{referenced_id}.md",
                referenced_hash,
            ),
        )
        connection.commit()
        terminal = await app.cancel_execution(resource["executionId"])

    assert terminal.status == "cancelled"
    assert review.sessions.repository.get_execution(
        resource["executionId"]
    ).status != "completed"
    assert review.sessions.repository.connection.execute(
        "SELECT COUNT(*) FROM review_curation_staged_drafts "
        "WHERE execution_id = ?",
        (resource["executionId"],),
    ).fetchone()[0] == 0
    assert referenced_path.read_bytes() == referenced_content
    assert [
        path.name
        for path in (
            review.workspace_root / "artifacts/review/drafts"
        ).glob("*.md")
    ] == [f"{referenced_id}.md"]


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
                source_refs=(source_ids[0],),
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

        async def fake_publish(
            candidate_id, *, idempotency_key, confirm_ai_supplement=False
        ):
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
                    "confirmedAiCandidateIds": [first.id, second.id],
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
        await app.wait_execution(rewritten.json()["executionId"])
        candidate = (await client.get(
            f"/api/review/question-candidates/{candidate_id}"
        )).json()
        assert candidate["curationSessionId"] == created["id"]
        assert candidate["draft"]["id"] != original["draft"]["id"]

        historical = await app.get_draft(original["draft"]["id"])
        assert historical["status"] == "superseded"
        with pytest.raises(DraftNotEditableError):
            await app.update_draft(
                historical["id"],
                UpdateDraftCommand(
                    expected_version=historical["version"],
                    markdown="# must remain historical\n",
                ),
            )
        with pytest.raises(DraftNotEditableError):
            await app.request_draft_publication(historical["id"])

        current = await app.get_draft(candidate["draft"]["id"])
        edited = await app.update_draft(
            current["id"],
            UpdateDraftCommand(
                expected_version=current["version"],
                markdown=current["markdown"] + "\n## 可继续编辑\n",
            ),
        )
        assert edited["status"] == "review_pending"
        assert edited["version"] == current["version"] + 1


@pytest.mark.asyncio
async def test_candidate_publication_retries_transient_projection_lock(
    api, application, monkeypatch
) -> None:
    app, source_ids = application
    review = app.review("w1")
    handler = review.hitl._handlers.get("knowledge.publish")
    original_after_publication = handler._after_publication
    attempts = 0

    def flaky_after_publication(draft, publication):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        return original_after_publication(draft, publication)

    monkeypatch.setattr(
        handler, "_after_publication", flaky_after_publication
    )
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
            await client.get(
                f"/api/review/curation-sessions/{created['id']}"
            )
        ).json()
        candidate_id = detail["summary"]["items"][0]["candidateId"]

        published = await client.post(
            f"/api/review/question-candidates/{candidate_id}/publish",
            json={
                "idempotencyKey": "publish-after-transient-lock",
                "confirmAiSupplement": True,
            },
        )

    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert attempts == 2


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
        with pytest.raises(ReviewConflictError, match="AI supplement"):
            await app.review("w1").publish_candidate(
                first_candidate_id,
                idempotency_key="publish-without-ai-confirmation",
            )
        published = await client.post(
            f"/api/review/question-candidates/{first_candidate_id}/publish",
            json={
                "idempotencyKey": "publish-original-question",
                "confirmAiSupplement": True,
            },
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
                    "confirmAiSupplement": True,
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
async def test_legacy_retry_cannot_reopen_review_pending_batch(
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
        finalized = review.repository.get_batch(batch_id)
        assert finalized.status == "review_pending"

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
        assert review.repository.get_batch(batch_id) == finalized
        assert review.repository.get_curation_session(session_id).stage == "failed"


@pytest.mark.asyncio
async def test_reused_sources_warn_but_do_not_block_new_session(
    api, application, tmp_path: Path
) -> None:
    app, _source_ids = application
    sources = KnowledgeSourceService(tmp_path / "workspace", workspace_id="w1")
    low_signal = await sources.create(
        original_filename="keywords.md",
        content_type="text/markdown",
        content=b"Redis TTL",
    )
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/review/curation-sessions",
            json={"workspaceId": "w1", "sourceRefs": [low_signal.id]},
        )
        assert first.status_code == 202
        await app.wait_execution(first.json()["executionId"])

        repeated = await client.post(
            "/api/review/curation-sessions",
            json={"workspaceId": "w1", "sourceRefs": [low_signal.id]},
        )

        assert repeated.status_code == 202, repeated.text
        assert repeated.json()["id"] != first.json()["id"]
        assert repeated.json()["warnings"] == [
            {"sourceId": low_signal.id, "code": "source_previously_curated"},
            {"sourceId": low_signal.id, "code": "low_signal"},
        ]
        assert repeated.json()["sources"][0]["organizationState"] == (
            "previously_curated"
        )


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
