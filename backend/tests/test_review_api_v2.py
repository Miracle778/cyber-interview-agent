from __future__ import annotations

import json
from pathlib import Path
from hashlib import sha256

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.graph import END, START, StateGraph

from app.agents.review_round_contracts import (
    ReviewSessionReportOutput,
    RoundAnswerEvaluation,
)
from app.api.dependencies import get_agent_application
from app.api.routes_review import router as review_router
from app.application.workspace_runtime import AgentApplication
from app.agents.question_curation_contracts import (
    QuestionCandidateChunk,
    QuestionSeedChunk,
)
from app.graphs.question_curation import create_question_curation_graph
from app.graphs.review_discussion import create_review_discussion_graph
from app.graphs.review_round import create_review_round_graph
from app.infrastructure.checkpoints import AgentCheckpointer
from app.knowledge.source_registry import KnowledgeSourceService
from app.review.errors import InputAlreadyResolvedError, ReviewConflictError
from app.review.models import QuestionSnapshot
from app.review.repository import ReviewRepository


class FakeRoundAgents:
    async def evaluate(self, **_values):
        return RoundAnswerEvaluation(
            score="good",
            missing_key_points=[],
            evidence="回答覆盖关键点",
            follow_up_required=False,
            follow_up_prompt=None,
            mastery_suggestion="stable",
        )

    async def report(self, **_values):
        return ReviewSessionReportOutput(
            title="复习报告",
            markdown="# 复习报告\n\n本轮回答完整。",
            mastery_explanation="当前题目已稳定掌握。",
        )

    async def discuss(self, **_values):
        return "这是基于冻结题目与 attempt 的解释。"


class EmptyCurationAgents:
    async def discover(self, *_args, **_kwargs):
        return QuestionSeedChunk(seeds=[])

    async def enrich(self, *_args, **_kwargs):
        return QuestionCandidateChunk(candidates=[])


class FailingDiscoveryAgents(EmptyCurationAgents):
    async def discover(self, *_args, **_kwargs):
        raise RuntimeError("private provider failure")


def _real_curation_application(tmp_path: Path, agents):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def real_curation_graph_factory(kind, **dependencies):
        if kind in {"question.curate", "question.revise"}:
            return create_question_curation_graph(
                agents,
                repository=dependencies["review_repository"],
                checkpointer=dependencies["checkpointer"],
            )
        return _graph_factory(kind, **dependencies)

    application = AgentApplication(
        workspace_resolver=lambda _workspace_id: workspace,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=real_curation_graph_factory,
    )
    api = FastAPI()
    api.include_router(review_router)
    api.dependency_overrides[get_agent_application] = lambda: application
    return application, api, workspace


def _graph_factory(kind, **dependencies):
    if kind == "review.round":
        return create_review_round_graph(
            FakeRoundAgents(),
            repository=dependencies["review_repository"],
            create_report_drafts=dependencies["create_report_drafts"],
            request_publication_action=dependencies["request_publication_action"],
            checkpointer=dependencies["checkpointer"],
        )
    if kind == "review.discussion":
        return create_review_discussion_graph(
            FakeRoundAgents(), checkpointer=dependencies["checkpointer"]
        )
    graph = StateGraph(dict)

    async def complete(state):
        if kind in {"question.curate", "question.revise"}:
            return {
                **state,
                "candidates": [
                    {
                        "title": "缓存穿透",
                        "question_text": "缓存穿透是什么？",
                        "reference_answer": "请求不存在的数据导致缓存无法命中。",
                        "topics": ["cache"],
                        "difficulty": "medium",
                        "key_points": ["缓存空值", "布隆过滤器"],
                        "follow_ups": [],
                        "source_refs": ["source-api"],
                        "correction_note": "补齐治理方式",
                    }
                ],
            }
        return state

    graph.add_node("complete", complete)
    graph.add_edge(START, "complete")
    graph.add_edge("complete", END)
    return graph.compile(checkpointer=dependencies.get("checkpointer"))


