from __future__ import annotations

from pathlib import Path
from hashlib import sha256

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.graph import END, START, StateGraph

from app.agents.r2_contracts import AnswerEvaluationV2, SessionReportOutput
from app.api.dependencies import get_agent_application
from app.api.routes_review import router as review_router
from app.application.workspace_runtime import AgentApplication
from app.graphs.review_discussion import create_review_discussion_graph
from app.graphs.review_round import create_review_round_graph
from app.review.errors import InputAlreadyResolvedError
from app.review.models import QuestionSnapshot


class FakeRoundAgents:
    async def evaluate(self, **_values):
        return AnswerEvaluationV2(
            score="good",
            missing_key_points=[],
            evidence="回答覆盖关键点",
            follow_up_required=False,
            follow_up_prompt=None,
            mastery_suggestion="stable",
        )

    async def report(self, **_values):
        return SessionReportOutput(
            title="复习报告",
            markdown="# 复习报告\n\n本轮回答完整。",
            mastery_explanation="当前题目已稳定掌握。",
        )

    async def discuss(self, **_values):
        return "这是基于冻结题目与 attempt 的解释。"


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
        if kind == "question.curate":
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
        input_value = round_value["currentInput"]

        answered = await client.post(
            f"/api/review/rounds/{round_value['id']}/answers",
            json={
                "inputRequestId": input_value["id"],
                "version": input_value["version"],
                "idempotencyKey": "answer-q1-0001",
                "value": "比较事务上下界和活跃事务集合",
            },
        )
        assert answered.status_code == 200, answered.text
        result = answered.json()
        assert result["status"] == "report_pending"
        assert result["executionStatus"] == "waiting_for_approval"
        assert result["attempts"][0]["evaluation"]["score"] == "good"

        duplicate = await client.post(
            f"/api/review/rounds/{round_value['id']}/answers",
            json={
                "inputRequestId": input_value["id"],
                "version": input_value["version"],
                "idempotencyKey": "answer-q1-0001",
                "value": "比较事务上下界和活跃事务集合",
            },
        )
        assert duplicate.status_code == 200
        assert len(duplicate.json()["attempts"]) == 1

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
        await application.wait_execution(batch["runId"])
        detail = await client.get(
            f"/api/review/question-batches/{batch['id']}"
        )
        assert detail.status_code == 200, detail.text
        value = detail.json()
        assert value["status"] == "completed"
        assert value["candidateCount"] == 1
        assert value["candidates"][0]["correctionNote"] == "补齐治理方式"
        assert value["candidates"][0]["draft"]["status"] == "review_pending"
