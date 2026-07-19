from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.context import AgentContext
from app.agents.factory import ModelOverride
from app.agents.review_round_contracts import (
    ReviewSessionReportOutput,
    RoundAnswerEvaluation,
)
from app.agents.review_round import ReviewRoundAgents
from app.application.session_service import ProductRepository
from app.graphs.review_round import DraftRef, create_review_round_graph
from app.infrastructure.runtime_database import connect_runtime_database
from app.review.models import (
    MasteryProjection,
    QuestionSnapshot,
    ReviewRoundSettings,
)
from app.review.repository import ReviewRepository


class RecordingAgent:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def ainvoke(self, input, config=None, *, context=None):
        self.calls.append((input, config, context))
        return self.result


class RecordingFactory:
    def __init__(self) -> None:
        self.calls = []

    def create(self, spec, **values):
        self.calls.append((spec, values))
        return RecordingAgent({})


def _context(session_id: str = "s1") -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=Path("/workspace"),
        session_id=session_id,
        run_id="r1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )


def _question() -> QuestionSnapshot:
    return QuestionSnapshot(
        question_id="q1",
        document_id="doc-q1",
        content_hash="a" * 64,
        title="MVCC",
        question_text="Read View 如何判断可见性？",
        reference_answer="比较事务上下界和活跃事务列表。",
        topics=("database",),
        difficulty="medium",
        key_points=("上下界", "活跃事务列表"),
        follow_ups=("活跃事务中的版本是否可见？",),
    )


@pytest.mark.asyncio
async def test_evaluation_uses_isolated_thread_and_optional_supplement() -> None:
    evaluation = RoundAnswerEvaluation(
        score="good",
        missing_key_points=[],
        evidence="补充回答覆盖活跃事务列表。",
        follow_up_required=False,
        follow_up_prompt=None,
        mastery_suggestion="stable",
    )
    evaluator = RecordingAgent({"structured_response": evaluation})
    agents = ReviewRoundAgents(
        evaluator=evaluator,
        reporter=RecordingAgent({}),
        discussion=RecordingAgent({}),
    )

    result = await agents.evaluate(
        question=_question(),
        answer="比较事务 ID 上下界",
        supplement="活跃事务中的版本不可见",
        context=_context(),
        config={"configurable": {"thread_id": "s1"}},
    )

    assert result == evaluation
    assert evaluator.calls[0][1]["configurable"] == {
        "thread_id": "s1:answer_evaluation"
    }
    assert "补充回答" in evaluator.calls[0][0]["messages"][0].content


@pytest.mark.asyncio
async def test_report_uses_report_role_thread() -> None:
    report = ReviewSessionReportOutput(
        title="数据库复习报告",
        markdown="# 数据库复习报告\n",
        mastery_explanation="MVCC 已趋于稳定。",
    )
    reporter = RecordingAgent({"structured_response": report})
    agents = ReviewRoundAgents(
        evaluator=RecordingAgent({}),
        reporter=reporter,
        discussion=RecordingAgent({}),
    )

    result = await agents.report(
        attempts=({"questionId": "q1", "score": "good"},),
        settings={"mode": "weak-point"},
        prior_reports=(),
        context=_context(),
        config={"configurable": {"thread_id": "s1"}},
    )

    assert result == report
    assert reporter.calls[0][1]["configurable"] == {
        "thread_id": "s1:report_summarization"
    }


def test_round_agents_apply_model_override_only_to_evaluator() -> None:
    factory = RecordingFactory()
    override = ModelOverride("provider-model-1", "high")

    ReviewRoundAgents.create(
        factory,  # type: ignore[arg-type]
        model_bindings={
            "answer_evaluation": "default-evaluator",
            "report_summarization": "reporter",
            "agent_chat": "chat",
        },
        answer_model_override=override,
    )

    by_role = {spec.role: values for spec, values in factory.calls}
    assert by_role["answer_evaluation"]["model_override"] == override
    assert by_role["report_summarization"]["model_override"] is None
    assert by_role["agent_chat"]["model_override"] is None


class SequencedRoundAgents:
    def __init__(self) -> None:
        self.evaluations = []

    async def evaluate(self, *, question, answer, supplement, **_kwargs):
        self.evaluations.append((question.question_id, answer, supplement))
        if question.question_id == "q1" and supplement is None:
            return RoundAnswerEvaluation(
                score="partial",
                missing_key_points=["活跃事务列表"],
                evidence="回答了上下界",
                follow_up_required=True,
                follow_up_prompt="活跃事务中的版本是否可见？",
                mastery_suggestion="partial",
            )
        return RoundAnswerEvaluation(
            score="good",
            missing_key_points=[],
            evidence="回答完整",
            follow_up_required=False,
            follow_up_prompt=None,
            mastery_suggestion="stable",
        )

    async def report(self, **_kwargs):
        return ReviewSessionReportOutput(
            title="复习报告",
            markdown="# 复习报告\n",
            mastery_explanation="掌握度提升",
        )