@pytest_asyncio.fixture
async def application(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = AgentApplication(
        workspace_resolver=lambda _workspace_id: workspace,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=_graph_factory,
    )
    review = app.review("w1")
    product = review.executions._repository  # noqa: SLF001
    product.create_session(
        workspace_id="w1",
        kind="question.curate",
        title="Curation",
        session_id="curation-session",
    )
    product.create_execution(
        "curation-session",
        input={},
        model_bindings={},
        execution_id="curation-execution",
    )
    snapshot = QuestionSnapshot(
        question_id="q1",
        document_id="doc-q1",
        content_hash=sha256(b"# MVCC\n").hexdigest(),
        title="MVCC",
        question_text="Read View 如何判断可见性？",
        reference_answer="比较上下界和活跃事务集合。",
        topics=("database",),
        difficulty="medium",
        key_points=("上下界", "活跃事务集合"),
        follow_ups=("活跃事务中的版本是否可见？",),
    )
    repository = review.repository
    repository.create_batch(
        workspace_id="w1",
        session_id="curation-session",
        run_id="curation-execution",
        source_refs=("source-1",),
        batch_id="batch-1",
    )
    connection = product.connection
    connection.execute(
        "INSERT INTO knowledge_sources "
        "(id, workspace_id, original_filename, stored_path, content_type, size_bytes) "
        "VALUES ('source-1', 'w1', '数据库事务笔记.md', "
        "'artifacts/review/sources/source-1.md', 'text/markdown', 16)"
    )
    connection.execute(
        "INSERT INTO pending_actions "
        "(id, workspace_id, session_id, run_id, action_type, payload_json, "
        "preview_json, status, idempotency_key) VALUES "
        "('action-q1', 'w1', 'curation-session', 'curation-execution', "
        "'knowledge.publish', '{}', '{}', 'approved', 'publish-q1')"
    )
    connection.execute(
        "INSERT INTO knowledge_drafts "
        "(id, workspace_id, session_id, run_id, domain, document_type, "
        "document_id, title, content_path, content_hash, status) VALUES "
        "('draft-q1', 'w1', 'curation-session', 'curation-execution', "
        "'review', 'question', 'doc-q1', 'MVCC', "
        "'artifacts/review/drafts/draft-q1.md', ?, 'published')",
        (snapshot.content_hash,),
    )
    connection.execute(
        "INSERT INTO publication_runs "
        "(id, action_id, draft_id, expected_draft_version, "
        "expected_content_hash, document_id, target_path, state) VALUES "
        "('publication-q1', 'action-q1', 'draft-q1', 1, ?, 'doc-q1', "
        "'10_question_bank/doc-q1.md', 'completed')",
        (snapshot.content_hash,),
    )
    connection.commit()
    repository.upsert_question_source_link(
        question_id="q1",
        source_id="source-1",
        batch_id="batch-1",
        session_id="curation-session",
        evidence_ref="source-1#section-0014",
        merge_reason="generated_from_source",
    )
    draft_path = workspace / "artifacts/review/drafts/draft-q1.md"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text("# MVCC\n", encoding="utf-8")
    repository.save_candidate(
        batch_id="batch-1",
        question=snapshot,
        draft_id="draft-q1",
        source_refs=("source-1",),
        correction_note="补齐活跃事务集合判断",
        status="review_pending",
        candidate_id="candidate-q1",
    )
    repository.activate_question(
        candidate_id="candidate-q1",
        workspace_id="w1",
        document_id="doc-q1",
        draft_id="draft-q1",
        publication_id="publication-q1",
        content_hash=snapshot.content_hash,
    )
    try:
        yield app
    finally:
        await app.close()


@pytest.fixture
def api(application):
    api = FastAPI()
    api.include_router(review_router)
    api.dependency_overrides[get_agent_application] = lambda: application
    return api


@pytest.mark.asyncio
async def test_source_file_round_uses_only_that_source_and_clamps_count(
    api,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/review/rounds",
            json={
                "workspaceId": "w1",
                "selectedTopics": [],
                "difficulties": ["medium"],
                "mode": "source-file",
                "sourceId": "source-1",
                "questionCount": 10,
                "allowFollowUp": True,
                "seed": 7,
                "answerModelId": "model-1",
                "reasoningEffort": "none",
            },
        )

    assert created.status_code == 201, created.text
    value = created.json()
    assert value["questionCount"] == 1
    assert value["currentQuestion"]["id"] == "q1"
    assert value["settings"]["source_id"] == "source-1"
    assert value["settings"]["question_count"] == 1


@pytest.mark.asyncio
async def test_active_catalog_and_round_answer_are_resource_driven(
    api, application
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        questions = await client.get(
            "/api/review/questions?workspaceId=w1&topic=database"
        )
        assert questions.status_code == 200
        assert questions.json()[0]["id"] == "q1"
        assert questions.json()[0]["sourceIds"] == ["source-1"]
        candidates = await client.get(
            "/api/review/question-candidates?workspaceId=w1&topic=database"
        )
        assert candidates.status_code == 200, candidates.text
        assert candidates.json()[0]["correctionNote"] == "补齐活跃事务集合判断"
        assert candidates.json()[0]["duplicateQuestion"] is None

        created = await client.post(
            "/api/review/rounds",
            json={
                "workspaceId": "w1",
                "selectedTopics": [],
                "difficulties": ["medium"],
                "mode": "random-mixed",
                "questionCount": 1,
                "allowFollowUp": True,
                "seed": 7,
                "answerModelId": "model-1",
                "reasoningEffort": "none",
            },
        )
        assert created.status_code == 201, created.text
        round_value = created.json()
        assert round_value["status"] == "waiting_for_input"
        assert round_value["executionStatus"] == "waiting_for_input"
        assert round_value["currentQuestion"]["id"] == "q1"
        assert round_value["currentQuestion"]["sources"] == [
            {
                "sourceId": "source-1",
                "filename": "数据库事务笔记.md",
                "sectionNumbers": [14],
                "evidenceCount": 1,
                "availability": "available",
            }
        ]
        input_value = round_value["currentInput"]

        answered = await client.post(
            f"/api/review/rounds/{round_value['id']}/answers",
            json={
                "inputRequestId": input_value["id"],
                "version": input_value["version"],
                "idempotencyKey": "answer-q1-0001",
                "value": "比较事务上下界和活跃事务集合",
                "providerModelId": "model-1",
                "reasoningEffort": "high",
            },
        )
        assert answered.status_code == 202, answered.text
        receipt = answered.json()
        assert receipt["status"] == "evaluating"
        assert receipt["roundId"] == round_value["id"]
        await application.wait_execution(round_value["executionId"])
        result = (
            await client.get(f"/api/review/rounds/{round_value['id']}")
        ).json()
        assert result["status"] == "report_pending"
        assert result["executionStatus"] == "waiting_for_approval"
        assert result["attempts"][0]["evaluation"]["score"] == "good"
        assert result["settings"]["answer_model_id"] == "model-1"
        assert result["settings"]["reasoning_effort"] == "high"
        assert result["reports"]
        assert all(report["markdown"].strip() for report in result["reports"])

        duplicate = await client.post(
            f"/api/review/rounds/{round_value['id']}/answers",
            json={
                "inputRequestId": input_value["id"],
                "version": input_value["version"],
                "idempotencyKey": "answer-q1-0001",
                "value": "比较事务上下界和活跃事务集合",
            },
        )
        assert duplicate.status_code == 202
        assert duplicate.json()["receiptId"] == receipt["receiptId"]
        assert len(result["attempts"]) == 1

    review = application.locate_review_round(round_value["id"])
    with pytest.raises(InputAlreadyResolvedError):
        await review.submit_answer(
            round_value["id"],
            request_id=input_value["id"],
            version=input_value["version"],
            idempotency_key="different-answer-key",
            value="不同回答",
        )


@pytest.mark.asyncio
async def test_deleting_published_candidate_deactivates_and_restore_reactivates_catalog(
    api, application
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        deleted = await client.post(
            "/api/review/question-candidates/candidate-q1/delete",
            json={
                "idempotencyKey": "delete-published-q1",
                "expectedVersion": 1,
            },
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["items"][0]["status"] == "deleted"
        assert (await client.get(
            "/api/review/questions?workspaceId=w1"
        )).json() == []

        restored = await client.post(
            "/api/review/question-candidates/candidate-q1/restore"
        )
        assert restored.status_code == 200, restored.text
        questions = (await client.get(
            "/api/review/questions?workspaceId=w1"
        )).json()
        assert [question["id"] for question in questions] == ["q1"]


@pytest.mark.asyncio
async def test_skip_and_cancel_are_explicit_round_operations(api) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        payload = {
            "workspaceId": "w1",
            "selectedTopics": [],
            "difficulties": ["medium"],
            "mode": "random-mixed",
            "questionCount": 1,
            "answerModelId": "model-1",
            "reasoningEffort": "none",
        }
        created = (await client.post("/api/review/rounds", json=payload)).json()
        skipped = await client.post(
            f"/api/review/rounds/{created['id']}/skip",
            json={
                "inputRequestId": created["currentInput"]["id"],
                "version": created["currentInput"]["version"],
                "idempotencyKey": "skip-q1-0000001",
            },
        )
        assert skipped.status_code == 200, skipped.text
        assert skipped.json()["attempts"][0]["skipped"] is True

        another = (await client.post("/api/review/rounds", json=payload)).json()
        cancelled = await client.post(
            f"/api/review/rounds/{another['id']}/cancel"
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_discussion_is_prepared_once_and_waits_for_real_user_message(
    api, application
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/api/review/rounds",
                json={
                    "workspaceId": "w1",
                    "selectedTopics": [],
                    "difficulties": ["medium"],
                    "mode": "random-mixed",
                    "questionCount": 1,
                    "answerModelId": "model-1",
                    "reasoningEffort": "none",
                },
            )
        ).json()
        request = created["currentInput"]
        answered = await client.post(
            f"/api/review/rounds/{created['id']}/answers",
            json={
                "inputRequestId": request["id"],
                "version": request["version"],
                "idempotencyKey": "discussion-answer-0001",
                "value": "我只提到了事务上下界",
            },
        )
        assert answered.status_code == 202
        await application.wait_execution(created["executionId"])

        prepared = await client.post(
            f"/api/review/rounds/{created['id']}/discussions",
            json={"ordinal": 1},
        )
        assert prepared.status_code == 201, prepared.text
        session_id = prepared.json()["id"]
        detail = await application.session_detail(session_id)
        assert detail["messages"] == []
        assert detail["latest_execution"]["status"] == "completed"
        assert detail["latest_execution"]["input"]["attempt_evidence"]["answer"] == "我只提到了事务上下界"

        repeated = await client.post(
            f"/api/review/rounds/{created['id']}/discussions",
            json={"ordinal": 1},
        )
        assert repeated.json()["id"] == session_id
        refreshed = (
            await client.get(f"/api/review/rounds/{created['id']}")
        ).json()
        assert refreshed["attempts"][0]["discussionSessionId"] == session_id

        execution = await application.start_execution(
            session_id, input={"message": "解释遗漏的活跃事务集合"}
        )
        await application.wait_execution(execution.id)
        after_message = await application.session_detail(session_id)
        assert [item["content"] for item in after_message["messages"]] == [
            "解释遗漏的活跃事务集合",
            "这是基于冻结题目与 attempt 的解释。",
        ]

        product = application.review("w1").executions._repository  # noqa: SLF001
        product.connection.execute(
            "UPDATE agent_runs SET status = 'failed' WHERE id = ?",
            (execution.id,),
        )
        product.connection.commit()
        retried = await client.post(
            f"/api/review/rounds/{created['id']}/discussions/{session_id}/retry"
        )
        assert retried.status_code == 202, retried.text
        await application.wait_execution(retried.json()["id"])
        after_retry = await application.session_detail(session_id)
        assert [item["role"] for item in after_retry["messages"]].count("user") == 1


@pytest.mark.asyncio
async def test_question_batch_persists_agent_candidates(api, application) -> None:
    review = application.review("w1")
    from app.knowledge.source_registry import KnowledgeSourceService

    source = await KnowledgeSourceService(
        review.workspace_root, workspace_id="w1"
    ).create(
        original_filename="cache.md",
        content_type="text/markdown",
        content="缓存穿透与缓存空值".encode(),
    )
    assert source.id
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/review/question-batches",
            json={"workspaceId": "w1", "sourceRefs": [source.id]},
        )
        assert created.status_code == 202, created.text
        batch = created.json()
        assert batch["version"] == 1
        assert batch["controlIntent"] is None
        assert batch["concurrencyLimit"] == 3
        execution = await application.wait_execution(batch["runId"])
        assert execution.status == "completed", (
            execution.error_code,
            execution.error_message,
        )
        detail = await client.get(
            f"/api/review/question-batches/{batch['id']}"
        )
        assert detail.status_code == 200, detail.text
        value = detail.json()
        assert value["status"] == "review_pending"
        assert value["candidateCount"] == 1
        assert value["candidates"][0]["correctionNote"] == "补齐治理方式"
        assert value["candidates"][0]["draft"]["status"] == "review_pending"


@pytest.mark.asyncio
async def test_public_question_batch_reaches_real_graph_without_checkpointing_corpus(
    tmp_path: Path, monkeypatch
) -> None:
    agents = EmptyCurationAgents()
    application, api, workspace = _real_curation_application(
        tmp_path, agents
    )
    source_marker = "PUBLIC_BATCH_CORPUS_MUST_NOT_ENTER_CHECKPOINT_7C31"
    source = await KnowledgeSourceService(
        workspace, workspace_id="w1"
    ).create(
        original_filename="checkpoint-safe.md",
        content_type="text/markdown",
        content=f"1、{source_marker}？\n答案保持在不可变执行输入中。".encode(),
    )
    observed_batch_ids: list[str] = []
    original_batch_input = ReviewRepository.curation_batch_input

    def record_batch_input(self, batch_id: str):
        observed_batch_ids.append(batch_id)
        return original_batch_input(self, batch_id)

    monkeypatch.setattr(
        ReviewRepository, "curation_batch_input", record_batch_input
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/review/question-batches",
                json={"workspaceId": "w1", "sourceRefs": [source.id]},
            )

        assert response.status_code == 202, response.text
        batch = response.json()
        execution = await application.wait_execution(batch["runId"])
        assert execution.status == "completed", (
            execution.error_code,
            execution.error_message,
        )
        assert observed_batch_ids == [batch["id"]]
        persisted_input = json.loads(
            application.review("w1").executions._repository.connection.execute(
                "SELECT input_json FROM agent_runs WHERE id = ?",
                (batch["runId"],),
            ).fetchone()[0]
        )
        assert persisted_input["batchId"] == batch["id"]
        assert persisted_input["batch_id"] == batch["id"]

        async with AgentCheckpointer(workspace).open() as saver:
            persisted = await saver.aget_tuple(
                {"configurable": {"thread_id": batch["sessionId"]}}
            )
            assert persisted is not None
            checkpoint_bytes = saver.serde.dumps_typed(persisted.checkpoint)[1]

        assert source_marker.encode() not in checkpoint_bytes
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_public_question_batch_reports_failed_discovery_without_failing_execution(
    tmp_path: Path, caplog
) -> None:
    application, api, workspace = _real_curation_application(
        tmp_path, FailingDiscoveryAgents()
    )
    source = await KnowledgeSourceService(
        workspace, workspace_id="w1"
    ).create(
        original_filename="plain.md",
        content_type="text/markdown",
        content=("plain source without question anchors " * 80).encode(),
    )
    caplog.set_level("ERROR", logger="app.application.execution_service")
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/review/question-batches",
                json={"workspaceId": "w1", "sourceRefs": [source.id]},
            )

        assert response.status_code == 202, response.text
        batch = response.json()
        terminal = await application.wait_execution(batch["runId"])
        review = application.review("w1")
        items = review.repository.list_curation_work_items(batch["id"])
        assert terminal.status == "completed"
        assert review.repository.get_batch(batch["id"]).status == "completed"
        assert {item.status for item in items} == {"failed"}
        assert all(item.attempt_count == 2 for item in items)
        assert "failed to persist agent execution failure" not in caplog.text
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_empty_curation_session_reports_completion_without_confirmation(
    tmp_path: Path,
) -> None:
    application, api, workspace = _real_curation_application(
        tmp_path, EmptyCurationAgents()
    )
    source = await KnowledgeSourceService(
        workspace, workspace_id="w1"
    ).create(
        original_filename="no-candidates.md",
        content="1、什么是不会生成候选的测试题？\n答案。".encode(),
        content_type="text/markdown",
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/review/curation-sessions",
                json={"workspaceId": "w1", "sourceRefs": [source.id]},
            )
            assert created.status_code == 202, created.text
            resource = created.json()
            terminal = await application.wait_execution(resource["executionId"])
            assert terminal.status == "completed"
            detail = await client.get(
                f"/api/review/curation-sessions/{resource['id']}"
            )

        assert detail.status_code == 200, detail.text
        value = detail.json()
        assert value["stage"] == "completed"
        assert value["batchStatus"] == "completed"
        summaries = [
            message["content"]
            for message in value["messages"]
            if message["messageKind"] == "curation_summary"
        ]
        assert summaries == [
            "未从本次材料中识别到可整理的题目；"
            "1 个处理单元未完成，已记录原因，可在运行提示中查看。"
        ]
        assert all("请确认" not in content for content in summaries)
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_public_question_batch_warning_does_not_fail_committed_execution(
    tmp_path: Path,
) -> None:
    application, api, workspace = _real_curation_application(
        tmp_path, EmptyCurationAgents()
    )
    source = await KnowledgeSourceService(
        workspace, workspace_id="w1"
    ).create(
        original_filename="large-question-list.md",
        content="\n\n".join(
            f"{index}、什么是边界场景 {index}？\n答案 {index}。"
            for index in range(1, 202)
        ).encode(),
        content_type="text/markdown",
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/review/question-batches",
                json={"workspaceId": "w1", "sourceRefs": [source.id]},
            )

        assert response.status_code == 202, response.text
        batch = response.json()
        terminal = await application.wait_execution(batch["runId"])
        review = application.review("w1")
        assert terminal.status == "completed", (
            terminal.error_code,
            terminal.error_message,
        )
        assert review.repository.get_batch(batch["id"]).status == "completed"
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_public_question_batch_finalization_rejection_terminalizes_without_session_projection(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    application, api, workspace = _real_curation_application(
        tmp_path, EmptyCurationAgents()
    )
    source = await KnowledgeSourceService(
        workspace, workspace_id="w1"
    ).create(
        original_filename="structured.md",
        content_type="text/markdown",
        content="1、What is a safe finalization boundary?\nAnswer.".encode(),
    )

    def reject_finalization(*_args, **_kwargs):
        raise ReviewConflictError("finalization claim rejected")

    monkeypatch.setattr(
        ReviewRepository,
        "claim_curation_finalization",
        reject_finalization,
    )
    caplog.set_level("ERROR", logger="app.application.execution_service")
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/review/question-batches",
                json={"workspaceId": "w1", "sourceRefs": [source.id]},
            )

        assert response.status_code == 202, response.text
        batch = response.json()
        terminal = await application.wait_execution(batch["runId"])
        review = application.review("w1")
        assert terminal.status == "failed"
        assert review.repository.get_batch(batch["id"]).status == "failed"
        assert "failed to persist agent execution failure" not in caplog.text
    finally:
        await application.close()
