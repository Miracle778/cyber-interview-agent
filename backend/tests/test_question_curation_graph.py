import pytest
from pydantic import ValidationError
from pathlib import Path

from app.agents.context import AgentContext
from app.agents.question_curation import QuestionCurationAgent
from app.agents.r2_contracts import (
    AnswerEvaluationV2,
    QuestionCandidate,
    QuestionCandidateBatch,
    SessionReportOutput,
)
from app.graphs.question_curation import create_question_curation_graph


class RecordingAgent:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def ainvoke(self, input, config=None, *, context=None):
        self.calls.append((input, config, context))
        return self.result


def _context() -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=Path("/workspace"),
        session_id="s1",
        run_id="r1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )


def test_question_candidate_batch_is_strict_and_source_backed() -> None:
    batch = QuestionCandidateBatch(
        candidates=[
            QuestionCandidate(
                title="MVCC 可见性",
                question_text="Read View 如何判断版本是否可见？",
                reference_answer="比较 creator_trx_id、上下界和活跃事务列表。",
                topics=["database", "mysql"],
                difficulty="medium",
                key_points=["creator_trx_id", "m_ids"],
                follow_ups=["活跃事务中的版本是否可见？"],
                source_refs=["source-1#L84"],
                correction_note="补齐活跃事务判断规则",
            )
        ]
    )

    assert batch.candidates[0].source_refs == ["source-1#L84"]
    with pytest.raises(ValidationError):
        QuestionCandidateBatch.model_validate(
            {**batch.model_dump(), "hidden_reasoning": "must not be accepted"}
        )


def test_answer_evaluation_v2_exposes_evidence_not_hidden_reasoning() -> None:
    evaluation = AnswerEvaluationV2(
        score="partial",
        missing_key_points=["m_ids"],
        evidence="回答说明了事务 ID 上下界。",
        follow_up_required=True,
        follow_up_prompt="活跃事务中的版本是否可见？",
        mastery_suggestion="partial",
    )

    assert "reasoning" not in evaluation.model_dump()
    with pytest.raises(ValidationError):
        AnswerEvaluationV2.model_validate(
            {**evaluation.model_dump(), "chain_of_thought": "secret"}
        )


def test_follow_up_prompt_is_required_only_when_follow_up_is_requested() -> None:
    with pytest.raises(ValidationError, match="follow_up_prompt"):
        AnswerEvaluationV2(
            score="partial",
            missing_key_points=["m_ids"],
            evidence="partial",
            follow_up_required=True,
            follow_up_prompt=None,
            mastery_suggestion="partial",
        )

    complete = AnswerEvaluationV2(
        score="good",
        missing_key_points=[],
        evidence="complete",
        follow_up_required=False,
        follow_up_prompt=None,
        mastery_suggestion="stable",
    )
    assert complete.follow_up_prompt is None


def test_session_report_output_contains_structured_mastery_proposal() -> None:
    output = SessionReportOutput(
        title="数据库复习报告",
        markdown="# 数据库复习报告\n",
        mastery_explanation="MVCC 仍需巩固。",
    )

    assert output.markdown.startswith("#")


@pytest.mark.asyncio
async def test_question_generation_uses_an_isolated_role_thread() -> None:
    batch = QuestionCandidateBatch(
        candidates=[
            QuestionCandidate(
                title="MVCC",
                question_text="什么是 MVCC？",
                reference_answer="多版本并发控制。",
                topics=["database"],
                difficulty="medium",
                key_points=["版本链"],
                follow_ups=[],
                source_refs=["source-1"],
                correction_note="结构化原题",
            )
        ]
    )
    runnable = RecordingAgent({"structured_response": batch})
    agent = QuestionCurationAgent(runnable)

    result = await agent.generate(
        source_excerpts=("source-1: MVCC notes",),
        similar_questions=(),
        rewrite_feedback=None,
        context=_context(),
        config={"configurable": {"thread_id": "s1"}},
    )

    assert result == batch
    assert runnable.calls[0][1]["configurable"] == {
        "thread_id": "s1:question_generation"
    }
    assert runnable.calls[0][2] == _context()


@pytest.mark.asyncio
async def test_question_curation_graph_returns_only_structured_candidates() -> None:
    batch = QuestionCandidateBatch(
        candidates=[
            QuestionCandidate(
                title="MVCC",
                question_text="什么是 MVCC？",
                reference_answer="多版本并发控制。",
                topics=["database"],
                difficulty="medium",
                key_points=["版本链"],
                follow_ups=[],
                source_refs=["source-1"],
                correction_note="结构化原题",
            )
        ]
    )
    agent = QuestionCurationAgent(RecordingAgent({"structured_response": batch}))
    graph = create_question_curation_graph(agent)

    result = await graph.ainvoke(
        {
            "source_excerpts": ["source-1: MVCC notes"],
            "similar_questions": [],
            "rewrite_feedback": None,
        },
        context=_context(),
    )

    assert result["candidates"] == batch.model_dump()["candidates"]
    assert "source_excerpts" in result