def _round_question(question_id: str) -> QuestionSnapshot:
    return QuestionSnapshot(
        question_id=question_id,
        document_id=f"doc-{question_id}",
        content_hash=("a" if question_id == "q1" else "b") * 64,
        title=question_id,
        question_text=f"Explain {question_id}",
        reference_answer=f"Answer {question_id}",
        topics=("database",),
        difficulty="medium",
        key_points=("point",),
        follow_ups=("why",),
    )


@pytest.mark.asyncio
async def test_review_round_graph_reuses_one_execution_across_interrupts(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    product = ProductRepository(connection)
    product.create_session(
        workspace_id="w1",
        kind="review.round",
        title="Round",
        session_id="s1",
    )
    product.create_execution(
        "s1", input={}, model_bindings={}, execution_id="r1"
    )
    repository = ReviewRepository(connection)
    repository.create_round(
        workspace_id="w1",
        session_id="s1",
        execution_id="r1",
        settings=ReviewRoundSettings(
            topics=(),
            difficulties=("medium",),
            mode="random-mixed",
            question_count=2,
            allow_follow_up=True,
            seed=1,
            answer_model_id="model-1",
            reasoning_effort="none",
        ),
        question_snapshots=(_round_question("q1"), _round_question("q2")),
        mastery_before=MasteryProjection("w1", 0, (), ()),
        round_id="round-1",
    )
    draft_calls = []
    action_calls = []

    async def create_report_drafts(**values):
        draft_calls.append(values)
        return (
            DraftRef("session-draft", 1, "c" * 64, "session_report"),
            DraftRef("mastery-draft", 1, "d" * 64, "mastery_report"),
        )

    async def request_action(draft):
        action_calls.append(draft.id)
        return SimpleNamespace(id=f"action-{draft.id}")

    agents = SequencedRoundAgents()
    graph = create_review_round_graph(
        agents,
        repository=repository,
        create_report_drafts=create_report_drafts,
        request_publication_action=request_action,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "s1"}}
    context = _context()

    q1 = await graph.ainvoke(
        {"round_id": "round-1"}, config, context=context
    )
    q1_request = q1["__interrupt__"][0].value
    product.transition_execution(
        "r1", expected=("running",), target="waiting_for_input"
    )
    repository.accept_review_answer(
        request_id=q1_request["inputRequestId"],
        expected_version=q1_request["version"],
        idempotency_key="answer-q1",
        value="answer 1",
    )
    follow_up = await graph.ainvoke(
        Command(
            resume={
                "inputRequestId": q1_request["inputRequestId"],
                "value": "answer 1",
                "receiptId": "receipt-q1",
            }
        ),
        config,
        context=context,
    )
    follow_up_request = follow_up["__interrupt__"][0].value
    product.transition_execution(
        "r1", expected=("running",), target="waiting_for_input"
    )
    repository.accept_review_answer(
        request_id=follow_up_request["inputRequestId"],
        expected_version=follow_up_request["version"],
        idempotency_key="follow-up-q1",
        value="supplement",
    )
    q2 = await graph.ainvoke(
        Command(
            resume={
                "inputRequestId": follow_up_request["inputRequestId"],
                "value": "supplement",
                "receiptId": "receipt-follow-up",
            }
        ),
        config,
        context=context,
    )
    q2_request = q2["__interrupt__"][0].value
    product.transition_execution(
        "r1", expected=("running",), target="waiting_for_input"
    )
    repository.accept_review_answer(
        request_id=q2_request["inputRequestId"],
        expected_version=q2_request["version"],
        idempotency_key="answer-q2",
        value="answer 2",
    )
    first_approval = await graph.ainvoke(
        Command(
            resume={
                "inputRequestId": q2_request["inputRequestId"],
                "value": "answer 2",
                "receiptId": "receipt-q2",
            }
        ),
        config,
        context=context,
    )
    assert first_approval["__interrupt__"][0].value == {
        "actionId": "action-session-draft"
    }
    second_approval = await graph.ainvoke(
        Command(resume={"decision": "approved"}),
        config,
        context=context,
    )
    assert second_approval["__interrupt__"][0].value == {
        "actionId": "action-mastery-draft"
    }
    completed = await graph.ainvoke(
        Command(resume={"decision": "approved"}),
        config,
        context=context,
    )

    assert completed["status"] == "completed"
    assert completed["attempt_ids"] == [
        repository.list_attempts("round-1")[0].id,
        repository.list_attempts("round-1")[1].id,
    ]
    assert product.get_execution("r1").id == "r1"
    assert len(draft_calls) == 1
    assert action_calls == ["session-draft", "mastery-draft"]
    connection.close()


