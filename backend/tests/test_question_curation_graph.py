import pytest
from pydantic import ValidationError
from pathlib import Path

from app.agents.context import AgentContext
from app.agents.question_curation import QuestionCurationAgent
from app.agents.question_curation_contracts import (
    QuestionCandidate,
    QuestionCandidateBatch,
)
from app.agents.review_round_contracts import (
    ReviewSessionReportOutput,
    RoundAnswerEvaluation,
)
from app.graphs.question_curation import create_question_curation_graph


class RecordingAgent:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def ainvoke(self, input, config=None, *, context=None):
        self.calls.append((input, config, context))
        return self.result


class SequencedAgent(RecordingAgent):
    def __init__(self, results):
        super().__init__(None)
        self.results = iter(results)

    async def ainvoke(self, input, config=None, *, context=None):
        self.calls.append((input, config, context))
        return {"structured_response": next(self.results)}


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


def test_round_answer_evaluation_exposes_evidence_not_hidden_reasoning() -> None:
    evaluation = RoundAnswerEvaluation(
        score="partial",
        missing_key_points=["m_ids"],
        evidence="回答说明了事务 ID 上下界。",
        follow_up_required=True,
        follow_up_prompt="活跃事务中的版本是否可见？",
        mastery_suggestion="partial",
    )

    assert "reasoning" not in evaluation.model_dump()
    with pytest.raises(ValidationError):
        RoundAnswerEvaluation.model_validate(
            {**evaluation.model_dump(), "chain_of_thought": "secret"}
        )


def test_follow_up_prompt_is_required_only_when_follow_up_is_requested() -> None:
    with pytest.raises(ValidationError, match="follow_up_prompt"):
        RoundAnswerEvaluation(
            score="partial",
            missing_key_points=["m_ids"],
            evidence="partial",
            follow_up_required=True,
            follow_up_prompt=None,
            mastery_suggestion="partial",
        )

    complete = RoundAnswerEvaluation(
        score="good",
        missing_key_points=[],
        evidence="complete",
        follow_up_required=False,
        follow_up_prompt=None,
        mastery_suggestion="stable",
    )
    assert complete.follow_up_prompt is None


def test_session_report_output_contains_structured_mastery_proposal() -> None:
    output = ReviewSessionReportOutput(
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
async def test_numbered_question_sources_are_chunked_and_deduplicated() -> None:
    def candidate(number: int, text: str) -> QuestionCandidate:
        return QuestionCandidate(
            title=f"题目 {number}",
            question_text=text,
            reference_answer=f"答案 {number}",
            topics=["systems"],
            difficulty="medium",
            key_points=[f"关键点 {number}"],
            follow_ups=[],
            source_refs=["source-1"],
            correction_note="结构化原题",
        )

    first = QuestionCandidateBatch(
        candidates=[candidate(number, f"问题 {number}？") for number in range(1, 7)]
    )
    second = QuestionCandidateBatch(
        candidates=[candidate(6, "问题 6？"), *[candidate(number, f"问题 {number}？") for number in range(7, 13)]]
    )
    runnable = SequencedAgent([first, second])
    agent = QuestionCurationAgent(runnable)
    source = "source-1:questions.md\n" + "\n".join(
        f"{number}. 问题 {number}？答：答案 {number}。"
        for number in range(1, 13)
    )

    result = await agent.generate(
        source_excerpts=(source,),
        similar_questions=(),
        rewrite_feedback=None,
        context=_context(),
        config={"configurable": {"thread_id": "s1"}},
    )

    assert len(runnable.calls) == 2
    assert "1. 问题 1" in runnable.calls[0][0]["messages"][0].content
    assert "7. 问题 7" not in runnable.calls[0][0]["messages"][0].content
    assert "7. 问题 7" in runnable.calls[1][0]["messages"][0].content
    assert len(result.candidates) == 12


@pytest.mark.asyncio
async def test_duplicate_candidates_merge_source_evidence_instead_of_dropping_it() -> None:
    def duplicate(source_ref: str) -> QuestionCandidate:
        return QuestionCandidate(
            title="缓存穿透",
            question_text="缓存穿透是什么？",
            reference_answer="查询不存在的数据导致缓存无法命中。",
            topics=["cache"],
            difficulty="medium",
            key_points=["空值缓存"],
            follow_ups=[],
            source_refs=[source_ref],
            correction_note="补齐治理方式",
        )

    runnable = SequencedAgent(
        [
            QuestionCandidateBatch(candidates=[duplicate("source-1#part-1")]),
            QuestionCandidateBatch(candidates=[duplicate("source-2#part-2")]),
        ]
    )
    agent = QuestionCurationAgent(runnable)
    source = "source-1:questions.md\n" + "\n".join(
        f"{number}. 问题 {number}？答：答案 {number}。"
        for number in range(1, 13)
    )

    result = await agent.generate(
        source_excerpts=(source,),
        similar_questions=(),
        rewrite_feedback=None,
        context=_context(),
        config={"configurable": {"thread_id": "s1"}},
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].source_refs == [
        "source-1#part-1",
        "source-2#part-2",
    ]


@pytest.mark.asyncio
async def test_high_confidence_paraphrases_merge_but_keep_all_evidence() -> None:
    def candidate(text: str, source_ref: str, key_point: str) -> QuestionCandidate:
        return QuestionCandidate(
            title="缓存穿透",
            question_text=text,
            reference_answer="查询不存在的数据导致缓存无法命中。",
            topics=["cache"],
            difficulty="medium",
            key_points=[key_point],
            follow_ups=[],
            source_refs=[source_ref],
            correction_note="补齐治理方式",
        )

    runnable = SequencedAgent([
        QuestionCandidateBatch(candidates=[candidate("什么是缓存穿透？", "source-1", "空值缓存")]),
        QuestionCandidateBatch(candidates=[candidate("请解释一下缓存穿透是什么", "source-2", "布隆过滤器")]),
    ])
    agent = QuestionCurationAgent(runnable)
    source = "source-1:questions.md\n" + "\n".join(
        f"{number}. 问题 {number}？答：答案 {number}。" for number in range(1, 13)
    )

    result = await agent.generate(
        source_excerpts=(source,),
        similar_questions=(),
        rewrite_feedback=None,
        context=_context(),
        config={"configurable": {"thread_id": "s1"}},
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].source_refs == ["source-1", "source-2"]
    assert result.candidates[0].key_points == ["空值缓存", "布隆过滤器"]


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