@pytest.mark.asyncio
async def test_review_round_skip_persists_without_model_evaluation(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    product = ProductRepository(connection)
    product.create_session(
        workspace_id="w1", kind="review.round", title="Round", session_id="s1"
    )
    product.create_execution("s1", input={}, model_bindings={}, execution_id="r1")
    repository = ReviewRepository(connection)
    repository.create_round(
        workspace_id="w1",
        session_id="s1",
        execution_id="r1",
        settings=ReviewRoundSettings(
            topics=(), difficulties=("medium",), mode="random-mixed",
            question_count=1, allow_follow_up=True, seed=1,
            answer_model_id="model-1", reasoning_effort="none",
        ),
        question_snapshots=(_round_question("q1"),),
        mastery_before=MasteryProjection("w1", 0, (), ()),
        round_id="round-1",
    )
    agents = SequencedRoundAgents()

    async def drafts(**_values):
        return (
            DraftRef("session", 1, "c" * 64, "session_report"),
            DraftRef("mastery", 1, "d" * 64, "mastery_report"),
        )

    async def action(draft):
        return SimpleNamespace(id=f"action-{draft.id}")

    graph = create_review_round_graph(
        agents,
        repository=repository,
        create_report_drafts=drafts,
        request_publication_action=action,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "s1"}}
    interrupted = await graph.ainvoke(
        {"round_id": "round-1"}, config, context=_context()
    )
    request = interrupted["__interrupt__"][0].value
    repository.resolve_input(
        request["inputRequestId"],
        idempotency_key="skip-q1",
        value="__skip__",
        receipt={"accepted": True},
    )
    await graph.ainvoke(
        Command(
            resume={
                "inputRequestId": request["inputRequestId"],
                "operation": "skip",
                "value": "",
                "receiptId": "skip-q1",
            }
        ),
        config,
        context=_context(),
    )

    attempts = repository.list_attempts("round-1")
    assert attempts[0].skipped is True
    assert attempts[0].evaluation is None
    assert agents.evaluations == []
    connection.close()


@pytest.mark.asyncio
async def test_skipping_follow_up_keeps_first_evaluation_and_advances(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    product = ProductRepository(connection)
    product.create_session(
        workspace_id="w1", kind="review.round", title="Round", session_id="s1"
    )
    product.create_execution("s1", input={}, model_bindings={}, execution_id="r1")
    repository = ReviewRepository(connection)
    repository.create_round(
        workspace_id="w1",
        session_id="s1",
        execution_id="r1",
        settings=ReviewRoundSettings(
            topics=(), difficulties=("medium",), mode="random-mixed",
            question_count=2, allow_follow_up=True, seed=1,
            answer_model_id="model-1", reasoning_effort="none",
        ),
        question_snapshots=(_round_question("q1"), _round_question("q2")),
        mastery_before=MasteryProjection("w1", 0, (), ()),
        round_id="round-1",
    )
    agents = SequencedRoundAgents()

    async def drafts(**_values):
        raise AssertionError("reports should not be generated yet")

    async def action(_draft):
        raise AssertionError("publication should not be requested yet")

    graph = create_review_round_graph(
        agents,
        repository=repository,
        create_report_drafts=drafts,
        request_publication_action=action,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "s1"}}
    first = await graph.ainvoke(
        {"round_id": "round-1"}, config, context=_context()
    )
    answer_request = first["__interrupt__"][0].value
    product.transition_execution(
        "r1", expected=("running",), target="waiting_for_input"
    )
    repository.accept_review_answer(
        request_id=answer_request["inputRequestId"],
        expected_version=answer_request["version"],
        idempotency_key="answer-q1",
        value="answer 1",
    )
    follow_up = await graph.ainvoke(
        Command(
            resume={
                "inputRequestId": answer_request["inputRequestId"],
                "value": "answer 1",
                "receiptId": "answer-q1",
            }
        ),
        config,
        context=_context(),
    )
    follow_up_request = follow_up["__interrupt__"][0].value
    repository.resolve_input(
        follow_up_request["inputRequestId"],
        idempotency_key="skip-follow-up-q1",
        value="__skip__",
        receipt={"accepted": True, "operation": "skip"},
    )

    second = await graph.ainvoke(
        Command(
            resume={
                "inputRequestId": follow_up_request["inputRequestId"],
                "operation": "skip",
                "value": "",
                "receiptId": "skip-follow-up-q1",
            }
        ),
        config,
        context=_context(),
    )

    assert second["__interrupt__"][0].value["ordinal"] == 2
    attempt = repository.list_attempts("round-1")[0]
    assert attempt.status == "completed"
    assert attempt.evaluation is not None
    assert attempt.follow_up_answer is None
    assert len(agents.evaluations) == 1
    connection.close()
